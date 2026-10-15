-- AIVIA - dữ liệu người dùng & kết quả thi (SQLite)
-- File database/users.db được server tự tạo từ schema này.
-- KHÔNG commit users.db lên GitHub công khai (chứa email, mật khẩu đã băm, điểm).
PRAGMA foreign_keys = ON;

-- Tài khoản
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name           TEXT NOT NULL,
    school         TEXT,
    class_name     TEXT,
    password_hash  TEXT,                       -- NULL nếu chỉ đăng nhập bằng Google
    google_sub     TEXT UNIQUE,                -- ID tài khoản Google
    avatar_url     TEXT,
    provider       TEXT NOT NULL DEFAULT 'password' CHECK (provider IN ('password', 'google')),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at  TEXT
);

-- Phiên đăng nhập (cookie). Chỉ lưu SHA-256 của token.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,
    user_agent  TEXT,
    ip          TEXT
);

-- Mỗi lượt làm bài
CREATE TABLE IF NOT EXISTS attempts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exam_code      TEXT NOT NULL,              -- 'MOCK08'
    status         TEXT NOT NULL DEFAULT 'in_progress'
                   CHECK (status IN ('in_progress', 'submitted', 'abandoned')),
    started_at     TEXT NOT NULL DEFAULT (datetime('now')),
    submitted_at   TEXT,
    duration_sec   INTEGER,
    score          INTEGER,                    -- số câu đúng (server tự chấm)
    total          INTEGER,
    exit_count     INTEGER NOT NULL DEFAULT 0, -- số lần thoát toàn màn hình / chuyển tab / tải lại
    submit_reason  TEXT CHECK (submit_reason IN ('manual', 'timeout', 'fullscreen')),
    violations     TEXT,                       -- JSON: [{kind, at}, ...]
    breakdown      TEXT,                       -- JSON: điểm theo chủ đề / mức độ
    ip             TEXT
);

-- Đáp án đã chọn cho từng câu của mỗi lượt
CREATE TABLE IF NOT EXISTS attempt_answers (
    attempt_id   INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    question_id  INTEGER NOT NULL,             -- = questions.id trong questions.db
    selected     TEXT NOT NULL DEFAULT '',     -- ví dụ 'B,C,G'
    is_correct   INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
    PRIMARY KEY (attempt_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user   ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_attempts_user   ON attempts(user_id, exam_code, status);
CREATE INDEX IF NOT EXISTS idx_attempts_score  ON attempts(exam_code, status, score DESC);
