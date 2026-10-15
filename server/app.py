#!/usr/bin/env python3
"""
AIVIA exam server - phục vụ index.html và API đăng nhập / lưu điểm vào SQLite.

Chỉ dùng thư viện chuẩn của Python, không cần cài thêm gì.

    python server/app.py                    # http://localhost:8000 (mở cho cả mạng LAN)
    python server/app.py --port 8080
    python server/app.py --host 127.0.0.1   # chỉ máy này truy cập được

Dữ liệu:
    database/questions.db   ngân hàng câu hỏi + đáp án (dùng để chấm điểm)
    database/users.db       tài khoản, phiên đăng nhập, lượt thi, điểm (tự tạo)

Đăng nhập Google (tùy chọn): tạo server/config.json từ server/config.example.json
và điền google_client_id (hoặc đặt biến môi trường GOOGLE_CLIENT_ID).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_DB = ROOT / "database" / "questions.db"
USERS_DB = ROOT / "database" / "users.db"
USERS_SCHEMA = ROOT / "database" / "users_schema.sql"
CONFIG_PATH = ROOT / "server" / "config.json"

EXAM_CODE = "MOCK08"
EXAM_SECONDS = 180 * 60
SESSION_COOKIE = "aivia_session"
SESSION_DAYS = 14
PBKDF2_ITER = 200_000
MAX_BODY = 512 * 1024
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
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


# --------------------------------------------------------------------------- #
# Cấu hình & database
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    cfg: dict = {}
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if os.environ.get("GOOGLE_CLIENT_ID"):
        cfg["google_client_id"] = os.environ["GOOGLE_CLIENT_ID"]
    return cfg


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(USERS_DB, timeout=10)
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


def init_users_db() -> None:
    USERS_DB.parent.mkdir(parents=True, exist_ok=True)
    with transaction() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(USERS_SCHEMA.read_text(encoding="utf-8"))
        conn.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")


_key_cache: dict = {"mtime": None, "data": None}
_key_lock = threading.Lock()


def answer_key() -> dict:
    """Đáp án đúng đọc từ questions.db (tự nạp lại khi file thay đổi)."""
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


# --------------------------------------------------------------------------- #
# Tiện ích bảo mật
# --------------------------------------------------------------------------- #
def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITER)
    return f"pbkdf2_sha256${PBKDF2_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        algo, iterations, salt, digest = (stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), digest)


_failures: dict[str, list[float]] = {}
_fail_lock = threading.Lock()


def check_rate_limit(ip: str) -> None:
    now = time.time()
    with _fail_lock:
        recent = [t for t in _failures.get(ip, []) if now - t < 600]
        _failures[ip] = recent
        if len(recent) >= 10:
            raise ApiError(429, "Bạn đã đăng nhập sai quá nhiều lần. Vui lòng thử lại sau 10 phút.")


def note_failure(ip: str) -> None:
    with _fail_lock:
        _failures.setdefault(ip, []).append(time.time())


def clean_text(value, max_len: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_len]


def clean_email(value) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 120 or not EMAIL_RE.match(email):
        raise ApiError(400, "Email không hợp lệ.")
    return email


def verify_google_token(credential: str, client_id: str) -> dict:
    url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": credential})
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            info = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        raise ApiError(401, "Phiên đăng nhập Google không hợp lệ.")
    except (urllib.error.URLError, OSError):
        raise ApiError(502, "Không kết nối được tới Google để xác minh tài khoản.")
    if info.get("aud") != client_id:
        raise ApiError(401, "Token Google không dành cho ứng dụng này.")
    if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise ApiError(401, "Token Google không hợp lệ.")
    if str(info.get("email_verified")).lower() != "true":
        raise ApiError(401, "Email Google chưa được xác minh.")
    if int(info.get("exp", 0)) < time.time():
        raise ApiError(401, "Phiên đăng nhập Google đã hết hạn.")
    if not info.get("sub") or not info.get("email"):
        raise ApiError(401, "Thiếu thông tin tài khoản Google.")
    return info


def public_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "email": row["email"], "name": row["name"],
        "school": row["school"], "class_name": row["class_name"],
        "avatar_url": row["avatar_url"], "provider": row["provider"],
    }


def leaderboard_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Điểm cao nhất của mỗi người; bằng điểm thì ai làm nhanh hơn xếp trên."""
    return conn.execute(
        """
        WITH ranked AS (
            SELECT a.*,
                   ROW_NUMBER() OVER (PARTITION BY a.user_id
                                      ORDER BY a.score DESC, a.duration_sec ASC, a.submitted_at ASC) AS rn,
                   COUNT(*) OVER (PARTITION BY a.user_id) AS attempts
              FROM attempts a
             WHERE a.status = 'submitted' AND a.exam_code = ?
        )
        SELECT u.id AS user_id, u.name, u.school, u.class_name, u.avatar_url,
               r.score, r.total, r.duration_sec, r.submitted_at, r.attempts
          FROM ranked r JOIN users u ON u.id = r.user_id
         WHERE r.rn = 1
         ORDER BY r.score DESC, r.duration_sec ASC, r.submitted_at ASC
        """,
        (EXAM_CODE,),
    ).fetchall()


