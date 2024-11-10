from flask import Flask, request, jsonify
import requests
import mimetypes
import os
import logging
from docx import Document
import fitz  # PyMuPDF
import html2text
from io import BytesIO
from PIL import Image
import pytesseract
import tempfile

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Dummy endpoint for warming up the container
@app.route('/dummy', methods=['GET'])
def dummy():
    logging.info("Dummy endpoint called for warm-up.")
    return jsonify({"message": "Container is warmed up and ready!"}), 200

# Helper function to download the document
def download_document(url):
    response = requests.get(url)
    if response.status_code == 200:
        file_name = url.split('/')[-1]
        file_data = BytesIO(response.content)
        return file_name, file_data
    else:
        logging.error(f"Failed to download document from {url}")
        raise Exception("Could not download file")

# Helper functions to handle different document conversions
def convert_pdf_to_text(file_data):
    text = ""
    with fitz.open(stream=file_data, filetype="pdf") as pdf:
        for page in pdf:
            text += page.get_text()
    return text

def convert_docx_to_text(file_data):
    doc = Document(file_data)
    return "\n".join([paragraph.text for paragraph in doc.paragraphs])

def convert_html_to_text(file_data):
    html_content = file_data.read().decode('utf-8')
    return html2text.html2text(html_content)

def convert_image_to_text(file_data):
    image = Image.open(file_data)
    return pytesseract.image_to_string(image)

# Main function to detect file type and convert to text
def convert_to_text(file_name, file_data):
    file_extension = os.path.splitext(file_name)[1].lower()

    if file_extension == ".pdf":
        return convert_pdf_to_text(file_data)
    elif file_extension == ".docx":
        return convert_docx_to_text(file_data)
    elif file_extension == ".html":
        return convert_html_to_text(file_data)
    elif file_extension == ".txt":
        return file_data.read().decode('utf-8')
    elif file_extension in [".jpg", ".jpeg", ".png", ".bmp", ".tiff"]:
        return convert_image_to_text(file_data)
    else:
        logging.warning(f"Unsupported file format: {file_extension}")
        return "Unsupported file format"

# Function to send the processed data to an external endpoint
def send_to_endpoint(endpoint_url, data):
    logging.info(f"Sending data to endpoint: {endpoint_url}")
    response = requests.post(endpoint_url, json=data)
    response.raise_for_status()  # Raise an error for bad responses
    logging.info("Data successfully sent to endpoint")
    return response.json()

@app.route('/submit-resumes', methods=['POST'])
def submit_resumes():
    data = request.json

    # Extracting fields from the request body
    company_name = data.get("companyName")
    posting_id = data.get("postingId")
    source = data.get("source")
    resume_url = data.get("resumeUrl")
    batch_id = data.get("batchId")
    sheet_name = data.get("sheetName")

    # Basic validation for required fields
    if not all([company_name, posting_id, source, resume_url, batch_id, sheet_name]):
        logging.error("Missing required fields in the request body")
        return jsonify({"error": "Missing required fields in the request body"}), 400

    try:
        # Step 1: Download the document
        file_name, file_data = download_document(resume_url)
        logging.info(f"Downloaded document: {file_name}")

        # Step 2: Convert document to text
        text_content = convert_to_text(file_name, file_data)
        print(text_content)

        # Step 3: Prepare the payload for the external endpoint
        payload = {
            "posting_id": posting_id,
            "sheet_name": sheet_name,
            "file_name": resume_url,
            "file_id": resume_url,
            "source": source,
            "resume_content": text_content,  # Add extracted text content here
            "parsed_resume": text_content    # Duplicate text content if needed
        }

        # Step 4: Get the endpoint URL from the environment, with a default fallback
        endpoint_url = os.getenv("EXTERNAL_ENDPOINT_URL", "https://hook.us1.make.com/khry5zdtsi56dgu0m2y9vtrh2u0y6e5x")
        logging.info(f"Using endpoint URL: {endpoint_url}")

        # Step 5: Send the payload to the external endpoint
        result = send_to_endpoint(endpoint_url, payload)

        # Step 6: Return the result from the external endpoint
        return jsonify({
            "companyName": company_name,
            "postingId": posting_id,
            "source": source,
            "batchId": batch_id,
            "resumeText": text_content,
            "externalResponse": result
        })
    except Exception as e:
        logging.error(f"Error processing resume: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
