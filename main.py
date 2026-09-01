# =================== MAIN APPLICATION - VERSION 18.6 ===================
import sys
import os
import json
import io
import time
import ctypes
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
from datetime import datetime, timedelta
import calendar
from PIL import Image, ImageTk, ImageGrab
import win32clipboard

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try: ctypes.windll.user32.SetProcessDPIAware()
    except Exception: pass

if getattr(sys, 'frozen', False):
    current_dir = os.path.dirname(sys.executable)
else:
    current_dir = os.path.dirname(os.path.abspath(__file__))

if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import config
from search_engine import ImageSearchEngine
from image_processor import ImageProcessor
from data_manager import DataManager
from shift_calculator import get_responsible_shift_and_line
from phone_server import start_phone_server, train_voice_pattern, test_mac_mini_relay_connection, get_file_datetime

def generate_shift_time_slots(interval_str):
    if interval_str == "1 Hour": step = 1
    elif interval_str == "2 Hours": step = 2
    elif interval_str == "4 Hours": step = 4
    else: return ["All Shift (06:00 - 18:00)"]
    slots = ["All Shift (06:00 - 18:00)"]
    start_base = getattr(config, 'SHIFT_START_HOUR', 6)
    for i in range(12 // step):
        sh = start_base + (i * step)
        eh = sh + step
        slots.append(f"{sh:02d}:00 - {eh:02d}:00")
    return slots

def get_current_shift_slot(slots):
    now_h = datetime.now().hour
    for s in slots:
        if "All Shift" in s: continue
        try:
            p1, p2 = s.split(' - ')
            sh, eh = int(p1.split(':')[0]), int(p2.split(':')[0])
            if sh <= now_h < eh: return s
        except Exception: pass
    return slots[0]

def get_zoom_factor():
    try:
        zoom_str = getattr(config, 'CHART_ZOOM_LEVEL', '90%')
        return int(zoom_str.replace("%", "").strip()) / 100.0
    except Exception: return 0.9

class ModernButton(tk.Button):
    def __init__(self, parent, text, command, primary=True, **kwargs):
        self.default_bg = kwargs.pop('bg', config.COLOR_PRIMARY if primary else config.COLOR_SECONDARY_BTN)
        fg = "white" if primary else config.COLOR_SECONDARY_TEXT
        padx = kwargs.pop('padx', 12)
        pady = kwargs.pop('pady', 4)
        super().__init__(parent, text=text, command=command, bg=self.default_bg, fg=fg, font=config.FONT_BODY_BOLD, relief=tk.FLAT, borderwidth=0, padx=padx, pady=pady, cursor="hand2", **kwargs)
        self.primary = primary
        self.bind("<Enter>", lambda e: self.config(bg=config.COLOR_PRIMARY_HOVER if self.primary else "#e2e8f0"))
        self.bind("<Leave>", lambda e: self.config(bg=self.default_bg))

class ModernToggleButton(tk.Button):
    def __init__(self, parent, text, initial_state=True, on_toggle=None, **kwargs):
        self.is_active = initial_state
        self.on_toggle = on_toggle
        self.active_bg = config.COLOR_PRIMARY
        self.active_fg = "white"
        self.inactive_bg = "#e2e8f0"
        self.inactive_fg = config.COLOR_TEXT_SECONDARY
        super().__init__(parent, text=text, font=config.FONT_BODY_BOLD, relief=tk.FLAT, borderwidth=0, padx=kwargs.pop('padx', 8), pady=kwargs.pop('pady', 2), cursor="hand2", command=self._handle_click, **kwargs)
        self._refresh_style()
        self.bind("<Enter>", self._on_hover)
        self.bind("<Leave>", self._on_leave)

    def _handle_click(self):
        self.is_active = not self.is_active
        self._refresh_style()
        if self.on_toggle: self.on_toggle(self.is_active)

    def set_state(self, state):
        self.is_active = state
        self._refresh_style()

    def get_state(self): return self.is_active

    def _refresh_style(self):
        if self.is_active: self.config(bg=self.active_bg, fg=self.active_fg)
        else: self.config(bg=self.inactive_bg, fg=self.inactive_fg)

    def _on_hover(self, e): self.config(bg=config.COLOR_PRIMARY_HOVER if self.is_active else "#cbd5e1")
    def _on_leave(self, e): self._refresh_style()

class SelectableLabel(tk.Entry):
    def __init__(self, parent, text="", bg="#ffffff", fg="#000000", font=None, width=None, justify=tk.LEFT, **kwargs):
        if width is None: width = len(text)
        super().__init__(parent, bg=bg, fg=fg, font=font, bd=0, highlightthickness=0, relief=tk.FLAT, readonlybackground=bg, width=width, justify=justify, **kwargs)
        self.insert(0, text)
        self.config(state="readonly", cursor="xterm")
        self.xview_moveto(0)

class CalendarDialog(tk.Toplevel):
    def __init__(self, parent, current_date=None, callback=None, anchor_widget=None):
        super().__init__(parent)
        self.callback = callback
        self.current_date = current_date or datetime.now()
        self.display_date = self.current_date
        self.title("Select Date")
        self.geometry("300x320")
        self.configure(bg="white")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        header = tk.Frame(self, bg=config.COLOR_PRIMARY, height=45)
        header.pack(fill=tk.X)
        self.lbl_month = tk.Label(header, text="", font=config.FONT_SUBTITLE, bg=config.COLOR_PRIMARY, fg="white")
        self.lbl_month.pack(side=tk.LEFT, padx=10, pady=8)
        nav = tk.Frame(header, bg=config.COLOR_PRIMARY)
        nav.pack(side=tk.RIGHT, padx=5)
        tk.Button(nav, text="<", command=self.prev_month, bg=config.COLOR_PRIMARY, fg="white", bd=0).pack(side=tk.LEFT)
        tk.Button(nav, text=">", command=self.next_month, bg=config.COLOR_PRIMARY, fg="white", bd=0).pack(side=tk.LEFT)
        self.cal_frame = tk.Frame(self, bg="white")
        self.cal_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.render_calendar()

    def render_calendar(self):
        for w in self.cal_frame.winfo_children(): w.destroy()
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, d in enumerate(days): tk.Label(self.cal_frame, text=d, font=config.FONT_BODY_BOLD, bg="white", fg="#999").grid(row=0, column=i, pady=(0,4))
        month_days = calendar.monthcalendar(self.display_date.year, self.display_date.month)
        for r, week in enumerate(month_days):
            for c, day in enumerate(week):
                if day == 0: continue
                bg = config.COLOR_PRIMARY if (day == self.current_date.day and self.display_date.month == self.current_date.month and self.display_date.year == self.current_date.year) else "white"
                fg = "white" if bg == config.COLOR_PRIMARY else "#333"
                tk.Button(self.cal_frame, text=str(day), bd=0, bg=bg, fg=fg, width=4, command=lambda d=day: self.select_date(d)).grid(row=r+1, column=c, padx=2, pady=2)
        self.lbl_month.config(text=self.display_date.strftime("%B %Y"))

    def prev_month(self):
        self.display_date = (self.display_date.replace(day=1) - timedelta(days=1))
        self.render_calendar()

    def next_month(self):
        self.display_date = (self.display_date.replace(day=calendar.monthrange(self.display_date.year, self.display_date.month)[1]) + timedelta(days=1))
        self.render_calendar()

    def select_date(self, day):
        if self.callback: self.callback(self.display_date.replace(day=day))
        self.destroy()

class ResultCard(tk.Frame):
    def __init__(self, parent, image_info, callback_click):
        status = image_info.get('status', '-')
        is_ng = (status == config.STATUS_NG)
        status_bg = config.COLOR_STATUS_NG if is_ng else config.COLOR_STATUS_OK
        super().__init__(parent, bg=config.COLOR_CARD_BG, highlightbackground=config.COLOR_CARD_BORDER, highlightthickness=1)
        self.image_info = image_info
        self.callback = callback_click
        info_frame = tk.Frame(self, bg=config.COLOR_CARD_BG, padx=8, pady=6)
        info_frame.pack(fill=tk.BOTH, expand=True)
        cat_text = image_info.get('category', 'UNK').replace("exteriorPic", "")
        SelectableLabel(info_frame, text=cat_text, font=config.FONT_BODY_BOLD, bg=config.COLOR_CARD_BG, fg=config.COLOR_TEXT_MAIN, width=len(cat_text)).pack(side=tk.LEFT)
        fname = image_info.get('filename', '')
        SelectableLabel(info_frame, text=fname, font=config.FONT_SMALL, bg=config.COLOR_CARD_BG, fg=config.COLOR_TEXT_SECONDARY, width=28).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(info_frame, text="View Image", font=config.FONT_SMALL, bg=config.COLOR_PRIMARY, fg="white", relief=tk.FLAT, bd=0, padx=8, pady=2, cursor="hand2", command=self._on_click).pack(side=tk.RIGHT, padx=(8, 0))
        SelectableLabel(info_frame, text=status, font=config.FONT_BODY_BOLD, bg=status_bg, fg="white", justify=tk.CENTER, width=len(status)+2).pack(side=tk.RIGHT, padx=4)
        SelectableLabel(info_frame, text=image_info['datetime'].strftime("%H:%M:%S"), font=config.FONT_SMALL, bg=config.COLOR_CARD_BG, fg=config.COLOR_TEXT_SECONDARY, width=8).pack(side=tk.RIGHT, padx=4)

    def _on_click(self): self.callback(self.image_info['path'])

# =================== TOP 5 & NON-EQUIPMENT SCRAP TAB ===================

class Top5AnalyticsTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=config.COLOR_BG_MAIN, padx=15, pady=10)
        self.app = app
        self.setup_ui()

    def setup_ui(self):
        top_bar = tk.Frame(self, bg=config.COLOR_BG_MAIN)
        top_bar.pack(fill=tk.X, pady=(0, 10))
        tk.Label(top_bar, text="Top 5 Defects & Non-Equipment Scrap Dashboard", font=config.FONT_TITLE, bg=config.COLOR_BG_MAIN, fg=config.COLOR_TEXT_MAIN).pack(side=tk.LEFT)
        ModernButton(top_bar, text="Refresh Charts", command=self.render_charts, primary=True).pack(side=tk.RIGHT)

        self.canvas_area = tk.Canvas(self, bg="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas_area.yview)
        self.scroll_frame = tk.Frame(self.canvas_area, bg="white")
        self.scroll_frame.bind("<Configure>", lambda e: self.canvas_area.config(scrollregion=self.canvas_area.bbox("all")))
        self.canvas_area.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas_area.configure(yscrollcommand=scrollbar.set)
        self.canvas_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.render_charts()

    def render_charts(self):
        for w in self.scroll_frame.winfo_children(): w.destroy()
        records = getattr(self.app, 'global_review_records', [])
        if not records:
            tk.Label(self.scroll_frame, text="No review records available for charts yet. Add items in QC Review Tab.", font=config.FONT_SUBTITLE, bg="white", fg=config.COLOR_TEXT_SECONDARY).pack(pady=50, padx=50)
            return

        defect_counts = {}
        defect_line_counts = {}
        non_eq_scrap_counts = {}
        eq_scrap_classes = ["Equipment Scrap 设备报废", "Production Scrap 生产报废"]

        for r in records:
            summary = r.get('summary', 'Unknown')
            line = r.get('line', 'Line 1')
            cls_val = r.get('class', '')
            res = r.get('result', '')

            defect_counts[summary] = defect_counts.get(summary, 0) + 1
            if summary not in defect_line_counts: defect_line_counts[summary] = {}
            defect_line_counts[summary][line] = defect_line_counts[summary].get(line, 0) + 1

            if res.lower() == "scrap" and cls_val not in eq_scrap_classes:
                non_eq_scrap_counts[summary] = non_eq_scrap_counts.get(summary, 0) + 1

        sorted_defects = sorted(defect_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_5_names = [d[0] for d in sorted_defects]

        w1 = tk.LabelFrame(self.scroll_frame, text=" Top 5 Defects ", font=config.FONT_BODY_BOLD, bg="white", fg=config.COLOR_PRIMARY, padx=10, pady=10)
        w1.pack(fill=tk.X, padx=10, pady=10)
        c1 = tk.Canvas(w1, width=900, height=240, bg="white", highlightthickness=0)
        c1.pack()
        self._draw_bar_chart(c1, 900, 240, sorted_defects)

        w2 = tk.LabelFrame(self.scroll_frame, text=" Top 5 Defects Detail per Line ", font=config.FONT_BODY_BOLD, bg="white", fg=config.COLOR_PRIMARY, padx=10, pady=10)
        w2.pack(fill=tk.X, padx=10, pady=10)
        c2 = tk.Canvas(w2, width=900, height=280, bg="white", highlightthickness=0)
        c2.pack()
        self._draw_grouped_line_chart(c2, 900, 280, top_5_names, defect_line_counts)

        if non_eq_scrap_counts:
            sorted_non_eq = sorted(non_eq_scrap_counts.items(), key=lambda x: x[1], reverse=True)
            w3 = tk.LabelFrame(self.scroll_frame, text=" Non-Equipment Scrap Breakdown ", font=config.FONT_BODY_BOLD, bg="white", fg=config.COLOR_STATUS_NG, padx=10, pady=10)
            w3.pack(fill=tk.X, padx=10, pady=10)
            c3 = tk.Canvas(w3, width=900, height=220, bg="white", highlightthickness=0)
            c3.pack()
            self._draw_bar_chart(c3, 900, 220, sorted_non_eq, bar_color="#dc2626")

    def _draw_bar_chart(self, canvas, c_w, c_h, data_pairs, bar_color="#1a5b82"):
        pad_l, pad_r, pad_t, pad_b = 40, 30, 20, 50
        plot_w, plot_h = c_w - pad_l - pad_r, c_h - pad_t - pad_b
        if not data_pairs: return
        max_val = max([v for k, v in data_pairs]) if data_pairs else 10
        y_max = max(10, ((max_val // 5) + 1) * 5)
        for i in range(6):
            val = int((y_max / 5) * i)
            y_pos = pad_t + plot_h - (i * (plot_h / 5))
            canvas.create_line(pad_l, y_pos, pad_l + plot_w, y_pos, fill="#f1f5f9", width=1)
            canvas.create_text(pad_l - 8, y_pos, text=str(val), fill="#64748b", font=("Segoe UI", 8), anchor="e")
        canvas.create_line(pad_l, pad_t + plot_h, pad_l + plot_w, pad_t + plot_h, fill="#cbd5e1", width=1.5)
        num_bars = len(data_pairs)
        bar_width = plot_w / max(1, num_bars * 1.8)
        for idx, (name, val) in enumerate(data_pairs):
            bx = pad_l + (idx * (plot_w / num_bars)) + (plot_w / num_bars / 2) - (bar_width / 2)
            bh = (val / y_max) * plot_h
            by = pad_t + plot_h - bh
            canvas.create_rectangle(bx, by, bx + bar_width, pad_t + plot_h, fill=bar_color, outline="")
            canvas.create_text(bx + bar_width/2, by - 8, text=str(val), font=("Segoe UI", 9, "bold"), fill="#334155")
            canvas.create_text(bx + bar_width/2, pad_t + plot_h + 15, text=name, font=("Segoe UI", 9), fill="#334155", angle=15, anchor="ne")

    def _draw_grouped_line_chart(self, canvas, c_w, c_h, top_5_names, defect_line_counts):
        pad_l, pad_r, pad_t, pad_b = 40, 150, 20, 40
        plot_w, plot_h = c_w - pad_l - pad_r, c_h - pad_t - pad_b
        lines = [f"Line {i}" for i in range(1, 8)]
        max_val = max([max(defect_line_counts.get(d, {}).values() or [0]) for d in top_5_names] or [1])
        y_max = max(8, ((max_val // 2) + 1) * 2)
        for i in range(5):
            val = int((y_max / 4) * i)
            y_pos = pad_t + plot_h - (i * (plot_h / 4))
            canvas.create_line(pad_l, y_pos, pad_l + plot_w, y_pos, fill="#f1f5f9", width=1)
            canvas.create_text(pad_l - 8, y_pos, text=str(val), fill="#64748b", font=("Segoe UI", 8), anchor="e")
        canvas.create_line(pad_l, pad_t + plot_h, pad_l + plot_w, pad_t + plot_h, fill="#cbd5e1", width=1.5)
        group_w = plot_w / len(lines)
        colors = ["#1a5b82", "#e8702a", "#64748b", "#ca8a04", "#0284c7"]
        for l_idx, l_name in enumerate(lines):
            g_center = pad_l + (l_idx * group_w) + (group_w / 2)
            bar_w = max(3, group_w / 6.5)
            start_x = g_center - ((len(top_5_names) * bar_w) / 2)
            for d_idx, d_name in enumerate(top_5_names):
                val = defect_line_counts.get(d_name, {}).get(l_name, 0)
                bx = start_x + (d_idx * bar_w)
                if val > 0:
                    bh = (val / y_max) * plot_h
                    by = pad_t + plot_h - bh
                    canvas.create_rectangle(bx, by, bx + bar_w, pad_t + plot_h, fill=colors[d_idx % len(colors)], outline="")
                    canvas.create_text(bx + bar_w/2, by - 6, text=str(val), font=("Segoe UI", 7, "bold"), fill="#334155")
            canvas.create_text(g_center, pad_t + plot_h + 12, text=l_name, font=("Segoe UI", 9, "bold"), fill="#334155")
        lx, ly = pad_l + plot_w + 15, pad_t + 20
        for d_idx, d_name in enumerate(top_5_names):
            col = colors[d_idx % len(colors)]
            canvas.create_rectangle(lx, ly, lx + 10, ly + 10, fill=col, outline="")
            canvas.create_text(lx + 16, ly + 5, text=d_name, font=("Segoe UI", 8), fill="#334155", anchor="w")
            ly += 22

# =================== QC DEFECT REVIEW TAB ===================

class QCDefectReviewTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=config.COLOR_BG_MAIN, padx=15, pady=10)
        self.app = app
        self.records = []
        self.active_photo_path = None
        self.last_spoken_raw = ""
        self.last_audio_path = None
        self.setup_ui()

    def setup_ui(self):
        top_ctrl = tk.Frame(self, bg=config.COLOR_BG_MAIN)
        top_ctrl.pack(fill=tk.X, pady=(0, 10))

        scan_box = tk.LabelFrame(top_ctrl, text=" 1. Barcode / QR Scanner Entry ", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_MAIN, fg=config.COLOR_PRIMARY, padx=10, pady=8)
        scan_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        tk.Label(scan_box, text="Serial Number:", font=config.FONT_BODY, bg=config.COLOR_BG_MAIN).pack(anchor=tk.W)
        self.ent_sn = tk.Entry(scan_box, font=("Segoe UI", 12, "bold"), bg=config.COLOR_INPUT_BG, relief=tk.FLAT, bd=5)
        self.ent_sn.pack(fill=tk.X, pady=(4, 6))
        self.ent_sn.bind("<Return>", lambda e: self.on_barcode_scanned())
        self.ent_sn.focus_set()

        meta_row = tk.Frame(scan_box, bg=config.COLOR_BG_MAIN)
        meta_row.pack(fill=tk.X, pady=2)

        tk.Label(meta_row, text="Classification:", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN).grid(row=0, column=0, sticky="w")
        class_options = [""] + list(config.DEFECT_TREE.keys())
        self.cb_class = ttk.Combobox(meta_row, values=class_options, width=28, state="readonly")
        self.cb_class.set("")
        self.cb_class.grid(row=0, column=1, padx=5, pady=2)
        self.cb_class.bind("<<ComboboxSelected>>", lambda e: self.on_class_changed())

        tk.Label(meta_row, text="Defect Summary:", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN).grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.cb_summary = ttk.Combobox(meta_row, values=[""], width=28)
        self.cb_summary.set("")
        self.cb_summary.grid(row=0, column=3, padx=5, pady=2)

        tk.Label(meta_row, text="Result:", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN).grid(row=1, column=0, sticky="w")
        self.cb_result = ttk.Combobox(meta_row, values=["", "Q3", "Scrap"], width=10, state="readonly")
        self.cb_result.set("")
        self.cb_result.grid(row=1, column=1, sticky="w", padx=5, pady=2)

        tk.Label(meta_row, text="Action Cause:", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN).grid(row=1, column=2, sticky="w", padx=(10, 0))
        self.cb_cause = ttk.Combobox(meta_row, values=["", "rework", "Missed inspection"], width=18)
        self.cb_cause.set("")
        self.cb_cause.grid(row=1, column=3, padx=5, pady=2)

        phone_box = tk.LabelFrame(top_ctrl, text=" 2. Live Voice Hearing & Calibration Preview ", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_MAIN, fg=config.COLOR_PRIMARY, padx=10, pady=8)
        phone_box.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(8, 0))

        self.lbl_server_url = tk.Label(phone_box, text=f"{self.app.phone_server_url}", font=("Consolas", 8, "bold"), bg=config.COLOR_BG_MAIN, fg=config.COLOR_PRIMARY, justify=tk.LEFT, wraplength=260)
        self.lbl_server_url.pack(anchor=tk.W, pady=(0, 4))
        self.lbl_photo_status = tk.Label(phone_box, text="Monitoring phone for photos & voice...", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN, fg=config.COLOR_TEXT_SECONDARY)
        self.lbl_photo_status.pack(anchor=tk.W, pady=2)

        self.lbl_hearing = tk.Label(phone_box, text="App Heard: [None]", font=("Segoe UI", 9, "bold"), bg="#f1f5f9", fg=config.COLOR_PRIMARY, padx=8, pady=4, anchor="w", justify=tk.LEFT, wraplength=260)
        self.lbl_hearing.pack(fill=tk.X, pady=4)

        self.btn_learn_voice = ModernButton(phone_box, text="Save Heard Voice as Sample for Selected Defect", command=self.save_heard_voice_as_sample, primary=False, padx=4, pady=2)
        self.btn_learn_voice.pack_forget()

        act_row = tk.Frame(self, bg=config.COLOR_BG_MAIN)
        act_row.pack(fill=tk.X, pady=(0, 8))

        ModernButton(act_row, text="+ Add Review Record", command=self.on_barcode_scanned, primary=True).pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(act_row, text="Export Styled Defect Excel File", command=self.export_styled_excel, primary=True).pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(act_row, text="Clear Records", command=self.clear_all_records, primary=False).pack(side=tk.LEFT)

        self.lbl_table_count = tk.Label(act_row, text="Total Records Reviewed: 0", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_MAIN, fg=config.COLOR_PRIMARY)
        self.lbl_table_count.pack(side=tk.RIGHT, padx=10)

        table_container = tk.Frame(self, bg="white", highlightbackground=config.COLOR_DIVIDER, highlightthickness=1)
        table_container.pack(fill=tk.BOTH, expand=True)

        cols = ("date", "order", "sn", "summary", "class", "result", "cause", "photo", "layup_time", "station", "eval_shift", "line", "shift")
        self.tree = ttk.Treeview(table_container, columns=cols, show='headings', selectmode='browse')
        
        headers = [
            ("date", "Date (A)", 85), ("order", "Order No (B)", 100), ("sn", "Serial No (C)", 140),
            ("summary", "Defect Summary (D)", 170), ("class", "Classification (E)", 120), ("result", "Result (F)", 70),
            ("cause", "Cause (G)", 90), ("photo", "Photo (K)", 110), ("layup_time", "Layup Time (L)", 140),
            ("station", "Station (M)", 100), ("eval_shift", "Eval Shift (N)", 80), ("line", "Line (O)", 70), ("shift", "Shift (P)", 70)
        ]
        for col_id, text, width in headers:
            self.tree.heading(col_id, text=text)
            self.tree.column(col_id, width=width, anchor=tk.CENTER)

        tree_scroll = ttk.Scrollbar(table_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def on_class_changed(self):
        sel_class = self.cb_class.get()
        if sel_class in config.DEFECT_TREE:
            summaries = [""] + config.DEFECT_TREE[sel_class]
            self.cb_summary['values'] = summaries
            self.cb_summary.set("")
        else:
            self.cb_summary['values'] = [""]
            self.cb_summary.set("")

    def refresh_defect_dropdowns(self):
        class_options = [""] + list(config.DEFECT_TREE.keys())
        self.cb_class['values'] = class_options
        self.on_class_changed()

    def save_heard_voice_as_sample(self):
        target_summary = self.cb_summary.get().strip()
        if not target_summary:
            messagebox.showwarning("Voice Training", "Please select a Defect Summary in the dropdown first to map this voice sample to!")
            return
        if not self.last_spoken_raw:
            messagebox.showwarning("Voice Training", "No recent voice recording detected to save!")
            return

        train_voice_pattern(self.last_spoken_raw, target_summary, self.last_audio_path)
        self.btn_learn_voice.pack_forget()
        self.lbl_hearing.config(text=f"Learned! '{self.last_spoken_raw}' -> {target_summary}", fg=config.COLOR_STATUS_OK)
        messagebox.showinfo("Trained", f"Successfully saved '{self.last_spoken_raw}' as a training sample for '{target_summary}'!")

    def find_session_for_file(self, file_dt, sn=None):
        WINDOW_SECONDS = 120  # 2-minute pairing window
        if sn:
            for rec in self.records:
                if rec.get('sn') == sn:
                    return rec

        if file_dt:
            for rec in self.records:
                rec_dt = rec.get('dt')
                if rec_dt and abs((rec_dt - file_dt).total_seconds()) <= WINDOW_SECONDS:
                    return rec
        return None

    def refresh_treeview(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for rec in self.records:
            photo_display = os.path.basename(rec['photo_path']) if rec.get('photo_path') else (os.path.basename(rec.get('sn_photo_path')) if rec.get('sn_photo_path') else "-")
            self.tree.insert('', tk.END, values=(
                rec.get('date', '-'), rec.get('order', '-'), rec.get('sn', '-'),
                rec.get('summary') or "-", rec.get('class') or "-", rec.get('result') or "-",
                rec.get('cause') or "", photo_display,
                rec.get('layup_time', '-'), rec.get('station', '-'), rec.get('eval_shift', ''),
                rec.get('line', ''), rec.get('shift', '')
            ))
        self.lbl_table_count.config(text=f"Total Records Reviewed: {len(self.records)}")
        self.app.global_review_records = self.records

    def query_pre_el(self, sn, session_dt):
        pre_stations = [f"{config.PRE_EL_STATION_PREFIX}{i}" for i in range(config.PRE_EL_STATION_MIN, config.PRE_EL_STATION_MAX + 1)]
        start_search = session_dt - timedelta(days=7)
        end_search = session_dt + timedelta(days=1)
        try:
            results, _ = self.app.search_engine.search_pre_el(sn, pre_stations, start_search, end_search, max_results=10)
        except Exception:
            results = []

        if results:
            latest = sorted(results, key=lambda x: x['timestamp'], reverse=True)[0]
            layup_dt = latest['datetime']
            station_found = latest.get('station', '')
            line_str, shift_str = get_responsible_shift_and_line(layup_dt, station_found)
            return layup_dt.strftime("%Y-%m-%d %H:%M:%S"), station_found, line_str, shift_str
        else:
            line_str, shift_str = get_responsible_shift_and_line(session_dt, "")
            return "-", "-", line_str, shift_str

    def handle_incoming_phone_upload(self, file_path, extracted_sn=None, action="NEW_RECORD", v_summary="", v_class="", v_result="", raw_voice="", audio_path="", file_dt=None):
        if file_dt is None and file_path:
            file_dt = get_file_datetime(file_path)
        if file_dt is None:
            file_dt = datetime.now()

        if raw_voice:
            self.last_spoken_raw = raw_voice
            self.last_audio_path = audio_path
            self.lbl_hearing.config(text=f"App Heard: '{raw_voice}'\n-> Defect: {v_summary or 'Unrecognized'} | Result: {v_result or 'Unspecified'}", fg=config.COLOR_PRIMARY)
            if v_summary:
                self.btn_learn_voice.pack(fill=tk.X, pady=4)

        target_rec = self.find_session_for_file(file_dt, sn=extracted_sn)

        if action == "VOICE_DETECTED":
            if target_rec:
                if v_summary:
                    target_rec['summary'] = v_summary
                    target_rec['class'] = v_class
                if v_result:
                    target_rec['result'] = v_result
                self.refresh_treeview()
            else:
                eval_shift = "Day白" if 6 <= file_dt.hour < 18 else "Night夜"
                line_str, shift_str = get_responsible_shift_and_line(file_dt, "")
                new_rec = {
                    'id': f"rec_{int(time.time()*1000)}",
                    'dt': file_dt,
                    'date': file_dt.strftime("%m/%d/%Y"),
                    'order': "-",
                    'sn': "Pending SN",
                    'summary': v_summary,
                    'class': v_class,
                    'result': v_result,
                    'cause': "",
                    'photo_path': "",
                    'sn_photo_path': "",
                    'layup_time': "-",
                    'station': "-",
                    'eval_shift': eval_shift,
                    'line': line_str,
                    'shift': shift_str
                }
                self.records.insert(0, new_rec)
                self.refresh_treeview()
            return

        if action == "DEFECT_PHOTO":
            if target_rec:
                target_rec['photo_path'] = file_path
                self.refresh_treeview()
            else:
                eval_shift = "Day白" if 6 <= file_dt.hour < 18 else "Night夜"
                line_str, shift_str = get_responsible_shift_and_line(file_dt, "")
                new_rec = {
                    'id': f"rec_{int(time.time()*1000)}",
                    'dt': file_dt,
                    'date': file_dt.strftime("%m/%d/%Y"),
                    'order': "-",
                    'sn': "Pending SN",
                    'summary': "",
                    'class': "",
                    'result': "",
                    'cause': "",
                    'photo_path': file_path,
                    'sn_photo_path': "",
                    'layup_time': "-",
                    'station': "-",
                    'eval_shift': eval_shift,
                    'line': line_str,
                    'shift': shift_str
                }
                self.records.insert(0, new_rec)
                self.refresh_treeview()
            return

        if action == "SN_PHOTO" or extracted_sn:
            sn = extracted_sn or ""
            if not sn: return

            layup_time_str, station_str, line_str, shift_str = self.query_pre_el(sn, file_dt)
            eval_shift = "Day白" if 6 <= file_dt.hour < 18 else "Night夜"

            if target_rec:
                target_rec['sn'] = sn
                target_rec['order'] = sn[:9] if len(sn) >= 9 else sn
                target_rec['sn_photo_path'] = file_path
                target_rec['layup_time'] = layup_time_str
                target_rec['station'] = station_str
                target_rec['line'] = line_str
                target_rec['shift'] = shift_str
                target_rec['date'] = file_dt.strftime("%m/%d/%Y")
                target_rec['eval_shift'] = eval_shift
                self.refresh_treeview()
            else:
                new_rec = {
                    'id': f"rec_{int(time.time()*1000)}",
                    'dt': file_dt,
                    'date': file_dt.strftime("%m/%d/%Y"),
                    'order': sn[:9] if len(sn) >= 9 else sn,
                    'sn': sn,
                    'summary': "",
                    'class': "",
                    'result': "",
                    'cause': "",
                    'photo_path': "",
                    'sn_photo_path': file_path,
                    'layup_time': layup_time_str,
                    'station': station_str,
                    'eval_shift': eval_shift,
                    'line': line_str,
                    'shift': shift_str
                }
                self.records.insert(0, new_rec)
                self.refresh_treeview()
            return

    def on_barcode_scanned(self):
        sn = self.ent_sn.get().strip()
        if not sn: return
        now_dt = datetime.now()

        target_rec = self.find_session_for_file(now_dt)
        layup_time_str, station_str, line_str, shift_str = self.query_pre_el(sn, now_dt)
        eval_shift = "Day白" if 6 <= now_dt.hour < 18 else "Night夜"

        if target_rec and (target_rec['sn'] == "Pending SN" or not target_rec['sn']):
            target_rec['sn'] = sn
            target_rec['order'] = sn[:9] if len(sn) >= 9 else sn
            target_rec['layup_time'] = layup_time_str
            target_rec['station'] = station_str
            target_rec['line'] = line_str
            target_rec['shift'] = shift_str
            if self.cb_summary.get(): target_rec['summary'] = self.cb_summary.get()
            if self.cb_class.get(): target_rec['class'] = self.cb_class.get()
            if self.cb_result.get(): target_rec['result'] = self.cb_result.get()
            if self.cb_cause.get(): target_rec['cause'] = self.cb_cause.get()
            self.refresh_treeview()
        else:
            self.records = [r for r in self.records if r.get('sn') != sn]
            rec = {
                'id': f"rec_{int(time.time()*1000)}",
                'dt': now_dt,
                'date': now_dt.strftime("%m/%d/%Y"),
                'order': sn[:9] if len(sn) >= 9 else sn,
                'sn': sn,
                'summary': self.cb_summary.get(),
                'class': self.cb_class.get(),
                'result': self.cb_result.get(),
                'cause': self.cb_cause.get(),
                'photo_path': self.active_photo_path or "",
                'sn_photo_path': "",
                'layup_time': layup_time_str,
                'station': station_str,
                'eval_shift': eval_shift,
                'line': line_str,
                'shift': shift_str
            }
            self.records.insert(0, rec)
            self.refresh_treeview()

        self.ent_sn.delete(0, tk.END)
        self.active_photo_path = None
        self.cb_summary.set("")
        self.cb_class.set("")
        self.cb_result.set("")
        self.cb_cause.set("")
        self.ent_sn.focus_set()


    def clear_all_records(self):
        if messagebox.askyesno("Clear", "Clear all records?"):
            self.records.clear()
            self.app.global_review_records = []
            for row in self.tree.get_children(): self.tree.delete(row)
            self.lbl_table_count.config(text="Total Records Reviewed: 0")

    def export_styled_excel(self):
        if not self.records:
            messagebox.showwarning("Export", "No records!")
            return
        filename = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel Files", "*.xlsx")], title="Export")
        if not filename: return
        try:
            import openpyxl
            from openpyxl.drawing.image import Image as XLImage
            
            wb = openpyxl.Workbook()
            ws = wb.active
            headers = [
                "Date", "Order No", "Serial No", "Defect Summary", "Classification", 
                "Result", "Defect Cause", "Defect Location", "Root Cause", 
                "Pre-Layup Photo", "Post-Layup Photo", "Layup Time", "Station", 
                "Eval Shift", "Line", "Responsible Shift"
            ]
            ws.append(headers)
            
            for r_idx, rec in enumerate(self.records, start=2):
                ws.cell(row=r_idx, column=1, value=rec['date'])
                ws.cell(row=r_idx, column=2, value=rec['order'])
                ws.cell(row=r_idx, column=3, value=rec['sn'])
                ws.cell(row=r_idx, column=4, value=rec.get('summary', ''))
                ws.cell(row=r_idx, column=5, value=rec.get('class', ''))
                ws.cell(row=r_idx, column=6, value=rec.get('result', ''))
                ws.cell(row=r_idx, column=7, value=rec.get('cause', ''))
                ws.cell(row=r_idx, column=12, value=rec['layup_time'])
                ws.cell(row=r_idx, column=13, value=rec['station'])
                ws.cell(row=r_idx, column=14, value=rec.get('eval_shift', ''))
                ws.cell(row=r_idx, column=15, value=rec.get('line', ''))
                ws.cell(row=r_idx, column=16, value=rec.get('shift', ''))
                
                # Embed and anchor the photo into Column K (Post-Layup / Primary Photo)
                photo_path = rec.get('photo_path')
                if photo_path and os.path.exists(photo_path):
                    try:
                        img = XLImage(photo_path)
                        img.width = 90
                        img.height = 120
                        ws.add_image(img, f"K{r_idx}")
                        ws.row_dimensions[r_idx].height = 95
                    except Exception as img_err:
                        print(f"Failed to embed image for row {r_idx}: {img_err}")

            wb.save(filename)
            messagebox.showinfo("Success", f"Exported styled Excel with images to {filename}")
        except Exception as e: 
            messagebox.showerror("Error", f"{e}")

# =================== CONFIG PANEL ===================

class ConfigPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=config.COLOR_BG_MAIN, padx=25, pady=20)
        self.app = app
        self.setup_ui()

    def setup_ui(self):
        canvas = tk.Canvas(self, bg=config.COLOR_BG_MAIN, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scroll_content = tk.Frame(canvas, bg=config.COLOR_BG_MAIN)
        scroll_content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        tk.Label(scroll_content, text="Server, Station & Defect Tree Configuration", font=config.FONT_TITLE, bg=config.COLOR_BG_MAIN, fg=config.COLOR_TEXT_MAIN).pack(anchor=tk.W, pady=(0, 15))

        card_defect = tk.LabelFrame(scroll_content, text=" 1. Defect Category Manager ", bg=config.COLOR_BG_MAIN, font=config.FONT_BODY_BOLD, fg=config.COLOR_PRIMARY, padx=12, pady=10)
        card_defect.pack(fill=tk.X, pady=(0, 12))
        action_bar = tk.Frame(card_defect, bg=config.COLOR_BG_MAIN)
        action_bar.pack(fill=tk.X, pady=(0, 8))
        ModernButton(action_bar, text="Upload Defect Excel File (.xlsx)", command=self.import_defect_excel, primary=True, padx=8, pady=3).pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(action_bar, text="Save Defect Tree as Default", command=self.save_defect_tree_directly, primary=False, padx=8, pady=3).pack(side=tk.LEFT)

        row_c = tk.Frame(card_defect, bg=config.COLOR_BG_MAIN)
        row_c.pack(fill=tk.X, pady=4)
        tk.Label(row_c, text="Select Classification:", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_MAIN, width=22, anchor="w").pack(side=tk.LEFT)
        self.cfg_cb_class = ttk.Combobox(row_c, values=list(config.DEFECT_TREE.keys()), width=32, state="readonly")
        if config.DEFECT_TREE: self.cfg_cb_class.set(list(config.DEFECT_TREE.keys())[0])
        self.cfg_cb_class.pack(side=tk.LEFT, padx=(0, 10))
        self.cfg_cb_class.bind("<<ComboboxSelected>>", lambda e: self.on_cfg_class_selected())
        self.cfg_ent_class_rename = tk.Entry(row_c, font=config.FONT_BODY, width=26)
        self.cfg_ent_class_rename.pack(side=tk.LEFT, padx=(0, 6))
        ModernButton(row_c, text="Rename Class", command=self.rename_current_classification, primary=False, padx=6, pady=2).pack(side=tk.LEFT)

        row_s = tk.Frame(card_defect, bg=config.COLOR_BG_MAIN)
        row_s.pack(fill=tk.X, pady=4)
        tk.Label(row_s, text="Select Defect Summary:", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_MAIN, width=22, anchor="w").pack(side=tk.LEFT)
        self.cfg_cb_summary = ttk.Combobox(row_s, values=[], width=32, state="readonly")
        self.cfg_cb_summary.pack(side=tk.LEFT, padx=(0, 10))
        self.cfg_ent_summary_rename = tk.Entry(row_s, font=config.FONT_BODY, width=26)
        self.cfg_ent_summary_rename.pack(side=tk.LEFT, padx=(0, 6))
        ModernButton(row_s, text="Rename Summary", command=self.rename_current_summary, primary=False, padx=6, pady=2).pack(side=tk.LEFT)

        row_add = tk.Frame(card_defect, bg=config.COLOR_BG_MAIN)
        row_add.pack(fill=tk.X, pady=(6, 2))
        tk.Label(row_add, text="Add New Item:", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_MAIN, width=22, anchor="w").pack(side=tk.LEFT)
        self.cfg_ent_new_item = tk.Entry(row_add, font=config.FONT_BODY, width=32)
        self.cfg_ent_new_item.pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(row_add, text="+ Add as New Summary", command=self.add_new_summary_to_class, primary=False, padx=6, pady=2).pack(side=tk.LEFT, padx=(0, 4))
        ModernButton(row_add, text="+ Add as New Class", command=self.add_new_classification, primary=False, padx=6, pady=2).pack(side=tk.LEFT)
        self.on_cfg_class_selected()

        card_lines = tk.LabelFrame(scroll_content, text=" 2. Active Production Lines (Default Selection) ", bg=config.COLOR_BG_MAIN, font=config.FONT_BODY_BOLD, fg=config.COLOR_PRIMARY, padx=12, pady=10)
        card_lines.pack(fill=tk.X, pady=(0, 12))
        self.line_buttons = {}
        active_lines_dict = getattr(config, 'ACTIVE_LINES', {})
        for i in range(config.FINAL_EL_STATION_MIN, config.FINAL_EL_STATION_MAX + 1):
            st = f"{config.FINAL_EL_STATION_PREFIX}{i}"
            is_active = active_lines_dict.get(st, True)
            line_idx = i - 1000
            btn = ModernToggleButton(card_lines, text=f"Line {line_idx}", initial_state=is_active, padx=10, pady=3)
            btn.pack(side=tk.LEFT, padx=6)
            self.line_buttons[st] = btn

        card_time = tk.LabelFrame(scroll_content, text=" 3. Search Preferences & Display Zoom ", bg=config.COLOR_BG_MAIN, font=config.FONT_BODY_BOLD, fg=config.COLOR_PRIMARY, padx=12, pady=10)
        card_time.pack(fill=tk.X, pady=(0, 12))
        tk.Label(card_time, text="Pre/Final EL Days Back:", font=config.FONT_BODY, bg=config.COLOR_BG_MAIN).grid(row=0, column=0, sticky="w", pady=4)
        self.ent_pre_days = tk.Entry(card_time, width=6, font=config.FONT_BODY, justify=tk.CENTER)
        self.ent_pre_days.insert(0, str(getattr(config, 'DEFAULT_PRE_FINAL_DAYS_BACK_START', 4)))
        self.ent_pre_days.grid(row=0, column=1, padx=6, pady=4)
        tk.Label(card_time, text="String Black Interval:", font=config.FONT_BODY, bg=config.COLOR_BG_MAIN).grid(row=0, column=2, sticky="w", padx=(15, 4), pady=4)
        self.cb_def_interval = ttk.Combobox(card_time, values=getattr(config, 'TIME_INTERVAL_OPTIONS', ["1 Hour", "2 Hours", "4 Hours", "All Shift"]), state="readonly", width=12)
        self.cb_def_interval.set(getattr(config, 'DEFAULT_TIME_INTERVAL', '2 Hours'))
        self.cb_def_interval.grid(row=0, column=3, padx=6, pady=4)
        self.cb_def_interval.bind("<<ComboboxSelected>>", lambda e: self.on_interval_selected())
        tk.Label(card_time, text="Display Zoom:", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_MAIN, fg=config.COLOR_PRIMARY).grid(row=0, column=4, sticky="w", padx=(15, 4), pady=4)
        zoom_options = getattr(config, 'CHART_ZOOM_OPTIONS', ["70%", "80%", "90%", "100%", "110%", "120%"])
        self.cb_zoom = ttk.Combobox(card_time, values=zoom_options, state="readonly", width=8)
        self.cb_zoom.set(getattr(config, 'CHART_ZOOM_LEVEL', '90%'))
        self.cb_zoom.grid(row=0, column=5, padx=6, pady=4)
        self.cb_zoom.bind("<<ComboboxSelected>>", lambda e: self.on_zoom_selected())

        card_pre = tk.LabelFrame(scroll_content, text=" 4. Pre EL Root Server ", bg=config.COLOR_BG_MAIN, font=config.FONT_BODY_BOLD, fg=config.COLOR_PRIMARY, padx=12, pady=10)
        card_pre.pack(fill=tk.X, pady=(0, 12))
        tk.Label(card_pre, text="Path:", font=config.FONT_BODY, bg=config.COLOR_BG_MAIN).grid(row=0, column=0, sticky="w", pady=4)
        self.ent_pre_root = tk.Entry(card_pre, width=65, font=config.FONT_BODY)
        self.ent_pre_root.insert(0, config.PRE_EL_NETWORK_ROOT)
        self.ent_pre_root.grid(row=0, column=1, padx=8, pady=4)
        self.lbl_pre_status = tk.Label(card_pre, text="Checking...", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_MAIN, fg=config.COLOR_STATUS_WARNING)
        self.lbl_pre_status.grid(row=0, column=2, padx=8)

        card_fin = tk.LabelFrame(scroll_content, text=" 5. Final EL Station IP Mappings (Line 1 to 7) ", bg=config.COLOR_BG_MAIN, font=config.FONT_BODY_BOLD, fg=config.COLOR_PRIMARY, padx=12, pady=10)
        card_fin.pack(fill=tk.X, pady=(0, 15))
        self.fin_entries = {}
        self.fin_labels = {}
        for row_idx, (st_name, st_path) in enumerate(config.FINAL_EL_MAP.items()):
            tk.Label(card_fin, text=f"{st_name}:", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_MAIN).grid(row=row_idx, column=0, sticky="w", pady=2)
            ent = tk.Entry(card_fin, width=65, font=config.FONT_BODY)
            ent.insert(0, st_path)
            ent.grid(row=row_idx, column=1, padx=8, pady=2)
            lbl = tk.Label(card_fin, text="Checking...", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN, fg=config.COLOR_STATUS_WARNING)
            lbl.grid(row=row_idx, column=2, padx=8)
            self.fin_entries[st_name] = ent
            self.fin_labels[st_name] = lbl

        card_phone = tk.LabelFrame(scroll_content, text=" 6. Phone Sync & Mac Mini Relay Setup ", bg=config.COLOR_BG_MAIN, font=config.FONT_BODY_BOLD, fg=config.COLOR_PRIMARY, padx=12, pady=10)
        card_phone.pack(fill=tk.X, pady=(0, 15))

        r_relay = tk.Frame(card_phone, bg=config.COLOR_BG_MAIN)
        r_relay.pack(fill=tk.X, pady=3)
        tk.Label(r_relay, text="Mac Mini Relay URL:", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_MAIN, width=20, anchor="w").pack(side=tk.LEFT)
        self.ent_relay_url = tk.Entry(r_relay, width=42, font=config.FONT_BODY)
        self.ent_relay_url.insert(0, getattr(config, 'MAC_MINI_RELAY_URL', ''))
        self.ent_relay_url.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_toggle_relay = ModernToggleButton(r_relay, text="Enable Relay", initial_state=getattr(config, 'MAC_MINI_RELAY_ENABLED', False), padx=8, pady=2)
        self.btn_toggle_relay.pack(side=tk.LEFT, padx=(0, 8))
        ModernButton(r_relay, text="Test Relay", command=self.test_relay_connection, primary=False, padx=6, pady=2).pack(side=tk.LEFT, padx=(0, 8))
        self.lbl_relay_status = tk.Label(r_relay, text="Ready", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN, fg=config.COLOR_TEXT_SECONDARY)
        self.lbl_relay_status.pack(side=tk.LEFT)

        r_cam = tk.Frame(card_phone, bg=config.COLOR_BG_MAIN)
        r_cam.pack(fill=tk.X, pady=3)
        tk.Label(r_cam, text="Custom Camera Dir (Optional):", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN, width=25, anchor="w").pack(side=tk.LEFT)
        self.ent_phone_cam = tk.Entry(r_cam, width=55, font=config.FONT_SMALL)
        self.ent_phone_cam.insert(0, getattr(config, 'PHONE_CAMERA_DIR', ''))
        self.ent_phone_cam.pack(side=tk.LEFT, padx=(0, 10))

        r_rec = tk.Frame(card_phone, bg=config.COLOR_BG_MAIN)
        r_rec.pack(fill=tk.X, pady=3)
        tk.Label(r_rec, text="Custom Audio Dir (Optional):", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN, width=25, anchor="w").pack(side=tk.LEFT)
        self.ent_phone_rec = tk.Entry(r_rec, width=55, font=config.FONT_SMALL)
        self.ent_phone_rec.insert(0, getattr(config, 'PHONE_RECORDINGS_DIR', ''))
        self.ent_phone_rec.pack(side=tk.LEFT, padx=(0, 10))

        btn_box = tk.Frame(scroll_content, bg=config.COLOR_BG_MAIN)
        btn_box.pack(anchor=tk.W, pady=(0, 20))
        ModernButton(btn_box, text="Test All Connections", command=self.test_connections, primary=False).pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(btn_box, text="Save Settings (Save as Default)", command=self.save_settings, primary=True).pack(side=tk.LEFT)
        self.test_connections()


    def on_cfg_class_selected(self):
        curr_class = self.cfg_cb_class.get()
        self.cfg_ent_class_rename.delete(0, tk.END)
        self.cfg_ent_class_rename.insert(0, curr_class)
        summaries = config.DEFECT_TREE.get(curr_class, [])
        self.cfg_cb_summary['values'] = summaries
        if summaries:
            self.cfg_cb_summary.set(summaries[0])
            self.cfg_ent_summary_rename.delete(0, tk.END)
            self.cfg_ent_summary_rename.insert(0, summaries[0])
        else:
            self.cfg_cb_summary.set("")
            self.cfg_ent_summary_rename.delete(0, tk.END)

    def rename_current_classification(self):
        old_name = self.cfg_cb_class.get()
        new_name = self.cfg_ent_class_rename.get().strip()
        if not old_name or not new_name or old_name == new_name: return
        items = config.DEFECT_TREE.pop(old_name, [])
        config.DEFECT_TREE[new_name] = items
        self.save_defect_tree_directly()
        self.cfg_cb_class['values'] = list(config.DEFECT_TREE.keys())
        self.cfg_cb_class.set(new_name)
        messagebox.showinfo("Renamed", f"Renamed classification:\n'{old_name}' -> '{new_name}'")

    def rename_current_summary(self):
        curr_class = self.cfg_cb_class.get()
        old_sum = self.cfg_cb_summary.get()
        new_sum = self.cfg_ent_summary_rename.get().strip()
        if not curr_class or not old_sum or not new_sum or old_sum == new_sum: return
        summaries = config.DEFECT_TREE.get(curr_class, [])
        if old_sum in summaries:
            idx = summaries.index(old_sum)
            summaries[idx] = new_sum
            config.DEFECT_TREE[curr_class] = summaries
            self.save_defect_tree_directly()
            self.cfg_cb_summary['values'] = summaries
            self.cfg_cb_summary.set(new_sum)
            messagebox.showinfo("Renamed", f"Renamed summary:\n'{old_sum}' -> '{new_sum}'")

    def add_new_summary_to_class(self):
        curr_class = self.cfg_cb_class.get()
        new_item = self.cfg_ent_new_item.get().strip()
        if not curr_class or not new_item: return
        summaries = config.DEFECT_TREE.setdefault(curr_class, [])
        if new_item not in summaries:
            summaries.append(new_item)
            self.save_defect_tree_directly()
            self.cfg_cb_summary['values'] = summaries
            self.cfg_cb_summary.set(new_item)
            self.cfg_ent_new_item.delete(0, tk.END)
            messagebox.showinfo("Added", f"Added '{new_item}' to '{curr_class}'!")

    def add_new_classification(self):
        new_class = self.cfg_ent_new_item.get().strip()
        if not new_class: return
        if new_class not in config.DEFECT_TREE:
            config.DEFECT_TREE[new_class] = []
            self.save_defect_tree_directly()
            self.cfg_cb_class['values'] = list(config.DEFECT_TREE.keys())
            self.cfg_cb_class.set(new_class)
            self.on_cfg_class_selected()
            self.cfg_ent_new_item.delete(0, tk.END)
            messagebox.showinfo("Added", f"Created new classification: '{new_class}'!")

    def import_defect_excel(self):
        file_path = filedialog.askopenfilename(title="Select Defect Table Excel", filetypes=[("Excel Files", "*.xlsx *.xls")])
        if not file_path: return
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, data_only=True)
            ws = wb.active
            new_tree = {}
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or len(row) < 2: continue
                desc = str(row[0] if row[0] is not None else "").strip()
                cls_val = str(row[1] if row[1] is not None else "").strip()
                if len(row) >= 3 and (not desc or desc.lower() == "none"):
                    desc = str(row[1] if row[1] is not None else "").strip()
                    cls_val = str(row[2] if row[2] is not None else "").strip()
                if not cls_val or not desc or "defect classification" in cls_val.lower(): continue
                if cls_val not in new_tree: new_tree[cls_val] = []
                if desc not in new_tree[cls_val]: new_tree[cls_val].append(desc)
            if new_tree:
                config.DEFECT_TREE = new_tree
                self.save_defect_tree_directly()
                self.cfg_cb_class['values'] = list(config.DEFECT_TREE.keys())
                self.cfg_cb_class.set(list(config.DEFECT_TREE.keys())[0])
                self.on_cfg_class_selected()
                self.app.sync_all_tabs(self.cb_def_interval.get())
                messagebox.showinfo("Import Success", f"Imported classifications from {os.path.basename(file_path)}")
        except Exception as e: messagebox.showerror("Excel Error", f"Failed: {e}")

    def save_defect_tree_directly(self):
        if hasattr(config, 'save_persistent_settings'): config.save_persistent_settings()
        self.app.sync_all_tabs(self.cb_def_interval.get())

    def on_interval_selected(self):
        new_interval = self.cb_def_interval.get()
        config.DEFAULT_TIME_INTERVAL = new_interval
        self.app.sync_all_tabs(new_interval)

    def on_zoom_selected(self):
        config.CHART_ZOOM_LEVEL = self.cb_zoom.get()
        self.app.sync_all_tabs(self.cb_def_interval.get())

    def test_relay_connection(self):
        url = self.ent_relay_url.get().strip()
        if not url:
            self.lbl_relay_status.config(text="URL Empty", fg=config.COLOR_STATUS_WARNING)
            return
        self.lbl_relay_status.config(text="Testing...", fg=config.COLOR_PRIMARY)
        def _test():
            ok, msg = test_mac_mini_relay_connection(url, getattr(config, 'MAC_MINI_RELAY_SECRET', ''))
            def update_ui():
                self.lbl_relay_status.config(text="ONLINE" if ok else "OFFLINE", fg=config.COLOR_STATUS_OK if ok else config.COLOR_STATUS_NG)
                if ok:
                    messagebox.showinfo("Mac Mini Relay", f"Relay is online!\n{msg}")
                else:
                    messagebox.showwarning("Mac Mini Relay", f"Could not reach relay:\n{msg}")
            self.app.root.after(0, update_ui)
        threading.Thread(target=_test, daemon=True).start()

    def test_connections(self):
        def _test():
            pre_ok, _ = self.app.search_engine.check_network_access(self.ent_pre_root.get().strip())
            fin_results = {st_name: self.app.search_engine.check_network_access(ent.get().strip())[0] for st_name, ent in self.fin_entries.items()}
            def update_ui():
                self.lbl_pre_status.config(text="ONLINE" if pre_ok else "OFFLINE", fg=config.COLOR_STATUS_OK if pre_ok else config.COLOR_STATUS_NG)
                for st_name, ok in fin_results.items():
                    self.fin_labels[st_name].config(text="ONLINE" if ok else "OFFLINE", fg=config.COLOR_STATUS_OK if ok else config.COLOR_STATUS_NG)
            self.app.root.after(0, update_ui)
        threading.Thread(target=_test, daemon=True).start()

    def save_settings(self):
        new_interval = self.cb_def_interval.get()
        config.DEFAULT_TIME_INTERVAL = new_interval
        config.CHART_ZOOM_LEVEL = self.cb_zoom.get()
        try: config.DEFAULT_PRE_FINAL_DAYS_BACK_START = int(self.ent_pre_days.get().strip())
        except ValueError: config.DEFAULT_PRE_FINAL_DAYS_BACK_START = 4
        config.PRE_EL_NETWORK_ROOT = self.ent_pre_root.get().strip()
        for st_name, ent in self.fin_entries.items(): config.FINAL_EL_MAP[st_name] = ent.get().strip()
        for st_name, btn in self.line_buttons.items(): config.ACTIVE_LINES[st_name] = btn.get_state()
        config.MAC_MINI_RELAY_URL = self.ent_relay_url.get().strip()
        config.MAC_MINI_RELAY_ENABLED = self.btn_toggle_relay.get_state()
        config.PHONE_CAMERA_DIR = self.ent_phone_cam.get().strip()
        config.PHONE_RECORDINGS_DIR = self.ent_phone_rec.get().strip()
        if hasattr(config, 'save_persistent_settings'): config.save_persistent_settings()
        self.app.sync_all_tabs(new_interval)
        self.test_connections()
        messagebox.showinfo("Configuration", "Settings saved!")


# =================== STANDARD SEARCH TAB CONTENT ===================

class TabContent(tk.Frame):
    def __init__(self, parent, app, mode="PRE_EL"):
        super().__init__(parent, bg=config.COLOR_BG_MAIN)
        self.app = app
        self.mode = mode
        self.current_results = {}
        self.raw_ng_images = []
        self.sn_list_ordered = []
        self.buttons_map = {}
        self.setup_ui()

    def setup_ui(self):
        filters = tk.Frame(self, bg=config.COLOR_BG_MAIN)
        filters.pack(fill=tk.X, pady=(0, 6))
        header_row = tk.Frame(filters, bg=config.COLOR_BG_MAIN)
        header_row.pack(fill=tk.X, pady=(0, 4))

        if self.mode == "PRE_EL": title_text = "Serial Numbers (Pre EL - PreEL1 to PreEL14)"
        elif self.mode == "FINAL_EL": title_text = "Serial Numbers (Final EL - Line 1 to 7)"
        else: title_text = "String Black Analytics (Multi-Chart View)"

        tk.Label(header_row, text=title_text, font=config.FONT_TITLE, bg=config.COLOR_BG_MAIN, fg=config.COLOR_TEXT_MAIN).pack(side=tk.LEFT)

        if self.mode != "STRING_BLACK":
            self.txt_sn = scrolledtext.ScrolledText(filters, height=3, font=("Segoe UI", 11), relief=tk.FLAT, bd=5, bg=config.COLOR_INPUT_BG, fg=config.COLOR_TEXT_MAIN)
            self.txt_sn.pack(fill=tk.X, pady=(0, 6))

        row2 = tk.Frame(filters, bg=config.COLOR_BG_MAIN)
        row2.pack(fill=tk.X, pady=(0, 4))

        def create_date_picker(parent_widget, label, default_days_back=0):
            container = tk.Frame(parent_widget, bg=config.COLOR_BG_MAIN)
            container.pack(side=tk.LEFT, padx=(0, 10), anchor="n")
            tk.Label(container, text=label, font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN, fg=config.COLOR_TEXT_SECONDARY).pack(anchor=tk.W)
            default_date = datetime.now() - timedelta(days=default_days_back)
            val_holder = {"date": default_date}
            cb = tk.Entry(container, width=11, font=config.FONT_BODY, bg=config.COLOR_INPUT_BG, fg=config.COLOR_TEXT_MAIN, relief=tk.FLAT, bd=5, justify=tk.CENTER, cursor="hand2")
            cb.insert(0, default_date.strftime("%Y-%m-%d"))
            cb.config(state="readonly", readonlybackground=config.COLOR_INPUT_BG)
            cb.pack(pady=(2, 0))
            cb.bind("<Button-1>", lambda e: CalendarDialog(self.app.root, current_date=val_holder['date'], anchor_widget=cb, callback=lambda d: (val_holder.update({'date': d}), cb.config(state='normal'), cb.delete(0, tk.END), cb.insert(0, d.strftime('%Y-%m-%d')), cb.config(state='readonly'))))
            return val_holder

        days_back_start = getattr(config, 'DEFAULT_PRE_FINAL_DAYS_BACK_START', 4) if self.mode != "STRING_BLACK" else 0
        self.date_from_val = create_date_picker(row2, "From Date", days_back_start)
        self.date_to_val = create_date_picker(row2, "To Date", 0)

        if self.mode == "STRING_BLACK":
            f_time = tk.Frame(row2, bg=config.COLOR_BG_MAIN)
            f_time.pack(side=tk.LEFT, padx=(0, 10), anchor="n")
            tk.Label(f_time, text="Filter Window", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN, fg=config.COLOR_TEXT_SECONDARY).pack(anchor=tk.W)
            slots = generate_shift_time_slots(getattr(config, 'DEFAULT_TIME_INTERVAL', '2 Hours'))
            self.cb_timeslot = ttk.Combobox(f_time, values=slots, width=20, state="readonly")
            self.cb_timeslot.set(get_current_shift_slot(slots))
            self.cb_timeslot.pack(pady=(2, 0))
            self.cb_timeslot.bind("<<ComboboxSelected>>", lambda e: self.render_string_black_dashboard())

            f_line = tk.Frame(row2, bg=config.COLOR_BG_MAIN)
            f_line.pack(side=tk.LEFT, padx=(0, 10), anchor="n")
            tk.Label(f_line, text="Trend Focus Line", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN, fg=config.COLOR_TEXT_SECONDARY).pack(anchor=tk.W)
            active_lines_dict = getattr(config, 'ACTIVE_LINES', {})
            active_line_names = [f"Line {int(st.replace(config.FINAL_EL_STATION_PREFIX,''))-1000}" for st, a in active_lines_dict.items() if a]
            self.cb_trend_line = ttk.Combobox(f_line, values=active_line_names, width=14, state="readonly")
            if active_line_names: self.cb_trend_line.set(active_line_names[0])
            self.cb_trend_line.pack(pady=(2, 0))
            self.cb_trend_line.bind("<<ComboboxSelected>>", lambda e: self.render_string_black_dashboard())

        summary_container = tk.Frame(row2, bg=config.COLOR_BG_MAIN)
        summary_container.pack(side=tk.LEFT, padx=10, anchor="n")
        tk.Label(summary_container, text=" ", font=config.FONT_SMALL, bg=config.COLOR_BG_MAIN).pack(anchor=tk.W)
        self.lbl_summary = tk.Label(summary_container, text="", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_MAIN, fg=config.COLOR_PRIMARY)
        self.lbl_summary.pack(side=tk.LEFT, pady=(2, 0))

        self.btn_export = ModernButton(row2, text="Export Excel", command=self.export_excel, primary=False)
        self.btn_export.pack(side=tk.RIGHT, anchor=tk.S, padx=(0, 10))
        self.btn_export.config(state="disabled")

        self.btn_go = ModernButton(row2, text="Refresh Cache" if self.mode == "STRING_BLACK" else "Search", command=self.toggle_search, primary=True)
        self.btn_go.pack(side=tk.RIGHT, anchor=tk.S)

        btn_bar = tk.Frame(filters, bg=config.COLOR_INPUT_BG, padx=8, pady=5)
        btn_bar.pack(fill=tk.X, pady=(4, 0))
        active_lines_dict = getattr(config, 'ACTIVE_LINES', {})

        if self.mode == "PRE_EL":
            tk.Label(btn_bar, text="Pre EL Stations:", font=config.FONT_BODY_BOLD, bg=config.COLOR_INPUT_BG).pack(side=tk.LEFT, padx=(0, 8))
            for st_idx in range(1, 15):
                st_code = f"{config.PRE_EL_STATION_PREFIX}{1000 + st_idx}"
                parent_line_idx = (st_idx + 1) // 2
                parent_key = f"{config.FINAL_EL_STATION_PREFIX}{1000 + parent_line_idx}"
                btn = ModernToggleButton(btn_bar, text=f"PreEL{st_idx}", initial_state=active_lines_dict.get(parent_key, True), padx=5, pady=2)
                btn.pack(side=tk.LEFT, padx=2)
                self.buttons_map[st_code] = btn
        else:
            tk.Label(btn_bar, text="Active Lines:", font=config.FONT_BODY_BOLD, bg=config.COLOR_INPUT_BG).pack(side=tk.LEFT, padx=(0, 8))
            for i in range(config.FINAL_EL_STATION_MIN, config.FINAL_EL_STATION_MAX + 1):
                st = f"{config.FINAL_EL_STATION_PREFIX}{i}"
                callback = (lambda state: self.render_string_black_dashboard()) if self.mode == "STRING_BLACK" else None
                btn = ModernToggleButton(btn_bar, text=f"Line {i - 1000}", initial_state=active_lines_dict.get(st, True), on_toggle=callback, padx=8, pady=2)
                btn.pack(side=tk.LEFT, padx=4)
                self.buttons_map[st] = btn

        self.results_area = tk.Frame(self, bg=config.COLOR_BG_MAIN)
        self.results_area.pack(fill=tk.BOTH, expand=True, pady=4)
        self.results_canvas = tk.Canvas(self.results_area, bg=config.COLOR_BG_MAIN, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.results_area, orient="vertical", command=self.results_canvas.yview)
        self.valid_frame = tk.Frame(self.results_canvas, bg=config.COLOR_BG_MAIN)
        self.valid_frame.bind("<Configure>", lambda e: self.results_canvas.config(scrollregion=self.results_canvas.bbox("all")))
        self.results_canvas.create_window((0, 0), window=self.valid_frame, anchor="nw", tags="inner_frame")
        self.results_canvas.configure(yscrollcommand=scrollbar.set)
        self.results_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.result_container = self.valid_frame

        if self.mode == "STRING_BLACK": self.after(500, self.render_string_black_dashboard)

    def get_selected_stations(self): return [st for st, btn in self.buttons_map.items() if btn.get_state()]
    def sync_line_buttons_from_config(self):
        active_lines_dict = getattr(config, 'ACTIVE_LINES', {})
        for st, btn in self.buttons_map.items(): btn.set_state(active_lines_dict.get(st, True))

    def update_time_slots(self, interval_str):
        self.sync_line_buttons_from_config()
        if hasattr(self, 'cb_timeslot'):
            slots = generate_shift_time_slots(interval_str)
            self.cb_timeslot['values'] = slots
            self.cb_timeslot.set(get_current_shift_slot(slots))
            self.render_string_black_dashboard()

    def toggle_search(self):
        if self.app.is_searching: self.app.stop_search()
        else: self.app.start_search_for_tab(self)

    def _show_single_sn_results(self, sn):
        results = self.current_results.get(sn, [])
        for w in self.result_container.winfo_children(): w.destroy()
        if not results:
            tk.Label(self.result_container, text=f"No data found for {sn}", font=config.FONT_TITLE, bg=config.COLOR_BG_MAIN, fg=config.COLOR_STATUS_NG).pack(pady=40)
            return
        groups = self.app.search_engine.group_by_timestamp(results)
        for timestamp, images in groups.items():
            frame_header = tk.Frame(self.result_container, bg=config.COLOR_BG_MAIN)
            frame_header.pack(fill=tk.X, pady=(8, 2))
            tk.Label(frame_header, text=f"{sn}  •  {timestamp}", font=config.FONT_SUBTITLE, bg=config.COLOR_BG_MAIN, fg=config.COLOR_PRIMARY).pack(side=tk.LEFT, padx=10)
            grid = tk.Frame(self.result_container, bg=config.COLOR_BG_MAIN)
            grid.pack(fill=tk.X, pady=(0, 6), padx=5)
            for col, img in enumerate(images):
                card = ResultCard(grid, img, self.app.open_image)
                card.grid(row=0, column=col, padx=5, pady=5, sticky="w")

    def render_string_black_dashboard(self):
        pass

    def export_excel(self):
        pass

# =================== MAIN APPLICATION ===================

class AOIDashboardApp:
    def __init__(self, root):
        self.root = root
        self.root.title(config.WINDOW_TITLE)
        self.root.geometry(config.WINDOW_SIZE)
        self.root.configure(bg=config.COLOR_BG_MAIN)
        
        self.search_engine = ImageSearchEngine()
        self.image_processor = ImageProcessor()
        self.data_manager = DataManager()
        self.global_review_records = []

        self.is_searching = False
        self.search_id = 0
        self.active_tab = None
        self.tab_counters = {"PRE_EL": 0, "FINAL_EL": 0, "STRING_BLACK": 0}

        self.phone_server_url = start_phone_server(self.on_phone_photo_uploaded)
        self.setup_styles()
        self.setup_layout()

    def on_phone_photo_uploaded(self, file_path, extracted_sn=None, action="NEW_RECORD", v_summary="", v_class="", v_result="", raw_voice="", audio_path="", file_dt=None):
        for tab in self.all_tabs:
            if isinstance(tab, QCDefectReviewTab):
                self.root.after(0, lambda p=file_path, s=extracted_sn, a=action, vs=v_summary, vc=v_class, vr=v_result, rv=raw_voice, ap=audio_path, fdt=file_dt: tab.handle_incoming_phone_upload(p, s, a, vs, vc, vr, rv, ap, fdt))
                break


    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TNotebook.Tab", font=config.FONT_BODY_BOLD, padding=[14, 7])

    def setup_layout(self):
        self.sidebar = tk.Frame(self.root, bg=config.COLOR_BG_SIDEBAR, width=config.LEFT_PANEL_WIDTH)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        self.create_sidebar_content()

        self.content = tk.Frame(self.root, bg=config.COLOR_BG_MAIN)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=15, pady=10)

        top_bar = tk.Frame(self.content, bg=config.COLOR_BG_MAIN)
        top_bar.pack(fill=tk.X, pady=(0, 5))
        
        ModernButton(top_bar, text="+ Pre EL Tab", command=lambda: self.add_new_tab("PRE_EL"), primary=False, padx=8, pady=3).pack(side=tk.LEFT, padx=(0, 4))
        ModernButton(top_bar, text="+ Final EL Tab", command=lambda: self.add_new_tab("FINAL_EL"), primary=False, padx=8, pady=3).pack(side=tk.LEFT, padx=(0, 4))
        ModernButton(top_bar, text="+ String Black Tab", command=lambda: self.add_new_tab("STRING_BLACK"), primary=False, padx=8, pady=3).pack(side=tk.LEFT, padx=(0, 4))
        ModernButton(top_bar, text="+ QC Defect Review", command=self.add_defect_review_tab, primary=True, padx=8, pady=3).pack(side=tk.LEFT, padx=(0, 4))
        ModernButton(top_bar, text="+ Top 5 Analytics", command=self.add_analytics_tab, primary=False, padx=8, pady=3).pack(side=tk.LEFT)
        ModernButton(top_bar, text="Close Tab", command=self.close_current_tab, primary=False, padx=10, pady=3).pack(side=tk.RIGHT)

        self.main_notebook = ttk.Notebook(self.content)
        self.main_notebook.pack(fill=tk.BOTH, expand=True)

        self.all_tabs = []
        self.add_new_tab("PRE_EL")
        self.add_new_tab("FINAL_EL")
        self.add_new_tab("STRING_BLACK")
        self.add_defect_review_tab()
        self.add_analytics_tab()
        
        self.tab_config = ConfigPanel(self.main_notebook, self)
        self.main_notebook.add(self.tab_config, text="  Config  ")
        self.main_notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

    def create_sidebar_content(self):
        brand_frame = tk.Frame(self.sidebar, bg=config.COLOR_BG_SIDEBAR)
        brand_frame.pack(fill=tk.X, padx=15, pady=15)
        tk.Label(brand_frame, text="AOI & EL Dashboard", font=config.FONT_SUBTITLE, bg=config.COLOR_BG_SIDEBAR, fg=config.COLOR_TEXT_MAIN).pack(anchor=tk.W)
        tk.Label(brand_frame, text="v18.6 - Complete Suite", font=config.FONT_SMALL, bg=config.COLOR_BG_SIDEBAR, fg=config.COLOR_TEXT_SECONDARY).pack(anchor=tk.W)

        nav_header = tk.Frame(self.sidebar, bg=config.COLOR_BG_SIDEBAR)
        nav_header.pack(fill=tk.X, padx=15, pady=(15, 8))
        self.lbl_sn_nav_title = tk.Label(nav_header, text="Serial Numbers (0)", font=config.FONT_BODY_BOLD, bg=config.COLOR_BG_SIDEBAR, fg=config.COLOR_TEXT_SECONDARY)
        self.lbl_sn_nav_title.pack(side=tk.LEFT)

        self.sidebar_nav_canvas = tk.Canvas(self.sidebar, bg=config.COLOR_BG_SIDEBAR, highlightthickness=0)
        self.sidebar_nav_scroll = ttk.Scrollbar(self.sidebar, orient="vertical", command=self.sidebar_nav_canvas.yview)
        self.sidebar_nav_content = tk.Frame(self.sidebar_nav_canvas, bg=config.COLOR_BG_SIDEBAR)
        self.sidebar_nav_content.bind("<Configure>", lambda e: self.sidebar_nav_canvas.configure(scrollregion=self.sidebar_nav_canvas.bbox("all")))
        self.sidebar_nav_canvas.create_window((0, 0), window=self.sidebar_nav_content, anchor="nw")
        self.sidebar_nav_canvas.configure(yscrollcommand=self.sidebar_nav_scroll.set)
        self.sidebar_nav_canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 25))
        self.sidebar_nav_scroll.pack(side="right", fill="y", pady=(0, 25))

    def add_new_tab(self, mode="PRE_EL"):
        self.tab_counters[mode] += 1
        tab = TabContent(self.main_notebook, self, mode=mode)
        self.all_tabs.append(tab)
        label = f"Pre EL {self.tab_counters[mode]}" if mode == "PRE_EL" else (f"Final EL {self.tab_counters[mode]}" if mode == "FINAL_EL" else "String Black")
        idx = max(0, len(self.main_notebook.tabs()) - 1) if hasattr(self, 'tab_config') else len(self.main_notebook.tabs())
        self.main_notebook.insert(idx, tab, text=f"  {label}  ")
        self.main_notebook.select(tab)

    def add_defect_review_tab(self):
        tab = QCDefectReviewTab(self.main_notebook, self)
        self.all_tabs.append(tab)
        idx = max(0, len(self.main_notebook.tabs()) - 1) if hasattr(self, 'tab_config') else len(self.main_notebook.tabs())
        self.main_notebook.insert(idx, tab, text="  QC Defect Review  ")
        self.main_notebook.select(tab)

    def add_analytics_tab(self):
        tab = Top5AnalyticsTab(self.main_notebook, self)
        self.all_tabs.append(tab)
        idx = max(0, len(self.main_notebook.tabs()) - 1) if hasattr(self, 'tab_config') else len(self.main_notebook.tabs())
        self.main_notebook.insert(idx, tab, text="  Top 5 & Scrap Analytics  ")
        self.main_notebook.select(tab)

    def close_current_tab(self):
        current_id = self.main_notebook.select()
        current_tab = self.main_notebook.nametowidget(current_id)
        if isinstance(current_tab, ConfigPanel): return
        if len(self.main_notebook.tabs()) <= 2: return
        if current_tab in self.all_tabs: self.all_tabs.remove(current_tab)
        self.main_notebook.forget(current_id)

    def sync_all_tabs(self, interval_str):
        for tab in self.all_tabs:
            if hasattr(tab, 'sync_line_buttons_from_config'): tab.sync_line_buttons_from_config()
            if getattr(tab, 'mode', None) == "STRING_BLACK": tab.update_time_slots(interval_str)
            if isinstance(tab, QCDefectReviewTab): tab.refresh_defect_dropdowns()

    def on_tab_changed(self, event):
        current_id = self.main_notebook.select()
        current_tab = self.main_notebook.nametowidget(current_id)
        if isinstance(current_tab, TabContent) and current_tab.mode != "STRING_BLACK":
            self.refresh_sidebar_for_tab(current_tab)
        else:
            self.lbl_sn_nav_title.config(text="Dashboard Mode")

    def refresh_sidebar_for_tab(self, tab):
        for w in self.sidebar_nav_content.winfo_children(): w.destroy()
        ordered_sns = getattr(tab, 'sn_list_ordered', [])
        all_results = getattr(tab, 'current_results', {})
        self.lbl_sn_nav_title.config(text=f"Serial Numbers ({len(ordered_sns)})")
        if not ordered_sns: return
        found_sns = [sn for sn, res in all_results.items() if res]
        for sn in ordered_sns:
            is_found = sn in found_sns
            txt = f" {sn} ({len(all_results.get(sn, []))})" if is_found else f" {sn} (0)"
            btn = tk.Button(self.sidebar_nav_content, text=txt, font=("Segoe UI", 9, "bold"), bg=config.COLOR_INPUT_BG if is_found else "#fff0f0", fg=config.COLOR_TEXT_MAIN if is_found else config.COLOR_STATUS_NG, anchor="w", relief=tk.FLAT, bd=0, padx=8, pady=4, cursor="hand2", command=lambda s=sn: tab._show_single_sn_results(s))
            btn.pack(fill=tk.X, pady=2, padx=4)
        self.root.update_idletasks()
        self.sidebar_nav_canvas.config(scrollregion=self.sidebar_nav_canvas.bbox("all"))

    def start_search_for_tab(self, tab):
        sn_list = [line.strip() for line in tab.txt_sn.get("1.0", tk.END).strip().split('\n') if line.strip()] if hasattr(tab, 'txt_sn') else []
        if not sn_list:
            messagebox.showwarning("Search", "Please enter at least one Serial Number!")
            return
        selected_stations = tab.get_selected_stations()
        if not selected_stations:
            messagebox.showwarning("Selection", "Please select at least one station!")
            return
        d_start = tab.date_from_val.get('date', datetime.now()).replace(hour=0, minute=0, second=0)
        d_end = tab.date_to_val.get('date', datetime.now()).replace(hour=23, minute=59, second=59)

        for w in tab.result_container.winfo_children(): w.destroy()
        tab.results_canvas.yview_moveto(0)
        tab.lbl_summary.config(text="")
        tab.btn_export.config(state="disabled")
        tab.progress_bar = ttk.Progressbar(tab.result_container, mode='determinate', length=350)
        tab.progress_bar.pack(pady=(40, 10))
        
        self.is_searching = True
        self.active_tab = tab
        self.search_id += 1
        current_sid = self.search_id
        tab.btn_go.config(text="Stop", bg=config.COLOR_STATUS_NG)
        self.search_engine.cancel_flag.clear()
        threading.Thread(target=self._run_search, args=(tab, sn_list, d_start, d_end, selected_stations, current_sid), daemon=True).start()

    def stop_search(self):
        if self.is_searching and self.active_tab:
            self.search_engine.cancel_search()
            self.is_searching = False
            self.search_id += 1
            try:
                self.active_tab.btn_go.config(text="Search", state="normal", bg=config.COLOR_PRIMARY)
                self.active_tab.lbl_summary.config(text="Cancelled")
                for w in self.active_tab.result_container.winfo_children():
                    if isinstance(w, ttk.Progressbar): w.destroy()
            except Exception: pass

    def _update_progress(self, tab, curr, total, msg):
        try:
            if hasattr(tab, 'progress_bar') and tab.progress_bar.winfo_exists():
                tab.progress_bar['maximum'], tab.progress_bar['value'] = total, curr
        except Exception: pass

    def _run_search(self, tab, sn_list, start, end, stations_list, search_id):
        if search_id != self.search_id: return
        all_results = {}
        self.search_engine.set_progress_callback(lambda c, t, m: self.root.after(0, lambda: self._update_progress(tab, c, t, m)))
        for sn in sn_list:
            if self.search_engine.cancel_flag.is_set() or search_id != self.search_id: break
            if tab.mode == "PRE_EL":
                res, _ = self.search_engine.search_pre_el(sn, stations_list, start, end, max_results=config.MAX_IMAGES_PER_SN)
            else:
                res, _ = self.search_engine.search_final_el(sn, stations_list, start, end, max_results=config.MAX_IMAGES_PER_SN)
            all_results[sn] = res
        self.root.after(0, lambda: self._display_results(tab, all_results, search_id))

    def _display_results(self, tab, all_results, search_id):
        if search_id != self.search_id: return
        self.is_searching = False
        tab.btn_go.config(state="normal", text="Search", bg=config.COLOR_PRIMARY)
        tab.current_results = all_results
        for w in tab.result_container.winfo_children():
            if isinstance(w, ttk.Progressbar): w.destroy()
        if not all_results:
            tk.Label(tab.result_container, text="No results found", font=config.FONT_SUBTITLE, bg=config.COLOR_BG_MAIN, fg=config.COLOR_TEXT_SECONDARY).pack(pady=40)
            return
        tab.btn_export.config(state="normal", text=f"Export ({len(all_results)})")
        found_sns = [sn for sn, res in all_results.items() if res]
        tab.lbl_summary.config(text=f"Found: {sum(len(res) for res in all_results.values())} Imgs across {len(found_sns)} SNs")
        tab.sn_list_ordered = found_sns + [sn for sn in all_results if sn not in found_sns]
        self.refresh_sidebar_for_tab(tab)
        if found_sns: tab._show_single_sn_results(found_sns[0])

    def open_image(self, path):
        try: os.startfile(path)
        except Exception as e: messagebox.showerror("Error", f"{e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = AOIDashboardApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (root.destroy(), sys.exit(0)))
    root.mainloop()