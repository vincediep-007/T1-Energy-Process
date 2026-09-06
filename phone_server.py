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

HAS_WHISPER = False
whisper_engine = None

def get_whisper_engine():
    global whisper_engine, HAS_WHISPER
    if whisper_engine is None:
        try:
            from faster_whisper import WhisperModel
            whisper_engine = WhisperModel("tiny", device="cpu", compute_type="int8")
            HAS_WHISPER = True
        except Exception:
            HAS_WHISPER = False
    return whisper_engine

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
        # English & Accented Pronunciation Variations
        "braxel": "Crack Cells", "braxell": "Crack Cells",
        "truck sale": "Crack Cells", "track cell": "Crack Cells",
        "crack cell": "Crack Cells", "crack cells": "Crack Cells",
        "crek": "Crack Cells", "crak": "Crack Cells", "crak cel": "Crack Cells",
        "bubble": "Bubble", "baba": "Bubble", "ba bo": "Bubble", "bup ble": "Bubble", "bap bo": "Bubble",
        "no melt": "No melt", "nomelt": "No melt", "no meo": "No melt", "nô meo": "No melt",
        "backsheet": "Backsheet Defect", "black sheet": "Backsheet Defect", "back sheet": "Backsheet Defect",
        "positioning tape": "Positioning Tape", "position tape": "Positioning Tape", "tape": "Positioning Tape",
        "fractale": "Positioning Tape", "fraktal": "Positioning Tape",
        "foreign object": "Foreign object", "foreign": "Foreign object", "fo ren": "Foreign object",
        "glass defect": "Glass Defect", "glass": "Glass Defect", "gờ lát": "Glass Defect",
        "solder defect": "Solder Defect", "solder": "Solder Defect", "xô đơ": "Solder Defect",
        "misalignment": "Missalignment Defect", "misline": "Missalignment Defect",
        "equipment scrap": "Equipment Scrap", "equipment": "Equipment Scrap",
        
        # Vietnamese Direct & Phonetic Translations
        "nứt cell": "Crack Cells", "nut cell": "Crack Cells", "nứt": "Crack Cells",
        "bọt khí": "Bubble", "bot khi": "Bubble", "bọt": "Bubble",
        "không chảy": "No melt", "khong chay": "No melt", "chưa chảy": "No melt",
        "băng keo": "Positioning Tape", "bang keo": "Positioning Tape", "keo": "Positioning Tape",
        "dị vật": "Foreign object", "di vat": "Foreign object", "rác": "Foreign object",
        "vỡ kính": "Glass Defect", "vo kinh": "Glass Defect", "nứt kính": "Glass Defect", "kính": "Glass Defect",
        "mối hàn": "Solder Defect", "hàn": "Solder Defect", "han": "Solder Defect",
        "lệch": "Missalignment Defect", "lech": "Missalignment Defect",
        "tấm lưng": "Backsheet Defect", "tam lung": "Backsheet Defect", "mặt sau": "Backsheet Defect",
        "chập": "Shorted cell scrap", "chap": "Shorted cell scrap"
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


def refresh_save_folders_for_today():
    """
    Refreshes the save folders (DailyCache and PhoneUploads) by replacing them with a fresh daily folder.
    Instead of deleting individual files (which triggers permission/admin authorization errors on corporate laptops),
    it safely archives previous day's folders and creates a clean, empty folder with the exact same name.
    """
    today_dt = datetime.now()
    today_date = today_dt.date()
    yesterday_str = today_date.strftime("%Y%m%d")
    
    archive_base = os.path.join(config.LOCAL_DATA_DIR, "FolderArchives")
    
    for folder_path in [LOCAL_CACHE_DIR, LOCAL_UPLOADS_DIR]:
        if not os.path.exists(folder_path):
            try:
                os.makedirs(folder_path, exist_ok=True)
            except Exception: pass
            continue
            
        try:
            items = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
            if not items:
                continue
                
            # Check if any file in the folder is from a previous day
            has_old_files = False
            today_files = []
            for fname in items:
                fpath = os.path.join(folder_path, fname)
                f_dt = get_file_datetime(fpath)
                if f_dt.date() < today_date:
                    has_old_files = True
                else:
                    today_files.append(fname)
                        
            if has_old_files:
                os.makedirs(archive_base, exist_ok=True)
                folder_name = os.path.basename(folder_path)
                archive_name = f"{folder_name}_{yesterday_str}"
                archive_target = os.path.join(archive_base, archive_name)
                
                # Handle unique archive folder name
                cnt = 1
                while os.path.exists(archive_target):
                    archive_target = os.path.join(archive_base, f"{folder_name}_{yesterday_str}_{cnt}")
                    cnt += 1
                    
                renamed = False
                try:
                    os.rename(folder_path, archive_target)
                    renamed = True
                    print(f"[DAILY FOLDER REFRESH]: Archived previous folder -> {archive_target}")
                except Exception as ren_err:
                    print(f"[DAILY FOLDER NOTICE]: Folder rename skipped ({ren_err}).")
                    
                # Create brand new clean folder with the exact same name
                os.makedirs(folder_path, exist_ok=True)
                print(f"[DAILY FOLDER REFRESH]: Created clean new workspace folder -> {folder_name}")
                
                # If there were any files created today before the rotation, move them back to the active folder
                if renamed and today_files:
                    for tf in today_files:
                        src = os.path.join(archive_target, tf)
                        dst = os.path.join(folder_path, tf)
                        if os.path.exists(src) and not os.path.exists(dst):
                            try:
                                shutil.move(src, dst)
                            except Exception: pass
        except Exception as e:
            print(f"[DAILY REFRESH NOTICE] in {folder_path}: {e}")
            try:
                os.makedirs(folder_path, exist_ok=True)
            except Exception: pass


def check_daily_reset():
    global last_checked_date, PROCESSED_SERIAL_NUMBERS
    today = datetime.now().date()
    if last_checked_date != today:
        PROCESSED_SERIAL_NUMBERS.clear()
        last_checked_date = today
        refresh_save_folders_for_today()
        print(f"[DAILY RESET]: Initialized fresh daily workspace for {today}.")



def scan_and_train_from_sample_folders():
    # Paused for fast startup and 0% CPU consumption
    return


def decode_qr_robust(cv_img):
    if cv_img is None or cv_img.size == 0:
        return ""
    
    h, w = cv_img.shape[:2]
    
    # Target widths: 800 and 1024 remove moire and high-frequency busbar grid noise
    target_widths = [800, 1024, 1200, 600, w]
    
    for tw in target_widths:
        if tw != w:
            scale = tw / w
            scaled = cv2.resize(cv_img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC)
        else:
            scaled = cv_img
            
        # Try all 4 orientations (0, 90, 180, 270)
        for deg in [0, 90, 180, 270]:
            if deg == 0:
                rot = scaled
            elif deg == 90:
                rot = cv2.rotate(scaled, cv2.ROTATE_90_CLOCKWISE)
            elif deg == 180:
                rot = cv2.rotate(scaled, cv2.ROTATE_180)
            else:
                rot = cv2.rotate(scaled, cv2.ROTATE_90_COUNTERCLOCKWISE)
                
            # 1. PyZbar with specific symbols (QRCODE, CODE128, CODE39 - avoids pdf417/databar assertion warnings)
            if HAS_PYZBAR:
                from pyzbar.pyzbar import ZBarSymbol
                try:
                    for obj in pyzbar_decode(rot, symbols=[ZBarSymbol.QRCODE, ZBarSymbol.CODE128, ZBarSymbol.CODE39]):
                        sn = obj.data.decode('utf-8', errors='ignore').strip()
                        if sn and len(sn) >= 6:
                            return sn
                except Exception:
                    pass

            # 2. PyZbar with light Gaussian blur (cleans up screen moire / LCD grid lines)
            if HAS_PYZBAR:
                from pyzbar.pyzbar import ZBarSymbol
                try:
                    blurred = cv2.GaussianBlur(rot, (5, 5), 0)
                    for obj in pyzbar_decode(blurred, symbols=[ZBarSymbol.QRCODE, ZBarSymbol.CODE128, ZBarSymbol.CODE39]):
                        sn = obj.data.decode('utf-8', errors='ignore').strip()
                        if sn and len(sn) >= 6:
                            return sn
                except Exception:
                    pass

            # 3. OpenCV QRCodeDetector
            try:
                detector = cv2.QRCodeDetector()
                data, _, _ = detector.detectAndDecode(rot)
                if data and len(data.strip()) >= 6:
                    return data.strip()
            except Exception:
                pass

            # 4. Adaptive thresholding
            try:
                gray = cv2.cvtColor(rot, cv2.COLOR_BGR2GRAY)
                thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5)
                if HAS_PYZBAR:
                    from pyzbar.pyzbar import ZBarSymbol
                    for obj in pyzbar_decode(thresh, symbols=[ZBarSymbol.QRCODE, ZBarSymbol.CODE128]):
                        sn = obj.data.decode('utf-8', errors='ignore').strip()
                        if sn and len(sn) >= 6:
                            return sn
            except Exception:
                pass

    return ""


def extract_sn_from_photo(image_path: str) -> str:
    try:
        cv_img = cv2.imread(image_path)
        if cv_img is None:
            return ""
        sn = decode_qr_robust(cv_img)
        if sn:
            return sn

        # If full-frame decode didn't match, attempt center/label contour crops
        h, w = cv_img.shape[:2]
        center_crop = cv_img[int(h * 0.15):int(h * 0.85), int(w * 0.15):int(w * 0.85)]
        sn = decode_qr_robust(center_crop)
        if sn:
            return sn

        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if (cw * ch) > (h * w * 0.005) and (cw > ch or ch > cw):
                label_crop = cv_img[max(0, y-10):min(h, y+ch+10), max(0, x-10):min(w, x+cw+10)]
                sn = decode_qr_robust(label_crop)
                if sn:
                    return sn
    except Exception as e:
        print(f"[EXTRACT SN ERROR]: {e}")
    return ""



def clean_text(text: str) -> str:
    text = re.sub(r'[^a-zA-Z0-9\sàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]', ' ', text)
    return " ".join(text.lower().split())


def parse_two_part_voice(raw_text: str):
    norm = clean_text(raw_text)
    detected_result = ""
    
    # Check Result Grade (Q3 / Scrap / Vietnamese equivalents)
    q3_triggers = ["q3", "ku three", "ku tri", "kiu tri", "kiu three", "quy ba", "quy 3", "q 3", "kiu ti", "ku"]
    scrap_triggers = ["scrap", "skrap", "sot", "scrab", "sờ ráp", "xì ráp", "xờ ráp", "sờ cờ ráp", "xrap", "phế phẩm", "phế", "bỏ"]

    for t in q3_triggers:
        if t in norm:
            detected_result = "Q3"
            norm = norm.replace(t, "").strip()
            break

    if not detected_result:
        for t in scrap_triggers:
            if t in norm:
                detected_result = "Scrap"
                norm = norm.replace(t, "").strip()
                break

    for spoken_trigger, target_summary in VOICE_GUIDE.items():
        if spoken_trigger == norm or spoken_trigger in norm or norm in spoken_trigger:
            for cls_name, summaries in config.DEFECT_TREE.items():
                if target_summary.lower() in [s.lower() for s in summaries]:
                    for s in summaries:
                        if s.lower() == target_summary.lower():
                            return s, cls_name, detected_result, norm

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
            prompt_context = "Crack cells, Bubble, No melt, Backsheet defect, Foreign object, Glass defect, Solder defect, Positioning Tape, Equipment scrap, Q3, Scrap, NG, OK, Cell overlap, Ribbon excess, Rework, Desiccant, Dirty, Insect, nứt cell, bọt khí, không chảy, băng keo, dị vật, vỡ kính, mối hàn, phế phẩm"
            segments, _ = whisper_engine.transcribe(wav_path, language=None, initial_prompt=prompt_context, beam_size=5)
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


