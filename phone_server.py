# =================== FINAL ROBUST PHONE SERVER ===================
import os
import sys
import time
import json
import re
import shutil
import threading
from datetime import datetime
import cv2
import numpy as np
from PIL import Image

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import config

import urllib.request
import urllib.parse

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    HAS_PYZBAR = True
except Exception:
    HAS_PYZBAR = False

try:
    from faster_whisper import WhisperModel
    whisper_engine = WhisperModel("tiny", device="cpu", compute_type="int8")
    HAS_WHISPER = True
except Exception:
    HAS_WHISPER = False

try:
    import speech_recognition as sr
    from pydub import AudioSegment
    HAS_SPEECH = True
except Exception:
    HAS_SPEECH = False

LOCAL_CACHE_DIR = getattr(config, 'DAILY_CACHE_DIR', os.path.join(config.LOCAL_DATA_DIR, "DailyCache"))
VOICE_SAMPLES_DIR = getattr(config, 'VOICE_SAMPLES_DIR', os.path.join(config.LOCAL_DATA_DIR, "VoiceSamples"))
LOCAL_UPLOADS_DIR = os.path.join(config.LOCAL_DATA_DIR, "PhoneUploads")

os.makedirs(LOCAL_CACHE_DIR, exist_ok=True)
os.makedirs(VOICE_SAMPLES_DIR, exist_ok=True)
os.makedirs(LOCAL_UPLOADS_DIR, exist_ok=True)

def find_phone_directories():
    """
    Dynamically auto-discovers Phone Link / CrossDevice storage directories across
    all Windows users and custom config paths.
    """
    cam_dirs = []
    rec_dirs = []

    # 1. Check custom configured paths
    cfg_cam = getattr(config, 'PHONE_CAMERA_DIR', '').strip()
    cfg_rec = getattr(config, 'PHONE_RECORDINGS_DIR', '').strip()
    if cfg_cam and os.path.exists(cfg_cam):
        cam_dirs.append(cfg_cam)
    if cfg_rec and os.path.exists(cfg_rec):
        rec_dirs.append(cfg_rec)

    # 2. Search Windows user profiles for CrossDevice storage
    candidate_user_dirs = []
    curr_profile = os.environ.get('USERPROFILE', '')
    if curr_profile and os.path.exists(curr_profile):
        candidate_user_dirs.append(curr_profile)
    
    users_root = r"C:\Users"
    if os.path.exists(users_root):
        try:
            for u in os.listdir(users_root):
                up = os.path.join(users_root, u)
                if up not in candidate_user_dirs and os.path.isdir(up):
                    candidate_user_dirs.append(up)
        except Exception:
            pass

    for u_dir in candidate_user_dirs:
        cd_base = os.path.join(u_dir, "CrossDevice")
        if os.path.exists(cd_base):
            try:
                for dev in os.listdir(cd_base):
                    storage_p = os.path.join(cd_base, dev, "storage")
                    if os.path.isdir(storage_p):
                        c_p = os.path.join(storage_p, "DCIM", "Camera")
                        r_p = os.path.join(storage_p, "Recordings")
                        if os.path.exists(c_p) and c_p not in cam_dirs:
                            cam_dirs.append(c_p)
                        if os.path.exists(r_p) and r_p not in rec_dirs:
                            rec_dirs.append(r_p)
            except Exception:
                pass

    return cam_dirs, rec_dirs

VOICE_GUIDE_FILE = os.path.join(config.LOCAL_DATA_DIR, "voice_guide_profile.json")
PAIRING_WINDOW_SECONDS = 60


PROCESSED_SERIAL_NUMBERS = set()
last_checked_date = None


