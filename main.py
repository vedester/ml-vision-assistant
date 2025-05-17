import openai
print(openai.__version__)

"""
AI Vision Assistant - Complete System

This application provides visual analysis capabilities with:
- Image upload and analysis
- Live camera feed processing
- Text-to-speech conversion
- Comprehensive error handling and fallback mechanisms
- Performance monitoring
"""

import atexit
import os
import logging
import base64
import cv2
import time
import json
import threading
import traceback
from io import BytesIO
from datetime import datetime
from flask import Flask, request, jsonify, send_file, Response, render_template_string
from werkzeug.utils import secure_filename
from pyngrok import ngrok, conf, exception
from flask_cors import CORS
import numpy as np

def cleanup():
    logger.info("Shutting down ngrok tunnel")
    ngrok.kill()

atexit.register(cleanup)

# Optional imports with fallback mechanisms
"""from dotenv import load_dotenv
load_dotenv()"""

try:
    from gtts import gTTS
    TEXT_TO_SPEECH_AVAILABLE = True
except ImportError:
    print("gTTS not installed, using fallback text-to-speech")
    TEXT_TO_SPEECH_AVAILABLE = False

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    print("OpenAI SDK not installed, using fallback image analysis")
    OPENAI_AVAILABLE = False

# Initialize Flask app
app = Flask(__name__)
CORS(app)

@app.after_request
def skip_ngrok_warning(response):
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response

# Configuration
#PORT = int(os.getenv("PORT", 5000))
PORT = 5000
NGROK_AUTH_TOKEN = "2xDCX0psN4CfAKv1fmppTmhOLSt_wCgo9bfmdiWxFopNmsyG"

OPENAI_API_KEY = "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"
#NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "2t8ZokKdH3ZT9hPjr7b4YBVQEft_4ub7pQ2gxjNVHzZcRRzhY")
#OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")

# Confirming .env load
print("DEBUG: Checking environment variables after load_dotenv()")
print("DEBUG: NGROK_AUTH_TOKEN =", NGROK_AUTH_TOKEN)
print("DEBUG: OPENAI_API_KEY =", OPENAI_API_KEY)
CAMERA_SOURCE = 0
FRAME_RATE = 2
API_RATE_LIMIT = 10
DEBUG_MODE = False

