# =================== DATA MANAGER ===================
# Manage search history and cached results

import json
import os
from datetime import datetime
from typing import List, Dict, Optional
import config


class DataManager:
    def __init__(self):
        self.search_history = []
        self.search_cache = {}  # Cache search results by SN
        self.load_history()

    def load_history(self):
        """Load search history from file"""
        try:
            if os.path.exists(config.HISTORY_FILE):
                with open(config.HISTORY_FILE, 'r') as f:
                    data = json.load(f)
                    self.search_history = data.get('history', [])
                    # Limit to max items
                    self.search_history = self.search_history[:config.HISTORY_MAX_ITEMS]
        except Exception as e:
            print(f"Error loading history: {e}")
            self.search_history = []

    def save_history(self):
        """Save search history to file"""
        try:
            data = {
                'history': self.search_history,
                'last_updated': datetime.now().isoformat()
            }
            with open(config.HISTORY_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving history: {e}")

    def add_to_history(self, serial_number: str, station_from: int, station_to: int,
                       days_back: int, result_count: int):
        """Add search to history

        Args:
            serial_number: Serial number searched
            station_from: Starting station number
            station_to: Ending station number
            days_back: Days back searched
            result_count: Number of images found
        """
        # Remove existing entry for same SN (move to top)
        self.search_history = [h for h in self.search_history if h.get('sn') != serial_number]

        # Add new entry at the beginning
        entry = {
            'sn': serial_number,
            'station_from': station_from,
            'station_to': station_to,
            'days_back': days_back,
            'result_count': result_count,
            'timestamp': datetime.now().isoformat()
        }
        self.search_history.insert(0, entry)

        # Limit to max items
        self.search_history = self.search_history[:config.HISTORY_MAX_ITEMS]

        # Save to file
        self.save_history()

    def add_batch_history(self, batch_data: List[Dict]):
        """Add multiple entries to history efficiently
        
        Args:
            batch_data: List of dicts with keys: sn, station_from, station_to, days_back, result_count
        """
        # Process in reverse order so the first item in list ends up at top of history
        # (Assuming the list is in Order of Search, e.g. SN1, SN2, SN3)
        # If we insert at 0:
        # Insert SN1 -> [SN1]
        # Insert SN2 -> [SN2, SN1]
        # So we should process SN1, SN2, SN3 normally to get [SN3, SN2, SN1] ?
        # Or if we want top to be SN1? User probably wants latest at top.
        # Let's iterate normally and insert at 0.
        
        for item in batch_data:
            sn = item['sn']
            # Remove existing
            self.search_history = [h for h in self.search_history if h.get('sn') != sn]
            
            # Create entry
            entry = {
                'sn': sn,
                'station_from': item.get('station_from', 0),
                'station_to': item.get('station_to', 0),
                'days_back': item.get('days_back', 0),
                'result_count': item.get('result_count', 0),
                'timestamp': datetime.now().isoformat()
            }
            self.search_history.insert(0, entry)
            
        # Limit
        self.search_history = self.search_history[:config.HISTORY_MAX_ITEMS]
        
        # Save ONCE
        self.save_history()

    def get_history(self) -> List[Dict]:
        """Get search history

        Returns:
            List of history entries
        """
        return self.search_history

    def clear_history(self):
        """Clear all search history"""
        self.search_history = []
        self.save_history()

    def cache_search_results(self, serial_number: str, results: List[Dict]):
        """Cache search results for a serial number

        Args:
            serial_number: Serial number
            results: List of image info dictionaries
        """
        self.search_cache[serial_number] = {
            'results': results,
            'timestamp': datetime.now()
        }

    def get_cached_results(self, serial_number: str, max_age_seconds: int = 3600) -> Optional[List[Dict]]:
        """Get cached search results if available and not too old

        Args:
            serial_number: Serial number
            max_age_seconds: Maximum age of cache in seconds (default: 1 hour)

        Returns:
            List of image info dictionaries or None if not cached or too old
        """
        if serial_number in self.search_cache:
            cache_entry = self.search_cache[serial_number]
            age = (datetime.now() - cache_entry['timestamp']).total_seconds()

            if age <= max_age_seconds:
                return cache_entry['results']

        return None

    def clear_cache(self):
        """Clear all cached search results"""
        self.search_cache.clear()

    def get_statistics(self) -> Dict:
        """Get statistics about cached data

        Returns:
            Dictionary with statistics
        """
        total_cached_sns = len(self.search_cache)
        total_cached_images = sum(len(entry['results']) for entry in self.search_cache.values())

        return {
            'cached_sns': total_cached_sns,
            'cached_images': total_cached_images,
            'history_count': len(self.search_history)
        }
