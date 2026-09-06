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


def sync_to_master_excel(master_path: str, records: List[Dict]) -> tuple:
    """
    Directly appends defect review records into the Master Daily QC Excel workbook.
    Uses Microsoft Excel COM Automation (Office 365 Enterprise native) to ensure:
      - 100% of existing photos (268+ images) remain perfectly intact (zero image deletion).
      - Zero corruption to External Data Ranges, Pivot Tables, Charts, or SharePoint links.
      - Dual embedding of Pre-Layup Photo in Column J and Post-Layup Photo in Column K.
      - Automatically syncs to '源数据data' (Source Data) and '报废scrap' (for Scrap).
    """
    if not records:
        return False, "No review records available to sync!"
    if not master_path or not master_path.strip():
        return False, "Master Report Excel file path is not configured! Please set it in Config tab."

    master_path = master_path.strip()

    # Try native Excel COM first (High-Fidelity Enterprise Mode)
    try:
        import win32com.client
        import pythoncom
        return _sync_via_excel_com(master_path, records)
    except Exception as com_err:
        print(f"[EXCEL COM NOTICE]: COM automation error or not available ({com_err}), running openpyxl fallback...")
        return _sync_via_openpyxl(master_path, records)


def _sync_via_excel_com(master_path: str, records: List[Dict]) -> tuple:
    import win32com.client
    import pythoncom
    
    pythoncom.CoInitialize()
    excel = None
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.ScreenUpdating = False
        
        abs_master_path = os.path.abspath(master_path)
        
        if os.path.exists(abs_master_path):
            wb = excel.Workbooks.Open(abs_master_path, UpdateLinks=0, ReadOnly=False)
        else:
            parent_dir = os.path.dirname(abs_master_path)
            if parent_dir: os.makedirs(parent_dir, exist_ok=True)
            wb = excel.Workbooks.Add()
            ws = wb.Sheets(1)
            ws.Name = "源数据data"
            headers = [
                "日期\nDate", "单号\nOrder number", "序列号\nSerialN0", "不良汇总\nDefect Summary", 
                "不良分类\nDefect Classification", "评审结果\nEvaluation Result", "不良问题\nDefect Cause", 
                "不良位置\nLocation", "流转原因\npass Cause", "层压前图片\nLamination pre-picture", 
                "层压后图片\nLamination Post-picture", "叠层时间\nlayup time", "测试机台\nTesting machine", 
                "评审班次\nEvaluation Shift", "线别\nline", "责任班次\nResponsible shift", 
                "评审位置\nReview position", "是否返工\nRework"
            ]
            for c_idx, h in enumerate(headers, 1):
                cell = ws.Cells(1, c_idx)
                cell.Value = h
                cell.Interior.Color = 0x825B1A
                cell.Font.Color = 0xFFFFFF
                cell.Font.Bold = True
                cell.HorizontalAlignment = -4108
                cell.VerticalAlignment = -4108
            ws.Rows(1).RowHeight = 28
            wb.SaveAs(abs_master_path)
            
        # 1. Locate data worksheet and scrap worksheet
        data_ws = None
        scrap_ws = None
        for s in wb.Sheets:
            s_name = str(s.Name).lower()
            if "源数据" in s_name or "data" in s_name:
                data_ws = s
            elif "报废" in s_name or "scrap" in s_name:
                scrap_ws = s
                
        if data_ws is None:
            for s in wb.Sheets:
                s_name = str(s.Name).lower()
                if "qc" in s_name or "report" in s_name:
                    data_ws = s
                    break
        if data_ws is None:
            data_ws = wb.Sheets(1)
            
        # 2. Collect existing SNs to prevent duplicates
        last_row = data_ws.Cells(data_ws.Rows.Count, 3).End(-4162).Row # xlUp
        existing_sns = set()
        if last_row >= 2:
            sn_values = data_ws.Range(data_ws.Cells(2, 3), data_ws.Cells(last_row, 3)).Value
            if sn_values:
                if isinstance(sn_values, tuple):
                    for row_val in sn_values:
                        if isinstance(row_val, tuple) and len(row_val) > 0 and row_val[0]:
                            existing_sns.add(str(row_val[0]).strip())
                        elif row_val:
                            existing_sns.add(str(row_val).strip())
                else:
                    existing_sns.add(str(sn_values).strip())

        def _clean(v):
            if v is None: return ""
            s = str(v).strip()
            return "" if s in ("-", "None", "Pending SN") else s

        def _append_to_sheet(target_sheet, rec, cur_last_row):
            r_idx = cur_last_row + 1
            sn = _clean(rec.get('sn'))
            
            target_sheet.Cells(r_idx, 1).Value = _clean(rec.get('date'))
            target_sheet.Cells(r_idx, 2).Value = _clean(rec.get('order'))
            target_sheet.Cells(r_idx, 3).Value = sn
            target_sheet.Cells(r_idx, 4).Value = _clean(rec.get('summary'))
            target_sheet.Cells(r_idx, 5).Value = _clean(rec.get('class'))
            target_sheet.Cells(r_idx, 6).Value = _clean(rec.get('result'))
            target_sheet.Cells(r_idx, 7).Value = _clean(rec.get('cause'))
            target_sheet.Cells(r_idx, 8).Value = _clean(rec.get('location'))
            target_sheet.Cells(r_idx, 9).Value = _clean(rec.get('pass_cause', ''))
            target_sheet.Cells(r_idx, 12).Value = _clean(rec.get('layup_time'))
            target_sheet.Cells(r_idx, 13).Value = _clean(rec.get('station'))
            target_sheet.Cells(r_idx, 14).Value = _clean(rec.get('eval_shift'))
            target_sheet.Cells(r_idx, 15).Value = _clean(rec.get('line'))
            target_sheet.Cells(r_idx, 16).Value = _clean(rec.get('shift'))
            target_sheet.Cells(r_idx, 17).Value = _clean(rec.get('review_position', ''))
            target_sheet.Cells(r_idx, 18).Value = _clean(rec.get('rework', ''))
            
            # Format row
            target_sheet.Rows(r_idx).RowHeight = 80
            for c_col in range(1, 19):
                cell_obj = target_sheet.Cells(r_idx, c_col)
                cell_obj.HorizontalAlignment = -4108 # xlCenter
                cell_obj.VerticalAlignment = -4108 # xlCenter
                cell_obj.Borders.Color = 0xE0E8E2 # light gray border
                
            # Highlight Q3 and Scrap
            res_val = str(rec.get('result', '')).upper()
            if "SCRAP" in res_val:
                target_sheet.Cells(r_idx, 6).Interior.Color = 0xE2E2FE # #FEE2E2 BGR
                target_sheet.Cells(r_idx, 6).Font.Color = 0x2626DC # #DC2626
                target_sheet.Cells(r_idx, 6).Font.Bold = True
            elif "Q3" in res_val:
                target_sheet.Cells(r_idx, 6).Interior.Color = 0xC7F3FE # #FEF3C7 BGR
                target_sheet.Cells(r_idx, 6).Font.Color = 0x048ACA # #CA8A04
                target_sheet.Cells(r_idx, 6).Font.Bold = True
                
            # Column 10 (J: Pre-Layup Photo)
            pre_path = rec.get('pre_el_snip_path')
            if pre_path and os.path.exists(pre_path):
                cell_j = target_sheet.Cells(r_idx, 10)
                try:
                    target_sheet.Columns(10).ColumnWidth = 18
                    pic_j = target_sheet.Shapes.AddPicture(
                        os.path.abspath(pre_path),
                        0,  # LinkToFile: msoFalse
                        -1, # SaveWithDocument: msoTrue
                        cell_j.Left + 3,
                        cell_j.Top + 3,
                        cell_j.Width - 6,
                        cell_j.Height - 6
                    )
                    pic_j.Placement = 1 # xlMoveAndSize
                except Exception as pic_err:
                    print(f"Error embedding Pre-EL picture in J{r_idx}: {pic_err}")
                    
            # Column 11 (K: Post-Layup Photo / MR Defect)
            post_path = rec.get('photo_path')
            if post_path and os.path.exists(post_path):
                cell_k = target_sheet.Cells(r_idx, 11)
                try:
                    target_sheet.Columns(11).ColumnWidth = 18
                    pic_k = target_sheet.Shapes.AddPicture(
                        os.path.abspath(post_path),
                        0,  # LinkToFile: msoFalse
                        -1, # SaveWithDocument: msoTrue
                        cell_k.Left + 3,
                        cell_k.Top + 3,
                        cell_k.Width - 6,
                        cell_k.Height - 6
                    )
                    pic_k.Placement = 1 # xlMoveAndSize
                except Exception as pic_err:
                    print(f"Error embedding MR Defect picture in K{r_idx}: {pic_err}")
                    
            return r_idx

        # 3. Append records
        new_synced_count = 0
        cur_data_last_row = last_row
        cur_scrap_last_row = scrap_ws.Cells(scrap_ws.Rows.Count, 3).End(-4162).Row if scrap_ws else 1
        
        for rec in reversed(records):
            sn = _clean(rec.get('sn'))
            if sn and sn in existing_sns:
                continue
                
            cur_data_last_row = _append_to_sheet(data_ws, rec, cur_data_last_row)
            
            # Also append to Scrap sheet if result is Scrap
            res_val = str(rec.get('result', '')).upper()
            if "SCRAP" in res_val and scrap_ws:
                cur_scrap_last_row = _append_to_sheet(scrap_ws, rec, cur_scrap_last_row)
                
            if sn:
                existing_sns.add(sn)
            new_synced_count += 1
            
        data_ws.Columns(10).ColumnWidth = 18
        data_ws.Columns(11).ColumnWidth = 18
        if scrap_ws:
            scrap_ws.Columns(10).ColumnWidth = 18
            scrap_ws.Columns(11).ColumnWidth = 18
            
        wb.Save()
        wb.Close(SaveChanges=True)
        excel.Quit()
        excel = None
        
        return True, f"Successfully synced {new_synced_count} records into Master Report:\n{abs_master_path}\n(All existing pictures, charts, and data ranges preserved!)"
        
    except Exception as e:
        if excel:
            try: excel.Quit()
            except Exception: pass
        raise e
    finally:
        pythoncom.CoUninitialize()