UPLOAD_FOLDER = "uploads"
AUDIO_FOLDER = "audio"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)
os.makedirs("logs", exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
CAMERA_SOURCE = int(os.getenv("CAMERA_SOURCE", 0))
FRAME_RATE = int(os.getenv("FRAME_RATE", 2))
API_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT", 10))
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"logs/vision_assistant_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize OpenAI
client = openai

if OPENAI_AVAILABLE and OPENAI_API_KEY:
    try:
        openai.api_key = OPENAI_API_KEY

        try:
            models = client.models.list()
            logger.info(f"OpenAI connection successful. Available models detected.")
        except Exception as e:
            logger.error(f"OpenAI models list error: {str(e)}")

    except Exception as e:
        logger.error(f"OpenAI initialization error: {str(e)}")
        client = None
else:
    logger.warning("OpenAI client not available or API key not provided")


camera = None
stream_active = False
stream_url = ""
api_call_timestamps = []
app.ngrok_url = None

# Stats and monitoring
stats = {
    'total_api_calls': 0,
    'successful_api_calls': 0,
    'failed_api_calls': 0,
    'total_processed_frames': 0,
    'total_processed_uploads': 0,
    'last_error': None,
    'api_quota_exceeded': False
}

last_processed = {
    'description': '',
    'audio': None,
    'frame': None,
    'timestamp': 0
}

# Constants
IMAGE_ANALYSIS_PROMPT = """Describe this image in detail including:
- All visible objects and their arrangement
- Colors, textures, and any notable visual features
- The overall scene and context
- Any text that appears in the image
Be thorough but concise in your description."""

# HTML
HTML_INDEX = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>AI Vision Assistant</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f9f9f9;
        }
        h1 {
            color: #2c3e50;
            text-align: center;
            margin-bottom: 30px;
        }
        .container {
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .section {
            margin-bottom: 20px;
            padding: 15px;
            background: #f5f7fa;
            border-left: 4px solid #3498db;
            border-radius: 4px;
        }
        h2 {
            color: #3498db;
            margin-top: 0;
        }
        form {
            margin: 20px 0;
        }
        .form-group {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }
        input, button, select {
            padding: 10px;
            border-radius: 4px;
            border: 1px solid #ddd;
            width: 100%;
            box-sizing: border-box;
        }
        button {
            background: #3498db;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            margin-top: 10px;
        }
        button:hover {
            background: #2980b9;
        }
        .status {
            display: none;
            padding: 10px;
            border-radius: 4px;
            margin: 10px 0;
            font-weight: bold;
        }
        .success {
            background: #d4edda;
            color: #155724;
        }
        .error {
            background: #f8d7da;
            color: #721c24;
        }
        .warning {
            background: #fff3cd;
            color: #856404;
        }
        .spinner {
            border: 4px solid rgba(0, 0, 0, 0.1);
            width: 24px;
            height: 24px;
            border-radius: 50%;
            border-left-color: #3498db;
            animation: spin 1s linear infinite;
            display: inline-block;
            margin-right: 10px;
            vertical-align: middle;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        #audioPlayer {
            width: 100%;
            margin-top: 15px;
            display: none;
        }
        .video-container {
            margin: 20px 0;
            text-align: center;
        }
        #liveFeed {
            width: 100%;
            max-height: 400px;
            background: #000;
            display: none;
        }
        footer {
            text-align: center;
            margin-top: 30px;
            color: #7f8c8d;
            font-size: 0.9em;
        }
        .tabs {
            display: flex;
            margin-bottom: 20px;
            border-bottom: 2px solid #ddd;
        }
        .tab {
            padding: 10px 20px;
            cursor: pointer;
            margin-right: 5px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }
        .tab.active {
            background: #3498db;
            color: white;
            border-bottom: 2px solid #2980b9;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
        .metric {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            padding: 8px;
            background: #f8f9fa;
            border-radius: 4px;
        }
        .metric-value {
            font-weight: bold;
        }
        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8em;
            font-weight: bold;
        }
        .badge-success {
            background: #d4edda;
            color: #155724;
        }
        .badge-danger {
            background: #f8d7da;
            color: #721c24;
        }
        .badge-warning {
            background: #fff3cd;
            color: #856404;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>AI Vision Assistant</h1>

        <div class="tabs">
            <div class="tab active" data-tab="upload-tab">Image Upload</div>
            <div class="tab" data-tab="camera-tab">Camera Feed</div>
            <div class="tab" data-tab="stats-tab">System Status</div>
        </div>

        <div id="upload-tab" class="tab-content active">
            <div class="section">
                <h2>Upload Image</h2>
                <form id="uploadForm" enctype="multipart/form-data">
                    <div class="form-group">
                        <label for="image">Select an image:</label>
                        <input type="file" id="image" name="image" accept="image/*" required>
                    </div>
                    <div class="form-group">
                        <label for="analysis-type">Analysis Type:</label>
                        <select id="analysis-type" name="analysis-type">
                            <option value="detailed">Detailed Description</option>
                            <option value="brief">Brief Summary</option>
                            <option value="objects">Object Detection</option>
                            <option value="text">Text Recognition</option>
                        </select>
                    </div>
                    <button type="submit">Analyze Image</button>
                </form>
                <div id="uploadStatus" class="status"></div>
            </div>

            <div class="section">
                <h2>Results</h2>
                <audio id="audioPlayer" controls></audio>
                <div id="descriptionOutput" style="margin-top: 15px; padding: 10px; background: #f0f0f0; border-radius: 4px;"></div>
            </div>
        </div>

        <div id="camera-tab" class="tab-content">
            <div class="section">
                <h2>Camera Feed</h2>
                <form id="cameraForm">
                    <div class="form-group">
                        <label for="frame-interval">Analysis Interval (seconds):</label>
                        <select id="frame-interval" name="frame-interval">
                            <option value="5">Every 5 seconds</option>
                            <option value="10">Every 10 seconds</option>
                            <option value="30">Every 30 seconds</option>
                            <option value="60">Every minute</option>
                        </select>
                    </div>
                    <button type="button" id="startCamera">Start Camera</button>
                    <button type="button" id="stopCamera" disabled>Stop Camera</button>
                    <button type="button" id="captureFrame">Capture & Analyze Frame</button>
                </form>
                <div id="cameraStatus" class="status"></div>
                <div class="video-container">
                    <img id="liveFeed" src="" alt="Live Camera Feed">
                </div>
            </div>

            <div class="section">
                <h2>Live Camera Results</h2>
                <audio id="cameraAudioPlayer" controls></audio>
                <div id="cameraDescriptionOutput" style="margin-top: 15px; padding: 10px; background: #f0f0f0; border-radius: 4px;"></div>
            </div>
        </div>

        <div id="stats-tab" class="tab-content">
            <div class="section">
                <h2>System Status</h2>
                <div class="metric">
                    <span class="metric-label">Server Status:</span>
                    <span id="serverStatus" class="metric-value">Checking...</span>
                </div>
                <div class="metric">
                    <span class="metric-label">OpenAI Connection:</span>
                    <span id="openaiStatus" class="metric-value">Checking...</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Camera Status:</span>
                    <span id="cameraStatusIndicator" class="metric-value">Inactive</span>
                </div>
                <div class="metric">
                    <span class="metric-label">API Quota Status:</span>
                    <span id="apiQuotaStatus" class="metric-value">Checking...</span>
                </div>
            </div>

            <div class="section">
                <h2>Usage Statistics</h2>
                <div class="metric">
                    <span class="metric-label">API Calls (Success/Total):</span>
                    <span id="apiCallStats" class="metric-value">0/0</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Processed Frames:</span>
                    <span id="processedFrames" class="metric-value">0</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Processed Uploads:</span>
                    <span id="processedUploads" class="metric-value">0</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Last Error:</span>
                    <span id="lastError" class="metric-value">None</span>
                </div>
            </div>

            <div class="section">
                <h2>Application Info</h2>
                <div class="metric">
                    <span class="metric-label">Public URL:</span>
                    <span id="publicUrlField" class="metric-value">Not available</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Application Version:</span>
                    <span class="metric-value">1.0.0</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Mode:</span>
                    <span id="appMode" class="metric-value">Standard</span>
                </div>
            </div>
        </div>
    </div>

    <footer>
        <p>AI Vision Assistant © 2025</p>
    </footer>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Set up tabs
            setupTabs();

            // System health check
            checkSystemStatus();

            // Set up form event listeners
            setupImageUpload();
            setupCameraControls();

            // Periodically refresh stats
            setInterval(updateStats, 10000);
        });

        function setupTabs() {
            const tabs = document.querySelectorAll('.tab');
            const tabContents = document.querySelectorAll('.tab-content');

            tabs.forEach(tab => {
                tab.addEventListener('click', function() {
                    // Remove active class from all tabs and contents
                    tabs.forEach(t => t.classList.remove('active'));
                    tabContents.forEach(c => c.classList.remove('active'));

                    // Add active class to current tab and content
                    this.classList.add('active');
                    document.getElementById(this.dataset.tab).classList.add('active');
                });
            });
        }

        function checkSystemStatus() {
            fetch('/health')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('serverStatus').textContent = "Online";
                    document.getElementById('serverStatus').classList.add('badge', 'badge-success');

                    if (data.openai_ready) {
                        document.getElementById('openaiStatus').textContent = "Connected";
                        document.getElementById('openaiStatus').classList.add('badge', 'badge-success');
                    } else {
                        document.getElementById('openaiStatus').textContent = "Disconnected (Using Fallback)";
                        document.getElementById('openaiStatus').classList.add('badge', 'badge-warning');
                    }

                    if (data.quota_exceeded) {
                        document.getElementById('apiQuotaStatus').textContent = "Quota Exceeded (Using Fallback)";
                        document.getElementById('apiQuotaStatus').classList.add('badge', 'badge-warning');
                    } else {
                        document.getElementById('apiQuotaStatus').textContent = "Available";
                        document.getElementById('apiQuotaStatus').classList.add('badge', 'badge-success');
                    }

                    if (data.public_url) {
                        document.getElementById('publicUrlField').textContent = data.public_url;
                        document.getElementById('publicUrlField').innerHTML = `<a href="${data.public_url}" target="_blank">${data.public_url}</a>`;
                    }

                    document.getElementById('appMode').textContent = data.debug_mode ? "Debug" : "Standard";
                })
                .catch(error => {
                    document.getElementById('serverStatus').textContent = "Error";
                    document.getElementById('serverStatus').classList.add('badge', 'badge-danger');
                    document.getElementById('openaiStatus').textContent = "Unknown";
                    document.getElementById('openaiStatus').classList.add('badge', 'badge-danger');
                    console.error('System status check failed:', error);
                });
        }

        function updateStats() {
            fetch('/api/stats')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('apiCallStats').textContent = `${data.successful_api_calls}/${data.total_api_calls}`;
                    document.getElementById('processedFrames').textContent = data.total_processed_frames;
                    document.getElementById('processedUploads').textContent = data.total_processed_uploads;

                    if (data.last_error) {
                        document.getElementById('lastError').textContent = data.last_error;
                        document.getElementById('lastError').classList.add('badge', 'badge-danger');
                    } else {
                        document.getElementById('lastError').textContent = "None";
                    }

                    // Update API quota status
                    if (data.api_quota_exceeded) {
                        document.getElementById('apiQuotaStatus').textContent = "Quota Exceeded (Using Fallback)";
                        document.getElementById('apiQuotaStatus').classList.add('badge', 'badge-warning');
                    } else {
                        document.getElementById('apiQuotaStatus').textContent = "Available";
                        document.getElementById('apiQuotaStatus').classList.add('badge', 'badge-success');
                    }
                })
                .catch(error => console.error('Stats update failed:', error));
        }

        function setupImageUpload() {
            document.getElementById('uploadForm').addEventListener('submit', function(e) {
                e.preventDefault();
                const statusDiv = document.getElementById('uploadStatus');
                const imageFile = document.getElementById('image').files[0];
                const analysisType = document.getElementById('analysis-type').value;

                // Validate file selection
                if (!imageFile) {
                    statusDiv.textContent = 'Please select an image file';
                    statusDiv.className = 'status error';
                    statusDiv.style.display = 'block';
                    return;
                }

                // Show processing status
                statusDiv.innerHTML = '<div class="spinner"></div> Processing image...';
                statusDiv.className = 'status';
                statusDiv.style.display = 'block';

                const formData = new FormData();
                formData.append('image', imageFile);
                formData.append('analysis_type', analysisType);

                fetch('/upload', {
                    method: 'POST',
                    body: formData
                })
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Upload failed');
                    }
                    return response.blob();
                })
                .then(blob => {
                    statusDiv.innerHTML = 'Analysis complete!';
                    statusDiv.className = 'status success';

                    const audioURL = URL.createObjectURL(blob);
                    const audioPlayer = document.getElementById('audioPlayer');
                    audioPlayer.src = audioURL;
                    audioPlayer.style.display = 'block';

                    // Get the description text
                    return fetch('/api/results');
                })
                .then(response => response.json())
                .then(data => {
                    document.getElementById('descriptionOutput').textContent = data.description || "No description available";

                    if (data.fallback_used) {
                        statusDiv.innerHTML = 'Analysis complete (using fallback)!';
                        statusDiv.className = 'status warning';
                    }

                    // Update stats after successful processing
                    updateStats();
                })
                .catch(error => {
                    statusDiv.textContent = 'Error: ' + error.message;
                    statusDiv.className = 'status error';
                    console.error('Upload error:', error);
                });
            });
        }

        function setupCameraControls() {
            const startBtn = document.getElementById('startCamera');
            const stopBtn = document.getElementById('stopCamera');
            const captureBtn = document.getElementById('captureFrame');
            const statusDiv = document.getElementById('cameraStatus');
            const videoElement = document.getElementById('liveFeed');
            let cameraInterval;

            startBtn.addEventListener('click', function() {
                statusDiv.innerHTML = '<div class="spinner"></div> Starting camera...';
                statusDiv.className = 'status';
                statusDiv.style.display = 'block';

                fetch('/api/start_stream', {
                    method: 'POST'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        statusDiv.innerHTML = 'Camera started!';
                        statusDiv.className = 'status success';

                        document.getElementById('cameraStatusIndicator').textContent = "Active";
                        document.getElementById('cameraStatusIndicator').classList.add('badge', 'badge-success');

                        startBtn.disabled = true;
                        stopBtn.disabled = false;
                        captureBtn.disabled = false;

                        // Start updating the video feed
                        videoElement.style.display = 'block';
                        videoElement.src = '/video_feed?' + new Date().getTime();

                        // Process frames periodically
                        const interval = document.getElementById('frame-interval').value * 1000;
                        cameraInterval = setInterval(() => {
                            processCurrentFrame();
                        }, interval);
                    } else {
                        throw new Error(data.message || 'Failed to start camera');
                    }
                })
                .catch(error => {
                    statusDiv.textContent = 'Error: ' + error.message;
                    statusDiv.className = 'status error';
                    console.error('Camera start error:', error);
                });
            });

            stopBtn.addEventListener('click', function() {
                clearInterval(cameraInterval);

                fetch('/api/stop_stream', {
                    method: 'POST'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        statusDiv.textContent = 'Camera stopped';
                        statusDiv.className = 'status success';

                        document.getElementById('cameraStatusIndicator').textContent = "Inactive";
                        document.getElementById('cameraStatusIndicator').classList.remove('badge-success');
                        document.getElementById('cameraStatusIndicator').classList.add('badge', 'badge-warning');

                        startBtn.disabled = false;
                        stopBtn.disabled = true;
                        captureBtn.disabled = true;

                        videoElement.style.display = 'none';
                        videoElement.src = '';
                    }
                })
                .catch(error => {
                    statusDiv.textContent = 'Error: ' + error.message;
                    statusDiv.className = 'status error';
                    console.error('Camera stop error:', error);
                });
            });

            captureBtn.addEventListener('click', function() {
                if (!videoElement.style.display || videoElement.style.display === 'none') {
                    statusDiv.textContent = 'Camera is not active';
                    statusDiv.className = 'status warning';
                    statusDiv.style.display = 'block';
                    return;
                }

                processCurrentFrame();
            });

            function processCurrentFrame() {
                statusDiv.innerHTML = '<div class="spinner"></div> Processing frame...';
                statusDiv.className = 'status';
                statusDiv.style.display = 'block';

                fetch('/api/process_frame', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        analysis_type: document.getElementById('analysis-type').value
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        statusDiv.innerHTML = 'Frame processed!';
                        statusDiv.className = 'status success';

                        if (data.fallback_used) {
                            statusDiv.innerHTML = 'Frame processed (using fallback)!';
                            statusDiv.className = 'status warning';
                        }

                        // Update audio and description
                        const audioPlayer = document.getElementById('cameraAudioPlayer');
                        audioPlayer.src = '/api/audio?' + new Date().getTime();
                        audioPlayer.style.display = 'block';
                        document.getElementById('cameraDescriptionOutput').textContent = data.description || "No description available";

                        // Update stats
                        updateStats();
                    } else {
                        throw new Error(data.message || 'Failed to process frame');
                    }
                })
                .catch(error => {
                    statusDiv.textContent = 'Error: ' + error.message;
                    statusDiv.className = 'status error';
                    console.error('Frame processing error:', error);
                });
            }
        }
    </script>
