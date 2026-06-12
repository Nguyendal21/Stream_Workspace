import sys
import os
import subprocess
import urllib.request
import time
import json
import websocket
import ctypes
from ctypes import wintypes
import threading
import asyncio
import socket
import sqlite3
import csv
import html
import ipaddress
from datetime import datetime, timedelta

try:
    import winsound
except ImportError:
    winsound = None

# ==========================================
# 1. MODULE TU DONG CAI DAT WINDOWS
# ==========================================
def auto_setup_windows():
    print("="*60)
    print(" DANG KIEM TRA MOI TRUONG HE THONG WINDOWS ".center(60))
    print("="*60)

    required_libs = {"PyQt5": "PyQt5", "websocket": "websocket-client", "pycaw": "pycaw", "websockets": "websockets"}
    for import_name, pip_name in required_libs.items():
        try:
            __import__(import_name)
        except ImportError:
            print(f"[*] Dang cai dat thu vien thieu: {pip_name}...")
            subprocess.run([sys.executable, "-m", "pip", "install", pip_name], stdout=subprocess.DEVNULL)
            print(f"[+] Da cai {pip_name} xong.")

    gst_exe = r"C:\Program Files\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe"
    if not os.path.exists(gst_exe):
        print("\n[!] Khong tim thay loi GStreamer tren may tinh nay.")
        msi_url = "https://gstreamer.freedesktop.org/data/pkg/windows/1.22.8/msvc/gstreamer-1.0-msvc-x86_64-1.22.8.msi"
        installer_path = os.path.join(os.environ["TEMP"], "gstreamer_installer.msi")
        
        print(f"[>] Dang tai GStreamer tu server chinh hang (Khoang 90MB)...")
        urllib.request.urlretrieve(msi_url, installer_path)
        
        print(f"[>] Dang cai dat ngam GStreamer (Vui long bam 'Yes' neu Windows hoi quyen Admin)...")
        install_cmd = f'msiexec /i "{installer_path}" /quiet /norestart ADDLOCAL=ALL'
        subprocess.run(install_cmd, shell=True)
        
        if os.path.exists(gst_exe):
            print(f"[+] Cai dat GStreamer thanh cong!")
        else:
            print(f"[-] Cai dat that bai. Vui long chay may voi quyen Admin.")
            sys.exit()
    else:
        print("[+] GStreamer da duoc cai dat san.")
        
    print("="*60)
    print(" KHOI DONG HE THONG... \n")

auto_setup_windows()

# ==========================================
# 2. GIAO DIEN VA LOGIC HE THONG
# ==========================================
import websockets
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, 
                             QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, 
                             QLabel, QGridLayout, QHeaderView, QMessageBox, QTextEdit, QSplitter,
                             QFrame, QGroupBox, QProgressBar, QFileDialog, QSystemTrayIcon,
                             QStyle, QLineEdit, QFormLayout, QButtonGroup, QDateTimeEdit)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QDateTime
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QTextDocument
from PyQt5.QtPrintSupport import QPrinter
from pycaw.pycaw import AudioUtilities

# --- AUTO DETECT LOCAL IP ---
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

VPS_URL = "ws://127.0.0.1:8765"
MASTER_VPN_IP = "100.92.168.67"
MASTER_LAN_IP = get_local_ip()
NOTES_FILE = "device_notes.json"
CBRN_DB_FILE = "cbrn_history.sqlite"
SCREENSHOT_DIR = "screenshots"
REPORT_DIR = "reports"
LOG_DIR = "logs"
CBRN_SENSORS = ["SVG-2", "RAID-M100"]
CLIENT_COLORS = ["#2ecc71", "#f39c12", "#9b59b6"]

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def now_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def classify_network(ip_value):
    if not ip_value or ip_value == "Unknown":
        return "Khong ro"
    try:
        ip_obj = ipaddress.ip_address(ip_value)
        if ip_obj.is_loopback:
            return "Localhost"
        if ip_obj.is_private:
            return "LAN/Wi-Fi noi bo"
        return "5G/VPN Internet"
    except ValueError:
        return "Khong ro"

def normalize_level(value):
    try:
        return max(0, min(8, int(float(value))))
    except (TypeError, ValueError):
        return 0

def is_alarm_status(status_text):
    text = str(status_text or "").strip().lower()
    return any(key in text for key in ["alarm", "alert", "warning", "canh", "cảnh", "bao dong", "báo động"])

def is_error_status(status_text):
    text = str(status_text or "").strip().lower()
    return any(key in text for key in ["loi", "lỗi", "error", "mat ket noi", "mất kết nối", "lost"])

