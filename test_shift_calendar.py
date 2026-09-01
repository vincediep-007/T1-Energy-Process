from datetime import datetime, timedelta
from shift_calculator import get_responsible_shift_and_line, EPOCH_SUNDAY

def run_calendar_check():
    print("=" * 80)
    print("      SHIFT & LINE ROTATION CALENDAR VERIFICATION")
    print("=" * 80)
    print(f"{'Test Timestamp':<22} | {'Station Input':<14} | {'Line Output':<10} | {'Shift Output':<12} | {'Notes'}")
    print("-" * 80)

    # Key test scenarios: Week 1 & Week 2 transitions + Night crossovers (02:00 AM)
    test_cases = [
        # --- Week 1 (A/B: 4-day block, C/D: 3-day block) ---
        (datetime(2026, 8, 30, 8, 30), "TUMCQEL1001", "Week 1 - Sun Day Shift (A)"),
        (datetime(2026, 8, 30, 20, 0), "TUMCQEL1002", "Week 1 - Sun Night Shift (B)"),
        (datetime(2026, 8, 31, 2, 15), "TUMCQEL1003", "Week 1 - Sun Night Crossover at 2 AM (B)"),
        (datetime(2026, 9, 2, 14, 0), "TUMCQEL1010", "Week 1 - Wed Day Shift (A - 4th Day)"),
        (datetime(2026, 9, 2, 23, 45), "TUMCQEL1010", "Week 1 - Wed Night Shift (B - 4th Night)"),
        (datetime(2026, 9, 3, 4, 30), "TUMCQEL1010", "Week 1 - Wed Night Crossover on Thu 4:30 AM (B)"),
        (datetime(2026, 9, 3, 7, 0), "TUMCQEL1014", "Week 1 - Thu Day Shift Start (C - 1st Day)"),
        (datetime(2026, 9, 5, 12, 0), "TUMCQEL1007", "Week 1 - Sat Day Shift End (C - 3rd Day)"),
        (datetime(2026, 9, 5, 21, 0), "TUMCQEL1008", "Week 1 - Sat Night Shift End (D - 3rd Night)"),
        
        # --- Week 2 (A/B: 3-day block, C/D: 4-day block) ---
        (datetime(2026, 9, 6, 6, 30), "TUMCQEL1001", "Week 2 - Sun Day Shift Start (A - 1st Day)"),
        (datetime(2026, 9, 8, 17, 45), "TUMCQEL1005", "Week 2 - Tue Day Shift End (A - 3rd Day)"),
        (datetime(2026, 9, 8, 19, 0), "TUMCQEL1006", "Week 2 - Tue Night Shift End (B - 3rd Night)"),
        (datetime(2026, 9, 9, 6, 15), "TUMCQEL1009", "Week 2 - Wed Day Shift Start (C - 1st Day)"),
        (datetime(2026, 9, 12, 16, 0), "TUMCQEL1013", "Week 2 - Sat Day Shift End (C - 4th Day)"),
        (datetime(2026, 9, 12, 23, 0), "TUMCQEL1014", "Week 2 - Sat Night Shift End (D - 4th Night)"),
        (datetime(2026, 9, 13, 2, 0), "TUMCQEL1014", "Week 2 - Sat Night Crossover on Sun 2 AM (D)"),
        # --- December 2026 Test (Requested Check: 12/6 to 12/9) ---
        (datetime(2026, 12, 6, 8, 0), "TUMCQEL1001", "Dec 6 - Sun Day Shift (A - 1st Day of 4d block)"),
        (datetime(2026, 12, 7, 10, 0), "TUMCQEL1001", "Dec 7 - Mon Day Shift (A - 2nd Day of 4d block)"),
        (datetime(2026, 12, 8, 14, 0), "TUMCQEL1001", "Dec 8 - Tue Day Shift (A - 3rd Day of 4d block)"),
        (datetime(2026, 12, 9, 17, 0), "TUMCQEL1001", "Dec 9 - Wed Day Shift (A - 4th Day of 4d block)"),
        (datetime(2026, 12, 9, 21, 0), "TUMCQEL1001", "Dec 9 - Wed Night Shift (B - 4th Night of 4d block)"),
        (datetime(2026, 12, 10, 8, 0), "TUMCQEL1001", "Dec 10 - Thu Day Shift (C - 1st Day of 3d block)"),
        (datetime(2026, 12, 13, 8, 0), "TUMCQEL1001", "Dec 13 - Sun Day Shift (A - 1st Day of 3d block)"),
        (datetime(2026, 12, 15, 17, 0), "TUMCQEL1001", "Dec 15 - Tue Day Shift (A - 3rd Day of 3d block)")
    ]

    for dt, st, note in test_cases:
        line_out, shift_out = get_responsible_shift_and_line(dt, st)
        print(f"{dt.strftime('%Y-%m-%d %H:%M:%S'):<22} | {st:<14} | {line_out:<10} | {shift_out + ' Shift':<12} | {note}")

    print("=" * 80)

if __name__ == "__main__":
    run_calendar_check()