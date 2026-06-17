# Tài Liệu Hệ Thống SCADA Phân Loại Nắp Chai Theo Màu

Tài liệu này mô tả đầy đủ hệ thống SCADA prototype dùng để điều khiển, giám sát và phân loại nắp chai theo màu trên băng chuyền. Nội dung bao gồm tổng quan hệ thống, phần cứng, đấu dây, phần mềm, nguyên lý vận hành, cài đặt, sử dụng, hiệu chỉnh, debug và kiểm thử.

Hệ thống được thiết kế theo hướng prototype chắc chắn cho đồ án hoặc mô hình phòng thí nghiệm: có điều khiển realtime ở Arduino, xử lý ảnh tại Rock5T, dashboard giám sát từ Windows qua LAN, logging, trạng thái hệ thống và cơ chế debug rõ ràng.

## 1. Tổng Quan Hệ Thống

### 1.1 Mục Tiêu

Hệ thống có nhiệm vụ:

- Điều khiển băng chuyền chạy bằng step motor.
- Quan sát nắp chai bằng camera gắn trực tiếp vào Rock5T.
- Nhận dạng màu nắp chai bằng xử lý ảnh HSV.
- Quyết định nắp chai nào được cho qua và nắp chai nào cần bị gạt khỏi băng chuyền.
- Điều khiển servo 180 độ làm cơ cấu gạt.
- Dùng cảm biến siêu âm HC-SR04 xác nhận vật đã rơi xuống máng sau khi gạt.
- Gửi dữ liệu realtime, video, trạng thái, log và cảnh báo lên dashboard SCADA trên máy Windows trong cùng mạng LAN.

### 1.2 Kiến Trúc Tổng Thể

```text
Camera gắn Rock5T
        |
        v
Rock5T: OpenCV + FastAPI + Dashboard + SQLite log
        |
        | USB Serial 115200 baud
        v
Arduino Uno
        |
        +--> Driver step motor PU/DR/+5V/MF --> Step motor --> Băng chuyền
        |
        +--> Servo 180 độ --> Cơ cấu gạt
        |
        +--> HC-SR04 --> Xác nhận vật rơi vào máng

Windows PC
        |
        | LAN: http://<ip-rock5t>:8000
        v
Dashboard SCADA trên trình duyệt
```

### 1.3 Phân Chia Vai Trò

- Windows PC:
  - Chỉ dùng để giám sát và điều khiển từ xa qua trình duyệt.
  - Không xử lý camera, không nối trực tiếp phần cứng IO.

- Rock5T:
  - Là máy tính hiện trường.
  - Nhận camera gắn trực tiếp vào Rock5T, mặc định `/dev/video0`.
  - Chạy xử lý ảnh OpenCV, API FastAPI, dashboard web, WebSocket telemetry, video stream MJPEG.
  - Giao tiếp Arduino qua USB Serial.
  - Lưu log vận hành vào SQLite.

- Arduino Uno:
  - Là bộ điều khiển realtime cho phần cơ điện.
  - Nhận lệnh từ Rock5T.
  - Tạo xung step cho driver step motor.
  - Điều khiển servo gạt.
  - Đọc HC-SR04.
  - Trả trạng thái và kết quả phân loại về Rock5T.

## 2. Cấu Trúc Dự Án

```text
Scada/
  Scada.txt
  README.md
  requirements.txt
  config/
    default_config.json
  docs/
    wiring.md
    protocol.md
    test_plan.md
  firmware/
    arduino_scada/
      arduino_scada.ino
  rock5t_scada/
    config.py
    event_logger.py
    main.py
    models.py
    serial_link.py
    state.py
    vision.py
  tests/
    test_config.py
    test_state.py
  web/
    index.html
    styles.css
    app.js
```

Ý nghĩa chính:

- `firmware/arduino_scada/arduino_scada.ino`: firmware nạp vào Arduino Uno.
- `rock5t_scada/`: phần mềm chạy trên Rock5T.
- `web/`: giao diện SCADA mở bằng trình duyệt.
- `config/default_config.json`: cấu hình mặc định cho camera, serial, HSV, tốc độ, ROI.
- `docs/wiring.md`: tài liệu đấu dây chi tiết.
- `docs/protocol.md`: giao thức Serial Rock5T - Arduino.
- `docs/test_plan.md`: checklist kiểm thử phần cứng, phần mềm, tích hợp.
- `data/`: thư mục runtime được tự tạo khi chạy, chứa `config.json` và `events.sqlite3`.

