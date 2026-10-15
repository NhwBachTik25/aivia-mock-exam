#!/usr/bin/env python3
"""
AIVIA Question Bank - công cụ quản lý database SQLite.

Chỉ dùng thư viện chuẩn của Python (sqlite3, json, argparse) - không cần cài thêm gì.

Ví dụ:
    python scripts/db_manager.py init                 # tạo DB từ file HTML đề thi
    python scripts/db_manager.py stats                # thống kê
    python scripts/db_manager.py list --topic Logic   # liệt kê câu hỏi
    python scripts/db_manager.py show 22              # xem chi tiết 1 câu
    python scripts/db_manager.py add new.json         # thêm câu hỏi từ file JSON
    python scripts/db_manager.py delete 101           # xóa câu hỏi
    python scripts/db_manager.py export-json          # xuất database/questions.json
    python scripts/db_manager.py import-json          # dựng lại DB từ questions.json
    python scripts/db_manager.py export-html          # ghi dữ liệu DB ngược vào file HTML
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "questions.db"
SCHEMA_PATH = ROOT / "database" / "schema.sql"
JSON_PATH = ROOT / "database" / "questions.json"
HTML_PATH = ROOT / "AIVIA_Mock_08_VOAI_Realistic_100_Cau_Foundation_to_Olympic.html"

DB_PREFIX = "const DB="
LABELS = "ABCDEFGHIJ"
QUESTION_KEYS = ("id", "kind", "topic", "question", "options", "answer",
                 "explanation", "source", "skill", "level", "code")

# Windows console mặc định không phải UTF-8 -> tránh lỗi khi in tiếng Việt
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


# --------------------------------------------------------------------------- #
# Kết nối & khởi tạo
# --------------------------------------------------------------------------- #
def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_fresh_db() -> sqlite3.Connection:
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = connect()
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


# --------------------------------------------------------------------------- #
# Đọc / ghi dữ liệu dạng "DB" giống trong file HTML
# --------------------------------------------------------------------------- #
def read_html_data(html_path: Path) -> dict:
    for line in html_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(DB_PREFIX):
            payload = line[len(DB_PREFIX):].rstrip().rstrip(";")
            return json.loads(payload)
    raise SystemExit(f"Không tìm thấy dòng '{DB_PREFIX}' trong {html_path}")


def validate_question(q: dict) -> None:
    missing = [k for k in ("id", "kind", "topic", "question", "options", "answer", "level") if k not in q]
    if missing:
        raise ValueError(f"Câu {q.get('id')}: thiếu trường {missing}")
    if q["kind"] not in ("S", "M"):
        raise ValueError(f"Câu {q['id']}: kind phải là 'S' hoặc 'M'")
    labels = LABELS[: len(q["options"])]
    bad = [a for a in q["answer"] if a not in labels]
    if bad or not q["answer"]:
        raise ValueError(f"Câu {q['id']}: đáp án {q['answer']} không hợp lệ (cho phép {list(labels)})")
    if q["kind"] == "S" and len(q["answer"]) != 1:
        raise ValueError(f"Câu {q['id']}: kind 'S' chỉ được có 1 đáp án")


def insert_question(conn: sqlite3.Connection, q: dict) -> None:
    validate_question(q)
    src = q.get("source")
    if src and not conn.execute("SELECT 1 FROM sources WHERE code=?", (src,)).fetchone():
        conn.execute("INSERT INTO sources(code, title, url) VALUES (?, ?, NULL)", (src, src))
    conn.execute(
        """INSERT INTO questions(id, kind, topic, level, question, code, explanation, skill, source_code)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (q["id"], q["kind"], q["topic"], q["level"], q["question"], q.get("code"),
         q.get("explanation"), q.get("skill"), src),
    )
    answers = set(q["answer"])
    conn.executemany(
        "INSERT INTO options(question_id, label, position, text, is_correct) VALUES (?, ?, ?, ?, ?)",
        [(q["id"], LABELS[i], i, text, int(LABELS[i] in answers)) for i, text in enumerate(q["options"])],
    )


def load_data(conn: sqlite3.Connection, data: dict) -> None:
    conn.executemany(
        "INSERT INTO sources(code, title, url) VALUES (?, ?, ?)",
        [(code, v[0], v[1] if len(v) > 1 else None) for code, v in data.get("sources", {}).items()],
    )
    for q in data["questions"]:
        insert_question(conn, q)
    conn.commit()


def dump_data(conn: sqlite3.Connection) -> dict:
    """Xuất DB về đúng cấu trúc {questions: [...], sources: {...}} mà file HTML dùng."""
    questions = []
    for row in conn.execute("SELECT * FROM questions ORDER BY id"):
        opts = conn.execute(
            "SELECT label, text, is_correct FROM options WHERE question_id=? ORDER BY position",
            (row["id"],),
        ).fetchall()
        questions.append({
            "id": row["id"],
            "kind": row["kind"],
            "topic": row["topic"],
            "question": row["question"],
            "options": [o["text"] for o in opts],
            "answer": [o["label"] for o in opts if o["is_correct"]],
            "explanation": row["explanation"],
            "source": row["source_code"],
            "skill": row["skill"],
            "level": row["level"],
            "code": row["code"],
        })
    sources = {r["code"]: [r["title"], r["url"]]
               for r in conn.execute("SELECT * FROM sources ORDER BY rowid")}
    return {"questions": questions, "sources": sources}


# --------------------------------------------------------------------------- #
# Lệnh CLI
# --------------------------------------------------------------------------- #
def cmd_init(args) -> None:
    html = Path(args.html)
    data = read_html_data(html)
    conn = create_fresh_db()
    load_data(conn, data)
    print(f"Đã tạo {DB_PATH.relative_to(ROOT)} với {len(data['questions'])} câu hỏi "
          f"và {len(data.get('sources', {}))} nguồn từ {html.name}")


