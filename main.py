import os
import json
import logging
import datetime
from flask import Flask, request, redirect, render_template, url_for
from google.cloud import storage, secretmanager
import google.generativeai as genai

# Flask App Initialization
app = Flask(__name__)

bucket_name = os.getenv("GCS_BUCKET_NAME") 
PROJECT_ID = "image-upload-gcp-project"
SECRET_NAME = "GCS_SERVICE_ACCOUNT_KEY"

# Configure Logging
logging.basicConfig(level=logging.DEBUG)

def get_gcs_credentials():
    """Fetches Service Account JSON from Secret Manager and sets environment variable."""
    client = secretmanager.SecretManagerServiceClient()
    secret_path = f"projects/{PROJECT_ID}/secrets/{SECRET_NAME}/versions/latest"
    
    response = client.access_secret_version(request={"name": secret_path})
    secret_json = response.payload.data.decode("UTF-8")

    # Store the credentials in a temporary file
    temp_cred_path = "/tmp/gcs_service_account.json"
    with open(temp_cred_path, "w") as f:
        f.write(secret_json)

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_cred_path
    return temp_cred_path

# Initialize Google Cloud Clients
def initialize_clients():
    get_gcs_credentials()
    return storage.Client()

storage_client = initialize_clients()

def upload_to_gemini(path, mime_type="image/jpeg"):
    """Uploads image to Gemini AI for processing."""
    file = genai.upload_file(path, mime_type=mime_type)
    return file

def generative_ai(image_file):
    """Sends image to Gemini AI and retrieves title & description."""
    model = genai.GenerativeModel(model_name="gemini-1.5-flash")
    files = upload_to_gemini(image_file)

    chat_session = model.start_chat(
        history=[{"role": "user", "parts": [files, "Generate title and description for the image and return as JSON"]}]
    )
    
    response = chat_session.send_message("Generate title and description in JSON format")
    logging.debug(f"Gemini API Response: {response.text}")

    try:
        response_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(response_text)
    except json.JSONDecodeError:
        logging.error("Invalid JSON response from Gemini API")
        return {"title": "No title", "description": "No description"}

def upload_to_gcs(bucket_name, source_file, destination_blob_name):
    """Uploads a file to Google Cloud Storage."""
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file)

def list_uploaded_images(bucket_name):
    """Lists all images in the GCS bucket."""
    bucket = storage_client.bucket(bucket_name)
    blobs = bucket.list_blobs()
    return [blob.name for blob in blobs if blob.name.endswith(('.jpg', '.jpeg'))]

def generate_temporary_url(bucket_name, blob_name, expiration=3600):
    """Generates a signed URL to access private GCS images."""
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    
    url = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(seconds=expiration),
        method="GET"
    )
    return url

@app.route('/')
def index():
    images = list_uploaded_images(bucket_name)
    return render_template('index.html', images=images)

@app.route('/upload', methods=['POST'])
def upload():
    """Handles image upload, AI processing, and JSON metadata storage."""
    bucket_name = "cnd2geminiai-images-buckets"  # Change as per your bucket
    json_path, temp_path = None, None

    try:
        if 'image' not in request.files:
            return "No file uploaded", 400

        file = request.files['image']
        if file.filename == '':
            return "No file selected", 400

        # Save file temporarily
        temp_path = os.path.join('/tmp', file.filename)
        file.save(temp_path)

        # Generate AI response
        ai_response = generative_ai(temp_path)
        title = ai_response.get('title', 'No title present')
        description = ai_response.get('description', 'No description present')

        # Save metadata as JSON
        json_data = {"title": title, "description": description}
        json_filename = os.path.splitext(file.filename)[0] + '.json'
        json_path = os.path.join('/tmp', json_filename)
        with open(json_path, 'w') as json_file:
            json.dump(json_data, json_file)

        # Upload to GCS
        upload_to_gcs(bucket_name, temp_path, file.filename)
        upload_to_gcs(bucket_name, json_path, json_filename)
    
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return "Internal Server Error", 500
    
    finally:
        # Cleanup temporary files
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        if json_path and os.path.exists(json_path):
            os.remove(json_path)

    return redirect(url_for('view_image', filename=file.filename))

@app.route('/view')
def view_image():
    """Fetches and displays metadata along with signed URL for image."""
    filename = request.args.get('filename')

    if not filename:
        return "No file specified", 400

    json_filename = os.path.splitext(filename)[0] + '.json'
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(json_filename)

    if not blob.exists():
        return "Metadata not found", 404

    json_data = json.loads(blob.download_as_text())
    title = json_data.get('title', 'No title available')
    description = json_data.get('description', 'No description available')

    # Generate a temporary URL for secure access
    temp_url = generate_temporary_url(bucket_name, filename)

    return render_template('view.html', image_url=temp_url, title=title, description=description)

if __name__ == '__main__':
    app.run(port=8080, debug=True)
