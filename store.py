"""Task state persistence (SQLite) + API Key management with asyncio locks."""
import datetime
import hashlib
import json
import secrets
import sqlite3
import threading
import time

_LOCK = threading.Lock()
SUPPORTED_DURATIONS = (10, 15, 30)
DEFAULT_ALLOWED_DURATIONS = list(SUPPORTED_DURATIONS)


class TaskQuotaExceeded(RuntimeError):
    """API Key reached daily task quota."""


class PendingTaskLimitExceeded(RuntimeError):
    """Server pending task queue is full."""


class TaskStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init()

    def _init(self):
        with _LOCK:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    model TEXT,
                    prompt TEXT,
                    ratio TEXT,
                    duration INTEGER,
                    status TEXT,
                    video_url TEXT,
                    error TEXT,
                    created_at REAL,
                    updated_at REAL,
                    conversation_id TEXT,
                    deadline_at REAL,
                    last_poll_at REAL,
                    failure_code TEXT,
                    reference_images TEXT,
                    api_key_hash TEXT,
                    api_key_name TEXT,
                    started_at REAL,
                    finished_at REAL,
                    client_concurrency_limit INTEGER DEFAULT 0
                )
                """
            )
            # Legacy migration: add missing columns for task recovery, client usage, and timing stats.
            for column, definition in (
                ("account", "TEXT"),
                ("conversation_id", "TEXT"),
                ("deadline_at", "REAL"),
                ("last_poll_at", "REAL"),
                ("failure_code", "TEXT"),
                ("reference_images", "TEXT"),
                ("api_key_hash", "TEXT"),
                ("api_key_name", "TEXT"),
                ("started_at", "REAL"),
                ("finished_at", "REAL"),
                ("client_concurrency_limit", "INTEGER DEFAULT 0"),
            ):
                try:
                    self._conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} {definition}")
                except sqlite3.OperationalError:
                    pass
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    key TEXT PRIMARY KEY,
                    name TEXT,
                    enabled INTEGER DEFAULT 1,
                    created_at REAL,
                    last_used_at REAL DEFAULT 0,
                    daily_limit INTEGER DEFAULT 0,
                    concurrency_limit INTEGER DEFAULT 0,
                    allowed_durations TEXT DEFAULT '[10, 15, 30]',
                    expires_at REAL DEFAULT 0
                )
                """
            )
            # Legacy migration: add client-level policy columns to existing API Keys.
            for column, definition in (
                ("daily_limit", "INTEGER DEFAULT 0"),
                ("concurrency_limit", "INTEGER DEFAULT 0"),
                ("allowed_durations", "TEXT DEFAULT '[10, 15, 30]'"),
                ("expires_at", "REAL DEFAULT 0"),
            ):
                try:
                    self._conn.execute(f"ALTER TABLE api_keys ADD COLUMN {column} {definition}")
                except sqlite3.OperationalError:
                    pass
            self._conn.commit()

    @staticmethod
    def hash_api_key(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_allowed_durations(raw) -> list[int]:
        if isinstance(raw, list):
            values = raw
        else:
            try:
                values = json.loads(raw or "[]")
            except (TypeError, json.JSONDecodeError):
                values = []
        result = set()
        for value in values if isinstance(values, list) else []:
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if value in SUPPORTED_DURATIONS:
                result.add(value)
        return sorted(result) or list(DEFAULT_ALLOWED_DURATIONS)

    @classmethod
    def _key_row(cls, row):
        if not row:
            return None
        data = dict(row)
        data["enabled"] = bool(data.get("enabled"))
        data["allowed_durations"] = cls._parse_allowed_durations(data.get("allowed_durations"))
        data["daily_limit"] = max(0, int(data.get("daily_limit") or 0))
        data["concurrency_limit"] = max(0, int(data.get("concurrency_limit") or 0))
        data["expires_at"] = float(data.get("expires_at") or 0)
        return data

    # ===== tasks =====

    def create(
        self,
        task_id,
        model,
        prompt,
        ratio,
        duration,
        account=None,
        reference_images=None,
        api_key_hash=None,
        api_key_name=None,
        daily_limit=0,
        concurrency_limit=0,
        max_pending=0,
    ):
        now = time.time()
        with _LOCK:
            if max_pending > 0:
                pending = self._conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE status IN ('queued','processing')"
                ).fetchone()[0]
                if pending >= max_pending:
                    raise PendingTaskLimitExceeded(
                        f"Pending task queue has reached server limit ({max_pending})"
                    )
            if daily_limit > 0 and api_key_hash:
                day = datetime.date.today().isoformat()
                used = self._conn.execute(
                    "SELECT COUNT(*) FROM tasks "
                    "WHERE api_key_hash=? AND date(created_at,'unixepoch','localtime')=?",
                    (api_key_hash, day),
                ).fetchone()[0]
                if used >= daily_limit:
                    raise TaskQuotaExceeded(
                        f"API Key daily quota exceeded ({daily_limit} tasks)"
                    )
            self._conn.execute(
                "INSERT INTO tasks ("
                "id,model,prompt,ratio,duration,status,account,created_at,updated_at,"
                "conversation_id,deadline_at,last_poll_at,failure_code,reference_images,"
                "api_key_hash,api_key_name,started_at,finished_at,client_concurrency_limit"
                ") VALUES (?,?,?,?,?,'queued',?,?,?,NULL,NULL,0,NULL,?,?,?,?,?,?)",
                (
                    task_id,
                    model,
                    prompt,
                    ratio,
                    duration,
                    account,
                    now,
                    now,
                    reference_images or "[]",
                    api_key_hash,
                    api_key_name,
                    None,
                    None,
                    max(0, int(concurrency_limit or 0)),
                ),
            )
            self._conn.commit()

    def update(self, task_id, **fields):
        if not fields:
            return
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [task_id]
        with _LOCK:
            self._conn.execute(f"UPDATE tasks SET {cols} WHERE id=?", vals)
            self._conn.commit()

    def get(self, task_id):
        with _LOCK:
            row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def get_for_client(self, task_id, api_key_hash: str | None):
        """Returns tasks belonging to current API Key; anonymous mode isolated by NULL hash."""
        with _LOCK:
            if api_key_hash:
                row = self._conn.execute(
                    "SELECT * FROM tasks WHERE id=? AND api_key_hash=?",
                    (task_id, api_key_hash),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM tasks WHERE id=? AND api_key_hash IS NULL",
                    (task_id,),
                ).fetchone()
        return dict(row) if row else None

    def recoverable_tasks(self) -> list:
        """Recovers tasks with existing conversation_id after restart without re-submitting prompt."""
        with _LOCK:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status IN ('queued','processing') "
                "AND conversation_id IS NOT NULL AND account IS NOT NULL "
                "ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def recoverable_queued_tasks(self) -> list:
        """Recovers queued tasks without conversation_id after restart."""
        with _LOCK:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status='queued' "
                "AND conversation_id IS NULL ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def pending_task_count(self) -> int:
        with _LOCK:
            return self._conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('queued','processing')"
            ).fetchone()[0]

    def recent_tasks(self, limit: int = 50, api_key_hash: str | None = None) -> list:
        with _LOCK:
            if api_key_hash:
                rows = self._conn.execute(
                    "SELECT * FROM tasks WHERE api_key_hash=? "
                    "ORDER BY created_at DESC LIMIT ?", (api_key_hash, limit)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    def key_usage(self, api_key_hash: str, day: str | None = None) -> dict:
        day = day or datetime.date.today().isoformat()
        with _LOCK:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(status='completed') AS completed, "
                "SUM(status='failed') AS failed, "
                "SUM(status='processing') AS active, "
                "SUM(status='queued') AS queued "
                "FROM tasks WHERE api_key_hash=? "
                "AND date(created_at,'unixepoch','localtime')=?",
                (api_key_hash, day),
            ).fetchone()
        return {
            "day": day,
            "total": row["total"] or 0,
            "completed": row["completed"] or 0,
            "failed": row["failed"] or 0,
            "active": row["active"] or 0,
            "queued": row["queued"] or 0,
        }

    def stats(self) -> dict:
        """Daily completed/failed stats, success rate, 7-day trend, and total generated per account."""
        days = [(datetime.date.today() - datetime.timedelta(days=i)).isoformat()
                for i in range(6, -1, -1)]
        with _LOCK:
            per_day = []
            for d in days:
                row = self._conn.execute(
                    "SELECT sum(status='completed'), sum(status='failed') FROM tasks "
                    "WHERE date(created_at,'unixepoch','localtime')=?", (d,),
                ).fetchone()
                per_day.append({"day": d[5:], "completed": row[0] or 0, "failed": row[1] or 0})
            t = per_day[-1]
            per_account = self._conn.execute(
                "SELECT account, sum(status='completed') FROM tasks "
                "WHERE account IS NOT NULL GROUP BY account"
            ).fetchall()
        completed, failed = t["completed"], t["failed"]
        total = completed + failed
        return {
            "today_completed": completed,
            "today_failed": failed,
            "success_rate": round(completed / total, 3) if total else None,
            "per_day": per_day,
            "per_account_total": {r[0]: r[1] for r in per_account},
        }

    # ===== api keys =====

    def list_keys(self) -> list:
        with _LOCK:
            rows = self._conn.execute(
                "SELECT * FROM api_keys ORDER BY created_at DESC"
            ).fetchall()
        return [self._key_row(r) for r in rows]

    def get_key(self, key: str) -> dict | None:
        with _LOCK:
            row = self._conn.execute(
                "SELECT * FROM api_keys WHERE key=?", (key,)
            ).fetchone()
        return self._key_row(row)

    def create_key(
        self,
        name: str,
        daily_limit: int = 0,
        concurrency_limit: int = 0,
        allowed_durations: list[int] | None = None,
        expires_at: float | None = None,
    ) -> dict:
        key = "sk-" + secrets.token_hex(16)
        now = time.time()
        allowed = self._parse_allowed_durations(allowed_durations or DEFAULT_ALLOWED_DURATIONS)
        expires = float(expires_at or 0)
        with _LOCK:
            self._conn.execute(
                "INSERT INTO api_keys (key,name,enabled,created_at,last_used_at,"
                "daily_limit,concurrency_limit,allowed_durations,expires_at) "
                "VALUES (?,?,1,?,0,?,?,?,?)",
                (
                    key,
                    name or "",
                    now,
                    max(0, int(daily_limit or 0)),
                    max(0, int(concurrency_limit or 0)),
                    json.dumps(allowed, ensure_ascii=False),
                    expires,
                ),
            )
            self._conn.commit()
        data = self.get_key(key)
        data["last_used_at"] = 0
        data["key"] = key
        return data

    def update_key(self, key: str, **fields):
        if not fields:
            return
        fields = dict(fields)
        if "allowed_durations" in fields:
            fields["allowed_durations"] = json.dumps(
                self._parse_allowed_durations(fields["allowed_durations"]),
                ensure_ascii=False,
            )
        cols = ", ".join(f"{k}=?" for k in fields)
        with _LOCK:
            self._conn.execute(
                f"UPDATE api_keys SET {cols} WHERE key=?",
                list(fields.values()) + [key],
            )
            self._conn.commit()

    def delete_key(self, key: str):
        with _LOCK:
            self._conn.execute("DELETE FROM api_keys WHERE key=?", (key,))
            self._conn.commit()

    def has_enabled_keys(self) -> bool:
        with _LOCK:
            row = self._conn.execute(
                "SELECT 1 FROM api_keys WHERE enabled=1 LIMIT 1"
            ).fetchone()
        return bool(row)

    def is_key_valid(self, key: str) -> bool:
        with _LOCK:
            row = self._conn.execute(
                "SELECT enabled, expires_at FROM api_keys WHERE key=?", (key,)
            ).fetchone()
        if not row or not row["enabled"]:
            return False
        return not row["expires_at"] or row["expires_at"] > time.time()

    def touch_key(self, key: str, min_interval: float = 60):
        """Throttled update of last_used_at."""
        now = time.time()
        with _LOCK:
            row = self._conn.execute(
                "SELECT last_used_at FROM api_keys WHERE key=?", (key,)
            ).fetchone()
            if row and now - (row[0] or 0) >= min_interval:
                self._conn.execute(
                    "UPDATE api_keys SET last_used_at=? WHERE key=?", (now, key)
                )
                self._conn.commit()