def rank_of(rows: list[sqlite3.Row], user_id: int) -> int | None:
    return next((i + 1 for i, r in enumerate(rows) if r["user_id"] == user_id), None)


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(SimpleHTTPRequestHandler):
    server_version = "AIVIA/1.0"
    sys_version = ""

    ROUTES = {
        ("GET", "/api/config"): "api_config",
        ("GET", "/api/me"): "api_me",
        ("POST", "/api/register"): "api_register",
        ("POST", "/api/login"): "api_login",
        ("POST", "/api/google"): "api_google",
        ("POST", "/api/logout"): "api_logout",
        ("POST", "/api/attempts/start"): "api_attempt_start",
        ("GET", "/api/attempts/mine"): "api_attempts_mine",
        ("GET", "/api/leaderboard"): "api_leaderboard",
    }
    SUBMIT_RE = re.compile(r"^/api/attempts/(\d+)/submit$")

    def __init__(self, *args, **kwargs):
        self._cookie_out = None
        super().__init__(*args, directory=str(ROOT), **kwargs)

    # ---------- file tĩnh: chỉ cho phép index.html (không lộ database, .git, ...) ----------
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
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache")
        super().end_headers()

    # ---------- khung API ----------
    def _api(self, method: str, path: str) -> None:
        try:
            name, args = self.ROUTES.get((method, path)), ()
            if not name and method == "POST":
                m = self.SUBMIT_RE.match(path)
                if m:
                    name, args = "api_attempt_submit", (int(m.group(1)),)
            if not name:
                raise ApiError(404, "API không tồn tại.")
            body = self._read_json() if method == "POST" else {}
            status, payload = 200, getattr(self, name)(body, *args)
        except ApiError as e:
            status, payload = e.status, {"error": e.message}
        except Exception:
            traceback.print_exc()
            status, payload = 500, {"error": "Lỗi máy chủ, vui lòng thử lại."}
        self._send_json(status, payload)

    def _read_json(self) -> dict:
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise ApiError(415, "Yêu cầu phải gửi dạng JSON.")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Content-Length không hợp lệ.")
        if length > MAX_BODY:
            raise ApiError(413, "Dữ liệu gửi lên quá lớn.")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "JSON không hợp lệ.")
        if not isinstance(data, dict):
            raise ApiError(400, "JSON phải là object.")
        return data

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if self._cookie_out:
            self.send_header("Set-Cookie", self._cookie_out)
        self.end_headers()
        self.wfile.write(data)

    # ---------- phiên đăng nhập ----------
    @property
    def ip(self) -> str:
        return self.client_address[0]

    def _token(self) -> str | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _current_user(self, conn) -> sqlite3.Row | None:
        token = self._token()
        if not token:
            return None
        return conn.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > datetime('now')""",
            (sha256(token),),
        ).fetchone()

    def _require_user(self, conn) -> sqlite3.Row:
        user = self._current_user(conn)
        if not user:
            raise ApiError(401, "Bạn cần đăng nhập lại.")
        return user

    def _login(self, conn, user_id: int) -> dict:
        token = secrets.token_urlsafe(32)
        conn.execute(
            """INSERT INTO sessions(token_hash, user_id, expires_at, user_agent, ip)
               VALUES (?, ?, datetime('now', ?), ?, ?)""",
            (sha256(token), user_id, f"+{SESSION_DAYS} days",
             (self.headers.get("User-Agent") or "")[:200], self.ip),
        )
        conn.execute("UPDATE users SET last_login_at = datetime('now') WHERE id = ?", (user_id,))
        self._cookie_out = (f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
                            f"Max-Age={SESSION_DAYS * 86400}")
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return {"user": public_user(user)}

    # ---------- API: tài khoản ----------
    def api_config(self, body):
        return {"googleClientId": CONFIG.get("google_client_id") or "",
                "examSeconds": EXAM_SECONDS, "exam": EXAM_CODE}

    def api_me(self, body):
        with transaction() as conn:
            user = self._current_user(conn)
            return {"user": public_user(user) if user else None}

    def api_register(self, body):
        email = clean_email(body.get("email"))
        name = clean_text(body.get("name"), 80)
        password = body.get("password")
        if not name:
            raise ApiError(400, "Vui lòng nhập họ và tên.")
        if not isinstance(password, str) or not 6 <= len(password) <= 128:
            raise ApiError(400, "Mật khẩu phải có từ 6 đến 128 ký tự.")
        school = clean_text(body.get("school"), 120) or None
        class_name = clean_text(body.get("class_name"), 30) or None
        with transaction() as conn:
            existing = conn.execute("SELECT password_hash FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                raise ApiError(409, "Email này đã được đăng ký. Hãy đăng nhập." if existing["password_hash"]
                               else "Email này đã đăng ký bằng Google – hãy dùng nút “Tiếp tục với Google”.")
            cur = conn.execute(
                """INSERT INTO users(email, name, school, class_name, password_hash, provider)
                   VALUES (?, ?, ?, ?, ?, 'password')""",
                (email, name, school, class_name, hash_password(password)),
            )
            return self._login(conn, cur.lastrowid)

    def api_login(self, body):
        check_rate_limit(self.ip)
        email = str(body.get("email") or "").strip().lower()
        password = str(body.get("password") or "")
        with transaction() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if user and not user["password_hash"]:
                raise ApiError(401, "Tài khoản này đăng nhập bằng Google – hãy dùng nút “Tiếp tục với Google”.")
            if not user or not verify_password(password, user["password_hash"]):
                note_failure(self.ip)
                raise ApiError(401, "Email hoặc mật khẩu không đúng.")
            return self._login(conn, user["id"])

    def api_google(self, body):
        client_id = CONFIG.get("google_client_id")
        if not client_id:
            raise ApiError(400, "Server chưa cấu hình đăng nhập Google.")
        credential = body.get("credential")
        if not isinstance(credential, str) or not 20 < len(credential) < 8192:
            raise ApiError(400, "Thiếu thông tin đăng nhập Google.")
        info = verify_google_token(credential, client_id)
        sub, email, picture = info["sub"], info["email"].lower(), info.get("picture")
        name = clean_text(info.get("name"), 80) or email.split("@")[0]
        with transaction() as conn:
            user = conn.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
            if not user:
                user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if user:  # liên kết Google với tài khoản email đã có (email đã được Google xác minh)
                    conn.execute("UPDATE users SET google_sub = ? WHERE id = ?", (sub, user["id"]))
                    user_id = user["id"]
                else:
                    user_id = conn.execute(
                        "INSERT INTO users(email, name, google_sub, avatar_url, provider) VALUES (?, ?, ?, ?, 'google')",
                        (email, name, sub, picture),
                    ).lastrowid
            else:
                user_id = user["id"]
            if picture:
                conn.execute("UPDATE users SET avatar_url = ? WHERE id = ?", (picture, user_id))
            return self._login(conn, user_id)

    def api_logout(self, body):
        token = self._token()
        if token:
            with transaction() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (sha256(token),))
        self._cookie_out = f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
        return {"ok": True}

    # ---------- API: làm bài & điểm ----------
    def api_attempt_start(self, body):
        total = len(answer_key())
        with transaction() as conn:
            user = self._require_user(conn)
            conn.execute(
                "UPDATE attempts SET status = 'abandoned' WHERE user_id = ? AND exam_code = ? AND status = 'in_progress'",
                (user["id"], EXAM_CODE),
            )
            attempt_id = conn.execute(
                "INSERT INTO attempts(user_id, exam_code, total, ip) VALUES (?, ?, ?, ?)",
                (user["id"], EXAM_CODE, total, self.ip),
            ).lastrowid
            row = conn.execute("SELECT started_at FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
            return {"attempt_id": attempt_id, "started_at": row["started_at"], "exam_seconds": EXAM_SECONDS}

    def api_attempt_submit(self, body, attempt_id: int):
        answers = body.get("answers") or {}
        if not isinstance(answers, dict):
            raise ApiError(400, "Dữ liệu bài làm không hợp lệ.")
        reason = body.get("reason") if body.get("reason") in REASONS else "manual"
        try:
            exit_count = max(0, min(int(body.get("exit_count") or 0), 99))
        except (TypeError, ValueError):
            exit_count = 0
        violations = body.get("violations") if isinstance(body.get("violations"), list) else []
        key = answer_key()

        with transaction() as conn:
            user = self._require_user(conn)
            attempt = conn.execute("SELECT * FROM attempts WHERE id = ? AND user_id = ?",
                                   (attempt_id, user["id"])).fetchone()
            if not attempt:
                raise ApiError(404, "Không tìm thấy lượt thi.")
            if attempt["status"] != "submitted":
                # Server tự chấm lại từ questions.db – không tin điểm do trình duyệt gửi lên
                score, rows, by_topic, by_level = 0, [], {}, {}
                for qid, q in key.items():
                    picked = answers.get(str(qid))
                    picked = sorted({p for p in picked if isinstance(p, str) and len(p) == 1}) \
                        if isinstance(picked, list) else []
                    ok = int(bool(picked) and set(picked) == q["answer"])
                    score += ok
                    rows.append((attempt_id, qid, ",".join(picked), ok))
                    for bucket, name in ((by_topic, q["topic"]), (by_level, q["level"])):
                        cell = bucket.setdefault(name, [0, 0])
                        cell[0] += ok
                        cell[1] += 1
                conn.execute("DELETE FROM attempt_answers WHERE attempt_id = ?", (attempt_id,))
                conn.executemany(
                    "INSERT INTO attempt_answers(attempt_id, question_id, selected, is_correct) VALUES (?, ?, ?, ?)",
                    rows,
                )
                conn.execute(
                    """UPDATE attempts
                          SET status = 'submitted', submitted_at = datetime('now'),
                              duration_sec = CAST(ROUND((julianday('now') - julianday(started_at)) * 86400) AS INTEGER),
                              score = ?, total = ?, exit_count = ?, submit_reason = ?, violations = ?, breakdown = ?
                        WHERE id = ?""",
                    (score, len(key), exit_count, reason,
                     json.dumps(violations[:50], ensure_ascii=False),
                     json.dumps({"topic": by_topic, "level": by_level}, ensure_ascii=False),
                     attempt_id),
                )
                attempt = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
            return {
                "attempt_id": attempt["id"], "score": attempt["score"], "total": attempt["total"],
                "duration_sec": attempt["duration_sec"], "submit_reason": attempt["submit_reason"],
                "rank": rank_of(leaderboard_rows(conn), user["id"]),
                "breakdown": json.loads(attempt["breakdown"] or "{}"),
            }

    def api_attempts_mine(self, body):
        with transaction() as conn:
            user = self._require_user(conn)
            rows = conn.execute(
                """SELECT id, status, started_at, submitted_at, duration_sec, score, total,
                          exit_count, submit_reason, breakdown
                     FROM attempts WHERE user_id = ? AND exam_code = ?
                    ORDER BY id DESC LIMIT 200""",
                (user["id"], EXAM_CODE),
            ).fetchall()
            return {
                "rows": [{**dict(r), "breakdown": json.loads(r["breakdown"] or "null")} for r in rows],
                "rank": rank_of(leaderboard_rows(conn), user["id"]),
            }

    def api_leaderboard(self, body):
        with transaction() as conn:
            user = self._require_user(conn)
            rows = leaderboard_rows(conn)[:100]
            return {"rows": [{
                "name": r["name"], "school": r["school"], "class_name": r["class_name"],
                "avatar_url": r["avatar_url"], "score": r["score"], "total": r["total"],
                "duration_sec": r["duration_sec"], "submitted_at": r["submitted_at"],
                "attempts": r["attempts"], "me": r["user_id"] == user["id"],
            } for r in rows]}


# --------------------------------------------------------------------------- #
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
    parser = argparse.ArgumentParser(description="AIVIA exam server (đăng nhập + lưu điểm SQLite)")
    parser.add_argument("--host", default=CONFIG.get("host", "0.0.0.0"),
                        help="0.0.0.0 = cho phép máy khác trong mạng LAN truy cập (mặc định)")
    parser.add_argument("--port", type=int, default=default_port, help=f"cổng (mặc định {default_port})")
    args = parser.parse_args()

    if not QUESTIONS_DB.exists():
        raise SystemExit("Chưa có database/questions.db – chạy: python scripts/db_manager.py init")
    init_users_db()
    total = len(answer_key())

    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        raise SystemExit(f"Không mở được cổng {args.port}: {e}\nThử cổng khác: python server/app.py --port 8080")

    print("=" * 62)
    print(" AIVIA exam server đang chạy")
    print(f"   Máy này     : http://localhost:{args.port}")
    if args.host in ("0.0.0.0", "") and (ip := lan_ip()):
        print(f"   Mạng LAN    : http://{ip}:{args.port}")
    print(f"   Câu hỏi     : {QUESTIONS_DB.relative_to(ROOT)} ({total} câu)")
    print(f"   Người dùng  : {USERS_DB.relative_to(ROOT)}")
    print(f"   Google login: {'BẬT' if CONFIG.get('google_client_id') else 'TẮT (chưa có google_client_id)'}")
    print(" Nhấn Ctrl+C để dừng.")
    print("=" * 62)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng server.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
