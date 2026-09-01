# QC Verification Script
import os
import sys
from datetime import datetime, timedelta

# Ensure we can import modules from the current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from search_engine import ImageSearchEngine

def run_test():
    print("--- QC VERIFICATION START ---")
    
    # 1. Setup
    engine = ImageSearchEngine()
    
    # Force use of local Sample Data
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sample_data_path = os.path.join(current_dir, "Sample Data")
    engine.set_search_root(sample_data_path)
    print(f"Testing with Root: {sample_data_path}")
    
    # 2. Parameters
    sn_query = "SN111"
    today = datetime.now()
    # Search today only (since we just made the folders today)
    start_date = today
    end_date = today
    
    # 3. Execution
    print(f"Searching for: '{sn_query}' in date: {today.strftime('%Y-%m-%d')}")
    
    results, exceeded = engine.search_images(
        serial_number=sn_query,
        station_from=config.STATION_MIN,
        station_to=config.STATION_MAX,
        start_date=start_date,
        end_date=end_date
    )
    
    # 4. Verification
    print(f"Results Found: {len(results)} | Exceeded Limit: {exceeded}")
    
    if len(results) > 0:
        print("[PASS] Search Logic works!")
        print("Details:")
        for r in results:
            print(f" - Found: {r['filename']} | Cat: {r['category']} | Status: {r['status']}")
            
        # Verify Grouping Logic
        groups = engine.group_by_timestamp(results)
        print(f"Grouped into {len(groups)} session(s).")
    else:
        print("[FAIL] No images found. Check folder structure or file naming.")
        print(f"Expected path pattern: .../{today.year} Year/{today.month:02d} Month/{today.day:02d} Day/...")

    print("--- QC VERIFICATION END ---")

if __name__ == "__main__":
    run_test()
