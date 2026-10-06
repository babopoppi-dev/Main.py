from __future__ import annotations

"""
Persistent job history for ANDREA AI TEAM (SQLite, WAL).

Invariants:
- every Telegram request that reaches a provider or MCP gets a job row first;
- state transitions are validated and persisted before side effects continue;
- the same Telegram message (chat_id + message_id) maps to exactly one job;
- no secret ever reaches the database: every free-text field is sanitized.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from redact import sanitize


QUEUED = "QUEUED"
ANALYZING = "ANALYZING"
RUNNING = "RUNNING"
TESTING = "TESTING"
REVIEWING = "REVIEWING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
ROLLED_BACK = "ROLLED_BACK"

ALL_STATES = (QUEUED, ANALYZING, RUNNING, TESTING, REVIEWING, COMPLETED, FAILED, CANCELLED, ROLLED_BACK)
TERMINAL_STATES = frozenset({COMPLETED, FAILED, CANCELLED, ROLLED_BACK})
ACTIVE_STATES = frozenset(set(ALL_STATES) - TERMINAL_STATES)

# Normal forward transitions. Recovery after restart may additionally move an
# active job back to QUEUED (see JobStore.requeue_after_restart).
TRANSITIONS: dict[str, frozenset[str]] = {
    QUEUED: frozenset({ANALYZING, CANCELLED, FAILED}),
    ANALYZING: frozenset({RUNNING, COMPLETED, FAILED, CANCELLED}),
    RUNNING: frozenset({TESTING, REVIEWING, FAILED, CANCELLED, ROLLED_BACK}),
    TESTING: frozenset({RUNNING, REVIEWING, COMPLETED, FAILED, CANCELLED, ROLLED_BACK}),
    REVIEWING: frozenset({RUNNING, TESTING, COMPLETED, FAILED, CANCELLED, ROLLED_BACK}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
    ROLLED_BACK: frozenset(),
}

AGENT_STATES = frozenset({"WAITING", "RUNNING", "DONE", "FAILED", "SKIPPED", "OFFLINE", "CANCELLED"})
AGENTS = ("codex", "claude", "grok")


class InvalidTransition(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

@dataclass
class Job:
    job_id: int
    uid: str
    idem_key: Optional[str]
    created_at: float
    started_at: Optional[float]
    completed_at: Optional[float]
    updated_at: float
    telegram_user_id: int
    telegram_chat_id: int
    request: str
    project: Optional[str]
    operation: str
    kind: str
    state: str
    phase: str
    codex_state: str
    claude_state: str
    grok_state: str
    executor: Optional[str]
    work_session_id: Optional[str]
    work_lock_id: Optional[str]
    lock_state: str
    files: list[str] = field(default_factory=list)
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    test_result: str = ""
    test_command: str = ""
    attempts: int = 0
    restarts: int = 0
    errors: list[str] = field(default_factory=list)
    rollback: str = "none"
    result_summary: str = ""
    cancel_requested: bool = False
    project_path: str = ""

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def agent_state(self, agent: str) -> str:
        return getattr(self, f"{agent}_state")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    idem_key TEXT UNIQUE,
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    updated_at REAL NOT NULL,
    telegram_user_id INTEGER NOT NULL,
    telegram_chat_id INTEGER NOT NULL,
    request TEXT NOT NULL,
    project TEXT,
    project_path TEXT NOT NULL DEFAULT '',
    operation TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT '',
    codex_state TEXT NOT NULL DEFAULT 'WAITING',
    claude_state TEXT NOT NULL DEFAULT 'WAITING',
    grok_state TEXT NOT NULL DEFAULT 'WAITING',
    executor TEXT,
    work_session_id TEXT,
    work_lock_id TEXT,
    lock_state TEXT NOT NULL DEFAULT 'NONE',
    files_json TEXT NOT NULL DEFAULT '[]',
    tests_run INTEGER NOT NULL DEFAULT 0,
    tests_passed INTEGER NOT NULL DEFAULT 0,
    tests_failed INTEGER NOT NULL DEFAULT 0,
    test_result TEXT NOT NULL DEFAULT '',
    test_command TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    restarts INTEGER NOT NULL DEFAULT 0,
    errors_json TEXT NOT NULL DEFAULT '[]',
    rollback TEXT NOT NULL DEFAULT 'none',
    result_summary TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_state_idx ON jobs(state);
CREATE INDEX IF NOT EXISTS jobs_project_idx ON jobs(project);
CREATE TABLE IF NOT EXISTS job_ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(job_id),
    at REAL NOT NULL,
    op TEXT NOT NULL,
    path TEXT NOT NULL,
    operation_id TEXT,
    rolled_back INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS job_ops_job_idx ON job_ops(job_id);
CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(job_id),
    at REAL NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS job_events_job_idx ON job_events(job_id);
"""