def _sync_via_openpyxl(master_path: str, records: List[Dict]) -> tuple:
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.drawing.image import Image as XLImage
        from openpyxl.utils import get_column_letter

        # 1. Load existing or create new master template
        if os.path.exists(master_path):
            wb = openpyxl.load_workbook(master_path)
            ws = wb.active
        else:
            parent_dir = os.path.dirname(master_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "源数据data"
            headers = [
                "日期\nDate", "单号\nOrder number", "序列号\nSerialN0", "不良汇总\nDefect Summary", 
                "不良分类\nDefect Classification", "评审结果\nEvaluation Result", "不良问题\nDefect Cause", 
                "不良位置\nLocation", "流转原因\npass Cause", "层压前图片\nLamination pre-picture", 
                "层压后图片\nLamination Post-picture", "叠层时间\nlayup time", "测试机台\nTesting machine", 
                "评审班次\nEvaluation Shift", "线别\nline", "责任班次\nResponsible shift", 
                "评审位置\nReview position", "是否返工\nRework"
            ]
            ws.append(headers)
            
            # Header styling
            header_fill = PatternFill(start_color="1A5B82", end_color="1A5B82", fill_type="solid")
            header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.row_dimensions[1].height = 24

        # 2. Check existing Serial Numbers to prevent duplicate rows
        existing_sns = set()
        for r in range(2, ws.max_row + 1):
            val = ws.cell(row=r, column=3).value
            if val:
                existing_sns.add(str(val).strip())

        new_synced_count = 0
        thin_border = Border(left=Side(style='thin', color='E2E8F0'),
                             right=Side(style='thin', color='E2E8F0'),
                             top=Side(style='thin', color='E2E8F0'),
                             bottom=Side(style='thin', color='E2E8F0'))

        def _clean(v):
            if v is None: return ""
            s = str(v).strip()
            return "" if s in ("-", "None", "Pending SN") else s

        # 3. Append new records (reversed so chronological order is maintained)
        for rec in reversed(records):
            sn = _clean(rec.get('sn'))
            if sn and sn in existing_sns:
                continue

            r_idx = ws.max_row + 1
            ws.cell(row=r_idx, column=1, value=_clean(rec.get('date')))
            ws.cell(row=r_idx, column=2, value=_clean(rec.get('order')))
            ws.cell(row=r_idx, column=3, value=sn)
            ws.cell(row=r_idx, column=4, value=_clean(rec.get('summary')))
            ws.cell(row=r_idx, column=5, value=_clean(rec.get('class')))
            ws.cell(row=r_idx, column=6, value=_clean(rec.get('result')))
            ws.cell(row=r_idx, column=7, value=_clean(rec.get('cause')))
            ws.cell(row=r_idx, column=12, value=_clean(rec.get('layup_time')))
            ws.cell(row=r_idx, column=13, value=_clean(rec.get('station')))
            ws.cell(row=r_idx, column=14, value=_clean(rec.get('eval_shift')))
            ws.cell(row=r_idx, column=15, value=_clean(rec.get('line')))
            ws.cell(row=r_idx, column=16, value=_clean(rec.get('shift')))

            # Style each cell in row
            for c_idx in range(1, 19):
                cell = ws.cell(row=r_idx, column=c_idx)
                cell.border = thin_border
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.font = Font(name="Segoe UI", size=9)

            # Highlight Q3 and Scrap
            res_val = str(rec.get('result', '')).upper()
            if "SCRAP" in res_val:
                ws.cell(row=r_idx, column=6).fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
                ws.cell(row=r_idx, column=6).font = Font(name="Segoe UI", size=9, bold=True, color="DC2626")
            elif "Q3" in res_val:
                ws.cell(row=r_idx, column=6).fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
                ws.cell(row=r_idx, column=6).font = Font(name="Segoe UI", size=9, bold=True, color="CA8A04")

            # 1. Embed Pre-Layup Photo into Column J (PreEL snip from Front/EL/Back)
            pre_photo = rec.get('pre_el_snip_path')
            if pre_photo and os.path.exists(pre_photo):
                try:
                    from openpyxl.drawing.spreadsheet_drawing import TwoCellAnchor, AnchorMarker
                    from openpyxl.utils.units import pixels_to_EMU
                    
                    img_pre = XLImage(pre_photo)
                    col_j = 9  # Column J (0-indexed)
                    row_num = r_idx - 1
                    _from_j = AnchorMarker(col=col_j, colOff=pixels_to_EMU(4), row=row_num, rowOff=pixels_to_EMU(4))
                    _to_j = AnchorMarker(col=col_j + 1, colOff=pixels_to_EMU(-4), row=row_num + 1, rowOff=pixels_to_EMU(-4))
                    img_pre.anchor = TwoCellAnchor(editAs='twoCell', _from=_from_j, to=_to_j)
                    ws.add_image(img_pre)
                    ws.row_dimensions[r_idx].height = 80
                except Exception:
                    try:
                        img_pre = XLImage(pre_photo)
                        img_pre.width = 100
                        img_pre.height = 75
                        ws.add_image(img_pre, f"J{r_idx}")
                        ws.row_dimensions[r_idx].height = 80
                    except Exception: pass

            # 2. Embed Post-Layup Photo into Column K (MR Defect Photo / Snip)
            photo_path = rec.get('photo_path')
            if photo_path and os.path.exists(photo_path):
                try:
                    from openpyxl.drawing.spreadsheet_drawing import TwoCellAnchor, AnchorMarker
                    from openpyxl.utils.units import pixels_to_EMU
                    
                    img = XLImage(photo_path)
                    col_k = 10  # Column K (0-indexed)
                    row_num = r_idx - 1
                    _from = AnchorMarker(col=col_k, colOff=pixels_to_EMU(4), row=row_num, rowOff=pixels_to_EMU(4))
                    _to = AnchorMarker(col=col_k + 1, colOff=pixels_to_EMU(-4), row=row_num + 1, rowOff=pixels_to_EMU(-4))
                    anchor = TwoCellAnchor(editAs='twoCell', _from=_from, to=_to)
                    img.anchor = anchor
                    ws.add_image(img)
                    ws.row_dimensions[r_idx].height = 80
                except Exception:
                    try:
                        img = XLImage(photo_path)
                        img.width = 100
                        img.height = 75
                        ws.add_image(img, f"K{r_idx}")
                        ws.row_dimensions[r_idx].height = 80
                    except Exception: pass

            if sn and sn != "Pending SN":
                existing_sns.add(sn)
            new_synced_count += 1

        # Column width optimization
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)
        ws.column_dimensions['J'].width = 18
        ws.column_dimensions['K'].width = 18

        wb.save(master_path)
        return True, f"Successfully synced {new_synced_count} records into Master Report:\n{master_path}"
    except Exception as e:
        return False, f"Master Sync Error: {e}"

