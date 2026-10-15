# AIVIA Mock 08 – Ngân hàng câu hỏi AI (VOAI) · Live Ranking kiểu Azota

Đề luyện tập **100 câu trắc nghiệm** mô phỏng vòng sơ loại Olympic AI (Foundation → Olympic),
kèm **database SQLite** quản lý ngân hàng câu hỏi, **hệ thống Live Ranking trực tiếp kiểu Azota** (không cần đăng ký tài khoản), **chấm điểm tự động lưu database** và **chế độ toàn màn hình chống gian lận (tự động nộp nếu thoát 3 lần)**.

**Làm bài trực tuyến:** https://nhwbachtik25.github.io/aivia-mock-exam/

> Tài liệu tự biên soạn phục vụ luyện tập. Không phải đề chính thức của VOAI/IOAI.

---

## Tính năng nổi bật

1. **Vào thi ngay kiểu Azota (Không cần tạo tài khoản hay mật khẩu):**
   - Thí sinh chỉ cần điền **Họ và tên** (bắt buộc) cùng **Lớp**, **Trường / SBD** (tùy chọn) ngay trên màn hình chính là vào làm bài ngay.
   - Không cần email, không cần đăng ký tài khoản, không cần mật khẩu.
2. **Bảng xếp hạng trực tiếp (Live Ranking) thẳng trên web:**
   - Khi nộp bài, máy chủ tự động đối chiếu đáp án chuẩn từ `database/questions.db`, chấm điểm độc lập và ghi nhận vào `database/results.db`.
   - Bảng xếp hạng cập nhật theo thời gian thực (Live Ranking): xếp thứ hạng theo **Điểm số cao nhất** và **Thời gian làm bài nhanh nhất**.
   - Có huy hiệu vinh danh top đầu (🥇 Vàng, 🥈 Bạc, 🥉 Đồng), làm nổi bật dòng của thí sinh hiện tại, và hiển thị feed các lượt nộp bài gần nhất.
   - Thí sinh có thể xem lại lịch sử các lần thi của chính mình bất cứ lúc nào.
3. **Tự động toàn màn hình & Chống gian lận nghiêm ngặt:**
   - Nhấn **"Bắt đầu làm bài"** sẽ tự động kích hoạt chế độ **Toàn màn hình (Fullscreen)**.
   - Theo dõi chặt chẽ mọi sự kiện thoát toàn màn hình, chuyển tab hoặc chuyển cửa sổ ứng dụng.
   - **Quy chế 3 lần:** Mỗi lần vi phạm sẽ hiện hộp cảnh báo màu đỏ. Nếu cố tình thoát toàn màn hình hoặc chuyển tab **đủ 3 lần**, hệ thống sẽ **tự động nộp bài và khóa kết quả** với lý do `fullscreen` ngay lập tức!
4. **Chế độ hoạt động linh hoạt:**
   - **Có server (`python server/app.py`):** Lưu điểm vào database SQLite `database/results.db`, chấm điểm server-side và Live Ranking theo thời gian thực.
   - **Offline / GitHub Pages:** Vẫn tự chấm điểm cục bộ và lưu kết quả trên trình duyệt bình thường nếu chưa bật server.

---

## Cấu trúc thư mục

```
.
├── index.html                  # Giao diện đề thi 100 câu, Live Ranking & giám sát toàn màn hình
├── database/
│   ├── schema.sql              # Lược đồ SQLite ngân hàng câu hỏi
│   ├── questions.db            # Database SQLite 100 câu hỏi và 13 nguồn
│   ├── questions.json          # Bản JSON câu hỏi (dễ xem diff trên GitHub)
│   ├── results_schema.sql      # Lược đồ SQLite lưu bài nộp & Live Ranking kiểu Azota
│   └── example_question.json   # File mẫu để thêm câu hỏi mới
├── server/
│   ├── app.py                  # HTTP API server Live Ranking (chỉ dùng Python chuẩn)
│   └── config.example.json     # File mẫu cấu hình cổng port, host (nếu cần)
└── scripts/
    └── db_manager.py           # CLI quản lý ngân hàng câu hỏi
```

