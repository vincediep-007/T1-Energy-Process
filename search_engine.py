# =================== SEARCH ENGINE ===================
# Multi-threaded search engine with 3-Zone String Black Classifier - Version 9.5

import os
import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from typing import List, Dict, Tuple
from PIL import Image
import config

class ImageSearchEngine:
    def __init__(self):
        self.cancel_flag = threading.Event()
        self.progress_callback = None

    def cancel_search(self):
        self.cancel_flag.set()

    def set_progress_callback(self, callback):
        self.progress_callback = callback

    def _report_progress(self, current, total, message=""):
        if self.progress_callback:
            self.progress_callback(current, total, message)

    def check_network_access(self, network_path: str, timeout: int = None) -> Tuple[bool, str]:
        if timeout is None: timeout = config.NETWORK_TIMEOUT
        result = {'accessible': False, 'error': None}

        def check_path():
            try:
                if os.path.exists(network_path):
                    os.listdir(network_path)
                    result['accessible'] = True
                else:
                    result['error'] = "Path unreachable"
            except Exception as e:
                result['error'] = str(e)

        t = threading.Thread(target=check_path, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive(): return False, f"Timeout ({timeout}s)"
        return (True, "Connected") if result['accessible'] else (False, result.get('error', 'Error'))

    # ================== 3-ZONE (MALE / MIDDLE / FEMALE) ANALYZER ==================
    def classify_string_black_zones(self, image_path: str) -> Dict:
        """
        Splits image into Top 1/3 (Male), Middle 1/3 (Middle), Bottom 1/3 (Female).
        Flagged as black if dark area is >= 30%.
        """
        res = {
            'is_string_black': False,
            'male': False,
            'middle': False,
            'female': False,
            'total_dark_pct': 0.0
        }
        try:
            with Image.open(image_path) as img:
                img_small = img.convert('L').resize((120, 90))
                pixels = list(img_small.getdata())
                
                w, h = 120, 90
                band_h = 30
                
                def get_band_dark_pct(y_start, y_end):
                    band_pixels = [pixels[y * w + x] for y in range(y_start, y_end) for x in range(w)]
                    dark_cnt = sum(1 for p in band_pixels if p < config.BLACK_PIXEL_THRESHOLD)
                    return (dark_cnt / len(band_pixels)) * 100

                top_pct = get_band_dark_pct(0, band_h)          # Top 1/3 (Male)
                mid_pct = get_band_dark_pct(band_h, band_h * 2) # Mid 1/3 (Middle)
                bot_pct = get_band_dark_pct(band_h * 2, h)       # Bot 1/3 (Female)

                total_dark = sum(1 for p in pixels if p < config.BLACK_PIXEL_THRESHOLD)
                total_dark_pct = round((total_dark / len(pixels)) * 100, 1)
                res['total_dark_pct'] = total_dark_pct

                ZONE_THRESHOLD = config.MIN_NG_BLACK_PERCENT # 30.0%
                if top_pct >= ZONE_THRESHOLD: res['male'] = True
                if mid_pct >= ZONE_THRESHOLD: res['middle'] = True
                if bot_pct >= ZONE_THRESHOLD: res['female'] = True

                if total_dark_pct >= ZONE_THRESHOLD or res['male'] or res['middle'] or res['female']:
                    res['is_string_black'] = True

        except Exception:
            pass
        return res

    # ================== PRE EL ==================
    def get_pre_el_date_folders(self, start_date: datetime, end_date: datetime) -> List[str]:
        date_folders = set()
        delta = (end_date - start_date).days
        for i in range(delta + 1):
            d = start_date + timedelta(days=i)
            date_folders.add(f"{d.year} Year\\{d.month:02d} Month\\{d.day:02d} Day")
            if (d + timedelta(days=1)).day == 1:
                nm = 1 if d.month == 12 else d.month + 1
                ny = d.year + 1 if d.month == 12 else d.year
                date_folders.add(f"{ny} Year\\{nm:02d} Month\\{d.day:02d} Day")
        return list(date_folders)

    def categorize_pre_el(self, file_path: str) -> Tuple[str, str]:
        p = file_path.lower()
        if "exteriorpicback" in p or "\\back\\" in p: cat = config.CATEGORY_BACK
        elif "exteriorpicfront" in p or "\\front\\" in p: cat = config.CATEGORY_FRONT
        else: cat = config.CATEGORY_EL
        status = config.STATUS_NG if "\\ng\\" in p or p.endswith("\\ng") else config.STATUS_OK
        return cat, status

    def search_pre_el_path(self, base_path: str, serial_number: str, station_name: str) -> List[Dict]:
        if self.cancel_flag.is_set() or not os.path.exists(base_path): return []
        results = []
        try:
            for root, _, files in os.walk(base_path):
                if self.cancel_flag.is_set(): break
                for filename in files:
                    if serial_number.upper() in filename.upper():
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in config.IMAGE_EXTENSIONS:
                            full_path = os.path.join(root, filename)
                            try:
                                stat = os.stat(full_path)
                                cat, status = self.categorize_pre_el(full_path)
                                results.append({
                                    'path': full_path,
                                    'filename': filename,
                                    'timestamp': stat.st_mtime,
                                    'datetime': datetime.fromtimestamp(stat.st_mtime),
                                    'category': cat,
                                    'status': status,
                                    'size': stat.st_size,
                                    'station': station_name
                                })
                            except: pass
        except: pass
        return results

    def search_pre_el(self, serial_number: str, stations_list: List[str], 
                      start_date: datetime, end_date: datetime, max_results: int = 100) -> Tuple[List[Dict], bool]:
        self.cancel_flag.clear()
        date_folders = self.get_pre_el_date_folders(start_date, end_date)
        search_paths = [(os.path.join(config.PRE_EL_NETWORK_ROOT, st, df), st) for st in stations_list for df in date_folders]
        return self._execute_pool(search_paths, serial_number, self.search_pre_el_path, max_results)

    # ================== FINAL EL & STRING BLACK ==================
    def _parse_final_el_time(self, filename: str, file_date: datetime) -> datetime:
        m = re.search(r'_(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', filename)
        if m:
            try:
                y, mo, d, h, mi, s = map(int, m.groups())
                return datetime(2000 + y, mo, d, h, mi, s)
            except: pass
        m2 = re.search(r'_(\d{6})', filename)
        if m2:
            try:
                h, mi, s = int(m2.group(1)[:2]), int(m2.group(1)[2:4]), int(m2.group(1)[4:6])
                return file_date.replace(hour=h, minute=mi, second=s)
            except: pass
        return file_date

    def search_final_el_path(self, base_path: str, serial_number: str, station_name: str, 
                             time_filter: Tuple[datetime, datetime] = None, 
                             require_string_black: bool = False) -> List[Dict]:
        if self.cancel_flag.is_set() or not os.path.exists(base_path): return []
        results = []
        is_blank_query = (serial_number == "")

        try:
            for root, _, files in os.walk(base_path):
                if self.cancel_flag.is_set(): break
                p_norm = root.replace('/', '\\').upper()
                
                if is_blank_query and require_string_black and not ("\\NG" in p_norm):
                    continue

                for filename in files:
                    if serial_number == "" or serial_number.upper() in filename.upper():
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in config.IMAGE_EXTENSIONS:
                            full_path = os.path.join(root, filename)
                            try:
                                stat = os.stat(full_path)
                                file_dt = datetime.fromtimestamp(stat.st_mtime)
                                parsed_dt = self._parse_final_el_time(filename, file_dt)
                                
                                if time_filter:
                                    t_start, t_end = time_filter
                                    if not (t_start <= parsed_dt <= t_end):
                                        continue

                                analysis = self.classify_string_black_zones(full_path)
                                
                                if require_string_black and not analysis['is_string_black']:
                                    continue

                                in_ng_dir = ("\\NG" in p_norm)
                                is_ng = in_ng_dir or analysis['is_string_black']
                                sn_found = filename.split('_')[0] if '_' in filename else filename

                                results.append({
                                    'path': full_path,
                                    'filename': filename,
                                    'timestamp': stat.st_mtime,
                                    'datetime': parsed_dt,
                                    'category': f"Final EL ({analysis['total_dark_pct']}%)",
                                    'status': config.STATUS_NG if is_ng else config.STATUS_OK,
                                    'dark_pct': analysis['total_dark_pct'],
                                    'male': analysis['male'],
                                    'middle': analysis['middle'],
                                    'female': analysis['female'],
                                    'sn': sn_found,
                                    'station': station_name
                                })
                            except: pass
        except: pass
        return results

    def search_final_el(self, serial_number: str, stations_list: List[str],
                        start_date: datetime, end_date: datetime, 
                        time_filter: Tuple[datetime, datetime] = None,
                        require_string_black: bool = False,
                        max_results: int = 800) -> Tuple[List[Dict], bool]:
        self.cancel_flag.clear()
        delta = (end_date - start_date).days
        search_paths = []

        for station in stations_list:
            station_root = config.FINAL_EL_MAP.get(station)
            if not station_root: continue
            
            for i in range(delta + 1):
                d = start_date + timedelta(days=i)
                y_str = f"{d.year} Year"
                m_str = f"{d.month} Month"
                d_str = f"{d.day} Day"
                day_path = os.path.join(station_root, y_str, m_str, d_str)
                search_paths.append((day_path, station))

        worker = lambda p, sn, st: self.search_final_el_path(p, sn, st, time_filter, require_string_black)
        return self._execute_pool(search_paths, serial_number, worker, max_results)

    # ================== THREAD POOL ==================
    def _execute_pool(self, search_paths, serial_number, scan_func, max_results):
        total_paths = len(search_paths)
        if total_paths == 0: return [], False

        completed = 0
        all_results = []
        exceeded_limit = False
        max_workers = min(14, total_paths)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {executor.submit(scan_func, path, serial_number, st): path 
                              for path, st in search_paths}
            
            for future in as_completed(future_to_path):
                if self.cancel_flag.is_set():
                    for f in future_to_path: f.cancel()
                    break
                
                completed += 1
                try:
                    results = future.result()
                    all_results.extend(results)
                    if max_results > 0 and len(all_results) > max_results:
                        exceeded_limit = True
                        self.cancel_flag.set()
                        for f in future_to_path: f.cancel()
                        break

                    pct = int((completed / total_paths) * 100)
                    tag = serial_number if serial_number else "Scanning"
                    self._report_progress(completed, total_paths, f"{tag}... {pct}%")
                except: pass

        return all_results, exceeded_limit

    def group_by_timestamp(self, images: List[Dict]) -> Dict[str, List[Dict]]:
        if not images: return {}
        sorted_images = sorted(images, key=lambda x: x['timestamp'], reverse=True)
        groups = {}
        processed_indices = set()
        
        for i, img in enumerate(sorted_images):
            if i in processed_indices: continue
            key = img['datetime'].strftime("%Y-%m-%d %H:%M:%S")
            groups[key] = [img]
            processed_indices.add(i)
            
            for j, other in enumerate(sorted_images):
                if j in processed_indices: continue
                if abs(other['timestamp'] - img['timestamp']) <= config.TIME_GROUP_WINDOW:
                    groups[key].append(other)
                    processed_indices.add(j)
                    
        return groups