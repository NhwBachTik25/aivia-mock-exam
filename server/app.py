#!/usr/bin/env python3
"""
AIVIA Exam Server - Chấm điểm tự động & Bảng xếp hạng trực tiếp (Live Ranking - kiểu Azota).

Học sinh không cần đăng ký tài khoản, chỉ cần nhập Họ tên (+ Lớp, Trường) là vào thi ngay.
Điểm thi được máy chủ tự động đối chiếu chấm lại từ database/questions.db và lưu vào database/results.db.

Chỉ dùng thư viện chuẩn của Python:
    python server/app.py                    # Chạy mặc định cổng 8000 (mở cho cả máy này và mạng LAN)
    python server/app.py --port 8080        # Đổi cổng tùy ý
    python server/app.py --host 127.0.0.1   # Chỉ cho phép máy nội bộ truy cập
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sqlite3
import sys
import threading
import time
import traceback
import urllib.parse
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_DB = ROOT / "database" / "questions.db"
RESULTS_DB = ROOT / "database" / "results.db"
RESULTS_SCHEMA = ROOT / "database" / "results_schema.sql"
CONFIG_PATH = ROOT / "server" / "config.json"

EXAM_CODE = "MOCK08"
EXAM_SECONDS = 180 * 60
MAX_BODY = 512 * 1024
REASONS = ("manual", "timeout", "fullscreen")

CONFIG: dict = {}

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(RESULTS_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_results_db() -> None:
    RESULTS_DB.parent.mkdir(parents=True, exist_ok=True)
    with transaction() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(RESULTS_SCHEMA.read_text(encoding="utf-8"))


_key_cache: dict = {"mtime": None, "data": None}
_key_lock = threading.Lock()


def answer_key() -> dict:
    """Đáp án đúng đọc trực tiếp từ questions.db (tự nạp lại khi file thay đổi)."""
    mtime = QUESTIONS_DB.stat().st_mtime
    with _key_lock:
        if _key_cache["mtime"] != mtime:
            conn = sqlite3.connect(QUESTIONS_DB.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                key = {qid: {"topic": topic, "level": level, "answer": set()}
                       for qid, topic, level in conn.execute("SELECT id, topic, level FROM questions")}
                for qid, label in conn.execute("SELECT question_id, label FROM options WHERE is_correct = 1"):
                    key[qid]["answer"].add(label)
            finally:
                conn.close()
            _key_cache.update(mtime=mtime, data=key)
        return _key_cache["data"]


def clean_text(value, max_len: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_len]


def get_live_ranking(conn: sqlite3.Connection) -> tuple[list[dict], int]:
    """Bảng xếp hạng trực tiếp: mỗi thí sinh lấy bài điểm cao nhất, làm nhanh nhất."""
    raw = conn.execute(
        """
        WITH ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY lower(trim(name)), lower(trim(ifnull(class_name, '')))
                       ORDER BY score DESC, duration_sec ASC, submitted_at ASC
                   ) AS rn,
                   COUNT(*) OVER (
                       PARTITION BY lower(trim(name)), lower(trim(ifnull(class_name, '')))
                   ) AS attempts
              FROM submissions
             WHERE exam_code = ?
        )
        SELECT id, name, class_name, school, score, total, duration_sec,
               exit_count, submit_reason, submitted_at, attempts
          FROM ranked
         WHERE rn = 1
         ORDER BY score DESC, duration_sec ASC, submitted_at ASC
         LIMIT 250
        """,
        (EXAM_CODE,),
    ).fetchall()

    total_submissions = conn.execute(
        "SELECT COUNT(*) FROM submissions WHERE exam_code = ?", (EXAM_CODE,)
    ).fetchone()[0]

    rows = []
    for idx, r in enumerate(raw):
        rows.append({
            "rank": idx + 1,
            "id": r["id"],
            "name": r["name"],
            "class_name": r["class_name"] or "",
            "school": r["school"] or "",
            "score": r["score"],
            "total": r["total"],
            "duration_sec": r["duration_sec"],
            "exit_count": r["exit_count"],
            "submit_reason": r["submit_reason"],
            "submitted_at": r["submitted_at"],
            "attempts": r["attempts"],
        })
    return rows, total_submissions


class Handler(SimpleHTTPRequestHandler):
    server_version = "AIVIA-Azota/1.0"
    sys_version = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    @staticmethod
    def _static_allowed(path: str) -> bool:
        return path in ("/", "/index.html", "/favicon.ico") or path.startswith("/assets/")

    def _serve_static(self, head: bool = False) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if not self._static_allowed(path):
            self.send_error(404, "Not found")
            return
        if path == "/":
            self.path = "/index.html"
        super().do_HEAD() if head else super().do_GET()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/api/"):
            self._api("GET", path)
        else:
            self._serve_static()

    def do_HEAD(self):
        self._serve_static(head=True)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/api/"):
            self._api("POST", path)
        else:
            self.send_error(405, "Method not allowed")

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache")
        super().end_headers()

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Content-Length không hợp lệ.")
        if length > MAX_BODY:
            raise ApiError(413, "Dữ liệu gửi lên quá lớn.")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
        except Exception:
            raise ApiError(400, "Dữ liệu JSON không hợp lệ.")
        if not isinstance(data, dict):
            raise ApiError(400, "JSON phải là object.")
        return data

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _api(self, method: str, path: str) -> None:
        try:
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)

            if method == "GET" and parsed.path in ("/api/ranking", "/api/live-ranking"):
                with transaction() as conn:
                    rows, total_sub = get_live_ranking(conn)
                    recent_raw = conn.execute(
                        """SELECT name, class_name, score, total, duration_sec, submit_reason, submitted_at
                             FROM submissions WHERE exam_code = ?
                            ORDER BY id DESC LIMIT 10""",
                        (EXAM_CODE,),
                    ).fetchall()
                    recent = [dict(r) for r in recent_raw]
                    payload = {"rows": rows, "total_submissions": total_sub, "recent": recent}
                self._send_json(200, payload)
                return

            if method == "GET" and parsed.path == "/api/my-history":
                name = clean_text(query.get("name", [""])[0], 80)
                class_name = clean_text(query.get("class_name", [""])[0], 40)
                if not name:
                    raise ApiError(400, "Thiếu họ và tên.")
                with transaction() as conn:
                    history = conn.execute(
                        """SELECT id, name, class_name, school, score, total, duration_sec,
                                  exit_count, submit_reason, submitted_at
                             FROM submissions
                            WHERE exam_code = ? AND lower(trim(name)) = lower(trim(?))
                            ORDER BY id DESC LIMIT 50""",
                        (EXAM_CODE, name),
                    ).fetchall()
                    payload = {"history": [dict(r) for r in history]}
                self._send_json(200, payload)
                return

            if method == "POST" and parsed.path == "/api/submit":
                body = self._read_json()
                name = clean_text(body.get("name"), 80)
                if not name:
                    raise ApiError(400, "Vui lòng nhập Họ và tên thí sinh.")
                class_name = clean_text(body.get("class_name"), 40)
                school = clean_text(body.get("school"), 100)
                answers = body.get("answers") or {}
                if not isinstance(answers, dict):
                    raise ApiError(400, "Dữ liệu câu trả lời không hợp lệ.")

                duration_sec = max(0, min(int(body.get("duration_sec") or 0), 86400))
                exit_count = max(0, min(int(body.get("exit_count") or 0), 99))
                reason = body.get("reason") if body.get("reason") in REASONS else "manual"

                key = answer_key()
                score, by_topic, by_level = 0, {}, {}

                # Server tự chấm lại 100% câu hỏi độc lập từ questions.db
                for qid, q in key.items():
                    picked = answers.get(str(qid))
                    picked = sorted({p for p in picked if isinstance(p, str) and len(p) == 1}) \
                        if isinstance(picked, list) else []
                    ok = int(bool(picked) and set(picked) == q["answer"])
                    score += ok
                    for bucket, bname in ((by_topic, q["topic"]), (by_level, q["level"])):
                        cell = bucket.setdefault(bname, [0, 0])
                        cell[0] += ok
                        cell[1] += 1

                ip = self.client_address[0]
                with transaction() as conn:
                    cur = conn.execute(
                        """INSERT INTO submissions(name, class_name, school, exam_code, score, total,
                                                   duration_sec, exit_count, submit_reason, answers_json, ip)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (name, class_name, school, EXAM_CODE, score, len(key),
                         duration_sec, exit_count, reason,
                         json.dumps(answers, ensure_ascii=False), ip),
                    )
                    sub_id = cur.lastrowid
                    rows, total_sub = get_live_ranking(conn)
                    my_rank = next((r["rank"] for r in rows if r["id"] == sub_id), None)
                    if not my_rank:
                        # Nếu bài thi này không phải bài điểm cao nhất của thí sinh
                        my_rank = next((r["rank"] for r in rows
                                        if r["name"].lower() == name.lower() and
                                        r["class_name"].lower() == class_name.lower()), len(rows))

                payload = {
                    "ok": True,
                    "id": sub_id,
                    "name": name,
                    "score": score,
                    "total": len(key),
                    "duration_sec": duration_sec,
                    "rank": my_rank,
                    "total_participants": len(rows),
                    "breakdown": {"topic": by_topic, "level": by_level},
                }
                self._send_json(200, payload)
                return

            raise ApiError(404, "API không tồn tại.")
        except ApiError as e:
            self._send_json(e.status, {"error": e.message})
        except Exception:
            traceback.print_exc()
            self._send_json(500, {"error": "Lỗi máy chủ nội bộ."})