PROCESSED_PHOTO_NAMES = set()

def mark_photo_processed(*names_or_paths):
    for item in names_or_paths:
        if item:
            PROCESSED_PHOTO_NAMES.add(str(item))
            PROCESSED_PHOTO_NAMES.add(os.path.basename(str(item)))

def is_photo_processed(name_or_path) -> bool:
    if not name_or_path:
        return False
    s = str(name_or_path)
    return s in PROCESSED_PHOTO_NAMES or os.path.basename(s) in PROCESSED_PHOTO_NAMES


def rename_to_sn_pattern(file_path: str, prefix: str, sn: str, target_dir: str = None) -> str:
    """
    Renames/copies a photo file to DailyCache with pattern <prefix>_<sn>.<ext>.
    Examples:
      - SN_V01269005050657.jpg for barcode photo
      - Def_V01269005050657.jpg for defect photo
    """
    if not file_path or not os.path.exists(file_path) or not sn or str(sn).strip() in ("Pending SN", "-", "", "None"):
        return file_path
    
    dir_name = target_dir or LOCAL_CACHE_DIR
    os.makedirs(dir_name, exist_ok=True)
    base_name = os.path.basename(file_path)
    ext = os.path.splitext(base_name)[1].lower() or ".jpg"
    clean_sn = re.sub(r'[^a-zA-Z0-9_\-]', '', str(sn).strip())
    
    target_name = f"{prefix}_{clean_sn}{ext}"
    target_path = os.path.join(dir_name, target_name)
    
    if os.path.abspath(file_path) == os.path.abspath(target_path):
        mark_photo_processed(file_path, base_name)
        return file_path

    counter = 1
    while os.path.exists(target_path) and os.path.abspath(target_path) != os.path.abspath(file_path):
        target_name = f"{prefix}_{clean_sn}_{counter}{ext}"
        target_path = os.path.join(dir_name, target_name)
        counter += 1
        
    try:
        if os.path.dirname(file_path) == dir_name:
            os.rename(file_path, target_path)
        else:
            shutil.copy2(file_path, target_path)
        print(f"[PHOTO RENAMED IN DAILYCACHE]: {base_name} -> {target_name}")
        mark_photo_processed(file_path, base_name, target_path, target_name)
        return target_path
    except Exception as e:
        print(f"[RENAME ERROR]: {e}")
        mark_photo_processed(file_path, base_name)
        return file_path


def process_file_item(full_source_path, fname, callback_fn):
    global PROCESSED_SERIAL_NUMBERS

    if is_photo_processed(fname) or is_photo_processed(full_source_path):
        return

    ext = os.path.splitext(fname)[1].lower()
    local_mirror_path = os.path.join(LOCAL_CACHE_DIR, fname)

    try:
        if not os.path.exists(local_mirror_path) or os.path.getsize(local_mirror_path) == 0:
            shutil.copy2(full_source_path, local_mirror_path)

        mark_photo_processed(fname, full_source_path, local_mirror_path)
        file_dt = get_file_datetime(local_mirror_path)

        # Audio Recording (Temporarily paused in favor of Mobile Defect Control Panel)
        if ext in ('.m4a', '.wav', '.mp3', '.aac', '.3gp', '.ogg', '.amr') or 'recording' in fname.lower() or 'voice' in fname.lower():
            # Voice processing paused as requested
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
        today_date = datetime.now().date()
        
        # 1. Startup sweep: Refresh folders and process only files from TODAY
        refresh_save_folders_for_today()
        if os.path.exists(LOCAL_UPLOADS_DIR):
            print(f"[SMART TODAY COPIER]: Performing startup sweep for today's files ({today_date})...")
            try:
                upload_files = []
                for fname in os.listdir(LOCAL_UPLOADS_DIR):
                    full_p = os.path.join(LOCAL_UPLOADS_DIR, fname)
                    if os.path.isfile(full_p):
                        try:
                            f_dt = get_file_datetime(full_p)
                            if f_dt.date() == today_date:
                                upload_files.append((f_dt.timestamp(), fname, full_p))
                        except Exception:
                            pass
                
                upload_files.sort(key=lambda x: x[0])

                for _, fname, full_p in upload_files:
                    try:
                        process_file_item(full_p, fname, callback_fn)
                        seen_files.add(fname)
                    except Exception as e:
                        print(f"Startup sweep error for {fname}: {e}")
            except Exception as e:
                print(f"Startup scan error: {e}")

        print(f"[SMART TODAY COPIER]: Active. Monitoring today's files...")

        while True:
            time.sleep(poll_interval)
            check_daily_reset()
            current_today = datetime.now().date()
            today_str = current_today.strftime("%Y%m%d")

            # 2. Dynamically discover all phone camera and recording directories
            cam_dirs, rec_dirs = find_phone_directories()
            watch_dirs = cam_dirs + rec_dirs

            for d in watch_dirs:
                if not os.path.exists(d): continue
                try:
                    for fname in os.listdir(d):
                        if fname not in seen_files:
                            full_p = os.path.join(d, fname)
                            if not os.path.isfile(full_p): continue

                            # Check if file belongs to TODAY
                            f_dt = get_file_datetime(full_p)
                            if f_dt.date() != current_today and today_str not in fname:
                                seen_files.add(fname)
                                continue

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
                        if fname not in seen_files and not is_photo_processed(fname):
                            full_p = os.path.join(LOCAL_UPLOADS_DIR, fname)
                            if os.path.isfile(full_p):
                                f_dt = get_file_datetime(full_p)
                                if f_dt.date() == current_today:
                                    process_file_item(full_p, fname, callback_fn)
                                seen_files.add(fname)
                except Exception: pass


    threading.Thread(target=_watch, daemon=True).start()
    return LOCAL_UPLOADS_DIR


def ensure_defect_sample_folders():
    """Ensures a dedicated subfolder exists for each factory defect description in VoiceSamples/"""
    os.makedirs(VOICE_SAMPLES_DIR, exist_ok=True)
    for cls_name, summaries in config.DEFECT_TREE.items():
        for summary in summaries:
            safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', summary.strip())
            folder_p = os.path.join(VOICE_SAMPLES_DIR, safe_name)
            os.makedirs(folder_p, exist_ok=True)


def train_voice_pattern(spoken_phrase: str, target_summary: str, audio_source_path: str = None):
    clean_p = clean_text(spoken_phrase)
    if clean_p and target_summary:
        VOICE_GUIDE[clean_p] = target_summary
        save_voice_guide(VOICE_GUIDE)
        print(f"[VOICE LEARNED]: '{clean_p}' -> '{target_summary}'")
        if audio_source_path and os.path.exists(audio_source_path):
            try:
                safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', target_summary.strip())
                defect_sample_dir = os.path.join(VOICE_SAMPLES_DIR, safe_name)
                os.makedirs(defect_sample_dir, exist_ok=True)
                sample_idx = len([f for f in os.listdir(defect_sample_dir) if f.startswith("Sample")]) + 1
                target_audio_p = os.path.join(defect_sample_dir, f"Sample_{sample_idx}.wav")
                try:
                    AudioSegment.from_file(audio_source_path).normalize().export(target_audio_p, format="wav")
                except Exception:
                    ext = os.path.splitext(audio_source_path)[1]
                    shutil.copy2(audio_source_path, os.path.join(defect_sample_dir, f"Sample_{sample_idx}{ext}"))
                print(f"[VOICE SAMPLE SAVED]: Stored in {defect_sample_dir}")
            except Exception as e:
                print(f"[VOICE SAMPLE SAVE ERROR]: {e}")


# =================== MOBILE LIVE WEB HUD & ANALYTICS SERVER ===================

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import socket


GLOBAL_OVERRIDE_CALLBACK = None

LIVE_HUD_STATE = {
    "last_panel": {
        "sn": "-",
        "order": "-",
        "summary": "-",
        "class": "-",
        "result": "-",
        "line": "-",
        "shift": "-",
        "layup_time": "-",
        "station": "-",
        "photo_name": "-",
        "photo_path": "",
        "timestamp": "",
        "status": "Ready"
    },
    "live_voice": {
        "raw_text": "",
        "defect": "-",
        "result": "-",
        "timestamp": ""
    },
"today_stats": {
        "total": 0,
        "q3": 0,
        "scrap": 0,
        "top_defects": [],
        "line_counts": {}
    },
    "records": []
}