</body>
</html>
"""



def allowed_file(filename):
    """Check if the file has an allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def check_rate_limit():
    """Check if API rate limit is exceeded"""
    global api_call_timestamps, stats


    current_time = time.time()
    api_call_timestamps = [ts for ts in api_call_timestamps if current_time - ts < 60]


    if len(api_call_timestamps) >= API_RATE_LIMIT:
        stats['api_quota_exceeded'] = True
        return False

    api_call_timestamps.append(current_time)
    stats['api_quota_exceeded'] = False
    return True

def analyze_image(image_data, analysis_type='detailed'):
    """Analyze image using OpenAI API or fallback to local processing"""
    global stats

    stats['total_api_calls'] += 1
    fallback_used = False



    if client and check_rate_limit():
        try:
            # Convert image to base64
            if isinstance(image_data, bytes):
                base64_image = base64.b64encode(image_data).decode('utf-8')
            else:
                success, buffer = cv2.imencode('.jpg', image_data)
                if not success:
                    raise ValueError("Failed to encode image using OpenCV")
                base64_image = base64.b64encode(buffer).decode('utf-8')

            assert isinstance(base64_image, str) and len(base64_image) > 0, "Base64 image encoding failed"



            # Determine prompt
            prompt = IMAGE_ANALYSIS_PROMPT
            if analysis_type == 'brief':
                prompt = "Give a brief summary of what's in this image in 1-2 sentences."
            elif analysis_type == 'objects':
                prompt = "List all objects visible in this image."
            elif analysis_type == 'text':
                prompt = "Read and transcribe any text visible in this image."

            logger.info(f"Sending image analysis request with prompt: {prompt}")
            logger.info(f"Base64 image length: {len(base64_image)} characters")


            response = client.chat.completions.create(
                model="gpt-4o",


                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},

                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }
                ],
                max_tokens=500
            )



             # Extract the text response
            description = response.choices[0].message.content
            stats['successful_api_calls'] += 1
            logger.info(f"Analysis successful using OpenAI Vision API")
            return description, fallback_used

        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            stats['failed_api_calls'] += 1
            stats['last_error'] = str(e)
            fallback_used = True

    else:
        fallback_used = True
        logger.warning("Using fallback image analysis (OpenAI API not available or rate limit exceeded)")


    try:

        if isinstance(image_data, bytes):
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        else:
            img = image_data

        # Basic image analysis
        height, width, channels = img.shape
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Calculate brightness
        brightness = np.mean(gray)

        # Calculate dominant color
        pixels = img.reshape(-1, 3)
        counts = np.unique(pixels, axis=0, return_counts=True)[1]
        dominant_color_idx = np.argmax(counts)
        dominant_color = pixels[dominant_color_idx]
        dom_b, dom_g, dom_r = dominant_color

        # Detect edges
        edges = cv2.Canny(gray, 100, 200)
        edge_percentage = np.count_nonzero(edges) / (height * width) * 100

        # Try to detect faces
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        face_count = len(faces)

        # Create description based on analysis type
        if analysis_type == 'brief':
            description = f"Image {width}x{height} pixels. " + \
                         (f"Contains {face_count} human face(s). " if face_count > 0 else "") + \
                         f"Overall brightness is {'bright' if brightness > 170 else 'medium' if brightness > 85 else 'dark'}."

        elif analysis_type == 'text':
            try:

                description = "Text extraction not available in fallback mode. Recommend trying again later when API is available."
            except Exception as text_err:
                description = f"Text recognition failed in fallback mode: {str(text_err)}"

        elif analysis_type == 'objects':
            description = "Objects detected: "
            if face_count > 0:
                description += f"{face_count} human face(s), "

            if edge_percentage > 20:
                description += "complex shapes or objects with many edges, "
            elif edge_percentage > 10:
                description += "moderate number of objects or shapes, "
            else:
                description += "simple scene with few objects, "

            description = description.rstrip(", ")

        else:
            description = f"This is a {width}x{height} pixel image. "

            # Brightness
            description += f"The image appears to be {'bright' if brightness > 170 else 'medium' if brightness > 85 else 'dark'} overall. "

            # Dominant color
            color_name = ""
            if dom_r > 200 and dom_g < 100 and dom_b < 100:
                color_name = "red"
            elif dom_r > 200 and dom_g > 200 and dom_b < 100:
                color_name = "yellow"
            elif dom_r < 100 and dom_g > 200 and dom_b < 100:
                color_name = "green"
            elif dom_r < 100 and dom_g < 100 and dom_b > 200:
                color_name = "blue"
            elif dom_r > 200 and dom_g > 100 and dom_b > 200:
                color_name = "purple"
            elif dom_r > 200 and dom_g > 100 and dom_b < 100:
                color_name = "orange"
            elif dom_r > 200 and dom_g > 200 and dom_b > 200:
                color_name = "white"
            elif dom_r < 100 and dom_g < 100 and dom_b < 100:
                color_name = "black"
            else:
                color_name = "mixed"

            description += f"The dominant color appears to be {color_name}. "

            # Faces
            if face_count > 0:
                description += f"There {'is' if face_count == 1 else 'are'} {face_count} human face{'s' if face_count > 1 else ''} in the image. "

            # Complexity based on edges
            if edge_percentage > 20:
                description += "The image contains many edges and appears to be complex or detailed. "
            elif edge_percentage > 10:
                description += "The image has a moderate level of detail. "
            else:
                description += "The image appears to be relatively simple with few distinct edges. "

            description += "Note: This is a fallback analysis with limited capabilities compared to the full AI vision analysis."

        stats['successful_api_calls'] += 1
        return description, fallback_used

    except Exception as e:
        error_msg = f"Fallback analysis failed: {str(e)}"
        logger.error(error_msg)
        stats['failed_api_calls'] += 1
        stats['last_error'] = error_msg
        return "Image analysis failed. The system encountered an error processing your image.", fallback_used

