# =================== FINAL ROBUST PHONE SERVER ===================
import os
import sys

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import time
import json
import re
import html
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
MES_PHOTOS_DIR = getattr(config, 'MES_PHOTOS_DIR', os.path.join(config.LOCAL_DATA_DIR, "mes_photos"))
MES_TREND_FILE = getattr(config, 'MES_TREND_FILE', os.path.join(config.LOCAL_DATA_DIR, "mes_process_trend_log.json"))

os.makedirs(LOCAL_CACHE_DIR, exist_ok=True)
os.makedirs(VOICE_SAMPLES_DIR, exist_ok=True)
os.makedirs(LOCAL_UPLOADS_DIR, exist_ok=True)
os.makedirs(MES_PHOTOS_DIR, exist_ok=True)

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


def clean_and_validate_sn(raw_text: str) -> str:
    """
    Validates and extracts the real Solar Module Serial Number.
    Per production standard, correct module SN ALWAYS begins with 'V01' (e.g. V01269003050237).
    Discards adjacent model/specification barcodes (e.g. 615NEG19RC.20|Q1||003050237, TSM-615...).
    """
    if not raw_text:
        return ""
    raw_text = str(raw_text).strip()

    # 1. Match 'V01' followed by 7-20 alphanumeric characters
    m = re.search(r'\b(V01[0-9A-Za-z]{7,20})\b', raw_text, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    # 2. Match Trina Solar prefixed SNs e.g. "Trina Solar V01269003050237" or "SN: V01..."
    m = re.search(r'(?:Trina\s*Solar\s*|SN:\s*|S/N:\s*)(V01[0-9A-Za-z]{7,20})', raw_text, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    # 3. Direct cleaned alphanumeric check
    clean = re.sub(r'[^A-Za-z0-9]', '', raw_text).upper()
    if clean.startswith("V01") and len(clean) >= 10:
        return clean

    return ""


def decode_qr_robust(cv_img) -> str:
    if cv_img is None or cv_img.size == 0:
        return ""
    
    h, w = cv_img.shape[:2]
    
    # Target scales: 1.0, 1.5, 2.0 to resolve small/dense QR codes
    for scale in [1.0, 1.5, 2.0]:
        if scale != 1.0:
            scaled = cv2.resize(cv_img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
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
                
            # 1. PyZbar with QRCODE, CODE128, CODE39
            if HAS_PYZBAR:
                from pyzbar.pyzbar import ZBarSymbol
                try:
                    for obj in pyzbar_decode(rot, symbols=[ZBarSymbol.QRCODE, ZBarSymbol.CODE128, ZBarSymbol.CODE39]):
                        raw = obj.data.decode('utf-8', errors='ignore').strip()
                        sn = clean_and_validate_sn(raw)
                        if sn:
                            return sn
                except Exception:
                    pass

            # 2. PyZbar with light Gaussian blur
            if HAS_PYZBAR:
                from pyzbar.pyzbar import ZBarSymbol
                try:
                    blurred = cv2.GaussianBlur(rot, (5, 5), 0)
                    for obj in pyzbar_decode(blurred, symbols=[ZBarSymbol.QRCODE, ZBarSymbol.CODE128, ZBarSymbol.CODE39]):
                        raw = obj.data.decode('utf-8', errors='ignore').strip()
                        sn = clean_and_validate_sn(raw)
                        if sn:
                            return sn
                except Exception:
                    pass

            # 3. OpenCV QRCodeDetector
            try:
                detector = cv2.QRCodeDetector()
                ok, decoded_info, _, _ = detector.detectAndDecodeMulti(rot)
                if ok and decoded_info:
                    for d in decoded_info:
                        sn = clean_and_validate_sn(d)
                        if sn:
                            return sn
                else:
                    data, _, _ = detector.detectAndDecode(rot)
                    if data:
                        sn = clean_and_validate_sn(data)
                        if sn:
                            return sn
            except Exception:
                pass

            # 4. Adaptive thresholding
            try:
                gray = cv2.cvtColor(rot, cv2.COLOR_BGR2GRAY)
                thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5)
                if HAS_PYZBAR:
                    from pyzbar.pyzbar import ZBarSymbol
                    for obj in pyzbar_decode(thresh, symbols=[ZBarSymbol.QRCODE, ZBarSymbol.CODE128]):
                        raw = obj.data.decode('utf-8', errors='ignore').strip()
                        sn = clean_and_validate_sn(raw)
                        if sn:
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


EASYOCR_READER = None

def get_easyocr_reader():
    global EASYOCR_READER
    if EASYOCR_READER is None:
        try:
            import easyocr
            EASYOCR_READER = easyocr.Reader(['en'], gpu=False, verbose=False)
        except Exception as e:
            print(f"[EASYOCR INIT]: {e}")
            EASYOCR_READER = False
    return EASYOCR_READER if EASYOCR_READER is not False else None


def normalize_v01_candidate(raw: str) -> str:
    """
    Normalizes candidate serial numbers from OCR, fixing common OCR letter/digit confusions
    such as VO1 -> V01, U01 -> V01, N01 -> V01.
    """
    if not raw:
        return ""
    s = str(raw).strip().upper()
    # Match patterns like V01..., VO1..., U01..., N01... followed by 7-20 alphanumeric characters
    m = re.search(r'\b([NUVO][O0]1[0-9A-Z]{7,20})\b', s)
    if m:
        candidate = m.group(1)
        val = 'V01' + candidate[3:]
        return val
    return ""


def extract_sn_with_ocr(image_path: str) -> str:
    """
    2-Way robust SN extraction:
    1. First tries PyZbar and OpenCV multi-scale QR/Barcode detection.
    2. Fallback to EasyOCR text recognition looking for 'V01...' patterns.
    """
    if not image_path or not os.path.exists(image_path):
        return ""

    # 1. Barcode / QR detection
    sn = extract_sn_from_photo(image_path)
    if sn:
        return sn

    # 2. EasyOCR text detection
    reader = get_easyocr_reader()
    if reader:
        try:
            results = reader.readtext(image_path, detail=0)
            for text in results:
                norm_sn = normalize_v01_candidate(text)
                if norm_sn:
                    print(f"[OCR V01 SN DETECTED]: '{text}' -> '{norm_sn}'")
                    return norm_sn
                sn_val = clean_and_validate_sn(text)
                if sn_val:
                    return sn_val
        except Exception as ocr_err:
            print(f"[OCR SN EXTRACT ERROR]: {ocr_err}")

    return ""


def parse_mes_datetime(dt_str: str):
    """
    Parses datetime string from MES report into Python datetime object.
    Supports formats: YYYY-MM-DD HH:MM:SS, YYYY/MM/DD HH:MM:SS, Chinese dates, etc.
    """
    if not dt_str or str(dt_str).strip() in ("", "-", "None", "Unknown"):
        return None
    s = str(dt_str).strip()
    s = s.replace("年", "-").replace("月", "-").replace("日", " ")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%m/%d/%Y %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y"
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def extract_layup_time_from_content(raw_content: str) -> str:
    """
    Extracts the Layup Operating Time (e.g. '2026-08-14 02:00:00' or '2026-09-07 01:22:06')
    from MES FineReport Electronic Transfer Order HTML table markup or copied plain text.
    """
    if not raw_content:
        return ""

    text_content = re.sub(r'<[^>]+>', ' ', raw_content)
    text_content = re.sub(r'\s+', ' ', text_content)

    time_pattern = r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}(?:[日\s]+\d{1,2}:\d{2}(?::\d{2})?)?)'

    # Priority 1: In HTML table row containing 'Lay up' or 'TUMLAYUP' or '敷设'
    row_matches = re.findall(r'<tr[^>]*>(.*?)</tr>', raw_content, re.IGNORECASE | re.DOTALL)
    for row in row_matches:
        if re.search(r'(?:Lay\s*up|TUMLAYUP|敷设)', row, re.IGNORECASE):
            m_tm = re.search(time_pattern, row)
            if m_tm:
                return m_tm.group(1).strip()

    # Priority 2: In plain text near 'Lay up' or '敷设' (within 150 chars)
    m_lay = re.search(r'(?:Lay\s*up|敷设)[^A-Za-z0-9]{0,30}[^\d]{0,80}' + time_pattern, text_content, re.IGNORECASE)
    if m_lay:
        return m_lay.group(1).strip()

    # Priority 3: Within 150 chars before or after TUMLAYUP
    m_near_before = re.search(time_pattern + r'.{0,150}?TUMLAYUP', text_content, re.IGNORECASE)
    if m_near_before:
        return m_near_before.group(1).strip()

    m_near_after = re.search(r'TUMLAYUP.{0,150}?' + time_pattern, text_content, re.IGNORECASE)
    if m_near_after:
        return m_near_after.group(1).strip()

    # Priority 4: Operating Time near Lay up
    m_op = re.search(r'Operating\s*Time\s*' + time_pattern, text_content, re.IGNORECASE)
    if m_op:
        return m_op.group(1).strip()

    # Priority 5: Fallback to any process timestamp in the content (Sorting, Welding, Lamination)
    # Since all processes for this module occurred on the same production day
    m_any = re.search(r'\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)\b', text_content)
    if m_any:
        return m_any.group(1).strip()

    return ""


def safe_ascii_url(url: str) -> str:
    """Ensures any URL is 100% pure ASCII for urllib/http.client by quoting non-ASCII characters."""
    if not url:
        return ""
    try:
        url.encode('ascii')
        return url
    except UnicodeEncodeError:
        parsed = urllib.parse.urlsplit(url)
        path = urllib.parse.quote(parsed.path, safe='/:@%')
        query = urllib.parse.quote(parsed.query, safe='=&%')
        fragment = urllib.parse.quote(parsed.fragment, safe='=&%')
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, fragment))


def parse_fr_artifacts(chunk: str) -> dict:
    """
    Extracts FineReport runtime artifacts from HTML, JS, or JSON chunks:
    - sessionID: active FineReport session ID (from sid, currentSessionID, sessionID)
    - cpt / frm: template path (e.g. production/module_flow.cpt)
    - iframe_src: embedded report viewer iframe source URL
    - param_widgets: input parameter names (e.g. MOUDLEID)
    """
    results = {}
    if not chunk:
        return results

    # 1. sessionID (matches currentSessionID, sessionID, sessionId, var sid)
    m_sess = re.search(r'(?:currentSessionID|sessionID|sessionId|sid)["\'\s:=]+([0-9a-zA-Z_-]{8,64})', chunk)
    if not m_sess:
        m_sess = re.search(r'[?&]sessionID=([0-9a-zA-Z_-]{8,64})', chunk)
    if m_sess:
        results['session_id'] = m_sess.group(1)

    # 2. cpt / frm template
    m_cpt = re.search(r'(?:viewlet|reportlet|templatePath|path)["\'\s:=]+([^"\'\s]+\.(?:cpt|frm))["\'&?]', chunk, re.IGNORECASE)
    if not m_cpt:
        m_cpt = re.search(r'["\'=]([a-zA-Z0-9_\-/%\\.]+\.(?:cpt|frm))["\'&?]', chunk, re.IGNORECASE)
    if m_cpt:
        results['cpt'] = urllib.parse.unquote(m_cpt.group(1))

    # 3. iframe src
    m_iframe = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', chunk, re.IGNORECASE)
    if m_iframe:
        results['iframe_src'] = m_iframe.group(1)

    # 4. parameter widget names (e.g. MOUDLEID)
    widgets = re.findall(r'"widgetName"\s*:\s*"([A-Za-z0-9_]+)"', chunk)
    param_widgets = [w for w in widgets if w.upper() not in ('PARA', 'SEARCH', 'LABELMOUDLEID', 'TOOLBAR', 'PAGESETUP', 'PRINTPREVIEW', 'NEWPRINT', 'EXPORT', 'EMAIL')]
    if param_widgets:
        results['param_widgets'] = param_widgets

    return results


