import os
import json
from flask import Flask, request, redirect, render_template, send_from_directory
from google.cloud import storage
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = 'saipranayassignment2'

bucket_name = 'cnd2geminiai-images-buckets'
storage_client = storage.Client()
genai.configure(api_key='AIzaSyABY4oVvH7JrxpA70rv0vhlWLJ5WjAVjoI')

logging.basicConfig(level=logging.DEBUG)

def upload_to_gemini(path, mime_type=None):
    file = genai.upload_file(path, mime_type=mime_type)
    return file

def generative_ai(image_file):
    model = genai.GenerativeModel(model_name="gemini-1.5-flash")
    files = upload_to_gemini(image_file, mime_type="image/jpeg")

    chat_session = model.start_chat(
        history=[{"role": "user", "parts": [files, "generate title and description for the image and return the response in json format"]}]
    )

    response = chat_session.send_message("INSERT_INPUT_HERE")
    logging.debug(f"Gemini API Response: {response.text}")
    return response.text

def upload_to_gcs(bucket_name, source_file, destination_blob_name):
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'image' not in request.files:
        return "No file uploaded", 400

    file = request.files['image']
    if file.filename == '':
        return "No file selected", 400

    # Save the file to a temporary location
    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
        file.save(temp_file.name)
        temp_path = temp_file.name

    try:
        response = generative_ai(temp_path)
        try:
            response = json.loads(response)
            title = response.get('title', 'No title present')
            description = response.get('description', 'No description present')
        except json.JSONDecodeError:
            logging.error("Invalid JSON response from Gemini API")
            return "Invalid response from Gemini API", 500
        except Exception as e:
            logging.error(f"Error processing Gemini API response: {e}")
            return "Error processing response", 500

        json_data = {
            "title": title,
            "description": description
        }

        json_filename = os.path.splitext(file.filename)[0] + '.json'
        json_path = os.path.join('/tmp', json_filename)
        with open(json_path, 'w') as json_file:
            json.dump(json_data, json_file)

        upload_to_gcs(bucket_name, temp_path, file.filename)
        upload_to_gcs(bucket_name, json_path, json_filename)

    finally:
        # Clean up the temporary files
        os.remove(temp_path)
        if os.path.exists(json_path):
            os.remove(json_path)

    return redirect('/')

if __name__ == '__main__':
    app.run(port=8080, debug=True)
