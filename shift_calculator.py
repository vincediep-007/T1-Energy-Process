# =================== SHIFT CALCULATOR ===================
# 2-2-3 (4-3 / 3-4) Alternating Shift Logic starting Sunday, Aug 30, 2026
# Day Shift (06:00 - 18:00): A or C
# Night Shift (18:00 - 06:00): B or D

import re
from datetime import datetime, date, timedelta

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
    if not station_str or station_str == "-" or "Unknown" in station_str:
        return "-"

    s = station_str.strip().upper()

    # Direct "Line X" match
    m_line = re.search(r'LINE\s*([1-7])', s)
    if m_line:
        return f"Line {m_line.group(1)}"

    # Pre-EL: TUMCQEL1001 - TUMCQEL1014
    m_cq = re.search(r'TUMCQEL(\d{4})', s)
    if m_cq:
        st_num = int(m_cq.group(1)) # 1001 to 1014
        st_idx = st_num - 1000      # 1 to 14
        line_num = max(1, min(7, (st_idx + 1) // 2))
        return f"Line {line_num}"

    # PreEL 1 - PreEL 14
    m_pre = re.search(r'PRE\s*EL\s*(\d+)', s)
    if m_pre:
        st_idx = int(m_pre.group(1))
        line_num = max(1, min(7, (st_idx + 1) // 2))
        return f"Line {line_num}"

    # Final EL: TUMZJEL1001 - TUMZJEL1007 / TUMEL1001 - TUMEL1007
    m_zj = re.search(r'(?:TUMZJEL|TUMEL)(\d{4})', s)
    if m_zj:
        st_num = int(m_zj.group(1)) # 1001 to 1007
        line_num = max(1, min(7, st_num - 1000))
        return f"Line {line_num}"

    return "Line 1"


def get_responsible_shift_and_line(dt: datetime, station_str: str):
    """
    Computes Line (e.g. Line 5) and Responsible Shift (A, B, C, or D) from timestamp and station.
    """
    # 1. Line Calculation
    line_str = parse_line_from_station(station_str)

    # 2. Shift Timing (06:00 to 18:00 Day, 18:00 to 06:00 Night)
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

    # 3. Bi-Weekly 14-Day Cycle Lookup
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