def read_and_decode_mes_response(raw_bytes: bytes, tag: str = "") -> str:
    """
    Decodes raw HTTP response bytes from FineReport into searchable text:
    - If binary XLSX (PK\x03\x04): parses all sheets and cells using openpyxl
    - If legacy XLS (\xd0\xcf\x11\xe0...): parses readable strings
    - Otherwise: decodes UTF-8 HTML / JSON / Text
    """
    if not raw_bytes:
        return ""

    # 1. XLSX Archive
    if len(raw_bytes) > 200 and raw_bytes[:4] == b'PK\x03\x04':
        try:
            import io
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
            excel_rows = []
            for sname in wb.sheetnames:
                ws = wb[sname]
                for row in ws.iter_rows(values_only=True):
                    r_txt = " ".join(str(c) for c in row if c is not None)
                    if r_txt.strip():
                        excel_rows.append(r_txt)
            excel_text = "\n".join(excel_rows)
            print(f"[MES EXCEL PARSED {tag}]: {len(wb.sheetnames)} sheets, {len(excel_rows)} rows, {len(excel_text)} bytes")
            return excel_text
        except Exception as xl_err:
            print(f"[MES EXCEL PARSE ERROR {tag}]: {xl_err}")

    # 2. Legacy XLS Stream
    if len(raw_bytes) > 500 and raw_bytes[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        try:
            xls_strings = re.findall(rb'[\x20-\x7e]{3,}', raw_bytes)
            xls_text = " ".join(s.decode('ascii', errors='ignore') for s in xls_strings)
            print(f"[MES LEGACY XLS PARSED {tag}]: {len(xls_text)} bytes")
            return xls_text
        except Exception:
            pass

    # 3. Standard Text / HTML / JSON
    return raw_bytes.decode('utf-8', errors='ignore')


MES_IN_FLIGHT_LOCK = threading.Lock()
MES_IN_FLIGHT_EVENTS = {}
MES_IN_FLIGHT_RESULTS = {}


def query_mes_process_log(sn: str, record_to_trend: bool = True) -> dict:
    """
    Queries the Factory MES Reporting Platform (10.200.3.109:8080) for the specified module SN.
    Searches for machine records:
      - TUMSOLDERING (Welding / 焊接)
      - TUMLAYUP (Lay up / 敷设) & Layup Operating Time
      - TUMLAMINATION (Lamination / 层压)
    Includes:
      1. Cache-First instant lookup (0 ms) from local persistent trend log
      2. In-flight request deduplication to eliminate race conditions
      3. Fast-Path direct Excel & HTML export (<1.5s response)
    """
    clean_sn = clean_and_validate_sn(sn) or (normalize_v01_candidate(sn) if sn else "") or (sn.strip().upper() if sn else "")
    if not clean_sn:
        return {
            "status": "error",
            "sn": "",
            "message": "Module Serial Number cannot be empty and must be valid",
            "tumsoldering": "",
            "tumlayup": "",
            "tumlamination": "",
            "layup_time": "",
            "raw_found": False
        }

    # 0. Cache-First Instant Return (0 ms): If already in persistent log with machine data
    cached = get_mes_trend_entry_by_sn(clean_sn)
    if cached and (cached.get('tumsoldering') or cached.get('tumlayup') or cached.get('tumlamination') or cached.get('layup_time')):
        print(f"[MES CACHE HIT]: SN='{clean_sn}' -> Soldering='{cached.get('tumsoldering')}', Layup='{cached.get('tumlayup')}', Lam='{cached.get('tumlamination')}'")
        return {
            "status": "ok",
            "sn": clean_sn,
            "tumsoldering": cached.get('tumsoldering', ''),
            "tumlayup": cached.get('tumlayup', ''),
            "tumlamination": cached.get('tumlamination', ''),
            "layup_time": cached.get('layup_time', ''),
            "product_family": cached.get('product_family', ''),
            "lot_no": cached.get('lot_no', ''),
            "mo_no": cached.get('mo_no', ''),
            "appearance_grade": cached.get('appearance_grade', ''),
            "defect": cached.get('defect', ''),
            "result": cached.get('result', ''),
            "raw_found": True
        }

    # In-Flight Deduplication: Merge concurrent queries for the same SN into a single execution
    is_primary = False
    evt = None
    with MES_IN_FLIGHT_LOCK:
        if clean_sn in MES_IN_FLIGHT_EVENTS:
            evt = MES_IN_FLIGHT_EVENTS[clean_sn]
            is_primary = False
        else:
            evt = threading.Event()
            MES_IN_FLIGHT_EVENTS[clean_sn] = evt
            is_primary = True

    if not is_primary and evt is not None:
        print(f"[MES IN-FLIGHT JOIN]: Concurrent request for {clean_sn} waiting on active query...")
        evt.wait(timeout=22.0)
        with MES_IN_FLIGHT_LOCK:
            res = MES_IN_FLIGHT_RESULTS.get(clean_sn)
            if res:
                return res
        cached_after = get_mes_trend_entry_by_sn(clean_sn)
        if cached_after and (cached_after.get('tumsoldering') or cached_after.get('tumlayup') or cached_after.get('tumlamination') or cached_after.get('layup_time')):
            return {
                "status": "ok",
                "sn": clean_sn,
                "tumsoldering": cached_after.get('tumsoldering', ''),
                "tumlayup": cached_after.get('tumlayup', ''),
                "tumlamination": cached_after.get('tumlamination', ''),
                "layup_time": cached_after.get('layup_time', ''),
                "product_family": cached_after.get('product_family', ''),
                "lot_no": cached_after.get('lot_no', ''),
                "mo_no": cached_after.get('mo_no', ''),
                "appearance_grade": cached_after.get('appearance_grade', ''),
                "defect": cached_after.get('defect', ''),
                "result": cached_after.get('result', ''),
                "raw_found": True
            }

    return_val = None
    try:
        base_url = "http://10.200.3.109:8080"
        login_url = f"{base_url}/webroot/decision/login"
        enc_sn = urllib.parse.quote(clean_sn)
        enc_zh = urllib.parse.quote('组件序列号')
        report_url = safe_ascii_url(f"{base_url}/webroot/decision/view/report?id=416090fb-b706-40e8-9e4d-d698a059f6bf&{enc_zh}={enc_sn}")
        direct_report_url = safe_ascii_url(f"{base_url}/webroot/decision#/?activeTab=416090fb-b706-40e8-9e4d-d698a059f6bf&{enc_zh}={enc_sn}")

        # 1. Check if 10.200.3.109 is reachable from this machine
        reachable = False
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.5)
                s.connect(("10.200.3.109", 8080))
                reachable = True
        except Exception:
            reachable = False

        if not reachable:
            # Host PC is offline from factory LAN (running on office Wi-Fi)
            if record_to_trend and clean_sn:
                save_mes_trend_entry({
                    "sn": clean_sn,
                    "tumsoldering": "",
                    "tumlayup": "",
                    "tumlamination": "",
                    "layup_time": "",
                    "defect": "Offline PC (Auto-Synced via Mobile)",
                    "result": "Pending MES"
                })
            return_val = {
                "status": "offline_pc",
                "sn": clean_sn,
                "tumsoldering": "",
                "tumlayup": "",
                "tumlamination": "",
                "layup_time": "",
                "direct_report_url": direct_report_url,
                "raw_found": False,
                "message": "Host PC is offline from factory LAN (10.200.3.109:8080 unreachable). Auto-extraction engaged on mobile."
            }
            return return_val

        # 2. Host PC is connected to factory LAN: perform automated login & query
        import http.cookiejar
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

        auth_headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*"
        }

        # Step A: Automated Login with username 030888, password 030888
        access_token = ""
        login_success = False
        login_endpoints = [
            f"{base_url}/webroot/decision/login",
            f"{base_url}/webroot/decision/login/valid",
            f"{base_url}/webroot/decision/login/v10"
        ]
        login_payload = json.dumps({"username": "030888", "password": "030888", "validity": -2}).encode('utf-8')

        for ep in login_endpoints:
            try:
                req = urllib.request.Request(ep, data=login_payload, headers=auth_headers)
                with opener.open(req, timeout=3.5) as resp:
                    resp_body = resp.read().decode('utf-8', errors='ignore')
                    try:
                        resp_json = json.loads(resp_body)
                        if isinstance(resp_json, dict):
                            data_obj = resp_json.get('data') or {}
                            access_token = data_obj.get('accessToken') or resp_json.get('accessToken', '')
                            login_success = True
                            print(f"[MES LOGIN]: Success at {ep} (token: {bool(access_token)})")
                            break
                    except Exception:
                        if getattr(resp, 'status', 200) in (200, 204):
                            login_success = True
                            print(f"[MES LOGIN]: Success at {ep}")
                            break
            except Exception as ep_err:
                print(f"[MES LOGIN PROBE {ep}]: {ep_err}")

        # Cross-Domain SSO Endpoint Probe
        try:
            cross_url = safe_ascii_url(f"{base_url}/webroot/decision/login/cross/domain?fine_username=030888&fine_password=030888&validity=-2")
            cross_req = urllib.request.Request(cross_url, headers={"User-Agent": auth_headers["User-Agent"]})
            with opener.open(cross_req, timeout=3.0) as cr_resp:
                pass
        except Exception:
            pass

        # Fallback to form URL encoded if JSON login didn't return success
        if not login_success:
            try:
                form_payload = urllib.parse.urlencode({"username": "030888", "password": "030888"}).encode('utf-8')
                form_headers = dict(auth_headers)
                form_headers["Content-Type"] = "application/x-www-form-urlencoded"
                form_req = urllib.request.Request(login_url, data=form_payload, headers=form_headers)
                with opener.open(form_req, timeout=3.0) as f_resp:
                    pass
            except Exception as form_err:
                print(f"[MES LOGIN FORM]: {form_err}")

        cookie_parts = []
        if access_token:
            cookie_parts.append(f"fine_auth_token={access_token}")
        for c in cj:
            cookie_parts.append(f"{c.name}={c.value}")

        query_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8"
        }
        if access_token:
            query_headers["fine_auth_token"] = access_token
            query_headers["Authorization"] = f"Bearer {access_token}"
        if cookie_parts:
            query_headers["Cookie"] = "; ".join(cookie_parts)

        token_param = f"&fine_auth_token={urllib.parse.quote(access_token)}" if access_token else ""
        combined_html = ""

        # Step B1: Fast-Path Direct Excel & HTML Export (Prioritize proven working endpoints)
        fast_urls = [
            safe_ascii_url(f"{base_url}/webroot/decision/v10/entry/access/416090fb-b706-40e8-9e4d-d698a059f6bf?op=export&format=excel&extype=simple&MOUDLEID={clean_sn}&__bypassevent__=true{token_param}"),
            safe_ascii_url(f"{base_url}/webroot/decision/view/report?id=416090fb-b706-40e8-9e4d-d698a059f6bf&MOUDLEID={clean_sn}&op=export&format=excel&extype=simple&__bypassevent__=true{token_param}"),
            safe_ascii_url(f"{base_url}/webroot/decision/v10/entry/access/416090fb-b706-40e8-9e4d-d698a059f6bf?op=export&format=html&MOUDLEID={clean_sn}&__bypassevent__=true{token_param}"),
            safe_ascii_url(f"{base_url}/webroot/decision/view/report?id=416090fb-b706-40e8-9e4d-d698a059f6bf&MOUDLEID={clean_sn}&op=export&format=html&__bypassevent__=true{token_param}")
        ]

        for f_u in fast_urls:
            try:
                f_req = urllib.request.Request(f_u, headers=query_headers)
                with opener.open(f_req, timeout=3.8) as f_resp:
                    f_raw = f_resp.read()
                    f_chunk = read_and_decode_mes_response(f_raw, tag="FAST_PATH")
                    if f_chunk:
                        combined_html += " " + f_chunk
                        if clean_sn in f_chunk and any(kw in f_chunk for kw in ("焊接", "敷设", "层压", "TUM", "SOL", "LAY", "LAM", "Stringer", "Lam")):
                            print(f"[MES FAST-PATH HIT]: Found module data in {f_u[:75]}...")
                            break
            except Exception as f_err:
                print(f"[MES FAST-PATH PROBE]: {f_err}")

        # Check if fast-path already resolved the module
        fast_parsed = extract_info_from_mes_html(combined_html, fallback_sn=clean_sn)
        if fast_parsed.get('tumsoldering') or fast_parsed.get('tumlayup') or fast_parsed.get('tumlamination') or fast_parsed.get('layup_time'):
            soldering = fast_parsed.get('tumsoldering', '')
            layup = fast_parsed.get('tumlayup', '')
            lamination = fast_parsed.get('tumlamination', '')
            layup_time = fast_parsed.get('layup_time', '')
            prod_family = fast_parsed.get('product_family', '')
            lot_no = fast_parsed.get('lot_no', '')
            mo_no = fast_parsed.get('mo_no', '')
            grade = fast_parsed.get('appearance_grade', '')

            print(f"[MES FAST-PATH PARSED]: SN='{clean_sn}' -> Soldering='{soldering}', Layup='{layup}', Lam='{lamination}', LayupTime='{layup_time}'")

            if record_to_trend and clean_sn:
                save_mes_trend_entry({
                    "sn": clean_sn,
                    "tumsoldering": soldering,
                    "tumlayup": layup,
                    "tumlamination": lamination,
                    "layup_time": layup_time,
                    "product_family": prod_family,
                    "lot_no": lot_no,
                    "mo_no": mo_no,
                    "appearance_grade": grade,
                    "defect": "MES Query: Found",
                    "result": "Logged"
                })

            return_val = {
                "status": "ok",
                "sn": clean_sn,
                "tumsoldering": soldering,
                "tumlayup": layup,
                "tumlamination": lamination,
                "layup_time": layup_time,
                "product_family": prod_family,
                "lot_no": lot_no,
                "mo_no": mo_no,
                "appearance_grade": grade,
                "raw_found": True
            }
            return return_val

        # Step B2: Deep Probe Directory Entry & Sessions if fast path missed
        encoded_param_dict = {
            'MOUDLEID': clean_sn,
            'moudleid': clean_sn,
            'MoudleId': clean_sn,
            'MODULEID': clean_sn,
            'moduleid': clean_sn,
            'ModuleId': clean_sn,
            '组件序列号': clean_sn,
            'SN': clean_sn,
            'sn': clean_sn,
            'ModuleSerialNo': clean_sn,
            'SerialNo': clean_sn,
            'barcode': clean_sn,
            'Barcode': clean_sn,
            '条码': clean_sn,
            '组件条码': clean_sn,
            '序列号': clean_sn,
            '__bypassevent__': 'true',
            '_bypassevent_': 'true',
            'cmd': 'query'
        }
        param_string = urllib.parse.urlencode(encoded_param_dict)

        template_path = ""
        entry_endpoints = [
            f"{base_url}/webroot/decision/v10/entry/access/416090fb-b706-40e8-9e4d-d698a059f6bf?preview=true&MOUDLEID={clean_sn}&__bypassevent__=true",
            f"{base_url}/webroot/decision/v10/entry/access/416090fb-b706-40e8-9e4d-d698a059f6bf",
            f"{base_url}/webroot/decision/link/416090fb-b706-40e8-9e4d-d698a059f6bf?MOUDLEID={clean_sn}&__bypassevent__=true",
            f"{base_url}/webroot/decision/view/report?id=416090fb-b706-40e8-9e4d-d698a059f6bf&MOUDLEID={clean_sn}&__bypassevent__=true"
        ]

        known_sessions = set()
        known_templates = set()

        for ep in entry_endpoints:
            try:
                ep_url = safe_ascii_url(f"{ep}?{token_param.lstrip('&')}" if ('?' not in ep and token_param) else (f"{ep}{token_param}" if token_param else ep))
                req = urllib.request.Request(ep_url, headers=query_headers)
                with opener.open(req, timeout=3.5) as resp:
                    raw_body = resp.read()
                    body = read_and_decode_mes_response(raw_body, tag="ENTRY")
                    status_code = getattr(resp, 'status', 200)
                    final_url = resp.geturl()
                    print(f"[MES ENTRY PROBE]: {ep[:75]}... -> status={status_code}, bytes={len(body)}")
                    if body:
                        combined_html += " " + body

                    entry_arts = parse_fr_artifacts(body)
                    url_arts = parse_fr_artifacts(final_url)
                    e_sess = entry_arts.get('session_id') or url_arts.get('session_id')
                    e_cpt = entry_arts.get('cpt') or url_arts.get('cpt')
                    if e_sess:
                        print(f"[MES ENTRY SESSION FOUND]: SessionID='{e_sess}' from {ep[:60]}")
                        known_sessions.add(e_sess)
                    if e_cpt and not template_path:
                        template_path = e_cpt
                        print(f"[MES ENTRY CPT FOUND]: '{template_path}'")

                    m_cpt = re.search(r'["\'=]([a-zA-Z0-9_\-/%\\.]+\.(?:cpt|frm))["\'&?]', body, re.IGNORECASE)
                    if m_cpt and not template_path:
                        template_path = urllib.parse.unquote(m_cpt.group(1))
                        print(f"[MES ENTRY REGEX RESOLVED]: 416090fb... -> '{template_path}'")

                    try:
                        data = json.loads(body)
                        entry_obj = data.get('data') or data
                        if isinstance(entry_obj, dict) and not template_path:
                            template_path = entry_obj.get('path') or entry_obj.get('templatePath') or entry_obj.get('url') or entry_obj.get('reportlet') or entry_obj.get('viewlet') or ""
                            if template_path:
                                print(f"[MES ENTRY RESOLVED]: 416090fb... -> '{template_path}'")
                    except Exception:
                        pass
            except Exception as ep_err:
                print(f"[MES ENTRY ERR {ep[:50]}]: {ep_err}")

        # Active Session Parameter Injection & Content Fetch
        for active_sid in list(known_sessions):
            print(f"[MES ACTIVE SESSION]: ID='{active_sid}'")
            param_post_urls = [
                safe_ascii_url(f"{base_url}/webroot/decision/view/report?op=fr_dialog&cmd=parameters_d&sessionID={active_sid}&MOUDLEID={clean_sn}{token_param}"),
                safe_ascii_url(f"{base_url}/webroot/decision/view/report?op=widget&widgetname=moudleid&sessionID={active_sid}&value={clean_sn}{token_param}"),
                safe_ascii_url(f"{base_url}/webroot/decision/view/report?op=widget&widgetname=Search&sessionID={active_sid}&MOUDLEID={clean_sn}{token_param}")
            ]
            for p_u in param_post_urls:
                try:
                    p_req = urllib.request.Request(p_u, data=param_string.encode('utf-8'), headers=query_headers, method='POST')
                    with opener.open(p_req, timeout=2.5) as p_resp:
                        p_raw = p_resp.read()
                        p_chunk = read_and_decode_mes_response(p_raw, tag="PARAM_POST")
                        if p_chunk:
                            combined_html += " " + p_chunk
                except Exception:
                    pass

            sess_content_endpoints = [
                safe_ascii_url(f"{base_url}/webroot/decision/view/report?op=export&sessionID={active_sid}&format=excel&extype=simple&MOUDLEID={clean_sn}&__bypassevent__=true{token_param}"),
                safe_ascii_url(f"{base_url}/webroot/decision/view/report?op=fr_view&cmd=view_content&sessionID={active_sid}&reportIndex=0&recal=true&MOUDLEID={clean_sn}&__bypassevent__=true{token_param}"),
                safe_ascii_url(f"{base_url}/webroot/decision/view/report?op=fr_view&cmd=view_content&sessionID={active_sid}&reportIndex=1&recal=true&MOUDLEID={clean_sn}&__bypassevent__=true{token_param}"),
                safe_ascii_url(f"{base_url}/webroot/decision/view/report?op=export&sessionID={active_sid}&format=html&extype=simple&MOUDLEID={clean_sn}&__bypassevent__=true{token_param}")
            ]
            for s_u in sess_content_endpoints:
                try:
                    with opener.open(urllib.request.Request(s_u, headers=query_headers), timeout=3.5) as s_resp:
                        s_raw = s_resp.read()
                        s_chunk = read_and_decode_mes_response(s_raw, tag=s_u[:40])
                        if s_chunk:
                            combined_html += " " + s_chunk
                            if clean_sn in s_chunk and any(kw in s_chunk for kw in ("焊接", "敷设", "层压", "TUM", "SOL", "LAY", "LAM", "Stringer", "Lam")):
                                print(f"[MES FETCH SN HIT]: Found module data in session {active_sid[:8]} content!")
                                break
                except Exception as c_err:
                    print(f"[MES FETCH CONTENT ERR]: {c_err}")

        # Save response for floor diagnostics
        try:
            dbg_path = os.path.join(config.LOCAL_DATA_DIR, "last_mes_response.html")
            with open(dbg_path, "w", encoding="utf-8", errors="ignore") as dbg_f:
                dbg_f.write(combined_html)
        except Exception:
            pass

        # Extract machines, process data, and layup operating time using bilingual extractor
        parsed_data = extract_info_from_mes_html(combined_html, fallback_sn=clean_sn)
        soldering = parsed_data.get('tumsoldering', '')
        layup = parsed_data.get('tumlayup', '')
        lamination = parsed_data.get('tumlamination', '')
        layup_time = parsed_data.get('layup_time', '')
        prod_family = parsed_data.get('product_family', '')
        lot_no = parsed_data.get('lot_no', '')
        mo_no = parsed_data.get('mo_no', '')
        grade = parsed_data.get('appearance_grade', '')

        found_any = bool(soldering or layup or lamination or layup_time)
        print(f"[MES QUERY PARSED]: SN='{clean_sn}' -> Soldering='{soldering}', Layup='{layup}', Lamination='{lamination}', LayupTime='{layup_time}', Family='{prod_family}', Lot='{lot_no}' (found={found_any})")

        # Record entry if requested so desktop MESProcessLogTab is populated on MES queries
        if record_to_trend and clean_sn:
            save_mes_trend_entry({
                "sn": clean_sn,
                "tumsoldering": soldering,
                "tumlayup": layup,
                "tumlamination": lamination,
                "layup_time": layup_time,
                "product_family": prod_family,
                "lot_no": lot_no,
                "mo_no": mo_no,
                "appearance_grade": grade,
                "defect": "MES Query: Found" if found_any else "MES Query: Blank (Tap Report on Phone)",
                "result": "Logged" if found_any else "Pending MES"
            })

        return_val = {
            "status": "ok",
            "sn": clean_sn,
            "tumsoldering": soldering,
            "tumlayup": layup,
            "tumlamination": lamination,
            "layup_time": layup_time,
            "product_family": prod_family,
            "lot_no": lot_no,
            "mo_no": mo_no,
            "appearance_grade": grade,
            "raw_found": found_any
        }
        return return_val
    except Exception as err:
        print(f"[MES QUERY ERROR]: {err}")
        return_val = {
            "status": "error",
            "sn": clean_sn,
            "tumsoldering": "",
            "tumlayup": "",
            "tumlamination": "",
            "layup_time": "",
            "raw_found": False,
            "message": f"Query error: {err}"
        }
        return return_val
    finally:
        if is_primary and evt is not None:
            with MES_IN_FLIGHT_LOCK:
                if return_val:
                    MES_IN_FLIGHT_RESULTS[clean_sn] = return_val
                evt.set()
                def _cleanup():
                    with MES_IN_FLIGHT_LOCK:
                        MES_IN_FLIGHT_EVENTS.pop(clean_sn, None)
                        MES_IN_FLIGHT_RESULTS.pop(clean_sn, None)
                threading.Timer(6.0, _cleanup).start()


