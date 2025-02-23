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
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=AIzaSyABY4oVvH7JrxpA70rv0vhlWLJ5WjAVjoI"
GEMINI_API_KEY = "AIzaSyABY4oVvH7JrxpA70rv0vhlWLJ5WjAVjoI"  # Replace with your actual API key

# Initialize GCS client
gcs = storage.Client()
bucket = gcs.bucket(CLOUD_STORAGE_BUCKET)

def upload_to_gcs(file, filename):
    blob = bucket.blob(filename)
    blob.upload_from_file(file)
    return f"https://storage.googleapis.com/{CLOUD_STORAGE_BUCKET}/{filename}"

def generate_caption_description(image_url):
    payload = {"image_url": image_url}
    headers = {"Authorization": f"Bearer {GEMINI_API_KEY}", "Content-Type": "application/json"}
    response = requests.post(GEMINI_API_URL, json=payload, headers=headers)
    return response.json() if response.status_code == 200 else {"error": "API request failed"}

@app.route('/', methods=['GET', 'POST'])
def upload_file():
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