GLOBAL_OVERRIDE_CALLBACK = None
GLOBAL_DEFECT_CALLBACK = None

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def update_live_hud_state(last_rec=None, live_voice=None, all_records=None, override_callback=None, defect_callback=None):
    global LIVE_HUD_STATE, GLOBAL_OVERRIDE_CALLBACK, GLOBAL_DEFECT_CALLBACK
    if override_callback is not None:
        GLOBAL_OVERRIDE_CALLBACK = override_callback
    if defect_callback is not None:
        GLOBAL_DEFECT_CALLBACK = defect_callback

    if last_rec:
        LIVE_HUD_STATE["last_panel"] = {
            "sn": last_rec.get("sn", "-"),
            "order": last_rec.get("order", "-"),
            "summary": last_rec.get("summary", "-"),
            "class": last_rec.get("class", "-"),
            "result": last_rec.get("result", "-"),
            "line": last_rec.get("line", "-"),
            "shift": last_rec.get("shift", "-"),
            "layup_time": last_rec.get("layup_time", "-"),
            "station": last_rec.get("station", "-"),
            "photo_name": os.path.basename(last_rec.get("photo_path", "")) if last_rec.get("photo_path") else "-",
            "photo_path": last_rec.get("photo_path", ""),
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "status": "Linked OK"
        }

    if live_voice:
        LIVE_HUD_STATE["live_voice"] = live_voice

    if all_records is not None:
        LIVE_HUD_STATE["records"] = [
            {
                "sn": r.get("sn", "-"),
                "order": r.get("order", "-"),
                "summary": r.get("summary", "-"),
                "class": r.get("class", "-"),
                "result": r.get("result", "-"),
                "line": r.get("line", "-"),
                "shift": r.get("shift", "-"),
                "layup_time": r.get("layup_time", "-"),
                "station": r.get("station", "-"),
                "date": r.get("date", "-")
            }
            for r in all_records[:15]
        ]
        
        # Calculate statistics
        total = len(all_records)
        q3_count = sum(1 for r in all_records if str(r.get("result", "")).upper() == "Q3")
        scrap_count = sum(1 for r in all_records if "SCRAP" in str(r.get("result", "")).upper())

        defect_counts = {}
        line_counts = {f"Line {i}": 0 for i in range(1, 8)}
        for r in all_records:
            sm = r.get("summary", "")
            if sm and sm != "-":
                defect_counts[sm] = defect_counts.get(sm, 0) + 1
            ln = r.get("line", "")
            if ln in line_counts:
                line_counts[ln] += 1

        top_defects = []
        for name, count in sorted(defect_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
            pct = round((count / total * 100), 1) if total > 0 else 0
            top_defects.append({"name": name, "count": count, "pct": pct})

        LIVE_HUD_STATE["today_stats"] = {
            "total": total,
            "q3": q3_count,
            "scrap": scrap_count,
            "top_defects": top_defects,
            "line_counts": line_counts
        }


MOBILE_HUD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>Mobile Defect Control Panel</title>
<style>
  :root {
    --bg-main: #0b132b;
    --bg-card: #1c2541;
    --bg-subcard: #24325a;
    --primary: #3a86ff;
    --primary-active: #2563eb;
    --accent-q3: #f59e0b;
    --accent-scrap: #ef4444;
    --accent-ok: #10b981;
    --text-main: #f8fafc;
    --text-muted: #94a3b8;
    --border-color: #334155;

    /* Dynamic Customizable Layout Properties */
    --status-padding: {{STATUS_PADDING}};
    --status-sn-font: {{STATUS_SN_FONT}};
    --col-class-pct: {{COL_CLASS_PCT}};
    --col-summary-pct: {{COL_SUMMARY_PCT}};
    --grid-btn-padding: {{GRID_BTN_PADDING}};
    --grid-btn-font: {{GRID_BTN_FONT}};
    --action-btn-height: {{ACTION_BTN_HEIGHT}};
    --action-btn-font: {{ACTION_BTN_FONT}};
    --cam-btn-height: {{CAM_BTN_HEIGHT}};
    --cam-title-font: {{CAM_TITLE_FONT}};
    --element-gap: {{ELEMENT_GAP}};
    --border-radius: {{BORDER_RADIUS}};
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-tap-highlight-color: transparent; }
  body { background: var(--bg-main); color: var(--text-main); font-size: 14px; -webkit-font-smoothing: antialiased; padding-bottom: 95px; }

  /* App Top Bar */
  .app-header {
    background: #0f172a;
    padding: 12px 14px 8px 14px;
    border-bottom: 1px solid var(--border-color);
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .header-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .app-title { font-size: 15px; font-weight: 800; color: #fff; letter-spacing: 0.3px; }
  .pulse-badge { display: flex; align-items: center; font-size: 10px; font-weight: 700; color: var(--accent-ok); background: rgba(16, 185, 129, 0.15); padding: 3px 8px; border-radius: 12px; }
  .pulse-dot { width: 6px; height: 6px; background: var(--accent-ok); border-radius: 50%; margin-right: 5px; animation: blink 1.4s infinite; }
  @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

  /* Tab Navigation Switcher */
  .tab-nav {
    display: flex;
    background: #1e293b;
    border-radius: var(--border-radius);
    padding: 3px;
    gap: 4px;
  }
  .tab-btn {
    flex: 1;
    padding: 8px 4px;
    font-size: 12px;
    font-weight: 700;
    color: var(--text-muted);
    background: transparent;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    text-align: center;
    transition: all 0.2s;
  }
  .tab-btn.active {
    background: var(--primary);
    color: #ffffff;
    box-shadow: 0 2px 8px rgba(58, 134, 255, 0.4);
  }

  .tab-content { display: none; padding: 10px; }
  .tab-content.active {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 74px);
    box-sizing: border-box;
    overflow: hidden;
  }
  #tab-content-dashboard.active {
    display: block;
    overflow-y: auto;
    height: auto;
  }

  /* ================== TAB 1: DEFECT CONTROL PANEL ================== */
  
  /* 1. Status Summary Bar: SN - Defect - Grade */
  .status-summary-bar {
    display: flex;
    gap: 6px;
    margin-bottom: var(--element-gap);
    flex-shrink: 0;
  }
  .status-badge {
    flex: 1;
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: var(--status-padding) 4px;
    text-align: center;
    overflow: hidden;
  }
  .badge-lbl {
    display: block;
    font-size: 9px;
    font-weight: 800;
    color: var(--text-muted);
    letter-spacing: 0.5px;
    text-transform: uppercase;
    margin-bottom: 2px;
  }
  .status-badge strong {
    display: block;
    font-size: var(--status-sn-font);
    font-weight: 800;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .status-sn strong { color: #38bdf8; }
  .status-def strong { color: #34d399; }
  .status-grade strong { color: #f59e0b; }

  /* Two Column Control Grid in Middle */
  .control-grid {
    display: flex;
    gap: var(--element-gap);
    flex: 1;
    min-height: 140px;
    margin-bottom: var(--element-gap);
    overflow: hidden;
  }
  .col-panel {
    display: flex;
    flex-direction: column;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    overflow: hidden;
  }
  .col-class { width: var(--col-class-pct); }
  .col-summary { width: var(--col-summary-pct); }

  .col-header {
    background: #0f172a;
    padding: 7px 9px;
    font-size: 10px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border-color);
    flex-shrink: 0;
  }
  .col-scroll {
    flex: 1;
    overflow-y: auto;
    padding: 6px;
    -webkit-overflow-scrolling: touch;
  }

  /* Buttons */
  .grid-btn {
    width: 100%;
    padding: var(--grid-btn-padding) 8px;
    margin-bottom: 6px;
    font-size: var(--grid-btn-font);
    font-weight: 700;
    text-align: left;
    background: var(--bg-subcard);
    color: #e2e8f0;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    cursor: pointer;
    line-height: 1.25;
    transition: all 0.15s;
    word-break: break-word;
  }
  .grid-btn:active { transform: scale(0.98); }
  
  .grid-btn.active-class {
    background: #2563eb;
    color: #ffffff;
    border-color: #60a5fa;
    box-shadow: 0 2px 10px rgba(37, 99, 235, 0.4);
  }
  .grid-btn.active-summary {
    background: #059669;
    color: #ffffff;
    border-color: #34d399;
    box-shadow: 0 2px 10px rgba(5, 150, 105, 0.4);
  }

  /* Action Grid Rows */
  .action-grid-row {
    display: flex;
    gap: var(--element-gap);
    margin-bottom: var(--element-gap);
    flex-shrink: 0;
  }
  .btn-action {
    flex: 1;
    height: var(--action-btn-height);
    padding: 6px 10px;
    font-size: var(--action-btn-font);
    font-weight: 900;
    border-radius: var(--border-radius);
    border: 1px solid rgba(255,255,255,0.15);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    transition: transform 0.1s, box-shadow 0.1s;
    text-align: left;
  }
  .btn-action:active { transform: scale(0.97); }
  
  .btn-q3 {
    background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
    border-color: #fbbf24;
    color: #000000;
    box-shadow: 0 4px 14px rgba(245, 158, 11, 0.35);
  }
  .btn-scrap {
    background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
    border-color: #f87171;
    color: #ffffff;
    box-shadow: 0 4px 14px rgba(239, 68, 68, 0.35);
  }

  /* Camera Buttons */
  .cam-btn-sn {
    height: var(--cam-btn-height);
    background: linear-gradient(135deg, #1e3a8a 0%, #172554 100%);
    border-color: #3b82f6;
    color: #fff;
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
  }
  .cam-btn-def {
    height: var(--cam-btn-height);
    background: linear-gradient(135deg, #581c87 0%, #3b0764 100%);
    border-color: #a855f7;
    color: #fff;
    box-shadow: 0 4px 12px rgba(168, 85, 247, 0.25);
  }
  .cam-icon {
    font-size: 22px;
    line-height: 1;
    flex-shrink: 0;
  }
  .cam-info {
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .cam-title {
    font-size: var(--cam-title-font);
    font-weight: 800;
    color: #ffffff;
    white-space: nowrap;
  }
  .cam-sub {
    font-size: 9px;
    font-weight: 600;
    color: #94a3b8;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* Toast Notification */
  .toast {
    position: fixed;
    top: 70px;
    left: 50%;
    transform: translateX(-50%) translateY(-100px);
    background: #059669;
    color: #fff;
    font-weight: 700;
    font-size: 13px;
    padding: 10px 18px;
    border-radius: 30px;
    box-shadow: 0 6px 20px rgba(0,0,0,0.4);
    z-index: 300;
    transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    pointer-events: none;
    text-align: center;
    max-width: 90%;
  }
  .toast.show { transform: translateX(-50%) translateY(0); }

  /* ================== TAB 2: LIVE DASHBOARD ================== */
  .card { background: var(--bg-card); border-radius: 12px; padding: 12px; margin-bottom: 12px; border: 1px solid var(--border-color); }
  .card-title { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 8px; }
  .sn-display { font-size: 18px; font-weight: 800; color: #fff; word-break: break-all; margin-bottom: 6px; }
  .pill-row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .pill { font-size: 11px; font-weight: 700; padding: 4px 8px; border-radius: 6px; }
  .pill-defect { background: #2563eb; color: #fff; }
  .pill-q3 { background: rgba(245, 158, 11, 0.2); color: var(--accent-q3); border: 1px solid var(--accent-q3); }
  .pill-scrap { background: rgba(239, 68, 68, 0.2); color: var(--accent-scrap); border: 1px solid var(--accent-scrap); }
  .pill-line { background: #334155; color: #f1f5f9; }

  .meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px; background: var(--bg-subcard); padding: 8px 10px; border-radius: 8px; }
  .meta-item span { color: var(--text-muted); display: block; font-size: 10px; }
  .meta-item strong { color: #f8fafc; font-size: 11px; }

  .stats-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }
  .stat-card { background: var(--bg-subcard); padding: 8px; border-radius: 8px; text-align: center; }
  .stat-num { font-size: 18px; font-weight: 800; }
  .stat-label { font-size: 10px; color: var(--text-muted); font-weight: 600; text-transform: uppercase; }

  .bar-item { margin-bottom: 6px; }
  .bar-info { display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 2px; }
  .bar-container { background: #334155; height: 6px; border-radius: 3px; overflow: hidden; }
  .bar-fill { height: 100%; background: var(--primary); border-radius: 3px; }

  .recent-item { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 11px; }
  .recent-item:last-child { border-bottom: none; }

  /* HTTPS Upgrade Top Banner */
  .https-banner {
    display: none;
    background: linear-gradient(90deg, #1e3a8a, #0369a1);
    color: #ffffff;
    padding: 8px 12px;
    font-size: 11px;
    font-weight: 700;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid #38bdf8;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  }
  .btn-https-switch {
    background: #38bdf8;
    color: #0f172a;
    border: none;
    font-size: 11px;
    font-weight: 800;
    padding: 5px 12px;
    border-radius: 6px;
    cursor: pointer;
    box-shadow: 0 2px 6px rgba(0,0,0,0.25);
    transition: transform 0.1s;
  }
  .btn-https-switch:active { transform: scale(0.96); }

  /* Badge Paste Action Button */
  .badge-paste-btn {
    font-size: 9px;
    font-weight: 800;
    background: rgba(56, 189, 248, 0.25);
    color: #38bdf8;
    border: 1px solid rgba(56, 189, 248, 0.5);
    padding: 2px 7px;
    border-radius: 5px;
    cursor: pointer;
    display: inline-block;
    transition: all 0.15s;
  }
  .badge-paste-btn:active {
    background: #38bdf8;
    color: #0f172a;
  }

  /* Live Hardware QR / Barcode Scanner Modal */
  .scanner-modal {
    display: none;
    position: fixed;
    top: 0; left: 0; width: 100vw; height: 100vh;
    background: #000000;
    z-index: 500;
    flex-direction: column;
  }
  .scanner-modal.active { display: flex; }
  
  .scanner-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 16px;
    background: rgba(15, 23, 42, 0.95);
    backdrop-filter: blur(10px);
    z-index: 30;
  }
  .scanner-title { font-size: 14px; font-weight: 800; color: #fff; }
  .scanner-actions { display: flex; gap: 8px; align-items: center; }
  .scanner-btn-icon {
    background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.25);
    color: #fff; border-radius: 8px; padding: 6px 12px; font-size: 13px; font-weight: 700; cursor: pointer;
  }
  .scanner-btn-close {
    background: #ef4444; border: none; color: #fff; border-radius: 8px;
    padding: 6px 14px; font-size: 13px; font-weight: 800; cursor: pointer;
  }

  .scanner-viewport {
    flex: 1; position: relative; display: flex; align-items: center; justify-content: center;
    overflow: hidden; background: #000;
    touch-action: none;
  }
  #scanner-video {
    width: 100%; height: 100%; object-fit: cover;
    transition: transform 0.08s ease-out;
  }
  .scanner-reticle {
    position: absolute;
    width: 250px; height: 250px;
    border: 3px solid #38bdf8;
    border-radius: 24px;
    box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.65);
    pointer-events: none;
    transition: all 0.2s;
    z-index: 5;
  }
  .scanner-reticle.detected {
    border-color: #10b981;
    box-shadow: 0 0 35px rgba(16, 185, 129, 0.95), 0 0 0 9999px rgba(0, 0, 0, 0.65);
  }
  .scanner-laser {
    width: 100%; height: 3px;
    background: linear-gradient(90deg, transparent, #38bdf8, transparent);
    box-shadow: 0 0 12px #38bdf8;
    position: absolute; top: 0;
    animation: laserScan 1.6s infinite ease-in-out;
  }
  @keyframes laserScan {
    0% { top: 6%; opacity: 0.3; }
    50% { top: 94%; opacity: 1; }
    100% { top: 6%; opacity: 0.3; }
  }

  /* Scanner Zoom Floating Controls */
  .scanner-zoom-overlay {
    position: absolute;
    bottom: 60px;
    left: 50%;
    transform: translateX(-50%);
    width: 90%;
    max-width: 340px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    z-index: 25;
    pointer-events: auto;
  }
  .zoom-presets {
    display: flex;
    gap: 8px;
    background: rgba(15, 23, 42, 0.8);
    backdrop-filter: blur(8px);
    padding: 3px 8px;
    border-radius: 20px;
    border: 1px solid rgba(255, 255, 255, 0.18);
  }
  .zoom-chip {
    background: transparent;
    border: none;
    color: #cbd5e1;
    font-size: 11px;
    font-weight: 800;
    padding: 3px 11px;
    border-radius: 14px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .zoom-chip.active {
    background: #38bdf8;
    color: #0f172a;
    box-shadow: 0 0 12px rgba(56, 189, 248, 0.6);
  }
  .zoom-slider-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    background: rgba(15, 23, 42, 0.88);
    backdrop-filter: blur(10px);
    padding: 6px 12px;
    border-radius: 25px;
    border: 1px solid rgba(255, 255, 255, 0.22);
    width: 100%;
    box-sizing: border-box;
  }
  .zoom-step-btn {
    background: rgba(255, 255, 255, 0.15);
    border: none;
    color: #ffffff;
    font-size: 14px;
    font-weight: 900;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex-shrink: 0;
  }
  .zoom-step-btn:active {
    background: #38bdf8;
    color: #0f172a;
  }
  #scanner-zoom-slider {
    flex: 1;
    height: 6px;
    border-radius: 3px;
    background: #334155;
    outline: none;
    accent-color: #38bdf8;
    cursor: pointer;
  }
  .zoom-badge {
    font-size: 12px;
    font-weight: 800;
    font-family: 'Consolas', monospace;
    color: #38bdf8;
    min-width: 38px;
    text-align: right;
  }

  .scanner-hint {
    position: absolute; bottom: 15px;
    background: rgba(15, 23, 42, 0.9);
    color: #f8fafc; font-size: 11px; font-weight: 700;
    padding: 5px 16px; border-radius: 20px;
    backdrop-filter: blur(8px);
    border: 1px solid rgba(255,255,255,0.2);
    text-align: center;
    max-width: 85%;
    z-index: 10;
  }
  .scanner-footer {
    padding: 10px 14px; background: rgba(15, 23, 42, 0.95);
    display: flex; gap: 8px; justify-content: center;
    z-index: 30;
  }
  .scanner-fallback-btn {
    flex: 1;
    background: #334155; color: #f8fafc; border: 1px solid rgba(255,255,255,0.2);
    padding: 10px 10px; border-radius: 10px; font-size: 12px; font-weight: 700; cursor: pointer;
    text-align: center;
  }
  .scanner-fallback-btn.primary-fallback {
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    border-color: #60a5fa;
    color: #fff;
  }

  /* Sheet & Input Dialog Modals */
  .modal-overlay {
    display: none;
    position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
    background: rgba(0, 0, 0, 0.75);
    backdrop-filter: blur(6px);
    z-index: 400;
    align-items: center; justify-content: center;
    padding: 20px;
  }
  .modal-overlay.active { display: flex; }
  .dialog-card {
    background: #1e293b;
    border: 1px solid var(--border-color);
    border-radius: 16px;
    padding: 20px;
    width: 100%;
    max-width: 360px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.6);
  }
  .dialog-title {
    font-size: 16px; font-weight: 800; color: #fff; margin-bottom: 12px;
    display: flex; align-items: center; gap: 8px;
  }
  .dialog-sub {
    font-size: 12px; color: var(--text-muted); margin-bottom: 16px; line-height: 1.4;
  }
  .sheet-btn-option {
    width: 100%;
    display: flex; align-items: center; gap: 12px;
    background: #334155; color: #fff;
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 10px;
    padding: 12px 14px;
    margin-bottom: 10px;
    font-size: 13px; font-weight: 700;
    cursor: pointer;
    text-align: left;
    transition: all 0.15s;
  }
  .sheet-btn-option:active { transform: scale(0.98); background: #2563eb; }
  .sheet-btn-option.primary-option {
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    border-color: #60a5fa;
  }
  .dialog-input {
    width: 100%;
    padding: 12px 14px;
    background: #0f172a;
    border: 2px solid #38bdf8;
    border-radius: 10px;
    color: #fff;
    font-size: 16px;
    font-weight: 700;
    font-family: 'Consolas', monospace;
    margin-bottom: 14px;
    outline: none;
    box-sizing: border-box;
  }
  .dialog-actions {
    display: flex; gap: 8px;
  }
  .dialog-btn {
    flex: 1;
    padding: 10px;
    border-radius: 10px;
    border: none;
    font-size: 13px;
    font-weight: 800;
    cursor: pointer;
    text-align: center;
  }
  .dialog-btn-cancel { background: #475569; color: #fff; }
  .dialog-btn-save { background: #10b981; color: #fff; }
</style>
</head>
<body>

<div id="toast" class="toast">Defect Logged</div>

<!-- HTTPS Switch Banner for HTTP Clients -->
<div id="https-banner" class="https-banner">
  <div style="display: flex; align-items: center; gap: 6px;">
    <span style="font-size: 14px;">⚡</span>
    <span>Live Pixel 6a Camera Scanner available:</span>
  </div>
  <button onclick="switchToHTTPS()" class="btn-https-switch">Switch to HTTPS (:8443)</button>
</div>

<!-- Live Direct Hardware QR Scanner Modal -->
<div id="scanner-modal" class="scanner-modal">
  <div class="scanner-header">
    <div class="scanner-title">🏷️ Scan Barcode / QR Label</div>
    <div class="scanner-actions">
      <button class="scanner-btn-icon" id="btn-torch" onclick="toggleTorch()" title="Toggle Flashlight">💡 Torch</button>
      <button class="scanner-btn-icon" id="btn-flip" onclick="toggleCameraFacing()" title="Flip Camera">🔄 Flip</button>
      <button class="scanner-btn-close" onclick="closeLiveScanner()">✕ Close</button>
    </div>
  </div>

  <div class="scanner-viewport" id="scanner-viewport">
    <video id="scanner-video" playsinline autoplay muted></video>
    <canvas id="scanner-canvas" style="display: none;"></canvas>
    
    <div class="scanner-reticle" id="scanner-reticle">
      <div class="scanner-laser"></div>
    </div>
    
    <!-- Floating Zoom Controls Overlay -->
    <div class="scanner-zoom-overlay">
      <div class="zoom-presets">
        <button class="zoom-chip active" id="chip-1x" data-zoom="1.0" onclick="applyZoom(1.0)">1x</button>
        <button class="zoom-chip" id="chip-2x" data-zoom="2.0" onclick="applyZoom(2.0)">2x</button>
        <button class="zoom-chip" id="chip-3x" data-zoom="3.0" onclick="applyZoom(3.0)">3x</button>
        <button class="zoom-chip" id="chip-5x" data-zoom="5.0" onclick="applyZoom(5.0)">5x</button>
        <button class="zoom-chip" id="chip-7x" data-zoom="7.0" onclick="applyZoom(7.0)">7x Max</button>
      </div>
      <div class="zoom-slider-bar">
        <button class="zoom-step-btn" onclick="adjustZoomStep(-0.2)">－</button>
        <input type="range" id="scanner-zoom-slider" min="1" max="7" step="0.1" value="1" oninput="applyZoom(this.value)">
        <button class="zoom-step-btn" onclick="adjustZoomStep(0.2)">＋</button>
        <span class="zoom-badge" id="scanner-zoom-badge">1.0x</span>
      </div>
    </div>

    <div class="scanner-hint" id="scanner-hint">⚡ Align QR / Barcode in frame</div>
  </div>

  <div class="scanner-footer">
    <button class="scanner-fallback-btn primary-fallback" onclick="triggerFileCamera('SN_PHOTO')">📷 Take SN Photo (Native App)</button>
    <button class="scanner-fallback-btn" onclick="quickPasteSN()">📋 Paste SN</button>
  </div>
</div>

<!-- Barcode Options Modal (For HTTP / Fast Selection) -->
<div id="barcode-sheet-modal" class="modal-overlay" onclick="closeBarcodeSheetModal(event)">
  <div class="dialog-card" onclick="event.stopPropagation()">
    <div class="dialog-title">🏷️ Barcode & SN Options</div>
    <div class="dialog-sub">Choose how to ingest the module serial number:</div>

    <button class="sheet-btn-option primary-option" onclick="switchToHTTPS()">
      <span style="font-size: 20px;">⚡</span>
      <div>
        <div>Open Live Camera Scanner (with Zoom)</div>
        <div style="font-size: 10px; opacity: 0.8;">Opens HTTPS :8443 for instant in-page scan with zoom controls</div>
      </div>
    </button>

    <button class="sheet-btn-option" onclick="closeBarcodeSheetModal(); triggerFileCamera('SN_PHOTO');">
      <span style="font-size: 20px;">📷</span>
      <div>
        <div>Take Barcode Photo (Native Camera)</div>
        <div style="font-size: 10px; opacity: 0.8;">Use full Google Pixel optical zoom and scan photo</div>
      </div>
    </button>

    <button class="sheet-btn-option" onclick="closeBarcodeSheetModal(); quickPasteSN();">
      <span style="font-size: 20px;">📋</span>
      <div>
        <div>Paste from Pixel QR Scanner</div>
        <div style="font-size: 10px; opacity: 0.8;">Extracts copied text from Pixel Quick Tile</div>
      </div>
    </button>

    <button class="sheet-btn-option" onclick="closeBarcodeSheetModal(); openSNModal();">
      <span style="font-size: 20px;">✏️</span>
      <div>
        <div>Enter SN Manually</div>
        <div style="font-size: 10px; opacity: 0.8;">Type or edit serial number directly</div>
      </div>
    </button>

    <button class="dialog-btn dialog-btn-cancel" style="width: 100%; margin-top: 6px;" onclick="closeBarcodeSheetModal()">Close</button>
  </div>
</div>

<!-- Manual / Paste SN Input Dialog Modal -->
<div id="sn-input-modal" class="modal-overlay" onclick="closeSNModal(event)">
  <div class="dialog-card" onclick="event.stopPropagation()">
    <div class="dialog-title">✏️ Enter Module SN</div>
    <div class="dialog-sub">Paste text from Pixel QR scanner or type module serial number:</div>

    <input type="text" id="manual-sn-input" class="dialog-input" placeholder="e.g. V01268005042145" autocomplete="off" autocorrect="off" autocapitalize="characters">

    <button class="sheet-btn-option" style="margin-bottom: 12px; background: #0f172a; border-color: #38bdf8;" onclick="pasteIntoInputModal()">
      <span style="font-size: 16px;">📋</span>
      <span>Paste from Clipboard</span>
    </button>

    <div class="dialog-actions">
      <button class="dialog-btn dialog-btn-cancel" onclick="closeSNModal()">Cancel</button>
      <button class="dialog-btn dialog-btn-save" onclick="saveSNInput()">Save SN</button>
    </div>
  </div>
</div>

<div class="app-header">
  <div class="header-top">
    <div class="app-title">QC Mobile Suite</div>
    <div class="pulse-badge">
      <div class="pulse-dot"></div> <span id="sync-status">LIVE SYNC</span>
    </div>
  </div>
  <div class="tab-nav">
    <button class="tab-btn active" id="tab-btn-control" onclick="switchTab('control')">⚡ Defect Control Panel</button>
    <button class="tab-btn" id="tab-btn-dashboard" onclick="switchTab('dashboard')">📊 Live Dashboard</button>
  </div>
</div>

<!-- ================= TAB 1: DEFECT CONTROL PANEL ================= -->
<div id="tab-content-control" class="tab-content active">

  <!-- 1. Display: SN - Defect - Grade (Top) -->
  <div class="status-summary-bar">
    <div class="status-badge status-sn" onclick="openSNModal()" title="Tap to enter or paste SN">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
        <span class="badge-lbl" style="margin-bottom: 0;">SN</span>
        <div style="display: flex; gap: 3px;">
          <span class="badge-paste-btn" onclick="event.stopPropagation(); quickPasteSN();" title="Paste SN from Clipboard">📋 Paste</span>
          <span class="badge-paste-btn" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border-color: rgba(56, 189, 248, 0.4);" onclick="event.stopPropagation(); resetActivePanel();" title="Clear / Start Next Module">＋ Next</span>
        </div>
      </div>
      <strong id="disp-sn">Pending SN</strong>
    </div>
    <div class="status-badge status-def">
      <span class="badge-lbl">Defect</span>
      <strong id="disp-selected-summary">Select Below</strong>
    </div>
    <div class="status-badge status-grade">
      <span class="badge-lbl">Grade</span>
      <strong id="disp-grade">-</strong>
    </div>
  </div>

  <!-- 2. Two-Column Category & Defect Summary Picker (Middle) -->
  <div class="control-grid">
    <!-- Left Column: Classification -->
    <div class="col-panel col-class">
      <div class="col-header">1. Category</div>
      <div class="col-scroll" id="class-list"></div>
    </div>

    <!-- Right Column: Defect Summary -->
    <div class="col-panel col-summary">
      <div class="col-header">2. Defect Summary</div>
      <div class="col-scroll" id="summary-list"></div>
    </div>
  </div>

  <!-- 3. Q3 and Scrap Buttons (No LOG, Row 1 of Bottom Actions) -->
  <div class="action-grid-row">
    <button class="btn-action btn-q3" onclick="submitDefect('Q3')">
      <span>⚡ Q3</span>
    </button>
    <button class="btn-action btn-scrap" onclick="submitDefect('Scrap')">
      <span>💥 SCRAP</span>
    </button>
  </div>

  <!-- 4. Defect Photo (1, Left) and Barcode Scan (2, Right) -->
  <div class="action-grid-row" style="margin-bottom: 0;">
    <button class="btn-action cam-btn-def" id="btn-snap-def" onclick="triggerDefectCamera()">
      <span class="cam-icon">📸</span>
      <div class="cam-info">
        <div class="cam-title">1. Defect Photo</div>
        <div class="cam-sub" id="def-cam-status">Tap to snap (Zoom)</div>
      </div>
    </button>
    <button class="btn-action cam-btn-sn" id="btn-snap-sn" onclick="triggerBarcodeScanner()">
      <span class="cam-icon">🏷️</span>
      <div class="cam-info">
        <div class="cam-title">2. Barcode Scan</div>
        <div class="cam-sub" id="sn-cam-status">Tap to scan SN</div>
      </div>
    </button>
  </div>
  <input type="file" id="camera-file-input" accept="image/*" capture="environment" style="display: none;" onchange="onCameraPhotoCaptured(event)">

</div>

<!-- ================= TAB 2: LIVE DASHBOARD ================= -->
<div id="tab-content-dashboard" class="tab-content">
  <!-- Last Inspected Panel -->
  <div class="card">
    <div class="card-title">Last Inspected Module</div>
    <div class="sn-display" id="panel-sn">Ready for Inspection</div>
    <div class="pill-row">
      <span class="pill pill-defect" id="panel-defect">Awaiting Scan</span>
      <span class="pill pill-q3" id="panel-result">-</span>
      <span class="pill pill-line" id="panel-line">-</span>
    </div>
    <div class="meta-grid">
      <div class="meta-item"><span>Layup Time:</span><strong id="panel-layup">-</strong></div>
      <div class="meta-item"><span>Pre-EL Station:</span><strong id="panel-station">-</strong></div>
      <div class="meta-item"><span>Shift:</span><strong id="panel-shift">-</strong></div>
      <div class="meta-item"><span>Order No:</span><strong id="panel-order">-</strong></div>
    </div>
  </div>

  <!-- Shift Statistics -->
  <div class="card">
    <div class="card-title">Today's Shift Analytics</div>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-num" id="stat-total" style="color: #fff;">0</div><div class="stat-label">Total</div></div>
      <div class="stat-card"><div class="stat-num" id="stat-q3" style="color: var(--accent-q3);">0</div><div class="stat-label">Q3</div></div>
      <div class="stat-card"><div class="stat-num" id="stat-scrap" style="color: var(--accent-scrap);">0</div><div class="stat-label">Scrap</div></div>
    </div>

    <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); margin: 10px 0 6px 0;">TOP 5 DEFECTS:</div>
    <div id="top-defects-list">
      <div style="font-size: 11px; color: var(--text-muted);">No defects recorded yet today.</div>
    </div>
  </div>

  <!-- Recent Records -->
  <div class="card">
    <div class="card-title">Recent Inspections</div>
    <div id="recent-list">
      <div style="font-size: 11px; color: var(--text-muted);">Awaiting panels...</div>
    </div>
  </div>
</div>

<script>
const DEFECT_TREE = {{DEFECT_TREE_JSON}};

let selectedClass = Object.keys(DEFECT_TREE)[0] || "Cells Defect";
let selectedSummary = DEFECT_TREE[selectedClass] ? DEFECT_TREE[selectedClass][0] : "";
let currentPhotoType = 'DEFECT_PHOTO';
let currentSN = '';
let currentGrade = '-';

let activeMediaStream = null;
let liveScannerRunning = false;
let isTorchActive = false;
let currentFacingMode = "environment";
let lastCheckedClipboard = "";

// Show HTTPS Banner if loaded on plain HTTP
if (location.protocol === 'http:') {
  const hb = document.getElementById('https-banner');
  if (hb) hb.style.display = 'flex';
}

function switchToHTTPS() {
  const curPort = location.port || '8080';
  let targetPort = '8443';
  if (curPort === '8080') targetPort = '8443';
  else {
    const pNum = parseInt(curPort);
    targetPort = isNaN(pNum) ? '8443' : (pNum + 363).toString();
  }
  location.href = `https://${location.hostname}:${targetPort}/`;
}

// 1. Text Parsing & SN Extraction Helper
function extractSNFromText(text) {
  if (!text) return '';
  text = text.trim();
  
  // 1. Matches "Trina Solar V01268005042145" or "SN: V01268005042145"
  const mTrina = text.match(/(?:Trina\\s+Solar\\s+|SN:\\s*|S\\/N:\\s*)([A-Z0-9]{8,25})/i);
  if (mTrina) return mTrina[1];
  
  // 2. Solar module SN format starting with V / capital letter and digits (10-25 chars)
  const mV = text.match(/\\b([A-Z][0-9A-Z]{9,24})\\b/);
  if (mV) return mV[1];
  
  // 3. General 8-25 char alphanumeric code
  const mGen = text.match(/\\b([A-Z0-9]{8,25})\\b/i);
  if (mGen) return mGen[1];
  
  return text.replace(/\\s+/g, '');
}

// 2. Set Active Serial Number & Sync to Desktop App
async function setSerialNumber(sn, source = 'Manual') {
  if (!sn) return;
  currentSN = sn;
  const snEl = document.getElementById('disp-sn');
  if (snEl) snEl.innerText = sn;
  
  const statusEl = document.getElementById('sn-cam-status');
  if (statusEl) statusEl.innerHTML = `<span style="color:#10b981; font-weight:bold;">✅ ${sn.slice(-6)}</span>`;

  try {
    const ts = (Date.now() / 1000).toFixed(3);
    await fetch(`/api/upload_photo?type=SN_PHOTO&timestamp=${ts}&client_sn=${encodeURIComponent(sn)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: new Uint8Array(0)
    });
  } catch (e) {
    console.warn('SN Sync notice:', e);
  }
}

// 3. Quick Paste from Android System Clipboard
async function quickPasteSN() {
  if (navigator.clipboard && navigator.clipboard.readText) {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        const sn = extractSNFromText(text);
        if (sn && sn.length >= 6) {
          setSerialNumber(sn, 'Clipboard Paste');
          showToast(`✅ Pasted SN: ${sn}`);
          playScanBeep();
          if (navigator.vibrate) navigator.vibrate([60, 40, 60]);
          return;
        }
      }
    } catch (e) {
      console.warn('Clipboard direct read not permitted, opening modal:', e);
    }
  }
  openSNModal();
}

// 4. Auto-Clipboard Detection on App Focus (When returning from Pixel Quick Settings Scanner)
async function checkClipboardOnFocus() {
  if (!navigator.clipboard || !navigator.clipboard.readText) return;
  try {
    const text = await navigator.clipboard.readText();
    if (!text || text === lastCheckedClipboard) return;
    lastCheckedClipboard = text;
    const sn = extractSNFromText(text);
    if (sn && sn.length >= 8 && sn !== currentSN) {
      setSerialNumber(sn, 'Auto-Clipboard');
      showToast(`📋 Auto-detected SN from QR: ${sn}`);
      playScanBeep();
      if (navigator.vibrate) navigator.vibrate([60, 40, 60]);
    }
  } catch (e) {
    // Ignore background permission restrictions
  }
}

window.addEventListener('focus', () => setTimeout(checkClipboardOnFocus, 300));
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') setTimeout(checkClipboardOnFocus, 300);
});

// 5. Manual SN Input Dialog Modal
function openSNModal() {
  const modal = document.getElementById('sn-input-modal');
  const input = document.getElementById('manual-sn-input');
  input.value = currentSN && currentSN !== 'Pending SN' ? currentSN : '';
  modal.classList.add('active');
  setTimeout(() => input.focus(), 150);
}

function closeSNModal(e) {
  if (e && e.target !== document.getElementById('sn-input-modal')) return;
  document.getElementById('sn-input-modal').classList.remove('active');
}

async function pasteIntoInputModal() {
  if (navigator.clipboard && navigator.clipboard.readText) {
    try {
      const text = await navigator.clipboard.readText();
      const sn = extractSNFromText(text);
      if (sn) {
        document.getElementById('manual-sn-input').value = sn;
        return;
      }
    } catch(e) {}
  }
  const manual = prompt("Paste QR Code text here:");
  if (manual) {
    document.getElementById('manual-sn-input').value = extractSNFromText(manual);
  }
}

function saveSNInput() {
  const val = document.getElementById('manual-sn-input').value.trim();
  if (val) {
    const sn = extractSNFromText(val);
    setSerialNumber(sn, 'Manual Input');
    showToast(`✅ Serial Number set: ${sn}`);
    playScanBeep();
    if (navigator.vibrate) navigator.vibrate([40, 30, 40]);
  }
  document.getElementById('sn-input-modal').classList.remove('active');
}

// 6. Barcode Options Sheet Modal
function openBarcodeSheetModal() {
  document.getElementById('barcode-sheet-modal').classList.add('active');
}

function closeBarcodeSheetModal(e) {
  if (e && e.target !== document.getElementById('barcode-sheet-modal')) return;
  document.getElementById('barcode-sheet-modal').classList.remove('active');
}

// 7. Direct Live Hardware QR/Barcode Scanner (Google Pixel 6a / Android Chrome ML Kit)
let currentZoom = 1.0;
let zoomMin = 1.0;
let zoomMax = 8.0;
let zoomStep = 0.1;
let hasHardwareZoom = false;
let touchStartDist = 0;
let touchStartZoom = 1.0;

function resetActivePanel() {
  currentSN = '';
  currentGrade = '-';
  const snEl = document.getElementById('disp-sn');
  if (snEl) snEl.innerText = 'Pending SN';
  const gradeEl = document.getElementById('disp-grade');
  if (gradeEl) {
    gradeEl.innerText = '-';
    gradeEl.style.color = 'var(--text-muted)';
  }
  const snCamEl = document.getElementById('sn-cam-status');
  if (snCamEl) snCamEl.innerText = 'Tap to scan SN';
  const defCamEl = document.getElementById('def-cam-status');
  if (defCamEl) defCamEl.innerText = 'Tap to snap (Zoom)';
  showToast('Ready for Next Panel');
}

async function triggerBarcodeScanner() {
  // If in Secure Context (HTTPS or localhost) where live camera streaming is enabled
  if (window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    try {
      await openLiveScanner();
      return;
    } catch (err) {
      console.warn('Live camera stream not available, opening options sheet:', err);
    }
  }
  // If on HTTP or live stream denied, open user-friendly option sheet
  openBarcodeSheetModal();
}

function triggerDefectCamera() {
  // Opens native camera with 0.5x - 10x hardware optical zoom for micro defect close-ups
  triggerFileCamera('DEFECT_PHOTO');
}

function triggerFileCamera(type) {
  closeLiveScanner();
  currentPhotoType = type;
  const input = document.getElementById('camera-file-input');
  input.value = '';
  input.click();
}

function initZoomCapabilities() {
  currentZoom = 1.0;
  hasHardwareZoom = false;
  zoomMin = 1.0;
  zoomMax = 7.0;
  zoomStep = 0.1;

  if (activeMediaStream) {
    const track = activeMediaStream.getVideoTracks()[0];
    if (track) {
      const caps = track.getCapabilities ? track.getCapabilities() : {};
      const settings = track.getSettings ? track.getSettings() : {};

      if (caps.zoom) {
        hasHardwareZoom = true;
        zoomMin = caps.zoom.min || 1.0;
        zoomMax = caps.zoom.max || 7.0;
        zoomStep = caps.zoom.step || 0.1;
        currentZoom = settings.zoom || zoomMin;
        console.log(`[CAMERA ZOOM]: Hardware zoom active (${zoomMin}x - ${zoomMax}x, step ${zoomStep})`);
      } else {
        hasHardwareZoom = false;
        zoomMin = 1.0;
        zoomMax = 7.0;
        zoomStep = 0.1;
        console.log('[CAMERA ZOOM]: Using digital zoom scaling fallback up to 7x');
      }
    }
  }

  const slider = document.getElementById('scanner-zoom-slider');
  if (slider) {
    slider.min = zoomMin;
    slider.max = zoomMax;
    slider.step = zoomStep;
    slider.value = currentZoom;
  }
  updateZoomUI(currentZoom);
}

async function applyZoom(val) {
  val = Math.max(zoomMin, Math.min(zoomMax, parseFloat(val)));
  currentZoom = val;

  if (hasHardwareZoom && activeMediaStream) {
    const track = activeMediaStream.getVideoTracks()[0];
    if (track) {
      try {
        await track.applyConstraints({ advanced: [{ zoom: val }] });
      } catch (err) {
        console.warn('Hardware zoom constraint warning, using digital scaling:', err);
        applyDigitalZoom(val);
      }
    }
  } else {
    applyDigitalZoom(val);
  }
  updateZoomUI(val);
}

function applyDigitalZoom(val) {
  const video = document.getElementById('scanner-video');
  if (video) {
    video.style.transform = `scale(${val})`;
    video.style.transformOrigin = 'center center';
  }
}

function updateZoomUI(val) {
  const badge = document.getElementById('scanner-zoom-badge');
  if (badge) badge.innerText = `${parseFloat(val).toFixed(1)}x`;
  const slider = document.getElementById('scanner-zoom-slider');
  if (slider && Math.abs(parseFloat(slider.value) - parseFloat(val)) > 0.05) {
    slider.value = val;
  }
  document.querySelectorAll('.zoom-chip').forEach(chip => {
    const chipVal = parseFloat(chip.getAttribute('data-zoom'));
    chip.classList.toggle('active', Math.abs(chipVal - val) < 0.18);
  });
}

function adjustZoomStep(delta) {
  applyZoom(currentZoom + delta);
}

function setupPinchToZoom() {
  const viewport = document.getElementById('scanner-viewport');
  if (!viewport || viewport._pinchBound) return;
  viewport._pinchBound = true;

  viewport.addEventListener('touchstart', (e) => {
    if (e.touches.length === 2) {
      touchStartDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      touchStartZoom = currentZoom;
    }
  }, { passive: true });

  viewport.addEventListener('touchmove', (e) => {
    if (e.touches.length === 2 && touchStartDist > 0) {
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      const factor = dist / touchStartDist;
      applyZoom(touchStartZoom * factor);
    }
  }, { passive: true });

  viewport.addEventListener('touchend', (e) => {
    if (e.touches.length < 2) {
      touchStartDist = 0;
    }
  });

  // Double tap to toggle 1x / 2.5x
  let lastTap = 0;
  viewport.addEventListener('click', (e) => {
    if (e.target.closest('.scanner-zoom-overlay') || e.target.closest('.scanner-actions')) return;
    const now = Date.now();
    if (now - lastTap < 350) {
      applyZoom(currentZoom > 1.8 ? 1.0 : 2.5);
    }
    lastTap = now;
  });
}

async function openLiveScanner() {
  const modal = document.getElementById('scanner-modal');
  const video = document.getElementById('scanner-video');
  const reticle = document.getElementById('scanner-reticle');
  const hint = document.getElementById('scanner-hint');

  modal.classList.add('active');
  reticle.classList.remove('detected');
  hint.innerText = '⚡ Align QR / Barcode in frame';
  isTorchActive = false;

  const constraints = {
    video: {
      facingMode: { ideal: currentFacingMode },
      width: { ideal: 1920 },
      height: { ideal: 1080 }
    }
  };

  activeMediaStream = await navigator.mediaDevices.getUserMedia(constraints);
  video.srcObject = activeMediaStream;
  await video.play();

  // Initialize zoom controls & pinch listener
  initZoomCapabilities();
  setupPinchToZoom();

  liveScannerRunning = true;
  startLiveDetectionLoop();
}

function closeLiveScanner() {
  liveScannerRunning = false;
  const modal = document.getElementById('scanner-modal');
  modal.classList.remove('active');

  const video = document.getElementById('scanner-video');
  if (video) video.style.transform = 'none';

  if (activeMediaStream) {
    activeMediaStream.getTracks().forEach(track => track.stop());
    activeMediaStream = null;
  }
}

async function toggleCameraFacing() {
  currentFacingMode = (currentFacingMode === "environment") ? "user" : "environment";
  closeLiveScanner();
  setTimeout(() => openLiveScanner(), 200);
}

async function toggleTorch() {
  if (!activeMediaStream) return;
  const track = activeMediaStream.getVideoTracks()[0];
  if (!track) return;

  try {
    const caps = track.getCapabilities ? track.getCapabilities() : {};
    if (caps.torch) {
      isTorchActive = !isTorchActive;
      await track.applyConstraints({ advanced: [{ torch: isTorchActive }] });
      document.getElementById('btn-torch').style.background = isTorchActive ? '#f59e0b' : 'rgba(255,255,255,0.15)';
    } else {
      showToast('Flashlight not supported on this stream');
    }
  } catch (e) {
    console.warn('Torch error:', e);
  }
}

function playScanBeep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(980, ctx.currentTime);
    gain.gain.setValueAtTime(0.25, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.12);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.12);
  } catch(e) {}
}

async function startLiveDetectionLoop() {
  const video = document.getElementById('scanner-video');
  const reticle = document.getElementById('scanner-reticle');
  const hint = document.getElementById('scanner-hint');

  // Use Pixel 6a native hardware BarcodeDetector
  let detector = null;
  if ('BarcodeDetector' in window) {
    try {
      detector = new BarcodeDetector({ formats: ['qr_code', 'code_128', 'code_39', 'data_matrix', 'ean_13', 'upc_a'] });
    } catch(e) {}
  }

  while (liveScannerRunning) {
    if (video.readyState >= 2 && detector) {
      try {
        const barcodes = await detector.detect(video);
        if (barcodes && barcodes.length > 0) {
          const raw = barcodes[0].rawValue.trim();
          const cleanSN = extractSNFromText(raw);
          if (cleanSN && cleanSN.length >= 6) {
            // Instant Lock!
            liveScannerRunning = false;
            reticle.classList.add('detected');
            hint.innerHTML = `<span style="color:#10b981; font-weight:bold;">✅ Found: ${cleanSN}</span>`;
            
            playScanBeep();
            if (navigator.vibrate) navigator.vibrate([60, 40, 60]);

            // Snap high-res frame and upload directly
            captureAndUploadLiveFrame(video, cleanSN);
            
            setTimeout(() => {
              closeLiveScanner();
            }, 350);
            return;
          }
        }
      } catch (detErr) {
        // continue
      }
    }
    await new Promise(r => setTimeout(r, 60)); // Fast ~16 FPS detection loop
  }
}

async function captureAndUploadLiveFrame(video, detectedSN) {
  setSerialNumber(detectedSN, 'Live Scanner');
  showToast(`✅ Scanned SN: ${detectedSN}`);

  const canvas = document.getElementById('scanner-canvas');
  const vw = video.videoWidth || 1280;
  const vh = video.videoHeight || 720;
  canvas.width = vw;
  canvas.height = vh;
  const ctx = canvas.getContext('2d');

  if (!hasHardwareZoom && currentZoom > 1.05) {
    const cropW = vw / currentZoom;
    const cropH = vh / currentZoom;
    const sx = (vw - cropW) / 2;
    const sy = (vh - cropH) / 2;
    ctx.drawImage(video, sx, sy, cropW, cropH, 0, 0, vw, vh);
  } else {
    ctx.drawImage(video, 0, 0, vw, vh);
  }

  canvas.toBlob(async (blob) => {
    if (!blob) return;
    try {
      const ts = (Date.now() / 1000).toFixed(3);
      const snParam = `&client_sn=${encodeURIComponent(detectedSN)}`;
      await fetch(`/api/upload_photo?type=SN_PHOTO&timestamp=${ts}${snParam}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: blob
      });
    } catch(e) {
      console.warn('Live snapshot upload error:', e);
    }
  }, 'image/jpeg', 0.92);
}

// 8. Direct On-Device Pixel 6a Scanner for Photo Capture Fallback
async function onCameraPhotoCaptured(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;

  const type = currentPhotoType;
  const statusEl = document.getElementById(type === 'SN_PHOTO' ? 'sn-cam-status' : 'def-cam-status');
  
  if (statusEl) statusEl.innerText = type === 'SN_PHOTO' ? '⏳ Scanning QR...' : '⏳ Uploading...';
  showToast(`Uploading ${type === 'SN_PHOTO' ? 'Barcode' : 'Defect'} photo...`);

  // Instant hardware BarcodeDetector on Google Pixel 6a (<5ms)
  let clientDetectedSN = '';
  if (type === 'SN_PHOTO' && 'BarcodeDetector' in window) {
    try {
      const detector = new BarcodeDetector({ formats: ['qr_code', 'code_128', 'code_39', 'data_matrix', 'ean_13', 'upc_a'] });
      const imgBitmap = await createImageBitmap(file);
      const detected = await detector.detect(imgBitmap);
      if (detected && detected.length > 0) {
        const raw = detected[0].rawValue.trim();
        clientDetectedSN = extractSNFromText(raw);
        if (clientDetectedSN) {
          setSerialNumber(clientDetectedSN, 'Photo BarcodeDetector');
          playScanBeep();
          if (navigator.vibrate) navigator.vibrate([40, 30, 40]);
        }
      }
    } catch (detErr) {
      console.warn('BarcodeDetector error:', detErr);
    }
  }

  // Stream Photo directly to PC Server
  try {
    const ts = (Date.now() / 1000).toFixed(3);
    const snToUse = clientDetectedSN || (currentSN && currentSN !== 'Pending SN' ? currentSN : '');
    const snParam = snToUse ? `&client_sn=${encodeURIComponent(snToUse)}` : '';
    const res = await fetch(`/api/upload_photo?type=${type}&timestamp=${ts}${snParam}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file
    });

    if (res.ok) {
      const data = await res.json();
      if (navigator.vibrate) navigator.vibrate([40, 30, 40]);
      
      if (type === 'SN_PHOTO') {
        const finalSN = data.sn || clientDetectedSN;
        if (finalSN) {
          setSerialNumber(finalSN, 'Server SN');
          showToast(`✅ Scanned SN: ${finalSN}`);
        } else {
          if (statusEl) statusEl.innerHTML = `<span style="color:#10b981;">✅ Uploaded</span>`;
          showToast('✅ Barcode photo uploaded');
        }
      } else {
        if (statusEl) statusEl.innerHTML = `<span style="color:#a855f7; font-weight:bold;">✅ Defect Saved</span>`;
        showToast('✅ Defect photo uploaded');
      }
    } else {
      if (statusEl) statusEl.innerText = '❌ Upload failed';
      showToast('❌ Upload failed', true);
    }
  } catch (err) {
    if (statusEl) statusEl.innerText = '❌ Error';
    showToast('❌ Connection error to PC', true);
  }
}

function renderClasses() {
  const container = document.getElementById('class-list');
  if (!container) return;
  container.innerHTML = Object.keys(DEFECT_TREE).map(cls => `
    <button class="grid-btn ${cls === selectedClass ? 'active-class' : ''}" onclick="selectClass('${cls.replace(/'/g, "\\'")}')">
      ${cls}
    </button>
  `).join('');
}

function renderSummaries() {
  const container = document.getElementById('summary-list');
  if (!container) return;
  const items = DEFECT_TREE[selectedClass] || [];
  container.innerHTML = items.map(sum => `
    <button class="grid-btn ${sum === selectedSummary ? 'active-summary' : ''}" onclick="selectSummary('${sum.replace(/'/g, "\\'")}')">
      ${sum}
    </button>
  `).join('');
}

function selectClass(cls) {
  selectedClass = cls;
  const items = DEFECT_TREE[cls] || [];
  if (!items.includes(selectedSummary)) {
    selectedSummary = items[0] || cls;
  }
  updateSelectedDisplay();
  renderClasses();
  renderSummaries();
}

function selectSummary(sum) {
  selectedSummary = sum;
  updateSelectedDisplay();
  renderSummaries();
  if (navigator.vibrate) navigator.vibrate(25);
}

function updateSelectedDisplay() {
  const el = document.getElementById('disp-selected-summary');
  if (el) el.innerText = selectedSummary || 'Select Below';
}

async function submitDefect(resultGrade) {
  if (!selectedSummary) {
    showToast('Please select a defect first!', true);
    return;
  }
  if (navigator.vibrate) navigator.vibrate([50, 30, 50]);

  currentGrade = resultGrade;
  const gradeEl = document.getElementById('disp-grade');
  if (gradeEl) {
    gradeEl.innerText = resultGrade;
    gradeEl.style.color = (resultGrade === 'Scrap') ? '#ef4444' : '#f59e0b';
  }

  const payload = {
    sn: currentSN && currentSN !== 'Pending SN' ? currentSN : '',
    class: selectedClass,
    summary: selectedSummary,
    result: resultGrade,
    timestamp: Date.now() / 1000
  };

  try {
    const res = await fetch('/api/mobile_defect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      showToast(`Logged: ${selectedSummary} (${resultGrade})`);
    } else {
      showToast('Error sending to PC', true);
    }
  } catch (err) {
    showToast('Cannot reach PC server', true);
  }
}

function showToast(msg, isError = false) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.innerText = msg;
  t.style.background = isError ? '#dc2626' : '#059669';
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

function switchTab(tabId) {
  document.getElementById('tab-btn-control').classList.toggle('active', tabId === 'control');
  document.getElementById('tab-btn-dashboard').classList.toggle('active', tabId === 'dashboard');
  document.getElementById('tab-content-control').classList.toggle('active', tabId === 'control');
  document.getElementById('tab-content-dashboard').classList.toggle('active', tabId === 'dashboard');
  if (tabId === 'dashboard') {
    fetchDashboardStatus();
  }
}

async function fetchDashboardStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    const data = await res.json();

    const p = data.last_panel || {};
    if (p.sn && p.sn !== 'Pending SN' && !currentSN) {
      const snEl = document.getElementById('disp-sn');
      if (snEl) snEl.innerText = p.sn;
    }
    if (p.result && p.result !== '-' && currentGrade === '-') {
      const gradeEl = document.getElementById('disp-grade');
      if (gradeEl) {
        gradeEl.innerText = p.result;
        gradeEl.style.color = (p.result === 'Scrap') ? '#ef4444' : '#f59e0b';
      }
    }

    const panelSn = document.getElementById('panel-sn');
    if (panelSn) panelSn.innerText = p.sn || 'Ready for Inspection';
    
    const panelDef = document.getElementById('panel-defect');
    if (panelDef) panelDef.innerText = p.summary || 'Awaiting Scan';
    
    const resEl = document.getElementById('panel-result');
    if (resEl) {
      resEl.innerText = p.result || '-';
      resEl.className = 'pill ' + (p.result === 'Scrap' ? 'pill-scrap' : 'pill-q3');
    }

    const setTxt = (id, txt) => {
      const el = document.getElementById(id);
      if (el) el.innerText = txt || '-';
    };

    setTxt('panel-line', p.line);
    setTxt('panel-shift', p.shift);
    setTxt('panel-layup', p.layup_time);
    setTxt('panel-station', p.station);
    setTxt('panel-order', p.order);

    const s = data.today_stats || {};
    setTxt('stat-total', s.total || 0);
    setTxt('stat-q3', s.q3 || 0);
    setTxt('stat-scrap', s.scrap || 0);

    const topDefContainer = document.getElementById('top-defects-list');
    if (topDefContainer) {
      if (s.top_defects && s.top_defects.length > 0) {
        topDefContainer.innerHTML = s.top_defects.map(d => `
          <div class="bar-item">
            <div class="bar-info">
              <span style="font-weight: 600;">${d.name}</span>
              <span style="color: var(--text-muted);">${d.count} (${d.pct}%)</span>
            </div>
            <div class="bar-container">
              <div class="bar-fill" style="width: ${d.pct}%;"></div>
            </div>
          </div>
        `).join('');
      } else {
        topDefContainer.innerHTML = '<div style="font-size: 11px; color: var(--text-muted);">No defects recorded yet today.</div>';
      }
    }

    const recContainer = document.getElementById('recent-list');
    if (recContainer && data.records && data.records.length > 0) {
      recContainer.innerHTML = data.records.slice(0, 8).map(r => `
        <div class="recent-item">
          <div>
            <strong style="color: #fff;">${r.sn}</strong>
            <div style="color: var(--text-muted); font-size: 10px;">${r.summary} | ${r.line}</div>
          </div>
          <span class="pill ${r.result === 'Scrap' ? 'pill-scrap' : 'pill-q3'}" style="font-size: 10px; padding: 2px 6px;">${r.result}</span>
        </div>
      `).join('');
    }

    const syncEl = document.getElementById('sync-status');
    if (syncEl) syncEl.innerText = 'LIVE SYNC';
  } catch (err) {
    const syncEl = document.getElementById('sync-status');
    if (syncEl) syncEl.innerText = 'RECONNECTING...';
  }
}

// Init
renderClasses();
renderSummaries();
updateSelectedDisplay();
setInterval(fetchDashboardStatus, 2000);
</script>
</body>
</html>
"""

def render_mobile_hud_html():
    cfg_layout = getattr(config, 'MOBILE_LAYOUT_SETTINGS', {})
    html = MOBILE_HUD_HTML.replace('{{DEFECT_TREE_JSON}}', json.dumps(config.DEFECT_TREE))
    html = html.replace('{{STATUS_PADDING}}', cfg_layout.get('status_padding', '7px'))
    html = html.replace('{{STATUS_SN_FONT}}', cfg_layout.get('status_sn_font', '13px'))
    html = html.replace('{{COL_CLASS_PCT}}', cfg_layout.get('col_class_pct', '44%'))
    html = html.replace('{{COL_SUMMARY_PCT}}', cfg_layout.get('col_summary_pct', '56%'))
    html = html.replace('{{GRID_BTN_PADDING}}', cfg_layout.get('grid_btn_padding', '11px'))
    html = html.replace('{{GRID_BTN_FONT}}', cfg_layout.get('grid_btn_font', '12px'))
    html = html.replace('{{ACTION_BTN_HEIGHT}}', cfg_layout.get('action_btn_height', '52px'))
    html = html.replace('{{ACTION_BTN_FONT}}', cfg_layout.get('action_btn_font', '16px'))
    html = html.replace('{{CAM_BTN_HEIGHT}}', cfg_layout.get('cam_btn_height', '52px'))
    html = html.replace('{{CAM_TITLE_FONT}}', cfg_layout.get('cam_title_font', '13px'))
    html = html.replace('{{ELEMENT_GAP}}', cfg_layout.get('element_gap', '8px'))
    html = html.replace('{{BORDER_RADIUS}}', cfg_layout.get('border_radius', '10px'))
    return html

GLOBAL_APP_CALLBACK = None

class MobileHUDHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ('/', '/hud', '/index.html'):
            html_content = render_mobile_hud_html()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(html_content.encode('utf-8'))
            return

        if path in ('/designer', '/design', '/designer.html'):
            designer_path = os.path.join(config.LOCAL_DATA_DIR, 'mobile_designer.html')
            if not os.path.exists(designer_path):
                # Fallback to artifact or app folder
                alt = os.path.join(os.path.dirname(__file__), 'mobile_designer.html')
                if os.path.exists(alt): designer_path = alt
            if os.path.exists(designer_path):
                with open(designer_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
                return

        if path == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(LIVE_HUD_STATE).encode('utf-8'))
            return

        if path.startswith('/photos/'):
            fname = os.path.basename(urllib.parse.unquote(path[8:]))
            target = os.path.join(LOCAL_UPLOADS_DIR, fname)
            if not os.path.exists(target):
                target = os.path.join(LOCAL_CACHE_DIR, fname)
            if os.path.exists(target):
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.end_headers()
                with open(target, 'rb') as f:
                    self.wfile.write(f.read())
                return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path.startswith('/api/save_custom_layout'):
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                data = json.loads(body)
                if isinstance(data, dict):
                    if not hasattr(config, 'MOBILE_LAYOUT_SETTINGS'):
                        config.MOBILE_LAYOUT_SETTINGS = {}
                    config.MOBILE_LAYOUT_SETTINGS.update(data)
                    config.save_persistent_settings()
                    print(f"[MOBILE LAYOUT UPDATED]: {data}")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok'}).encode('utf-8'))
                return
            except Exception as e:
                print(f"[LAYOUT UPDATE ERROR]: {e}")
                self.send_response(500)
                self.end_headers()
                return

        if self.path.startswith('/api/upload_photo'):
            try:
                parsed_url = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed_url.query)
                photo_hint = params.get('type', ['AUTO'])[0]
                client_sn = params.get('client_sn', [''])[0].strip()
                ts_str = params.get('timestamp', [None])[0]
                file_dt = datetime.fromtimestamp(float(ts_str)) if ts_str else datetime.now()

                length = int(self.headers.get('Content-Length', 0))
                if length == 0:
                    if client_sn:
                        # Direct SN sync from Mobile Hub without image file
                        print(f"[MOBILE SN SYNC]: Received client_sn '{client_sn}'")
                        if GLOBAL_APP_CALLBACK:
                            try:
                                GLOBAL_APP_CALLBACK(
                                    file_path="",
                                    extracted_sn=client_sn,
                                    action="SN_PHOTO",
                                    file_dt=file_dt
                                )
                            except Exception as cb_err:
                                print(f"[SN SYNC DISPATCH ERROR]: {cb_err}")
                        resp_data = {'status': 'ok', 'action': 'SN_PHOTO', 'sn': client_sn, 'filename': ''}
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps(resp_data).encode('utf-8'))
                        return
                    else:
                        self.send_response(400)
                        self.end_headers()
                        return

                img_bytes = self.rfile.read(length)
                ts_tag = int(time.time() * 1000)
                raw_fname = f"MobileSnap_{ts_tag}.jpg"
                save_path = os.path.join(LOCAL_UPLOADS_DIR, raw_fname)
                with open(save_path, 'wb') as f:
                    f.write(img_bytes)

                # Normalize EXIF orientation on save so portrait photos remain portrait everywhere
                try:
                    from PIL import Image as PIL_Img, ImageOps as PIL_Ops
                    with PIL_Img.open(save_path) as p_img:
                        transposed = PIL_Ops.exif_transpose(p_img)
                        if transposed is not None:
                            transposed.save(save_path, quality=95)
                except Exception: pass

                mark_photo_processed(raw_fname, save_path)
                print(f"[MOBILE CAMERA SNAP]: Received {raw_fname} ({len(img_bytes)} bytes) Mode: {photo_hint} ClientSN: '{client_sn}'")

                # Barcode / SN detection (Run ONLY for SN_PHOTO; skip completely for DEFECT_PHOTO)
                found_sn = ""
                action = "DEFECT_PHOTO"

                if photo_hint == "SN_PHOTO":
                    action = "SN_PHOTO"
                    if client_sn:
                        found_sn = client_sn
                    if not found_sn:
                        found_sn = extract_sn_from_photo(save_path)

                final_path = save_path
                if found_sn:
                    final_path = rename_to_sn_pattern(save_path, "SN", found_sn, LOCAL_CACHE_DIR)
                elif photo_hint == "DEFECT_PHOTO":
                    active_sn = LIVE_HUD_STATE.get("last_panel", {}).get("sn", "")
                    if active_sn and active_sn not in ("Pending SN", "-", "None", ""):
                        final_path = rename_to_sn_pattern(save_path, "Def", active_sn, LOCAL_CACHE_DIR)

                mark_photo_processed(final_path, os.path.basename(final_path))

                # Dispatch to desktop app callback
                if GLOBAL_APP_CALLBACK:
                    try:
                        GLOBAL_APP_CALLBACK(
                            file_path=final_path,
                            extracted_sn=found_sn,
                            action=action,
                            file_dt=file_dt
                        )
                    except Exception as cb_err:
                        print(f"[PHOTO DISPATCH ERROR]: {cb_err}")

                resp_data = {
                    'status': 'ok',
                    'action': action,
                    'sn': found_sn or '',
                    'filename': os.path.basename(final_path)
                }
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(resp_data).encode('utf-8'))
                return
            except Exception as e:
                print(f"[MOBILE UPLOAD ERROR]: {e}")
                self.send_response(500)
                self.end_headers()
                return

        if self.path == '/api/mobile_defect':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                data = json.loads(body)
                
                def_sn = data.get('sn', '').strip()
                def_class = data.get('class', '')
                def_summary = data.get('summary', '')
                def_result = data.get('result', 'Q3')
                def_ts = data.get('timestamp', time.time())
                def_dt = datetime.fromtimestamp(def_ts)

                print(f"[MOBILE DEFECT LOGGED]: SN: '{def_sn}' | {def_summary} ({def_class}) -> {def_result} at {def_dt.strftime('%H:%M:%S')}")

                if "last_panel" not in LIVE_HUD_STATE:
                    LIVE_HUD_STATE["last_panel"] = {}
                if def_sn:
                    LIVE_HUD_STATE["last_panel"]["sn"] = def_sn
                LIVE_HUD_STATE["last_panel"]["summary"] = def_summary
                LIVE_HUD_STATE["last_panel"]["class"] = def_class
                LIVE_HUD_STATE["last_panel"]["result"] = def_result

                if GLOBAL_DEFECT_CALLBACK:
                    try:
                        GLOBAL_DEFECT_CALLBACK({
                            'sn': def_sn,
                            'class': def_class,
                            'summary': def_summary,
                            'result': def_result,
                            'dt': def_dt
                        })
                    except Exception as cb_err:
                        print(f"[CALLBACK DISPATCH]: {cb_err}")

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok'}).encode('utf-8'))
                return

            except Exception as e:
                print(f"[MOBILE DEFECT ERROR]: {e}")
                self.send_response(500)
                self.end_headers()
                return

        self.send_response(404)
        self.end_headers()

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass
        except Exception as e:
            pass

    def log_message(self, format, *args):
        pass  # Suppress console clutter


def ensure_ssl_certificates():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    cert_path = os.path.join(app_dir, "server.crt")
    key_path = os.path.join(app_dir, "server.key")
    if os.path.exists(cert_path) and os.path.exists(key_path) and os.path.getsize(cert_path) > 0 and os.path.getsize(key_path) > 0:
        return cert_path, key_path

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import datetime as dt_module
        import ipaddress

        local_ip_str = get_local_ip()
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "QC Mobile Suite"),
            x509.NameAttribute(NameOID.COMMON_NAME, local_ip_str),
        ])
        
        san_list = [
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.DNSName("localhost")
        ]
        try:
            san_list.append(x509.IPAddress(ipaddress.ip_address(local_ip_str)))
        except Exception:
            san_list.append(x509.DNSName(local_ip_str))

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(dt_module.datetime.utcnow() - dt_module.timedelta(days=1))
            .not_valid_after(dt_module.datetime.utcnow() + dt_module.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName(san_list),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        print(f"[SSL CERT GENERATED]: Created {cert_path}")
        return cert_path, key_path
    except Exception as e:
        print(f"[SSL CERT ERROR]: {e}")
        return None, None


GLOBAL_HUD_HTTP_URL = ""
GLOBAL_HUD_HTTPS_URL = ""
GLOBAL_HUD_URL = ""

def get_mobile_hud_url() -> str:
    global GLOBAL_HUD_URL, GLOBAL_HUD_HTTPS_URL, GLOBAL_HUD_HTTP_URL
    if GLOBAL_HUD_HTTPS_URL:
        return GLOBAL_HUD_HTTPS_URL
    if GLOBAL_HUD_URL:
        return GLOBAL_HUD_URL
    return f"http://{get_local_ip()}:8080"


def start_mobile_hud_server(port: int = 8080, ssl_port: int = 8443) -> str:
    global GLOBAL_HUD_URL, GLOBAL_HUD_HTTP_URL, GLOBAL_HUD_HTTPS_URL
    local_ip = get_local_ip()

    # 1. Start HTTP Server (port 8080)
    for p in range(port, port + 5):
        try:
            httpd = ThreadingHTTPServer(('', p), MobileHUDHTTPHandler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            GLOBAL_HUD_HTTP_URL = f"http://{local_ip}:{p}"
            print(f"[MOBILE HTTP HUD]: Running at {GLOBAL_HUD_HTTP_URL}")
            break
        except Exception as http_err:
            print(f"[HTTP SERVER START NOTICE on port {p}]: {http_err}")
            continue

    # 2. Start HTTPS Server (port 8443) for Pixel 6a Direct Live Scanner
    cert_p, key_p = ensure_ssl_certificates()
    if cert_p and key_p and os.path.exists(cert_p) and os.path.exists(key_p):
        import ssl
        for sp in range(ssl_port, ssl_port + 5):
            try:
                httpsd = ThreadingHTTPServer(('', sp), MobileHUDHTTPHandler)
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(certfile=cert_p, keyfile=key_p)
                httpsd.socket = context.wrap_socket(httpsd.socket, server_side=True)
                threading.Thread(target=httpsd.serve_forever, daemon=True).start()
                GLOBAL_HUD_HTTPS_URL = f"https://{local_ip}:{sp}"
                print(f"[MOBILE HTTPS LIVE HUD (PIXEL 6A HARDWARE SCANNER)]: Running at {GLOBAL_HUD_HTTPS_URL}")
                break
            except Exception as ssl_err:
                print(f"[HTTPS SERVER START NOTICE on port {sp}]: {ssl_err}")
                continue

    GLOBAL_HUD_URL = GLOBAL_HUD_HTTPS_URL if GLOBAL_HUD_HTTPS_URL else GLOBAL_HUD_HTTP_URL
    return GLOBAL_HUD_URL


def start_phone_server(callback_fn, defect_callback=None):
    global GLOBAL_APP_CALLBACK
    GLOBAL_APP_CALLBACK = callback_fn
    ensure_defect_sample_folders()
    scan_and_train_from_sample_folders()
    active_path = start_smart_today_copier(callback_fn)
    start_mac_mini_relay_client(callback_fn)
    
    # Start Mobile Live Web HUD (Dual HTTP :8080 and HTTPS :8443)
    hud_port = getattr(config, 'MOBILE_HUD_PORT', 8080)
    hud_url = start_mobile_hud_server(hud_port, 8443)
    update_live_hud_state(defect_callback=defect_callback)

    cam_dirs, rec_dirs = find_phone_directories()
    phone_link_status = "Phone Link: Connected" if cam_dirs else "Phone Link: Watching"
    relay_status = "Mac Relay: Enabled" if getattr(config, 'MAC_MINI_RELAY_ENABLED', False) else "Mac Relay: Ready"
    
    https_note = f"\n🔒 Live QR Scanner (HTTPS): {GLOBAL_HUD_HTTPS_URL}" if GLOBAL_HUD_HTTPS_URL else ""
    return f"📱 Mobile HUD: {hud_url}{https_note}\n{phone_link_status} | {relay_status}"