# ================== MES BILINGUAL DICTIONARY & TRANSLATOR ==================
MES_CHINESE_DICTIONARY = [
    # 1. Header & Order Metadata
    {
        "cn": "组件生产流转",
        "en": "Module Production Routing",
        "cat": "Header / Document Title",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Page 1/2 report title (Chinese version of Electronic Transfer Order / Process Logsheet)"
    },
    {
        "cn": "组件序列号",
        "en": "Module Serial Number (SN)",
        "cat": "Header Metadata",
        "equipment": "-",
        "page": "Page 1/2 & 2/2",
        "desc": "Unique barcode identifier for solar module, typically starts with V01"
    },
    {
        "cn": "工单号",
        "en": "MO Number (Work Order)",
        "cat": "Header Metadata",
        "equipment": "-",
        "page": "Page 1/2 & 2/2",
        "desc": "Manufacturing Order number (e.g. 5M269M1003)"
    },
    {
        "cn": "产品系列",
        "en": "Product Family / Series",
        "cat": "Header Metadata",
        "equipment": "-",
        "page": "Page 1/2 & 2/2",
        "desc": "Module model series (e.g. TSM-***NEG19RC.20)"
    },
    {
        "cn": "料号",
        "en": "Part Number / Lot Number",
        "cat": "Header Metadata",
        "equipment": "-",
        "page": "Page 1/2 & 2/2",
        "desc": "Component BOM / part identifier (e.g. 6A024170)"
    },
    {
        "cn": "组件规格",
        "en": "Module Specification / Cell Type",
        "cat": "Header Metadata",
        "equipment": "-",
        "page": "Page 1/2 & 2/2",
        "desc": "Cell format or specification code (e.g. 210R, 182R)"
    },
    {
        "cn": "组件外观等级",
        "en": "Appearance Grade",
        "cat": "Header Metadata",
        "equipment": "-",
        "page": "Page 1/2 & 2/2",
        "desc": "Visual cosmetic inspection quality tier (e.g. Q3, A, B, OK, NG)"
    },
    {
        "cn": "组件最终等级",
        "en": "Final Grade",
        "cat": "Header Metadata",
        "equipment": "-",
        "page": "Page 1/2 & 2/2",
        "desc": "Final combined quality rating after EL, IV, and visual tests (e.g. Q3, OK)"
    },
    {
        "cn": "当前工序",
        "en": "Current Station / Process Step",
        "cat": "Header Metadata",
        "equipment": "-",
        "page": "Page 1/2 & 2/2",
        "desc": "Active manufacturing stage (e.g. M12, M12工序NG自动Hold)"
    },

    # 2. Front-End Process Steps (Left Column on Page 1/2)
    {
        "cn": "划片",
        "en": "Laser Scribing / Cell Cutting",
        "cat": "Front-End Process",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Laser cutting of solar cells into half-cut or third-cut pieces"
    },
    {
        "cn": "焊接",
        "en": "Welding / Soldering / Stringing",
        "cat": "Front-End Process",
        "equipment": "TUMSOLDERING / TUMSOLERING",
        "page": "Page 1/2 & 2/2",
        "desc": "Stringer machines soldering cells with ribbons (e.g. TUMSOLERING1009)"
    },
    {
        "cn": "叠焊",
        "en": "Matrix / Auto Bussing",
        "cat": "Front-End Process",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Interconnecting cell strings with bus ribbons into an electrical matrix"
    },
    {
        "cn": "敷设",
        "en": "Lay up / Module Assembly",
        "cat": "Front-End Process",
        "equipment": "TUMLAYUP",
        "page": "Page 1/2 & 2/2",
        "desc": "Layering glass, encapsulant (EVA/POE), cell matrix, and backsheet (e.g. TUMLAYUP1004)"
    },
    {
        "cn": "前EL",
        "en": "Pre-EL Inspection",
        "cat": "Front-End Process",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Electroluminescence optical check before lamination to catch microcracks"
    },
    {
        "cn": "层压",
        "en": "Lamination",
        "cat": "Front-End Process",
        "equipment": "TUMLAMINATION",
        "page": "Page 1/2 & 2/2",
        "desc": "Thermal vacuum bonding of module sandwich (e.g. TUMLAMINATION1018 上层3号位)"
    },
    {
        "cn": "削边",
        "en": "Edge Trimming",
        "cat": "Front-End Process",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Automated trimming of excess EVA/POE after lamination"
    },
    {
        "cn": "终检",
        "en": "Post-Lam Visual QA",
        "cat": "Front-End Process",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Inspection for bubbles, debris, ribbon shift after lamination"
    },

    # 3. Back-End Process Steps (Right Column on Page 1/2)
    {
        "cn": "固化检验",
        "en": "Curing Inspection",
        "cat": "Back-End Process",
        "equipment": "M901_TUMCV",
        "page": "Page 1/2",
        "desc": "Inspection of silicone curing tunnel (e.g. M901_TUMCV1010-S OK)"
    },
    {
        "cn": "装框",
        "en": "Framing",
        "cat": "Back-End Process",
        "equipment": "TUMFRAMING",
        "page": "Page 1/2",
        "desc": "Mounting aluminum frames and corner keys (e.g. TUMFRAMING1006)"
    },
    {
        "cn": "接线盒安装",
        "en": "Junction Box Installation",
        "cat": "Back-End Process",
        "equipment": "TUMJBOX",
        "page": "Page 1/2",
        "desc": "Affixing junction box base to backsheet (e.g. TUMJBOX1006_1 OK)"
    },
    {
        "cn": "接线盒打胶",
        "en": "J-Box Potting / Glue Injection",
        "cat": "Back-End Process",
        "equipment": "TUMJBOX",
        "page": "Page 1/2",
        "desc": "Filling junction box cavity with potting silicone (e.g. TUMJBOX1006_2 OK)"
    },
    {
        "cn": "扣盖/清洗",
        "en": "Cap Fastening & Cleaning",
        "cat": "Back-End Process",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Snapping J-box cover and automated glass surface washing"
    },
    {
        "cn": "耐压",
        "en": "Hi-Pot Withstand Voltage Test",
        "cat": "Electrical QA",
        "equipment": "MV01_NY / DLSK",
        "page": "Page 1/2",
        "desc": "High-voltage electrical insulation and safety test (e.g. DLSK06 合格/Pass)"
    },
    {
        "cn": "功率测试",
        "en": "Power / Flash Test (IV Curve)",
        "cat": "Electrical QA",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Sun simulator IV curve rating: Pmax (Watts), Voc, Isc, Fill Factor (FF)"
    },
    {
        "cn": "EL测试",
        "en": "Final EL Test",
        "cat": "Electrical QA",
        "equipment": "TUMEL",
        "page": "Page 1/2",
        "desc": "Final electroluminescence crack/defect imaging & grade assignment (e.g. TUMEL1006 Q3)"
    },
    {
        "cn": "分档包装",
        "en": "Sorting & Bin Packaging",
        "cat": "Back-End Process",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Automated pallet binning and shipping carton packaging"
    },
    {
        "cn": "评审人员/时间",
        "en": "Reviewer / Review Timestamp",
        "cat": "Quality Review",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "QA Inspector name and timestamp of final review (e.g. 马春蕾 2026-09-07)"
    },
    {
        "cn": "评审人员",
        "en": "Reviewer / QA Inspector",
        "cat": "Quality Review",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Quality inspector who reviewed and signed off on module"
    },

    # 4. Status, Chambers & UI Actions
    {
        "cn": "合格",
        "en": "Pass / Qualified / OK",
        "cat": "Status / Verdict",
        "equipment": "-",
        "page": "All Pages",
        "desc": "Result passed inspection standard"
    },
    {
        "cn": "不合格",
        "en": "Defective / Failed / NG",
        "cat": "Status / Verdict",
        "equipment": "-",
        "page": "All Pages",
        "desc": "Result failed quality tolerance"
    },
    {
        "cn": "自动Hold",
        "en": "Auto-Hold (Line Quarantine)",
        "cat": "Status / Verdict",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "System automatically quarantined module due to inspection NG"
    },
    {
        "cn": "工序NG自动Hold",
        "en": "Process NG Auto-Hold",
        "cat": "Status / Verdict",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Module placed on hold because the specified station flagged an NG"
    },
    {
        "cn": "上层3号位",
        "en": "Upper Deck Position 3",
        "cat": "Equipment Chamber",
        "equipment": "TUMLAMINATION",
        "page": "Page 1/2",
        "desc": "Chamber location inside two-tier multi-chamber laminator"
    },
    {
        "cn": "下层4号位",
        "en": "Lower Deck Position 4",
        "cat": "Equipment Chamber",
        "equipment": "TUMLAMINATION",
        "page": "Page 1/2",
        "desc": "Lower deck chamber location 4 inside two-tier multi-chamber laminator (Lam12.1 / etc.)"
    },
    {
        "cn": "上层",
        "en": "Upper Deck / Top Chamber",
        "cat": "Equipment Chamber",
        "equipment": "TUMLAMINATION",
        "page": "Page 1/2",
        "desc": "Upper heating vacuum chamber"
    },
    {
        "cn": "下层",
        "en": "Lower Deck / Bottom Chamber",
        "cat": "Equipment Chamber",
        "equipment": "TUMLAMINATION",
        "page": "Page 1/2",
        "desc": "Lower heating vacuum chamber"
    },
    {
        "cn": "号位",
        "en": "Position / Slot Number",
        "cat": "Equipment Chamber",
        "equipment": "-",
        "page": "Page 1/2",
        "desc": "Chamber slot or position index"
    },
    {
        "cn": "确定",
        "en": "OK / Confirm",
        "cat": "UI Action",
        "equipment": "-",
        "page": "FineReport Web",
        "desc": "Confirmation button on FineReport popup dialogs"
    },
    {
        "cn": "查询",
        "en": "Query / Search",
        "cat": "UI Action",
        "equipment": "-",
        "page": "FineReport Web",
        "desc": "Submit button on FineReport parameter query bar"
    }
]

def translate_mes_text(text: str) -> str:
    """Translates Chinese MES terms into clear English equivalents."""
    if not text or not isinstance(text, str):
        return ""
    res = text
    # Sort terms by length descending so longer phrases match first
    sorted_terms = sorted(MES_CHINESE_DICTIONARY, key=lambda x: len(x['cn']), reverse=True)
    for item in sorted_terms:
        cn = item['cn']
        en = item['en']
        if cn in res:
            res = res.replace(cn, en)
    return res

MES_TREND_FILE = os.path.join(config.LOCAL_DATA_DIR, "mes_process_trend_log.json")


def normalize_soldering_machine(raw_val: str) -> str:
    """
    Normalizes soldering machine numbers to stringer line designations:
    - TUMSOLDERING1001 to TUMSOLDERING1042 -> Stringer101 to Stringer706
      (6 stringers per line, 7 lines total: line 1 = 1-6, line 2 = 7-12, ..., line 7 = 37-42)
    - TUMSOLDERING1099 -> TUMSOLDERING1099 (remains unchanged)
    - Stringer101..706 -> Stringer101..706
    """
    if not raw_val:
        return ""
    val_str = str(raw_val).strip()
    if not val_str or val_str in ("-", "None"):
        return ""

    m_already = re.match(r'^Stringer\s*([1-7]0[1-6])$', val_str, re.IGNORECASE)
    if m_already:
        return f"Stringer{m_already.group(1)}"

    m = re.search(r'TUM\s*SOLD?E?RING[\s_-]*(\d+)', val_str, re.IGNORECASE)
    if m:
        num = int(m.group(1))
        n = num - 1000 if num >= 1000 else num
        if n == 99 or num == 1099:
            return "TUMSOLDERING1099"
        if 1 <= n <= 42:
            line = (n - 1) // 6 + 1
            st = (n - 1) % 6 + 1
            return f"Stringer{line}{st:02d}"
        return val_str.upper()

    return val_str


def normalize_lamination_machine(raw_val: str, full_context: str = "") -> str:
    """
    Normalizes lamination machine numbers to Lam deck designations:
    - TUMLAMINATION1001 to TUMLAMINATION1021:
      - Lower deck (下层 / Lower Deck) -> Lam<X>.1 (e.g. Lam12.1)
      - Upper deck (上层 / Upper Deck) -> Lam<X>.2 (e.g. Lam12.2)
      - Unspecified deck -> Lam<X>
      - Attaches chamber slot position if present, e.g. Lam12.1 (下层4号位) or Lam18.2 (上层3号位)
    - TUMLAMINATION1099 -> TUMLAMINATION1099 (remains unchanged)
    - TUMLAYUP -> remains unchanged (handled separately)
    """
    if not raw_val and not full_context:
        return ""
    val_str = str(raw_val or "").strip()
    if val_str in ("-", "None"):
        val_str = ""

    # If already fully formatted with bilingual deck/position, keep it
    if val_str and re.match(r'^Lam\d+(\.\d)?\s*\([^)]*(?:Upper|Lower)[^)]*\)$', val_str, re.IGNORECASE):
        return val_str

    scope = f"{val_str} "
    if full_context:
        # Prioritize area around TUMLAMINATION, 层压, or Lamination
        m_near = re.search(r'(?:TUM\s*LAMINATION|层压|Lamination).{0,120}?(上层\s*\d+\s*号位|下层\s*\d+\s*号位|Upper\s*Deck\s*(?:Pos(?:ition)?\s*)?\d+|Lower\s*Deck\s*(?:Pos(?:ition)?\s*)?\d+|上层|下层|Upper\s*Deck|Lower\s*Deck)', full_context, re.IGNORECASE)
        if m_near:
            scope += m_near.group(0) + " "
        else:
            scope += full_context

    m_pos = re.search(r'((?:上层|下层)\s*\d+\s*号位|Upper\s*Deck\s*(?:Pos(?:ition)?\s*)?\d+|Lower\s*Deck\s*(?:Pos(?:ition)?\s*)?\d+)', scope, re.IGNORECASE)
    pos_str = m_pos.group(1).strip() if m_pos else ""

    is_lower = bool(re.search(r'(下层|Lower\s*Deck|\bLower\b)', scope, re.IGNORECASE))
    is_upper = bool(re.search(r'(上层|Upper\s*Deck|\bUpper\b)', scope, re.IGNORECASE))

    m_mach = (re.search(r'(?:TUM\s*LAMINATION[\s_-]*|Lam\s*)(\d+)', val_str, re.IGNORECASE) or 
              re.search(r'(?:TUM\s*LAMINATION[\s_-]*|Lam\s*)(\d+)', scope, re.IGNORECASE))
    if not m_mach:
        return val_str

    num = int(m_mach.group(1))
    n = num - 1000 if num >= 1000 else num

    if n == 99 or num == 1099:
        res = "TUMLAMINATION1099"
        if pos_str and pos_str not in res:
            res += f" ({pos_str})"
        return res

    if 1 <= n <= 21:
        deck_suffix = ""
        if is_lower:
            deck_suffix = ".1"
        elif is_upper:
            deck_suffix = ".2"
        elif re.search(r'Lam\d+\.1', val_str):
            deck_suffix = ".1"
        elif re.search(r'Lam\d+\.2', val_str):
            deck_suffix = ".2"

        base_lam = f"Lam{n}{deck_suffix}"
        if pos_str:
            pos_label = pos_str
            if ("上层" in pos_label or "下层" in pos_label) and "(" not in pos_label:
                deck_en = "Upper" if "上层" in pos_label else "Lower"
                m_num = re.search(r'(\d+)', pos_label)
                pos_num = m_num.group(1) if m_num else ""
                pos_label = f"{pos_str} ({deck_en} {pos_num})" if pos_num else f"{pos_str} ({deck_en})"
            return f"{base_lam} ({pos_label})"
        return base_lam

    return val_str


def extract_info_from_mes_html(raw_content: str, fallback_sn: str = "") -> dict:
    """
    Extracts machine and process information from raw HTML markup, copied page text,
    JSON/JS variables, or OCR-scanned text from FineReport '组件生产流转' (Page 1/2) or
    'Module Product Process Logsheet' (Page 2/2).
    """
    if not raw_content and not fallback_sn:
        return {}

    # 1. HTML unescape
    if raw_content:
        raw_content = html.unescape(raw_content)
        # 2. Decode \uXXXX unicode escapes (common in FineReport JSON/JS)
        try:
            raw_content = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), raw_content)
        except Exception:
            pass

    text_content = re.sub(r'<[^>]+>', ' ', raw_content or '')
    text_content = re.sub(r'\s+', ' ', text_content)

    # 1. Serial Number (V01...)
    sn = ""
    m_sn = re.search(r'\b(V01[0-9A-Za-z]{7,20})\b', raw_content or '', re.IGNORECASE) or re.search(r'\b(V01[0-9A-Za-z]{7,20})\b', text_content, re.IGNORECASE)
    if m_sn:
        sn = m_sn.group(1).upper()
    else:
        norm_sn = normalize_v01_candidate(text_content)
        if norm_sn:
            sn = norm_sn
        elif fallback_sn:
            sn = clean_and_validate_sn(fallback_sn) or normalize_v01_candidate(fallback_sn) or fallback_sn.strip().upper()

    # 2. Soldering Machine (TUMSOLDERING1001-1042 -> Stringer101-706, 1099 remains TUMSOLDERING1099)
    soldering = ""
    m_sol = re.search(r'\b(TUM\s*SOLD?E?RING[\s_-]*[0-9A-Za-z_-]*)\b', raw_content or '', re.IGNORECASE) or re.search(r'\b(TUM\s*SOLD?E?RING[\s_-]*[0-9A-Za-z_-]*)\b', text_content, re.IGNORECASE)
    if m_sol:
        soldering = normalize_soldering_machine(m_sol.group(1))
    else:
        m_str = re.search(r'\b(Stringer\s*[1-7]0[1-6])\b', text_content, re.IGNORECASE) or re.search(r'\b(Stringer\s*[1-7]0[1-6])\b', raw_content or '', re.IGNORECASE)
        if m_str:
            soldering = normalize_soldering_machine(m_str.group(1))

    # 3. Layup Machine (TUMLAYUP... remains unchanged)
    layup = ""
    m_lay = re.search(r'\b(TUM\s*LAYUP[\s_-]*[0-9A-Za-z_-]*)\b', raw_content or '', re.IGNORECASE) or re.search(r'\b(TUM\s*LAYUP[\s_-]*[0-9A-Za-z_-]*)\b', text_content, re.IGNORECASE)
    if m_lay:
        layup = re.sub(r'\s+', '', m_lay.group(1)).upper()

    # 4. Lamination Machine (TUMLAMINATION1001-1021 -> Lam1.1-21.2 & Deck Position, 1099 remains)
    lamination = ""
    m_lam = re.search(r'\b(TUM\s*LAMINATION[\s_-]*[0-9A-Za-z_-]*)\b', raw_content or '', re.IGNORECASE) or re.search(r'\b(TUM\s*LAMINATION[\s_-]*[0-9A-Za-z_-]*)\b', text_content, re.IGNORECASE)
    if m_lam:
        lamination = normalize_lamination_machine(m_lam.group(1), full_context=text_content)
    else:
        lam_norm = normalize_lamination_machine("", full_context=text_content)
        if lam_norm:
            lamination = lam_norm

    # 5. Additional Process Fields (Bilingual: English & Chinese, robust against HTML/JSON delimiters)
    prod_family = ""
    m_fam = re.search(r'(TSM-[0-9A-Za-z\.\*\-]+)', text_content, re.IGNORECASE)
    if m_fam:
        prod_family = m_fam.group(1).upper()
    else:
        m_fam_lbl = re.search(r'(?:Product\s*Family|产品系列|产品型号)[:\s"\'=]+([A-Za-z0-9\.\*\-_]+)', text_content, re.IGNORECASE)
        if m_fam_lbl:
            prod_family = m_fam_lbl.group(1).upper()

    lot_no = ""
    m_lot = re.search(r'(?:Lot\s*No|Lot\s*Number|料号|批次号?|批号)[:\s"\'=]+([0-9A-Za-z]{6,14})', text_content, re.IGNORECASE)
    if m_lot:
        lot_no = m_lot.group(1).upper()

    mo_no = ""
    m_mo = re.search(r'(?:MO\s*No|MO\s*Number|工单号?|制令单号?)[:\s"\'=]+([0-9A-Za-z]{6,16})', text_content, re.IGNORECASE)
    if m_mo:
        mo_no = m_mo.group(1).upper()

    grade = ""
    m_grd = re.search(r'(?:Module\s*Appearance\s*Grade|Appearance\s*Grade|Module\s*Final\s*Grade|Final\s*Grade|组件外观等级|外观等级|组件最终等级|终检等级|等级)[:\s"\'=]+(NG|OK|Q3|[A-D])', text_content, re.IGNORECASE)
    if m_grd:
        grade = m_grd.group(1).upper()

    # 6. Current Step & Defect Notes (Bilingual Extraction & Auto-Translation)
    current_step = ""
    m_step = re.search(r'(?:Current\s*Step|Current\s*Station|当前工序)[:\s"\'=]+([^\r\n<",]+)', text_content, re.IGNORECASE)
    if m_step:
        raw_step = m_step.group(1).strip()
        raw_step = re.sub(r'\s+(?:划片|焊接|叠焊|敷设|层压|固化检验|装框|接线盒).*$', '', raw_step).strip()
        trans_step = translate_mes_text(raw_step)
        current_step = trans_step if trans_step else raw_step

    # 7. Lamination Chamber Position
    lam_pos = ""
    m_pos = re.search(r'((?:上层|下层)\s*\d+\s*号位|Upper\s*Deck\s*Pos\s*\d+|Lower\s*Deck\s*Pos\s*\d+)', text_content, re.IGNORECASE)
    if m_pos:
        lam_pos = m_pos.group(1).strip()
    if lamination and lam_pos and "(" not in lamination and lam_pos not in lamination:
        lamination = f"{lamination} ({lam_pos})"

    # 8. Layup Operating Time
    layup_time = extract_layup_time_from_content(raw_content or '') or extract_layup_time_from_content(text_content)

    found_any = bool(soldering or layup or lamination or layup_time)

    defect_desc = current_step or ("MES Query: Found" if found_any else "-")

    parsed_result = {
        "status": "ok" if found_any or sn else "not_found",
        "sn": sn,
        "tumsoldering": soldering,
        "tumlayup": layup,
        "tumlamination": lamination,
        "layup_time": layup_time,
        "product_family": prod_family,
        "lot_no": lot_no,
        "mo_no": mo_no,
        "appearance_grade": grade,
        "current_step": current_step,
        "defect": defect_desc,
        "raw_found": found_any
    }

    if sn and found_any:
        save_mes_trend_entry(parsed_result)

    return parsed_result


