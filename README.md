# AIVIA Mock 08 – Ngân hàng câu hỏi AI (VOAI)

Đề luyện tập **100 câu trắc nghiệm** mô phỏng vòng sơ loại Olympic AI (Foundation → Olympic),
kèm **database SQLite** để quản lý ngân hàng câu hỏi.

**Làm bài online:** https://nhwbachtik25.github.io/aivia-mock-exam/

> Tài liệu tự biên soạn phục vụ luyện tập. Không phải đề chính thức của VOAI/IOAI.

## Cấu trúc thư mục

```
.
├── index.html                  # Đề thi (mở trực tiếp bằng trình duyệt / GitHub Pages)
├── database/
│   ├── schema.sql              # Lược đồ SQLite
│   ├── questions.db            # Database SQLite (100 câu, 13 nguồn)
│   ├── questions.json          # Bản JSON dễ đọc / dễ xem diff trên GitHub
│   └── example_question.json   # Mẫu để thêm câu hỏi mới
└── scripts/
    └── db_manager.py           # CLI quản lý database (chỉ dùng thư viện chuẩn Python)
```

## Lược đồ database

| Bảng          | Mô tả                                                                 |
|---------------|-----------------------------------------------------------------------|
| `sources`     | Nguồn tham khảo: `code`, `title`, `url`                                |
| `questions`   | Câu hỏi: `id`, `kind` (S/M), `topic`, `level`, `question`, `code`, `explanation`, `skill`, `source_code` |
| `options`     | Phương án: `question_id`, `label` (A–H), `position`, `text`, `is_correct` |
| `v_questions` | View: mỗi câu kèm chuỗi đáp án đúng, ví dụ `B,C,G`                     |

- `kind = 'S'`: một đáp án đúng · `kind = 'M'`: nhiều đáp án đúng
- `topic`: ML/DL, Logic, Code, Thực tế, Đạo đức
- `level`: Nền tảng, Trung bình, Nâng cao, Olympic

## Sử dụng

Yêu cầu: Python 3.10+ (không cần cài thư viện nào).

```bash
python scripts/db_manager.py stats                          # thống kê theo chủ đề / mức độ / nguồn
python scripts/db_manager.py list --topic Logic --level Olympic
python scripts/db_manager.py list --search "Bayes"
python scripts/db_manager.py show 22                        # xem chi tiết + đáp án + giải thích

python scripts/db_manager.py add database/example_question.json   # thêm câu hỏi (tự cấp id nếu thiếu)
python scripts/db_manager.py delete 101

python scripts/db_manager.py export-json                    # DB -> database/questions.json
python scripts/db_manager.py import-json                    # database/questions.json -> DB
python scripts/db_manager.py export-html                    # DB -> cập nhật câu hỏi trong file HTML
python scripts/db_manager.py init                           # dựng lại DB từ file HTML
```

Quy trình sửa đề: `add` / `delete` (hoặc sửa `questions.json` rồi `import-json`)
→ `export-json` → `export-html` → commit.

### Truy vấn SQL trực tiếp

```sql
-- Số câu theo chủ đề và mức độ
SELECT topic, level, COUNT(*) FROM questions GROUP BY topic, level;

-- Các câu nhiều đáp án thuộc chủ đề Đạo đức
SELECT id, question, answer FROM v_questions WHERE kind = 'M' AND topic = 'Đạo đức';
```

## Bản quyền

© AIVIA 2026 · Đề nguồn, chương trình và tài liệu tham chiếu thuộc chủ sở hữu tương ứng.
