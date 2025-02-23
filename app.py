import os
import json
import google.auth
from flask import Flask, request, render_template, redirect, url_for
from google.cloud import storage
from werkzeug.utils import secure_filename
import requests

app = Flask(__name__)

# Google Cloud Storage setup
CLOUD_STORAGE_BUCKET = "cnd2geminiai-images-buckets"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent"
GEMINI_API_KEY = "AIzaSyABY4oVvH7JrxpA70rv0vhlWLJ5WjAVjoI"  # Replace with your actual API key

# Initialize GCS client
gcs = storage.Client()
bucket = gcs.bucket(CLOUD_STORAGE_BUCKET)

def upload_to_gcs(file, filename):
    """Uploads a file to Google Cloud Storage and returns its public URL."""
    blob = bucket.blob(filename)
    blob.upload_from_file(file, content_type=file.content_type)
    return f"https://storage.googleapis.com/{CLOUD_STORAGE_BUCKET}/{filename}"

def generate_caption_description(image_url):
    """Calls the Gemini API to generate a caption/description for an image."""
    payload = {
        "contents": [
            {
                "parts": [
                    {"data": {"url": image_url}}
                ]
            }
        ]
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(f"{GEMINI_API_URL}?key={GEMINI_API_KEY}", json=payload, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        return {"error": f"API request failed with status code {response.status_code}"}

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    """Handles file upload and sends the image to Gemini for processing."""
    if request.method == 'POST':
        if 'file' not in request.files:
            return "No file part"
        file = request.files['file']
        if file.filename == '':
            return "No selected file"
        
        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in ['.jpg', '.jpeg', '.png']:
            return "Invalid file format"

        # Upload image to GCS
        image_url = upload_to_gcs(file, filename)
        
        # Generate caption and description
        gemini_response = generate_caption_description(image_url)
        
        # Save JSON response in GCS
        json_filename = f"{os.path.splitext(filename)[0]}.json"
        blob = bucket.blob(json_filename)
        blob.upload_from_string(json.dumps(gemini_response), content_type='application/json')
        
        return redirect(url_for('upload_file'))
    
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
