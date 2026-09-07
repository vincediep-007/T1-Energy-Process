# =================== CONFIGURATION FILE ===================
import os
import json

# Define the root local data directory right inside the app folder
LOCAL_DATA_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(LOCAL_DATA_DIR, exist_ok=True)

# Define dependent paths safely
DAILY_CACHE_DIR = os.path.join(LOCAL_DATA_DIR, "DailyCache")
VOICE_SAMPLES_DIR = os.path.join(LOCAL_DATA_DIR, "VoiceSamples")
MES_PHOTOS_DIR = os.path.join(LOCAL_DATA_DIR, "mes_photos")
os.makedirs(DAILY_CACHE_DIR, exist_ok=True)
os.makedirs(VOICE_SAMPLES_DIR, exist_ok=True)
os.makedirs(MES_PHOTOS_DIR, exist_ok=True)

# Window & Theme Settings
WINDOW_TITLE = "AOI & EL Dashboard - Production Suite v18.6"
WINDOW_SIZE = "1400x850"
LEFT_PANEL_WIDTH = 260
THUMBNAIL_CACHE_SIZE = 128
NETWORK_TIMEOUT = 3.0

COLOR_BG_MAIN = "#f8fafc"
COLOR_BG_SIDEBAR = "#ffffff"
COLOR_PRIMARY = "#1a5b82"
COLOR_PRIMARY_HOVER = "#154c6d"
COLOR_SECONDARY_BTN = "#e2e8f0"
COLOR_SECONDARY_TEXT = "#334155"
COLOR_TEXT_MAIN = "#0f172a"
COLOR_TEXT_SECONDARY = "#64748b"
COLOR_INPUT_BG = "#ffffff"
COLOR_DIVIDER = "#cbd5e1"
COLOR_CARD_BG = "#ffffff"
COLOR_CARD_BORDER = "#e2e8f0"

COLOR_STATUS_OK = "#16a34a"
COLOR_STATUS_NG = "#dc2626"
COLOR_STATUS_WARNING = "#ca8a04"

FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_SUBTITLE = ("Segoe UI", 12, "bold")
FONT_BODY = ("Segoe UI", 10)
FONT_BODY_BOLD = ("Segoe UI", 10, "bold")
FONT_SMALL = ("Segoe UI", 9)

# Pre-EL Station Prefix & Range Settings
PRE_EL_STATION_PREFIX = "TUMCQEL"
PRE_EL_STATION_MIN = 1001
PRE_EL_STATION_MAX = 1014

# Image Categories, Status & Search Constants
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')
CATEGORY_FRONT = "exteriorPicFront"
CATEGORY_BACK = "exteriorPicBack"
CATEGORY_EL = "EL"
STATUS_NG = "NG"
STATUS_OK = "OK"
TIME_GROUP_WINDOW = 2 * 60
BLACK_PIXEL_THRESHOLD = 50
THUMBNAIL_SIZE = (280, 140)
HISTORY_MAX_ITEMS = 100

# Backwards Compatibility Aliases
STATION_PREFIX = PRE_EL_STATION_PREFIX
STATION_MIN = PRE_EL_STATION_MIN
STATION_MAX = PRE_EL_STATION_MAX


# Final EL Station Settings
FINAL_EL_STATION_PREFIX = "TUMZJEL"
FINAL_EL_STATION_MIN = 1001
FINAL_EL_STATION_MAX = 1007

FINAL_EL_MAP = {
    "TUMZJEL1001": r"\\10.200.104.1\elpic\TUM\TUMEL1001",
    "TUMZJEL1002": r"\\10.200.104.3\elpic\TUM\TUMEL1002",
    "TUMZJEL1003": r"\\10.200.104.4\elpic\TUM\TUMEL1003",
    "TUMZJEL1004": r"\\10.200.104.5\elpic\TUM\TUMEL1004",
    "TUMZJEL1005": r"\\10.200.118.6\elpic\TUM\TUMEL1005",
    "TUMZJEL1006": r"\\10.200.118.7\elpic\TUM\TUMEL1006",
    "TUMZJEL1007": r"\\10.200.118.9\elpic\TUM\TUMEL1007"
}

PRE_EL_NETWORK_ROOT = r"\\10.200.4.19\filesystem\PREELPIC\MV01"
NETWORK_ROOT = PRE_EL_NETWORK_ROOT

ACTIVE_LINES = {
    "TUMZJEL1001": True,
    "TUMZJEL1002": True,
    "TUMZJEL1003": False,
    "TUMZJEL1004": True,
    "TUMZJEL1005": True,
    "TUMZJEL1006": True,
    "TUMZJEL1007": True
}

DEFAULT_PRE_FINAL_DAYS_BACK_START = 4
MAX_IMAGES_PER_SN = 0  # 0 = Unlimited images per SN to capture all station passes
TIME_INTERVAL_OPTIONS = ["1 Hour", "2 Hours", "4 Hours", "All Shift"]
DEFAULT_TIME_INTERVAL = "2 Hours"
CHART_ZOOM_OPTIONS = ["70%", "80%", "90%", "100%", "110%", "120%"]
CHART_ZOOM_LEVEL = "100%"
MIN_NG_BLACK_PERCENT = 30.0