def text_to_speech(text):
    """Convert text to speech using gTTS or fallback method"""
    audio_path = os.path.join(AUDIO_FOLDER, f"speech_{int(time.time())}.mp3")

    if TEXT_TO_SPEECH_AVAILABLE:
        try:
            tts = gTTS(text=text, lang='en')
            tts.save(audio_path)
            logger.info(f"Text-to-speech conversion successful, saved to {audio_path}")
            return audio_path
        except Exception as e:
            logger.error(f"gTTS error: {str(e)}")
            # Fall through to fallback


    fallback_path = os.path.join(AUDIO_FOLDER, f"text_{int(time.time())}.txt")
    try:
        with open(fallback_path, 'w') as f:
            f.write(text)
        logger.warning(f"Used fallback text-to-speech (text file): {fallback_path}")
        return fallback_path
    except Exception as e:
        logger.error(f"Fallback text-to-speech error: {str(e)}")
        return None

from pyngrok import ngrok, exception

from pyngrok import ngrok, conf

def setup_ngrok():
    try:
        ngrok.set_auth_token(NGROK_AUTH_TOKEN)  # Set the token before connecting
        print("NGROK_AUTH_TOKEN =", NGROK_AUTH_TOKEN)

        tunnel = ngrok.connect(PORT)
        app.ngrok_url = tunnel.public_url
        logger.info(f" * Ngrok tunnel established: {app.ngrok_url}")
    except exception.PyngrokNgrokError as e:
        if "ERR_NGROK_108" in str(e):
            logger.error("Ngrok tunnel error: Already an active tunnel session. Visit https://dashboard.ngrok.com/agents to manage.")
        else:
            logger.error("Ngrok tunnel error: %s", e)

