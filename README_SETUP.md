# AOI & EL Dashboard - QC Defect Suite v18.6

## Quick Start on Laptop

1. **Extract the ZIP file** to any folder on your laptop (e.g. `D:\MR_app\` or `C:\Users\...\Documents\MR_app\`).
2. **Install requirements** (if not already installed):
   ```cmd
   pip install -r requirements.txt
   ```
3. **Launch the app**:
   - Double-click `start_app.bat` (or `a.bat`).

---

## 1. Phone Link Mode (Working Right Now This Week)
- Keep **Phone Link** connected on your laptop.
- Take photos in your native Camera app (zoom is fully supported) and record voice notes in Easy Voice Recorder.
- The app automatically auto-detects your CrossDevice folders across all user profiles and reads photos/audio with **0 extra steps**.

---

## 2. Mac Mini Relay Mode (Next Week & Beyond)
- **On your Mac Mini at home**:
  ```bash
  python3 mac_mini_relay.py
  ```
- **To tunnel from anywhere without router port forwarding**:
  ```bash
  cloudflared tunnel --url http://localhost:8000
  ```
- In the laptop app, go to the **Config** tab &rarr; **Section 6: Phone Sync & Mac Mini Relay Setup**:
  - Paste the Cloudflare URL (e.g. `https://xxxx.trycloudflare.com`).
  - Click **Test Relay** &rarr; Toggle **Enable Relay** &rarr; Click **Save Settings**.

---

## 3. Shift Schedule
- Pre-programmed with the **4-3-3-4 rotating shift schedule** starting Sunday August 30, 2026 for Teams A (Day) and B (Night).
- Automatically calculates the responsible line (Line 1–7) and shift (A, B, C, D) based on module layup timestamp and station ID.