# Full Comprehensive Factory Defect Tree Mapping
DEFECT_TREE = {
    "Backsheet Defect 背板不良": ["Backsheet Defect", "Backsheet indentation", "Backsheet joint"],
    "Bubble Defect 气泡不良": ["Bubble", "No melt"],
    "Cells Defect 电池片不良": ["Cell Defect", "Crack Cells", "Cell color difference"],
    "EL Defect EL不良": ["EL Defect", "EL broken grid", "EL uneven brightness", "EL shorted cell", "EL cold solder", "EL shaped microcrack"],
    "Equipment Scrap 设备报废": ["Equipment Scrap", "Busbar machine Scrap", "Conveyer line scrap", "Edge Trimming machine Scrap", "Fixture machine scrap", "Frame installation machine scrap", "Junction box machine scrap", "Laminator machine scrap", "Power outage Scrap", "Stringing machine scrap"],
    "Foreign material Defect 异物不良": ["Foreign material", "Cell fragments", "Desiccant", "Dirty in the module", "EVA label", "EVA seal strip", "Extra Busbar", "Extra ribbon", "Flux crystal", "Glass fragments", "Glass paper", "Insect", "Masking tape", "Paper object", "Positioning tape", "Small label", "Solding balls", "Teflon strip", "sawdust"],
    "Glass Defect 玻璃不良": ["Glass Defect", "Glass reversed", "Glass scratches", "Glass raw material", "Glass Missing", "Glass offset"],
    "Missalignment Defect 间距不良": ["间距不良 Cell Gap Defect", "String gap Defect", "Cell to Busbar Gap Defect", "Creepage by long ribbons", "Poor creepage distance", "Cells gap defect"],
    "Others Defects 其它": ["Others Defects", "Tin exposure on busbar", "Static pattern", "Ribbon Not Cut", "Defect Label", "label offset"],
    "Production Scrap 生产报废": ["Production caused Scrap", "Rework causing Scrapped", "Warehousing scrap", "Turnover scrap"],
    "Short Circuit Scrap 短路报废": ["Shorted cell scrap", "Cell overlap scrap", "Ribbon overlap scrap", "Busbar misalignment or missing", "Two cell scrap"],
    "Solder Defect 焊接不良": ["Solder Defect", "Ribbon offset", "No ribbon", "Busbar Offset"]
}

def get_class_for_summary(summary: str) -> str:
    """Finds the parent classification for a given defect summary."""
    if not summary: return ""
    s_clean = summary.strip().lower()
    for cls_name, items in DEFECT_TREE.items():
        if s_clean in [it.lower() for it in items] or s_clean in cls_name.lower():
            return cls_name
    return ""

# Phone Link, Mobile HUD & Mac Mini Relay Settings
PHONE_CAMERA_DIR = ""
PHONE_RECORDINGS_DIR = ""
MASTER_REPORT_PATH = ""
MOBILE_HUD_PORT = 8080
MAC_MINI_RELAY_URL = ""
MAC_MINI_RELAY_ENABLED = False
MAC_MINI_RELAY_SECRET = "qc_secret_2026"

MOBILE_LAYOUT_SETTINGS = {
    "status_padding": "7px",
    "status_sn_font": "13px",
    "col_class_pct": "44%",
    "col_summary_pct": "56%",
    "grid_btn_padding": "11px",
    "grid_btn_font": "12px",
    "action_btn_height": "52px",
    "action_btn_font": "16px",
    "cam_btn_height": "52px",
    "cam_title_font": "13px",
    "element_gap": "8px",
    "border_radius": "10px"
}

REVIEW_TABLE_COL_WIDTHS = {
    "date": 100,
    "sn": 175,
    "summary": 160,
    "grade": 80,
    "pre_el": 210,
    "mr_pic": 125,
    "layup_time": 155,
    "station": 110,
    "shift": 105,
    "line": 85
}

SETTINGS_FILE = os.path.join(LOCAL_DATA_DIR, "persistent_settings.json")
HISTORY_FILE = os.path.join(LOCAL_DATA_DIR, "history_records.json")

