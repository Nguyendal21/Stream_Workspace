# Tài liệu kỹ thuật và hướng dẫn sử dụng phần mềm Master

Tài liệu này mô tả phần mềm Master hiện tại trong file `master_auto.py`. Nội dung được viết theo trạng thái code hiện có, bao gồm kiến trúc, thư viện, chức năng, cách vận hành, ý nghĩa các nút bấm, dữ liệu vào/ra, giao thức với client Rock5T và các lưu ý triển khai.

## 1. Tổng quan hệ thống

Phần mềm Master là ứng dụng chạy trên Windows, dùng để điều khiển và giám sát tối đa 3 client Rock5T trong một hệ thống truyền hình ảnh, âm thanh, vị trí chiến thuật và cảnh báo CBRN.

Các chức năng chính:

- Tự kiểm tra/cài đặt thư viện Python cần thiết trên Windows.
- Kiểm tra và cài GStreamer nếu máy chưa có.
- Chạy WebSocket signaling server cục bộ trên Master tại cổng `8765`.
- Nhận danh sách client Rock5T đang online.
- Ra lệnh client bắt đầu/dừng stream camera và micro.
- Nhận video/audio RTP qua UDP từ client và hiển thị trong giao diện PyQt5.
- Hiển thị camera/micro local của Master.
- Hiển thị telemetry client: pin, loại mạng, tín hiệu, nhiệt CPU, tên thiết bị, trạng thái.
- Hiển thị bản đồ chiến thuật dạng offline/radar 2D với Master ở trung tâm.
- Vẽ đường di chuyển 100 điểm gần nhất cho từng client.
- Nhận dữ liệu cảm biến CBRN từ client, hiển thị panel cảnh báo, ghi SQLite và xuất báo cáo.
- Hiển thị log hệ thống, trạng thái phần cứng và bảng mã lỗi.
- Cung cấp tab Master + cấp trên để chuẩn bị giao diện gọi 2 chiều qua mạng 5G/VPN.

## 2. Cấu trúc file và thư mục

File chính:

- `master_auto.py`: chương trình Master chạy trên Windows.

Các file/thư mục phát sinh khi chạy:

- `device_notes.json`: lưu ghi chú/tên gọi người dùng đặt cho từng client.
- `cbrn_history.sqlite`: cơ sở dữ liệu SQLite lưu lịch sử đo và cảnh báo CBRN.
- `screenshots/`: lưu ảnh chụp màn hình video call.
- `reports/`: lưu báo cáo CBRN xuất ra PDF/Excel/CSV.
- `logs/`: lưu log phiên làm việc khi người dùng bấm lưu log.

File client tương ứng:

- `rock_auto.py`: chương trình chạy trên Rock5T, kết nối về Master và gửi stream/telemetry/GPS/CBRN.

## 3. Thư viện và công nghệ sử dụng

### 3.1. Python và thư viện chuẩn

Phần mềm dùng Python trên Windows. Các thư viện chuẩn chính:

- `sys`, `os`, `subprocess`: kiểm tra môi trường, chạy lệnh cài đặt, gọi GStreamer/taskkill.
- `urllib.request`: tải GStreamer và lấy vị trí AGPS theo IP.
- `time`, `datetime`: timestamp, log, tên file.
- `json`: mã hóa/gỡ mã WebSocket payload.
- `ctypes`: thao tác Win32 để nhúng cửa sổ video GStreamer vào widget PyQt.
- `threading`, `asyncio`: chạy server, tác vụ nền, cập nhật GPS.
- `socket`, `ipaddress`: xác định IP local và phân loại mạng.
- `sqlite3`: lưu lịch sử CBRN.
- `csv`, `html`: xuất báo cáo CSV/HTML/Excel.
- `winsound`: phát âm cảnh báo trên Windows.

### 3.2. Thư viện Python bên ngoài

Ứng dụng tự kiểm tra và cài các thư viện này nếu thiếu:

- `PyQt5`: xây dựng giao diện Windows.
- `websocket-client`: WebSocket client nội bộ để GUI Master kết nối tới signaling server.
- `websockets`: WebSocket server async nhận kết nối từ client Rock5T.
- `pycaw`: điều khiển mute/unmute audio process GStreamer trên Windows.

### 3.3. GStreamer

GStreamer dùng cho luồng camera/micro:

- Master nhận video H265 qua RTP/UDP.
- Master nhận audio OPUS qua RTP/UDP.
- Master hiển thị bằng `d3d11videosink`.
- Master phát camera local bằng `ksvideosrc`.
- Master đọc micro local bằng `wasapisrc`.

Đường dẫn GStreamer được code kiểm tra:

```text
C:\Program Files\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe
```

Nếu chưa có, chương trình tải MSI GStreamer 1.22.8 từ trang chính thức và cài ngầm.

## 4. Kiến trúc chương trình Master

### 4.1. `auto_setup_windows()`

Chạy ngay khi mở `master_auto.py`.

Nhiệm vụ:

- Kiểm tra thư viện Python.
- Cài thư viện thiếu bằng `pip`.
- Kiểm tra GStreamer.
- Tải và cài GStreamer nếu thiếu.
- Sau khi xong mới khởi động giao diện.

Lưu ý vận hành:

- Lần chạy đầu có thể cần Internet.
- Khi cài GStreamer có thể cần quyền Administrator.
- Nếu không cài được GStreamer, chương trình thoát.

### 4.2. `LocalSignalingServer`

Đây là WebSocket server chạy nền trong Master bằng `QThread`, lắng nghe tại:

```text
0.0.0.0:8765
```

Server này là trung tâm điều phối giữa GUI Master và các client Rock5T.

Các dữ liệu server giữ trong RAM:

- `clients`: client đang online, IP, WebSocket object.
- `master_ws`: WebSocket của GUI Master.
- `device_locations`: vị trí GPS mới nhất.
- `device_states`: trạng thái thiết bị/luồng/phần cứng.
- `device_telemetry`: pin/mạng/tín hiệu/CPU/tên thiết bị.
- `device_cbrn`: dữ liệu CBRN mới nhất.

Các action WebSocket server xử lý:

- `register_client`: client Rock5T đăng ký vào hệ thống.
- `register_master`: GUI Master đăng ký để nhận danh sách client và dữ liệu realtime.
- `get_client_list`: GUI yêu cầu refresh danh sách client.
- `request_connect`: Master yêu cầu một client bắt đầu stream.
- `stop_stream`: Master yêu cầu client dừng stream.
- `client_log`: client gửi log/phần cứng về Master.
- `error_alert`: client báo lỗi.
- `telemetry_update`: client gửi pin/mạng/tín hiệu/nhiệt CPU/tên/trạng thái.
- `cbrn_update`: client gửi dữ liệu cảm biến CBRN.
- `gps_update`: client gửi vị trí GPS/AGPS.

### 4.3. Smart routing LAN/VPN

Khi Master yêu cầu client stream, server tự chọn IP Master để gửi xuống client.

Logic hiện tại:

- Nếu `remote_ip` của client thuộc dải private như `192.168.x.x`, `10.x.x.x`, `172.x.x.x`, Master chọn `MASTER_LAN_IP`.
- Nếu không, Master chọn `MASTER_VPN_IP`.

Mục tiêu:

- Ưu tiên LAN/Wi-Fi nội bộ khi cùng mạng.
- Dùng VPN/Tailscale/5G khi client ở ngoài LAN.

Các biến chính:

```python
MASTER_VPN_IP = "100.92.168.67"
MASTER_LAN_IP = get_local_ip()
VPS_URL = "ws://127.0.0.1:8765"
```

### 4.4. `WebSocketThread`

Đây là WebSocket client chạy bên trong GUI Master. Nó kết nối tới server cục bộ:

```text
ws://127.0.0.1:8765
```

Nhiệm vụ:

- Đăng ký GUI Master với action `register_master`.
- Nhận `update_list` để cập nhật Tab 1.
- Nhận `gps_update` để cập nhật bản đồ.
- Nhận `telemetry_update` để cập nhật thông tin dưới ô video.
- Nhận `cbrn_update` để cập nhật panel CBRN.
- Gửi `request_connect`, `stop_stream`, `get_client_list`.

### 4.5. `CameraCell`

Widget dùng cho từng ô video.

Mỗi ô có:

- Vùng video đen để nhúng cửa sổ GStreamer.
- Tiêu đề ô.
- Dòng thông tin thiết bị.
- Nút bật/tắt hình.
- Nút bật/tắt tiếng.
- Nút phóng to/thu nhỏ.
- Nút ngắt kết nối hoặc bật camera Master.

Khi stream client:

- Master mở pipeline nhận H265/OPUS qua UDP.
- Video dùng `d3d11videosink`.
- Audio dùng `wasapisink`.
- Cửa sổ GStreamer được tìm bằng PID và nhúng vào widget bằng Win32 API.

### 4.6. `GpsMapWidget`

Widget bản đồ chiến thuật tự vẽ bằng `QPainter`.

Đặc điểm hiện tại:

- Không dùng tile Google thật trong code hiện tại.
- Nền là lưới/radar 2D offline.
- Master nằm ở chính giữa màn hình, marker màu đỏ.
- Client hiển thị xung quanh Master theo sai lệch lat/lng.
- Mỗi client có một màu trong danh sách:

```text
Client 1: xanh lá
Client 2: cam
Client 3: tím
```

- Mỗi client lưu tối đa 100 điểm gần nhất để vẽ polyline.
- Khi CBRN alarm, marker client chuyển thành biểu tượng nguy hiểm đỏ nhấp nháy.
- Có chức năng fit map về vùng chứa Master và client.
- Có chức năng cập nhật vị trí Master theo IP-AGPS qua `http://ip-api.com/json/`.

### 4.7. `CBRNDatabase`

Quản lý SQLite file:

```text
cbrn_history.sqlite
```

Bảng chính:

```sql
cbrn_measurements
```

Các cột:

- `id`
- `timestamp`
- `device_id`
- `sensor`
- `status`
- `agent`
- `concentration`
- `unit`
- `level`
- `acknowledged`
- `raw_json`

Chức năng:

- Tạo bảng nếu chưa có.
- Ghi dữ liệu đo/cảnh báo.
- Đánh dấu tất cả đã xác nhận.
- Truy vấn theo khung giờ.
- Xuất PDF, Excel HTML hoặc CSV.

### 4.8. `CBRNPanel`

Panel CBRN luôn hiển thị phía dưới các tab chính.

Cấu trúc:

- 3 cột tương ứng tối đa 3 client.
- 2 dòng tương ứng cảm biến:
  - `SVG-2`
  - `RAID-M100`

Mỗi ô cảm biến hiển thị:

- Tên client + tên cảm biến.
- Trạng thái: OK/Cảnh báo/Lỗi/Mất kết nối.
- Tác nhân phát hiện.
- Nồng độ.
- Đơn vị.
- Thanh mức độ `LEVEL 0/8` đến `LEVEL 8/8`.

Khi có cảnh báo:

- Ô cảm biến chuyển đỏ và nhấp nháy.
- Phát âm thanh cảnh báo Windows.
- Ghi dữ liệu vào SQLite.
- Hiện system tray notification.
- Marker trên bản đồ của client đó chuyển sang cảnh báo đỏ.

### 4.9. `MasterGUI`

Lớp giao diện chính.

Giao diện dùng `QSplitter(Qt.Vertical)`:

- Phần trên: `QTabWidget` chứa các tab chính.
- Phần dưới: `CBRNPanel` luôn hiển thị.

Người dùng có thể kéo splitter để tăng/giảm chiều cao khu vực CBRN.

## 5. Các tab trong phần mềm

## 5.1. Tab 1 - `1. Clients`

Mục đích:

- Xem danh sách client đang online.
- Ghi chú/tên gọi client.
- Bắt đầu kết nối stream với từng client.

Bảng gồm 6 cột:

| Cột | Ý nghĩa |
|---|---|
| STT | Số thứ tự trong danh sách hiện tại |
| ID Client (MAC) | ID client theo MAC, ví dụ `ROCK-ABCDEF...` |
| IP Noi bo | IP client tự báo về Master |
| IP Internet/5G | IP remote mà Master thấy qua socket |
| Ghi chu | Tên gọi/ghi chú người dùng nhập |
| Thao tac | Nút bắt đầu kết nối |

### Nút `Refresh`

Ý nghĩa:

- Yêu cầu server nội bộ gửi lại danh sách client mới nhất.

Khi bấm:

- GUI gửi action `get_client_list` tới WebSocket server cục bộ.
- Server trả `update_list`.
- Bảng client được render lại.
- Panel CBRN cập nhật mapping client theo thứ tự mới.

Phím tắt:

```text
F5
```

### Nút `Luu ghi chu`

Ý nghĩa:

- Lưu nội dung cột `Ghi chu` vào file `device_notes.json`.

Khi bấm:

- Chương trình đọc từng dòng trong bảng.
- Lấy `device_id` và ghi chú.
- Ghi JSON ra `device_notes.json`.
- Cập nhật tên hiển thị trong panel CBRN.
- Hiện hộp thoại báo lưu thành công.

Phím tắt:

```text
Ctrl+S
```

### Nút `Bat dau ket noi`

Ý nghĩa:

- Yêu cầu client tương ứng bắt đầu phát stream camera/micro về Master.

Khi bấm:

1. Master lấy `device_id` của dòng đó.
2. Đưa `device_id` vào bộ nhớ auto-resume.
3. Tìm một ô trống trong 3 ô client ở Tab 2.
4. Tính cặp cổng UDP:
   - Client slot 1: video `5000`, audio `5001`
   - Client slot 2: video `5002`, audio `5003`
   - Client slot 3: video `5004`, audio `5005`
5. GUI gửi action `request_connect` tới server.
6. Server chọn LAN/VPN IP phù hợp rồi gửi `start_stream` xuống client.
7. Master chuyển sang Tab 2.
8. Ô client bắt đầu chạy pipeline GStreamer nhận stream.

Nếu đã đủ 3 client:

- Hiện cảnh báo quá tải.
- Người dùng cần ngắt một luồng trước khi kết nối client khác.

## 5.2. Tab 2 - `2. Video call`

Mục đích:

- Hiển thị video/audio Master và 3 client.
- Điều khiển hình/tiếng/phóng to/ngắt kết nối.
- Chọn chế độ liên lạc.
- Chụp màn hình phiên video.

Giao diện:

- 4 ô video:
  - Ô 1: Master local.
  - Ô 2: Client 1.
  - Ô 3: Client 2.
  - Ô 4: Client 3.
- Thanh chọn chế độ liên lạc phía trên.
- Nút chụp màn hình.

### 6 chế độ liên lạc

Các nút:

