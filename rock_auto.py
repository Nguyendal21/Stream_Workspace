import subprocess
import os
import sys
import re
import uuid
import time
import asyncio
import websockets
import json
import socket
import glob
import math
from datetime import datetime

# Su dung duong dan tuyet doi theo dung yeu cau
CONFIG_FILE = "/home/radxa/stream_workspace/device_config.env"

# Cac khoa cau hinh mo rong co the them vao CONFIG_FILE:
# DEVICE_NAME="Client 1"
# GPS_LAT="21.028511" / GPS_LNG="105.854165"  # fallback khi chua co GPS thật
# ENABLE_IP_AGPS="1"                          # fallback dinh vi IP, do chinh xac thap
# CBRN_SVG2_PORT="/dev/ttyUSB0" / CBRN_SVG2_BAUD="9600"
# CBRN_RAIDM100_PORT="/dev/ttyUSB1" / CBRN_RAIDM100_BAUD="9600"
# CBRN_TEST_ALARM="1"                         # chi dung de test panel Master

# ==============================================================
# [MỚI] CẤU HÌNH DUAL-IP — SỬA 2 DÒNG NÀY CHO PHÙ HỢP
# ==============================================================
# Thứ tự ưu tiên: LAN trước (nhanh hơn), VPN sau (dự phòng 4G/5G)
MASTER_LAN_IP       = "192.168.200.74"   # ← IP tĩnh LAN của máy Master (Windows PC)
MASTER_VPN_IP       = "100.92.168.67"   # ← IP Tailscale của Master (giữ nguyên)
MASTER_IP_PRIORITY  = [MASTER_LAN_IP, MASTER_VPN_IP]

SIGNALING_PORT  = 8765   # Cổng WebSocket của Master (không đổi)
CONNECT_TIMEOUT = 4      # Giây timeout khi thăm dò từng IP
RETRY_DELAY     = 5      # Giây chờ trước khi thử lại toàn bộ danh sách
TELEMETRY_INTERVAL = 2   # Giây gửi pin/mạng/tín hiệu/nhiệt độ
GPS_INTERVAL       = 1   # Giây gửi vị trí GPS/AGPS
CBRN_INTERVAL      = 2   # Giây quét cảm biến CBRN
# ==============================================================

stream_process = None
active_interface = ""
master_requested_streaming = False
current_stream_mode = "none"
current_master_config = {"master_ip": None, "video_port": None, "audio_port": None}
last_gps_position = None

# ==========================================
# MODULE 1: TU DONG CAI DAT THU VIEN
# ==========================================
def check_and_install_dependencies():
    print("[SYS] Dang kiem tra thu vien he thong...")
    required_apt_packages = [
        "v4l-utils", "alsa-utils", "net-tools", "python3-pip", "python3-websockets",
        "gstreamer1.0-tools", "gstreamer1.0-plugins-base", "gstreamer1.0-plugins-good",
        "gstreamer1.0-plugins-bad", "gstreamer1.0-plugins-ugly", "gstreamer1.0-alsa",
        "python3-serial", "gpsd-clients", "modemmanager"
    ]
    missing_packages = []
    for pkg in required_apt_packages:
        result = subprocess.run(f"dpkg -s {pkg}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            missing_packages.append(pkg)
    if missing_packages:
        print(f"[!] Phat hien thieu thu vien: {', '.join(missing_packages)}")
        print("[>] Dang tu dong cai dat (Yeu cau nhap mat khau sudo neu co)...")
        install_cmd = f"sudo apt update && sudo apt install -y {' '.join(missing_packages)}"
        subprocess.run(install_cmd, shell=True)
        print("[+] Da cai dat xong thu vien co ban!")
    else:
        print("[+] He thong da day du thu vien.")

check_and_install_dependencies()

# ==========================================
# CAC HAM TIEN ICH HE THONG
# ==========================================
def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True).strip()
    except:
        return ""

def run_cmd_timeout(cmd, timeout=3):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, timeout=timeout, stderr=subprocess.DEVNULL).strip()
    except:
        return ""

def get_mac_address():
    mac_num = uuid.getnode()
    mac_hex = ':'.join(['{:02x}'.format((mac_num >> elements) & 0xff) for elements in range(0, 2*6, 2)][::-1])
    return mac_hex.replace(':', '').upper()

def get_tailscale_ip():
    output = run_cmd("ip -4 addr show tailscale0")
    match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', output)
    return match.group(1) if match else "Unknown"

