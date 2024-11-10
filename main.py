from flask import Flask, request, jsonify
import requests
import mimetypes
import os
from docx import Document
import fitz  # PyMuPDF
import html2text
from io import BytesIO
from PIL import Image
import pytesseract
import tempfile

app = Flask(__name__)

# Helper function to download the document
def download_document(url):
    response = requests.get(url)
    if response.status_code == 200:
        file_name = url.split('/')[-1]
        file_data = BytesIO(response.content)
        return file_name, file_data
    else:
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
        return "Unsupported file format"

@app.route('/submit-resumes', methods=['POST'])
def submit_resumes():
    data = request.json
    
    # Extracting fields from the request body
    company_name = data.get("companyName")
    posting_id = data.get("postingId")
    source = data.get("source")
    resume_url = data.get("resumeUrl")
    batch_id = data.get("batchId")
    
    # Basic validation for required fields
    if not all([company_name, posting_id, source, resume_url, batch_id]):
        return jsonify({"error": "Missing required fields in the request body"}), 400

    try:
        # Step 1: Download the document
        file_name, file_data = download_document(resume_url)

        # Step 2: Convert document to text
        text_content = convert_to_text(file_name, file_data)

        # Step 3: Return the result as JSON
        return jsonify({
            "companyName": company_name,
            "postingId": posting_id,
            "source": source,
            "batchId": batch_id,
            "resumeText": text_content
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
