# =================== SHIFT CALCULATOR ===================
# 2-2-3 (4-3 / 3-4) Alternating Shift Logic starting Sunday, Aug 30, 2026
# Day Shift (06:00 - 18:00): A or C
# Night Shift (18:00 - 06:00): B or D

import os
import re
from datetime import datetime, date, timedelta
from typing import Tuple, List, Dict, Optional
import config

# Epoch anchor: Sunday Aug 30, 2026 is Day 0 of Week 1 (4-day week for A/B: Sun, Mon, Tue, Wed)
EPOCH_SUNDAY = date(2026, 8, 30)

def parse_line_from_station(station_str: str) -> str:
    """
    Determines Line (Line 1 to Line 7) from Pre-EL or Final-EL station string.
    7 production lines, each line has 2 Pre-EL stations:
      - Line 1: TUMCQEL1001, TUMCQEL1002 (PreEL 1, PreEL 2)
      - Line 2: TUMCQEL1003, TUMCQEL1004 (PreEL 3, PreEL 4)
      - Line 3: TUMCQEL1005, TUMCQEL1006 (PreEL 5, PreEL 6)
      - Line 4: TUMCQEL1007, TUMCQEL1008 (PreEL 7, PreEL 8)
      - Line 5: TUMCQEL1009, TUMCQEL1010 (PreEL 9, PreEL 10)
      - Line 6: TUMCQEL1011, TUMCQEL1012 (PreEL 11, PreEL 12)
      - Line 7: TUMCQEL1013, TUMCQEL1014 (PreEL 13, PreEL 14)
    Final EL (1 station per line):
      - TUMZJEL1001 to TUMZJEL1007 -> Line 1 to Line 7
    """
    if not station_str or str(station_str).strip() in ("", "-", "None", "Unknown"):
        return ""

    s = str(station_str).strip().upper()

    # Direct "Line X" match
    m_line = re.search(r'LINE\s*([1-7])', s)
    if m_line:
        return f"Line {m_line.group(1)}"

    # Pre-EL: TUMCQEL1001 - TUMCQEL1014
    m_cq = re.search(r'TUMCQEL(\d{4})', s)
    if m_cq:
        st_num = int(m_cq.group(1)) # 1001 to 1014
        st_idx = st_num - 1000      # 1 to 14
        if 1 <= st_idx <= 14:
            line_num = max(1, min(7, (st_idx + 1) // 2))
            return f"Line {line_num}"

    # PreEL 1 - PreEL 14
    m_pre = re.search(r'PRE\s*EL\s*(\d+)', s)
    if m_pre:
        st_idx = int(m_pre.group(1))
        if 1 <= st_idx <= 14:
            line_num = max(1, min(7, (st_idx + 1) // 2))
            return f"Line {line_num}"

    # Final EL: TUMZJEL1001 - TUMZJEL1007 / TUMEL1001 - TUMEL1007
    m_zj = re.search(r'(?:TUMZJEL|TUMEL)(\d{4})', s)
    if m_zj:
        st_num = int(m_zj.group(1)) # 1001 to 1007
        st_idx = st_num - 1000
        if 1 <= st_idx <= 7:
            line_num = max(1, min(7, st_idx))
            return f"Line {line_num}"

    # Layup Machine: TUMLAYUP1001 - TUMLAYUP1007
    m_lay = re.search(r'TUMLAYUP(\d{4})', s)
    if m_lay:
        st_num = int(m_lay.group(1)) # 1001 to 1007
        st_idx = st_num - 1000
        if 1 <= st_idx <= 7:
            line_num = max(1, min(7, st_idx))
            return f"Line {line_num}"

    return ""


def get_responsible_shift_and_line(dt, station_str: str):
    """
    Computes Line (e.g. Line 5) based on station string,
    and Responsible Shift (A, B, C, or D) corresponding to the layup time dt.
    If no station info -> Line is blank ("").
    If no layup time dt -> Shift is blank ("").
    """
    # 1. Line Calculation from station
    line_str = parse_line_from_station(station_str)

    # 2. Responsible Shift Calculation (strictly corresponding to layup time dt)
    if dt is None:
        return line_str, ""

    if isinstance(dt, str):
        dt_str = dt.strip()
        if not dt_str or dt_str in ("", "-", "None", "Unknown"):
            return line_str, ""
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(dt_str, fmt)
                break
            except ValueError:
                pass
        if not parsed:
            return line_str, ""
        dt = parsed

    # 3. Shift Timing (06:00 to 18:00 Day, 18:00 to 06:00 Night)
    # If between 00:00 and 05:59:59, it belongs to the previous calendar day's night shift
    cal_date = dt.date()
    hour = dt.hour

    if hour < 6:
        cal_date = cal_date - timedelta(days=1)
        is_day = False
    elif 6 <= hour < 18:
        is_day = True
    else:
        is_day = False

    # 4. Bi-Weekly 14-Day Cycle Lookup
    days_from_epoch = (cal_date - EPOCH_SUNDAY).days
    cycle_day = days_from_epoch % 14  # 0 to 13

    # Cycle Map:
    # Days 0-3 (Sun-Wed of Week 1): A (Day), B (Night) - 4 days work
    # Days 4-6 (Thu-Sat of Week 1): C (Day), D (Night) - 3 days work
    # Days 7-9 (Sun-Tue of Week 2): A (Day), B (Night) - 3 days work
    # Days 10-13 (Wed-Sat of Week 2): C (Day), D (Night) - 4 days work
    if cycle_day in [0, 1, 2, 3]:
        shift_team = "A" if is_day else "B"
    elif cycle_day in [4, 5, 6]:
        shift_team = "C" if is_day else "D"
    elif cycle_day in [7, 8, 9]:
        shift_team = "A" if is_day else "B"
    else:
        shift_team = "C" if is_day else "D"

    return line_str, shift_team


def get_evaluation_shift(dt=None) -> str:
    """
    Determines the Evaluation Shift (评审班次) for Excel export and operations:
      - 'Day 白': 6am to 6pm (06:00:00 - 17:59:59)
      - 'Night 夜': 6pm to 6am (18:00:00 - 05:59:59)
    """
    if dt is None:
        dt = datetime.now()
    elif isinstance(dt, str):
        s = dt.strip()
        if not s or s in ("-", "None", "Unknown", ""):
            dt = datetime.now()
        elif "DAY" in s.upper() or "白" in s:
            return "Day 白"
        elif "NIGHT" in s.upper() or "夜" in s:
            return "Night 夜"
        else:
            parsed = None
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%m/%d/%Y %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M",
                "%m/%d/%Y %H:%M",
                "%H:%M:%S",
                "%H:%M"
            ):
                try:
                    parsed = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    pass
            dt = parsed if parsed else datetime.now()

    hour = getattr(dt, 'hour', datetime.now().hour)
    return "Day 白" if 6 <= hour < 18 else "Night 夜"


def get_operational_shift_info(dt=None) -> dict:
    """
    Returns operational shift information for general factory operations:
      - Day Shift: 06:00 to 18:00 (A and C shift)
      - Night Shift: 18:00 to 06:00 (B and D shift)
    Returns dict:
      {
         'shift_key': (production_date, is_day_shift),
         'team': 'A' | 'B' | 'C' | 'D',
         'type': 'Day' | 'Night',
         'name': 'A Shift (Day)' | 'B Shift (Night)' | ...,
         'date': production_date,
         'is_day': bool
      }
    """
    if dt is None:
        dt = datetime.now()
    elif isinstance(dt, str):
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(dt.strip(), fmt)
                break
            except Exception:
                pass
        dt = parsed if parsed else datetime.now()

    cal_date = dt.date()
    hour = dt.hour
    if hour < 6:
        prod_date = cal_date - timedelta(days=1)
        is_day = False
    elif 6 <= hour < 18:
        prod_date = cal_date
        is_day = True
    else:
        prod_date = cal_date
        is_day = False

    _, team = get_responsible_shift_and_line(dt, "")
    shift_type = "Day" if is_day else "Night"
    team_label = team or ("A" if is_day else "B")

    return {
        "shift_key": (prod_date, is_day),
        "team": team_label,
        "type": shift_type,
        "name": f"{team_label} Shift ({shift_type})",
        "date": prod_date,
        "is_day": is_day
    }


def get_pre_el_chinese_shift_folder(dt) -> Tuple[date, str, str]:
    """
    Computes the Chinese factory Pre-EL date and shift folder:
    - Daily rollover is 8:00 AM (08:00:00).
    - Day shift ('白班'): 08:00:00 to 19:59:59
    - Night shift ('夜班'): 20:00:00 to 07:59:59 next morning
      (00:00:00 to 07:59:59 belongs to yesterday's night shift)
    Returns: (production_date, shift_folder_name, relative_path)
    Example:
      2026-09-07 20:00:04 -> (2026-09-07, '夜班', '2026 Year\\09 Month\\07 Day\\夜班')
      2026-09-07 09:15:00 -> (2026-09-07, '白班', '2026 Year\\09 Month\\07 Day\\白班')
      2026-09-07 06:16:43 -> (2026-09-06, '夜班', '2026 Year\\09 Month\\06 Day\\夜班')
    """
    if dt is None:
        dt = datetime.now()
    elif isinstance(dt, str):
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(dt.strip(), fmt)
                break
            except Exception:
                pass
        dt = parsed if parsed else datetime.now()

    cal_date = dt.date()
    hour = dt.hour

    if hour < 8:
        # Before 8:00 AM belongs to yesterday's night shift (夜班)
        prod_date = cal_date - timedelta(days=1)
        shift_name = "夜班"
    elif 8 <= hour < 20:
        # 8:00 AM to 7:59:59 PM is today's day shift (白班)
        prod_date = cal_date
        shift_name = "白班"
    else:
        # 8:00 PM to 11:59:59 PM is today's night shift (夜班)
        prod_date = cal_date
        shift_name = "夜班"

    rel_folder = f"{prod_date.year} Year\\{prod_date.month:02d} Month\\{prod_date.day:02d} Day\\{shift_name}"
    return prod_date, shift_name, rel_folder


def get_pinpointed_pre_el_paths(layup_dt, stations_list: list) -> list:
    """
    Builds pinpointed search paths for Pre-EL stations based on Layup Time:
    - Primary pinpointed Chinese shift folder
    - If layup time is within 45 minutes of a shift transition (08:00 or 20:00),
      also includes the adjacent shift folder as a fallback.
    Returns: list of (full_directory_path, station_name)
    """
    if not layup_dt:
        return []

    if isinstance(layup_dt, str):
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(layup_dt.strip(), fmt)
                break
            except Exception:
                pass
        if not parsed:
            return []
        layup_dt = parsed

    # 1. Primary pinpointed folder
    _, primary_shift, primary_rel = get_pre_el_chinese_shift_folder(layup_dt)
    target_rel_folders = [primary_rel]

    # 2. Check for transition boundary within 45 minutes of 08:00 or 20:00
    t_min = layup_dt.hour * 60 + layup_dt.minute
    # Near 8am (07:15 - 08:45)
    if 7 * 60 + 15 <= t_min <= 8 * 60 + 45:
        alt_dt = layup_dt + timedelta(minutes=60 if t_min < 8 * 60 else -60)
        _, _, alt_rel = get_pre_el_chinese_shift_folder(alt_dt)
        if alt_rel not in target_rel_folders:
            target_rel_folders.append(alt_rel)
    # Near 8pm (19:15 - 20:45)
    elif 19 * 60 + 15 <= t_min <= 20 * 60 + 45:
        alt_dt = layup_dt + timedelta(minutes=60 if t_min < 20 * 60 else -60)
        _, _, alt_rel = get_pre_el_chinese_shift_folder(alt_dt)
        if alt_rel not in target_rel_folders:
            target_rel_folders.append(alt_rel)

    # 3. Combine with stations list
    paths = []
    for st in stations_list:
        for rf in target_rel_folders:
            p = os.path.join(config.PRE_EL_NETWORK_ROOT, st, rf)
            paths.append((p, st))

    return paths


def get_pre_el_stations_for_layup_station(station_str: str, available_stations: list) -> list:
    """
    Given a station identifier from MES (e.g. TUMCQEL1007, TUMLAYUP1004, or Line 4),
    prioritizes the matching Pre-EL station(s) at the front of available_stations.
    """
    if not station_str or not available_stations:
        return list(available_stations)

    s = str(station_str).strip().upper()
    
    # 1. Direct Pre-EL station match (e.g. TUMCQEL1007)
    if s in available_stations:
        return [s] + [st for st in available_stations if st != s]

    # 2. Check if station_str corresponds to a production line
    line_label = parse_line_from_station(s)
    if line_label and line_label.startswith("Line "):
        try:
            line_num = int(line_label.replace("Line ", "").strip())
            st_a = f"{config.PRE_EL_STATION_PREFIX}{1000 + 2 * line_num - 1}"
            st_b = f"{config.PRE_EL_STATION_PREFIX}{1000 + 2 * line_num}"
            prioritized = [st for st in (st_a, st_b) if st in available_stations]
            remaining = [st for st in available_stations if st not in prioritized]
            return prioritized + remaining
        except Exception:
            pass

    return list(available_stations)