def lan_ip() -> str | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def main() -> None:
    CONFIG.update(load_config())
    default_port = int(os.environ.get("PORT") or CONFIG.get("port") or 8000)
    parser = argparse.ArgumentParser(description="AIVIA Exam Server - Live Ranking (Kiểu Azota)")
    parser.add_argument("--host", default=CONFIG.get("host", "0.0.0.0"),
                        help="0.0.0.0 = cho phép các máy trong cùng mạng LAN truy cập")
    parser.add_argument("--port", type=int, default=default_port, help=f"cổng (mặc định {default_port})")
    args = parser.parse_args()

    if not QUESTIONS_DB.exists():
        raise SystemExit("Chưa có database/questions.db – chạy: python scripts/db_manager.py init")
    init_results_db()
    total = len(answer_key())

    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        raise SystemExit(f"Không mở được cổng {args.port}: {e}\nThử cổng khác: python server/app.py --port 8080")

    print("=" * 64)
    print(" AIVIA EXAM SERVER - LIVE RANKING (Kiểu Azota)")
    print(f"   Trực tiếp máy này : http://localhost:{args.port}")
    if args.host in ("0.0.0.0", "") and (ip := lan_ip()):
        print(f"   Trong mạng LAN    : http://{ip}:{args.port}")
    print(f"   Ngân hàng câu hỏi : {QUESTIONS_DB.relative_to(ROOT)} ({total} câu)")
    print(f"   Database kết quả  : {RESULTS_DB.relative_to(ROOT)}")
    print("   Thí sinh chỉ cần nhập Họ tên (+ Lớp) là vào thi, Live Ranking tự động!")
    print(" Nhấn Ctrl+C để dừng server.")
    print("=" * 64)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng server.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