class CBRNDatabase:
    def __init__(self, db_path=CBRN_DB_FILE):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cbrn_measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    sensor TEXT NOT NULL,
                    status TEXT NOT NULL,
                    agent TEXT,
                    concentration TEXT,
                    unit TEXT,
                    level INTEGER,
                    acknowledged INTEGER DEFAULT 0,
                    raw_json TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cbrn_time ON cbrn_measurements(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cbrn_device ON cbrn_measurements(device_id, sensor)")

    def log_measurement(self, payload):
        row = {
            "timestamp": payload.get("timestamp") or now_ts(),
            "device_id": payload.get("device_id", "UNKNOWN"),
            "sensor": payload.get("sensor", "UNKNOWN"),
            "status": payload.get("status", "OK"),
            "agent": payload.get("agent", ""),
            "concentration": str(payload.get("concentration", "")),
            "unit": payload.get("unit", ""),
            "level": normalize_level(payload.get("level", 0)),
            "raw_json": json.dumps(payload, ensure_ascii=False)
        }
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO cbrn_measurements
                    (timestamp, device_id, sensor, status, agent, concentration, unit, level, raw_json)
                VALUES
                    (:timestamp, :device_id, :sensor, :status, :agent, :concentration, :unit, :level, :raw_json)
            """, row)

    def acknowledge_all(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE cbrn_measurements SET acknowledged = 1 WHERE acknowledged = 0")

    def fetch_measurements(self, start_ts=None, end_ts=None, limit=1000):
        query = """
            SELECT timestamp, device_id, sensor, status, agent, concentration, unit, level, acknowledged
            FROM cbrn_measurements
        """
        params = []
        filters = []
        if start_ts:
            filters.append("timestamp >= ?")
            params.append(start_ts)
        if end_ts:
            filters.append("timestamp <= ?")
            params.append(end_ts)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(query, params).fetchall()

    def export_report(self, path, start_ts=None, end_ts=None):
        rows = self.fetch_measurements(start_ts=start_ts, end_ts=end_ts, limit=50000)
        headers = ["Thoi gian", "Client", "Cam bien", "Trang thai", "Tac nhan", "Nong do", "Don vi", "Level", "Da xac nhan"]
        ext = os.path.splitext(path)[1].lower()

        if ext == ".pdf":
            doc = QTextDocument()
            doc.setHtml(self._build_html_report(headers, rows, start_ts, end_ts))
            printer = QPrinter(QPrinter.HighResolution)
            printer.setOutputFormat(QPrinter.PdfFormat)
            printer.setOutputFileName(path)
            doc.print_(printer)
        elif ext in [".xls", ".html"]:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._build_html_report(headers, rows, start_ts, end_ts))
        else:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
        return len(rows)

    def _build_html_report(self, headers, rows, start_ts, end_ts):
        period = f"{html.escape(start_ts or 'Bat dau')} - {html.escape(end_ts or 'Hien tai')}"
        header_html = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        body_html = ""
        for row in rows:
            body_html += "<tr>" + "".join(f"<td>{html.escape(str(cell if cell is not None else ''))}</td>" for cell in row) + "</tr>"
        return f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; font-size: 10pt; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #888; padding: 5px; }}
                th {{ background: #e8eef6; }}
            </style>
        </head>
        <body>
            <h2>Bao cao CBRN</h2>
            <p>Khung gio: {period}</p>
            <table><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>
        </body>
        </html>
        """

# --- HAM TIM CUA SO WINDOWS ---
def find_window_by_pid(pid):
    hwnds = []
    def callback(hwnd, lParam):
        window_pid = ctypes.c_uint()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value == pid and ctypes.windll.user32.IsWindowVisible(hwnd):
            hwnds.append(hwnd)
        return True
    cb_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(cb_type(callback), 0)
    return hwnds[0] if hwnds else None

# ==============================================================
# LUỒNG CHẠY NGẦM SERVER VPS TRÊN MASTER (ROUTING THÔNG MINH)
# ==============================================================
class LocalSignalingServer(QThread):
    log_signal = pyqtSignal(str)
    htop_signal = pyqtSignal(dict) 
    client_disconnected_signal = pyqtSignal(str) # [CẬP NHẬT]: Tín hiệu Client ngắt kết nối
    client_connected_signal = pyqtSignal(str)    # [CẬP NHẬT]: Tín hiệu Client trực tuyến lại

    def __init__(self):
        super().__init__()
        self.clients = {}
        self.master_ws = None
        self.device_locations = {}
        self.device_states = {} 
        self.device_telemetry = {}
        self.device_cbrn = {}

    def log(self, msg):
        time_str = time.strftime("%H:%M:%S")
        self.log_signal.emit(f"[{time_str}] {msg}")

    async def send_client_list(self):
        if self.master_ws:
            client_list = []
            for device_id, info in self.clients.items():
                remote_ip = info.get("remote_ip", "Unknown")
                client_list.append({
                    "device_id": device_id,
                    "ip": info.get("ip", "Unknown"),
                    "local_ip": info.get("ip", "Unknown"),
                    "internet_ip": remote_ip,
                    "remote_ip": remote_ip,
                    "network": classify_network(remote_ip),
                    "last_seen": info.get("last_seen", "")
                })
            await self.master_ws.send(json.dumps({"action": "update_list", "clients": client_list}))

    async def handler(self, websocket):
        remote_ip = websocket.remote_address[0] if websocket.remote_address else "Unknown"
        try:
            async for message in websocket:
                data = json.loads(message)
                action = data.get("action")
                seen_id = data.get("device_id")
                if seen_id in self.clients:
                    self.clients[seen_id]["last_seen"] = time.strftime("%H:%M:%S")
                    if seen_id in self.device_states:
                        self.device_states[seen_id]["last_seen"] = time.strftime("%H:%M:%S")

                if action == "register_client":
                    device_id = data["device_id"]
                    ip = data["ip"]
                    
                    # [CẬP NHẬT]: Ghi nhớ IP thật sự mà Client dùng để kết nối vào Master
                    network_type = classify_network(remote_ip)
                    self.clients[device_id] = {
                        "ip": ip,
                        "remote_ip": remote_ip,
                        "ws": websocket,
                        "last_seen": time.strftime("%H:%M:%S")
                    }
                    self.device_locations[device_id] = {"lat": 0.0, "lng": 0.0, "speed": 0.0, "last_seen": time.strftime("%H:%M:%S")}
                    
                    self.device_states[device_id] = {
                        "ip": ip,
                        "remote_ip": remote_ip,
                        "status": "San sang",
                        "hw": "Dang quet...",
                        "battery": "--",
                        "network": network_type,
                        "signal": "--",
                        "cpu_temp": "--",
                        "device_name": data.get("device_name", device_id),
                        "last_seen": time.strftime("%H:%M:%S")
                    }
                    self.device_telemetry[device_id] = dict(self.device_states[device_id])
                    self.htop_signal.emit(self.device_states)

                    self.log(f"[+] CLIENT DANG KY: {device_id} (Gốc: {remote_ip})")
                    await self.send_client_list()
                    
                    # Phát tín hiệu kiểm tra Auto-Resume
                    self.client_connected_signal.emit(device_id)

                elif action == "register_master":
                    self.master_ws = websocket
                    self.log("[+] MASTER DANG KY: Ung dung chinh da san sang.")
                    self.log(f"[*] SMART ROUTING SẴN SÀNG - LAN: {MASTER_LAN_IP} | VPN: {MASTER_VPN_IP}")
                    await self.send_client_list()

                elif action == "get_client_list":
                    await self.send_client_list()

                elif action == "request_connect":
                    target_id = data["target_device_id"]
                    vid_port = data.get("video_port", 5000)
                    aud_port = data.get("audio_port", 5001)

                    if target_id in self.clients:
                        # [CẬP NHẬT]: ĐỊNH TUYẾN THÔNG MINH (SMART ROUTING)
                        client_remote_ip = self.clients[target_id]["remote_ip"]
                        
                        if client_remote_ip.startswith("192.168.") or client_remote_ip.startswith("10.") or client_remote_ip.startswith("172."):
                            chosen_master_ip = MASTER_LAN_IP
                            net_type = "LAN (Wi-Fi Nội bộ)"
                        else:
                            chosen_master_ip = MASTER_VPN_IP
                            net_type = "VPN (Tailscale 5G)"

                        self.log(f"[>>>] Yeu cau {target_id} phat stream qua {net_type} -> {chosen_master_ip}")
                        self.device_states[target_id]["status"] = "Dang phat"
                        self.htop_signal.emit(self.device_states)

                        await self.clients[target_id]["ws"].send(json.dumps({
                            "action": "start_stream",
                            "master_ip": chosen_master_ip,
                            "video_port": vid_port,
                            "audio_port": aud_port
                        }))

                elif action == "stop_stream":
                    target_id = data.get("target_device_id")
                    if target_id and target_id in self.clients:
                        self.log(f"[XXX] Yeu cau {target_id} DUNG phat stream")
                        self.device_states[target_id]["status"] = "San sang"
                        self.htop_signal.emit(self.device_states)

                        await self.clients[target_id]["ws"].send(json.dumps({
                            "action": "stop_stream"
                        }))
                
                elif action == "client_log":
                    dev_id = data.get("device_id")
                    msg = data.get("message", "")
                    self.log(msg)
                    if dev_id in self.device_states:
                        hw_status = msg.split("->")[-1].strip() if "->" in msg else msg
                        self.device_states[dev_id]["hw"] = hw_status
                        self.htop_signal.emit(self.device_states)

                elif action == "error_alert":
                    dev_id = data.get("device_id")
                    err = data.get("error", "")
                    self.log(f"[CẢNH BÁO LỖI] {dev_id}: {err}")
                    if dev_id in self.device_states:
                        self.device_states[dev_id]["status"] = "Doi thiet bi"
                        self.htop_signal.emit(self.device_states)

                elif action == "telemetry_update":
                    dev_id = data.get("device_id")
                    if dev_id:
                        telemetry = {
                            "ip": self.device_states.get(dev_id, {}).get("ip", data.get("ip", "Unknown")),
                            "remote_ip": self.device_states.get(dev_id, {}).get("remote_ip", remote_ip),
                            "status": data.get("status", self.device_states.get(dev_id, {}).get("status", "San sang")),
                            "hw": data.get("hw", self.device_states.get(dev_id, {}).get("hw", "OK")),
                            "battery": data.get("battery", data.get("pin", "--")),
                            "network": data.get("network", classify_network(remote_ip)),
                            "signal": data.get("signal", data.get("rssi", "--")),
                            "cpu_temp": data.get("cpu_temp", data.get("temperature", "--")),
                            "device_name": data.get("device_name", dev_id),
                            "last_seen": time.strftime("%H:%M:%S")
                        }
                        if dev_id in self.device_states:
                            self.device_states[dev_id].update(telemetry)
                        else:
                            self.device_states[dev_id] = telemetry
                        self.device_telemetry[dev_id] = dict(self.device_states[dev_id])
                        self.htop_signal.emit(self.device_states)
                        if self.master_ws:
                            await self.master_ws.send(json.dumps({"action": "telemetry_update", "device_id": dev_id, **telemetry}))

                elif action == "cbrn_update":
                    dev_id = data.get("device_id")
                    if dev_id:
                        self.device_cbrn[dev_id] = data
                        if self.master_ws:
                            await self.master_ws.send(json.dumps(data))

                elif action == "gps_update":
                    dev_id = data["device_id"]
                    self.device_locations[dev_id] = {
                        "lat": data["lat"], 
                        "lng": data["lng"], 
                        "speed": data["speed"],
                        "last_seen": time.strftime("%H:%M:%S")
                    }
                    if self.master_ws:
                        await self.master_ws.send(json.dumps(data))

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            self.log(f"[ERR] LOI HE THONG ({remote_ip}): {e}")
        finally:
            if websocket == self.master_ws:
                self.master_ws = None
                self.log("[---] DONG KET NOI: Ung dung Master da ngat.")
            else:
                disconnected_id = None
                for dev_id, info in self.clients.items():
                    if info["ws"] == websocket:
                        disconnected_id = dev_id
                        break
                if disconnected_id:
                    del self.clients[disconnected_id]
                    if disconnected_id in self.device_locations:
                        del self.device_locations[disconnected_id]
                    if disconnected_id in self.device_states:
                        del self.device_states[disconnected_id]
                        self.htop_signal.emit(self.device_states)
                    if disconnected_id in self.device_telemetry:
                        del self.device_telemetry[disconnected_id]

                    self.log(f"[---] DONG KET NOI: Client {disconnected_id} da roi mang.")
                    await self.send_client_list()
                    # Phát tín hiệu dọn dẹp giao diện
                    self.client_disconnected_signal.emit(disconnected_id)

    async def serve_forever(self):
        self.log("="*60)
        self.log("🚀 MÁY CHỦ LOCAL ĐÃ KHỞI ĐỘNG TRÊN CỔNG 8765")
        self.log("="*60)
        async with websockets.serve(self.handler, "0.0.0.0", 8765):
            await asyncio.Future()

    def run(self):
        asyncio.set_event_loop(asyncio.new_event_loop())
        asyncio.run(self.serve_forever())


# --- LUONG MANG WEBSOCKETS (CLIENT) ---
class WebSocketThread(QThread):
    update_clients_signal = pyqtSignal(list)
    gps_update_signal = pyqtSignal(dict)
    telemetry_update_signal = pyqtSignal(dict)
    cbrn_update_signal = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.ws = None

    def run(self):
        def on_message(ws, message):
            data = json.loads(message)
            action = data.get("action")
            if action == "update_list": 
                self.update_clients_signal.emit(data.get("clients", []))
            elif action == "gps_update":
                self.gps_update_signal.emit(data)
            elif action == "telemetry_update":
                self.telemetry_update_signal.emit(data)
            elif action == "cbrn_update":
                self.cbrn_update_signal.emit(data)
                
        def on_open(ws): ws.send(json.dumps({"action": "register_master"}))
        
        while True:
            self.ws = websocket.WebSocketApp(VPS_URL, on_open=on_open, on_message=on_message)
            self.ws.run_forever()
            self.sleep(3)

    def send_command(self, action, target_id, v_port=5000, a_port=5001):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            self.ws.send(json.dumps({
                "action": action, "target_device_id": target_id, 
                "video_port": v_port, "audio_port": a_port # Không cần gửi IP nữa, Server tự lo
            }))
            return True
        return False

    def send_stop_command(self, target_id):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            self.ws.send(json.dumps({
                "action": "stop_stream",
                "target_device_id": target_id
            }))
            return True
        return False

    def request_client_list(self):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            self.ws.send(json.dumps({"action": "get_client_list"}))
            return True
        return False

# --- WIDGET BAN DO GPS 2D ---
class GpsMapWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.master_pos = {"lat": 21.028511, "lng": 105.854165} 
        self.clients = {} 
        self.trails = {}
        self.client_order = []
        self.cbrn_alarm_devices = set()
        self.blink_on = True
        self.scale = 8000
        self.setMinimumHeight(420)
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.toggle_blink)
        self.blink_timer.start(500)
        threading.Thread(target=self.fetch_master_gps, daemon=True).start()

    def toggle_blink(self):
        self.blink_on = not self.blink_on
        if self.cbrn_alarm_devices:
            self.update()

    def fetch_master_gps(self):
        try:
            req = urllib.request.Request("http://ip-api.com/json/")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                if "lat" in data and "lon" in data:
                    self.master_pos = {"lat": data["lat"], "lng": data["lon"]}
                    self.update()
        except Exception: pass

    def update_gps_data(self, data):
        dev_id = data["device_id"]
        if dev_id not in self.client_order:
            self.client_order.append(dev_id)
        lat = float(data.get("lat", 0.0))
        lng = float(data.get("lng", 0.0))
        self.clients[dev_id] = {
            "lat": lat,
            "lng": lng,
            "speed": data.get("speed", 0),
            "heading": data.get("heading", "--"),
            "last_seen": data.get("last_seen", time.strftime("%H:%M:%S"))
        }
        if lat != 0.0 or lng != 0.0:
            trail = self.trails.setdefault(dev_id, [])
            trail.append((lat, lng))
            if len(trail) > 100:
                del trail[:-100]
        self.update()

    def set_cbrn_alarm(self, device_id, is_alarm):
        if is_alarm:
            self.cbrn_alarm_devices.add(device_id)
        else:
            self.cbrn_alarm_devices.discard(device_id)
        self.update()

    def fit_to_all(self):
        points = [(self.master_pos["lat"], self.master_pos["lng"])]
        for data in self.clients.values():
            if data.get("lat") != 0.0 or data.get("lng") != 0.0:
                points.append((data["lat"], data["lng"]))
        if len(points) <= 1:
            self.scale = 8000
            self.update()
            return
        max_lat_delta = max(abs(lat - self.master_pos["lat"]) for lat, _ in points)
        max_lng_delta = max(abs(lng - self.master_pos["lng"]) for _, lng in points)
        if max_lat_delta == 0 and max_lng_delta == 0:
            self.scale = 8000
        else:
            usable_w = max(100, self.width() * 0.38)
            usable_h = max(100, self.height() * 0.38)
            scale_lat = usable_h / max(max_lat_delta, 0.00001)
            scale_lng = usable_w / max(max_lng_delta, 0.00001)
            self.scale = int(max(1000, min(180000, min(scale_lat, scale_lng))))
        self.update()

    def download_map_area(self):
        self.fetch_master_gps()
        QMessageBox.information(self, "Tai ban do", "Da cap nhat toa do AGPS Master. Nguon tile offline/API co the cau hinh them khi co goi ban do hop le.")

    def client_color(self, device_id):
        if device_id not in self.client_order:
            self.client_order.append(device_id)
        return QColor(CLIENT_COLORS[self.client_order.index(device_id) % len(CLIENT_COLORS)])

    def to_screen(self, lat, lng):
        cx, cy = self.width() // 2, self.height() // 2
        dx = (lng - self.master_pos["lng"]) * self.scale
        dy = (self.master_pos["lat"] - lat) * self.scale
        return cx + int(dx), cy - int(dy)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(15, 20, 25))
        painter.setPen(QPen(QColor(40, 50, 60), 1, Qt.DashLine))
        for i in range(0, w, 50): painter.drawLine(i, 0, i, h)
        for i in range(0, h, 50): painter.drawLine(0, i, w, i)
        cx, cy = w // 2, h // 2
        painter.setPen(QPen(QColor(60, 80, 100), 2))
        painter.drawLine(cx, 0, cx, h)
        painter.drawLine(0, cy, w, cy)

        painter.setBrush(QBrush(QColor(220, 30, 30)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(cx - 9, cy - 9, 18, 18)
        painter.setPen(QPen(Qt.white))
        painter.setFont(QFont("Arial", 10, QFont.Bold))
        painter.drawText(cx + 15, cy + 5, "TRUNG TÂM CHỈ HUY (MASTER)")
        painter.setPen(QPen(QColor(170, 170, 170)))
        painter.setFont(QFont("Arial", 8))
        painter.drawText(cx + 15, cy + 20, f"GPS: {self.master_pos['lat']:.6f}, {self.master_pos['lng']:.6f}")
        painter.drawText(12, 22, f"Offline tactical map | Scale: {self.scale}")

        for cid, data in self.clients.items():
            if data["lat"] == 0.0 and data["lng"] == 0.0: continue
            color = self.client_color(cid)
            trail = self.trails.get(cid, [])
            if len(trail) > 1:
                painter.setPen(QPen(color, 2))
                for idx in range(1, len(trail)):
                    x1, y1 = self.to_screen(trail[idx - 1][0], trail[idx - 1][1])
                    x2, y2 = self.to_screen(trail[idx][0], trail[idx][1])
                    painter.drawLine(x1, y1, x2, y2)

            px, py = self.to_screen(data["lat"], data["lng"])
            has_alarm = cid in self.cbrn_alarm_devices
            if has_alarm and self.blink_on:
                painter.setBrush(QBrush(QColor(220, 30, 30)))
                painter.setPen(QPen(QColor(255, 255, 255), 2))
                painter.drawEllipse(px - 15, py - 15, 30, 30)
                painter.setPen(QPen(Qt.white))
                painter.setFont(QFont("Arial", 16, QFont.Bold))
                painter.drawText(px - 9, py + 7, "\u2622")
            else:
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.NoPen)
                painter.drawRect(px - 8, py - 8, 16, 16)
            painter.setPen(QPen(QColor(241, 196, 15))) 
            painter.setFont(QFont("Arial", 9, QFont.Bold))
            painter.drawText(px + 12, py, f"{cid}")
            painter.setPen(QPen(QColor(189, 195, 199)))
            painter.drawText(px + 12, py + 15, f"{data['speed']} km/h | {data.get('last_seen', '--')}")


class CBRNSensorCell(QFrame):
    def __init__(self, slot_index, sensor_name):
        super().__init__()
        self.slot_index = slot_index
        self.sensor_name = sensor_name
        self.device_id = None
        self.payload = {
            "status": "Mat ket noi",
            "agent": "",
            "concentration": "--",
            "unit": "",
            "level": 0
        }

        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumHeight(92)
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 6, 8, 6)

        self.lbl_title = QLabel(f"Client {slot_index + 1} | {sensor_name}")
        self.lbl_title.setStyleSheet("font-weight: bold; color: #f2f2f2;")
        self.lbl_status = QLabel("Trang thai: Mat ket noi")
        self.lbl_agent = QLabel("Tac nhan: --")
        self.lbl_value = QLabel("Nong do: --")
        for label in [self.lbl_status, self.lbl_agent, self.lbl_value]:
            label.setStyleSheet("color: #dddddd;")
            label.setWordWrap(True)

        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 8)
        self.level_bar.setFormat("LEVEL %v/8")
        self.level_bar.setTextVisible(True)

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_status)
        layout.addWidget(self.lbl_agent)
        layout.addWidget(self.lbl_value)
        layout.addWidget(self.level_bar)
        self.setLayout(layout)
        self.apply_visual(False, False, False)

    def set_device_label(self, device_id, note=""):
        self.device_id = device_id
        if device_id:
            suffix = f" - {note}" if note else ""
            self.lbl_title.setText(f"{device_id}{suffix} | {self.sensor_name}")
        else:
            self.lbl_title.setText(f"Client {self.slot_index + 1} | {self.sensor_name}")

    def update_payload(self, payload, blink_on=False, acknowledged=False):
        self.payload = dict(payload)
        status = self.payload.get("status", "OK")
        agent = self.payload.get("agent") or "--"
        concentration = self.payload.get("concentration", "--")
        unit = self.payload.get("unit", "")
        level = normalize_level(self.payload.get("level", 0))

        self.lbl_status.setText(f"Trang thai: {status}")
        self.lbl_agent.setText(f"Tac nhan: {agent}")
        self.lbl_value.setText(f"Nong do: {concentration} {unit}".strip())
        self.level_bar.setValue(level)
        self.apply_visual(is_alarm_status(status), is_error_status(status), blink_on and not acknowledged)

    def apply_visual(self, alarm, error, blink_on):
        if alarm:
            bg = "#b71c1c" if blink_on else "#5d1515"
            border = "#ffdddd"
            bar = "#ff5252"
        elif error:
            bg = "#4d3a11"
            border = "#f39c12"
            bar = "#f39c12"
        else:
            bg = "#17251d"
            border = "#2ecc71"
            bar = "#2ecc71"
        self.setStyleSheet(f"""
            QFrame {{ background-color: {bg}; border: 1px solid {border}; border-radius: 6px; }}
            QProgressBar {{ color: white; border: 1px solid #555; border-radius: 3px; text-align: center; }}
            QProgressBar::chunk {{ background-color: {bar}; }}
        """)