def save_persistent_settings():
    try:
        data = {
            "DEFECT_TREE": DEFECT_TREE,
            "ACTIVE_LINES": ACTIVE_LINES,
            "DEFAULT_TIME_INTERVAL": DEFAULT_TIME_INTERVAL,
            "CHART_ZOOM_LEVEL": CHART_ZOOM_LEVEL,
            "DEFAULT_PRE_FINAL_DAYS_BACK_START": DEFAULT_PRE_FINAL_DAYS_BACK_START,
            "PRE_EL_NETWORK_ROOT": PRE_EL_NETWORK_ROOT,
            "FINAL_EL_MAP": FINAL_EL_MAP,
            "PRE_EL_STATION_PREFIX": PRE_EL_STATION_PREFIX,
            "PRE_EL_STATION_MIN": PRE_EL_STATION_MIN,
            "PRE_EL_STATION_MAX": PRE_EL_STATION_MAX,
            "MIN_NG_BLACK_PERCENT": MIN_NG_BLACK_PERCENT,
            "PHONE_CAMERA_DIR": PHONE_CAMERA_DIR,
            "PHONE_RECORDINGS_DIR": PHONE_RECORDINGS_DIR,
            "MASTER_REPORT_PATH": MASTER_REPORT_PATH,
            "MOBILE_HUD_PORT": MOBILE_HUD_PORT,
            "MAC_MINI_RELAY_URL": MAC_MINI_RELAY_URL,
            "MAC_MINI_RELAY_ENABLED": MAC_MINI_RELAY_ENABLED,
            "MAC_MINI_RELAY_SECRET": MAC_MINI_RELAY_SECRET,
            "MOBILE_LAYOUT_SETTINGS": MOBILE_LAYOUT_SETTINGS,
            "REVIEW_TABLE_COL_WIDTHS": REVIEW_TABLE_COL_WIDTHS
        }
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def load_persistent_settings():
    global DEFECT_TREE, ACTIVE_LINES, DEFAULT_TIME_INTERVAL, CHART_ZOOM_LEVEL
    global DEFAULT_PRE_FINAL_DAYS_BACK_START, PRE_EL_NETWORK_ROOT, FINAL_EL_MAP
    global PRE_EL_STATION_PREFIX, PRE_EL_STATION_MIN, PRE_EL_STATION_MAX, MIN_NG_BLACK_PERCENT
    global PHONE_CAMERA_DIR, PHONE_RECORDINGS_DIR, MASTER_REPORT_PATH, MOBILE_HUD_PORT
    global MAC_MINI_RELAY_URL, MAC_MINI_RELAY_ENABLED, MAC_MINI_RELAY_SECRET, MOBILE_LAYOUT_SETTINGS
    global REVIEW_TABLE_COL_WIDTHS
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "DEFECT_TREE" in data: DEFECT_TREE = data["DEFECT_TREE"]
                if "ACTIVE_LINES" in data: ACTIVE_LINES = data["ACTIVE_LINES"]
                if "DEFAULT_TIME_INTERVAL" in data: DEFAULT_TIME_INTERVAL = data["DEFAULT_TIME_INTERVAL"]
                if "CHART_ZOOM_LEVEL" in data: CHART_ZOOM_LEVEL = data["CHART_ZOOM_LEVEL"]
                if "DEFAULT_PRE_FINAL_DAYS_BACK_START" in data: DEFAULT_PRE_FINAL_DAYS_BACK_START = data["DEFAULT_PRE_FINAL_DAYS_BACK_START"]
                if "PRE_EL_NETWORK_ROOT" in data: PRE_EL_NETWORK_ROOT = data["PRE_EL_NETWORK_ROOT"]
                if "FINAL_EL_MAP" in data: FINAL_EL_MAP = data["FINAL_EL_MAP"]
                if "PRE_EL_STATION_PREFIX" in data: PRE_EL_STATION_PREFIX = data["PRE_EL_STATION_PREFIX"]
                if "PRE_EL_STATION_MIN" in data: PRE_EL_STATION_MIN = data["PRE_EL_STATION_MIN"]
                if "PRE_EL_STATION_MAX" in data: PRE_EL_STATION_MAX = data["PRE_EL_STATION_MAX"]
                if "MIN_NG_BLACK_PERCENT" in data: MIN_NG_BLACK_PERCENT = data["MIN_NG_BLACK_PERCENT"]
                if "PHONE_CAMERA_DIR" in data: PHONE_CAMERA_DIR = data["PHONE_CAMERA_DIR"]
                if "PHONE_RECORDINGS_DIR" in data: PHONE_RECORDINGS_DIR = data["PHONE_RECORDINGS_DIR"]
                if "MASTER_REPORT_PATH" in data: MASTER_REPORT_PATH = data["MASTER_REPORT_PATH"]
                if "MOBILE_HUD_PORT" in data: MOBILE_HUD_PORT = data["MOBILE_HUD_PORT"]
                if "MAC_MINI_RELAY_URL" in data: MAC_MINI_RELAY_URL = data["MAC_MINI_RELAY_URL"]
                if "MAC_MINI_RELAY_ENABLED" in data: MAC_MINI_RELAY_ENABLED = data["MAC_MINI_RELAY_ENABLED"]
                if "MAC_MINI_RELAY_SECRET" in data: MAC_MINI_RELAY_SECRET = data["MAC_MINI_RELAY_SECRET"]
                if "MOBILE_LAYOUT_SETTINGS" in data and isinstance(data["MOBILE_LAYOUT_SETTINGS"], dict):
                    MOBILE_LAYOUT_SETTINGS.update(data["MOBILE_LAYOUT_SETTINGS"])
                if "REVIEW_TABLE_COL_WIDTHS" in data and isinstance(data["REVIEW_TABLE_COL_WIDTHS"], dict):
                    REVIEW_TABLE_COL_WIDTHS.update(data["REVIEW_TABLE_COL_WIDTHS"])
        except Exception:
            pass

load_persistent_settings()