## 3. Phần Cứng

### 3.1 Danh Sách Thiết Bị

| Thiết bị | Vai trò |
| --- | --- |
| Windows PC | Giám sát, điều khiển từ xa qua browser |
| Rock5T | Xử lý camera, chạy SCADA service, giao tiếp Arduino |
| Camera gắn Rock5T | Quan sát nắp chai trên băng chuyền |
| Arduino Uno | Điều khiển realtime motor, servo, cảm biến |
| Driver step motor `PU/DR/+5V/MF` | Nhận xung và điều khiển step motor |
| Step motor | Kéo băng chuyền |
| Servo 180 độ | Cơ cấu gạt sản phẩm |
| HC-SR04 | Xác nhận sản phẩm rơi vào máng sau khi gạt |
| Nguồn motor | Cấp nguồn động lực cho step motor theo driver thực tế |
| Nguồn tổ ong 24V servo | Cấp riêng cho servo |
| Đèn LED chiếu sáng | Giữ ánh sáng ổn định cho nhận dạng HSV |

### 3.2 Sơ Đồ Đấu Dây Arduino

| Chức năng | Arduino Uno | Thiết bị |
| --- | --- | --- |
| Step pulse | D2 | Driver `PU` |
| Direction | D3 | Driver `DR` |
| Motor free / enable | D4 | Driver `MF` |
| Servo signal | D5 | Servo signal |
| Ultrasonic trigger | D10 | HC-SR04 `TRIG` |
| Ultrasonic echo | D11 | HC-SR04 `ECHO` |
| Serial | USB | Rock5T USB |

### 3.3 Đấu Driver Step Motor `PU/DR/+5V/MF`

Driver của hệ thống có 4 ngõ vào điều khiển:

- `+5V`: nối 5V logic từ Arduino.
- `PU`: nhận xung bước từ Arduino D2.
- `DR`: nhận tín hiệu chiều quay từ Arduino D3.
- `MF`: motor free hoặc enable, nối Arduino D4.

Firmware hiện tại giả định kiểu common `+5V` phổ biến:

- `PU` active-low.
- `MF` active-low theo nghĩa motor-free.
- `DR` không đảo chiều.

Nếu driver thực tế hoạt động ngược, chỉnh các hằng số ở đầu file firmware:

```cpp
const bool DRIVER_PU_ACTIVE_LOW = true;
const bool DRIVER_DR_INVERTED = false;
const bool DRIVER_MF_ACTIVE_LOW = true;
```

Nếu motor quay ngược chiều mong muốn, đổi `DRIVER_DR_INVERTED` từ `false` sang `true`.

Nếu motor không giữ lực hoặc luôn free, thử đổi `DRIVER_MF_ACTIVE_LOW`.

### 3.4 Nguồn Và Mass

Yêu cầu quan trọng:

- Step motor dùng nguồn động lực riêng theo thông số driver và motor.
- Servo dùng nguồn 24V riêng, khuyến nghị tối thiểu 2A.
- Arduino có thể cấp bằng USB từ Rock5T.
- GND của nguồn motor, nguồn servo và Arduino phải nối chung.
- Không cấp nguồn servo tải lớn trực tiếp từ chân 5V Arduino.
- Dây motor nên đi tách khỏi dây camera, HC-SR04 và dây tín hiệu logic.
- Nên có nút ngắt nguồn phần công suất khi vận hành mô hình thật.

### 3.5 Cơ Khí Và Bố Trí Thiết Bị

- Camera gắn trực tiếp vào Rock5T và đặt cố định phía trên băng chuyền.
- Camera phải nhìn rõ vùng nhận dạng ROI và vị trí/vạch gạt.
- Băng chuyền mặc định được giả định chạy từ trái sang phải trong khung hình.
- Vạch quyết định gạt trong phần mềm mặc định ở `vision.sort_line_ratio = 0.72`.
- Servo mặc định:
  - Góc home: `20°`.
  - Góc push: `100°`.
  - Thời gian giữ push: `300ms`.