def cmd_import_json(args) -> None:
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    conn = create_fresh_db()
    load_data(conn, data)
    print(f"Đã dựng lại DB từ {args.file}: {len(data['questions'])} câu hỏi")


def cmd_export_json(args) -> None:
    conn = connect()
    data = dump_data(conn)
    out = Path(args.out)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    print(f"Đã xuất {len(data['questions'])} câu hỏi ra {out}")


def cmd_export_html(args) -> None:
    conn = connect()
    data = dump_data(conn)
    html = Path(args.html)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    with open(html, encoding="utf-8", newline="") as f:
        lines = f.read().split("\n")
    for i, line in enumerate(lines):
        if line.startswith(DB_PREFIX):
            lines[i] = f"{DB_PREFIX}{payload};"
            break
    else:
        raise SystemExit(f"Không tìm thấy dòng '{DB_PREFIX}' trong {html}")
    html.write_text("\n".join(lines), encoding="utf-8", newline="")  # giữ LF trên Windows
    print(f"Đã ghi {len(data['questions'])} câu hỏi vào {html.name}")


def cmd_stats(args) -> None:
    conn = connect()
    total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    print(f"Tổng số câu hỏi: {total}\n")
    for col, title in (("topic", "Chủ đề"), ("level", "Mức độ"), ("kind", "Loại (S=1 đáp án, M=nhiều)"),
                       ("source_code", "Nguồn")):
        print(f"== {title} ==")
        for r in conn.execute(f"SELECT {col} AS k, COUNT(*) AS n FROM questions GROUP BY {col} ORDER BY n DESC"):
            print(f"  {str(r['k']):<12} {r['n']:>4}")
        print()


def cmd_list(args) -> None:
    conn = connect()
    sql, params = "SELECT * FROM v_questions WHERE 1=1", []
    for col, val in (("topic", args.topic), ("level", args.level), ("source_code", args.source)):
        if val:
            sql += f" AND {col} = ?"
            params.append(val)
    if args.search:
        sql += " AND question LIKE ?"
        params.append(f"%{args.search}%")
    rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    for r in rows:
        text = r["question"].replace("\n", " ")
        print(f"#{r['id']:<4} [{r['topic']}/{r['level']}/{r['kind']}] {text[:90]}{'…' if len(text) > 90 else ''}  -> {r['answer']}")
    print(f"\n{len(rows)} câu")


def cmd_show(args) -> None:
    conn = connect()
    q = conn.execute("SELECT * FROM questions WHERE id=?", (args.id,)).fetchone()
    if not q:
        raise SystemExit(f"Không có câu #{args.id}")
    print(f"Câu {q['id']} · {q['topic']} · {q['level']} · {'Nhiều đáp án' if q['kind'] == 'M' else 'Một đáp án'}")
    print(q["question"])
    if q["code"]:
        print("\n" + q["code"].replace("\\n", "\n") + "\n")
    for o in conn.execute("SELECT * FROM options WHERE question_id=? ORDER BY position", (args.id,)):
        print(f"  {'✔' if o['is_correct'] else ' '} {o['label']}. {o['text']}")
    print(f"\nGiải thích: {q['explanation']}")
    print(f"Kỹ năng: {q['skill']} · Nguồn: {q['source_code']}")


def cmd_add(args) -> None:
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("questions", [data])
    conn = connect()
    next_id = (conn.execute("SELECT MAX(id) FROM questions").fetchone()[0] or 0) + 1
    try:
        for q in items:
            if "id" not in q:
                q["id"], next_id = next_id, next_id + 1
            insert_question(conn, q)
        conn.commit()
    except (sqlite3.IntegrityError, ValueError) as e:
        conn.rollback()
        raise SystemExit(f"Lỗi, không thêm câu nào: {e}")
    print(f"Đã thêm {len(items)} câu: {[q['id'] for q in items]}")


def cmd_delete(args) -> None:
    conn = connect()
    n = conn.execute("DELETE FROM questions WHERE id=?", (args.id,)).rowcount
    conn.commit()
    print(f"Đã xóa câu #{args.id}" if n else f"Không có câu #{args.id}")


def main() -> None:
    p = argparse.ArgumentParser(description="Quản lý ngân hàng câu hỏi AIVIA (SQLite)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="Tạo DB mới từ file HTML đề thi")
    s.add_argument("--html", default=str(HTML_PATH))
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("import-json", help="Dựng lại DB từ file JSON")
    s.add_argument("file", nargs="?", default=str(JSON_PATH))
    s.set_defaults(func=cmd_import_json)

    s = sub.add_parser("export-json", help="Xuất DB ra JSON")
    s.add_argument("--out", default=str(JSON_PATH))
    s.set_defaults(func=cmd_export_json)

    s = sub.add_parser("export-html", help="Ghi dữ liệu DB vào biến DB trong file HTML")
    s.add_argument("--html", default=str(HTML_PATH))
    s.set_defaults(func=cmd_export_html)

    sub.add_parser("stats", help="Thống kê").set_defaults(func=cmd_stats)

    s = sub.add_parser("list", help="Liệt kê câu hỏi")
    s.add_argument("--topic")
    s.add_argument("--level")
    s.add_argument("--source")
    s.add_argument("--search", help="Tìm theo nội dung câu hỏi")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="Xem chi tiết một câu")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("add", help="Thêm câu hỏi từ file JSON (1 object hoặc danh sách)")
    s.add_argument("file")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("delete", help="Xóa một câu")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_delete)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