_UPDATABLE = {
    "project", "project_path", "operation", "phase", "codex_state", "claude_state", "grok_state",
    "executor", "work_session_id", "work_lock_id", "lock_state", "tests_run", "tests_passed",
    "tests_failed", "test_result", "test_command", "attempts", "rollback", "result_summary",
    "started_at",
}
_TEXT_FIELDS = {"phase", "test_result", "test_command", "result_summary", "project", "operation"}


class JobStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=10)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- helpers -----------------------------------------------------------

    def _tx(self):
        store = self

        class _Tx:
            def __enter__(self_inner):
                store._lock.acquire()
                store._conn.execute("BEGIN IMMEDIATE")
                return store._conn

            def __exit__(self_inner, exc_type, exc, tb):
                try:
                    if exc_type is None:
                        store._conn.execute("COMMIT")
                    else:
                        store._conn.execute("ROLLBACK")
                finally:
                    store._lock.release()
                return False

        return _Tx()

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            job_id=row["job_id"],
            uid=row["uid"],
            idem_key=row["idem_key"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            updated_at=row["updated_at"],
            telegram_user_id=row["telegram_user_id"],
            telegram_chat_id=row["telegram_chat_id"],
            request=row["request"],
            project=row["project"],
            operation=row["operation"],
            kind=row["kind"],
            state=row["state"],
            phase=row["phase"],
            codex_state=row["codex_state"],
            claude_state=row["claude_state"],
            grok_state=row["grok_state"],
            executor=row["executor"],
            work_session_id=row["work_session_id"],
            work_lock_id=row["work_lock_id"],
            lock_state=row["lock_state"],
            files=json.loads(row["files_json"] or "[]"),
            tests_run=row["tests_run"],
            tests_passed=row["tests_passed"],
            tests_failed=row["tests_failed"],
            test_result=row["test_result"],
            test_command=row["test_command"],
            attempts=row["attempts"],
            restarts=row["restarts"],
            errors=json.loads(row["errors_json"] or "[]"),
            rollback=row["rollback"],
            result_summary=row["result_summary"],
            cancel_requested=bool(row["cancel_requested"]),
            project_path=row["project_path"],
        )

    def _event(self, conn: sqlite3.Connection, job_id: int, kind: str, detail: str = "") -> None:
        conn.execute(
            "INSERT INTO job_events(job_id, at, kind, detail) VALUES (?,?,?,?)",
            (job_id, time.time(), kind, sanitize(detail, 2000)),
        )

    # -- creation ----------------------------------------------------------

    def create(
        self,
        *,
        user_id: int,
        chat_id: int,
        request: str,
        kind: str,
        operation: str,
        project: Optional[str] = None,
        idem_key: Optional[str] = None,
    ) -> tuple[Job, bool]:
        """Create a job or return the existing one for the same idempotency key.

        Returns (job, created)."""
        now = time.time()
        uid = uuid.uuid4().hex
        with self._tx() as conn:
            if idem_key:
                row = conn.execute("SELECT * FROM jobs WHERE idem_key=?", (idem_key,)).fetchone()
                if row is not None:
                    return self._row_to_job(row), False
            cur = conn.execute(
                "INSERT INTO jobs(uid, idem_key, created_at, updated_at, telegram_user_id, telegram_chat_id,"
                " request, project, operation, kind, state, phase) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uid, idem_key, now, now, int(user_id), int(chat_id), sanitize(request, 8000),
                    project, sanitize(operation, 200), kind, QUEUED, "in coda",
                ),
            )
            job_id = int(cur.lastrowid)
            self._event(conn, job_id, "created", f"kind={kind} operation={operation} project={project or '-'}")
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return self._row_to_job(row), True

    # -- reads -------------------------------------------------------------

    def get(self, job_id: int) -> Optional[Job]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (int(job_id),)).fetchone()
        return self._row_to_job(row) if row is not None else None

    def get_by_idem(self, idem_key: str) -> Optional[Job]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE idem_key=?", (idem_key,)).fetchone()
        return self._row_to_job(row) if row is not None else None

    def active(self) -> list[Job]:
        marks = ",".join("?" for _ in ACTIVE_STATES)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM jobs WHERE state IN ({marks}) ORDER BY job_id", tuple(sorted(ACTIVE_STATES))
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def last(self, chat_id: Optional[int] = None) -> Optional[Job]:
        with self._lock:
            if chat_id is None:
                row = self._conn.execute("SELECT * FROM jobs ORDER BY job_id DESC LIMIT 1").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM jobs WHERE telegram_chat_id=? ORDER BY job_id DESC LIMIT 1", (int(chat_id),)
                ).fetchone()
        return self._row_to_job(row) if row is not None else None

    def recent(self, limit: int = 10, offset: int = 0, project: Optional[str] = None,
               state: Optional[str] = None) -> list[Job]:
        limit = max(1, min(int(limit), 50))
        offset = max(0, int(offset))
        clauses, params = [], []
        if project:
            clauses.append("project=?")
            params.append(project)
        if state:
            clauses.append("state=?")
            params.append(state)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM jobs {where} ORDER BY job_id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def events(self, job_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT at, kind, detail FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT ?",
                (int(job_id), int(limit)),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def ops(self, job_id: int, include_rolled_back: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT id, at, op, path, operation_id, rolled_back FROM job_ops WHERE job_id=?"
        if not include_rolled_back:
            sql += " AND rolled_back=0"
        sql += " ORDER BY id"
        with self._lock:
            rows = self._conn.execute(sql, (int(job_id),)).fetchall()
        return [dict(r) for r in rows]

    # -- writes ------------------------------------------------------------

    def transition(self, job_id: int, new_state: str, phase: Optional[str] = None,
                   *, _allow_recovery: bool = False) -> Job:
        if new_state not in ALL_STATES:
            raise InvalidTransition(f"unknown state {new_state}")
        now = time.time()
        with self._tx() as conn:
            row = conn.execute("SELECT state FROM jobs WHERE job_id=?", (int(job_id),)).fetchone()
            if row is None:
                raise InvalidTransition(f"unknown job {job_id}")
            current = row["state"]
            allowed = TRANSITIONS[current]
            recovery_ok = _allow_recovery and current in ACTIVE_STATES and new_state == QUEUED
            if new_state not in allowed and not recovery_ok:
                raise InvalidTransition(f"{current} -> {new_state} not allowed")
            sets = ["state=?", "updated_at=?"]
            params: list[Any] = [new_state, now]
            if phase is not None:
                sets.append("phase=?")
                params.append(sanitize(phase, 200))
            if new_state in TERMINAL_STATES:
                sets.append("completed_at=?")
                params.append(now)
            if new_state == ANALYZING:
                sets.append("started_at=COALESCE(started_at, ?)")
                params.append(now)
            params.append(int(job_id))
            conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id=?", params)
            self._event(conn, int(job_id), "state", f"{current} -> {new_state}" + (f" ({phase})" if phase else ""))
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (int(job_id),)).fetchone()
            return self._row_to_job(row)

    def update(self, job_id: int, **fields: Any) -> Job:
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"fields not updatable: {sorted(unknown)}")
        for agent in AGENTS:
            key = f"{agent}_state"
            if key in fields and fields[key] not in AGENT_STATES:
                raise ValueError(f"invalid agent state {fields[key]}")
        clean = {}
        for key, value in fields.items():
            clean[key] = sanitize(value, 4000) if key in _TEXT_FIELDS and value is not None else value
        with self._tx() as conn:
            sets = ", ".join(f"{k}=?" for k in clean) + ", updated_at=?"
            conn.execute(f"UPDATE jobs SET {sets} WHERE job_id=?", (*clean.values(), time.time(), int(job_id)))
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (int(job_id),)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return self._row_to_job(row)

    def set_agent(self, job_id: int, agent: str, state: str) -> None:
        if agent not in AGENTS:
            return
        self.update(job_id, **{f"{agent}_state": state})

    def add_error(self, job_id: int, error: str) -> None:
        with self._tx() as conn:
            row = conn.execute("SELECT errors_json FROM jobs WHERE job_id=?", (int(job_id),)).fetchone()
            errors = json.loads(row["errors_json"] or "[]") if row else []
            errors.append(sanitize(error, 1500))
            errors = errors[-20:]
            conn.execute("UPDATE jobs SET errors_json=?, updated_at=? WHERE job_id=?",
                         (json.dumps(errors, ensure_ascii=False), time.time(), int(job_id)))
            self._event(conn, int(job_id), "error", error)

    def add_files(self, job_id: int, paths: Iterable[str]) -> None:
        with self._tx() as conn:
            row = conn.execute("SELECT files_json FROM jobs WHERE job_id=?", (int(job_id),)).fetchone()
            files = json.loads(row["files_json"] or "[]") if row else []
            for p in paths:
                if p not in files:
                    files.append(p)
            conn.execute("UPDATE jobs SET files_json=?, updated_at=? WHERE job_id=?",
                         (json.dumps(files[:500], ensure_ascii=False), time.time(), int(job_id)))

    def record_op(self, job_id: int, op: str, path: str, operation_id: Optional[str]) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO job_ops(job_id, at, op, path, operation_id) VALUES (?,?,?,?,?)",
                (int(job_id), time.time(), op, path, operation_id),
            )
            self._event(conn, int(job_id), "op", f"{op} {path} op={operation_id or '-'}")

    def mark_op_rolled_back(self, op_row_id: int) -> None:
        with self._tx() as conn:
            conn.execute("UPDATE job_ops SET rolled_back=1 WHERE id=?", (int(op_row_id),))

    def event(self, job_id: int, kind: str, detail: str = "") -> None:
        with self._tx() as conn:
            self._event(conn, int(job_id), kind, detail)

    def request_cancel(self, job_id: int) -> bool:
        with self._tx() as conn:
            row = conn.execute("SELECT state FROM jobs WHERE job_id=?", (int(job_id),)).fetchone()
            if row is None or row["state"] in TERMINAL_STATES:
                return False
            conn.execute("UPDATE jobs SET cancel_requested=1, updated_at=? WHERE job_id=?",
                         (time.time(), int(job_id)))
            self._event(conn, int(job_id), "cancel_requested", "")
            return True

    def bump_restarts(self, job_id: int) -> int:
        with self._tx() as conn:
            conn.execute("UPDATE jobs SET restarts=restarts+1, updated_at=? WHERE job_id=?",
                         (time.time(), int(job_id)))
            return int(conn.execute("SELECT restarts FROM jobs WHERE job_id=?", (int(job_id),)).fetchone()[0])

    def requeue_after_restart(self, job_id: int, phase: str) -> Job:
        return self.transition(job_id, QUEUED, phase, _allow_recovery=True)

    def find_active_duplicate(self, chat_id: int, request: str, window: float = 180.0) -> Optional[Job]:
        """Same text from the same chat while an identical job is still active."""
        cutoff = time.time() - window
        clean = sanitize(request, 8000)
        marks = ",".join("?" for _ in ACTIVE_STATES)
        with self._lock:
            row = self._conn.execute(
                f"SELECT * FROM jobs WHERE telegram_chat_id=? AND request=? AND created_at>=? "
                f"AND state IN ({marks}) ORDER BY job_id DESC LIMIT 1",
                (int(chat_id), clean, cutoff, *sorted(ACTIVE_STATES)),
            ).fetchone()
        return self._row_to_job(row) if row is not None else None