- `Hoi thoai nhom`
- `Broadcast`
- `Rieng Client 1`
- `Rieng Client 2`
- `Rieng Client 3`
- `Tat mic chi huy`

Hiện trạng code:

- Khi bấm, chương trình lưu chế độ hiện tại vào `self.current_audio_mode`.
- Ghi log chế độ vào Debug.
- Chưa triển khai routing audio/mix thật theo từng chế độ.

Ý nghĩa thiết kế:

- `Hoi thoai nhom`: Master và 3 client cùng hội thoại.
- `Broadcast`: Master phát lệnh xuống tất cả client.
- `Rieng Client 1/2/3`: Master nói riêng với client được chọn.
- `Tat mic chi huy`: tắt micro phía Master.

Để triển khai audio routing thật, cần bổ sung luồng gửi audio từ Master về client và logic mute/mix hai chiều.

### Nút `Chup man hinh`

Khi bấm:

- Chụp khu vực Tab 2.
- Lưu file PNG vào thư mục `screenshots/`.
- Tên file dạng:

```text
video_call_YYYYMMDD_HHMMSS.png
```

Phím tắt:

```text
F12
```

### Ô Master local

Nút chính:

- `Bật Camera Master`
- Sau khi bật đổi thành `Tắt Camera/Micro`.

Khi bật:

- Chạy GStreamer pipeline:
  - `ksvideosrc` lấy camera Windows.
  - `d3d11videosink` hiển thị video.
  - `wasapisrc` lấy micro local, nhưng hiện đưa vào `fakesink`.

Khi tắt:

- Dừng process GStreamer.
- Giải phóng cửa sổ video.

### Nút `Tắt Hình` / `Bật Hình`

Khi bấm:

- Không dừng stream.
- Chỉ ẩn/hiện cửa sổ video GStreamer đã nhúng vào ô.

### Nút `Tắt Tiếng` / `Bật Tiếng`

Khi bấm:

- Dùng `pycaw` tìm audio session theo PID process GStreamer.
- Mute/unmute audio process đó.
- Không gửi lệnh về client.

### Nút `Phóng To` / `Thu Nhỏ`

Khi bấm:

- Nếu phóng to: ẩn các ô còn lại, chỉ giữ ô đang chọn.
- Nếu thu nhỏ: hiện lại tất cả ô.

### Nút `Ngắt Kết Nối`

Đối với client:

1. Xóa client khỏi bộ nhớ auto-resume.
2. Gửi action `stop_stream` xuống client.
3. Đặt `current_device_id = None`.
4. Dừng pipeline nhận stream trên Master.
5. Ô quay về trạng thái chờ kết nối.

Đối với Master local:

- Nút này dùng để bật/tắt camera/micro local.

### Auto-resume client

Khi client bị rớt mạng:

- Server phát signal client disconnected.
- Ô video dừng stream local.
- Tiêu đề ô đổi sang trạng thái mất mạng/chờ phục hồi.
- `current_device_id` vẫn được giữ để dành slot.

Khi client online lại:

- Nếu client vẫn nằm trong `auto_resume_devices`, Master tự gửi lại `request_connect`.
- Ô video khởi động lại GStreamer với đúng cổng cũ.

## 5.3. Tab 3 - `3. Ban do chien thuat`

Mục đích:

- Theo dõi vị trí Master và client.
- Xem đường di chuyển.
- Hiển thị cảnh báo CBRN trực tiếp trên marker client.

Giao diện:

- Thanh nút phía trên.
- Bản đồ radar 2D phía dưới.

### Nút `Tai ban do`

Hiện trạng code:

- Gọi `fetch_master_gps()`.
- Thử cập nhật tọa độ Master qua IP-AGPS từ `http://ip-api.com/json/`.
- Hiện thông báo rằng nguồn tile offline/API có thể cấu hình thêm khi có gói bản đồ hợp lệ.

Lưu ý:

- Code hiện tại chưa tích hợp tile Google Map offline thật.
- Đây là khung/hook để sau này gắn bộ tile offline hoặc API bản đồ.

### Nút `Ve trung tam`

Khi bấm:

- Tính vùng chứa Master và các client có tọa độ hợp lệ.
- Điều chỉnh `scale` để fit các điểm vào màn hình.
- Nếu chưa có client hợp lệ, scale quay về mặc định.

### Marker Master

- Luôn nằm giữa màn hình.
- Màu đỏ.
- Hiển thị tọa độ GPS/AGPS hiện tại.

### Marker client

- Hiển thị theo sai lệch lat/lng so với Master.
- Mỗi client có màu riêng.
- Hiển thị tốc độ và thời điểm cập nhật gần nhất.

### Polyline di chuyển

- Mỗi client lưu tối đa 100 điểm gần nhất.
- Khi có điểm mới, chương trình nối các điểm bằng đường màu theo client.

### Cảnh báo CBRN trên bản đồ

Khi client có alarm CBRN:

- Marker client chuyển thành biểu tượng nguy hiểm màu đỏ.
- Biểu tượng nhấp nháy theo timer.