- HC-SR04 đặt tại máng rơi, ngưỡng xác nhận mặc định dưới `10cm`.
- Ánh sáng nên dùng LED cố định, tránh ánh sáng ngoài trời thay đổi mạnh.

## 4. Phần Mềm

### 4.1 Firmware Arduino

Firmware nằm tại:

```text
firmware/arduino_scada/arduino_scada.ino
```

Chức năng:

- Nhận lệnh text line từ Rock5T qua Serial 115200.
- Điều khiển step motor bằng thư viện `AccelStepper`.
- Điều khiển servo bằng thư viện `Servo`.
- Đọc HC-SR04 theo kiểu không blocking.
- Quản lý queue lệnh phân loại.
- Trả trạng thái định kỳ về Rock5T.
- Báo lỗi khi command sai hoặc queue đầy.

State machine chính:

- `IDLE`: hệ thống dừng, motor không chạy.
- `RUNNING`: băng chuyền đang chạy.
- `SORTING`: đang thực hiện lệnh gạt hoặc xác nhận gạt.
- `FAULT`: trạng thái lỗi, dùng cho mở rộng an toàn.

Firmware tránh dùng `delay()` trong vòng lặp chính để motor, serial, servo và cảm biến vẫn phản hồi nhanh.

### 4.2 Service Rock5T

Service Rock5T nằm trong thư mục:

```text
rock5t_scada/
```

Các module chính:

- `main.py`: FastAPI app, API điều khiển, WebSocket, MJPEG video.
- `vision.py`: đọc camera, nhận dạng HSV, tracking object, overlay video.
- `serial_link.py`: giao tiếp Arduino qua USB Serial, mô phỏng khi thiếu thiết bị.
- `state.py`: trạng thái realtime, counter, fault, telemetry.
- `event_logger.py`: log sự kiện vào SQLite.
- `config.py`: đọc và lưu cấu hình runtime.
- `models.py`: model dữ liệu API.

Service có chế độ fallback:

- Nếu chưa có camera, dùng frame mô phỏng để dashboard vẫn chạy được.
- Nếu chưa có Arduino, dùng serial simulation nếu `simulate_when_missing = true`.
- Nếu Arduino thật đang gửi dòng ngoài protocol, hệ thống ghi dạng `serial_debug` và throttle để log không bị ngập.

### 4.3 Dashboard Windows SCADA

Dashboard nằm trong:

```text
web/
```

Windows PC mở dashboard bằng trình duyệt:

```text
http://<ip-rock5t>:8000
```

Các vùng chính trên dashboard:

- Live Vision:
  - Video realtime từ camera Rock5T.
  - Overlay ROI, vạch sort line, bounding box, màu, quyết định `PASS/PUSH`.

- Controls:
  - `Start`: chạy băng chuyền.
  - `Stop`: dừng băng chuyền.
  - `Jog`: chạy thử motor trong thời gian ngắn.
  - `Test Push`: test servo gạt thủ công.
  - `Test Pass`: test luồng cho qua.
  - Speed slider/input: đặt tốc độ stepper.

- HSV Calibration:
  - Bật/tắt từng màu.
  - Chọn màu nào là hợp lệ bằng `Allowed`.
  - Chỉnh dải HSV cho từng màu.
  - Lưu cấu hình vào `data/config.json`.

- Event Log:
  - Hiển thị sự kiện mới nhất.
  - Bao gồm detection, decision, serial, sort result, lỗi.

## 5. Nguyên Lý Hoạt Động

### 5.1 Luồng Bình Thường

1. Operator mở dashboard từ Windows.
2. Operator kiểm tra camera, serial, FPS, trạng thái hệ thống.
3. Operator bấm `Start`.
4. Rock5T gửi `RUN 1` xuống Arduino.
5. Arduino bật driver, phát xung step và kéo băng chuyền.
6. Camera trên Rock5T chụp frame realtime.
7. OpenCV chuyển ảnh sang HSV và lọc theo các khoảng màu đã cấu hình.
8. Hệ thống tạo object id cho từng nắp chai được tracking.
9. Khi vật đi qua sort line:
   - Màu `allowed=true`: Rock5T gửi `SORT <id> PASS <delay_ms>`.
   - Màu `allowed=false` hoặc `unknown`: Rock5T gửi `SORT <id> PUSH <delay_ms>`.
