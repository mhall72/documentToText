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
import psycopg2
import easyocr

app = Flask(__name__)

microservice_name = "textToDocument"

# Initialize the OCR reader
ocr_reader = easyocr.Reader(['en'])

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DB_CONNECTION_STRING = "user=postgres.tvkwdvwednprjmomudhg password=-P7M2jft9rrR*XU host=aws-0-us-west-1.pooler.supabase.com port=6543 dbname=postgres"

# Function to insert log entry into log_resume_processing table
def insert_log_entry(resume_url, processing_stage, status, error_message=None, microservice_id=microservice_name):
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(DB_CONNECTION_STRING)
        cursor = conn.cursor()
        
        insert_query = """
        INSERT INTO log_resume_processing (resumeUrl, processing_stage, timestamp, status, error_message, microservice_id)
        VALUES (%s, %s, NOW(), %s, %s, %s)
        """
        
        cursor.execute(insert_query, (resume_url, processing_stage, status, error_message, microservice_id))
        conn.commit()
        
    except Exception as e:
        logging.error(f"Failed to insert log entry: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()



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

# Function to perform OCR on an image using EasyOCR
def perform_ocr_on_image(image):
    try:
        text = ocr_reader.readtext(image, detail=0)
        return "\n".join(text)
    except Exception as e:
        logging.error(f"Error during OCR processing: {e}")
        return ""

# Helper functions to handle different document conversions
def convert_pdf_to_text(file_data):
    text = ""
    with fitz.open(stream=file_data, filetype="pdf") as pdf:
        for page in pdf:
            # Attempt text extraction
            page_text = page.get_text()
            if page_text.strip():  # If text is found, add to output
                text += page_text
            else:
                # Perform OCR on page if no text is found
                logging.info("No text found on PDF page, performing OCR.")
                page_image = page.get_pixmap()
                with tempfile.NamedTemporaryFile(suffix=".png") as temp_img_file:
                    page_image.save(temp_img_file.name)
                    text += perform_ocr_on_image(temp_img_file.name)
    return text

# Updated DOCX conversion with OCR fallback
def convert_docx_to_text(file_data):
    doc = Document(file_data)
    text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
    
    if not text.strip():  # If no text, process images with OCR
        logging.info("No text found in DOCX, performing OCR on images.")
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                with tempfile.NamedTemporaryFile(suffix=".png") as temp_img_file:
                    img = Image.open(BytesIO(rel.target_part.blob))
                    img.save(temp_img_file.name)
                    text += perform_ocr_on_image(temp_img_file.name)
    return text

# Updated HTML conversion with OCR fallback
def convert_html_to_text(file_data):
    from bs4 import BeautifulSoup
    import requests
    html_content = file_data.read().decode('utf-8')
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract text from HTML
    text = soup.get_text(separator="\n").strip()
    
    # Perform OCR on images if HTML text is minimal
    if len(text) < 50:  # Adjust threshold as needed
        logging.info("No text or minimal text in HTML, performing OCR on images.")
        for img_tag in soup.find_all("img"):
            img_url = img_tag.get("src")
            if img_url:
                try:
                    img_data = requests.get(img_url).content
                    with tempfile.NamedTemporaryFile(suffix=".png") as temp_img_file:
                        temp_img_file.write(img_data)
                        temp_img_file.flush()
                        text += perform_ocr_on_image(temp_img_file.name)
                except Exception as e:
                    logging.error(f"Error loading image for OCR in HTML: {e}")
    return text

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
        # Log the "Received" stage
        insert_log_entry(resume_url, "Received", "In Progress", microservice_id=microservice_name)

        # Step 1: Download the document
        file_name, file_data = download_document(resume_url)
        logging.info(f"Downloaded document: {file_name}")

        # Step 2: Convert document to text
        text_content = convert_to_text(file_name, file_data)
        logging.info("Document converted to text")

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

        # Log the "Processed" stage as "Success"
        insert_log_entry(resume_url, "Processed", "Success", microservice_id=microservice_name)

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

        # Log the "Processed" stage as "Failure"
        insert_log_entry(resume_url, "Processed", "Failure", str(e), microservice_id=microservice_name)

        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))