def load_voice_guide():
    guide = {
        "braxel": "Crack Cells", "braxell": "Crack Cells",
        "truck sale": "Crack Cells", "track cell": "Crack Cells",
        "crack cell": "Crack Cells", "crack cells": "Crack Cells",
        "bubble": "Bubble", "baba": "Bubble", "ba bo": "Bubble",
        "no melt": "No melt", "backsheet": "Backsheet Defect", "black sheet": "Backsheet Defect",
        "positioning tape": "Positioning Tape", "position tape": "Positioning Tape", "tape": "Positioning Tape",
        "fractale": "Positioning Tape", "fraktal": "Positioning Tape"
    }
    if os.path.exists(VOICE_GUIDE_FILE):
        try:
            with open(VOICE_GUIDE_FILE, "r", encoding="utf-8") as f:
                guide.update(json.load(f))
        except Exception: pass
    return guide

def save_voice_guide(guide_dict):
    try:
        with open(VOICE_GUIDE_FILE, "w", encoding="utf-8") as f:
            json.dump(guide_dict, f, indent=2, ensure_ascii=False)
    except Exception: pass

VOICE_GUIDE = load_voice_guide()


def check_daily_reset():
    global last_checked_date, PROCESSED_SERIAL_NUMBERS
    today = datetime.now().date()
    if last_checked_date != today:
        PROCESSED_SERIAL_NUMBERS.clear()
        last_checked_date = today


def scan_and_train_from_sample_folders():
    if not os.path.exists(VOICE_SAMPLES_DIR) or not HAS_WHISPER: return
    updated = False
    try:
        for folder_name in os.listdir(VOICE_SAMPLES_DIR):
            sub_path = os.path.join(VOICE_SAMPLES_DIR, folder_name)
            if not os.path.isdir(sub_path): continue
            target_value = folder_name.replace("_", " ")
            for file_name in os.listdir(sub_path):
                if file_name.lower().endswith((".wav", ".m4a", ".mp3", ".ogg")):
                    try:
                        segments, _ = whisper_engine.transcribe(os.path.join(sub_path, file_name), language="en", beam_size=3)
                        clean_spoken = " ".join(re.sub(r'[^a-zA-Z0-9\s]', ' ', " ".join([seg.text for seg in segments])).split()).lower()
                        if clean_spoken and clean_spoken not in VOICE_GUIDE:
                            VOICE_GUIDE[clean_spoken] = target_value
                            updated = True
                    except Exception: pass
        if updated: save_voice_guide(VOICE_GUIDE)
    except Exception: pass


def decode_qr_robust(cv_img):
    if cv_img is None or cv_img.size == 0: return ""
    
    # 1. Fast path: Direct PyZbar decode on original image (0.05s)
    if HAS_PYZBAR:
        try:
            for obj in pyzbar_decode(cv_img):
                sn = obj.data.decode('utf-8').strip()
                if sn and len(sn) >= 6: return sn
        except Exception: pass

    # 2. Fast OpenCV detector
    detector = cv2.QRCodeDetector()
    try:
        data, _, _ = detector.detectAndDecode(cv_img)
        if data and len(data.strip()) >= 6: return data.strip()
    except Exception: pass

    # 3. Robust fallback: Multi-scale and CLAHE enhancement
    h, w = cv_img.shape[:2]
    for scale in [0.5, 0.25, 1.5]:
        resized = cv2.resize(cv_img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC)
        if HAS_PYZBAR:
            try:
                for obj in pyzbar_decode(resized):
                    sn = obj.data.decode('utf-8').strip()
                    if sn and len(sn) >= 6: return sn
            except Exception: pass

        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        if HAS_PYZBAR:
            try:
                for obj in pyzbar_decode(enhanced):
                    sn = obj.data.decode('utf-8').strip()
                    if sn and len(sn) >= 6: return sn
            except Exception: pass

        try:
            data, _, _ = detector.detectAndDecode(enhanced)
            if data and len(data.strip()) >= 6: return data.strip()
        except Exception: pass

    return ""



def extract_sn_from_photo(image_path: str) -> str:
    try:
        cv_img = cv2.imread(image_path)
        if cv_img is None: return ""
        sn = decode_qr_robust(cv_img)
        if sn: return sn

        h, w = cv_img.shape[:2]
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if (cw * ch) > (h * w * 0.005) and (cw > ch) and (y > h * 0.3):
                label_crop = cv_img[max(0, y-10):min(h, y+ch+10), max(0, x-10):min(w, x+cw+10)]
                sn = decode_qr_robust(label_crop)
                if sn: return sn
    except Exception: pass
    return ""