def load_mes_trend_log() -> list:
    if os.path.exists(MES_TREND_FILE):
        try:
            with open(MES_TREND_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    for r in data:
                        if isinstance(r, dict):
                            s = r.get("tumsoldering")
                            if s:
                                r["tumsoldering"] = normalize_soldering_machine(s)
                            lm = r.get("tumlamination")
                            if lm:
                                r["tumlamination"] = normalize_lamination_machine(lm)
                    return data
        except Exception:
            return []
    return []


def get_mes_trend_entry_by_sn(sn: str) -> dict:
    if not sn:
        return {}
    clean_sn = clean_and_validate_sn(sn) or normalize_v01_candidate(sn) or (sn.strip().upper() if sn else "")
    if not clean_sn:
        return {}
    for entry in load_mes_trend_log():
        if entry.get("sn") == clean_sn:
            return dict(entry)
    return {}


def save_mes_trend_entry(entry: dict) -> list:
    logs = load_mes_trend_log()
    sn = entry.get('sn', '').strip()
    if not sn or sn in ("Pending SN", "-", "", "None"):
        return logs

    existing_idx = None
    for i, r in enumerate(logs):
        if r.get('sn') == sn:
            existing_idx = i
            break

    # Correlate with current defect info from HUD state if not present
    last_p = LIVE_HUD_STATE.get("last_panel", {})
    defect_sm = entry.get("defect") or entry.get("current_step") or (last_p.get("summary") if last_p.get("sn") == sn else "") or "-"
    if defect_sm and any('\u4e00' <= char <= '\u9fff' for char in str(defect_sm)):
        defect_sm = translate_mes_text(str(defect_sm))
    defect_res = entry.get("result") or (last_p.get("result") if last_p.get("sn") == sn else "") or "-"

    raw_s = entry.get("tumsoldering", "")
    norm_s = normalize_soldering_machine(raw_s) if raw_s else ""
    raw_lm = entry.get("tumlamination", "")
    norm_lm = normalize_lamination_machine(raw_lm) if raw_lm else ""

    entry_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sn": sn,
        "layup_time": entry.get("layup_time", ""),
        "tumsoldering": norm_s,
        "tumlayup": entry.get("tumlayup", ""),
        "tumlamination": norm_lm,
        "product_family": entry.get("product_family", ""),
        "lot_no": entry.get("lot_no", ""),
        "mo_no": entry.get("mo_no", ""),
        "appearance_grade": entry.get("appearance_grade", ""),
        "current_step": entry.get("current_step", ""),
        "defect": defect_sm,
        "result": defect_res,
        "photo_path": entry.get("photo_path", "")
    }

    if existing_idx is not None:
        for k, v in entry_data.items():
            if v and v != "-":
                logs[existing_idx][k] = v
        final_record = dict(logs[existing_idx])
    else:
        logs.insert(0, entry_data)
        final_record = dict(entry_data)

    logs = logs[:500]
    try:
        os.makedirs(os.path.dirname(MES_TREND_FILE), exist_ok=True)
        with open(MES_TREND_FILE, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[MES TREND LOG SAVE ERROR]: {e}")

    # Broadcast to Mobile HUD State for instant 2-second background sync
    LIVE_HUD_STATE["last_mes"] = {
        "sn": final_record.get("sn", ""),
        "tumsoldering": final_record.get("tumsoldering", ""),
        "tumlayup": final_record.get("tumlayup", ""),
        "tumlamination": final_record.get("tumlamination", ""),
        "layup_time": final_record.get("layup_time", ""),
        "product_family": final_record.get("product_family", ""),
        "lot_no": final_record.get("lot_no", ""),
        "mo_no": final_record.get("mo_no", ""),
        "appearance_grade": final_record.get("appearance_grade", ""),
        "defect": final_record.get("defect", ""),
        "result": final_record.get("result", ""),
        "timestamp": final_record.get("timestamp", ""),
        "raw_found": bool(final_record.get("tumsoldering") or final_record.get("tumlayup") or final_record.get("tumlamination"))
    }

    if GLOBAL_MES_CALLBACK:
        try:
            GLOBAL_MES_CALLBACK(final_record)
        except Exception as cb_err:
            print(f"[MES DISPATCH ERROR]: {cb_err}")

    return logs


def get_mes_layup_time_for_sn(sn: str) -> tuple:
    """
    Retrieves the Layup Time (as a datetime object) and Layup Station from MES for a given module SN.
    1. Looks in local persistent MES log (mes_process_trend_log.json).
    2. If not found or missing layup_time, queries MES platform directly via query_mes_process_log(sn).
    Returns (layup_datetime, station_string, mes_record_dict).
    """
    clean_sn = clean_and_validate_sn(sn) or (normalize_v01_candidate(sn) if sn else "") or (sn.strip().upper() if sn else "")
    if not clean_sn:
        return None, "", {}

    # Check local cache first
    try:
        logs = load_mes_trend_log()
        for r in logs:
            if r.get('sn') == clean_sn:
                lt_str = r.get('layup_time') or ""
                if lt_str:
                    dt = parse_mes_datetime(lt_str)
                    if dt:
                        return dt, r.get('tumlayup', ''), r
    except Exception as e:
        print(f"[MES CACHE LOOKUP ERROR]: {e}")

    # Not found in local cache: query MES directly without recording to trend / firing MES tab callback
    try:
        res = query_mes_process_log(clean_sn, record_to_trend=False)
        if isinstance(res, dict) and res.get('status') == 'ok':
            lt_str = res.get('layup_time') or ""
            if lt_str:
                dt = parse_mes_datetime(lt_str)
                if dt:
                    return dt, res.get('tumlayup', ''), res
    except Exception as q_err:
        print(f"[MES DIRECT QUERY ERROR]: {q_err}")

    return None, "", {}


def get_mes_trend_analytics() -> dict:
    logs = load_mes_trend_log()
    total = len(logs)
    sol_counts = {}
    lay_counts = {}
    lam_counts = {}

    for r in logs:
        s = r.get("tumsoldering", "").strip()
        if s: sol_counts[s] = sol_counts.get(s, 0) + 1

        ly = r.get("tumlayup", "").strip()
        if ly: lay_counts[ly] = lay_counts.get(ly, 0) + 1

        lm = r.get("tumlamination", "").strip()
        if lm: lam_counts[lm] = lam_counts.get(lm, 0) + 1

    def to_sorted_list(counts_dict):
        res = []
        tot = sum(counts_dict.values())
        for name, cnt in sorted(counts_dict.items(), key=lambda x: x[1], reverse=True):
            pct = round((cnt / tot * 100), 1) if tot > 0 else 0
            res.append({"name": name, "count": cnt, "pct": pct})
        return res

    return {
        "total_logged": total,
        "soldering_top": to_sorted_list(sol_counts),
        "layup_top": to_sorted_list(lay_counts),
        "lamination_top": to_sorted_list(lam_counts),
        "recent_records": logs[:25]
    }


def export_mes_trend_csv_string() -> str:
    logs = load_mes_trend_log()
    lines = ["Logged Time,Layup Operating Time,Serial Number,Welding (Stringer),Layup Machine (TUMLAYUP),Lamination Machine (Lam),Product Family,Lot No,Appearance Grade,Defect Summary,Result Grade"]
    for r in logs:
        line = [
            f'"{r.get("timestamp", "")}"',
            f'"{r.get("layup_time", "")}"',
            f'"{r.get("sn", "")}"',
            f'"{r.get("tumsoldering", "")}"',
            f'"{r.get("tumlayup", "")}"',
            f'"{r.get("tumlamination", "")}"',
            f'"{r.get("product_family", "")}"',
            f'"{r.get("lot_no", "")}"',
            f'"{r.get("appearance_grade", "")}"',
            f'"{r.get("defect", "")}"',
            f'"{r.get("result", "")}"'
        ]
        lines.append(",".join(line))
    return "\n".join(lines)


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
GLOBAL_MES_CALLBACK = None

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def update_live_hud_state(last_rec=None, live_voice=None, all_records=None, override_callback=None, defect_callback=None, mes_callback=None):
    global LIVE_HUD_STATE, GLOBAL_OVERRIDE_CALLBACK, GLOBAL_DEFECT_CALLBACK, GLOBAL_MES_CALLBACK
    if override_callback is not None:
        GLOBAL_OVERRIDE_CALLBACK = override_callback
    if defect_callback is not None:
        GLOBAL_DEFECT_CALLBACK = defect_callback
    if mes_callback is not None:
        GLOBAL_MES_CALLBACK = mes_callback

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
<script src="/js/jsqr.min.js"></script>
<script src="/js/zxing.min.js"></script>
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
  #tab-content-dashboard.active,
  #tab-content-mes.active {
    display: block;
    overflow-y: auto;
    height: calc(100vh - 74px);
    -webkit-overflow-scrolling: touch;
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

  /* ================== TAB 3: MES PROCESS LOG ================== */
  .mes-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    padding: 12px;
    margin-bottom: 10px;
  }
  .mes-card-title {
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .mes-input-group {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .mes-sn-input {
    flex: 1;
    background: #0f172a;
    border: 2px solid #38bdf8;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 15px;
    font-weight: 800;
    font-family: 'Consolas', monospace;
    color: #38bdf8;
    outline: none;
    box-sizing: border-box;
  }
  .mes-sn-btn {
    background: #334155;
    color: #fff;
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
  }
  .mes-sn-btn:active {
    background: #2563eb;
    transform: scale(0.97);
  }
  .mes-ingest-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
    margin-top: 8px;
  }
  .btn-mes-ingest {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    border: 1px solid #38bdf8;
    border-radius: 10px;
    padding: 10px 8px;
    color: #fff;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    text-align: center;
    transition: all 0.15s;
  }
  .btn-mes-ingest:active {
    transform: scale(0.97);
    border-color: #60a5fa;
  }
  .btn-mes-ingest-icon { font-size: 20px; }
  .btn-mes-ingest-title { font-size: 12px; font-weight: 800; color: #fff; }
  .btn-mes-ingest-sub { font-size: 9px; color: var(--text-muted); }

  /* Dictionary & Translation Modal Styles */
  .dict-pill {
    background: #1e293b;
    border: 1px solid #475569;
    color: #cbd5e1;
    border-radius: 20px;
    padding: 4px 9px;
    font-size: 10px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
  }
  .dict-pill.active {
    background: #2563eb;
    border-color: #60a5fa;
    color: #fff;
    font-weight: 700;
  }
  .dict-card-item {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px 10px;
    transition: border-color 0.15s, background 0.15s;
    cursor: pointer;
  }
  .dict-card-item:hover, .dict-card-item:active {
    border-color: #38bdf8;
    background: #24324d;
  }
  .dict-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 3px;
  }
  .dict-card-cn {
    font-size: 14px;
    font-weight: 800;
    color: #fff;
  }
  .dict-card-en {
    font-size: 12px;
    font-weight: 700;
    color: #38bdf8;
  }
  .dict-card-desc {
    font-size: 10px;
    color: #94a3b8;
    line-height: 1.35;
    margin-top: 3px;
  }

  /* Highlight Cards */
  .mes-highlight-item {
    background: #0f172a;
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 10px 12px;
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    transition: all 0.2s;
  }
  .mes-highlight-item.present {
    border-color: #10b981;
    background: rgba(16, 185, 129, 0.08);
  }
  .mes-highlight-item.blank {
    border-color: #64748b;
    background: rgba(100, 116, 139, 0.05);
  }
  .mes-highlight-name {
    font-size: 13px;
    font-weight: 800;
    color: #f8fafc;
  }
  .mes-highlight-sub {
    font-size: 10px;
    color: var(--text-muted);
    margin-top: 2px;
  }
  .mes-badge {
    padding: 4px 10px;
    border-radius: 14px;
    font-size: 11px;
    font-weight: 800;
    font-family: 'Consolas', monospace;
    letter-spacing: 0.3px;
    white-space: nowrap;
  }
  .mes-badge-present {
    background: rgba(16, 185, 129, 0.2);
    color: #34d399;
    border: 1px solid #10b981;
  }
  .mes-badge-blank {
    background: rgba(239, 68, 68, 0.15);
    color: #f87171;
    border: 1px solid #ef4444;
  }
  .mes-badge-pending {
    background: rgba(148, 163, 184, 0.15);
    color: #94a3b8;
    border: 1px solid #64748b;
  }

  /* Quick-Copy Chips */
  .mes-chip-bar {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: 8px;
  }
  .mes-chip {
    background: #1e293b;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 14px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 700;
    color: #cbd5e1;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 4px;
    transition: all 0.15s;
  }
  .mes-chip:active {
    background: #38bdf8;
    color: #0f172a;
  }

  /* Action Launchers */
  .mes-action-btn-primary {
    width: 100%;
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    border: 1px solid #60a5fa;
    color: #fff;
    border-radius: 10px;
    padding: 12px;
    font-size: 13px;
    font-weight: 800;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin-bottom: 8px;
    box-shadow: 0 4px 14px rgba(37, 99, 235, 0.35);
  }
  .mes-action-btn-primary:active { transform: scale(0.98); }
  .mes-action-btn-secondary {
    flex: 1;
    background: #334155;
    border: 1px solid rgba(255,255,255,0.15);
    color: #f8fafc;
    border-radius: 8px;
    padding: 9px;
    font-size: 11px;
    font-weight: 700;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
  }
  .mes-action-btn-secondary:active { background: #475569; }

  /* Iframe Viewer Container */
  .mes-iframe-container {
    margin-top: 10px;
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    overflow: hidden;
    background: #0f172a;
    display: none;
  }
  .mes-iframe-header {
    background: #1e293b;
    padding: 8px 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border-color);
  }
  .mes-iframe-view {
    width: 100%;
    height: 520px;
    border: none;
    background: #ffffff;
  }

  /* Guide Notes */
  .mes-guide-step {
    font-size: 11px;
    color: #cbd5e1;
    line-height: 1.5;
    margin-bottom: 6px;
    padding-left: 14px;
    position: relative;
  }
  .mes-guide-step::before {
    content: "•";
    position: absolute;
    left: 4px;
    color: #38bdf8;
    font-weight: bold;
  }
  .mes-guide-step strong { color: #fff; }
  .mes-guide-step .blue-tag {
    background: #2563eb;
    color: #fff;
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 800;
  }

  /* Paste HTML Modal Overlay & Box */
  .modal-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.85);
    backdrop-filter: blur(6px);
    z-index: 9999;
    display: none;
    align-items: center;
    justify-content: center;
    padding: 16px;
  }
  .modal-overlay.active {
    display: flex;
  }
  .modal-box {
    background: #0f172a;
    border: 1px solid #38bdf8;
    border-radius: 16px;
    width: 100%;
    max-width: 480px;
    padding: 18px;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.7);
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .modal-title {
    font-size: 15px;
    font-weight: 800;
    color: #38bdf8;
  }
  .paste-textarea {
    width: 100%;
    height: 140px;
    background: #1e293b;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    color: #f8fafc;
    padding: 10px;
    font-family: 'Consolas', monospace;
    font-size: 11px;
    resize: vertical;
    outline: none;
    box-sizing: border-box;
  }
  .paste-textarea:focus {
    border-color: #38bdf8;
  }

  /* Trend Section Styles */
  .trend-bar-group {
    margin-bottom: 12px;
  }
  .trend-header-row {
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    font-weight: 700;
    color: #94a3b8;
    margin-bottom: 4px;
  }
  .trend-bar-track {
    height: 20px;
    background: #1e293b;
    border-radius: 6px;
    overflow: hidden;
    position: relative;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
  }
  .trend-bar-fill {
    height: 100%;
    border-radius: 6px;
    transition: width 0.4s ease;
  }
  .trend-bar-fill.soldering {
    background: linear-gradient(90deg, #f59e0b, #ef4444);
  }
  .trend-bar-fill.layup {
    background: linear-gradient(90deg, #10b981, #06b6d4);
  }
  .trend-bar-fill.lamination {
    background: linear-gradient(90deg, #8b5cf6, #ec4899);
  }
  .trend-bar-label {
    position: absolute;
    left: 8px;
    right: 8px;
    font-size: 10px;
    font-weight: 700;
    color: #fff;
    text-shadow: 0 1px 2px rgba(0,0,0,0.8);
    display: flex;
    justify-content: space-between;
    pointer-events: none;
  }
  .trend-table-container {
    max-height: 220px;
    overflow-y: auto;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    margin-top: 8px;
  }
  .trend-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 10px;
    text-align: left;
  }
  .trend-table th {
    background: #1e293b;
    padding: 6px 8px;
    color: #94a3b8;
    font-weight: 700;
    position: sticky;
    top: 0;
    z-index: 1;
  }
  .trend-table td {
    padding: 6px 8px;
    border-top: 1px solid #1e293b;
    color: #f8fafc;
    white-space: nowrap;
  }
</style>
</head>
<body>

<div id="toast" class="toast">Defect Logged</div>

<!-- HTTPS Switch Banner for HTTP Clients -->
<div id="https-banner" class="https-banner">
  <div style="display: flex; align-items: center; gap: 6px;">
    <span style="font-size: 14px;">⚡</span>
    <span>Live Camera Scanner (iPhone, Samsung, Pixel):</span>
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
    <video id="scanner-video" playsinline webkit-playsinline autoplay muted></video>
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
    <button class="scanner-fallback-btn primary-fallback" onclick="triggerBarcodePhotoOption()">📷 Take SN Photo (Native App)</button>
    <button class="scanner-fallback-btn" onclick="quickPasteSN()">📋 Paste SN</button>
  </div>
</div>

<!-- Barcode Options Modal (For HTTP / Fast Selection) -->
<div id="barcode-sheet-modal" class="modal-overlay" onclick="closeBarcodeSheetModal(event)">
  <div class="dialog-card" onclick="event.stopPropagation()">
    <div class="dialog-title">🏷️ Barcode & SN Options</div>
    <div class="dialog-sub">Universal Scanner for iPhone 15, Samsung & Pixel:</div>

    <button class="sheet-btn-option primary-option" onclick="switchToHTTPS()">
      <span style="font-size: 20px;">⚡</span>
      <div>
        <div>Open Live Camera Scanner (with Zoom)</div>
        <div style="font-size: 10px; opacity: 0.85;">Opens HTTPS :8443 for instant in-page scan. On Safari/Chrome, accept cert prompt once ("Show Details" / "Advanced" &rarr; "Visit Website")</div>
      </div>
    </button>

    <button class="sheet-btn-option" onclick="triggerBarcodePhotoOption();">
      <span style="font-size: 20px;">📷</span>
      <div>
        <div>Take Barcode Photo (Native Camera)</div>
        <div style="font-size: 10px; opacity: 0.85;">Works directly on plain HTTP with zero certificate steps on all devices</div>
      </div>
    </button>

    <button class="sheet-btn-option" onclick="closeBarcodeSheetModal(); quickPasteSN();">
      <span style="font-size: 20px;">📋</span>
      <div>
        <div>Paste from QR Scanner / Clipboard</div>
        <div style="font-size: 10px; opacity: 0.85;">Extracts copied V01 serial number from clipboard</div>
      </div>
    </button>

    <button class="sheet-btn-option" onclick="closeBarcodeSheetModal(); openSNModal();">
      <span style="font-size: 20px;">✏️</span>
      <div>
        <div>Enter SN Manually</div>
        <div style="font-size: 10px; opacity: 0.85;">Type or edit serial number directly</div>
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
    <button class="tab-btn" id="tab-btn-mes" onclick="switchTab('mes')">📋 MES Process Log</button>
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
        <div class="cam-title">2. Review Barcode</div>
        <div class="cam-sub" id="sn-cam-status">Defect Tab • SN Photos</div>
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

<!-- ================= TAB 3: MES PROCESS LOG ================= -->
<div id="tab-content-mes" class="tab-content">
  <!-- Module SN & 2 Ingest Ways -->
  <div class="mes-card">
    <div class="mes-card-title">
      <span>Module Serial Number (V01)</span>
      <span id="mes-query-badge" style="color: #38bdf8; font-size: 10px; font-weight: 700;">Ready</span>
    </div>

    <div class="mes-input-group">
      <input type="text" id="mes-sn-input" class="mes-sn-input" placeholder="Scan or enter V01..." autocomplete="off" autocorrect="off" autocapitalize="characters" oninput="onMESSNInputChanged()">
      <button class="mes-sn-btn" onclick="quickPasteMESText()" title="Paste SN from Clipboard">📋 Paste</button>
      <button class="mes-sn-btn" onclick="triggerQueryMES()" style="background: #2563eb; border-color: #60a5fa;" title="Query MES Logsheet">🔍 Query</button>
    </div>

    <!-- The 4 Ingest & Helper Ways (Barcode, Photo, Paste HTML, Chinese Guide) -->
    <div class="mes-ingest-grid">
      <button class="btn-mes-ingest" onclick="triggerBarcodeScannerForMES()">
        <span class="btn-mes-ingest-icon">📋</span>
        <span class="btn-mes-ingest-title">1. MES Barcode</span>
        <span class="btn-mes-ingest-sub">MES Log Tab • MES Photos</span>
      </button>

      <button class="btn-mes-ingest" onclick="triggerPhotoForMES()">
        <span class="btn-mes-ingest-icon">📷</span>
        <span class="btn-mes-ingest-title">2. Get SN Pic</span>
        <span class="btn-mes-ingest-sub">Photo (V01 OCR)</span>
      </button>

      <button class="btn-mes-ingest" onclick="openPasteHTMLModal()">
        <span class="btn-mes-ingest-icon">📋</span>
        <span class="btn-mes-ingest-title">3. Paste HTML</span>
        <span class="btn-mes-ingest-sub">Extract from MES</span>
      </button>

      <button class="btn-mes-ingest" onclick="openMESTranslationModal()" style="border-color: #60a5fa; background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);">
        <span class="btn-mes-ingest-icon">🇨🇳</span>
        <span class="btn-mes-ingest-title">4. Chinese Guide</span>
        <span class="btn-mes-ingest-sub">Page 1/2 Dictionary</span>
      </button>
    </div>
    <input type="file" id="mes-photo-file-input" accept="image/*" capture="environment" style="display: none;" onchange="onMESPhotoCaptured(event)">
  </div>

  <!-- Highlights Information (3 Key Machines: Soldering, Layup, Lamination) -->
  <div class="mes-card">
    <div class="mes-card-title">
      <span>Key Machine Highlights</span>
      <span style="font-size: 9px; color: var(--text-muted);">From Electronic Transfer Order (Page 2/2)</span>
    </div>

    <!-- 1. Welding (Stringer 101-706) -->
    <div class="mes-highlight-item" id="mes-card-soldering">
      <div>
        <div class="mes-highlight-name">Welding (Stringer)</div>
        <div class="mes-highlight-sub">Stringer 101–706 (焊接)</div>
      </div>
      <div id="mes-val-soldering" class="mes-badge mes-badge-pending">PENDING SN</div>
    </div>

    <!-- 2. Layup (TUMLAYUP) -->
    <div class="mes-highlight-item" id="mes-card-layup">
      <div>
        <div class="mes-highlight-name">Lay up (TUMLAYUP)</div>
        <div class="mes-highlight-sub">Lay up (敷设)</div>
      </div>
      <div id="mes-val-layup" class="mes-badge mes-badge-pending">PENDING SN</div>
    </div>

    <!-- 3. Lamination (Lam 1.1-21.2 & Deck) -->
    <div class="mes-highlight-item" id="mes-card-lamination">
      <div>
        <div class="mes-highlight-name">Lamination (Lam)</div>
        <div class="mes-highlight-sub">Lam 1.1–21.2 & Deck (层压)</div>
      </div>
      <div id="mes-val-lamination" class="mes-badge mes-badge-pending">PENDING SN</div>
    </div>

    <!-- Additional Process Fields (Auto-populated if extracted) -->
    <div id="mes-extra-details" style="display: none; background: #1e293b; border-radius: 8px; padding: 8px 10px; margin-top: 8px; font-size: 10px; color: #cbd5e1;">
      <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
        <span><strong>Family:</strong> <span id="mes-extra-family" style="color:#38bdf8;">-</span></span>
        <span><strong>Lot/料号:</strong> <span id="mes-extra-lot" style="color:#f59e0b;">-</span></span>
      </div>
      <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
        <span><strong>MO/工单:</strong> <span id="mes-extra-mo" style="color:#cbd5e1;">-</span></span>
        <span><strong>Grade/等级:</strong> <span id="mes-extra-grade" style="color:#10b981; font-weight:700;">-</span></span>
      </div>
      <div style="display: flex; justify-content: space-between;">
        <span><strong>Step/工序:</strong> <span id="mes-extra-step" style="color:#f43f5e; font-weight:700;">-</span></span>
        <span style="font-size: 9px; color: #94a3b8;"><a href="javascript:void(0)" onclick="openMESTranslationModal()" style="color:#38bdf8; text-decoration: none;">📖 Chinese Guide</a></span>
      </div>
    </div>
  </div>

  <!-- 1-Tap MES Web Direct Launchers & Quick Clipboard Helpers -->
  <div class="mes-card">
    <div class="mes-card-title">
      <span>MES Portal Access & Quick-Copy</span>
      <span style="color: #34d399; font-size: 10px;">10.200.3.109:8080</span>
    </div>

    <button class="mes-action-btn-primary" onclick="openMESReportDirect()">
      <span>🚀 Open MES Report Tab (416090fb...)</span>
      <span style="font-size: 11px; opacity: 0.85;">(Auto-copies SN)</span>
    </button>

    <div style="display: flex; gap: 6px; margin-bottom: 8px;">
      <button class="mes-action-btn-secondary" onclick="openMESLoginDirect()">
        <span>🔐 Open Login (030888)</span>
      </button>
      <button class="mes-action-btn-secondary" onclick="toggleMESIframe()">
        <span id="mes-iframe-toggle-text">🖥️ In-Page Viewer</span>
      </button>
    </div>

    <div class="mes-chip-bar">
      <span class="mes-chip" onclick="copyToClipboard('030888', 'Username')">👤 User: 030888</span>
      <span class="mes-chip" onclick="copyToClipboard('030888', 'Password')">🔑 Pass: 030888</span>
      <span class="mes-chip" onclick="copyCurrentMESSN()">📋 Copy Active SN</span>
    </div>

    <!-- Quick Chinese Translation Launcher -->
    <button class="mes-action-btn-secondary" style="border-color: #38bdf8; background: rgba(56, 189, 248, 0.12); color: #38bdf8; font-weight: 700; width: 100%; justify-content: center; gap: 8px; margin-top: 8px;" onclick="openMESTranslationModal()">
      <span style="font-size: 15px;">🇨🇳 ⇄ 🇺🇸</span>
      <span>Open Chinese MES Field Dictionary & Live Translator</span>
    </button>
  </div>

  <!-- Embedded In-Page MES Iframe (Toggleable) -->
  <div class="mes-iframe-container" id="mes-iframe-container">
    <div class="mes-iframe-header">
      <div style="display: flex; gap: 4px; align-items: center;">
        <button class="mes-sn-btn" style="padding: 4px 8px; font-size: 10px;" onclick="loadMESIframe('report')">📄 Report</button>
        <button class="mes-sn-btn" style="padding: 4px 8px; font-size: 10px;" onclick="loadMESIframe('login')">🔐 Login</button>
      </div>
      <div style="display: flex; gap: 4px; align-items: center;">
        <button class="mes-sn-btn" style="padding: 4px 8px; font-size: 10px;" onclick="reloadMESIframe()">🔄 Reload</button>
        <button class="mes-sn-btn" style="padding: 4px 8px; font-size: 10px; background: #dc2626;" onclick="toggleMESIframe()">✕</button>
      </div>
    </div>
    <iframe id="mes-frame" class="mes-iframe-view" src="about:blank"></iframe>
  </div>

  <!-- Visual Operator Guide Card -->
  <div class="mes-card">
    <div class="mes-card-title">📖 Operator Guide & Field Reference</div>
    <div class="mes-guide-step">
      <strong>Login Credentials:</strong> Username <code style="color:#38bdf8;">030888</code> | Password <code style="color:#38bdf8;">030888</code>
    </div>
    <div class="mes-guide-step">
      <strong>Prompts & Popups:</strong> Click <span class="blue-tag">[ 确定 / OK ]</span> to confirm and dismiss session dialogs.
    </div>
    <div class="mes-guide-step">
      <strong>Parameter Search:</strong> Paste SN into <strong>组件序列号:</strong> (or <strong>Module Serial No:</strong>) and tap <strong>[ 查询 / Query ]</strong>.
    </div>
    <div class="mes-guide-step">
      <strong>Chinese (Page 1/2) vs English (Page 2/2):</strong><br>
      • <code>组件生产流转</code> = Module Production Routing (Page 1/2)<br>
      • <code>焊接</code> = Welding / Stringing (<code>TUMSOLERING</code> / <code>TUMSOLDERING</code>)<br>
      • <code>敷设</code> = Lay up / Assembly (<code>TUMLAYUP</code>)<br>
      • <code>层压</code> = Lamination (<code>TUMLAMINATION</code>)<br>
      • <code>料号</code> = Lot / Part Number | <code>工单号</code> = MO Number<br>
      • <code>耐压</code> = Hi-Pot Test | <code>当前工序</code> = Current Station
    </div>
    <div style="margin-top: 8px;">
      <button class="mes-sn-btn" style="width: 100%; padding: 7px; font-size: 11px; background: #1e293b; border-color: #38bdf8; color: #38bdf8;" onclick="openMESTranslationModal()">
        📖 View Full Chinese ⇄ English Translation Dictionary
      </button>
    </div>
  </div>

  <!-- Machine Trend Analytics Card -->
  <div class="mes-card" id="mes-trend-card">
    <div class="mes-card-title">
      <div style="display: flex; align-items: center; gap: 6px;">
        <span>📊 Machine Trend Analytics</span>
        <span id="mes-trend-count" style="font-size: 10px; color: #38bdf8; font-weight: 700;">(0 logged)</span>
      </div>
      <div style="display: flex; gap: 4px;">
        <button class="mes-sn-btn" style="padding: 3px 8px; font-size: 10px;" onclick="fetchMESTrendAnalytics()" title="Refresh Trend Analytics">🔄</button>
        <button class="mes-sn-btn" style="padding: 3px 8px; font-size: 10px; background: #059669; border-color: #34d399;" onclick="exportMESTrendCSV()" title="Export CSV Report">📥 Export</button>
      </div>
    </div>

    <!-- Trend Distribution Bars -->
    <div style="margin-top: 6px;">
      <!-- Soldering Machines -->
      <div class="trend-bar-group">
        <div class="trend-header-row">
          <span>🔥 Welding Stringers (Stringer 101–706)</span>
          <span id="trend-soldering-summary" style="color: #cbd5e1;">-</span>
        </div>
        <div id="trend-soldering-bars">
          <div style="font-size: 10px; color: var(--text-muted); font-style: italic;">No stringer records yet</div>
        </div>
      </div>

      <!-- Layup Machines -->
      <div class="trend-bar-group">
        <div class="trend-header-row">
          <span>🧩 Layup Machines (TUMLAYUP)</span>
          <span id="trend-layup-summary" style="color: #cbd5e1;">-</span>
        </div>
        <div id="trend-layup-bars">
          <div style="font-size: 10px; color: var(--text-muted); font-style: italic;">No layup records yet</div>
        </div>
      </div>

      <!-- Lamination Machines -->
      <div class="trend-bar-group">
        <div class="trend-header-row">
          <span>⚡ Lamination Machines (Lam 1.1–21.2)</span>
          <span id="trend-lamination-summary" style="color: #cbd5e1;">-</span>
        </div>
        <div id="trend-lamination-bars">
          <div style="font-size: 10px; color: var(--text-muted); font-style: italic;">No lamination records yet</div>
        </div>
      </div>
    </div>

    <!-- Recent Modules Logged Table -->
    <div style="margin-top: 10px;">
      <div style="font-size: 11px; font-weight: 700; color: #94a3b8; margin-bottom: 4px;">Recent Processed Modules:</div>
      <div class="trend-table-container">
        <table class="trend-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Serial Number</th>
              <th>Stringer</th>
              <th>Layup</th>
              <th>Lam (Deck)</th>
            </tr>
          </thead>
          <tbody id="trend-recent-tbody">
            <tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No records logged yet</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Modal for Pasting HTML / Text from FineReport -->
  <div class="modal-overlay" id="html-paste-modal" onclick="if(event.target===this)closePasteHTMLModal()">
    <div class="modal-box" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div class="modal-title">📋 Extract MES Info from HTML / Text</div>
        <button class="mes-sn-btn" style="padding: 2px 8px; font-size: 12px; background: #475569;" onclick="closePasteHTMLModal()">✕</button>
      </div>
      <div style="font-size: 11px; color: var(--text-muted); line-height: 1.4;">
        In Chrome on your phone, copy the page content or HTML table from <strong>Electronic Transfer Order (Page 2/2)</strong> or <strong>组件生产流转 (Page 1/2)</strong>, then paste below to auto-extract <strong>TUMSOLDERING</strong>, <strong>TUMLAYUP</strong>, and <strong>TUMLAMINATION</strong>.
      </div>
      <textarea id="mes-html-paste-input" class="paste-textarea" placeholder="Paste copied HTML source or table text here..."></textarea>
      <div style="display: flex; gap: 8px; justify-content: flex-end;">
        <button class="mes-sn-btn" style="background: #334155;" onclick="pasteClipboardToHTMLInput()">📋 Paste Clipboard</button>
        <button class="mes-sn-btn" style="background: #2563eb; border-color: #60a5fa;" onclick="submitHTMLForExtraction()">⚡ Extract & Highlight</button>
      </div>
    </div>
  </div>

  <!-- Modal for Chinese MES Translation & Dictionary -->
  <div class="modal-overlay" id="mes-translation-modal" onclick="if(event.target===this)closeMESTranslationModal()">
    <div class="modal-box" style="max-height: 88vh; display: flex; flex-direction: column; overflow: hidden;" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div class="modal-title">🇨🇳 MES Chinese ⇄ English Guide</div>
        <button class="mes-sn-btn" style="padding: 2px 8px; font-size: 12px; background: #475569;" onclick="closeMESTranslationModal()">✕</button>
      </div>

      <!-- Live Chinese Translator Box -->
      <div style="background: #1e293b; border-radius: 10px; padding: 8px 10px; margin-bottom: 8px; border: 1px solid #334155; flex-shrink: 0;">
        <div style="font-size: 11px; font-weight: 700; color: #38bdf8; margin-bottom: 4px; display: flex; justify-content: space-between;">
          <span>🌐 Live Chinese Translator</span>
          <span style="font-size: 9px; color: #94a3b8;">Type or paste text</span>
        </div>
        <div style="display: flex; gap: 6px;">
          <input type="text" id="mes-trans-live-input" class="mes-sn-input" style="font-size: 12px; height: 34px; padding: 6px 10px;" placeholder="Paste Chinese (e.g. M12工序NG自动Hold, 焊接, 上层3号位)..." oninput="onMESTranslateInputChanged()">
          <button class="mes-sn-btn" style="padding: 6px 10px; font-size: 11px;" onclick="pasteToMESTranslator()">📋 Paste</button>
        </div>
        <div id="mes-trans-live-result" style="display: none; margin-top: 6px; padding: 6px 8px; background: #0f172a; border-radius: 6px; border: 1px solid #38bdf8; font-size: 11px; color: #4ade80;">
          <strong>Translation:</strong> <span id="mes-trans-live-text">-</span>
        </div>
      </div>

      <!-- Search Dictionary Filter -->
      <div style="display: flex; gap: 6px; margin-bottom: 6px; flex-shrink: 0;">
        <input type="text" id="mes-dict-search-input" class="mes-sn-input" style="font-size: 12px; height: 34px; padding: 6px 10px;" placeholder="🔍 Filter terms (e.g. 焊接, layup, Q3, 耐压)..." oninput="filterMESDictionary()">
        <button class="mes-sn-btn" style="padding: 6px 10px; font-size: 11px;" onclick="clearMESDictFilter()">Clear</button>
      </div>

      <!-- Category Filter Pills -->
      <div style="display: flex; gap: 4px; overflow-x: auto; padding-bottom: 4px; margin-bottom: 6px; flex-shrink: 0;">
        <button class="dict-pill active" onclick="filterMESCategory('all', this)">All</button>
        <button class="dict-pill" onclick="filterMESCategory('Header', this)">Headers</button>
        <button class="dict-pill" onclick="filterMESCategory('Front-End', this)">Front-End</button>
        <button class="dict-pill" onclick="filterMESCategory('Back-End', this)">Back-End</button>
        <button class="dict-pill" onclick="filterMESCategory('Electrical', this)">Electrical</button>
        <button class="dict-pill" onclick="filterMESCategory('Status', this)">Status</button>
      </div>

      <!-- Scrollable List of Dictionary Items -->
      <div id="mes-dict-list-container" style="flex: 1; overflow-y: auto; padding-right: 4px; display: flex; flex-direction: column; gap: 6px;">
      </div>

      <div style="margin-top: 6px; font-size: 9px; color: var(--text-muted); text-align: center; flex-shrink: 0;">
        Page 1/2 is Chinese (组件生产流转) • Page 2/2 is English (Process Logsheet)
      </div>
    </div>
  </div>
</div>

<script>
const MES_BASE_URL = "http://10.200.3.109:8080";
const MES_ACCESS_URL = "http://10.200.3.109:8080/webroot/decision/v10/entry/access/416090fb-b706-40e8-9e4d-d698a059f6bf";
const MES_REPORT_URL = "http://10.200.3.109:8080/webroot/decision#/?activeTab=416090fb-b706-40e8-9e4d-d698a059f6bf";
const MES_LOGIN_URL = "http://10.200.3.109:8080/webroot/decision/login";

const DEFECT_TREE = {{DEFECT_TREE_JSON}};
const MES_CHINESE_DICT = {{MES_CHINESE_DICT_JSON}};

let selectedClass = Object.keys(DEFECT_TREE)[0] || "Cells Defect";
let selectedSummary = DEFECT_TREE[selectedClass] ? DEFECT_TREE[selectedClass][0] : "";
let currentPhotoType = 'DEFECT_PHOTO';
let currentSN = '';
let currentMESSN = '';
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

// 1. Text Parsing & SN Extraction Helper (Strict V01 Module SN Validation)
function extractSNFromText(text) {
  if (!text) return '';
  text = text.trim();
  
  // 1. Primary Rule: Matches V01 + 7-20 alphanumeric characters (e.g. V01269003050237)
  const mV01 = text.match(/\\b(V01[0-9A-Za-z]{7,20})\\b/i);
  if (mV01) return mV01[1].toUpperCase();

  // 2. Matches "Trina Solar V01..." or "SN: V01..." or "S/N: V01..."
  const mTrinaV01 = text.match(/(?:Trina\\s*Solar\\s*|SN:\\s*|S\\/N:\\s*)(V01[0-9A-Za-z]{7,20})/i);
  if (mTrinaV01) return mTrinaV01[1].toUpperCase();

  // 3. Clean direct check: starts with V01
  const clean = text.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
  if (clean.startsWith('V01') && clean.length >= 10) {
    return clean;
  }
  
  // Discard all non-V01 barcodes (such as model barcodes 615NEG19RC...)
  return '';
}

// 2A. Dedicated MES Serial Number Ingest (Isolated from Defect Review)
function setMESSerialNumber(sn, source = 'MES') {
  if (!sn) return;
  const clean = extractSNFromText(sn) || (sn.toUpperCase().startsWith('V01') ? sn.trim().toUpperCase() : '');
  if (!clean) return;
  currentMESSN = clean;
  const mesInput = document.getElementById('mes-sn-input');
  if (mesInput) mesInput.value = clean;
  const badge = document.getElementById('mes-query-badge');
  if (badge) { badge.innerText = 'Auto-Querying MES...'; badge.style.color = '#38bdf8'; }

  // 1. Automated background login & prefetch to FineReport
  autoLoginFineReportOnPhone(clean);

  // 2. Query MES process log details (synchronizes UI, trend log, and desktop)
  if (typeof queryMESProcessLog === 'function') {
    queryMESProcessLog(clean);
  }
}

function autoLoginFineReportOnPhone(cleanSN) {
  // Pre-authenticates phone browser into FineReport with 030888/030888 via cross-domain SSO
  const ssoUrl = `${MES_BASE_URL}/webroot/decision/login/cross/domain?fine_username=030888&fine_password=030888&validity=-2`;
  const ssoScript = document.createElement('script');
  ssoScript.src = ssoUrl;
  ssoScript.async = true;
  document.head.appendChild(ssoScript);
  setTimeout(() => { try { document.head.removeChild(ssoScript); } catch(e){} }, 3000);

  // Pre-load in-page iframe to the exact entry access with SN parameter
  const frame = document.getElementById('mes-frame');
  if (frame && cleanSN) {
    frame.src = `${MES_ACCESS_URL}?preview=true&MOUDLEID=${encodeURIComponent(cleanSN)}&__bypassevent__=true&组件序列号=${encodeURIComponent(cleanSN)}&SN=${encodeURIComponent(cleanSN)}`;
  }
}


// 2B. Set Active Serial Number for Defect Control & Sync to Desktop App
async function setSerialNumber(sn, source = 'Manual') {
  if (!sn) return;
  // STRICT TAB ISOLATION GUARD: Never route MES activity to Defect Review!
  if (typeof currentMobileTab !== 'undefined' && (currentMobileTab === 'mes' || scannerTarget === 'MES')) {
    setMESSerialNumber(sn, source);
    return;
  }

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
          if (currentMobileTab === 'mes' || scannerTarget === 'MES') {
            setMESSerialNumber(sn, 'Clipboard Paste');
            showToast(`✅ MES SN: ${sn}`);
          } else {
            setSerialNumber(sn, 'Clipboard Paste');
            showToast(`✅ Pasted SN: ${sn}`);
          }
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
    if (sn && sn.length >= 8) {
      if (currentMobileTab === 'mes' || scannerTarget === 'MES') {
        setMESSerialNumber(sn, 'Auto-Clipboard');
        showToast(`📋 Auto-detected MES SN: ${sn}`);
        playScanBeep();
        if (navigator.vibrate) navigator.vibrate([60, 40, 60]);
      } else if (sn !== currentSN) {
        setSerialNumber(sn, 'Auto-Clipboard');
        showToast(`📋 Auto-detected SN from QR: ${sn}`);
        playScanBeep();
        if (navigator.vibrate) navigator.vibrate([60, 40, 60]);
      }
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
  if (typeof currentMobileTab !== 'undefined' && (currentMobileTab === 'mes' || scannerTarget === 'MES')) {
    const mesInput = document.getElementById('mes-sn-input');
    input.value = (mesInput && mesInput.value.trim()) || currentMESSN || '';
  } else {
    input.value = currentSN && currentSN !== 'Pending SN' ? currentSN : '';
  }
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
    if (currentMobileTab === 'mes' || scannerTarget === 'MES') {
      setMESSerialNumber(sn, 'Manual Input');
      showToast(`✅ MES Serial Number set: ${sn}`);
    } else {
      setSerialNumber(sn, 'Manual Input');
      showToast(`✅ Serial Number set: ${sn}`);
    }
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
  scannerTarget = 'CONTROL';
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

function triggerBarcodePhotoOption() {
  closeBarcodeSheetModal();
  if (scannerTarget === 'MES') {
    triggerPhotoForMES();
  } else {
    triggerFileCamera('SN_PHOTO');
  }
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
  hint.innerText = (scannerTarget === 'MES' || (typeof currentMobileTab !== 'undefined' && currentMobileTab === 'mes'))
    ? '📋 Align Barcode for Factory MES Log'
    : '🏷️ Align Barcode for Module Review';
  isTorchActive = false;

  // iOS Safari requires attributes before attaching stream
  video.setAttribute('playsinline', 'true');
  video.setAttribute('webkit-playsinline', 'true');
  video.muted = true;

  const constraints = {
    video: {
      facingMode: { ideal: currentFacingMode },
      width: { ideal: 1280, max: 1920 },
      height: { ideal: 720, max: 1080 }
    },
    audio: false
  };

  try {
    activeMediaStream = await navigator.mediaDevices.getUserMedia(constraints);
  } catch (err1) {
    console.warn('Initial camera constraints failed, trying basic fallback:', err1);
    try {
      activeMediaStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: currentFacingMode },
        audio: false
      });
    } catch (err2) {
      console.error('All camera access attempts failed:', err2);
      closeLiveScanner();
      showToast('❌ Camera stream failed or denied', true);
      openBarcodeSheetModal();
      return;
    }
  }

  video.srcObject = activeMediaStream;
  try {
    await video.play();
  } catch (playErr) {
    console.warn('Waiting for video loadedmetadata to play:', playErr);
    await new Promise((resolve) => {
      video.onloadedmetadata = () => {
        video.play().then(resolve).catch(resolve);
      };
      setTimeout(resolve, 800);
    });
  }

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
      showToast('Flashlight not supported on this browser/stream');
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

  // Tier 1: Hardware BarcodeDetector (Google Pixel 6a / Chromium Android)
  let nativeDetector = null;
  if ('BarcodeDetector' in window) {
    try {
      nativeDetector = new BarcodeDetector({ formats: ['qr_code', 'code_128', 'code_39', 'data_matrix', 'ean_13', 'upc_a'] });
    } catch(e) {}
  }

  // Tier 3: ZXing MultiFormat Reader (Code 128 / Code 39 / Data Matrix on iPhone 15 & Samsung)
  let zxingReader = null;
  if (window.ZXing && window.ZXing.BrowserMultiFormatReader) {
    try {
      zxingReader = new ZXing.BrowserMultiFormatReader();
    } catch(e) {}
  }

  // Shared offscreen canvas for high-performance frame sampling
  const scanCanvas = document.createElement('canvas');

  while (liveScannerRunning) {
    if (video.readyState >= 2) {
      let foundSN = '';
      let sawWrongBarcode = false;
      let wrongRaw = '';

      // --- TIER 1: Native BarcodeDetector (<5ms) ---
      if (nativeDetector) {
        try {
          const barcodes = await nativeDetector.detect(video);
          if (barcodes && barcodes.length > 0) {
            for (const b of barcodes) {
              const raw = (b.rawValue || '').trim();
              const clean = extractSNFromText(raw);
              if (clean && clean.startsWith('V01')) {
                foundSN = clean;
                break;
              } else if (raw) {
                sawWrongBarcode = true;
                wrongRaw = raw.split('|')[0].trim();
              }
            }
          }
        } catch (detErr) {}
      }

      // --- TIER 2: Fast jsQR Engine (10-25ms) for iPhone 15 Safari & Samsung Internet ---
      if (!foundSN && window.jsQR) {
        try {
          const vw = video.videoWidth || 640;
          const vh = video.videoHeight || 480;
          const scale = Math.min(1.0, 720 / Math.max(vw, vh));
          const sw = Math.round(vw * scale);
          const sh = Math.round(vh * scale);

          scanCanvas.width = sw;
          scanCanvas.height = sh;
          const sctx = scanCanvas.getContext('2d', { willReadFrequently: true });
          sctx.drawImage(video, 0, 0, sw, sh);
          const imgData = sctx.getImageData(0, 0, sw, sh);
          const qr = jsQR(imgData.data, imgData.width, imgData.height, { inversionAttempts: "attemptBoth" });
          if (qr && qr.data) {
            const raw = qr.data.trim();
            const clean = extractSNFromText(raw);
            if (clean && clean.startsWith('V01')) {
              foundSN = clean;
            } else if (raw) {
              sawWrongBarcode = true;
              wrongRaw = raw.split('|')[0].trim();
            }
          }
        } catch (qrErr) {}
      }

      // --- TIER 3: ZXing MultiFormat Reader for 1D Barcode & DataMatrix on iPhone 15 & Samsung ---
      if (!foundSN && zxingReader) {
        try {
          const zxResult = zxingReader.decode(video);
          if (zxResult && zxResult.text) {
            const raw = zxResult.text.trim();
            const clean = extractSNFromText(raw);
            if (clean && clean.startsWith('V01')) {
              foundSN = clean;
            } else if (raw) {
              sawWrongBarcode = true;
              wrongRaw = raw.split('|')[0].trim();
            }
          }
        } catch (zxErr) {
          // ZXing throws NotFoundException when frame has no code, expected
        }
      }

      if (foundSN) {
        // Instant Lock on V01 SN!
        liveScannerRunning = false;
        reticle.classList.add('detected');
        hint.innerHTML = `<span style="color:#10b981; font-weight:bold;">✅ Found: ${foundSN}</span>`;
        
        playScanBeep();
        if (navigator.vibrate) navigator.vibrate([60, 40, 60]);

        // Snap high-res frame and upload directly
        captureAndUploadLiveFrame(video, foundSN);
        
        setTimeout(() => {
          closeLiveScanner();
        }, 350);
        return;
      } else if (sawWrongBarcode) {
        // Show real-time guidance warning on screen
        hint.innerHTML = `<span style="color:#f59e0b; font-weight:bold; font-size:12px;">⚠️ Model Barcode (${wrongRaw.slice(0, 16)})<br>Aim at bottom Barcode (starts with V01)</span>`;
      }
    }
    await new Promise(r => setTimeout(r, 60)); // Fast ~16 FPS detection loop
  }
}

async function captureAndUploadLiveFrame(video, detectedSN) {
  const isMes = (scannerTarget === 'MES' || (typeof currentMobileTab !== 'undefined' && currentMobileTab === 'mes'));
  if (isMes) {
    closeLiveScanner();
    setMESSerialNumber(detectedSN, 'MES Live Scanner');
    showToast(`✅ Scanned MES SN: ${detectedSN}`);
    playScanBeep();
    if (navigator.vibrate) navigator.vibrate([40, 30, 40]);
  } else {
    setSerialNumber(detectedSN, 'Live Scanner');
    showToast(`✅ Scanned SN: ${detectedSN}`);
  }

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
      const targetParam = isMes ? `&type=MES_PHOTO&target_tab=mes` : `&type=SN_PHOTO&target_tab=control`;
      const resp = await fetch(`/api/upload_photo?timestamp=${ts}${snParam}${targetParam}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: blob
      });
      if (resp.ok && isMes) {
        try {
          const upData = await resp.json();
          if (upData && (upData.raw_found || upData.tumsoldering || upData.tumlayup || upData.tumlamination)) {
            if (typeof applyMESDataToUI === 'function') {
              applyMESDataToUI(upData);
            }
          }
        } catch (jsonErr) {}
      }
    } catch(e) {
      console.warn('Live snapshot upload error:', e);
    }
  }, 'image/jpeg', 0.92);
}

// 8. Direct On-Device Pixel 6a Scanner for Photo Capture Fallback
async function onCameraPhotoCaptured(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;

  // STRICT TAB ISOLATION GUARD:
  if (typeof currentMobileTab !== 'undefined' && (currentMobileTab === 'mes' || scannerTarget === 'MES')) {
    onMESPhotoCaptured(e);
    return;
  }

  const type = currentPhotoType;
  const statusEl = document.getElementById(type === 'SN_PHOTO' ? 'sn-cam-status' : 'def-cam-status');
  
  if (statusEl) statusEl.innerText = type === 'SN_PHOTO' ? '⏳ Scanning QR...' : '⏳ Uploading...';
  showToast(`Uploading ${type === 'SN_PHOTO' ? 'Barcode' : 'Defect'} photo...`);

  // Universal on-device barcode recognition (<50ms)
  let clientDetectedSN = '';
  if (type === 'SN_PHOTO') {
    // 1. Native BarcodeDetector (Google Pixel 6a / Android Chrome)
    if ('BarcodeDetector' in window) {
      try {
        const detector = new BarcodeDetector({ formats: ['qr_code', 'code_128', 'code_39', 'data_matrix', 'ean_13', 'upc_a'] });
        const imgBitmap = await createImageBitmap(file);
        const detected = await detector.detect(imgBitmap);
        if (detected && detected.length > 0) {
          for (const d of detected) {
            const raw = (d.rawValue || '').trim();
            const clean = extractSNFromText(raw);
            if (clean && clean.startsWith('V01')) {
              clientDetectedSN = clean;
              break;
            }
          }
        }
      } catch (detErr) {}
    }

    // 2. jsQR Fallback (iPhone 15 & Samsung)
    if (!clientDetectedSN && window.jsQR) {
      try {
        const imgBitmap = await createImageBitmap(file);
        const canvas = document.createElement('canvas');
        canvas.width = imgBitmap.width;
        canvas.height = imgBitmap.height;
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(imgBitmap, 0, 0);
        const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const qr = jsQR(imgData.data, imgData.width, imgData.height, { inversionAttempts: "attemptBoth" });
        if (qr && qr.data) {
          const clean = extractSNFromText(qr.data);
          if (clean && clean.startsWith('V01')) clientDetectedSN = clean;
        }
      } catch (e) {}
    }

    // 3. ZXing Fallback (iPhone 15 & Samsung for 1D/DataMatrix)
    if (!clientDetectedSN && window.ZXing && window.ZXing.BrowserMultiFormatReader) {
      try {
        const reader = new ZXing.BrowserMultiFormatReader();
        const img = new Image();
        img.src = URL.createObjectURL(file);
        await new Promise((res) => { img.onload = res; img.onerror = res; });
        const zx = reader.decode(img);
        if (zx && zx.text) {
          const clean = extractSNFromText(zx.text);
          if (clean && clean.startsWith('V01')) clientDetectedSN = clean;
        }
        URL.revokeObjectURL(img.src);
      } catch (e) {}
    }

    if (clientDetectedSN) {
      setSerialNumber(clientDetectedSN, 'Photo Client Scanner');
      playScanBeep();
      if (navigator.vibrate) navigator.vibrate([40, 30, 40]);
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

let currentMobileTab = 'control'; // 'control', 'dashboard', 'mes'

function switchTab(tabId) {
  currentMobileTab = tabId;
  if (tabId === 'mes') {
    scannerTarget = 'MES';
  } else {
    scannerTarget = 'CONTROL';
  }

  document.getElementById('tab-btn-control').classList.toggle('active', tabId === 'control');
  document.getElementById('tab-btn-dashboard').classList.toggle('active', tabId === 'dashboard');
  const btnMes = document.getElementById('tab-btn-mes');
  if (btnMes) btnMes.classList.toggle('active', tabId === 'mes');

  document.getElementById('tab-content-control').classList.toggle('active', tabId === 'control');
  document.getElementById('tab-content-dashboard').classList.toggle('active', tabId === 'dashboard');
  const contentMes = document.getElementById('tab-content-mes');
  if (contentMes) contentMes.classList.toggle('active', tabId === 'mes');

  if (tabId === 'dashboard') {
    fetchDashboardStatus();
  } else if (tabId === 'mes') {
    // STRICT TAB ISOLATION: Do not sync MR tab's currentSN into MES tab!
    fetchMESTrendAnalytics();
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
    if (data.last_mes && data.last_mes.sn) {
      const mesInput = document.getElementById('mes-sn-input');
      const curVal = (mesInput ? mesInput.value.trim() : '') || currentMESSN || '';
      if (!curVal || curVal === data.last_mes.sn || (currentMESSN && currentMESSN === data.last_mes.sn)) {
        if (!curVal && mesInput) {
          mesInput.value = data.last_mes.sn;
          currentMESSN = data.last_mes.sn;
        }
        if (data.last_mes.raw_found || data.last_mes.tumsoldering || data.last_mes.tumlayup || data.last_mes.tumlamination) {
          if (typeof applyMESDataToUI === 'function') {
            applyMESDataToUI(data.last_mes);
          }
        }
      }
    }

    const syncEl = document.getElementById('sync-status');
    if (syncEl) syncEl.innerText = 'LIVE SYNC';
  } catch (err) {
    const syncEl = document.getElementById('sync-status');
    if (syncEl) syncEl.innerText = 'RECONNECTING...';
  }
}

// ================== TAB 3: MES PROCESS LOG HELPERS ==================
let scannerTarget = 'CONTROL'; // 'CONTROL' or 'MES'

function triggerBarcodeScannerForMES() {
  scannerTarget = 'MES';
  if (location.protocol === 'https:' && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    openLiveScanner();
  } else {
    const sheet = document.getElementById('barcode-sheet-modal');
    if (sheet) sheet.classList.add('active');
    else triggerPhotoForMES();
  }
}

function triggerPhotoForMES() {
  scannerTarget = 'MES';
  const inp = document.getElementById('mes-photo-file-input');
  if (inp) {
    inp.value = '';
    inp.click();
  }
}

async function onMESPhotoCaptured(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;

  showToast('🔍 Analyzing picture for V01 SN...');
  const badge = document.getElementById('mes-query-badge');
  if (badge) { badge.innerText = 'Extracting SN...'; badge.style.color = '#f59e0b'; }

  let detectedSN = '';
  // 1. Instant client-side BarcodeDetector (<5ms, Pixel 6a)
  if ('BarcodeDetector' in window) {
    try {
      const detector = new BarcodeDetector({ formats: ['qr_code', 'code_128', 'code_39', 'data_matrix', 'ean_13', 'upc_a'] });
      const imgBitmap = await createImageBitmap(file);
      const detected = await detector.detect(imgBitmap);
      if (detected && detected.length > 0) {
        for (const d of detected) {
          const clean = extractSNFromText((d.rawValue || '').trim());
          if (clean && clean.startsWith('V01')) {
            detectedSN = clean;
            break;
          }
        }
      }
    } catch(err) {}
  }

  // 2. jsQR Client Fallback (iPhone 15 & Samsung)
  if (!detectedSN && window.jsQR) {
    try {
      const imgBitmap = await createImageBitmap(file);
      const canvas = document.createElement('canvas');
      canvas.width = imgBitmap.width;
      canvas.height = imgBitmap.height;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(imgBitmap, 0, 0);
      const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const qr = jsQR(imgData.data, imgData.width, imgData.height, { inversionAttempts: "attemptBoth" });
      if (qr && qr.data) {
        const clean = extractSNFromText(qr.data);
        if (clean && clean.startsWith('V01')) detectedSN = clean;
      }
    } catch (e) {}
  }

  // 3. ZXing Client Fallback (iPhone 15 & Samsung for 1D/DataMatrix)
  if (!detectedSN && window.ZXing && window.ZXing.BrowserMultiFormatReader) {
    try {
      const reader = new ZXing.BrowserMultiFormatReader();
      const img = new Image();
      img.src = URL.createObjectURL(file);
      await new Promise((res) => { img.onload = res; img.onerror = res; });
      const zx = reader.decode(img);
      if (zx && zx.text) {
        const clean = extractSNFromText(zx.text);
        if (clean && clean.startsWith('V01')) detectedSN = clean;
      }
      URL.revokeObjectURL(img.src);
    } catch (e) {}
  }

  // 4. Server-side robust fallback: EasyOCR extracts SN AND Machines AND Layup Time from photos/screenshots
  try {
    const res = await fetch('/api/extract_sn_from_image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file
    });
    if (res.ok) {
      const data = await res.json();
      if (!detectedSN && data.sn) detectedSN = data.sn;
      if (data.tumsoldering || data.tumlayup || data.tumlamination || data.layup_time) {
        if (typeof applyMESDataToUI === 'function') {
          applyMESDataToUI(data);
        }
        showToast('✅ Machine details extracted from screen photo!');
      }
    }
  } catch(srvErr) {
    console.warn('Server OCR error:', srvErr);
  }

  if (detectedSN) {
    setMESSerialNumber(detectedSN, 'MES Picture');
    showToast(`✅ Extracted SN: ${detectedSN}`);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(detectedSN).catch(()=>{});
    }
  } else {
    if (badge) { badge.innerText = 'No V01 SN found'; badge.style.color = '#ef4444'; }
    showToast('⚠️ Could not find V01 SN in picture. Please try closer or enter manually.', true);
  }
}

function applyMESDataToUI(data) {
  if (!data) return;
  const badge = document.getElementById('mes-query-badge');
  const hasMachines = !!(data.raw_found || data.tumsoldering || data.tumlayup || data.tumlamination);
  
  if (hasMachines) {
    if (badge) {
      badge.innerText = 'Logsheet Retrieved';
      badge.style.color = '#10b981';
    }
  } else if (data.status === 'ok') {
    if (badge) {
      badge.innerText = 'No Record for SN';
      badge.style.color = '#f59e0b';
    }
  }

  updateHighlightCard('soldering', data.tumsoldering);
  updateHighlightCard('layup', data.tumlayup, data.layup_time);
  updateHighlightCard('lamination', data.tumlamination);

  if (data.layup_time) {
    const layupEl = document.getElementById('panel-layup');
    if (layupEl) layupEl.innerText = data.layup_time;
  }

  if (data.product_family || data.lot_no || data.mo_no || data.appearance_grade) {
    const extraBox = document.getElementById('mes-extra-details');
    if (extraBox) {
      extraBox.style.display = 'block';
      const setSpan = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = val || '-'; };
      setSpan('mes-extra-family', data.product_family);
      setSpan('mes-extra-lot', data.lot_no);
      setSpan('mes-extra-mo', data.mo_no);
      setSpan('mes-extra-grade', data.appearance_grade);
    }
  }

  if (typeof fetchMESTrendAnalytics === 'function') {
    fetchMESTrendAnalytics();
  }
}

async function pollMESResultUntilFound(sn, maxRetries = 3) {
  for (let i = 0; i < maxRetries; i++) {
    await new Promise(r => setTimeout(r, 1500));
    try {
      const res = await fetch(`/api/mes_query?sn=${encodeURIComponent(sn)}`);
      if (res.ok) {
        const d = await res.json();
        if (d && (d.raw_found || d.tumsoldering || d.tumlayup || d.tumlamination)) {
          return d;
        }
      }
    } catch(e) {}
  }
  return null;
}

async function queryMESProcessLog(sn) {
  if (!sn) {
    const mesInput = document.getElementById('mes-sn-input');
    sn = mesInput ? mesInput.value.trim() : '';
  }
  const cleanSN = extractSNFromText(sn) || (sn.toUpperCase().startsWith('V01') ? sn.trim().toUpperCase() : '');
  if (!cleanSN) {
    return;
  }

  currentMESSN = cleanSN;
  const mesInput = document.getElementById('mes-sn-input');
  if (mesInput && mesInput.value !== cleanSN) mesInput.value = cleanSN;

  const badge = document.getElementById('mes-query-badge');
  if (badge) { badge.innerText = 'Auto-Querying MES...'; badge.style.color = '#38bdf8'; }

  setHighlightBadge('soldering', 'Checking...', 'pending');
  setHighlightBadge('layup', 'Checking...', 'pending');
  setHighlightBadge('lamination', 'Checking...', 'pending');

  try {
    const res = await fetch(`/api/mes_query?sn=${encodeURIComponent(cleanSN)}`);
    if (res.ok) {
      const data = await res.json();
      if (data.status === 'ok' && (data.raw_found || data.tumsoldering || data.tumlayup || data.tumlamination)) {
        applyMESDataToUI(data);
        showToast('✅ Auto-extracted from FineReport!');
        return;
      } else if (data.status === 'offline_pc') {
        // Host PC is offline from factory LAN, attempt direct fetch via phone Wi-Fi
        if (badge) { badge.innerText = 'Connecting via Phone...'; badge.style.color = '#38bdf8'; }
        
        try {
          const directUrl = `${MES_ACCESS_URL}?preview=true&MOUDLEID=${encodeURIComponent(cleanSN)}&__bypassevent__=true&op=export&format=html&组件序列号=${encodeURIComponent(cleanSN)}&SN=${encodeURIComponent(cleanSN)}`;
          const dResp = await fetch(directUrl, { mode: 'cors' });
          if (dResp.ok) {
            const dHtml = await dResp.text();
            if (dHtml) {
              const resExt = await fetch('/api/extract_from_html', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json; charset=utf-8' },
                body: JSON.stringify({ content: dHtml, sn: cleanSN })
              });
              if (resExt.ok) {
                const extData = (await resExt.json()).data || {};
                if (extData.tumsoldering || extData.tumlayup || extData.tumlamination) {
                  applyMESDataToUI(extData);
                  if (badge) { badge.innerText = 'Auto-Extracted via Wi-Fi'; badge.style.color = '#10b981'; }
                  showToast('✅ Auto-extracted from FineReport via Phone Wi-Fi!');
                  return;
                }
              }
            }
          }
        } catch (phoneErr) {}

        // In-page viewer pre-authenticated fallback
        const container = document.getElementById('mes-iframe-container');
        if (container) {
          container.style.display = 'block';
          const toggleTxt = document.getElementById('mes-iframe-toggle-text');
          if (toggleTxt) toggleTxt.innerText = '✕ Hide In-Page Viewer';
          autoLoginFineReportOnPhone(cleanSN);
        }
        if (badge) { badge.innerText = 'In-Page MES Loaded'; badge.style.color = '#10b981'; }
        setHighlightBadge('soldering', 'Loaded In-Page Viewer', 'pending');
        setHighlightBadge('layup', 'Loaded In-Page Viewer', 'pending');
        setHighlightBadge('lamination', 'Loaded In-Page Viewer', 'pending');
        showToast('🖥️ Auto-loaded in In-Page Viewer below!');
        return;
      } else {
        // Check if in-flight query resolves within a few seconds
        const pollResult = await pollMESResultUntilFound(cleanSN, 3);
        if (pollResult && (pollResult.raw_found || pollResult.tumsoldering || pollResult.tumlayup || pollResult.tumlamination)) {
          applyMESDataToUI(pollResult);
          showToast('✅ Auto-extracted from FineReport!');
          return;
        }
        applyMESDataToUI(data);
        return;
      }
    }
    if (badge) { badge.innerText = 'Query Ready'; badge.style.color = '#38bdf8'; }
    setHighlightBadge('soldering', '-', 'blank');
    setHighlightBadge('layup', '-', 'blank');
    setHighlightBadge('lamination', '-', 'blank');
  } catch(e) {
    if (badge) { badge.innerText = 'Query Error'; badge.style.color = '#ef4444'; }
    setHighlightBadge('soldering', '-', 'blank');
    setHighlightBadge('layup', '-', 'blank');
    setHighlightBadge('lamination', '-', 'blank');
  }
}

function updateHighlightCard(key, value, extraText = "") {
  const card = document.getElementById(`mes-card-${key}`);
  const valEl = document.getElementById(`mes-val-${key}`);
  if (!valEl) return;

  if (value && value.trim()) {
    valEl.innerText = `PRESENT: ${value}`;
    valEl.className = 'mes-badge mes-badge-present';
    if (card) { card.classList.add('present'); card.classList.remove('blank'); }
  } else {
    valEl.innerText = 'BLANK (No record)';
    valEl.className = 'mes-badge mes-badge-blank';
    if (card) { card.classList.add('blank'); card.classList.remove('present'); }
  }
}

function setHighlightBadge(key, text, type) {
  const card = document.getElementById(`mes-card-${key}`);
  const valEl = document.getElementById(`mes-val-${key}`);
  if (valEl) {
    valEl.innerText = text;
    valEl.className = `mes-badge mes-badge-${type}`;
  }
  if (card) {
    card.classList.remove('present', 'blank');
  }
}

function openMESReportDirect() {
  const mesInput = document.getElementById('mes-sn-input');
  const sn = (mesInput ? mesInput.value.trim() : '') || currentMESSN || '';
  autoLoginFineReportOnPhone(sn);
  if (sn && sn !== 'Pending SN') {
    copyToClipboard(sn, 'Module SN');
    showToast(`🚀 Auto-Logging In (030888) & Opening MES Report for ${sn}...`);
    const directUrl = `${MES_ACCESS_URL}?preview=true&MOUDLEID=${encodeURIComponent(sn)}&__bypassevent__=true&组件序列号=${encodeURIComponent(sn)}&ModuleSerialNo=${encodeURIComponent(sn)}&SN=${encodeURIComponent(sn)}`;
    window.open(directUrl, '_blank');
  } else {
    showToast('🚀 Auto-Logging In (030888) & Opening MES Report...');
    window.open(`${MES_ACCESS_URL}?preview=true`, '_blank');
  }
}

function openMESLoginDirect() {
  copyToClipboard('030888', 'Login Credential (030888)');
  showToast('🔐 Copied 030888 to clipboard! Opening login page...');
  window.open(MES_LOGIN_URL, '_blank');
}

function copyToClipboard(text, label = 'Text') {
  if (!text) return;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      showToast(`📋 Copied ${label}: ${text}`);
    }).catch(() => {
      prompt(`Copy ${label}:`, text);
    });
  } else {
    prompt(`Copy ${label}:`, text);
  }
}

function copyCurrentMESSN() {
  const mesInput = document.getElementById('mes-sn-input');
  const sn = (mesInput ? mesInput.value.trim() : '') || currentMESSN || '';
  if (sn && sn !== 'Pending SN') {
    copyToClipboard(sn, 'Module SN');
  } else {
    showToast('No SN to copy yet', true);
  }
}

async function quickPasteMESText() {
  if (navigator.clipboard && navigator.clipboard.readText) {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        const sn = extractSNFromText(text) || text.trim().toUpperCase();
        if (sn) {
          showToast(`📋 Pasted: ${sn}`);
          setMESSerialNumber(sn, 'MES Paste');
        }
      }
    } catch(e) {
      showToast('Tap to paste directly into input', true);
    }
  }
}

function onMESSNInputChanged() {
  const mesInput = document.getElementById('mes-sn-input');
  if (!mesInput) return;
  const sn = extractSNFromText(mesInput.value) || mesInput.value.trim().toUpperCase();
  if (sn.startsWith('V01') && sn.length >= 10) {
    currentMESSN = sn;
    setMESSerialNumber(sn, 'MES Input');
  }
}

function triggerQueryMES() {
  const mesInput = document.getElementById('mes-sn-input');
  const sn = mesInput ? mesInput.value.trim() : '';
  queryMESProcessLog(sn);
}

function syncCurrentSNToMES() {
  // Intentionally no-op to maintain complete bi-directional tab isolation between MR and MES
}

function toggleMESIframe() {
  const container = document.getElementById('mes-iframe-container');
  const toggleTxt = document.getElementById('mes-iframe-toggle-text');
  if (!container) return;
  const isVisible = (container.style.display === 'block');
  if (isVisible) {
    container.style.display = 'none';
    if (toggleTxt) toggleTxt.innerText = '🖥️ In-Page Viewer';
  } else {
    container.style.display = 'block';
    if (toggleTxt) toggleTxt.innerText = '✕ Hide In-Page Viewer';
    loadMESIframe('report');
  }
}

function loadMESIframe(type) {
  const frame = document.getElementById('mes-frame');
  if (!frame) return;
  if (type === 'login') {
    frame.src = MES_LOGIN_URL;
  } else {
    frame.src = MES_REPORT_URL;
  }
}

function reloadMESIframe() {
  const frame = document.getElementById('mes-frame');
  if (frame) {
    frame.src = frame.src;
  }
}

// ================== HTML EXTRACTOR & TREND HELPERS ==================
function openPasteHTMLModal() {
  const modal = document.getElementById('html-paste-modal');
  if (modal) {
    modal.classList.add('active');
    const ta = document.getElementById('mes-html-paste-input');
    if (ta) setTimeout(() => ta.focus(), 150);
  }
}

function closePasteHTMLModal() {
  const modal = document.getElementById('html-paste-modal');
  if (modal) modal.classList.remove('active');
}

async function pasteClipboardToHTMLInput() {
  if (navigator.clipboard && navigator.clipboard.readText) {
    try {
      const text = await navigator.clipboard.readText();
      const ta = document.getElementById('mes-html-paste-input');
      if (ta && text) {
        ta.value = text;
        showToast('📋 Pasted text from clipboard');
        return;
      }
    } catch(e) {}
  }
  showToast('Please long-press and paste inside the box', true);
}

async function submitHTMLForExtraction() {
  const ta = document.getElementById('mes-html-paste-input');
  const content = ta ? ta.value.trim() : '';
  if (!content) {
    showToast('Please paste HTML or table text first', true);
    return;
  }

  showToast('⚡ Extracting machines & process data...');
  const mesInput = document.getElementById('mes-sn-input');
  const activeSn = (mesInput ? mesInput.value.trim() : '') || currentMESSN || '';
  try {
    const res = await fetch('/api/extract_from_html', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ content: content, sn: activeSn })
    });

    if (res.ok) {
      const jsonResp = await res.json();
      const data = jsonResp.data || {};
      
      if (data.sn) {
        const mesInput = document.getElementById('mes-sn-input');
        if (mesInput) mesInput.value = data.sn;
      }

      updateHighlightCard('soldering', data.tumsoldering);
      updateHighlightCard('layup', data.tumlayup, data.layup_time);
      updateHighlightCard('lamination', data.tumlamination);
      if (data.layup_time) setTxt('panel-layup', data.layup_time);

      const extraBox = document.getElementById('mes-extra-details');
      if (extraBox && (data.product_family || data.lot_no || data.mo_no || data.appearance_grade)) {
        extraBox.style.display = 'block';
        const setSpan = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = val || '-'; };
        setSpan('mes-extra-family', data.product_family);
        setSpan('mes-extra-lot', data.lot_no);
        setSpan('mes-extra-mo', data.mo_no);
        setSpan('mes-extra-grade', data.appearance_grade);
      }

      const badge = document.getElementById('mes-query-badge');
      if (badge) { badge.innerText = 'HTML Processed'; badge.style.color = '#10b981'; }

      if (jsonResp.trend) {
        renderMESTrendAnalytics(jsonResp.trend);
      } else {
        fetchMESTrendAnalytics();
      }

      closePasteHTMLModal();
      showToast('✅ Machine highlights extracted & trend logged');
    } else {
      showToast('❌ Extraction request failed', true);
    }
  } catch(err) {
    showToast('❌ Extraction connection error', true);
  }
}

async function fetchMESTrendAnalytics() {
  try {
    const res = await fetch('/api/mes_trend');
    if (res.ok) {
      const data = await res.json();
      renderMESTrendAnalytics(data);
    }
  } catch(e) {
    console.warn('Failed to fetch MES trend:', e);
  }
}

function renderMESTrendAnalytics(data) {
  if (!data) return;
  const countEl = document.getElementById('mes-trend-count');
  if (countEl) countEl.innerText = `(${data.total_logged || 0} logged)`;

  const renderBars = (containerId, summaryId, items, colorClass) => {
    const container = document.getElementById(containerId);
    const summary = document.getElementById(summaryId);
    if (!container) return;
    if (!items || items.length === 0) {
      container.innerHTML = '<div style="font-size: 10px; color: var(--text-muted); font-style: italic;">No records yet</div>';
      if (summary) summary.innerText = '-';
      return;
    }
    if (summary) summary.innerText = `${items.length} machine${items.length > 1 ? 's' : ''}`;
    container.innerHTML = items.slice(0, 5).map(item => `
      <div class="trend-bar-track">
        <div class="trend-bar-fill ${colorClass}" style="width: ${Math.max(item.pct, 8)}%;"></div>
        <div class="trend-bar-label">
          <span>${item.name}</span>
          <span>${item.count} (${item.pct}%)</span>
        </div>
      </div>
    `).join('');
  };

  renderBars('trend-soldering-bars', 'trend-soldering-summary', data.soldering_top, 'soldering');
  renderBars('trend-layup-bars', 'trend-layup-summary', data.layup_top, 'layup');
  renderBars('trend-lamination-bars', 'trend-lamination-summary', data.lamination_top, 'lamination');

  const tbody = document.getElementById('trend-recent-tbody');
  if (tbody && data.recent_records) {
    if (data.recent_records.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No records logged yet</td></tr>';
    } else {
      tbody.innerHTML = data.recent_records.slice(0, 15).map(r => `
        <tr>
          <td style="color: var(--text-muted); font-size: 9px;">${(r.timestamp || '').split(' ')[1] || r.timestamp}</td>
          <td style="font-weight: 700; color: #38bdf8;">${r.sn || '-'}</td>
          <td><span style="color: ${r.tumsoldering ? '#f59e0b' : '#64748b'}; font-weight: 600;">${r.tumsoldering || '-'}</span></td>
          <td><span style="color: ${r.tumlayup ? '#10b981' : '#64748b'}; font-weight: 600;">${r.tumlayup || '-'}</span></td>
          <td><span style="color: ${r.tumlamination ? '#c084fc' : '#64748b'}; font-weight: 600;">${r.tumlamination || '-'}</span></td>
        </tr>
      `).join('');
    }
  }
}

function exportMESTrendCSV() {
  window.open('/api/export_mes_trend_csv', '_blank');
}

// ================== MES CHINESE ⇄ ENGLISH DICTIONARY & TRANSLATOR ==================
let currentDictCategory = 'all';

function openMESTranslationModal() {
  const modal = document.getElementById('mes-translation-modal');
  if (modal) {
    modal.classList.add('active');
    renderMESDictionaryList();
    const input = document.getElementById('mes-dict-search-input');
    if (input) setTimeout(() => input.focus(), 150);
  }
}

function closeMESTranslationModal() {
  const modal = document.getElementById('mes-translation-modal');
  if (modal) modal.classList.remove('active');
}

function translateMESTextClient(text) {
  if (!text || typeof text !== 'string') return '';
  let res = text;
  const dict = Array.isArray(MES_CHINESE_DICT) ? MES_CHINESE_DICT : [];
  const sorted = [...dict].sort((a, b) => (b.cn ? b.cn.length : 0) - (a.cn ? a.cn.length : 0));
  for (const item of sorted) {
    if (item.cn && res.includes(item.cn)) {
      res = res.split(item.cn).join(item.en);
    }
  }
  return res;
}

function onMESTranslateInputChanged() {
  const input = document.getElementById('mes-trans-live-input');
  const resBox = document.getElementById('mes-trans-live-result');
  const resText = document.getElementById('mes-trans-live-text');
  if (!input || !resBox || !resText) return;
  const val = input.value.trim();
  if (!val) {
    resBox.style.display = 'none';
    return;
  }
  const translated = translateMESTextClient(val);
  resText.innerText = translated || val;
  resBox.style.display = 'block';
}

async function pasteToMESTranslator() {
  if (navigator.clipboard && navigator.clipboard.readText) {
    try {
      const text = await navigator.clipboard.readText();
      const input = document.getElementById('mes-trans-live-input');
      if (input && text) {
        input.value = text;
        onMESTranslateInputChanged();
        showToast('📋 Pasted text for translation');
        return;
      }
    } catch(e) {}
  }
  showToast('Please type or long-press paste', true);
}

function filterMESCategory(cat, el) {
  currentDictCategory = cat;
  const pills = document.querySelectorAll('.dict-pill');
  pills.forEach(p => p.classList.remove('active'));
  if (el) el.classList.add('active');
  renderMESDictionaryList();
}

function filterMESDictionary() {
  renderMESDictionaryList();
}

function clearMESDictFilter() {
  const input = document.getElementById('mes-dict-search-input');
  if (input) input.value = '';
  filterMESCategory('all', document.querySelector('.dict-pill'));
}

function renderMESDictionaryList() {
  const container = document.getElementById('mes-dict-list-container');
  if (!container) return;
  const searchInput = document.getElementById('mes-dict-search-input');
  const q = (searchInput ? searchInput.value.trim().toLowerCase() : '');

  const dict = Array.isArray(MES_CHINESE_DICT) ? MES_CHINESE_DICT : [];
  const filtered = dict.filter(item => {
    if (currentDictCategory !== 'all') {
      const cat = (item.cat || '').toLowerCase();
      if (!cat.includes(currentDictCategory.toLowerCase())) return false;
    }
    if (q) {
      const haystack = `${item.cn} ${item.en} ${item.cat} ${item.equipment} ${item.desc}`.toLowerCase();
      return haystack.includes(q);
    }
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = '<div style="font-size: 11px; color: var(--text-muted); text-align: center; padding: 15px;">No matching terms found.</div>';
    return;
  }

  container.innerHTML = filtered.map(item => `
    <div class="dict-card-item" onclick="copyToClipboard('${item.cn} (${item.en})', 'Translation')">
      <div class="dict-card-header">
        <span class="dict-card-cn">${item.cn}</span>
        <span class="pill" style="font-size: 8px; padding: 2px 6px; background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);">${item.cat || 'General'}</span>
      </div>
      <div class="dict-card-en">${item.en}</div>
      ${item.equipment && item.equipment !== '-' ? `<div style="font-size: 10px; color: #fbbf24; margin-top: 2px;"><strong>Equipment:</strong> <code>${item.equipment}</code></div>` : ''}
      <div class="dict-card-desc">${item.desc || ''}</div>
    </div>
  `).join('');
}

// Init
renderClasses();
renderSummaries();
updateSelectedDisplay();
setInterval(fetchDashboardStatus, 2000);
fetchMESTrendAnalytics();
</script>
</body>
</html>
"""

def render_mobile_hud_html():
    cfg_layout = getattr(config, 'MOBILE_LAYOUT_SETTINGS', {})
    html = MOBILE_HUD_HTML.replace('{{DEFECT_TREE_JSON}}', json.dumps(config.DEFECT_TREE))
    html = html.replace('{{MES_CHINESE_DICT_JSON}}', json.dumps(MES_CHINESE_DICTIONARY, ensure_ascii=False))
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

        if path in ('/js/jsqr.min.js', '/jsqr.min.js'):
            js_path = os.path.join(os.path.dirname(__file__), 'jsqr.min.js')
            if not os.path.exists(js_path):
                js_path = os.path.join(config.LOCAL_DATA_DIR, 'jsqr.min.js')
            if os.path.exists(js_path):
                with open(js_path, 'rb') as f:
                    js_bytes = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(js_bytes)
                return

        if path in ('/js/zxing.min.js', '/zxing.min.js'):
            js_path = os.path.join(os.path.dirname(__file__), 'zxing.min.js')
            if not os.path.exists(js_path):
                js_path = os.path.join(config.LOCAL_DATA_DIR, 'zxing.min.js')
            if os.path.exists(js_path):
                with open(js_path, 'rb') as f:
                    js_bytes = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(js_bytes)
                return

        if path == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(LIVE_HUD_STATE).encode('utf-8'))
            return

        if path == '/api/mes_scan_sn' or path.startswith('/api/mes_scan_sn?'):
            params = urllib.parse.parse_qs(parsed.query)
            sn = params.get('sn', [''])[0].strip()
            source = params.get('source', ['Mobile Scanner'])[0].strip()
            clean_sn = clean_and_validate_sn(sn) or normalize_v01_candidate(sn) or (sn.strip().upper() if sn else "")
            if clean_sn:
                query_res = query_mes_process_log(clean_sn, record_to_trend=True)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(query_res).encode('utf-8'))
                return
            else:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Invalid SN"}).encode('utf-8'))
                return

        if path == '/api/mes_query':
            params = urllib.parse.parse_qs(parsed.query)
            sn = params.get('sn', [''])[0].strip()
            result = query_mes_process_log(sn)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode('utf-8'))
            return

        if path == '/api/mes_trend':
            analytics = get_mes_trend_analytics()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(analytics).encode('utf-8'))
            return

        if path == '/api/export_mes_trend_csv':
            csv_data = export_mes_trend_csv_string()
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="MES_Process_Trend_Log.csv"')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(csv_data.encode('utf-8'))
            return

        if path == '/api/mes_dictionary':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(MES_CHINESE_DICTIONARY, ensure_ascii=False).encode('utf-8'))
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

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
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
                client_sn_raw = params.get('client_sn', [''])[0].strip()
                client_sn = clean_and_validate_sn(client_sn_raw)
                ts_str = params.get('timestamp', [None])[0]
                file_dt = datetime.fromtimestamp(float(ts_str)) if ts_str else datetime.now()
                target_tab = params.get('target_tab', [''])[0].lower()

                # Strict Tab Isolation Guard: Never send MES scans to ModuleReviewTab
                if target_tab == 'mes' or photo_hint == 'MES_PHOTO':
                    length = int(self.headers.get('Content-Length', 0))
                    saved_path = ""
                    found_sn = client_sn

                    if length > 0:
                        img_bytes = self.rfile.read(length)
                        ts_tag = int(time.time() * 1000)
                        raw_fname = f"MES_Snap_{ts_tag}.jpg"
                        tmp_save_path = os.path.join(LOCAL_UPLOADS_DIR, raw_fname)
                        with open(tmp_save_path, 'wb') as f:
                            f.write(img_bytes)

                        # Normalize EXIF orientation on save
                        try:
                            from PIL import Image as PIL_Img, ImageOps as PIL_Ops
                            with PIL_Img.open(tmp_save_path) as p_img:
                                transposed = PIL_Ops.exif_transpose(p_img)
                                if transposed is not None:
                                    transposed.save(tmp_save_path, quality=95)
                        except Exception: pass

                        # If client_sn wasn't provided, try barcode/OCR extraction
                        if not found_sn:
                            found_sn = extract_sn_with_ocr(tmp_save_path)

                        # Save into MES_PHOTOS_DIR and mirror to DailyCache/YYYY-MM-DD/mes_photos
                        if found_sn:
                            saved_path = rename_to_sn_pattern(tmp_save_path, "MES_SN", found_sn, MES_PHOTOS_DIR)
                            daily_mes_dir = os.path.join(LOCAL_CACHE_DIR, "mes_photos")
                            os.makedirs(daily_mes_dir, exist_ok=True)
                            try:
                                shutil.copy2(saved_path, os.path.join(daily_mes_dir, os.path.basename(saved_path)))
                            except Exception: pass
                        else:
                            dest = os.path.join(MES_PHOTOS_DIR, raw_fname)
                            try:
                                shutil.move(tmp_save_path, dest)
                                saved_path = dest
                            except Exception:
                                saved_path = tmp_save_path

                        mark_photo_processed(saved_path, os.path.basename(saved_path))
                        print(f"[MES PHOTO SAVED]: Saved MES photo to '{saved_path}', SN='{found_sn}'")

                    query_res = {}
                    if found_sn:
                        existing = get_mes_trend_entry_by_sn(found_sn)
                        if existing:
                            existing["photo_path"] = saved_path
                            save_mes_trend_entry(existing)
                        else:
                            initial_entry = {
                                "sn": found_sn,
                                "tumsoldering": "",
                                "tumlayup": "",
                                "tumlamination": "",
                                "layup_time": "",
                                "defect": "MES Barcode Photo" if length > 0 else "Mobile MES Sync",
                                "result": "Pending MES",
                                "photo_path": saved_path
                            }
                            save_mes_trend_entry(initial_entry)
                        query_res = query_mes_process_log(found_sn, record_to_trend=True)

                    resp_data = {
                        'status': 'ok',
                        'action': 'MES_PHOTO',
                        'sn': found_sn or '',
                        'photo_path': saved_path,
                        'tumsoldering': query_res.get('tumsoldering', ''),
                        'tumlayup': query_res.get('tumlayup', ''),
                        'tumlamination': query_res.get('tumlamination', ''),
                        'layup_time': query_res.get('layup_time', ''),
                        'product_family': query_res.get('product_family', ''),
                        'lot_no': query_res.get('lot_no', ''),
                        'mo_no': query_res.get('mo_no', ''),
                        'appearance_grade': query_res.get('appearance_grade', ''),
                        'raw_found': query_res.get('raw_found', False)
                    }
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps(resp_data).encode('utf-8'))
                    return

                length = int(self.headers.get('Content-Length', 0))
                if length == 0:
                    if client_sn:
                        # Direct SN sync from Mobile Hub without image file
                        print(f"[MOBILE SN SYNC]: Received valid client_sn '{client_sn}'")
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
                        print(f"[MOBILE SN SYNC REJECTED]: Rejected non-V01 barcode '{client_sn_raw}'")
                        resp_data = {'status': 'rejected', 'reason': 'Invalid barcode. Must begin with V01.', 'sn': ''}
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps(resp_data).encode('utf-8'))
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
                print(f"[MOBILE CAMERA SNAP]: Received {raw_fname} ({len(img_bytes)} bytes) Mode: {photo_hint} ClientSN: '{client_sn}' (Raw: '{client_sn_raw}')")

                # Barcode / SN detection (Run ONLY for SN_PHOTO; skip completely for DEFECT_PHOTO)
                found_sn = ""
                action = "DEFECT_PHOTO"

                if photo_hint == "SN_PHOTO":
                    action = "SN_PHOTO"
                    if client_sn:
                        found_sn = client_sn
                    if not found_sn:
                        found_sn = extract_sn_with_ocr(save_path)
                    print(f"[SN PHOTO PROCESSED]: Extracted V01 SN -> '{found_sn}'")

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
                
                raw_sn = data.get('sn', '').strip()
                def_sn = clean_and_validate_sn(raw_sn) or raw_sn
                def_class = data.get('class', '')
                def_summary = data.get('summary', '')
                if not def_class and def_summary and hasattr(config, 'get_class_for_summary'):
                    def_class = config.get_class_for_summary(def_summary)
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

        if self.path.startswith('/api/mes_scan_sn'):
            try:
                length = int(self.headers.get('Content-Length', 0))
                sn = ""
                source = "Mobile Scan"
                if length > 0:
                    body = self.rfile.read(length).decode('utf-8', errors='ignore')
                    try:
                        data = json.loads(body)
                        sn = data.get('sn', '')
                        source = data.get('source', source)
                    except Exception:
                        sn = body.strip()
                if not sn:
                    parsed_url = urllib.parse.urlparse(self.path)
                    params = urllib.parse.parse_qs(parsed_url.query)
                    sn = params.get('sn', [''])[0].strip()
                    source = params.get('source', [source])[0].strip()

                clean_sn = clean_and_validate_sn(sn) or normalize_v01_candidate(sn) or (sn.strip().upper() if sn else "")
                if clean_sn:
                    initial_entry = {
                        "sn": clean_sn,
                        "tumsoldering": "",
                        "tumlayup": "",
                        "tumlamination": "",
                        "layup_time": "",
                        "defect": f"Scanned via {source}",
                        "result": "Pending MES"
                    }
                    save_mes_trend_entry(initial_entry)
                    query_res = query_mes_process_log(clean_sn)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps(query_res).encode('utf-8'))
                    return
                else:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": "Invalid SN"}).encode('utf-8'))
                    return
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                return

        if self.path.startswith('/api/extract_sn_from_image'):
            try:
                length = int(self.headers.get('Content-Length', 0))
                img_bytes = self.rfile.read(length)
                tmp_fname = f"mes_snap_{int(time.time() * 1000)}.jpg"
                tmp_path = os.path.join(MES_PHOTOS_DIR, tmp_fname)
                with open(tmp_path, 'wb') as f:
                    f.write(img_bytes)

                # Normalize EXIF
                try:
                    from PIL import Image as PIL_Img, ImageOps as PIL_Ops
                    with PIL_Img.open(tmp_path) as p_img:
                        transposed = PIL_Ops.exif_transpose(p_img)
                        if transposed is not None:
                            transposed.save(tmp_path, quality=95)
                except Exception: pass

                # 1. Barcode / QR detection
                found_sn = extract_sn_with_ocr(tmp_path)
                
                # 2. EasyOCR text detection on full image for MES screen photos
                all_text = ""
                reader = get_easyocr_reader()
                if reader:
                    try:
                        lines = reader.readtext(tmp_path, detail=0)
                        all_text = " ".join(lines)
                        if not found_sn:
                            for l in lines:
                                norm = normalize_v01_candidate(l)
                                if norm:
                                    found_sn = norm
                                    break
                                cl = clean_and_validate_sn(l)
                                if cl:
                                    found_sn = cl
                                    break
                    except Exception as o_err:
                        print(f"[OCR MES DETECT ERROR]: {o_err}")

                # 3. Extract machines & process data if photo is of MES screen
                parsed_mes = extract_info_from_mes_html(all_text, fallback_sn=found_sn)
                final_sn = parsed_mes.get('sn') or found_sn

                # 4. If photo was of module barcode (no machines in image text), automatically query FineReport MES portal!
                if final_sn and (not parsed_mes.get('tumsoldering') and not parsed_mes.get('tumlayup')):
                    print(f"[EXTRACT SN OCR]: Barcode detected for {final_sn}. Automatically querying FineReport MES platform...")
                    try:
                        auto_res = query_mes_process_log(final_sn, record_to_trend=True)
                        if auto_res and auto_res.get('status') == 'ok':
                            for k in ['tumsoldering', 'tumlayup', 'tumlamination', 'layup_time', 'product_family', 'lot_no', 'mo_no', 'appearance_grade', 'defect', 'result']:
                                if auto_res.get(k):
                                    parsed_mes[k] = auto_res[k]
                            print(f"[AUTO MES LOGGED]: Extracted from FineReport -> Stringer='{parsed_mes.get('tumsoldering')}', Layup='{parsed_mes.get('tumlayup')}', Lam='{parsed_mes.get('tumlamination')}', LayupTime='{parsed_mes.get('layup_time')}'")
                    except Exception as qe:
                        print(f"[AUTO MES QUERY ERROR]: {qe}")

                saved_path = tmp_path
                if final_sn:
                    saved_path = rename_to_sn_pattern(tmp_path, "MES_SN", final_sn, MES_PHOTOS_DIR)
                    daily_mes_dir = os.path.join(LOCAL_CACHE_DIR, "mes_photos")
                    os.makedirs(daily_mes_dir, exist_ok=True)
                    try:
                        shutil.copy2(saved_path, os.path.join(daily_mes_dir, os.path.basename(saved_path)))
                    except Exception: pass
                    mark_photo_processed(saved_path, os.path.basename(saved_path))
                    parsed_mes['sn'] = final_sn
                    parsed_mes['photo_path'] = saved_path
                    save_mes_trend_entry(parsed_mes)

                print(f"[EXTRACT SN/MES OCR]: Extracted from {tmp_fname} -> SN='{final_sn}', Soldering='{parsed_mes.get('tumsoldering')}', Layup='{parsed_mes.get('tumlayup')}', Lam='{parsed_mes.get('tumlamination')}', SavedTo='{saved_path}'")

                resp_data = {
                    'status': 'ok',
                    'sn': final_sn or '',
                    'photo_path': saved_path,
                    'tumsoldering': parsed_mes.get('tumsoldering', ''),
                    'tumlayup': parsed_mes.get('tumlayup', ''),
                    'tumlamination': parsed_mes.get('tumlamination', ''),
                    'layup_time': parsed_mes.get('layup_time', ''),
                    'product_family': parsed_mes.get('product_family', ''),
                    'lot_no': parsed_mes.get('lot_no', ''),
                    'mo_no': parsed_mes.get('mo_no', ''),
                    'appearance_grade': parsed_mes.get('appearance_grade', ''),
                    'raw_found': parsed_mes.get('raw_found', False) or bool(parsed_mes.get('tumsoldering') or parsed_mes.get('tumlayup'))
                }

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(resp_data).encode('utf-8'))
                return
            except Exception as e:
                print(f"[EXTRACT SN OCR ERROR]: {e}")
                self.send_response(500)
                self.end_headers()
                return

        if self.path.startswith('/api/mes_query'):
            try:
                length = int(self.headers.get('Content-Length', 0))
                sn = ""
                if length > 0:
                    body = self.rfile.read(length).decode('utf-8', errors='ignore')
                    try:
                        data = json.loads(body)
                        sn = data.get('sn', '')
                    except Exception:
                        sn = body.strip()
                if not sn:
                    parsed_url = urllib.parse.urlparse(self.path)
                    params = urllib.parse.parse_qs(parsed_url.query)
                    sn = params.get('sn', [''])[0].strip()

                result = query_mes_process_log(sn)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode('utf-8'))
                return
            except Exception as e:
                print(f"[MES POST QUERY ERROR]: {e}")
                self.send_response(500)
                self.end_headers()
                return

        if self.path.startswith('/api/extract_from_html'):
            try:
                length = int(self.headers.get('Content-Length', 0))
                raw_html = ""
                sn_hint = ""
                if length > 0:
                    body = self.rfile.read(length).decode('utf-8', errors='ignore')
                    raw_html = body
                    try:
                        data = json.loads(body)
                        if isinstance(data, dict):
                            raw_html = data.get('content') or data.get('html', '')
                            sn_hint = data.get('sn', '')
                    except Exception:
                        pass

                parsed_data = extract_info_from_mes_html(raw_html, fallback_sn=sn_hint)
                trend_data = get_mes_trend_analytics()
                resp = {"status": "ok", "data": parsed_data, "trend": trend_data}
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode('utf-8'))
                return
            except Exception as e:
                print(f"[EXTRACT HTML ERROR]: {e}")
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


def start_phone_server(callback_fn, defect_callback=None, mes_callback=None):
    global GLOBAL_APP_CALLBACK, GLOBAL_MES_CALLBACK
    GLOBAL_APP_CALLBACK = callback_fn
    if mes_callback is not None:
        GLOBAL_MES_CALLBACK = mes_callback
    ensure_defect_sample_folders()
    scan_and_train_from_sample_folders()
    active_path = start_smart_today_copier(callback_fn)
    start_mac_mini_relay_client(callback_fn)
    
    # Start Mobile Live Web HUD (Dual HTTP :8080 and HTTPS :8443)
    hud_port = getattr(config, 'MOBILE_HUD_PORT', 8080)
    hud_url = start_mobile_hud_server(hud_port, 8443)
    update_live_hud_state(defect_callback=defect_callback, mes_callback=mes_callback)

    cam_dirs, rec_dirs = find_phone_directories()
    phone_link_status = "Phone Link: Connected" if cam_dirs else "Phone Link: Watching"
    relay_status = "Mac Relay: Enabled" if getattr(config, 'MAC_MINI_RELAY_ENABLED', False) else "Mac Relay: Ready"
    
    https_note = f"\n🔒 Live QR Scanner (HTTPS): {GLOBAL_HUD_HTTPS_URL}" if GLOBAL_HUD_HTTPS_URL else ""
    return f"📱 Mobile HUD: {hud_url}{https_note}\n{phone_link_status} | {relay_status}"