import os
import json
import logging
import datetime
from flask import Flask, request, redirect, render_template, url_for, jsonify
from google.cloud import storage, secretmanager
import google.generativeai as genai

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Configuration
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "image-upload-gcp-project")
SECRET_NAME = os.getenv("GCS_SECRET_NAME", "GCS_SERVICE_ACCOUNT_KEY")
GEMINI_SECRET_NAME = os.getenv("GEMINI_SECRET_NAME", "GEMINI_API_KEY")
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

# Validate required environment variables
if not BUCKET_NAME:
    logger.error("GCS_BUCKET_NAME environment variable is not set")
    raise RuntimeError("GCS_BUCKET_NAME environment variable is required")

# Initialize clients with retry logic
def initialize_clients():
    """Initialize GCP clients with proper error handling."""
    try:
        # Get GCS credentials
        client = secretmanager.SecretManagerServiceClient()
        
        # Fetch GCS Service Account Key
        secret_path = f"projects/{PROJECT_ID}/secrets/{SECRET_NAME}/versions/latest"
        response = client.access_secret_version(request={"name": secret_path})
        secret_json = response.payload.data.decode("UTF-8")
        
        # Save to temporary file
        temp_cred_path = "/tmp/gcs_service_account.json"
        with open(temp_cred_path, "w") as f:
            f.write(secret_json)
        
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_cred_path
        
        # Initialize Storage Client
        storage_client = storage.Client()
        
        # Verify bucket exists
        bucket = storage_client.bucket(BUCKET_NAME)
        if not bucket.exists():
            logger.error(f"Bucket {BUCKET_NAME} does not exist")
            raise RuntimeError(f"Bucket {BUCKET_NAME} not found")
        
        # Configure Gemini AI
        gemini_secret_path = f"projects/{PROJECT_ID}/secrets/{GEMINI_SECRET_NAME}/versions/latest"
        gemini_response = client.access_secret_version(request={"name": gemini_secret_path})
        gemini_api_key = gemini_response.payload.data.decode("UTF-8")
        genai.configure(api_key=gemini_api_key)
        
        logger.info("All clients initialized successfully")
        return storage_client
        
    except Exception as e:
        logger.error(f"Failed to initialize clients: {e}")
        raise

# Initialize clients at startup
try:
    storage_client = initialize_clients()
except Exception as e:
    logger.error(f"Application startup failed: {e}")
    raise

def upload_to_gemini(path, mime_type="image/jpeg"):
    """Uploads image to Gemini AI for processing."""
    try:
        file = genai.upload_file(path, mime_type=mime_type)
        return file
    except Exception as e:
        logger.error(f"Failed to upload image to Gemini: {e}")
        return None

def generative_ai(image_file):
    """Sends image to Gemini AI and retrieves title & description."""
    try:
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        files = upload_to_gemini(image_file)
        
        if not files:
            return {"title": "Upload Error", "description": "Failed to upload image to Gemini AI."}

        chat_session = model.start_chat(
            history=[{"role": "user", "parts": [files, "Generate title and description for the image and return as JSON"]}]
        )

        response = chat_session.send_message("Generate title and description in JSON format")
        logger.debug(f"Gemini API Response: {response.text}")

        response_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(response_text)

    except json.JSONDecodeError:
        logger.error("Invalid JSON response from Gemini AI")
        return {"title": "Invalid Response", "description": "Gemini AI returned an invalid response."}
    except Exception as e:
        logger.error(f"Error in generative AI: {e}")
        return {"title": "Error", "description": "An error occurred while processing the image."}

def upload_to_gcs(bucket_name, source_file, destination_blob_name):
    """Uploads a file to Google Cloud Storage."""
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(source_file)
        logger.info(f"Uploaded {destination_blob_name} to GCS successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to upload {source_file} to GCS: {e}")
        return False

def list_uploaded_images(bucket_name):
    """Lists all images in the GCS bucket."""
    try:
        bucket = storage_client.bucket(bucket_name)
        blobs = bucket.list_blobs()
        return [blob.name for blob in blobs if blob.name.endswith(('.jpg', '.jpeg'))]
    except Exception as e:
        logger.error(f"Failed to list images in GCS: {e}")
        return []

def generate_temporary_url(bucket_name, blob_name, expiration=3600):
    """Generates a signed URL to access private GCS images."""
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        if not blob.exists(storage_client):
            logger.error(f"File {blob_name} not found in GCS.")
            return None

        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(seconds=expiration),
            method="GET"
        )
        return url
    except Exception as e:
        logger.error(f"Failed to generate signed URL for {blob_name}: {e}")
        return None

@app.route('/health')
def health_check():
    """Endpoint for health checks and version identification"""
    return jsonify({
        "status": "healthy",
        "version": os.getenv("APP_VERSION", "1.0.0"),
        "deployment_color": os.getenv("DEPLOYMENT_COLOR", "none")
    })

@app.context_processor
def inject_deployment_info():
    """Inject deployment color into all templates"""
    return {
        "deployment_color": os.getenv("DEPLOYMENT_COLOR", "none"),
        "app_version": os.getenv("APP_VERSION", "1.0.0")
    }

@app.before_request
def check_services():
    """Verify required services are available before processing requests."""
    try:
        # Simple check to verify storage client is working
        storage_client.bucket(BUCKET_NAME).exists()
    except Exception as e:
        logger.error(f"Service check failed: {e}")
        return jsonify({"error": "Service unavailable"}), 503

@app.route('/')
def index():
    images = list_uploaded_images(BUCKET_NAME)
    return render_template('index.html', 
                        images=images,
                        deployment_color=os.getenv("DEPLOYMENT_COLOR", "none"))

@app.route('/upload', methods=['POST'])
def upload():
    """Handles image upload, AI processing, and JSON metadata storage."""
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
        if not upload_to_gcs(BUCKET_NAME, temp_path, file.filename) or not upload_to_gcs(BUCKET_NAME, json_path, json_filename):
            return "File upload failed", 500

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
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
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(json_filename)

    if not blob.exists():
        logger.error(f"Metadata file {json_filename} not found in bucket.")
        return "Metadata not found", 404

    try:
        json_data = json.loads(blob.download_as_text())
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in metadata file: {json_filename}")
        return "Invalid metadata format", 500

    title = json_data.get('title', 'No title available')
    description = json_data.get('description', 'No description available')

    # Generate a temporary URL for secure access
    temp_url = generate_temporary_url(BUCKET_NAME, filename)
    logger.debug(f"Generated Signed URL: {temp_url}")

    if not temp_url:
        return "Error generating image URL", 500

    return render_template('view.html', image_url=temp_url, title=title, description=description)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