---

## Khởi chạy Server trên máy / Mạng LAN

Yêu cầu: **Python 3.10+** (chỉ dùng thư viện chuẩn `sqlite3`, `http.server`, `json`, `socket` – không cần cài thêm `pip`).

### 1. Chạy server mặc định (cổng 8000)

```bash
python server/app.py
```

Server sẽ hiển thị:
- **Truy cập máy này:** `http://localhost:8000`
- **Truy cập từ máy khác trong cùng mạng LAN/Wifi:** `http://<IP_MÁY_BẠN>:8000`

### 2. Đổi cổng (Port) linh hoạt

Bạn có thể đổi cổng tùy ý bằng 1 trong các cách:

```bash
# Cách 1: Qua tham số dòng lệnh
python server/app.py --port 8080

# Cách 2: Qua biến môi trường
$env:PORT=8888; python server/app.py   # PowerShell trên Windows
set PORT=8888 && python server/app.py  # CMD trên Windows
PORT=8888 python server/app.py         # Linux / macOS

# Cách 3: Qua file server/config.json
copy server\config.example.json server\config.json
# Sửa giá trị "port": 8080 trong server/config.json
```

---

## Quản lý Ngân hàng câu hỏi (CLI)

```bash
python scripts/db_manager.py stats                          # Thống kê theo chủ đề / mức độ / nguồn
python scripts/db_manager.py list --topic Logic --level Olympic
python scripts/db_manager.py list --search "Bayes"
python scripts/db_manager.py show 22                        # Xem chi tiết + đáp án + giải thích

python scripts/db_manager.py add database/example_question.json   # Thêm câu hỏi mới
python scripts/db_manager.py delete 101                     # Xóa câu hỏi

python scripts/db_manager.py export-json                    # DB -> database/questions.json
python scripts/db_manager.py import-json                    # database/questions.json -> DB
python scripts/db_manager.py export-html                    # DB -> cập nhật dữ liệu vào index.html
python scripts/db_manager.py init                           # Dựng lại DB từ index.html
```

---

## Lược đồ Database SQLite

### 1. `database/questions.db` (Ngân hàng câu hỏi)
- `sources`: Nguồn tham chiếu (VOAI, NOAI, IOAI, CS188, NIST, ...)
- `questions`: ID, loại (S/M), chuyên đề, độ khó, nội dung, code minh họa, giải thích, kỹ năng.
- `options`: Phương án A–H, cờ đúng/sai `is_correct`.
- `v_questions`: View tra cứu nhanh câu hỏi kèm chuỗi đáp án đúng.

### 2. `database/results.db` (Bài nộp & Live Ranking - được gitignore bảo mật)
- `submissions`:
  - `id`: Mã lượt nộp bài tự tăng.
  - `name`: Họ và tên thí sinh (bắt buộc).
  - `class_name`: Lớp (12 Tin, 11A1, ...).
  - `school`: Trường THPT / SBD.
  - `score`: Số câu đúng (0–100) do máy chủ tự chấm lại từ `questions.db`.
  - `total`: Tổng số câu (100).
  - `duration_sec`: Thời gian làm bài (giây).
  - `exit_count`: Số lần thoát toàn màn hình / rời tab.
  - `submit_reason`: Lý do nộp bài (`manual`: tự nộp, `timeout`: hết giờ, `fullscreen`: vi phạm thoát 3 lần).
  - `submitted_at`: Thời điểm nộp bài.
  - `answers_json`: Toàn bộ đáp án chi tiết của thí sinh.
  - `ip`: Địa chỉ IP của thí sinh.

---

## Bản quyền

© AIVIA 2026 · Đề nguồn, chương trình và tài liệu tham chiếu thuộc chủ sở hữu tương ứng.