# ==========================================
# [MỚI] MODULE DUAL-IP: THĂM DÒ VÀ CHỌN IP TỐT NHẤT
# ==========================================
def is_reachable(ip: str, port: int, timeout: float) -> bool:
    """
    Kiểm tra kết nối TCP tới ip:port trong vòng timeout giây.
    Nhanh hơn ping ICMP và không cần quyền root.
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False

def pick_best_master() -> str | None:
    """
    Duyệt MASTER_IP_PRIORITY theo thứ tự.
    Trả về IP đầu tiên kết nối được, hoặc None nếu tất cả thất bại.
    LAN (192.168.x.x) được thử trước → VPN Tailscale (100.x.x.x) sau.
    """
    for ip in MASTER_IP_PRIORITY:
        label = "LAN" if ip == MASTER_LAN_IP else "VPN Tailscale"
        print(f"[NET] Thu ket noi {label}: {ip}:{SIGNALING_PORT} ...")
        if is_reachable(ip, SIGNALING_PORT, timeout=CONNECT_TIMEOUT):
            print(f"[NET] OK -> Chon {label}: {ip}")
            return ip
        else:
            print(f"[NET] THAT BAI -> Khong den duoc {label}: {ip}")
    return None

def get_local_ip_for(target_ip: str) -> str:
    """
    Trả về IP cục bộ của card mạng đang dùng để đi tới target_ip.
    Dùng để báo cáo chính xác IP lên Master (LAN IP hoặc Tailscale IP).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect((target_ip, 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        # Fallback về Tailscale IP nếu không xác định được
        return get_tailscale_ip()

# ==========================================
# MODULE 2: TU DONG PHAN LUONG MANG (FAILOVER)
# ==========================================
def optimize_network_routes():
    print("\n" + "="*50)
    print(" DANG QUET VA CAU HINH FAILOVER MANG TU DONG ")
    print("="*50)
    try:
        lines = run_cmd("nmcli -t -f TYPE,NAME connection show --active").split('\n')
        wifi_found = False
        cell_found = False
        for line in lines:
            if not line:
                continue
            net_type, net_name = line.split(':', 1)
            if "802-11-wireless" in net_type:
                print(f"[>] Tim thay Wi-Fi: '{net_name}' -> Dat Metric = 100 (UU TIEN 1)")
                run_cmd(f'sudo nmcli connection modify "{net_name}" ipv4.route-metric 100')
                wifi_found = True
            elif net_type in ["gsm", "cdma", "broadband", "802-3-ethernet"]:
                if "tailscale" not in net_name.lower() and "lo" not in net_name.lower():
                    print(f"[>] Tim thay 5G/LAN: '{net_name}' -> Dat Metric = 200 (DU PHONG 2)")
                    run_cmd(f'sudo nmcli connection modify "{net_name}" ipv4.route-metric 200')
                    cell_found = True
        if wifi_found or cell_found:
            print("[*] Dang ap dung luong dinh tuyen (Reloading NetworkManager)...")
            run_cmd("sudo systemctl reload NetworkManager")
            time.sleep(2)
            print("[+] Cau hinh Failover thanh cong!\n")
        else:
            print("[-] Khong tim thay ket noi mang ngoai nao.\n")
    except Exception as e:
        print(f"[-] Loi cau hinh mang: {e}\n")

# ==========================================
# MODULE 3: QUAN LY VA XAC THUC PHAN CUNG
# ==========================================
def setup_devices():
    print("\n[SYS] Dang quet phan cung he thong...")
    raw_video = run_cmd("v4l2-ctl --list-devices")
    cameras = []
    for block in raw_video.split('\n\n'):
        lines = block.strip().split('\n')
        if len(lines) >= 2:
            name = lines[0].strip().replace(':', '')
            path = lines[1].strip()
            cameras.append({"name": name, "display": f"{name} ({path})"})
    raw_audio = run_cmd("arecord -l")
    audios = []
    for line in raw_audio.split('\n'):
        if line.startswith("card"):
            name_match = re.search(r'card \d+: (.*?), device \d+', line)
            hw_match = re.search(r'card (\d+).*?device (\d+)', line)
            if name_match and hw_match:
                audios.append({"name": name_match.group(1).strip(), "display": line.strip()})

    def user_select(devices, dev_type):
        if not devices:
            print(f"Khong tim thay {dev_type} nao. Kiem tra lai cap ket noi!")
            return None
        print(f"\n--- DANH SACH {dev_type.upper()} ---")
        for idx, dev in enumerate(devices, 1):
            print(f"[{idx}] {dev['display']}")
        while True:
            try:
                choice = int(input(f"Nhap so de chon {dev_type}: "))
                if 1 <= choice <= len(devices):
                    return devices[choice - 1]
                print("So khong hop le.")
            except ValueError:
                print("Vui long nhap so nguyen.")
            except EOFError:
                print(f"\n[!] Khong the nhap du lieu (Dang chay ngam). Thoat chuong trinh.")
                sys.exit(1)

    selected_cam = user_select(cameras, "Camera")
    selected_mic = user_select(audios, "Microphone")
    if selected_cam and selected_mic:
        with open(CONFIG_FILE, "w") as f:
            f.write(f'VIDEO_NAME="{selected_cam["name"]}"\n')
            f.write(f'AUDIO_NAME="{selected_mic["name"]}"\n')
        print(f"[+] Da luu cau hinh thiet bi moi vao {CONFIG_FILE}!\n")
    else:
        print("[!] Khong du phan cung. Thoat chuong trinh.")
        sys.exit()

def get_video_path(target_name):
    if not target_name:
        return None
    raw_data = run_cmd("v4l2-ctl --list-devices")
    for block in raw_data.split('\n\n'):
        lines = block.strip().split('\n')
        if len(lines) >= 2 and lines[0].strip().replace(':', '') == target_name:
            return lines[1].strip()
    return None

def get_audio_hw(target_name):
    if not target_name:
        return None
    raw_data = run_cmd("arecord -l")
    for line in raw_data.split('\n'):
        if target_name in line:
            match = re.search(r'card (\d+).*?device (\d+)', line)
            if match:
                return f"hw:{match.group(1)},{match.group(2)}"
    return None

def load_config():
    config = {}
    try:
        with open(CONFIG_FILE, "r") as f:
            for line in f:
                if "=" in line:
                    key, val = line.strip().split("=", 1)
                    config[key] = val.strip('"')
    except Exception as e:
        print(f"[!] Loi doc file cau hinh: {e}")
    return config

def get_config_value(key, default=""):
    return os.environ.get(key) or load_config().get(key, default)

def get_device_name():
    return get_config_value("DEVICE_NAME") or socket.gethostname() or f"ROCK-{get_mac_address()}"

def get_active_interface():
    route_info = run_cmd_timeout("ip route get 8.8.8.8", timeout=2)
    match = re.search(r'dev\s+([^\s]+)', route_info)
    return match.group(1) if match else ""

def get_network_type():
    iface = get_active_interface()
    if not iface:
        return "Khong ro"
    if iface.startswith(("wl", "wlan")):
        return f"Wi-Fi ({iface})"
    if iface.startswith(("wwan", "cdc", "usb")):
        return f"4G/5G ({iface})"
    if iface.startswith(("eth", "en")):
        return f"LAN ({iface})"
    if "tailscale" in iface.lower():
        return f"VPN Tailscale ({iface})"
    return iface

def get_signal_strength():
    iface = get_active_interface()
    if not iface:
        return "--"

    if iface.startswith(("wl", "wlan")):
        iw_output = run_cmd_timeout(f"iw dev {iface} link", timeout=2)
        match = re.search(r'signal:\s*(-?\d+)\s*dBm', iw_output)
        if match:
            return f"{match.group(1)} dBm"
        nmcli_output = run_cmd_timeout("nmcli -t -f active,signal dev wifi", timeout=2)
        for line in nmcli_output.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[0].lower() == "yes":
                return f"{parts[1]}%"

    if iface.startswith(("wwan", "cdc", "usb")):
        mmcli_output = run_cmd_timeout("mmcli -m any --signal-get", timeout=3)
        match = re.search(r'rssi:\s*([-\d.]+)\s*dBm', mmcli_output, re.IGNORECASE)
        if match:
            return f"{match.group(1)} dBm"
        mmcli_output = run_cmd_timeout("mmcli -m any", timeout=3)
        match = re.search(r'signal quality:\s*([0-9]+)%', mmcli_output, re.IGNORECASE)
        if match:
            return f"{match.group(1)}%"

    return "Co ket noi"

def get_battery_status():
    supplies = glob.glob("/sys/class/power_supply/*")
    for supply in supplies:
        name = os.path.basename(supply)
        capacity_path = os.path.join(supply, "capacity")
        status_path = os.path.join(supply, "status")
        if os.path.exists(capacity_path):
            try:
                with open(capacity_path, "r") as f:
                    capacity = f.read().strip()
                status = ""
                if os.path.exists(status_path):
                    with open(status_path, "r") as f:
                        status = f.read().strip()
                return f"{capacity}% {status}".strip()
            except Exception:
                continue
    return "Nguon ngoai"

def get_cpu_temp():
    candidates = glob.glob("/sys/class/thermal/thermal_zone*/temp")
    for path in candidates:
        try:
            with open(path, "r") as f:
                raw = f.read().strip()
            value = float(raw)
            if value > 1000:
                value = value / 1000.0
            if 0 < value < 120:
                return f"{value:.1f} C"
        except Exception:
            continue
    vcgencmd = run_cmd_timeout("vcgencmd measure_temp", timeout=2)
    match = re.search(r'temp=([\d.]+)', vcgencmd)
    return f"{match.group(1)} C" if match else "--"

def build_hw_summary():
    available_mode, _, _ = detect_available_mode()
    cam_ok = available_mode in ("both", "video_only")
    mic_ok = available_mode in ("both", "audio_only")
    return f"Camera ({'ok' if cam_ok else 'thieu'}); Micro ({'ok' if mic_ok else 'thieu'}); CBRN ({detect_cbrn_status()})"

def get_telemetry_payload(device_id, status="San sang"):
    return {
        "action": "telemetry_update",
        "device_id": device_id,
        "battery": get_battery_status(),
        "network": get_network_type(),
        "signal": get_signal_strength(),
        "cpu_temp": get_cpu_temp(),
        "device_name": get_device_name(),
        "status": status,
        "hw": build_hw_summary()
    }

def parse_float(value):
    try:
        return float(str(value).strip().strip("'\""))
    except Exception:
        return None

def get_configured_position():
    lat = parse_float(get_config_value("GPS_LAT", os.environ.get("CLIENT_LAT", "")))
    lng = parse_float(get_config_value("GPS_LNG", os.environ.get("CLIENT_LNG", "")))
    if lat is not None and lng is not None:
        return {"lat": lat, "lng": lng, "source": "config"}
    return None

def get_gpspipe_position():
    output = run_cmd_timeout("gpspipe -w -n 10", timeout=4)
    for line in output.splitlines():
        try:
            data = json.loads(line)
        except Exception:
            continue
        if data.get("class") == "TPV" and "lat" in data and "lon" in data:
            return {"lat": float(data["lat"]), "lng": float(data["lon"]), "source": "gpsd"}
    return None

def get_mmcli_position():
    output = run_cmd_timeout("mmcli -m any --location-get", timeout=4)
    patterns = [
        (r'latitude:\s*([-\d.]+)', r'longitude:\s*([-\d.]+)'),
        (r'Latitude\s*=\s*([-\d.]+)', r'Longitude\s*=\s*([-\d.]+)')
    ]
    for lat_pattern, lng_pattern in patterns:
        lat_match = re.search(lat_pattern, output, re.IGNORECASE)
        lng_match = re.search(lng_pattern, output, re.IGNORECASE)
        if lat_match and lng_match:
            return {"lat": float(lat_match.group(1)), "lng": float(lng_match.group(1)), "source": "mmcli"}
    return None

def get_ip_agps_position():
    if get_config_value("ENABLE_IP_AGPS", "0") != "1":
        return None
    try:
        import urllib.request
        with urllib.request.urlopen("http://ip-api.com/json/", timeout=4) as response:
            data = json.loads(response.read().decode())
            if "lat" in data and "lon" in data:
                return {"lat": float(data["lat"]), "lng": float(data["lon"]), "source": "ip-agps"}
    except Exception:
        return None
    return None

def haversine_meters(lat1, lng1, lat2, lng2):
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def bearing_degrees(lat1, lng1, lat2, lng2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lam = math.radians(lng2 - lng1)
    y = math.sin(d_lam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lam)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def get_position_payload(device_id):
    global last_gps_position
    position = get_gpspipe_position() or get_mmcli_position() or get_configured_position() or get_ip_agps_position()
    if not position:
        position = {"lat": 0.0, "lng": 0.0, "source": "none"}

    now = time.time()
    speed_kmh = 0.0
    heading = "--"
    if last_gps_position and position["lat"] != 0.0 and position["lng"] != 0.0:
        prev_lat, prev_lng, prev_time = last_gps_position
        delta_t = max(0.1, now - prev_time)
        distance_m = haversine_meters(prev_lat, prev_lng, position["lat"], position["lng"])
        speed_kmh = (distance_m / delta_t) * 3.6
        heading = f"{bearing_degrees(prev_lat, prev_lng, position['lat'], position['lng']):.0f}"

    if position["lat"] != 0.0 or position["lng"] != 0.0:
        last_gps_position = (position["lat"], position["lng"], now)

    return {
        "action": "gps_update",
        "device_id": device_id,
        "lat": position["lat"],
        "lng": position["lng"],
        "speed": round(speed_kmh, 1),
        "heading": heading,
        "source": position.get("source", "unknown"),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

def detect_cbrn_status():
    svg_port = get_config_value("CBRN_SVG2_PORT")
    raid_port = get_config_value("CBRN_RAIDM100_PORT")
    if svg_port or raid_port:
        return "configured"
    return "mat ket noi"

def normalize_sensor_status(value):
    text = str(value or "OK").strip()
    lower = text.lower()
    if lower in ("alarm", "alert", "warning", "canh bao", "báo động"):
        return "Canh bao"
    if lower in ("error", "loi", "lỗi", "lost", "disconnect", "mat ket noi"):
        return "Mat ket noi"
    return text

def parse_cbrn_line(sensor_name, line):
    line = (line or "").strip()
    if not line:
        return None
    try:
        data = json.loads(line)
        return {
            "sensor": sensor_name,
            "status": normalize_sensor_status(data.get("status", "OK")),
            "agent": data.get("agent", data.get("detected_agent", "")),
            "concentration": data.get("concentration", data.get("value", "--")),
            "unit": data.get("unit", "ppm"),
            "level": data.get("level", data.get("severity", 0))
        }
    except Exception:
        pass

    parts = {}
    for piece in re.split(r'[;,]\s*', line):
        if "=" in piece:
            key, value = piece.split("=", 1)
            parts[key.strip().lower()] = value.strip()
    if parts:
        return {
            "sensor": sensor_name,
            "status": normalize_sensor_status(parts.get("status", "OK")),
            "agent": parts.get("agent", parts.get("detected_agent", "")),
            "concentration": parts.get("concentration", parts.get("value", "--")),
            "unit": parts.get("unit", "ppm"),
            "level": parts.get("level", parts.get("severity", 0))
        }
    return None

def read_serial_sensor(sensor_name, port, baudrate):
    if not port:
        return {
            "sensor": sensor_name,
            "status": "Mat ket noi",
            "agent": "",
            "concentration": "--",
            "unit": "ppm",
            "level": 0
        }
    try:
        import serial
        with serial.Serial(port, int(baudrate), timeout=0.6) as ser:
            line = ser.readline().decode(errors="ignore")
        parsed = parse_cbrn_line(sensor_name, line)
        if parsed:
            return parsed
        return {
            "sensor": sensor_name,
            "status": "Loi",
            "agent": "",
            "concentration": "--",
            "unit": "ppm",
            "level": 0
        }
    except Exception as e:
        return {
            "sensor": sensor_name,
            "status": "Mat ket noi",
            "agent": str(e)[:80],
            "concentration": "--",
            "unit": "ppm",
            "level": 0
        }

def read_cbrn_sensors():
    if get_config_value("CBRN_TEST_ALARM", "0") == "1":
        return [
            {"sensor": "SVG-2", "status": "Canh bao", "agent": "TEST", "concentration": "1.2", "unit": "ppm", "level": 6},
            {"sensor": "RAID-M100", "status": "OK", "agent": "", "concentration": "0", "unit": "mg/m3", "level": 0}
        ]
    return [
        read_serial_sensor("SVG-2", get_config_value("CBRN_SVG2_PORT"), get_config_value("CBRN_SVG2_BAUD", "9600")),
        read_serial_sensor("RAID-M100", get_config_value("CBRN_RAIDM100_PORT"), get_config_value("CBRN_RAIDM100_BAUD", "9600"))
    ]

def detect_available_mode():
    """Quet thiet bi thuc te hien co va tra ve che do kha dung."""
    try:
        config = load_config()
        vid_name = config.get("VIDEO_NAME")
        aud_name = config.get("AUDIO_NAME")
        vid_path = get_video_path(vid_name) if vid_name else None
        aud_hw   = get_audio_hw(aud_name)   if aud_name else None

        if vid_path and aud_hw:
            return "both", vid_path, aud_hw
        elif vid_path:
            return "video_only", vid_path, None
        elif aud_hw:
            return "audio_only", None, aud_hw
        else:
            return "none", None, None
    except Exception as e:
        print(f"[!] Loi detect_available_mode: {e}")
        return "none", None, None

def ensure_devices_ready():
    if os.path.exists(CONFIG_FILE):
        config = load_config()
        vid_name = config.get("VIDEO_NAME")
        aud_name = config.get("AUDIO_NAME")
        if vid_name and aud_name:
            if get_video_path(vid_name) and get_audio_hw(aud_name):
                print(f"[+] Phan cung da xac thuc OK: {vid_name} / {aud_name}")
                return True
            else:
                if sys.stdin.isatty():
                    print("\n[!] Thiet bi cu da bi rut hoac loi ket noi. Ban dang chay thu cong, cho phep chon lai...")
                    os.remove(CONFIG_FILE)
                    setup_devices()
                else:
                    print(f"\n[!] Thiet bi ({vid_name} hoac {aud_name}) hien chua duoc ket noi vao mach.")
                    print("[>] He thong dang chay tu dong. Giu nguyen cau hinh va tiep tuc duy tri mang de cho doi ban cam thiet bi vao...")
                    return False
    else:
        if sys.stdin.isatty():
            setup_devices()
        else:
            print("\n[!] LOI: Chua co file cau hinh .env ma he thong lai dang chay tu dong!")
            print("Vui long chay code thu cong tren Terminal 1 lan de setup truoc.")
            sys.exit(1)

# ==========================================
# MODULE 4: XU LY MEDIA (DUMMY STREAM CHỐNG KẸT PREROLL)
# ==========================================
def start_gstreamer(master_ip, video_port, audio_port):
    global stream_process, current_stream_mode, current_master_config

    current_master_config = {"master_ip": master_ip, "video_port": video_port, "audio_port": audio_port}
    available_mode, vid_path, aud_hw = detect_available_mode()

    if available_mode == "none":
        print("[LOI] Khong tim thay bat ky thiet bi nao (Camera / Micro). Khong the bat luong.")
        current_stream_mode = "none"
        return False

    # Luồng Thật
    video_real = (
        f"v4l2src device={vid_path} ! image/jpeg,width=1280,height=720,framerate=30/1 ! "
        f"jpegdec ! videoconvert ! mpph265enc rc-mode=cbr bps=2000000 ! rtph265pay config-interval=1 pt=96 ! "
        f"udpsink host={master_ip} port={video_port} sync=false async=false "
    )
    audio_real = (
        f"alsasrc device={aud_hw} buffer-time=10000 latency-time=5000 ! audio/x-raw,rate=48000 ! "
        f"audioconvert ! audioresample ! opusenc bitrate=48000 frame-size=10 ! rtpopuspay pt=97 ! "
        f"udpsink host={master_ip} port={audio_port} sync=false async=false "
    )

    # Luồng Ảo (Dummy) bù đắp lỗ hổng
    video_dummy = (
        f"videotestsrc is-live=true pattern=black ! video/x-raw,width=1280,height=720,framerate=30/1 ! "
        f"videoconvert ! mpph265enc rc-mode=cbr bps=2000000 ! rtph265pay config-interval=1 pt=96 ! "
        f"udpsink host={master_ip} port={video_port} sync=false async=false "
    )
    audio_dummy = (
        f"audiotestsrc is-live=true wave=silence ! audio/x-raw,rate=48000 ! "
        f"audioconvert ! audioresample ! opusenc bitrate=48000 frame-size=10 ! rtpopuspay pt=97 ! "
        f"udpsink host={master_ip} port={audio_port} sync=false async=false "
    )

    if available_mode == "both":
        pipeline = f"gst-launch-1.0 {video_real} {audio_real}"
    elif available_mode == "video_only":
        print("[!] Chi co Camera, thieu Micro -> Phat VIDEO THAT + AUDIO DUMMY (im lang)")
        pipeline = f"gst-launch-1.0 {video_real} {audio_dummy}"
    else:  # audio_only
        print("[!] Chi co Micro, thieu Camera -> Phat AUDIO THAT + VIDEO DUMMY (nen den)")
        pipeline = f"gst-launch-1.0 {video_dummy} {audio_real}"

    print(f"[>] KICH HOAT luong truyen tai P2P [Che do: {available_mode.upper()}] -> {master_ip}")
    try:
        stream_process = subprocess.Popen(pipeline, shell=True)
        current_stream_mode = available_mode
        return True
    except Exception as e:
        print(f"[LOI] Khong the khoi dong GStreamer: {e}")
        current_stream_mode = "none"
        return False

def stop_gstreamer():
    global stream_process, current_stream_mode
    if stream_process:
        stream_process.terminate()
        stream_process.wait()
        stream_process = None
    current_stream_mode = "none"
    os.system("killall -9 gst-launch-1.0 2>/dev/null")
    print("[x] Da dung stream va giai phong phan cung.")

# ==========================================
# MODULE 5: RADAR GIAM SAT DUONG TRUYEN
# ==========================================
async def monitor_network_switch():
    global active_interface
    while True:
        try:
            route_info = run_cmd("ip route get 8.8.8.8")
            match = re.search(r'dev\s+([^\s]+)', route_info)
            if match:
                current_iface = match.group(1)
                if current_iface != active_interface:
                    if "wl" in current_iface:
                        net_type = "WI-FI (Toc do cao)"
                    elif "wwan" in current_iface or "cdc" in current_iface or "usb" in current_iface or "eth" in current_iface:
                        net_type = "4G/5G (Du phong)"
                    else:
                        net_type = current_iface
                    if active_interface != "":
                        print("\n" + "="*60)
                        print(f" [!!!] HE THONG VUA CHUYEN SANG DUNG MANG: {net_type} [!!!]".center(60))
                        print("="*60 + "\n")
                    else:
                        print(f"\n[*] Mang dang hoat dong chinh: {net_type} (Card: {current_iface})\n")
                    active_interface = current_iface
        except Exception:
            pass
        await asyncio.sleep(1)

# ==============================================================
# LUỒNG QUÉT PHẦN CỨNG & DỰ PHÒNG CẮM NÓNG
# ==============================================================
async def hardware_live_monitor_loop(websocket, device_id):
    global master_requested_streaming, current_stream_mode, current_master_config
    last_mode_detected = None

    while True:
        try:
            available_mode, _, _ = detect_available_mode()

            # Chỉ gửi thông báo về Master KHI CÓ SỰ THAY ĐỔI
            if available_mode != last_mode_detected:
                vid_ok = available_mode in ("both", "video_only")
                aud_ok = available_mode in ("both", "audio_only")
                status_msg = (
                    f"[{device_id}] TRANG THAI NGOAI VI -> "
                    f"Cam: {'OK' if vid_ok else 'THIEU CAM ❌'}, "
                    f"Mic: {'OK' if aud_ok else 'THIEU MIC ❌'}"
                )
                try:
                    await websocket.send(json.dumps({
                        "action": "client_log",
                        "device_id": device_id,
                        "message": status_msg
                    }))
                    last_mode_detected = available_mode
                except Exception:
                    pass

            # Hot-plug: tu dong tai cau hinh khi dang stream ma thiet bi thay doi
            if master_requested_streaming:
                if available_mode != current_stream_mode:
                    print(f"[SYS] Phat hien thay doi phan cung ({current_stream_mode} -> {available_mode}). Dang tu dong tai cau hinh...")
                    stop_gstreamer()
                    if available_mode != "none":
                        start_gstreamer(
                            current_master_config["master_ip"],
                            current_master_config["video_port"],
                            current_master_config["audio_port"]
                        )
                    else:
                        print("[!] Mat het thiet bi. Dang cho cam lai...")
                        current_stream_mode = "none"

        except Exception as e:
            print(f"[-] Loi quet thiet bi ngam: {e}")

        await asyncio.sleep(3)

async def send_json_safe(websocket, payload):
    try:
        await websocket.send(json.dumps(payload, ensure_ascii=False))
        return True
    except Exception:
        return False

async def telemetry_loop(websocket, device_id):
    while True:
        status = "Dang phat" if master_requested_streaming else "San sang"
        payload = get_telemetry_payload(device_id, status=status)
        ok = await send_json_safe(websocket, payload)
        if not ok:
            return
        await asyncio.sleep(TELEMETRY_INTERVAL)

async def gps_update_loop(websocket, device_id):
    while True:
        payload = get_position_payload(device_id)
        ok = await send_json_safe(websocket, payload)
        if not ok:
            return
        await asyncio.sleep(GPS_INTERVAL)

async def cbrn_update_loop(websocket, device_id):
    last_payload = None
    while True:
        sensors = read_cbrn_sensors()
        payload = {
            "action": "cbrn_update",
            "device_id": device_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sensors": sensors
        }
        payload_key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if payload_key != last_payload:
            ok = await send_json_safe(websocket, payload)
            if not ok:
                return
            last_payload = payload_key
        await asyncio.sleep(CBRN_INTERVAL)

# ==========================================
# MODULE 6: GIAO TIEP MANG — DUAL-IP WEBSOCKET AGENT
# ==========================================
async def connect_to_vps():
    """
    Vòng lặp kết nối chính với logic Dual-IP:
      1. Dùng pick_best_master() thăm dò LAN trước, VPN sau.
      2. Kết nối WebSocket tới IP tìm được.
      3. Lấy IP cục bộ thực sự (LAN hoặc Tailscale) để báo cáo lên Master.
         → Master đọc remote_ip để Smart Routing, nên báo đúng IP rất quan trọng.
      4. Nếu mất kết nối: dừng GStreamer, thử lại vòng mới (có thể đổi sang IP khác).
    """
    global master_requested_streaming

    ensure_devices_ready()
    asyncio.create_task(monitor_network_switch())

    device_id = f"ROCK-{get_mac_address()}"
    print(f"\n{'='*60}")
    print(f" KHOI DONG CLIENT: {device_id} ".center(60, "="))
    print(f"{'='*60}")
    print(f"[NET] Danh sach IP uu tien: {MASTER_IP_PRIORITY}")

    while True:
        # ── Bước 1: Thăm dò, chọn IP khả dụng tốt nhất ──────────
        chosen_ip = pick_best_master()

        if chosen_ip is None:
            print(f"[-] Tat ca IP deu khong den duoc. Thu lai sau {RETRY_DELAY}s...")
            await asyncio.sleep(RETRY_DELAY)
            continue

        # ── Bước 2: Xác định IP cục bộ phù hợp ──────────────────
        # get_local_ip_for() dùng UDP trick: không gửi packet thật,
        # chỉ hỏi OS "nếu đi tới IP này thì dùng card nào?"
        local_ip = get_local_ip_for(chosen_ip)
        net_label = "LAN" if chosen_ip == MASTER_LAN_IP else "VPN Tailscale"
        ws_url    = f"ws://{chosen_ip}:{SIGNALING_PORT}"

        print(f"\n[WS] Dang ket noi [{net_label}]: {ws_url}")
        print(f"[WS] IP cuc bo bao cao len Master: {local_ip}")

        try:
            async with websockets.connect(
                ws_url,
                ping_interval=20,   # Ping 20s/lần để phát hiện mạng đứt sớm
                ping_timeout=10,    # Sau 10s không pong → coi là mất kết nối
                close_timeout=5,
            ) as websocket:
                print(f"[+] Da ket noi toi Master ({net_label}: {chosen_ip})!")

                # ── Bước 3: Đăng ký với Master ───────────────────
                # Gửi local_ip thật sự (LAN hoặc Tailscale) để Master
                # hiển thị đúng trong bảng Htop.
                # Master đọc thêm remote_address của socket để Smart Routing.
                await websocket.send(json.dumps({
                    "action":    "register_client",
                    "device_id": device_id,
                    "ip":        local_ip,
                    "device_name": get_device_name(),
                }))

                await send_json_safe(websocket, get_telemetry_payload(device_id, status="San sang"))

                # ── Bước 4: Chạy các luồng giám sát song song ──
                background_tasks = [
                    asyncio.create_task(hardware_live_monitor_loop(websocket, device_id)),
                    asyncio.create_task(telemetry_loop(websocket, device_id)),
                    asyncio.create_task(gps_update_loop(websocket, device_id)),
                    asyncio.create_task(cbrn_update_loop(websocket, device_id)),
                ]

                # ── Bước 5: Lắng nghe lệnh từ Master ─────────────
                try:
                    async for message in websocket:
                        data   = json.loads(message)
                        action = data.get("action")

                        if action == "start_stream":
                            master_ip = data.get("master_ip")
                            v_port    = data.get("video_port", "5000")
                            a_port    = data.get("audio_port", "5001")
                            print(f"\n[CMD] Nhan lenh START_STREAM tu Master -> {master_ip}:{v_port}/{a_port}")

                            master_requested_streaming = True
                            stop_gstreamer()

                            try:
                                ok = start_gstreamer(master_ip, v_port, a_port)
                                await send_json_safe(websocket, get_telemetry_payload(device_id, status="Dang phat" if ok else "Loi stream"))
                                if not ok:
                                    print("[!] Chua co thiet bi nao. Che do cho: khi cam thiet bi vao se tu dong bat stream.")
                            except Exception as e:
                                print(f"[LOI] start_gstreamer that bai: {e}")
                                await send_json_safe(websocket, {
                                    "action": "error_alert",
                                    "device_id": device_id,
                                    "error": f"start_gstreamer failed: {e}"
                                })

                        elif action == "stop_stream":
                            print("\n[CMD] Nhan lenh STOP_STREAM tu Master.")
                            master_requested_streaming = False
                            stop_gstreamer()
                            await send_json_safe(websocket, get_telemetry_payload(device_id, status="San sang"))

                finally:
                    for task in background_tasks:
                        task.cancel()
                    await asyncio.gather(*background_tasks, return_exceptions=True)

        except (
            websockets.exceptions.ConnectionClosed,
            websockets.exceptions.WebSocketException,
            ConnectionRefusedError,
            OSError,
        ) as e:
            print(f"[-] Mat ket noi [{net_label}] ({type(e).__name__}): {e}")
        except Exception as e:
            print(f"[-] Loi khong mong doi: {e}")
        finally:
            # Dừng GStreamer khi mất kết nối tránh stream zombie
            # → Master sẽ dọn UI (handle_client_disconnect)
            # → Vòng lặp tiếp theo sẽ thăm dò lại IP (có thể đổi LAN↔VPN)
            master_requested_streaming = False
            stop_gstreamer()
            print(f"[WS] Da dong ket noi. Thu lai sau {RETRY_DELAY}s (se thang do IP tu dau)...")
            await asyncio.sleep(RETRY_DELAY)

if __name__ == "__main__":
    optimize_network_routes()
    os.system("killall -9 gst-launch-1.0 2>/dev/null")
    try:
        asyncio.run(connect_to_vps())
    except KeyboardInterrupt:
        stop_gstreamer()
        print("\nThoat chuong trinh.")
