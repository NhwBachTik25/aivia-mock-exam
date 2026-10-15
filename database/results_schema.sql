-- AIVIA - Database lưu bài nộp & Bảng xếp hạng trực tiếp (Live Ranking - kiểu Azota)
-- File database/results.db được máy chủ tự tạo từ schema này.
-- KHÔNG commit results.db lên GitHub công khai (đã được cấu hình trong .gitignore).
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS submissions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,              -- Họ và tên thí sinh (bắt buộc)
    class_name     TEXT,                       -- Lớp (ví dụ: 12 Tin, 11A1...)
    school         TEXT,                       -- Trường / SBD
    exam_code      TEXT NOT NULL DEFAULT 'MOCK08',
    score          INTEGER NOT NULL,           -- Số câu đúng (0-100) do máy chủ tự chấm
    total          INTEGER NOT NULL DEFAULT 100,
    duration_sec   INTEGER NOT NULL DEFAULT 0, -- Thời gian làm bài (giây)
    exit_count     INTEGER NOT NULL DEFAULT 0, -- Số lần thoát toàn màn hình / rời tab
    submit_reason  TEXT DEFAULT 'manual',      -- 'manual', 'timeout', 'fullscreen'
    submitted_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    answers_json   TEXT,                       -- JSON chi tiết các đáp án đã chọn
    ip             TEXT
);

CREATE INDEX IF NOT EXISTS idx_submissions_rank 
ON submissions(exam_code, score DESC, duration_sec ASC, submitted_at ASC);
