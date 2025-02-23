import os
import json
from flask import Flask, request, send_from_directory, render_template, redirect
from google.cloud import storage
import google.generativeai as genai

app = Flask(__name__)

# Google Cloud Storage Config
BUCKET_NAME = 'cnd2geminiai-images-buckets'
storage_client = storage.Client()
os.makedirs('files', exist_ok=True)

# Gemini AI Config
genai.configure(api_key='AIzaSyABY4oVvH7JrxpA70rv0vhlWLJ5WjAVjoI')

def upload_to_gemini(path, mime_type=None):
    file = genai.upload_file(path, mime_type=mime_type)
    print(f"Uploaded file '{file.display_name}' as: {file.uri}")
    return file

def generative_ai(image_file):
    """Generate image title & description using Gemini AI"""
    model = genai.GenerativeModel(model_name="gemini-1.5-flash")
    files = upload_to_gemini(image_file, mime_type="image/jpeg")

    chat_session = model.start_chat(
        history=[{"role": "user", "parts": [files, "Generate a title and description for this image and return as JSON."]}]
    )
    
    response = chat_session.send_message("Generate title and description.")
    return response.text

def upload_to_gcs(bucket_name, source_file, destination_blob):
    """Uploads a file to Google Cloud Storage"""
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob)
    blob.upload_from_file(source_file)

def list_files(bucket_name):
    """List all files in the GCS bucket"""
    bucket = storage_client.bucket(bucket_name)
    blobs = bucket.list_blobs()
    return [blob.name for blob in blobs]

@app.route('/')
def index():
    """Main page displaying uploaded images"""
    image_files = list_files(BUCKET_NAME)
    return render_template('index.html', images=image_files)

@app.route('/upload', methods=['POST'])
def upload():
    """Handles image upload, sends to Gemini, and stores result in GCS"""
    file = request.files['image']
    filename = file.filename
    local_path = os.path.join('files', filename)
    file.save(local_path)

    response = generative_ai(local_path)

    try:
        response = response.replace('json', '').replace('```', '').strip()
        response = json.loads(response)
        title = response.get('title', 'No title present')
        description = response.get('description', 'No description present')
    except:
        return "Error processing AI response."

    # Save text file with generated title & description
    text_path = os.path.splitext(local_path)[0] + '.txt'
    with open(text_path, 'w') as txt:
        txt.write(f"{title}\n{description}")

    # Upload image & description to GCS
    file.seek(0)
    upload_to_gcs(BUCKET_NAME, file, filename)
    with open(text_path, 'rb') as txt_file:
        upload_to_gcs(BUCKET_NAME, txt_file, os.path.basename(text_path))

    return redirect('/')

@app.route('/files/<filename>')
def get_file(filename):
    """Serves files from local storage"""
    return send_from_directory('files', filename)

@app.route('/view/<filename>')
def view_file(filename):
    """Displays image and its description"""
    text_filename = os.path.splitext(filename)[0] + '.txt'
    title, description = "No title", "No description"

    text_path = os.path.join('files', text_filename)
    if os.path.exists(text_path):
        with open(text_path, 'r') as txt:
            lines = txt.readlines()
            title = lines[0].strip() if lines else "No title"
            description = '\n'.join(lines[1:]).strip() if len(lines) > 1 else "No description"

    return render_template('view.html', filename=filename, title=title, description=description)

if __name__ == '__main__':
    app.run(port=8080, debug=True)