class CBRNPanel(QWidget):
    alarm_signal = pyqtSignal(str, str)
    device_alarm_state_changed = pyqtSignal(str, bool)
    history_changed_signal = pyqtSignal()

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.device_order = []
        self.cells = {}
        self.sensor_payloads = {}
        self.active_alarms = set()
        self.device_alerts = {}
        self.blink_on = True
        self.collapsed = False

        root = QVBoxLayout()
        root.setContentsMargins(6, 4, 6, 6)

        header = QHBoxLayout()
        title = QLabel("CBRN SENSOR PANEL")
        title.setStyleSheet("font-weight: bold; color: #ffffff;")
        self.btn_ack = QPushButton("Xac nhan da xem")
        self.btn_export = QPushButton("Xuat bao cao")
        self.btn_collapse = QPushButton("Thu gon")
        self.btn_ack.clicked.connect(self.acknowledge_all)
        self.btn_export.clicked.connect(self.export_report)
        self.btn_collapse.clicked.connect(self.toggle_collapse)

        self.dt_from = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-3600))
        self.dt_from.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_from.setCalendarPopup(True)
        self.dt_to = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_to.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_to.setCalendarPopup(True)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("Tu"))
        header.addWidget(self.dt_from)
        header.addWidget(QLabel("Den"))
        header.addWidget(self.dt_to)
        header.addWidget(self.btn_ack)
        header.addWidget(self.btn_export)
        header.addWidget(self.btn_collapse)
        root.addLayout(header)

        self.grid_container = QWidget()
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        for col in range(3):
            for row, sensor in enumerate(CBRN_SENSORS):
                cell = CBRNSensorCell(col, sensor)
                self.cells[(col, sensor)] = cell
                grid.addWidget(cell, row, col)
        self.grid_container.setLayout(grid)
        root.addWidget(self.grid_container)
        self.setLayout(root)
        self.setStyleSheet("background-color: #111820;")

        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.update_blink)
        self.blink_timer.start(500)

        self.sound_timer = QTimer(self)
        self.sound_timer.timeout.connect(self.play_alarm_sound)

    def set_devices(self, clients, notes):
        visible_ids = [client.get("device_id") for client in clients if client.get("device_id")]
        kept = [device_id for device_id in self.device_order if device_id in visible_ids]
        for device_id in visible_ids:
            if device_id not in kept and len(kept) < 3:
                kept.append(device_id)
        self.device_order = kept[:3]

        for col in range(3):
            device_id = self.device_order[col] if col < len(self.device_order) else None
            note = notes.get(device_id, "") if device_id else ""
            for sensor in CBRN_SENSORS:
                self.cells[(col, sensor)].set_device_label(device_id, note)

    def slot_for_device(self, device_id):
        if device_id in self.device_order:
            return self.device_order.index(device_id)
        if len(self.device_order) < 3:
            self.device_order.append(device_id)
            for sensor in CBRN_SENSORS:
                self.cells[(len(self.device_order) - 1, sensor)].set_device_label(device_id)
            return len(self.device_order) - 1
        return None

    def handle_update(self, payload):
        updates = payload.get("sensors")
        if isinstance(updates, list):
            for sensor_payload in updates:
                merged = dict(payload)
                merged.update(sensor_payload)
                merged.pop("sensors", None)
                self.handle_update(merged)
            return

        device_id = payload.get("device_id", "UNKNOWN")
        sensor = payload.get("sensor", payload.get("sensor_name", CBRN_SENSORS[0]))
        if sensor not in CBRN_SENSORS:
            sensor = CBRN_SENSORS[0] if "svg" in str(sensor).lower() else CBRN_SENSORS[-1]
        slot = self.slot_for_device(device_id)
        if slot is None:
            return

        normalized = {
            "timestamp": payload.get("timestamp") or now_ts(),
            "device_id": device_id,
            "sensor": sensor,
            "status": payload.get("status", "OK"),
            "agent": payload.get("agent", payload.get("detected_agent", "")),
            "concentration": payload.get("concentration", payload.get("value", "--")),
            "unit": payload.get("unit", "ppm"),
            "level": normalize_level(payload.get("level", payload.get("severity", 0)))
        }
        self.db.log_measurement(normalized)
        key = (device_id, sensor)
        self.sensor_payloads[key] = normalized

        alarm = is_alarm_status(normalized["status"])
        self.device_alerts[key] = alarm
        if alarm:
            was_new = key not in self.active_alarms
            self.active_alarms.add(key)
            if was_new:
                self.alarm_signal.emit(device_id, sensor)
                self.play_alarm_sound()
            if not self.sound_timer.isActive():
                self.sound_timer.start(2500)
        else:
            self.active_alarms.discard(key)
            if not self.active_alarms:
                self.sound_timer.stop()

        self.cells[(slot, sensor)].update_payload(normalized, blink_on=self.blink_on, acknowledged=key not in self.active_alarms)
        self.device_alarm_state_changed.emit(device_id, self.device_has_alarm(device_id))
        self.history_changed_signal.emit()

    def device_has_alarm(self, device_id):
        return any(active for (dev_id, _), active in self.device_alerts.items() if dev_id == device_id)

    def update_blink(self):
        self.blink_on = not self.blink_on
        for key in list(self.sensor_payloads.keys()):
            device_id, sensor = key
            slot = self.slot_for_device(device_id)
            if slot is not None:
                self.cells[(slot, sensor)].update_payload(
                    self.sensor_payloads[key],
                    blink_on=self.blink_on,
                    acknowledged=key not in self.active_alarms
                )

    def play_alarm_sound(self):
        if winsound and self.active_alarms:
            try:
                winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass

    def acknowledge_all(self):
        self.active_alarms.clear()
        self.sound_timer.stop()
        if winsound:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        self.db.acknowledge_all()
        self.update_blink()
        self.history_changed_signal.emit()

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        self.grid_container.setVisible(not self.collapsed)
        self.btn_collapse.setText("Mo rong" if self.collapsed else "Thu gon")

    def export_report(self):
        ensure_dir(REPORT_DIR)
        default_path = os.path.join(REPORT_DIR, f"cbrn_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Xuat bao cao CBRN",
            default_path,
            "PDF (*.pdf);;Excel (*.xls);;CSV (*.csv)"
        )
        if not path:
            return
        if not os.path.splitext(path)[1]:
            if "Excel" in selected_filter:
                path += ".xls"
            elif "CSV" in selected_filter:
                path += ".csv"
            else:
                path += ".pdf"
        start_ts = self.dt_from.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        end_ts = self.dt_to.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        count = self.db.export_report(path, start_ts=start_ts, end_ts=end_ts)
        QMessageBox.information(self, "Xuat bao cao", f"Da xuat {count} dong du lieu:\n{path}")