10. Arduino nhận lệnh:
   - `PASS`: ghi nhận vật đi qua.
   - `PUSH`: đưa servo sang góc gạt, giữ 300ms, trả về home.
11. Nếu gạt, Arduino đọc HC-SR04 trong cửa sổ xác nhận 1000ms.
12. Arduino trả kết quả:
   - `SORT_DONE <id> result=PASSED`.
   - `SORT_DONE <id> result=PUSHED`.
   - `SORT_DONE <id> result=TIMEOUT`.
13. Rock5T cập nhật counter, event log, dashboard và SQLite.

### 5.2 Quy Tắc Phân Loại

Quy tắc mặc định:

- Màu có `allowed=true`: cho qua.
- Màu có `allowed=false`: gạt.
- Vật thể không khớp màu nào nhưng vẫn có vùng màu đủ rõ: `unknown`, gạt.

Ví dụ trong cấu hình mặc định:

- `red`: allowed.
- `blue`: allowed.
- `yellow`: reject.
- `green`: reject.

### 5.3 Độ Trễ Và Vị Trí Gạt

Có 2 cách vận hành:

- Camera nhìn trực tiếp vị trí gạt:
  - Đặt `control.sort_delay_ms = 0`.
  - Khi object đi qua sort line, Rock5T gửi lệnh ngay.

- Camera nhìn vùng trước vị trí gạt:
  - Cần tính delay theo khoảng cách từ vùng camera đến cơ cấu gạt.
  - Có thể đặt `control.sort_delay_ms` cố định trong cấu hình.
  - Công thức thực nghiệm: `delay_ms = distance_to_gate / belt_speed`.

Trong prototype hiện tại, cách đơn giản và ổn nhất là đặt camera nhìn được vùng gần vị trí gạt và dùng delay bằng `0`.

## 6. Giao Thức Serial Rock5T - Arduino

Kết nối:

- USB Serial.
- Baudrate: `115200`.
- Mỗi lệnh kết thúc bằng `\n`.

### 6.1 Lệnh Từ Rock5T

| Lệnh | Ý nghĩa |
| --- | --- |
| `RUN 1` | Chạy băng chuyền |
| `RUN 0` | Dừng băng chuyền |
| `SPEED <steps_per_sec>` | Đặt tốc độ stepper |
| `SORT <id> PUSH <delay_ms>` | Lên lịch gạt vật thể |
| `SORT <id> PASS <delay_ms>` | Lên lịch cho qua |
| `PING <seq>` | Kiểm tra kết nối |
| `STATE` | Yêu cầu Arduino gửi trạng thái |

### 6.2 Phản Hồi Từ Arduino

| Phản hồi | Ý nghĩa |
| --- | --- |
| `READY fw=1.0` | Firmware đã khởi động |
| `ACK <cmd> <id>` | Đã nhận lệnh |
| `STATE run=<0|1> speed=<value> queue=<n> mode=<mode> distance_cm=<cm>` | Trạng thái realtime |
| `SORT_DONE <id> result=PASSED` | Vật được cho qua |
| `SORT_DONE <id> result=PUSHED` | Servo đã gạt và HC-SR04 xác nhận |
| `SORT_DONE <id> result=TIMEOUT` | Đã gạt nhưng HC-SR04 không xác nhận |
| `ERR code=<code> msg=<short_msg>` | Lỗi lệnh hoặc lỗi firmware |

## 7. API Và Dữ Liệu Realtime

FastAPI chạy trên Rock5T tại port `8000`.

| Endpoint | Chức năng |
| --- | --- |
| `GET /` | Dashboard SCADA |
| `GET /api/status` | Trạng thái hệ thống, cấu hình, log gần nhất |
| `POST /api/control/start` | Chạy băng chuyền |
| `POST /api/control/stop` | Dừng băng chuyền |
| `POST /api/control/speed` | Đặt tốc độ stepper |
| `POST /api/control/jog` | Chạy thử băng chuyền trong thời gian ngắn |
| `POST /api/control/manual-sort` | Test `PUSH` hoặc `PASS` thủ công |
| `GET /api/config/colors` | Đọc cấu hình màu |
| `POST /api/config/colors` | Lưu cấu hình màu |
| `GET /api/events` | Đọc event log gần nhất |
| `GET /video.mjpg` | Video MJPEG realtime |
| `WS /ws/telemetry` | Telemetry realtime cho dashboard |

