-- AIVIA Question Bank - SQLite schema
-- Dùng: sqlite3 database/questions.db < database/schema.sql
PRAGMA foreign_keys = ON;

-- Nguồn tham khảo (VOAI, NOAI, IOAI, CS188, ...)
CREATE TABLE IF NOT EXISTS sources (
    code   TEXT PRIMARY KEY,          -- ví dụ: 'VOAI'
    title  TEXT NOT NULL,
    url    TEXT
);3

-- Câu hỏi
CREATE TABLE IF NOT EXISTS questions (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('S', 'M')),  -- S: 1 đáp án, M: nhiều đáp án
    topic        TEXT NOT NULL,       -- ML/DL, Logic, Thực tế, Đạo đức, Code
    level        TEXT NOT NULL,       -- Nền tảng, Trung bình, Nâng cao, Olympic
    question     TEXT NOT NULL,
    code         TEXT,                -- đoạn code minh họa (nếu có)
    explanation  TEXT,
    skill        TEXT,
    source_code  TEXT REFERENCES sources(code) ON UPDATE CASCADE,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Phương án trả lời (A, B, C, ...)
CREATE TABLE IF NOT EXISTS options (
    question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    label        TEXT NOT NULL,       -- 'A'..'H'
    position     INTEGER NOT NULL,    -- thứ tự hiển thị, bắt đầu từ 0
    text         TEXT NOT NULL,
    is_correct   INTEGER NOT NULL DEFAULT 0 CHECK (is_correct IN (0, 1)),
    PRIMARY KEY (question_id, label)
);

CREATE INDEX IF NOT EXISTS idx_questions_topic  ON questions(topic);
CREATE INDEX IF NOT EXISTS idx_questions_level  ON questions(level);
CREATE INDEX IF NOT EXISTS idx_questions_source ON questions(source_code);

-- View tiện tra cứu: mỗi câu kèm chuỗi đáp án đúng, ví dụ 'B,C,G'
CREATE VIEW IF NOT EXISTS v_questions AS
SELECT q.id, q.kind, q.topic, q.level, q.skill, q.source_code,
       q.question,
       (SELECT group_concat(label, ',')
          FROM (SELECT label FROM options o
                 WHERE o.question_id = q.id AND o.is_correct = 1
                 ORDER BY o.position)) AS answer
FROM questions q;