# --- O LUOI HIEU THI VIDEO (CAMERA CELL) ---
class CameraCell(QWidget):
    toggle_maximize_signal = pyqtSignal(object)

    def __init__(self, title_text="Chưa kết nối", cell_id="MASTER"):
        super().__init__()
        self.cell_id = cell_id
        self.current_device_id = None 
        self.stream_process = None
        self.hwnd_child = None
        self.is_video_on = True
        self.is_audio_on = True
        self.is_maximized = False
        
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        self.video_frame = QWidget()
        self.video_frame.setAttribute(Qt.WA_NativeWindow, True)
        self.video_frame.setAttribute(Qt.WA_PaintOnScreen, True)
        self.video_frame.setAttribute(Qt.WA_NoSystemBackground, True)
        self.video_frame.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.video_frame.setStyleSheet("background-color: #050505; border: 2px solid #333; border-radius: 5px;")
        layout.addWidget(self.video_frame, stretch=1)

        self.lbl_title = QLabel(title_text)
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setStyleSheet("font-weight: bold; font-size: 13px; margin-top: 5px; color: white;")
        layout.addWidget(self.lbl_title)

        self.lbl_info = QLabel("Pin: -- | Mang: -- | Tin hieu: -- | CPU: --\nThiet bi: -- | Trang thai: Cho ket noi")
        self.lbl_info.setAlignment(Qt.AlignCenter)
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color: #d0d0d0; font-size: 11px;")
        layout.addWidget(self.lbl_info)

        toolbar = QHBoxLayout()
        self.btn_video = QPushButton("📷 Tắt Hình")
        self.btn_video.setStyleSheet("background-color: #3498db; color: white; padding: 5px; border-radius: 3px;")
        self.btn_video.clicked.connect(self.toggle_video)
        self.btn_video.setEnabled(False)
        
        self.btn_audio = QPushButton("🎤 Tắt Tiếng")
        self.btn_audio.setStyleSheet("background-color: #2ecc71; color: white; padding: 5px; border-radius: 3px;")
        self.btn_audio.clicked.connect(self.toggle_audio)
        self.btn_audio.setEnabled(False)
        
        self.btn_maximize = QPushButton("⤢ Phóng To")
        self.btn_maximize.setStyleSheet("background-color: #f39c12; color: white; padding: 5px; border-radius: 3px;")
        self.btn_maximize.clicked.connect(self.toggle_maximize)
        
        self.btn_hangup = QPushButton("❌ Ngắt Kết Nối")
        self.btn_hangup.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 5px; border-radius: 3px;")
        
        toolbar.addWidget(self.btn_video)
        toolbar.addWidget(self.btn_audio)
        toolbar.addWidget(self.btn_maximize)
        toolbar.addWidget(self.btn_hangup)
        layout.addLayout(toolbar) 
        self.setLayout(layout)

    def set_device_info(self, info):
        battery = info.get("battery", info.get("pin", "--"))
        network = info.get("network", "--")
        signal = info.get("signal", "--")
        cpu_temp = info.get("cpu_temp", info.get("temperature", "--"))
        device_name = info.get("device_name", self.current_device_id or "--")
        status = info.get("status", "Cho ket noi")
        self.lbl_info.setText(
            f"Pin: {battery} | Mang: {network} | Tin hieu: {signal} | CPU: {cpu_temp}\n"
            f"Thiet bi: {device_name} | Trang thai: {status}"
        )

    def toggle_maximize(self):
        self.is_maximized = not self.is_maximized
        if self.is_maximized:
            self.btn_maximize.setText("⤡ Thu Nhỏ")
        else:
            self.btn_maximize.setText("⤢ Phóng To")
        self.toggle_maximize_signal.emit(self)

    def start_stream(self, video_port=5000, audio_port=5001):
        self.stop_stream()
        gst_exe = r"C:\Program Files\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe"
        
        if self.cell_id == "MASTER":
            pipeline_cmd = [
                gst_exe, "-v",
                "ksvideosrc", "!", "videoconvert", "!", "d3d11videosink", "sync=false",
                "wasapisrc", "low-latency=true", "!", "audioconvert", "!", "fakesink", "sync=false"
            ]
            self.lbl_title.setText("📹 ĐANG QUAY MASTER (LOCAL)")
            self.btn_hangup.setText("❌ Tắt Camera/Micro")
            self.btn_hangup.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 5px; border-radius: 3px;")
        else:
            pipeline_cmd = [
                gst_exe, "-v",
                "udpsrc", f"port={video_port}", "!", "application/x-rtp,media=video,clock-rate=90000,encoding-name=H265,payload=96", "!",
                "rtpjitterbuffer", "latency=10", "!",
                "rtph265depay", "!", "avdec_h265", "!", "d3d11videosink", "sync=false",
                "udpsrc", f"port={audio_port}", "!", "application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS,payload=97", "!",
                "rtpjitterbuffer", "latency=10", "!",
                "rtpopusdepay", "!", "opusdec", "!", "audioconvert", "!", "audioresample", "!",
                "wasapisink", "low-latency=true", "sync=false"
            ]
        
        self.stream_process = subprocess.Popen(pipeline_cmd, shell=False)
        self.lbl_title.setStyleSheet("color: #27ae60; font-weight: bold; font-size: 13px;")
        self.btn_video.setEnabled(True)
        self.btn_audio.setEnabled(True)
        threading.Thread(target=self.embed_window, args=(self.stream_process.pid,), daemon=True).start()

    def embed_window(self, pid):
        hwnd = None
        for _ in range(100):
            hwnd = find_window_by_pid(pid)
            if hwnd: break
            time.sleep(0.1)

        if hwnd:
            self.hwnd_child = hwnd
            hwnd_parent = int(self.video_frame.winId())
            WS_CHILD = 0x40000000
            GWL_STYLE = -16
            style = ctypes.windll.user32.GetWindowLongW(self.hwnd_child, GWL_STYLE)
            style |= WS_CHILD  
            style &= ~0x00C00000
            style &= ~0x00040000
            ctypes.windll.user32.SetWindowLongW(self.hwnd_child, GWL_STYLE, style)
            ctypes.windll.user32.SetParent(self.hwnd_child, hwnd_parent)
            self.update_video_size()

    def update_video_size(self):
        if self.hwnd_child and self.is_video_on:
            w = self.video_frame.width()
            h = self.video_frame.height()
            ctypes.windll.user32.SetWindowPos(self.hwnd_child, 0, 0, 0, w, h, 0x0020 | 0x0004)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_video_size()

    def toggle_video(self):
        if not self.hwnd_child: return
        self.is_video_on = not self.is_video_on
        if self.is_video_on:
            ctypes.windll.user32.ShowWindow(self.hwnd_child, 5)
            self.update_video_size()
            self.btn_video.setText("📷 Tắt Hình")
            self.btn_video.setStyleSheet("background-color: #3498db; color: white; padding: 5px; border-radius: 3px;")
        else:
            ctypes.windll.user32.ShowWindow(self.hwnd_child, 0)
            self.btn_video.setText("📷 Bật Hình")
            self.btn_video.setStyleSheet("background-color: #7f8c8d; color: white; padding: 5px; border-radius: 3px;")

    def toggle_audio(self):
        if not self.stream_process: return
        self.is_audio_on = not self.is_audio_on
        pid = self.stream_process.pid
        for session in AudioUtilities.GetAllSessions():
            if session.Process and session.Process.pid == pid:
                session.SimpleAudioVolume.SetMute(int(not self.is_audio_on), None)
                break
        if self.is_audio_on:
            self.btn_audio.setText("🎤 Tắt Tiếng")
            self.btn_audio.setStyleSheet("background-color: #2ecc71; color: white; padding: 5px; border-radius: 3px;")
        else:
            self.btn_audio.setText("🎤 Bật Tiếng")
            self.btn_audio.setStyleSheet("background-color: #7f8c8d; color: white; padding: 5px; border-radius: 3px;")

    def stop_stream(self):
        if self.stream_process:
            try:
                subprocess.run(f"taskkill /F /T /PID {self.stream_process.pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception: pass
            
            self.stream_process.terminate()
            self.stream_process = None
            self.hwnd_child = None
            
            if self.cell_id == "MASTER":
                self.lbl_title.setText("Màn hình Local (Master)")
                self.btn_hangup.setText("▶ Bật Camera Master")
                self.btn_hangup.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 5px; border-radius: 3px;")
            else:
                self.lbl_title.setText("Đã ngắt kết nối")
                self.set_device_info({"status": "Ngat ket noi"})
                
            self.lbl_title.setStyleSheet("color: #c0392b; font-weight: bold; font-size: 13px;")
            self.btn_video.setEnabled(False)
            self.btn_audio.setEnabled(False)
            self.is_video_on = True
            self.is_audio_on = True
            self.btn_video.setText("📷 Tắt Hình")
            self.btn_video.setStyleSheet("background-color: #3498db; color: white; padding: 5px; border-radius: 3px;")
            self.btn_audio.setText("🎤 Tắt Tiếng")
            self.btn_audio.setStyleSheet("background-color: #2ecc71; color: white; padding: 5px; border-radius: 3px;")
            
            if self.is_maximized:
                self.toggle_maximize()
            self.video_frame.update()


# --- GIAO DIEN CHINH (MAIN WINDOW) ---
class MasterGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hệ thống TT-1PM/TDL-02")
        self.setGeometry(100, 100, 1200, 800)
        
        self.clients = []
        self.notes = self.load_notes()
        self.telemetry_cache = {}
        self.pending_debug_logs = []
        self.current_audio_mode = "Hoi thoai nhom"
        self.cbrn_db = CBRNDatabase()
        ensure_dir(SCREENSHOT_DIR)
        ensure_dir(REPORT_DIR)
        ensure_dir(LOG_DIR)

        # [TÍNH NĂNG MỚI]: Bộ nhớ lưu trữ thiết bị đang xem dở để tự phục hồi
        self.auto_resume_devices = set()

        self.server_thread = LocalSignalingServer()
        self.server_thread.log_signal.connect(self.append_debug_log)
        self.server_thread.htop_signal.connect(self.update_htop_table) 
        
        # [CẬP NHẬT]: Kết nối sự kiện Tự Phục Hồi & Dọn UI
        self.server_thread.client_disconnected_signal.connect(self.handle_client_disconnect)
        self.server_thread.client_connected_signal.connect(self.handle_client_reconnect)
        self.server_thread.start()

        self.tabs = QTabWidget()
        self.cbrn_panel = CBRNPanel(self.cbrn_db)
        self.cbrn_panel.alarm_signal.connect(self.handle_cbrn_alarm)
        self.cbrn_panel.device_alarm_state_changed.connect(self.handle_cbrn_map_alarm)
        self.cbrn_panel.history_changed_signal.connect(self.refresh_cbrn_history)

        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.addWidget(self.tabs)
        self.main_splitter.addWidget(self.cbrn_panel)
        self.main_splitter.setSizes([620, 220])
        self.setCentralWidget(self.main_splitter)
        self.init_tray()

        self.setup_home_tab()
        self.setup_camera_tab()
        self.setup_gps_tab()
        self.setup_cbrn_history_tab()
        self.setup_upper_tab()
        self.setup_debug_tab()

        self.ws_thread = WebSocketThread()
        self.ws_thread.update_clients_signal.connect(self.refresh_table)
        self.ws_thread.gps_update_signal.connect(self.gps_map.update_gps_data)
        self.ws_thread.telemetry_update_signal.connect(self.handle_telemetry_update)
        self.ws_thread.cbrn_update_signal.connect(self.handle_cbrn_update)
        self.ws_thread.start()

    def init_tray(self):
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self)
            self.tray.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxWarning))
            self.tray.setToolTip("TT-1PM/TDL-02 CBRN")
            self.tray.show()

    def load_notes(self):
        if os.path.exists(NOTES_FILE):
            with open(NOTES_FILE, "r", encoding="utf-8") as f: return json.load(f)
        return {}

    def save_notes(self):
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            json.dump(self.notes, f, ensure_ascii=False, indent=4)

    def setup_home_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["STT", "ID Client (MAC)", "IP Noi bo", "IP Internet/5G", "Ghi chu", "Thao tac"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_refresh = QPushButton("Refresh")
        btn_save_note = QPushButton("Luu ghi chu")
        btn_refresh.setShortcut("F5")
        btn_save_note.setShortcut("Ctrl+S")
        btn_refresh.clicked.connect(self.request_refresh_clients)
        btn_save_note.clicked.connect(self.handle_save_notes)
        btn_layout.addWidget(btn_refresh)
        btn_layout.addWidget(btn_save_note)
        layout.addLayout(btn_layout)
        tab.setLayout(layout)
        self.tabs.addTab(tab, "1. Clients")

    def refresh_table(self, client_list):
        self.clients = client_list
        self.table.setRowCount(len(client_list))
        for row, client in enumerate(client_list):
            dev_id = client["device_id"]
            local_ip = client.get("local_ip", client.get("ip", "Unknown"))
            internet_ip = client.get("internet_ip", client.get("remote_ip", "Unknown"))
            self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.table.setItem(row, 1, QTableWidgetItem(dev_id))
            self.table.setItem(row, 2, QTableWidgetItem(local_ip))
            self.table.setItem(row, 3, QTableWidgetItem(internet_ip))
            self.table.setItem(row, 4, QTableWidgetItem(self.notes.get(dev_id, "")))
            
            btn_connect = QPushButton("Bat dau ket noi")
            btn_connect.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; border-radius: 3px;")
            btn_connect.clicked.connect(lambda checked, r=row: self.connect_to_client(r))
            self.table.setCellWidget(row, 5, btn_connect)
        if hasattr(self, "cbrn_panel"):
            self.cbrn_panel.set_devices(client_list, self.notes)

    def handle_save_notes(self):
        for row in range(self.table.rowCount()):
            dev_id = self.table.item(row, 1).text()
            self.notes[dev_id] = self.table.item(row, 4).text()
        self.save_notes()
        if hasattr(self, "cbrn_panel"):
            self.cbrn_panel.set_devices(self.clients, self.notes)
        QMessageBox.information(self, "Thành công", "Đã lưu toàn bộ ghi chú.")

    def request_refresh_clients(self):
        if hasattr(self, "ws_thread") and self.ws_thread.request_client_list():
            self.append_debug_log(f"[{time.strftime('%H:%M:%S')}] REFRESH danh sach client")
        else:
            self.refresh_table(self.clients)

    def connect_to_client(self, row):
        dev_id = self.clients[row]["device_id"]
        
        # Thêm ID vào trí nhớ để Tự phục hồi
        self.auto_resume_devices.add(dev_id)

        empty_slot = -1
        # Ưu tiên ghi đè lên chính ô cũ của nó nếu có
        for i, cell in enumerate(self.cell_clients):
            if cell.current_device_id == dev_id:
                empty_slot = i
                break
        
        # Nếu chưa có, tìm ô hoàn toàn trống
        if empty_slot == -1:
            for i, cell in enumerate(self.cell_clients):
                if cell.stream_process is None and cell.current_device_id is None:
                    empty_slot = i
                    break
                    
        # Nếu vẫn không có, tìm ô đang dừng phát
        if empty_slot == -1:
            for i, cell in enumerate(self.cell_clients):
                if cell.stream_process is None:
                    # Đẩy thiết bị cũ ra khỏi trí nhớ vì ô này bị chiếm mất rồi
                    if cell.current_device_id:
                        self.auto_resume_devices.discard(cell.current_device_id)
                    empty_slot = i
                    break

        if empty_slot == -1:
            QMessageBox.warning(self, "Quá tải", "Đã hiển thị tối đa 3 Client. Vui lòng ngắt bớt một luồng để xem tiếp.")
            return

        v_port, a_port = 5000 + (empty_slot * 2), 5001 + (empty_slot * 2)
        if self.ws_thread.send_command("request_connect", dev_id, v_port, a_port):
            self.tabs.setCurrentIndex(1)
            
            self.cell_clients[empty_slot].current_device_id = dev_id
            self.cell_clients[empty_slot].lbl_title.setText(f"Live: {dev_id} - {self.notes.get(dev_id, '')}")
            self.cell_clients[empty_slot].start_stream(video_port=v_port, audio_port=a_port)
            self.cell_clients[empty_slot].set_device_info(self.telemetry_cache.get(dev_id, {
                "device_name": dev_id,
                "status": "Dang ket noi",
                "network": self.clients[row].get("network", "--")
            }))
        else:
            QMessageBox.warning(self, "Lỗi", "Mất kết nối tới máy chủ (Local)!")

    # [TÍNH NĂNG MỚI]: Dọn UI tức thì khi rớt mạng
    def handle_client_disconnect(self, dev_id):
        for cell in self.cell_clients:
            if cell.current_device_id == dev_id:
                cell.stop_stream()
                cell.lbl_title.setText(f"Mất mạng: {dev_id} (Đang đợi phục hồi...)")
                cell.lbl_title.setStyleSheet("color: #f39c12; font-weight: bold; font-size: 13px; margin-top: 5px;")
                cell.set_device_info({**self.telemetry_cache.get(dev_id, {}), "status": "Dang cho ket noi lai"})
                # Lưu ý: Không đặt cell.current_device_id = None để giữ chỗ cho nó quay lại.

    # [TÍNH NĂNG MỚI]: Auto-Resume khi mạng 4G/WiFi thông lại
    def handle_client_reconnect(self, dev_id):
        if dev_id in self.auto_resume_devices:
            for i, cell in enumerate(self.cell_clients):
                if cell.current_device_id == dev_id:
                    v_port, a_port = 5000 + (i * 2), 5001 + (i * 2)
                    cell.lbl_title.setText(f"Live (Auto-Resume): {dev_id} - {self.notes.get(dev_id, '')}")
                    # Gửi lệnh yêu cầu phát stream xuống Rock5T
                    self.ws_thread.send_command("request_connect", dev_id, v_port, a_port)
                    cell.start_stream(video_port=v_port, audio_port=a_port)
                    cell.set_device_info({**self.telemetry_cache.get(dev_id, {}), "status": "Dang ket noi"})
                    break

    def setup_camera_tab(self):
        tab = QWidget()
        self.camera_tab = tab
        root_layout = QVBoxLayout()

        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Che do lien lac:"))
        self.audio_mode_group = QButtonGroup(self)
        self.audio_mode_group.setExclusive(True)
        modes = [
            "Hoi thoai nhom",
            "Broadcast",
            "Rieng Client 1",
            "Rieng Client 2",
            "Rieng Client 3",
            "Tat mic chi huy"
        ]
        for idx, mode in enumerate(modes):
            btn = QPushButton(mode)
            btn.setCheckable(True)
            if idx == 0:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, m=mode: self.set_audio_mode(m))
            self.audio_mode_group.addButton(btn, idx)
            mode_layout.addWidget(btn)
        btn_screenshot = QPushButton("Chup man hinh")
        btn_screenshot.setShortcut("F12")
        btn_screenshot.clicked.connect(self.capture_video_call)
        mode_layout.addWidget(btn_screenshot)
        root_layout.addLayout(mode_layout)

        layout = QGridLayout()
        
        self.cell_master = CameraCell("Màn hình Local (Master)", cell_id="MASTER")
        self.cell_master.toggle_maximize_signal.connect(self.handle_maximize_cell)
        self.cell_master.set_device_info({
            "battery": "AC",
            "network": f"LAN {MASTER_LAN_IP}",
            "signal": "PC",
            "cpu_temp": "--",
            "device_name": "MASTER",
            "status": "San sang"
        })
        
        self.cell_master.btn_hangup.setText("▶ Bật Camera Master")
        self.cell_master.btn_hangup.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 5px; border-radius: 3px;")
        
        def toggle_master_cam():
            if self.cell_master.stream_process is None:
                self.cell_master.start_stream()
            else:
                self.cell_master.stop_stream()
                
        self.cell_master.btn_hangup.clicked.connect(toggle_master_cam)
        layout.addWidget(self.cell_master, 0, 0)
        
        self.cell_clients = []
        for i in range(3):
            cell = CameraCell(f"Client {i+1} (Chờ kết nối...)", cell_id=f"CLIENT_{i+1}")
            
            def create_disconnect_handler(c):
                def handler():
                    if c.current_device_id:
                        # [CẬP NHẬT]: Chỉ khi ấn NÚT ĐỎ này, Master mới quên đi trí nhớ Auto-Resume
                        self.auto_resume_devices.discard(c.current_device_id)
                        self.ws_thread.send_stop_command(c.current_device_id)
                        c.current_device_id = None
                        
                    c.stop_stream()
                    c.lbl_title.setText("Chờ kết nối...")
                    c.lbl_title.setStyleSheet("font-weight: bold; font-size: 13px; margin-top: 5px; color: white;")
                return handler

            cell.btn_hangup.clicked.connect(create_disconnect_handler(cell))
            cell.toggle_maximize_signal.connect(self.handle_maximize_cell)
            self.cell_clients.append(cell)
            layout.addWidget(cell, 0 if i == 0 else 1, 1 if i == 0 else (i - 1))
            
        root_layout.addLayout(layout)
        tab.setLayout(root_layout)
        self.tabs.addTab(tab, "2. Video call")

    def handle_maximize_cell(self, target_cell):
        all_cells = [self.cell_master] + self.cell_clients
        if target_cell.is_maximized:
            for cell in all_cells:
                if cell != target_cell:
                    cell.hide()
        else:
            for cell in all_cells:
                cell.show()

    def set_audio_mode(self, mode):
        self.current_audio_mode = mode
        self.append_debug_log(f"[{time.strftime('%H:%M:%S')}] Che do lien lac: {mode}")

    def capture_video_call(self):
        ensure_dir(SCREENSHOT_DIR)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.abspath(os.path.join(SCREENSHOT_DIR, f"video_call_{timestamp}.png"))
        screen = QApplication.primaryScreen()
        if screen and hasattr(self, "camera_tab"):
            top_left = self.camera_tab.mapToGlobal(self.camera_tab.rect().topLeft())
            pixmap = screen.grabWindow(
                self.winId(),
                top_left.x() - self.frameGeometry().x(),
                top_left.y() - self.frameGeometry().y(),
                self.camera_tab.width(),
                self.camera_tab.height()
            )
        else:
            pixmap = self.grab()
        if pixmap.save(path, "PNG"):
            self.append_debug_log(f"[{time.strftime('%H:%M:%S')}] Da chup man hinh: {path}")
            QMessageBox.information(self, "Chup man hinh", f"Da luu:\n{path}")
        else:
            QMessageBox.warning(self, "Chup man hinh", "Khong luu duoc anh chup man hinh.")

    def setup_gps_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        btn_download = QPushButton("Tai ban do")
        btn_center = QPushButton("Ve trung tam")
        btn_download.clicked.connect(lambda: self.gps_map.download_map_area())
        btn_center.clicked.connect(lambda: self.gps_map.fit_to_all())
        toolbar.addWidget(btn_download)
        toolbar.addWidget(btn_center)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.gps_map = GpsMapWidget()
        layout.addWidget(self.gps_map)
        tab.setLayout(layout)
        self.tabs.addTab(tab, "3. Ban do chien thuat")

    def setup_cbrn_history_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()

        filters = QHBoxLayout()
        self.history_dt_from = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-3600))
        self.history_dt_from.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.history_dt_from.setCalendarPopup(True)
        self.history_dt_to = QDateTimeEdit(QDateTime.currentDateTime())
        self.history_dt_to.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.history_dt_to.setCalendarPopup(True)
        btn_refresh = QPushButton("Tai timeline")
        btn_export = QPushButton("Xuat PDF/Excel")
        btn_refresh.clicked.connect(self.refresh_cbrn_history)
        btn_export.clicked.connect(self.export_cbrn_history)
        filters.addWidget(QLabel("Tu"))
        filters.addWidget(self.history_dt_from)
        filters.addWidget(QLabel("Den"))
        filters.addWidget(self.history_dt_to)
        filters.addWidget(btn_refresh)
        filters.addWidget(btn_export)
        filters.addStretch()
        layout.addLayout(filters)

        self.cbrn_history_table = QTableWidget(0, 9)
        self.cbrn_history_table.setHorizontalHeaderLabels([
            "Thoi gian", "Client", "Cam bien", "Trang thai", "Tac nhan",
            "Nong do", "Don vi", "Level", "Da xac nhan"
        ])
        self.cbrn_history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.cbrn_history_table)
        tab.setLayout(layout)
        self.tabs.addTab(tab, "4. CBRN timeline")
        self.refresh_cbrn_history()

    def refresh_cbrn_history(self):
        if not hasattr(self, "cbrn_history_table"):
            return
        start_ts = self.history_dt_from.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        end_ts = self.history_dt_to.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        rows = self.cbrn_db.fetch_measurements(start_ts=start_ts, end_ts=end_ts, limit=1000)
        self.cbrn_history_table.setRowCount(len(rows))
        for row_idx, row_data in enumerate(rows):
            for col_idx, value in enumerate(row_data):
                self.cbrn_history_table.setItem(row_idx, col_idx, QTableWidgetItem(str(value if value is not None else "")))

    def export_cbrn_history(self):
        ensure_dir(REPORT_DIR)
        default_path = os.path.join(REPORT_DIR, f"cbrn_timeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Xuat timeline CBRN",
            default_path,
            "PDF (*.pdf);;Excel (*.xls);;CSV (*.csv)"
        )
        if not path:
            return
        if not os.path.splitext(path)[1]:
            if "Excel" in selected_filter:
                path += ".xls"
            elif "CSV" in selected_filter:
                path += ".csv"
            else:
                path += ".pdf"
        start_ts = self.history_dt_from.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        end_ts = self.history_dt_to.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        count = self.cbrn_db.export_report(path, start_ts=start_ts, end_ts=end_ts)
        QMessageBox.information(self, "Xuat timeline", f"Da xuat {count} dong du lieu:\n{path}")

    def setup_upper_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()

        info_group = QGroupBox("Thong tin xe chi huy")
        info_layout = QFormLayout()
        self.upper_gps_label = QLabel("--")
        self.upper_network_label = QLabel(f"LAN: {MASTER_LAN_IP} | VPN/5G: {MASTER_VPN_IP}")
        self.upper_speed_label = QLabel("--")
        self.upper_heading_label = QLabel("--")
        info_layout.addRow("Toa do GPS", self.upper_gps_label)
        info_layout.addRow("Loai mang", self.upper_network_label)
        info_layout.addRow("Toc do", self.upper_speed_label)
        info_layout.addRow("Huong", self.upper_heading_label)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        self.upper_mini_map = GpsMapWidget()
        self.upper_mini_map.setMaximumHeight(220)
        layout.addWidget(self.upper_mini_map)

        call_layout = QHBoxLayout()
        self.upper_master_cell = CameraCell("Camera Master", cell_id="MASTER")
        self.upper_remote_cell = CameraCell("Video cap tren", cell_id="SUPERIOR")
        self.upper_master_cell.set_device_info({"device_name": "MASTER", "network": "5G/VPN", "status": "San sang"})
        self.upper_remote_cell.set_device_info({"device_name": "CAP TREN", "network": "5G/VPN", "status": "Cho goi"})
        call_layout.addWidget(self.upper_master_cell)
        call_layout.addWidget(self.upper_remote_cell)
        layout.addLayout(call_layout)

        controls = QHBoxLayout()
        self.upper_id_input = QLineEdit()
        self.upper_id_input.setPlaceholderText("Nhap ID cap tren")
        self.upper_call_state = QLabel("Trang thai: Chua goi")
        btn_call = QPushButton("Goi")
        btn_end = QPushButton("Ket thuc")
        btn_call.clicked.connect(self.call_superior)
        btn_end.clicked.connect(self.end_superior_call)
        controls.addWidget(QLabel("ID cap tren"))
        controls.addWidget(self.upper_id_input)
        controls.addWidget(btn_call)
        controls.addWidget(btn_end)
        controls.addWidget(self.upper_call_state)
        layout.addLayout(controls)

        self.upper_timer = QTimer(self)
        self.upper_timer.timeout.connect(self.update_upper_status)
        self.upper_timer.start(1000)
        self.update_upper_status()

        tab.setLayout(layout)
        self.tabs.addTab(tab, "5. Master + Cap tren")

    def update_upper_status(self):
        if not hasattr(self, "upper_gps_label"):
            return
        pos = self.gps_map.master_pos if hasattr(self, "gps_map") else {"lat": 0.0, "lng": 0.0}
        self.upper_gps_label.setText(f"{pos['lat']:.6f}, {pos['lng']:.6f}")
        self.upper_network_label.setText(f"LAN: {MASTER_LAN_IP} | VPN/5G: {MASTER_VPN_IP}")
        self.upper_speed_label.setText("0 km/h")
        self.upper_heading_label.setText("--")
        if hasattr(self, "upper_mini_map"):
            self.upper_mini_map.master_pos = dict(pos)
            self.upper_mini_map.update()

    def call_superior(self):
        superior_id = self.upper_id_input.text().strip()
        if not superior_id:
            QMessageBox.warning(self, "Goi cap tren", "Vui long nhap ID cap tren.")
            return
        self.upper_call_state.setText(f"Trang thai: Dang goi {superior_id}")
        self.upper_remote_cell.set_device_info({"device_name": superior_id, "network": "5G/VPN", "status": "Dang ket noi"})
        self.append_debug_log(f"[{time.strftime('%H:%M:%S')}] Goi cap tren: {superior_id}")

    def end_superior_call(self):
        self.upper_call_state.setText("Trang thai: Da ket thuc")
        self.upper_remote_cell.stop_stream()
        self.upper_remote_cell.set_device_info({"device_name": "CAP TREN", "network": "5G/VPN", "status": "Ngat ket noi"})
        self.append_debug_log(f"[{time.strftime('%H:%M:%S')}] Ket thuc goi cap tren")

    def setup_debug_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()

        toolbar = QHBoxLayout()
        btn_save_log = QPushButton("Luu log phien")
        btn_save_log.clicked.connect(self.save_debug_log)
        toolbar.addWidget(btn_save_log)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.htop_table = QTableWidget(0, 8)
        self.htop_table.setHorizontalHeaderLabels([
            "Device ID", "IP Address", "Trang thai", "Phan cung",
            "Pin", "Mang", "Tin hieu", "CPU/Nhiet"
        ])
        self.htop_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.htop_table.setStyleSheet("background-color: #0c0c0c; color: #ffffff; gridline-color: #333333; font-family: Consolas, monospace; font-size: 14px;")
        self.htop_table.verticalHeader().setVisible(False)
        self.htop_table.horizontalHeader().setStyleSheet("QHeaderView::section { background-color: #1a1a1a; color: white; padding: 6px; font-weight: bold; border: 1px solid #333; }")
        
        self.txt_debug = QTextEdit()
        self.txt_debug.setReadOnly(True)
        self.txt_debug.setStyleSheet("background-color: #050505; color: #ffffff; font-family: Consolas, monospace; font-size: 15px; padding: 10px; border: 1px solid #333;")

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.htop_table)
        splitter.addWidget(self.txt_debug)

        self.error_code_table = QTableWidget(0, 3)
        self.error_code_table.setHorizontalHeaderLabels(["Ma loi", "Y nghia", "Xu ly goi y"])
        self.error_code_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.error_code_table.setRowCount(6)
        error_rows = [
            ("NET-01", "Mat ket noi client", "Kiem tra Wi-Fi/5G/Tailscale va refresh danh sach"),
            ("AV-01", "Thieu camera", "Kiem tra camera USB/driver va cap quyen thiet bi"),
            ("AV-02", "Thieu micro", "Kiem tra input audio/driver Windows hoac client"),
            ("GPS-01", "Khong co toa do", "Kiem tra AGPS/GPS va tin hieu mang"),
            ("CBRN-01", "Canh bao tac nhan", "Xac nhan da xem, ghi nhan vi tri, xuat bao cao"),
            ("DB-01", "Khong ghi duoc SQLite", "Kiem tra quyen ghi thu muc chuong trinh")
        ]
        for row, values in enumerate(error_rows):
            for col, value in enumerate(values):
                self.error_code_table.setItem(row, col, QTableWidgetItem(value))
        splitter.addWidget(self.error_code_table)
        splitter.setSizes([260, 420, 180])
        
        layout.addWidget(splitter)
        tab.setLayout(layout)
        self.tabs.addTab(tab, "6. Debug & Htop")

        for text in self.pending_debug_logs:
            self.txt_debug.append(text)
        self.pending_debug_logs.clear()

    def update_htop_table(self, states_dict):
        if not hasattr(self, "htop_table"):
            return
        self.htop_table.setRowCount(len(states_dict))
        for row, (dev_id, info) in enumerate(states_dict.items()):
            item_id = QTableWidgetItem(dev_id)
            item_ip = QTableWidgetItem(info.get("ip", "Unknown"))
            item_status = QTableWidgetItem(info.get("status", "--"))
            item_hw = QTableWidgetItem(info.get("hw", "--"))
            item_battery = QTableWidgetItem(str(info.get("battery", "--")))
            item_network = QTableWidgetItem(info.get("network", "--"))
            item_signal = QTableWidgetItem(str(info.get("signal", "--")))
            item_cpu = QTableWidgetItem(str(info.get("cpu_temp", "--")))

            status_text = info.get("status", "")
            if "Dang phat" in status_text or "ĐANG PHÁT" in status_text:
                item_status.setForeground(QBrush(QColor("#e74c3c")))
            elif "Doi" in status_text or "Đợi" in status_text:
                item_status.setForeground(QBrush(QColor("#f39c12")))
            else:
                item_status.setForeground(QBrush(QColor("#2ecc71")))

            hw_text = info.get("hw", "")
            if "THIEU" in hw_text.upper() or "THIẾU" in hw_text or "LOI" in hw_text.upper() or "LỖI" in hw_text or "❌" in hw_text:
                item_hw.setForeground(QBrush(QColor("#e74c3c")))
            else:
                item_hw.setForeground(QBrush(QColor("#2ecc71")))

            self.htop_table.setItem(row, 0, item_id)
            self.htop_table.setItem(row, 1, item_ip)
            self.htop_table.setItem(row, 2, item_status)
            self.htop_table.setItem(row, 3, item_hw)
            self.htop_table.setItem(row, 4, item_battery)
            self.htop_table.setItem(row, 5, item_network)
            self.htop_table.setItem(row, 6, item_signal)
            self.htop_table.setItem(row, 7, item_cpu)

    def append_debug_log(self, text):
        if not hasattr(self, "txt_debug"):
            self.pending_debug_logs.append(text)
            return
        self.txt_debug.append(text)
        scrollbar = self.txt_debug.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def save_debug_log(self):
        ensure_dir(LOG_DIR)
        default_path = os.path.abspath(os.path.join(LOG_DIR, f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"))
        path, _ = QFileDialog.getSaveFileName(self, "Luu log phien", default_path, "Log (*.log);;Text (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.txt_debug.toPlainText())
        QMessageBox.information(self, "Luu log", f"Da luu log:\n{path}")

    def handle_telemetry_update(self, data):
        dev_id = data.get("device_id")
        if not dev_id:
            return
        info = {
            "battery": data.get("battery", data.get("pin", "--")),
            "network": data.get("network", "--"),
            "signal": data.get("signal", data.get("rssi", "--")),
            "cpu_temp": data.get("cpu_temp", data.get("temperature", "--")),
            "device_name": data.get("device_name", dev_id),
            "status": data.get("status", "Dang ket noi")
        }
        self.telemetry_cache[dev_id] = info
        if hasattr(self, "cell_clients"):
            for cell in self.cell_clients:
                if cell.current_device_id == dev_id:
                    cell.set_device_info(info)

    def handle_cbrn_update(self, data):
        self.cbrn_panel.handle_update(data)

    def handle_cbrn_alarm(self, device_id, sensor):
        message = f"Canh bao CBRN: {device_id} | {sensor}"
        self.append_debug_log(f"[{time.strftime('%H:%M:%S')}] {message}")
        if self.tray:
            self.tray.showMessage("Canh bao CBRN", message, QSystemTrayIcon.Warning, 5000)

    def handle_cbrn_map_alarm(self, device_id, is_alarm):
        if hasattr(self, "gps_map"):
            self.gps_map.set_cbrn_alarm(device_id, is_alarm)
        if hasattr(self, "upper_mini_map"):
            self.upper_mini_map.set_cbrn_alarm(device_id, is_alarm)

    def setup_system_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        lbl = QLabel("⚙ HỆ THỐNG MỞ RỘNG (Trống)")
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)
        tab.setLayout(layout)
        self.tabs.addTab(tab, "🧩 Hệ Thống")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MasterGUI()
    window.show()
    sys.exit(app.exec_())
