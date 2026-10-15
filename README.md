# AIVIA Mock 08 – Ngân hàng câu hỏi AI (VOAI)

Đề luyện tập **100 câu trắc nghiệm** mô phỏng vòng sơ loại Olympic AI (Foundation → Olympic),
kèm **database SQLite** quản lý ngân hàng câu hỏi, hệ thống **đăng nhập**, **chấm điểm tự động lưu database**, **bảng xếp hạng** và **chế độ toàn màn hình chống gian lận (tự nộp nếu thoát 3 lần)**.

**Làm bài trực tuyến:** https://nhwbachtik25.github.io/aivia-mock-exam/

> Tài liệu tự biên soạn phục vụ luyện tập. Không phải đề chính thức của VOAI/IOAI.

---

## Tính năng nổi bật

1. **Giao diện thi chuẩn quốc gia:**
   - 100 câu trắc nghiệm (50 câu chọn 1, 50 câu chọn 2–4). Thời gian 180 phút.
   - Bảng phân bổ 100 câu, lọc chuyên đề, đánh dấu câu hỏi.
2. **Tự động phóng to toàn màn hình & Chống gian lận:**
   - Nhấn **"Bắt đầu làm bài"** sẽ tự động kích hoạt chế độ **Toàn màn hình (Fullscreen)**.
   - Theo dõi sự kiện thoát toàn màn hình, chuyển tab hoặc chuyển cửa sổ.
   - **Quy chế thoát 3 lần:** Nếu cố tình thoát toàn màn hình hoặc chuyển tab **đủ 3 lần**, hệ thống sẽ **tự động nộp bài và khóa kết quả** ngay lập tức.
3. **Đăng nhập & Lưu điểm vào Database:**
   - Đăng nhập bằng Email/Mật khẩu hoặc Google (1 chạm).
   - Khi hoàn thành bài thi, điểm số được **máy chủ tự động chấm lại và lưu thẳng vào database SQLite (`database/users.db`)**.
   - Bảng xếp hạng trực tiếp (Leaderboard) vinh danh điểm số và thời gian làm bài.
   - Xem lại lịch sử các lần thi trước của chính mình.

---

## Cấu trúc thư mục

```
.
├── index.html                  # Giao diện đề thi, bảng câu hỏi, modal đăng nhập & xếp hạng
├── database/
│   ├── schema.sql              # Lược đồ SQLite ngân hàng câu hỏi
│   ├── questions.db            # Database SQLite 100 câu hỏi và 13 nguồn
│   ├── questions.json          # Bản JSON câu hỏi (dễ xem diff trên GitHub)
│   ├── users_schema.sql        # Lược đồ SQLite lưu tài khoản, phiên đăng nhập, lịch sử thi
│   ├── users.db                # Database SQLite lưu tài khoản & điểm (tự sinh, gitignore bảo mật)
│   └── example_question.json   # File mẫu để thêm câu hỏi mới
├── server/
│   ├── app.py                  # HTTP API server (Python chuẩn, không cần cài thư viện)
│   └── config.example.json     # Cấu hình cổng port, host, Google Client ID
└── scripts/
    └── db_manager.py           # CLI quản lý ngân hàng câu hỏi
```

---

## Khởi chạy Server trên máy / Mạng LAN

Yêu cầu: **Python 3.10+** (chỉ dùng thư viện chuẩn `sqlite3`, `http.server`, `json`, `hashlib`, không cần `pip install`).

### 1. Chạy server mặc định (cổng 8000)

```bash
python server/app.py
```

Server sẽ mở:
- **Trên máy của bạn:** `http://localhost:8000`
- **Các máy khác trong cùng mạng LAN/Wifi:** `http://<IP_MÁY_BẠN>:8000`

### 2. Đổi cổng (Port) tùy ý

Bạn có thể đổi cổng linh hoạt bằng 1 trong 3 cách:

```bash
# Cách 1: Qua tham số dòng lệnh
python server/app.py --port 8080

# Cách 2: Qua biến môi trường
$env:PORT=8888; python server/app.py   # PowerShell
set PORT=8888 && python server/app.py  # CMD

# Cách 3: Qua file server/config.json
copy server/config.example.json server/config.json
# Sau đó sửa giá trị "port": 8080 trong config.json
```

### 3. Cấu hình đăng nhập bằng Google (Tùy chọn)

1. Tạo OAuth Client ID (Web application) tại [Google Cloud Console](https://console.cloud.google.com/apis/credentials).
2. Thêm `http://localhost:8000` vào mục **Authorized JavaScript origins**.
3. Điền Client ID vào `server/config.json`:
   ```json
   {
     "host": "0.0.0.0",
     "port": 8000,
     "google_client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com"
   }
   ```
4. Khởi động lại `python server/app.py`. Nút "Tiếp tục với Google" sẽ xuất hiện trong giao diện đăng nhập.

---

## Quản lý Ngân hàng câu hỏi (CLI)

```bash
python scripts/db_manager.py stats                          # Thống kê theo chủ đề / mức độ / nguồn
python scripts/db_manager.py list --topic Logic --level Olympic
python scripts/db_manager.py list --search "Bayes"
python scripts/db_manager.py show 22                        # Xem chi tiết + đáp án + giải thích

python scripts/db_manager.py add database/example_question.json   # Thêm câu hỏi
python scripts/db_manager.py delete 101                     # Xóa câu hỏi

python scripts/db_manager.py export-json                    # DB -> database/questions.json
python scripts/db_manager.py import-json                    # database/questions.json -> DB
python scripts/db_manager.py export-html                    # DB -> cập nhật dữ liệu vào index.html
python scripts/db_manager.py init                           # Dựng lại DB từ index.html
```

---

## Lược đồ Database SQLite

### 1. `database/questions.db` (Ngân hàng câu hỏi công khai)
- `sources`: Nguồn tham chiếu (VOAI, NOAI, IOAI, CS188, NIST, ...)
- `questions`: ID, loại (S/M), chuyên đề, độ khó, nội dung, code minh họa, giải thích, kỹ năng.
- `options`: Phương án A–H, cờ đúng/sai `is_correct`.
- `v_questions`: View tra cứu nhanh câu hỏi kèm chuỗi đáp án đúng.

### 2. `database/users.db` (Tài khoản & Điểm thi - được gitignore bảo mật)
- `users`: ID, email, tên, trường, lớp, mật khẩu băm PBKDF2-SHA256, Google Sub ID, ảnh đại diện.
- `sessions`: Token phiên làm việc qua HTTP Cookie (HttpOnly).
- `attempts`: Lượt thi, thời điểm bắt đầu/nộp, điểm số, thời gian làm bài (giây), số lần thoát toàn màn hình, lý do nộp (`manual`, `timeout`, `fullscreen`), chi tiết vi phạm.
- `attempt_answers`: Chi tiết phương án thí sinh chọn cho từng câu của mỗi lượt thi.

---

## Bản quyền

© AIVIA 2026 · Đề nguồn, chương trình và tài liệu tham chiếu thuộc chủ sở hữu tương ứng.