def clean_text(text: str) -> str:
    text = re.sub(r'[^a-zA-Z0-9\s]', ' ', text)
    return " ".join(text.lower().split())


def parse_two_part_voice(raw_text: str):
    norm = clean_text(raw_text)
    detected_result = ""
    
    # Dynamic or fallback check for grades (Q3, Scrap)
    grades = ["Q3", "Scrap"]
    for grade in grades:
        if grade.lower() in norm:
            detected_result = grade
            norm = norm.replace(grade.lower(), "").strip()

    if not detected_result:
        if "q3" in norm or "ku" in norm or "queue" in norm:
            detected_result = "Q3"
        elif "scrap" in norm or "skrap" in norm or "sot" in norm or "scrab" in norm:
            detected_result = "Scrap"

    for spoken_trigger, target_summary in VOICE_GUIDE.items():
        if spoken_trigger == norm or spoken_trigger in norm or norm in spoken_trigger:
            for cls_name, summaries in config.DEFECT_TREE.items():
                if target_summary in summaries: return target_summary, cls_name, detected_result, norm

    for cls_name, summaries in config.DEFECT_TREE.items():
        for summary in summaries:
            if clean_text(summary) in norm or norm in clean_text(summary):
                return summary, cls_name, detected_result, norm

    return "", "", detected_result, norm


def transcribe_voice_recording(local_audio_path: str):
    if not os.path.isfile(local_audio_path): return "", "", "", ""
    raw_text = ""
    wav_path = os.path.join(LOCAL_CACHE_DIR, "temp_voice.wav")
    try:
        AudioSegment.from_file(local_audio_path).normalize().export(wav_path, format="wav")
    except Exception: wav_path = local_audio_path

    if HAS_WHISPER:
        try:
            segments, _ = whisper_engine.transcribe(wav_path, language="en", beam_size=5)
            raw_text = " ".join([seg.text for seg in segments]).strip().lower()
        except Exception as e:
            print(f"Whisper error: {e}")

    if not raw_text and HAS_SPEECH:
        try:
            r = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                r.adjust_for_ambient_noise(source, duration=0.15)
                raw_text = r.recognize_google(r.record(source), language="en-US").lower().strip()
        except Exception as e:
            print(f"SpeechRecognition error: {e}")

    print(f"[VOICE TRANSCRIPT DEBUG]: Heard -> '{raw_text}'")

    if not raw_text: return "", "", "", ""
    return parse_two_part_voice(raw_text)


def get_file_datetime(file_path: str) -> datetime:
    fname = os.path.basename(file_path)
    m = re.search(r'(?:PXL_|IMG_|Photo_|Voice_|REC_)?(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', fname)
    if m:
        try:
            y, mo, d, h, mi, s = map(int, m.groups())
            return datetime(y, mo, d, h, mi, s)
        except Exception: pass
    m2 = re.search(r'(\d{4})(\d{2})(\d{2})', fname)
    if m2:
        try:
            y, mo, d = map(int, m2.groups())
            mtime = os.path.getmtime(file_path)
            dt = datetime.fromtimestamp(mtime)
            return dt.replace(year=y, month=mo, day=d)
        except Exception: pass
    try:
        return datetime.fromtimestamp(os.path.getmtime(file_path))
    except Exception:
        return datetime.now()


