# =================== SEARCH ENGINE ===================
# Multi-threaded image search with optimizations - Version 5

import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from typing import List, Dict, Tuple
import config

class ImageSearchEngine:
    def __init__(self):
        self.cancel_flag = threading.Event()
        self.progress_callback = None
        self.active_root = config.NETWORK_ROOT # Default to network

    def set_search_root(self, root_path: str):
        """Set the root directory for search (Network or Local Test)"""
        self.active_root = root_path

    def cancel_search(self):
        """Cancel ongoing search"""
        self.cancel_flag.set()

    def set_progress_callback(self, callback):
        """Set callback for progress updates: callback(current, total, message)"""
        self.progress_callback = callback

    def _report_progress(self, current, total, message):
        """Report progress if callback is set"""
        if self.progress_callback:
            self.progress_callback(current, total, message)

    def check_network_access(self, network_path: str, timeout: int = None) -> Tuple[bool, str]:
        """Check if network path is accessible"""
        if timeout is None:
            timeout = config.NETWORK_TIMEOUT

        self._report_progress(0, 1, "Checking connection...")

        result = {'accessible': False, 'error': None}

        def check_path():
            try:
                if os.path.exists(network_path):
                    os.listdir(network_path) # Try to read
                    result['accessible'] = True
                else:
                    result['error'] = "Path does not exist"
            except Exception as e:
                result['error'] = str(e)

        check_thread = threading.Thread(target=check_path, daemon=True)
        check_thread.start()
        check_thread.join(timeout=timeout)

        if check_thread.is_alive():
            return False, f"Timeout ({timeout}s)"

        if result['accessible']:
            self._report_progress(1, 1, "Connected")
            return True, "Connected"
        else:
            return False, result.get('error', 'Unknown error')

    def get_date_folders_range(self, start_date: datetime, end_date: datetime) -> List[str]:
        """Generate date folder paths for a date range [start_date, end_date] (inclusive)"""
        date_folders = []
        delta = end_date - start_date
        
        # Iterate from start_date to end_date
        for i in range(delta.days + 1):
            d = start_date + timedelta(days=i)
            # Format: YYYY Year\MM Month\DD Day
            folder = f"{d.year} Year\\{d.month:02d} Month\\{d.day:02d} Day"
            date_folders.append(folder)
            
        return date_folders

    def categorize_image(self, file_path: str) -> Tuple[str, str]:
        """Categorize image based on path"""
        path_lower = file_path.lower()
        path_normalized = file_path.replace('/', '\\')

        # Category
        if "\\exteriorpicback" in path_lower or "\\back\\" in path_lower:
             category = config.CATEGORY_BACK
        elif "\\exteriorpicfront" in path_lower or "\\front\\" in path_lower:
             category = config.CATEGORY_FRONT
        else:
            category = config.CATEGORY_EL

        # Status
        if "\\ng\\" in path_lower or path_normalized.endswith("\\NG"):
            status = config.STATUS_NG
        elif "\\ok\\" in path_lower or path_normalized.endswith("\\OK"):
            status = config.STATUS_OK
        else:
            status = "UNKNOWN"

        return category, status

    def search_single_path(self, base_path: str, serial_number: str, station_name: str = "Unknown") -> List[Dict]:
        """Search for images in a single path"""
        if self.cancel_flag.is_set() or not os.path.exists(base_path):
            return []

        results = []
        try:
            for root, dirs, files in os.walk(base_path):
                if self.cancel_flag.is_set():
                    break
                for filename in files:
                    # Case-insensitive substring match
                    if serial_number.upper() in filename.upper():
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in config.IMAGE_EXTENSIONS:
                            full_path = os.path.join(root, filename)
                            try:
                                stat = os.stat(full_path)
                                category, status = self.categorize_image(full_path)
                                results.append({
                                    'path': full_path,
                                    'filename': filename,
                                    'timestamp': stat.st_mtime,
                                    'datetime': datetime.fromtimestamp(stat.st_mtime),
                                    'category': category,
                                    'status': status,
                                    'size': stat.st_size,
                                    'station': station_name
                                })
                            except:
                                continue
        except:
            pass
        return results

    def search_images(self, serial_number: str, station_from: int, station_to: int, 
                     start_date: datetime, end_date: datetime, max_results: int = 0) -> Tuple[List[Dict], bool]:
        """Search for images across stations and date range. Return (all_results, exceeded_limit)"""
        self.cancel_flag.clear()

        stations = [f"{config.STATION_PREFIX}{i}" for i in range(station_from, station_to + 1)]
        date_folders = self.get_date_folders_range(start_date, end_date)
        
        search_paths = []
        for station in stations:
            for date_folder in date_folders:
                path = os.path.join(self.active_root, station, date_folder)
                search_paths.append((path, station))

        total_paths = len(search_paths)
        completed = 0
        all_results = []
        exceeded_limit = False
        
        if total_paths == 0:
            return [], False

        # Limit threads
        max_workers = min(8, total_paths) if total_paths > 0 else 1
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {executor.submit(self.search_single_path, path, serial_number, station): path 
                              for path, station in search_paths}
            
            for future in as_completed(future_to_path):
                if self.cancel_flag.is_set():
                    for f in future_to_path: f.cancel()
                    break
                
                path = future_to_path[future]
                completed += 1
                
                try:
                    results = future.result()
                    all_results.extend(results)
                    
                    # Safeguard: Check if results exceed limit
                    if max_results > 0 and len(all_results) > max_results:
                        exceeded_limit = True
                        self.cancel_flag.set() # Stop other threads
                        for f in future_to_path: f.cancel()
                        break

                    # Progress update
                    pct = int((completed / total_paths) * 100)
                    msg = f"Scanning... {pct}%"
                    self._report_progress(completed, total_paths, msg)
                except:
                    pass

        return all_results, exceeded_limit

    def group_by_timestamp(self, images: List[Dict]) -> Dict[str, List[Dict]]:
        """Group images by timestamp (within window)"""
        if not images:
            return {}

        # Sort by timestamp
        sorted_images = sorted(images, key=lambda x: x['timestamp'], reverse=True) # Newest first for display

        groups = {}
        processed_indices = set()
        
        for i, img in enumerate(sorted_images):
            if i in processed_indices:
                continue
                
            # Start a new group with this image
            current_time = img['datetime']
            key = current_time.strftime("%Y-%m-%d %H:%M:%S")
            groups[key] = [img]
            processed_indices.add(i)
            
            # Look for others that fit in this group
            for j, other in enumerate(sorted_images):
                if j in processed_indices:
                    continue
                    
                time_diff = abs((other['timestamp'] - img['timestamp']))
                if time_diff <= config.TIME_GROUP_WINDOW:
                    groups[key].append(other)
                    processed_indices.add(j)
                    
        return groups

    def organize_by_category(self, images: List[Dict]) -> Dict[str, List[Dict]]:
        """Organize images by category for display"""
        organized = {
            config.CATEGORY_FRONT: [],
            config.CATEGORY_BACK: [],
            config.CATEGORY_EL: []
        }
        
        for img in images:
            cat = img.get('category', config.CATEGORY_EL)
            if cat in organized:
                organized[cat].append(img)
                
        return organized