Log runtime:

- `data/events.sqlite3`: log vận hành.
- `data/config.json`: cấu hình đã lưu từ dashboard.

## 8. Cấu Hình Hệ Thống

Cấu hình mặc định nằm tại:

```text
config/default_config.json
```

Khi service chạy, cấu hình runtime có thể được tạo tại:

```text
data/config.json
```

### 8.1 Camera

```json
{
  "camera": {
    "device": "/dev/video0",
    "index": 0,
    "width": 640,
    "height": 480,
    "fps": 30,
    "retry_interval_sec": 30,
    "synthetic_when_missing": true
  }
}
```

Ý nghĩa:

- `device`: đường dẫn camera trên Rock5T, mặc định `/dev/video0`.
- `index`: camera fallback nếu `device` để rỗng.
- `width`, `height`: kích thước frame.
- `fps`: FPS mục tiêu.
- `retry_interval_sec`: chu kỳ thử kết nối lại camera nếu camera lỗi.
- `synthetic_when_missing`: dùng video mô phỏng khi thiếu camera.

### 8.2 Serial

```json
{
  "serial": {
    "port": "AUTO",
    "baudrate": 115200,
    "simulate_when_missing": true
  }
}
```

Ý nghĩa:

- `port = AUTO`: tự tìm Arduino.
- Có thể đặt cụ thể như `/dev/ttyACM0`, `/dev/ttyUSB0`, `COM5`.
- `simulate_when_missing = true`: cho phép chạy dashboard khi chưa cắm Arduino.

### 8.3 Điều Khiển

```json
{
  "control": {
    "default_speed_steps_per_sec": 800,
    "sort_delay_ms": 0,
    "jog_duration_ms": 1500
  }
}
```

Ý nghĩa:

- `default_speed_steps_per_sec`: tốc độ stepper khi khởi động.
- `sort_delay_ms`: delay từ lúc quyết định đến lúc gạt.
- `jog_duration_ms`: thời gian chạy thử motor khi bấm Jog.

### 8.4 Vision

```json
{
  "vision": {
    "min_area": 500,
    "match_distance_px": 80,
    "lost_after_frames": 8,
    "sort_line_ratio": 0.72,
    "roi": {
      "x": 0.05,
      "y": 0.12,
      "w": 0.9,
      "h": 0.76
    }
  }
}
```

Ý nghĩa:

- `min_area`: diện tích contour nhỏ nhất để nhận là vật thể.
- `match_distance_px`: khoảng cách tối đa để nối detection vào track cũ.
- `lost_after_frames`: số frame mất dấu trước khi xóa track.
- `sort_line_ratio`: vị trí vạch quyết định theo chiều ngang frame.
- `roi`: vùng xử lý ảnh theo tỉ lệ khung hình.

## 9. Cài Đặt Và Thiết Lập

### 9.1 Chuẩn Bị Arduino

1. Mở Arduino IDE.
2. Cài thư viện `AccelStepper` bằng Library Manager.
3. Mở file:

```text
firmware/arduino_scada/arduino_scada.ino
```

4. Chọn board `Arduino Uno`.
5. Chọn port Arduino.
6. Upload firmware.
7. Mở Serial Monitor baud `115200`.
8. Kiểm tra có dòng:

```text
READY fw=1.0
```

9. Test thủ công:

```text
SPEED 800
RUN 1
RUN 0
SORT 1 PUSH 0
STATE
```

### 9.2 Chuẩn Bị Rock5T

Trên Rock5T Linux:

```bash
cd /path/to/Scada
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Nếu camera dùng V4L2, có thể kiểm tra:

```bash
ls /dev/video*
v4l2-ctl --list-devices
```

Nếu Arduino không truy cập được do quyền serial:

```bash
sudo usermod -aG dialout $USER
```

Sau đó logout/login lại hoặc reboot.

### 9.3 Chạy Service Trên Rock5T

```bash
source .venv/bin/activate
python -m uvicorn rock5t_scada.main:app --host 0.0.0.0 --port 8000
```

Trên máy Windows dùng để phát triển có thể chạy tương tự:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn rock5t_scada.main:app --host 0.0.0.0 --port 8000
```