def process_file_item(full_source_path, fname, callback_fn):
    global PROCESSED_SERIAL_NUMBERS

    ext = os.path.splitext(fname)[1].lower()
    local_mirror_path = os.path.join(LOCAL_CACHE_DIR, fname)

    try:
        if not os.path.exists(local_mirror_path) or os.path.getsize(local_mirror_path) == 0:
            shutil.copy2(full_source_path, local_mirror_path)

        file_dt = get_file_datetime(local_mirror_path)

        # Audio Recording
        if ext in ('.m4a', '.wav', '.mp3', '.aac', '.3gp', '.ogg', '.amr') or 'recording' in fname.lower() or 'voice' in fname.lower():
            summary, cls_name, result_grade, raw_spoken = transcribe_voice_recording(local_mirror_path)
            if callback_fn:
                callback_fn(file_path=local_mirror_path, extracted_sn=None, action="VOICE_DETECTED",
                            v_summary=summary, v_class=cls_name, v_result=result_grade, raw_voice=raw_spoken, audio_path=local_mirror_path, file_dt=file_dt)
            return

        # Photo Sync
        if ext in ('.jpg', '.jpeg', '.png', '.bmp'):
            found_sn = extract_sn_from_photo(local_mirror_path)
            
            if found_sn:
                if callback_fn:
                    callback_fn(file_path=local_mirror_path, extracted_sn=found_sn, action="SN_PHOTO",
                                v_summary="", v_class="", v_result="", file_dt=file_dt)
            else:
                # Defect close-up photo (no barcode on it)
                if callback_fn:
                    callback_fn(file_path=local_mirror_path, extracted_sn=None, action="DEFECT_PHOTO",
                                v_summary="", v_class="", v_result="", file_dt=file_dt)
    except Exception as e:
        print(f"Error processing item {fname}: {e}")



def test_mac_mini_relay_connection(url: str, secret: str = "") -> tuple:
    if not url: return False, "URL is empty"
    clean_url = url.strip().rstrip('/')
    try:
        headers = {'User-Agent': 'QC-Defect-App/18.6'}
        if secret: headers['X-Relay-Secret'] = secret
        req = urllib.request.Request(f"{clean_url}/api/health", headers=headers)
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                return True, f"Connected (Pending: {data.get('pending_count', 0)})"
    except Exception as e:
        return False, f"Offline ({e})"
    return False, "Offline"


def start_mac_mini_relay_client(callback_fn, poll_interval=2.0):
    def _poll():
        while True:
            time.sleep(poll_interval)
            url = getattr(config, 'MAC_MINI_RELAY_URL', '').strip().rstrip('/')
            enabled = getattr(config, 'MAC_MINI_RELAY_ENABLED', False)
            if not enabled or not url:
                continue

            try:
                secret = getattr(config, 'MAC_MINI_RELAY_SECRET', '')
                headers = {'User-Agent': 'QC-Defect-App/18.6'}
                if secret: headers['X-Relay-Secret'] = secret

                req = urllib.request.Request(f"{url}/api/pending", headers=headers)
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    pending_files = data.get('files', [])

                for file_info in pending_files:
                    fname = file_info['name']
                    download_url = f"{url}/api/download/{urllib.parse.quote(fname)}"
                    target_p = os.path.join(LOCAL_UPLOADS_DIR, fname)

                    dl_req = urllib.request.Request(download_url, headers=headers)
                    with urllib.request.urlopen(dl_req, timeout=12) as dl_resp:
                        with open(target_p, 'wb') as f:
                            f.write(dl_resp.read())

                    # Acknowledge file on relay server
                    try:
                        ack_req = urllib.request.Request(f"{url}/api/ack/{urllib.parse.quote(fname)}", method='POST', headers=headers)
                        urllib.request.urlopen(ack_req, timeout=4)
                    except Exception: pass

                    print(f"[MAC MINI RELAY]: Downloaded {fname} -> PhoneUploads")
                    time.sleep(0.2)
                    process_file_item(target_p, fname, callback_fn)

            except Exception:
                pass

    threading.Thread(target=_poll, daemon=True).start()


