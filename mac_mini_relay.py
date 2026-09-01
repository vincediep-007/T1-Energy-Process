#!/usr/bin/env python3
# ==============================================================================
# MAC MINI RELAY SERVER - QC INSPECTION PHOTO & VOICE BRIDGE
# ==============================================================================
#
# Runs on your Mac Mini at home. Requires ZERO external packages (pure Python 3).
#
# QUICK START ON MAC MINI:
#   1. Open Terminal on your Mac Mini
#   2. Run: python3 mac_mini_relay.py
#
# TO ACCESS FROM ANYWHERE (No port forwarding needed):
#   Install free Cloudflare Tunnel on Mac:
#     brew install cloudflared
#     cloudflared tunnel --url http://localhost:8000
#   (It will give you an HTTPS URL like https://xyz.trycloudflare.com to paste into the app)
# ==============================================================================

import os
import sys
import json
import time
import shutil
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import mimetypes

PORT = int(os.environ.get("RELAY_PORT", 8000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INCOMING_DIR = os.path.join(BASE_DIR, "relay_incoming")
ARCHIVE_DIR = os.path.join(BASE_DIR, "relay_archive")
SECRET_KEY = os.environ.get("RELAY_SECRET", "qc_secret_2026")

os.makedirs(INCOMING_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>QC Defect Bridge</title>
    <style>
        * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; min-height: 100vh; }
        .card { background: #1e293b; border-radius: 16px; padding: 24px; width: 100%; max-width: 420px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); text-align: center; }
        h1 { font-size: 22px; margin-top: 0; color: #38bdf8; }
        p { color: #94a3b8; font-size: 14px; margin-bottom: 20px; }
        .btn-box { display: flex; flex-direction: column; gap: 14px; }
        .btn { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 16px 20px; border-radius: 12px; font-size: 16px; font-weight: bold; border: none; cursor: pointer; text-decoration: none; color: white; transition: 0.2s; }
        .btn-photo { background: #0284c7; }
        .btn-photo:active { background: #0369a1; transform: scale(0.98); }
        .btn-voice { background: #16a34a; }
        .btn-voice:active { background: #15803d; transform: scale(0.98); }
        .btn-record { background: #dc2626; }
        .btn-record:active { background: #b91c1c; transform: scale(0.98); }
        input[type="file"] { display: none; }
        #status { margin-top: 20px; padding: 12px; border-radius: 8px; font-size: 14px; display: none; font-weight: 500; }
        .status-ok { background: #065f46; color: #6ee7b7; display: block !important; }
        .status-err { background: #991b1b; color: #fca5a5; display: block !important; }
        .status-uploading { background: #1e3a8a; color: #93c5fd; display: block !important; }
        .footer { margin-top: 25px; font-size: 12px; color: #64748b; }
    </style>
</head>
<body>
    <div class="card">
        <h1>QC Defect Direct Bridge</h1>
        <p>Take inspection photos or record voice notes. Files stream directly to the desktop app.</p>
        
        <div class="btn-box">
            <label class="btn btn-photo">
                📸 Take / Upload Photo
                <input type="file" id="photoInput" accept="image/*" capture="environment" onchange="handleFileUpload(this)">
            </label>

            <label class="btn btn-voice">
                🎙️ Upload Voice Recording
                <input type="file" id="audioInput" accept="audio/*,.m4a,.wav,.mp3,.aac" onchange="handleFileUpload(this)">
            </label>

            <button id="btnRec" class="btn btn-record" onclick="toggleDirectRecording()">
                🔴 Direct Mic Record (Hold/Tap)
            </button>
        </div>

        <div id="status"></div>
        <div class="footer">Mac Mini Relay Active &bull; Zero Lag</div>
    </div>

    <script>
        let mediaRecorder = null;
        let audioChunks = [];
        let isRecording = false;

        function setStatus(msg, type) {
            const el = document.getElementById('status');
            el.className = 'status-' + type;
            el.innerHTML = msg;
        }

        async function handleFileUpload(input) {
            if (!input.files || input.files.length === 0) return;
            const file = input.files[0];
            setStatus('Uploading ' + file.name + '...', 'uploading');

            const formData = new FormData();
            formData.append('file', file, file.name);

            try {
                const resp = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });
                const res = await resp.json();
                if (resp.ok && res.status === 'ok') {
                    setStatus('✅ Successfully sent ' + file.name + ' to laptop!', 'ok');
                } else {
                    setStatus('❌ Upload failed: ' + (res.error || 'Unknown error'), 'err');
                }
            } catch (err) {
                setStatus('❌ Network error: ' + err.message, 'err');
            }
            input.value = '';
        }

        async function toggleDirectRecording() {
            const btn = document.getElementById('btnRec');
            if (!isRecording) {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    mediaRecorder = new MediaRecorder(stream);
                    audioChunks = [];
                    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
                    mediaRecorder.onstop = async () => {
                        const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                        const fname = 'voice_' + new Date().toISOString().replace(/[:.]/g, '-') + '.wav';
                        setStatus('Sending voice recording...', 'uploading');
                        const formData = new FormData();
                        formData.append('file', audioBlob, fname);
                        try {
                            const resp = await fetch('/api/upload', { method: 'POST', body: formData });
                            const res = await resp.json();
                            if (resp.ok && res.status === 'ok') setStatus('✅ Voice sent to laptop!', 'ok');
                            else setStatus('❌ Voice upload failed', 'err');
                        } catch(e) { setStatus('❌ Network error: ' + e.message, 'err'); }
                    };
                    mediaRecorder.start();
                    isRecording = true;
                    btn.innerHTML = '⏹️ Stop & Send Recording';
                    btn.style.background = '#e11d48';
                    setStatus('🎙️ Recording voice... Speak defect and result (e.g., "Crack cell Q3")', 'uploading');
                } catch(err) {
                    setStatus('Microphone access denied: ' + err.message, 'err');
                }
            } else {
                mediaRecorder.stop();
                isRecording = false;
                btn.innerHTML = '🔴 Direct Mic Record (Hold/Tap)';
                btn.style.background = '#dc2626';
            }
        }
    </script>
</body>
</html>
"""

class RelayHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {args[0]} {args[1]}")

    def send_json_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ('/', '/index.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
            return

        if path == '/api/health':
            self.send_json_response(200, {
                'status': 'ok',
                'service': 'Mac Mini QC Relay',
                'pending_count': len([f for f in os.listdir(INCOMING_DIR) if os.path.isfile(os.path.join(INCOMING_DIR, f))])
            })
            return

        if path == '/api/pending':
            files = []
            if os.path.exists(INCOMING_DIR):
                for fname in sorted(os.listdir(INCOMING_DIR)):
                    fpath = os.path.join(INCOMING_DIR, fname)
                    if os.path.isfile(fpath):
                        files.append({
                            'name': fname,
                            'size': os.path.getsize(fpath),
                            'mtime': os.path.getmtime(fpath)
                        })
            self.send_json_response(200, {'status': 'ok', 'files': files})
            return

        if path.startswith('/api/download/'):
            fname = urllib.parse.unquote(path[len('/api/download/'):])
            fpath = os.path.join(INCOMING_DIR, fname)
            if not os.path.exists(fpath) or not os.path.isfile(fpath):
                self.send_json_response(404, {'status': 'error', 'error': 'File not found'})
                return

            mime_type, _ = mimetypes.guess_type(fpath)
            if not mime_type:
                mime_type = 'application/octet-stream'

            self.send_response(200)
            self.send_header('Content-Type', mime_type)
            self.send_header('Content-Length', str(os.path.getsize(fpath)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with open(fpath, 'rb') as f:
                shutil.copyfileobj(f, self.wfile)
            return

        self.send_json_response(404, {'status': 'error', 'error': 'Endpoint not found'})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/ack/'):
            fname = urllib.parse.unquote(path[len('/api/ack/'):])
            src = os.path.join(INCOMING_DIR, fname)
            dst = os.path.join(ARCHIVE_DIR, fname)
            if os.path.exists(src):
                try:
                    shutil.move(src, dst)
                    self.send_json_response(200, {'status': 'ok', 'acked': fname})
                except Exception as e:
                    self.send_json_response(500, {'status': 'error', 'error': str(e)})
            else:
                self.send_json_response(200, {'status': 'ok', 'message': 'Already processed'})
            return

        if path == '/api/upload':
            content_type = self.headers.get('Content-Type', '')
            content_length = int(self.headers.get('Content-Length', 0))

            if content_length == 0:
                self.send_json_response(400, {'status': 'error', 'error': 'No content'})
                return

            body = self.rfile.read(content_length)

            if 'multipart/form-data' in content_type:
                boundary = content_type.split("boundary=")[-1].encode('utf-8')
                parts = body.split(b"--" + boundary)
                saved_files = []

                for part in parts:
                    if b'filename="' in part:
                        header_part, file_data = part.split(b'\r\n\r\n', 1)
                        file_data = file_data.rstrip(b'\r\n')
                        header_lines = header_part.decode('utf-8', errors='ignore').split('\r\n')
                        filename = "upload.jpg"
                        for line in header_lines:
                            if 'filename="' in line:
                                filename = line.split('filename="')[1].split('"')[0]
                                filename = os.path.basename(filename)

                        if filename and file_data:
                            target = os.path.join(INCOMING_DIR, filename)
                            with open(target, 'wb') as f:
                                f.write(file_data)
                            saved_files.append(filename)
                            print(f"[SAVED]: {filename} ({len(file_data)} bytes)")

                self.send_json_response(200, {'status': 'ok', 'saved': saved_files})
                return
            else:
                # Raw binary upload
                fname = self.headers.get('X-File-Name', f"upload_{int(time.time())}.jpg")
                target = os.path.join(INCOMING_DIR, os.path.basename(fname))
                with open(target, 'wb') as f:
                    f.write(body)
                print(f"[SAVED RAW]: {fname} ({len(body)} bytes)")
                self.send_json_response(200, {'status': 'ok', 'saved': [fname]})
                return

        self.send_json_response(404, {'status': 'error', 'error': 'Endpoint not found'})

def run_server():
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, RelayHTTPHandler)
    print("=" * 70)
    print(f" MAC MINI RELAY SERVER LISTENING ON PORT {PORT}")
    print(f" Local Web Interface: http://localhost:{PORT}")
    print(f" Incoming Drop Folder: {INCOMING_DIR}")
    print(f" Archive Folder:       {ARCHIVE_DIR}")
    print("=" * 70)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping relay server.")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