def gen_camera_frames():
    """Generator for video streaming frames"""
    global camera, stream_active

    if camera is None or not stream_active:
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n'
               b'No camera stream available\r\n\r\n')
        return

    last_frame_time = 0
    frame_interval = 1.0 / FRAME_RATE

    while stream_active:
        current_time = time.time()
        if current_time - last_frame_time >= frame_interval:
            success, frame = camera.read()
            if not success:
                logger.error("Failed to capture frame from camera")
                break

            last_frame_time = current_time
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                continue

            frame_data = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')


            last_processed['frame'] = frame
        else:

            time.sleep(0.01)

# Flask Routes

@app.route('/')
def index():
    """Render the main application page"""
    return render_template_string(HTML_INDEX)

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle image upload and analysis"""
    global last_processed, stats

    if 'image' not in request.files:
        return jsonify({'status': 'error', 'message': 'No image part'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        try:
            # Read image data
            image_data = file.read()

            # Get analysis type
            analysis_type = request.form.get('analysis_type', 'detailed')

            # Analyze image
            description, fallback_used = analyze_image(image_data, analysis_type)

            # Store results
            last_processed['description'] = description
            last_processed['timestamp'] = time.time()
            stats['total_processed_uploads'] += 1

            # Convert to speech
            audio_path = text_to_speech(description)
            last_processed['audio'] = audio_path

            if audio_path and audio_path.endswith('.mp3'):
                # Return audio file if TTS was successful
                return send_file(audio_path, mimetype='audio/mpeg')
            else:
                # Return the description as JSON if no audio
                return jsonify({
                    'status': 'success',
                    'description': description,
                    'fallback_used': fallback_used
                })

        except Exception as e:
            error_msg = f"Image processing error: {str(e)}"
            stats['last_error'] = error_msg
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            return jsonify({'status': 'error', 'message': error_msg}), 500

    return jsonify({'status': 'error', 'message': 'Invalid file type'}), 400

@app.route('/video_feed')
def video_feed():
    """Stream video from the camera"""
    if not stream_active:
        return Response("Camera not active", status=400, mimetype='text/plain')

    return Response(gen_camera_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/start_stream', methods=['POST'])
def start_stream():
    """Start the camera stream"""
    global camera, stream_active

    try:
        if stream_active:
            return jsonify({'status': 'success', 'message': 'Camera already started'})

        # Initialize camera
        camera = cv2.VideoCapture(CAMERA_SOURCE)
        if not camera.isOpened():
            return jsonify({'status': 'error', 'message': 'Failed to open camera'}), 500

        stream_active = True
        logger.info("Camera stream started")
        return jsonify({'status': 'success', 'message': 'Camera started'})
    except Exception as e:
        error_msg = f"Failed to start camera: {str(e)}"
        stats['last_error'] = error_msg
        logger.error(error_msg)
        return jsonify({'status': 'error', 'message': error_msg}), 500

@app.route('/api/stop_stream', methods=['POST'])
def stop_stream():
    """Stop the camera stream"""
    global camera, stream_active

    try:
        if not stream_active:
            return jsonify({'status': 'success', 'message': 'Camera already stopped'})

        stream_active = False

        # Release camera resources
        if camera is not None:
            camera.release()
            camera = None

        logger.info("Camera stream stopped")
        return jsonify({'status': 'success', 'message': 'Camera stopped'})
    except Exception as e:
        error_msg = f"Failed to stop camera: {str(e)}"
        stats['last_error'] = error_msg
        logger.error(error_msg)
        return jsonify({'status': 'error', 'message': error_msg}), 500

@app.route('/api/process_frame', methods=['POST'])
def process_frame():
    """Process the latest frame from the camera"""
    global last_processed, stats

    try:
        if not stream_active or last_processed['frame'] is None:
            return jsonify({
                'status': 'error',
                'message': 'No camera frame available'
            }), 400


        request_data = request.get_json() or {}
        analysis_type = request_data.get('analysis_type', 'detailed')

        frame = last_processed['frame']
        description, fallback_used = analyze_image(frame, analysis_type)

        last_processed['description'] = description
        last_processed['timestamp'] = time.time()
        stats['total_processed_frames'] += 1

        # Convert to speech
        audio_path = text_to_speech(description)
        last_processed['audio'] = audio_path

        return jsonify({
            'status': 'success',
            'description': description,
            'fallback_used': fallback_used
        })
    except Exception as e:
        error_msg = f"Frame processing error: {str(e)}"
        stats['last_error'] = error_msg
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        return jsonify({'status': 'error', 'message': error_msg}), 500

@app.route('/api/audio')
def get_audio():
    """Return the latest audio file"""
    if last_processed['audio'] and os.path.exists(last_processed['audio']):
        return send_file(last_processed['audio'])
    else:
        return jsonify({'status': 'error', 'message': 'No audio available'}), 404

@app.route('/api/results')
def get_results():
    """Return the latest processing results"""
    return jsonify({
        'description': last_processed['description'],
        'timestamp': last_processed['timestamp'],
        'has_audio': last_processed['audio'] is not None and os.path.exists(last_processed['audio'])
    })

@app.route('/api/stats')
def get_stats():
    """Return the current stats"""
    return jsonify(stats)

@app.route('/health')
def health_check():
    """Return the system health status"""
    return jsonify({
        'status': 'healthy',
        'openai_ready': client is not None,
        'camera_ready': camera is not None,
        'stream_active': stream_active,
        'quota_exceeded': stats['api_quota_exceeded'],
        'debug_mode': DEBUG_MODE,
        'public_url': app.ngrok_url
    })

# Application startup
def start_app():
    """Start the Flask application with ngrok tunnel"""
    global app

    # Setup ngrok
    app.ngrok_url = setup_ngrok()

    # Print ngrok URL prominently
    if app.ngrok_url:
        print("\n" + "=" * 80)
        print(f"ACCESS APPLICATION AT: {app.ngrok_url}")
        print("=" * 80 + "\n")
        # Also log it
        logger.info(f"Public URL available at: {app.ngrok_url}")
    else:
        print("\n" + "=" * 80)
        print(f"LOCAL ACCESS ONLY: http://localhost:{PORT}")
        print("=" * 80 + "\n")

    # Start the application
    logger.info(f"Starting Vision Assistant on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=DEBUG_MODE, threaded=True)

if __name__ == '__main__':
    try:
        start_app()
    except Exception as e:
        logger.error(f"Application startup error: {str(e)}")
        logger.error(traceback.format_exc())