Khi alarm được xóa hoặc xác nhận:

- Marker quay về màu client bình thường.

## 5.4. Tab 4 - `4. CBRN timeline`

Mục đích:

- Xem lại lịch sử đo và cảnh báo CBRN theo khung giờ.
- Xuất báo cáo.

Bảng gồm 9 cột:

| Cột | Ý nghĩa |
|---|---|
| Thoi gian | Timestamp bản ghi |
| Client | ID client |
| Cam bien | Tên cảm biến |
| Trang thai | OK/Cảnh báo/Lỗi/Mất kết nối |
| Tac nhan | Tác nhân phát hiện nếu có |
| Nong do | Giá trị đo |
| Don vi | ppm, mg/m3 hoặc đơn vị cảm biến gửi |
| Level | Mức nguy hiểm 0-8 |
| Da xac nhan | 0 hoặc 1 |

### Bộ lọc `Tu` / `Den`

Người dùng chọn khung thời gian cần xem lại.

### Nút `Tai timeline`

Khi bấm:

- Truy vấn SQLite theo khung giờ.
- Lấy tối đa 1000 bản ghi mới nhất.
- Render lại bảng timeline.

### Nút `Xuat PDF/Excel`

Khi bấm:

- Mở hộp thoại chọn file.
- Hỗ trợ:
  - PDF `.pdf`
  - Excel HTML `.xls`
  - CSV `.csv`
- Dữ liệu xuất theo khung giờ đang chọn.

File mặc định lưu trong:

```text
reports/
```

## 5.5. Tab 5 - `5. Master + Cap tren`

Mục đích:

- Chuẩn bị giao diện liên lạc giữa Master và cấp trên qua 5G/VPN.
- Hiển thị thông tin xe chỉ huy.
- Có mini map vị trí xe.
- Có hai khung video cho Master và cấp trên.

Thông tin xe chỉ huy:

- Tọa độ GPS.
- Loại mạng.
- Tốc độ.
- Hướng.

Hiện trạng code:

- Tọa độ lấy từ `gps_map.master_pos`.
- Mạng hiển thị `MASTER_LAN_IP` và `MASTER_VPN_IP`.
- Tốc độ hiện là `0 km/h`.
- Hướng hiện là `--`.

### Khung video

- Khung trái: Camera Master.
- Khung phải: Video cấp trên.

Hiện trạng:

- Đã có UI và widget video.
- Chưa có signaling/giao thức gọi thật với cấp trên.
- Chưa có stream 2 chiều thật tới endpoint cấp trên.

### Ô `ID cap tren`

Người dùng nhập ID cấp trên cần gọi.

### Nút `Goi`

Khi bấm:

- Nếu chưa nhập ID, hiện cảnh báo.
- Nếu có ID:
  - Cập nhật trạng thái `Dang goi <ID>`.
  - Cập nhật thông tin khung video cấp trên.
  - Ghi log Debug.

### Nút `Ket thuc`

Khi bấm:

- Đổi trạng thái sang `Da ket thuc`.
- Dừng stream khung cấp trên nếu đang có.
- Ghi log Debug.

## 5.6. Tab 6 - `6. Debug & Htop`

Mục đích:

- Theo dõi trạng thái toàn hệ thống.
- Xem log realtime.
- Lưu log phiên.
- Tra bảng mã lỗi cơ bản.

### Nút `Luu log phien`

Khi bấm:

- Mở hộp thoại chọn đường dẫn file.
- Mặc định lưu vào `logs/`.
- Tên mặc định:

```text
session_YYYYMMDD_HHMMSS.log
```

- Ghi toàn bộ nội dung log hiện tại trong ô debug ra file.

### Bảng Htop thiết bị

Bảng gồm 8 cột:

| Cột | Ý nghĩa |
|---|---|
| Device ID | ID client |
| IP Address | IP client |
| Trang thai | Trạng thái stream/kết nối |
| Phan cung | Camera/Micro/CBRN |
| Pin | Pin hoặc nguồn |
| Mang | Loại mạng |
| Tin hieu | Cường độ tín hiệu |
| CPU/Nhiet | Nhiệt CPU |

Màu trạng thái:

- Đỏ: đang phát hoặc trạng thái nghiêm trọng.
- Vàng: chờ thiết bị.
- Xanh: sẵn sàng/bình thường.

### Vùng log

Hiển thị:

- Server khởi động.
- Client đăng ký/ngắt kết nối.
- Yêu cầu stream.
- Lỗi hệ thống.
- Chế độ liên lạc.
- Cảnh báo CBRN.
- Đường dẫn ảnh chụp/log/báo cáo.

### Bảng mã lỗi

Các mã hiện có:

| Mã | Ý nghĩa | Gợi ý xử lý |
|---|---|---|
| NET-01 | Mất kết nối client | Kiểm tra Wi-Fi/5G/Tailscale và refresh |
| AV-01 | Thiếu camera | Kiểm tra camera USB/driver/quyền thiết bị |
| AV-02 | Thiếu micro | Kiểm tra input audio/driver |
| GPS-01 | Không có tọa độ | Kiểm tra AGPS/GPS và tín hiệu mạng |
| CBRN-01 | Cảnh báo tác nhân | Xác nhận đã xem, ghi nhận vị trí, xuất báo cáo |
| DB-01 | Không ghi được SQLite | Kiểm tra quyền ghi thư mục chương trình |

## 6. Panel CBRN cố định

Panel CBRN nằm bên dưới các tab, luôn hiển thị để người vận hành không bỏ lỡ cảnh báo.

### Bố cục

- 3 cột: tối đa 3 client.
- 2 dòng:
  - SVG-2
  - RAID-M100

### Mỗi ô cảm biến hiển thị

- Tên client/tên ghi chú.
- Tên cảm biến.
- Trạng thái.
- Tác nhân.
- Nồng độ.
- Đơn vị.
- Thanh `LEVEL`.

### Nút `Xac nhan da xem`

Khi bấm:

1. Xóa danh sách alarm đang nhấp nháy trong RAM.
2. Dừng âm thanh cảnh báo.
3. Cập nhật SQLite: `acknowledged = 1`.
4. Refresh timeline nếu Tab 4 đã mở.
5. Các ô alarm ngừng nhấp nháy.

### Nút `Xuat bao cao`

Khi bấm:

- Xuất báo cáo CBRN theo khung giờ trên panel.
- Hỗ trợ PDF, Excel HTML, CSV.
- File mặc định trong `reports/`.

### Nút `Thu gon` / `Mo rong`

Khi bấm:

- Ẩn/hiện lưới cảm biến.
- Giữ thanh header CBRN để người dùng có thể mở lại.

## 7. Luồng dữ liệu giữa Master và client

## 7.1. Client đăng ký

Client gửi:

```json
{
  "action": "register_client",
  "device_id": "ROCK-<MAC>",
  "ip": "192.168.x.x",
  "device_name": "Client 1"
}
```

Master xử lý:

- Lưu client vào `self.clients`.
- Tạo trạng thái ban đầu.
- Gửi lại danh sách client cho GUI Master.
- Phát signal client connected để auto-resume nếu cần.

## 7.2. Master đăng ký GUI

GUI Master gửi:

```json
{
  "action": "register_master"
}
```

Server xử lý:

- Lưu `master_ws`.
- Gửi log server sẵn sàng.
- Gửi danh sách client hiện tại.

## 7.3. Bắt đầu stream

GUI Master gửi tới server:

```json
{
  "action": "request_connect",
  "target_device_id": "ROCK-...",
  "video_port": 5000,
  "audio_port": 5001
}
```

Server gửi xuống client:

```json
{
  "action": "start_stream",
  "master_ip": "<LAN hoặc VPN IP>",
  "video_port": 5000,
  "audio_port": 5001
}
```

Client sau đó phát:

- Video H265 RTP tới `master_ip:video_port`.
- Audio OPUS RTP tới `master_ip:audio_port`.

Master đồng thời mở pipeline nhận đúng cặp port.

## 7.4. Dừng stream

GUI Master gửi:

```json
{
  "action": "stop_stream",
  "target_device_id": "ROCK-..."
}
```

Server chuyển tiếp xuống client:

```json
{
  "action": "stop_stream"
}
```

Client dừng GStreamer.

Master dừng pipeline nhận stream.

## 7.5. Telemetry

Client gửi:

```json
{
  "action": "telemetry_update",
  "device_id": "ROCK-...",
  "battery": "85%",
  "network": "Wi-Fi",
  "signal": "-55 dBm",
  "cpu_temp": "48.2 C",
  "device_name": "Client 1",
  "status": "San sang",
  "hw": "Camera (ok); Micro (ok); CBRN (configured)"
}
```

Master dùng dữ liệu này để:

- Cập nhật dòng thông tin dưới ô video.
- Cập nhật Htop.
- Cập nhật trạng thái thiết bị trong Debug.

## 7.6. GPS

Client gửi:

```json
{
  "action": "gps_update",
  "device_id": "ROCK-...",
  "lat": 21.028511,
  "lng": 105.854165,
  "speed": 12.5,
  "heading": "90",
  "timestamp": "2026-06-12 12:00:00"
}
```

Master dùng dữ liệu này để:

- Cập nhật marker client trên bản đồ.
- Thêm điểm vào polyline.
- Hiển thị tốc độ và thời điểm cập nhật.

## 7.7. CBRN

Client có thể gửi một cảm biến:

```json
{
  "action": "cbrn_update",
  "device_id": "ROCK-...",
  "sensor": "SVG-2",
  "status": "Canh bao",
  "agent": "TEST",
  "concentration": "1.2",
  "unit": "ppm",
  "level": 6
}
```

Hoặc gửi nhiều cảm biến:

```json
{
  "action": "cbrn_update",
  "device_id": "ROCK-...",
  "timestamp": "2026-06-12 12:00:00",
  "sensors": [
    {
      "sensor": "SVG-2",
      "status": "OK",
      "agent": "",
      "concentration": "0",
      "unit": "ppm",
      "level": 0
    },
    {
      "sensor": "RAID-M100",
      "status": "Canh bao",
      "agent": "Unknown",
      "concentration": "0.8",
      "unit": "mg/m3",
      "level": 5
    }
  ]
}
```

Master xử lý:

- Chuẩn hóa sensor về `SVG-2` hoặc `RAID-M100`.
- Ghi SQLite.
- Cập nhật panel CBRN.
- Nếu status là alarm/cảnh báo:
  - Nhấp nháy ô.
  - Phát âm thanh.
  - Hiện tray notification.
  - Đổi marker bản đồ sang biểu tượng nguy hiểm.

## 8. Hướng dẫn vận hành cơ bản

### 8.1. Chuẩn bị Master

1. Cài Python trên Windows.
2. Đặt `master_auto.py` trong thư mục chạy.
3. Đảm bảo máy có Internet cho lần chạy đầu nếu thiếu thư viện/GStreamer.
4. Kiểm tra firewall Windows cho phép:
   - WebSocket TCP `8765`.
   - UDP nhận stream:
     - `5000-5005`.
5. Chạy:

```powershell
python master_auto.py
```

### 8.2. Chuẩn bị client

1. Chạy `rock_auto.py` trên Rock5T.
2. Đảm bảo client biết IP Master:
   - `MASTER_LAN_IP`
   - `MASTER_VPN_IP`
3. Đảm bảo client kết nối được tới Master cổng `8765`.
4. Client sẽ tự đăng ký vào danh sách.

### 8.3. Kết nối video client

1. Mở Tab 1.
2. Bấm `Refresh` nếu chưa thấy client.
3. Nhập ghi chú nếu cần.
4. Bấm `Luu ghi chu`.
5. Bấm `Bat dau ket noi` ở client cần xem.
6. Phần mềm chuyển sang Tab 2 và mở ô video.

### 8.4. Ngắt video client

1. Mở Tab 2.
2. Tại ô client, bấm `Ngắt Kết Nối`.
3. Master gửi lệnh dừng stream xuống client.
4. Ô video quay về trạng thái chờ.

### 8.5. Theo dõi bản đồ

1. Mở Tab 3.
2. Bấm `Ve trung tam` để fit Master và client.
3. Nếu vị trí Master chưa đúng, bấm `Tai ban do` để cập nhật IP-AGPS.
4. Quan sát marker client và đường di chuyển.

### 8.6. Xử lý cảnh báo CBRN

Khi có cảnh báo:

1. Panel CBRN phía dưới chuyển đỏ/nhấp nháy.
2. Windows phát âm cảnh báo.
3. System tray hiện notification.
4. Marker trên bản đồ đổi sang biểu tượng nguy hiểm.
5. Người vận hành kiểm tra client, cảm biến, tác nhân, nồng độ, level.
6. Bấm `Xac nhan da xem` khi đã tiếp nhận cảnh báo.
7. Mở Tab 4 để xem lại timeline.
8. Bấm `Xuat PDF/Excel` hoặc `Xuat bao cao` để lưu hồ sơ.

### 8.7. Lưu log phiên

1. Mở Tab 6.
2. Bấm `Luu log phien`.
3. Chọn đường dẫn hoặc giữ mặc định trong `logs/`.

## 9. Cổng mạng và dữ liệu truyền thông

### 9.1. TCP

| Cổng | Giao thức | Mục đích |
|---|---|---|
| 8765 | WebSocket TCP | Signaling Master/client |

### 9.2. UDP

| Cổng | Mục đích |
|---|---|
| 5000 | Video client slot 1 |
| 5001 | Audio client slot 1 |
| 5002 | Video client slot 2 |
| 5003 | Audio client slot 2 |
| 5004 | Video client slot 3 |
| 5005 | Audio client slot 3 |

Firewall cần cho phép các cổng trên.

## 10. Dữ liệu lưu trữ

### 10.1. Ghi chú client

File:

```text
device_notes.json
```

Dạng:

```json
{
  "ROCK-001122AABBCC": "Client 1"
}
```

### 10.2. SQLite CBRN

File:

```text
cbrn_history.sqlite
```

Mỗi bản ghi được tạo khi Master nhận `cbrn_update`.

### 10.3. Ảnh chụp

Thư mục:

```text
screenshots/
```

### 10.4. Báo cáo

Thư mục:

```text
reports/
```

Định dạng:

- `.pdf`
- `.xls`
- `.csv`

### 10.5. Log phiên

Thư mục:

```text
logs/
```

## 11. Trạng thái tính năng hiện tại

Đã có trong code:

- UI Master đầy đủ 6 tab.
- Panel CBRN cố định.
- WebSocket signaling server.
- Client list.
- Ghi chú client.
- Start/stop stream client.
- Nhận camera/micro client qua GStreamer.
- Camera local Master.
- Điều khiển mute audio process.
- Phóng to/thu nhỏ ô video.
- Chụp màn hình.
- Telemetry.
- GPS/radar map.
- Polyline 100 điểm.
- Alarm CBRN, âm thanh, tray notification.
- SQLite CBRN.
- Timeline và xuất báo cáo.
- Debug/Htop/log.
- Auto-resume stream khi client reconnect.

Đang là khung/hook, chưa phải tích hợp thật hoàn chỉnh:

- Google Map offline/tile thật.
- Gọi 2 chiều với cấp trên qua 5G.
- Audio routing thật cho 6 chế độ liên lạc.
- Điều khiển bật/tắt camera/micro từ Master xuống client ở mức thiết bị; hiện nút chỉ ẩn hình hoặc mute audio local process trên Master.
- AGPS qua cột sóng có độ chính xác phụ thuộc nguồn dữ liệu client; Master hiện có IP-AGPS cơ bản cho chính Master.

## 12. Lỗi thường gặp và cách xử lý

### Không thấy client trong Tab 1

Kiểm tra:

- Client đã chạy `rock_auto.py` chưa.
- Client có ping/telnet tới Master cổng `8765` được không.
- Firewall Windows có chặn cổng `8765` không.
- `MASTER_LAN_IP`/`MASTER_VPN_IP` trong client đã đúng chưa.
- Bấm `Refresh`.

### Bấm kết nối nhưng không có hình

Kiểm tra:

- GStreamer đã cài đúng trên Master.
- Client có camera không.
- Firewall Windows có chặn UDP `5000-5005` không.
- Client có log thiếu camera/micro ở Tab 6 không.
- Master và client có cùng đường mạng LAN/VPN đúng không.

### Có hình nhưng không có tiếng

Kiểm tra:

- Client có micro không.
- Audio UDP port có bị chặn không.
- Nút `Bật Tiếng/Tắt Tiếng` trong ô video.
- Windows audio output.
- `pycaw` có mute process GStreamer không.

### Bản đồ không có vị trí client

Kiểm tra:

- Client có gửi `gps_update` không.
- Tọa độ client có khác `0.0, 0.0` không.
- Client có GPS/gpsd/mmcli hoặc cấu hình fallback không.

### Không có cảnh báo CBRN

Kiểm tra:

- Client có gửi `cbrn_update` không.
- Tên sensor có đúng `SVG-2` hoặc `RAID-M100` không.
- Status có chứa `Canh bao`, `alarm`, `alert`, `warning` không.
- SQLite có quyền ghi không.

### Không xuất được báo cáo

Kiểm tra:

- Thư mục `reports/` có quyền ghi không.
- File đang mở bởi chương trình khác không.
- Nếu PDF lỗi, thử xuất CSV.

## 13. Gợi ý kiểm tra nhanh

### Kiểm tra cú pháp

```powershell
python -m py_compile master_auto.py
```

### Chạy Master

```powershell
python master_auto.py
```

### Kiểm tra cổng WebSocket

Trên Windows PowerShell:

```powershell
netstat -ano | findstr 8765
```

### Kiểm tra UDP stream

Khi đang xem client, kiểm tra process GStreamer:

```powershell
Get-Process | Where-Object { $_.ProcessName -like "*gst*" }
```

## 14. Gợi ý phát triển tiếp

Các hướng nên phát triển tiếp để hoàn thiện hệ thống:

- Tách cấu hình `MASTER_VPN_IP`, cổng, thư mục lưu trữ ra file `.json` hoặc `.env`.
- Bổ sung xác thực WebSocket để tránh client lạ đăng ký vào hệ thống.
- Thêm heartbeat/timeout rõ ràng cho telemetry và CBRN.
- Thêm lưu session vận hành riêng theo ngày/ca.
- Tích hợp tile map offline thật, ví dụ MBTiles hoặc server tile local.
- Hoàn thiện audio uplink/downlink để 6 chế độ liên lạc hoạt động thật.
- Hoàn thiện signaling cho Tab 5 Master + cấp trên.
- Thêm nút test CBRN giả lập trong Debug để huấn luyện.
- Thêm cơ chế replay timeline CBRN + GPS theo thời gian.
- Thêm phân quyền người vận hành.

## 15. Tóm tắt vận hành một phiên mẫu

1. Chạy `master_auto.py` trên Windows.
2. Chạy `rock_auto.py` trên từng Rock5T.
3. Mở Tab 1, bấm `Refresh`.
4. Đặt ghi chú cho client, bấm `Luu ghi chu`.
5. Bấm `Bat dau ket noi` với client cần xem.
6. Theo dõi video ở Tab 2.
7. Theo dõi bản đồ ở Tab 3.
8. Theo dõi CBRN ở panel dưới cùng.
9. Khi có alarm, xác minh, ghi nhận, bấm `Xac nhan da xem`.
10. Mở Tab 4 để xuất báo cáo nếu cần.
11. Mở Tab 6 để lưu log phiên.