def start_smart_today_copier(callback_fn, poll_interval=1.5):
    threading.Thread(target=scan_and_train_from_sample_folders, daemon=True).start()

    def _watch():
        check_daily_reset()
        seen_files = set()
        
        # 1. Startup sweep of existing PhoneUploads, sorted chronologically by file time
        if os.path.exists(LOCAL_UPLOADS_DIR):
            print(f"[SMART TODAY COPIER]: Performing chronological startup sweep of PhoneUploads...")
            try:
                upload_files = []
                for fname in os.listdir(LOCAL_UPLOADS_DIR):
                    full_p = os.path.join(LOCAL_UPLOADS_DIR, fname)
                    if os.path.isfile(full_p):
                        try:
                            mtime = os.path.getmtime(full_p)
                            upload_files.append((mtime, fname, full_p))
                        except Exception:
                            pass
                
                upload_files.sort(key=lambda x: x[0])

                for mtime, fname, full_p in upload_files:
                    try:
                        process_file_item(full_p, fname, callback_fn)
                        seen_files.add(fname)
                    except Exception as e:
                        print(f"Startup sweep error for {fname}: {e}")
            except Exception as e:
                print(f"Startup scan error: {e}")

        print(f"[SMART TODAY COPIER]: Active. Monitoring new files...")

        while True:
            time.sleep(poll_interval)
            check_daily_reset()
            today_str = datetime.now().strftime("%Y%m%d")

            # 2. Dynamically discover all phone camera and recording directories
            cam_dirs, rec_dirs = find_phone_directories()
            watch_dirs = cam_dirs + rec_dirs

            for d in watch_dirs:
                if not os.path.exists(d): continue
                try:
                    for fname in os.listdir(d):
                        if fname not in seen_files:
                            if today_str in fname or 'recording' in fname.lower() or 'voice' in fname.lower():
                                full_p = os.path.join(d, fname)
                                target_p = os.path.join(LOCAL_UPLOADS_DIR, fname)
                                try:
                                    if not os.path.exists(target_p):
                                        shutil.copy2(full_p, target_p)
                                        print(f"[COPIED TODAY FILE]: {fname} -> PhoneUploads")
                                    
                                    time.sleep(0.3)
                                    process_file_item(target_p, fname, callback_fn)
                                except Exception as e:
                                    print(f"Copy/process error for {fname}: {e}")
                                
                                seen_files.add(fname)
                except Exception: 
                    pass

            # 3. Check for any new files manually dropped into PhoneUploads while running
            if os.path.exists(LOCAL_UPLOADS_DIR):
                try:
                    for fname in os.listdir(LOCAL_UPLOADS_DIR):
                        if fname not in seen_files:
                            full_p = os.path.join(LOCAL_UPLOADS_DIR, fname)
                            if os.path.isfile(full_p):
                                process_file_item(full_p, fname, callback_fn)
                                seen_files.add(fname)
                except Exception: pass

    threading.Thread(target=_watch, daemon=True).start()
    return LOCAL_UPLOADS_DIR


def train_voice_pattern(spoken_phrase: str, target_summary: str, audio_source_path: str = None):
    clean_p = clean_text(spoken_phrase)
    if clean_p and target_summary:
        VOICE_GUIDE[clean_p] = target_summary
        save_voice_guide(VOICE_GUIDE)
        if audio_source_path and os.path.exists(audio_source_path):
            try:
                safe_name = re.sub(r'[^a-zA-Z0-9]', '_', target_summary)
                defect_sample_dir = os.path.join(VOICE_SAMPLES_DIR, safe_name)
                os.makedirs(defect_sample_dir, exist_ok=True)
                if len(os.listdir(defect_sample_dir)) < 10:
                    shutil.copy(audio_source_path, os.path.join(defect_sample_dir, f"Sample{len(os.listdir(defect_sample_dir))+1}.wav"))
            except Exception: pass


def start_phone_server(callback_fn):
    active_path = start_smart_today_copier(callback_fn)
    start_mac_mini_relay_client(callback_fn)
    
    cam_dirs, rec_dirs = find_phone_directories()
    phone_link_status = "Phone Link: Connected" if cam_dirs else "Phone Link: Watching"
    relay_status = "Mac Relay: Enabled" if getattr(config, 'MAC_MINI_RELAY_ENABLED', False) else "Mac Relay: Ready"
    return f"{phone_link_status} | {relay_status}\nDrop: {active_path}"