Mở dashboard:

```text
http://<ip-rock5t>:8000
```

Nếu Rock5T có mDNS:

```text
http://rock5t.local:8000
```

### 9.4 Chạy Tự Động Bằng systemd

Tạo file service:

```bash
sudo nano /etc/systemd/system/scada-sorter.service
```

Nội dung mẫu:

```ini
[Unit]
Description=SCADA Color Sorter
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/path/to/Scada
ExecStart=/path/to/Scada/.venv/bin/python -m uvicorn rock5t_scada.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
User=rock

[Install]
WantedBy=multi-user.target
```

Bật service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable scada-sorter
sudo systemctl start scada-sorter
sudo systemctl status scada-sorter
```

Xem log:

```bash
journalctl -u scada-sorter -f
```

## 10. Hướng Dẫn Sử Dụng Dashboard

### 10.1 Kiểm Tra Trước Khi Chạy

Trên dashboard, kiểm tra:

- `Camera OK` hoặc video mô phỏng nếu chưa cắm camera.
- `Serial OK` nếu Arduino đã kết nối.
- FPS gần hoặc trên 20 FPS.
- Mode đang là `IDLE`.
- Không có fault nghiêm trọng.
- Video nhìn rõ băng chuyền và vùng gạt.

### 10.2 Chạy Hệ Thống

1. Bật nguồn motor, nguồn servo, Rock5T và Arduino.
2. Mở dashboard từ Windows.
3. Kiểm tra video và serial.
4. Đặt tốc độ stepper bằng Speed.
5. Bấm `Start`.
6. Đưa nắp chai lên băng chuyền.
7. Quan sát overlay nhận màu và quyết định `PASS/PUSH`.
8. Quan sát counter và event log.

### 10.3 Dừng Hệ Thống

1. Bấm `Stop`.
2. Chờ băng chuyền dừng hẳn.
3. Ngắt nguồn công suất nếu cần thao tác cơ khí.
4. Không chỉnh cơ khí servo khi hệ thống đang chạy.

### 10.4 Test Thủ Công

- `Jog`: chạy thử băng chuyền trong thời gian ngắn.
- `Test Push`: gửi lệnh gạt thử servo.
- `Test Pass`: gửi lệnh pass thử luồng logic.
- Speed: thay đổi tốc độ stepper.

Dùng các nút này khi:

- Kiểm tra motor sau khi đấu dây.
- Kiểm tra chiều servo.
- Kiểm tra Serial Rock5T - Arduino.
- Kiểm tra dashboard có nhận phản hồi hay không.

## 11. Hiệu Chỉnh HSV

### 11.1 Quy Trình Hiệu Chỉnh

1. Cố định camera.
2. Bật đèn LED chiếu sáng ổn định.
3. Đặt từng màu nắp chai vào vùng camera.
4. Mở dashboard, quan sát overlay.
5. Trong `HSV Calibration`, chỉnh từng khoảng:
   - `H_MIN`, `H_MAX`: màu sắc.
   - `S_MIN`, `S_MAX`: độ bão hòa.
   - `V_MIN`, `V_MAX`: độ sáng.
6. Tick `Enabled` cho màu đang dùng.
7. Tick `Allowed` cho màu được cho qua.
8. Bỏ tick `Allowed` cho màu cần loại.
9. Bấm `Save`.
10. Chạy thử nhiều lần để kiểm tra ổn định.

### 11.2 Gợi Ý Chỉnh HSV

- Nếu nhận nhầm nền thành vật:
  - Tăng `S_MIN`.
  - Tăng `V_MIN`.
  - Tăng `vision.min_area`.

- Nếu màu thật không được nhận:
  - Mở rộng `H_MIN/H_MAX`.
  - Giảm `S_MIN`.
  - Giảm `V_MIN`.

- Nếu màu bị thay đổi theo ánh sáng:
  - Cố định nguồn sáng.
  - Che ánh sáng ngoài trời.
  - Tránh bóng đổ từ tay hoặc cơ cấu gạt.

### 11.3 Màu Đỏ Có Hai Khoảng Hue

Trong HSV của OpenCV, Hue nằm trong khoảng `0..179`. Màu đỏ nằm ở hai đầu vòng màu, nên cấu hình mặc định dùng hai range:

- `0..10`.
- `170..179`.

Không nên gộp đỏ thành một khoảng lớn vì dễ nhận nhầm màu khác.

## 12. Quy Trình Vận Hành Khuyến Nghị

### 12.1 Trước Ca Chạy

- Kiểm tra nguồn motor và nguồn servo.
- Kiểm tra GND chung.
- Kiểm tra camera chắc chắn, không rung.
- Kiểm tra cơ cấu gạt không kẹt.
- Kiểm tra HC-SR04 không bị che.
- Mở dashboard và kiểm tra video.
- Bấm `Test Push` để kiểm tra servo.
- Bấm `Jog` để kiểm tra băng chuyền.
- Chạy thử 3 đến 5 nắp trước khi chạy chính thức.

### 12.2 Trong Khi Chạy

- Theo dõi FPS và latency.
- Theo dõi counter `Seen`, `Pass`, `Push`, `Timeout`.
- Nếu `Timeout` tăng, kiểm tra cơ cấu gạt và HC-SR04.
- Nếu nhận màu sai, dừng hệ thống và hiệu chỉnh HSV.
- Không đưa tay vào vùng băng chuyền hoặc cơ cấu gạt khi motor đang chạy.

### 12.3 Sau Khi Chạy

- Bấm `Stop`.
- Lưu lại log nếu cần báo cáo.
- Vệ sinh băng chuyền, máng rơi, vùng camera.
- Kiểm tra servo có nóng bất thường không.
- Tắt nguồn công suất.

## 13. Debug Và Xử Lý Lỗi

### 13.1 Không Có Video Camera

Kiểm tra trên Rock5T:

```bash
ls /dev/video*
v4l2-ctl --list-devices
```

Cách xử lý:

- Đảm bảo camera gắn vào Rock5T, không phải Windows PC.
- Nếu camera không phải `/dev/video0`, sửa `camera.device` trong `data/config.json` hoặc `config/default_config.json`.
- Kiểm tra quyền truy cập camera.
- Khởi động lại service.

### 13.2 Dashboard Không Mở Được Từ Windows

Kiểm tra:

- Rock5T và Windows cùng mạng LAN.
- Service đang chạy port `8000`.
- Firewall không chặn port.

Trên Rock5T:

```bash
hostname -I
curl http://127.0.0.1:8000/api/status
```

Trên Windows mở:

```text
http://<ip-rock5t>:8000
```

### 13.3 Không Kết Nối Được Arduino

Kiểm tra:

- Arduino đã nạp firmware đúng.
- USB cắm vào Rock5T.
- Port serial đúng, ví dụ `/dev/ttyACM0` hoặc `/dev/ttyUSB0`.
- User Rock5T có quyền `dialout`.

Cấu hình có thể đặt cụ thể:

```json
{
  "serial": {
    "port": "/dev/ttyACM0"
  }
}
```

### 13.4 Motor Không Chạy

Kiểm tra:

- Nguồn động lực driver.
- GND chung.
- `PU` nối D2, `DR` nối D3, `MF` nối D4.
- Driver có đang ở trạng thái motor-free không.
- Tốc độ có quá cao khiến motor mất bước không.
- Dòng driver đã chỉnh đúng chưa.

Nếu chiều quay sai:

```cpp
const bool DRIVER_DR_INVERTED = true;
```

Nếu enable/free bị ngược:

```cpp
const bool DRIVER_MF_ACTIVE_LOW = false;
```

### 13.5 Servo Gạt Yếu Hoặc Arduino Reset

Nguyên nhân thường gặp:

- Servo lấy nguồn từ Arduino.
- Nguồn 5V servo không đủ dòng.
- GND servo và Arduino nối kém.
- Cơ cấu gạt bị kẹt.

Cách xử lý:

- Dùng nguồn 5V riêng cho servo.
- Nối GND servo với GND Arduino.
- Thêm tụ gần servo nếu cần.
- Kiểm tra cơ khí, giảm tải gạt.

### 13.6 HC-SR04 Không Xác Nhận

Kiểm tra:

- `TRIG` đúng D10, `ECHO` đúng D11.
- Cảm biến đặt đúng hướng máng rơi.
- Vật rơi có đi qua vùng đo không.
- Ngưỡng `<10cm` có phù hợp không.
- Bề mặt vật có phản xạ siêu âm tốt không.

Nếu gạt thật nhưng vẫn `TIMEOUT`, cần chỉnh lại vị trí cảm biến hoặc tăng cửa sổ xác nhận trong firmware.

### 13.7 Nhận Dạng Màu Sai

Kiểm tra:

- Ánh sáng có thay đổi không.
- Camera có auto exposure quá mạnh không.
- Nền băng chuyền có màu gần giống nắp không.
- ROI có bao cả vùng không cần thiết không.
- HSV range có quá rộng không.

Cách xử lý:

- Cố định ánh sáng.
- Thu hẹp ROI.
- Tăng `min_area`.
- Chỉnh lại HSV từng màu.

## 14. Kiểm Thử

### 14.1 Test Phần Cứng Rời

- Đo nguồn motor khi chưa tải và khi chạy.
- Đo nguồn 5V servo khi servo gạt.
- Kiểm tra GND chung.
- Test motor bằng `RUN 1`, `RUN 0`.
- Test tốc độ bằng `SPEED 400`, `SPEED 800`, `SPEED 1200`.
- Test servo bằng `SORT 1 PUSH 0`.
- Test HC-SR04 bằng cách đưa vật qua máng.

### 14.2 Test Phần Mềm

Chạy test Python:

```bash
python -m pytest -q
```

Kỳ vọng:

```text
4 passed
```

Kiểm tra API:

```bash
curl http://127.0.0.1:8000/api/status
```

### 14.3 Test Tích Hợp

- Chạy 30 nắp cho mỗi màu.
- Ghi lại số nhận đúng, sai, timeout.
- Màu allowed phải đi qua.
- Màu reject phải bị gạt.
- Khi gạt thành công phải có `SORT_DONE result=PUSHED`.
- Khi cố tình che HC-SR04 phải có `TIMEOUT`.
- Khi rút mạng Windows, Rock5T vẫn phải tiếp tục chạy local.

### 14.4 Tiêu Chí Đạt Prototype

- Nhận dạng đúng từ 95% trở lên trong ánh sáng cố định.
- FPS camera thật trên Rock5T đạt khoảng 20 FPS trở lên.
- Lệnh gạt phản hồi dưới 200ms khi camera nhìn trực tiếp vùng gạt.
- Không reset Arduino khi servo hoạt động.
- Log có đủ object id, màu, decision, result và lỗi.

## 15. Lưu Ý An Toàn

- Luôn có cách ngắt nguồn motor/servo nhanh khi vận hành mô hình thật.
- Không đưa tay vào vùng băng chuyền khi đang chạy.
- Không chỉnh cơ khí servo khi hệ thống đang cấp nguồn công suất.
- Kiểm tra dòng driver trước khi chạy tải.
- Không để dây motor và dây tín hiệu camera/cảm biến bó sát nhau.
- Không chạy servo tải lớn bằng nguồn Arduino.
- Khi debug phần cứng, ưu tiên chạy từng phần: nguồn, motor, servo, cảm biến, serial, camera, sau đó mới tích hợp toàn hệ thống.

## 16. Trạng Thái Hiện Tại Của Project

Đã có:

- Firmware Arduino điều khiển driver `PU/DR/+5V/MF`, servo, HC-SR04.
- Service Rock5T bằng FastAPI/OpenCV.
- Dashboard Windows qua LAN.
- Video MJPEG realtime.
- WebSocket telemetry.
- HSV calibration trên dashboard.
- SQLite event log.
- Serial protocol rõ ràng.
- Chế độ mô phỏng camera/serial để test khi chưa có phần cứng.
- Test Python cho config và parser trạng thái.

Lệnh chạy nhanh khi phát triển:

```bash
python -m pytest -q
python -m uvicorn rock5t_scada.main:app --host 0.0.0.0 --port 8000
```

Dashboard:

```text
http://127.0.0.1:8000
http://<ip-rock5t>:8000
```
