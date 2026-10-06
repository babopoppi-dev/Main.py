#!/usr/bin/python3
from __future__ import annotations

"""
ANDREA AI TEAM - controlled MCP write gate.

Runs as the same account as the existing restricted MCP status helper and is
the ONLY component of the TEAM that can reach MCP Andrea with write capability.

Trust model:
- the orchestrator talks to this process over a Unix socket (peer uid checked);
- it never receives MCP bearer tokens nor work_session capability tokens;
- every request is (job uid, project name, relative path): absolute paths are
  rebuilt here from the policy module and must stay inside the projects root;
- every mutation goes through MCP Andrea: work_session -> work_lock -> tool;
  MCP Andrea provides lease, heartbeat, hard-fail on conflicts, audit and
  durable rollback. Nothing here bypasses or re-implements those features;
- tests run only through the MCP isolated shell with network disabled, and
  only from the fixed command allowlist in gate_policy.TEST_COMMANDS.
"""

import json
import logging
import math
import os
import pwd
import socket
import ssl
import stat
import struct
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import gate_policy as policy
from redact import sanitize


LOG = logging.getLogger("andrea-ai-team-gate")
MAX_REQUEST = 3 * 1024 * 1024
MAX_RESPONSE = 2 * 1024 * 1024
MACHINE = "vps"
# Short leases: if the whole stack dies, MCP Andrea frees the locks quickly by itself.
SESSION_MINUTES = int(os.environ.get("GATE_SESSION_MINUTES", "20"))
LOCK_MINUTES = int(os.environ.get("GATE_LOCK_MINUTES", "20"))
MAX_SESSIONS = 4
SHELL_HEARTBEAT_SECONDS = 15


class GateError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = sanitize(detail, 300)


# --------------------------------------------------------------------------
# MCP Andrea transport (same local gateway endpoint as mcp_probe_server.py)
# --------------------------------------------------------------------------

def _classify_mcp_error(text: str) -> str:
    low = (text or "").lower()
    # The live gateway hides exception messages ("Internal error for <tool>: <Type>").
    # A refused work_lock acquire is a PermissionError: path locked by another session.
    if "for work_lock" in low and "permissionerror" in low:
        return "LOCK_CONFLICT"
    if "for enable_full_shell" in low and "permissionerror" in low:
        return "LOCK_REQUIRED"
    if any(k in low for k in ("conflict", "already locked", "held by", "locked by", "lock is held")):
        return "LOCK_CONFLICT"
    if "lock" in low and any(k in low for k in ("required", "covering", "not covered", "missing")):
        return "LOCK_REQUIRED"
    if any(k in low for k in ("expired", "unknown work_session", "invalid work_session", "session not")):
        return "SESSION_EXPIRED"
    if any(k in low for k in ("outside", "not allowed", "denied", "protected", "forbidden")):
        return "MCP_DENIED"
    if any(k in low for k in ("exists", "already exist")):
        return "ALREADY_EXISTS"
    if any(k in low for k in ("timeout", "timed out")):
        return "MCP_TIMEOUT"
    return "MCP_ERROR"


class MCPGatewayClient:
    """Minimal JSON-RPC tools/call client for the local MCP Andrea gateway."""

    def __init__(self, config_path: str):
        self.config_path = Path(config_path)

    def _load(self) -> tuple[str, str, ssl.SSLContext]:
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            raise GateError("GATE_CONFIG")
        token_file = cfg.get("mcp_token_file")
        tls_cert = cfg.get("tls_cert")
        port = cfg.get("port")
        if not token_file or not tls_cert or port is None:
            raise GateError("GATE_CONFIG")
        secret = Path(str(token_file)).read_text(encoding="utf-8").strip()
        if not secret:
            raise GateError("GATE_CONFIG")
        ctx = ssl.create_default_context(cafile=str(tls_cert))
        ctx.check_hostname = False
        return f"https://127.0.0.1:{int(port)}/mcp", secret, ctx

    def call(self, tool: str, arguments: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        try:
            url, secret, ctx = self._load()
        except GateError:
            raise
        except Exception as exc:
            raise GateError("GATE_CONFIG", type(exc).__name__) from None
        payload = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + secret},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                obj = json.load(resp)
        except urllib.error.HTTPError as exc:
            raise GateError("MCP_HTTP", str(exc.code)) from None
        except (TimeoutError, socket.timeout):
            raise GateError("MCP_TIMEOUT") from None
        except Exception as exc:
            raise GateError("MCP_UNREACHABLE", type(exc).__name__) from None
        return parse_tool_response(obj)


def parse_tool_response(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise GateError("MCP_ERROR", "invalid response")
    if "error" in obj:
        err = obj.get("error") or {}
        message = str(err.get("message", "")) if isinstance(err, dict) else str(err)
        raise GateError(_classify_mcp_error(message), message)
    result = obj.get("result") or {}
    content = result.get("content") if isinstance(result, dict) else None
    text = ""
    if isinstance(content, list) and content and isinstance(content[0], dict):
        text = str(content[0].get("text", ""))
    if isinstance(result, dict) and result.get("isError"):
        raise GateError(_classify_mcp_error(text), text)
    if isinstance(result, dict) and isinstance(result.get("structuredContent"), dict) and not text:
        return dict(result["structuredContent"])
    try:
        parsed = json.loads(text) if text else {}
    except Exception:
        parsed = {"text": text}
    if not isinstance(parsed, dict):
        parsed = {"value": parsed}
    return parsed


# --------------------------------------------------------------------------
# Gate core (transport-independent, unit tested with a fake MCP)
# --------------------------------------------------------------------------

def _first(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def normalize_shell_result(res: dict[str, Any]) -> dict[str, Any]:
    code = _first(res, "exit_code", "returncode", "rc", "code", "status_code")
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    stdout = str(_first(res, "stdout", "output", "out", default="") or "")
    stderr = str(_first(res, "stderr", "err", default="") or "")
    running = bool(_first(res, "running", default=False))
    timed_out = bool(_first(res, "timed_out", "timeout_expired", default=False))
    return {"exit_code": code, "stdout": stdout, "stderr": stderr, "running": running, "timed_out": timed_out}


class _Session:
    def __init__(self, uid: str, project: str, session_id: str, token: str):
        self.uid = uid
        self.project = project
        self.session_id = session_id
        self.token = token
        self.locks: dict[str, str] = {}
        self.created = time.time()
        self.lock = threading.RLock()


class GateCore:
    def __init__(
        self,
        mcp_call: Callable[[str, dict[str, Any], float], dict[str, Any]],
        projects_root: str = policy.DEFAULT_PROJECTS_ROOT,
        shell_lock_path: Optional[str] = None,
        sleep: Callable[[float], None] = time.sleep,
        shell_lock_wait: float = 300.0,
        shell_lock_poll: float = 10.0,
    ):
        self._mcp = mcp_call
        self.root = projects_root.rstrip("/")
        self.shell_lock_path = shell_lock_path
        self._sleep = sleep
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.RLock()
        # MCP Andrea runs one isolated workspace shell at a time.
        self._shell_mutex = threading.Lock()
        self.shell_lock_wait = shell_lock_wait
        self.shell_lock_poll = shell_lock_poll

    # -- internals ---------------------------------------------------------

    def _call(self, tool: str, args: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        args = dict(args)
        args.setdefault("machine", MACHINE)
        return self._mcp(tool, args, timeout)

    def _auth(self, s: _Session) -> dict[str, str]:
        return {"work_session_id": s.session_id, "work_session_token": s.token}

    def _session(self, uid: str, project: str) -> _Session:
        policy.validate_uid(uid)
        with self._lock:
            s = self._sessions.get(uid)
        if s is None:
            raise GateError("NO_SESSION")
        if s.project != project:
            raise GateError("PROJECT_MISMATCH")
        return s

    @staticmethod
    def _overlaps(a: str, b: str) -> bool:
        a, b = a.rstrip("/"), b.rstrip("/")
        return a == b or a.startswith(b + "/") or b.startswith(a + "/")

    def _foreign_lock_on(self, s: _Session, path: str) -> Optional[str]:
        """The live gateway hides why a call failed: ask who_is_working (read-only)."""
        try:
            info = self._call("who_is_working", {}, 20.0)
        except GateError:
            return None
        for lk in info.get("work_locks") or []:
            if not isinstance(lk, dict):
                continue
            other = str(lk.get("session_id", ""))
            if other and other != s.session_id and self._overlaps(str(lk.get("path", "")), path):
                return other
        return None

    def _acquire(self, s: _Session, name: str, path: str, minutes: int = LOCK_MINUTES) -> str:
        try:
            res = self._call("work_lock", {"action": "acquire", "path": path, "minutes": minutes, **self._auth(s)})
        except GateError as exc:
            if exc.code in {"MCP_ERROR", "LOCK_CONFLICT"}:
                holder = self._foreign_lock_on(s, path)
                if holder:
                    raise GateError("LOCK_CONFLICT", f"path locked by work session {holder[:8]}") from None
            raise
        lock_id = str(res.get("lock_id", ""))
        if not lock_id:
            raise GateError("LOCK_FAILED")
        s.locks[name] = lock_id
        return lock_id

    def _release_all(self, s: _Session) -> None:
        for name, lock_id in list(s.locks.items()):
            try:
                self._call("work_lock", {"action": "release", "lock_id": lock_id, **self._auth(s)})
            except GateError as exc:
                LOG.warning("lock release failed name=%s code=%s", name, exc.code)
            s.locks.pop(name, None)

    # -- lifecycle ---------------------------------------------------------

    def begin(self, uid: str, project: str, label: str = "") -> dict[str, Any]:
        policy.validate_uid(uid)
        policy.validate_project_name(project)
        with self._lock:
            existing = self._sessions.get(uid)
            if existing is not None:
                if existing.project != project:
                    raise GateError("PROJECT_MISMATCH")
                return self._describe(existing, resumed=True)
            if len(self._sessions) >= MAX_SESSIONS:
                raise GateError("GATE_BUSY")
        safe_label = f"andrea-ai-team job {uid[:8]} {project}"[:80]
        res = self._call("work_session", {"action": "open", "label": safe_label, "minutes": SESSION_MINUTES})
        sid = str(res.get("work_session_id", ""))
        token = str(res.get("work_session_token", ""))
        if not sid or not token:
            raise GateError("SESSION_FAILED")
        s = _Session(uid, project, sid, token)
        try:
            self._acquire(s, "project", policy.project_path(self.root, project))
            self._acquire(s, "snapshot", policy.snapshot_parent(self.root, project))
            self._acquire(s, "trash", policy.trash_path(self.root, project, uid))
        except GateError:
            # Hard-fail on conflicts: give back what we hold, never steal.
            self._release_all(s)
            try:
                self._call("work_session", {"action": "close", **self._auth(s)})
            except GateError:
                pass
            raise
        with self._lock:
            self._sessions[uid] = s
        return self._describe(s, resumed=False)

    def _describe(self, s: _Session, resumed: bool) -> dict[str, Any]:
        return {
            "work_session_id": s.session_id,
            "work_lock_id": s.locks.get("project", ""),
            "locks": len(s.locks),
            "resumed": resumed,
        }

    def heartbeat(self, uid: str, project: str) -> dict[str, Any]:
        s = self._session(uid, project)
        with s.lock:
            self._call("work_session", {"action": "renew", "minutes": SESSION_MINUTES, **self._auth(s)})
            for lock_id in list(s.locks.values()):
                self._call("work_lock", {"action": "renew", "lock_id": lock_id, "minutes": LOCK_MINUTES,
                                         **self._auth(s)})
        return {"renewed": True}

    def end(self, uid: str, project: str) -> dict[str, Any]:
        s = self._session(uid, project)
        with s.lock:
            self._release_all(s)
            try:
                self._call("work_session", {"action": "close", **self._auth(s)})
            except GateError as exc:
                LOG.warning("session close failed code=%s", exc.code)
        with self._lock:
            self._sessions.pop(uid, None)
        return {"closed": True}

    def has_session(self, uid: str) -> dict[str, Any]:
        policy.validate_uid(uid)
        with self._lock:
            s = self._sessions.get(uid)
        return {"active": s is not None, "project": s.project if s else None}

    # -- read operations (no lock needed by MCP; session still required) ----

    def exists(self, uid: str, project: str, rel: str = "") -> dict[str, Any]:
        s = self._session(uid, project)
        path = policy.file_path(self.root, project, rel, allow_root=True)
        try:
            info = self._call("get_file_info", {"path": path, **self._auth(s)})
        except GateError as exc:
            if exc.code in {"MCP_ERROR", "MCP_DENIED"}:
                return {"exists": False}
            raise
        return {"exists": True, "is_directory": bool(info.get("is_directory")), "size": info.get("size")}

    def list(self, uid: str, project: str, rel: str = "", depth: int = 4) -> dict[str, Any]:
        s = self._session(uid, project)
        path = policy.file_path(self.root, project, rel, allow_root=True)
        res = self._call("list_directory", {"path": path, "depth": max(0, min(int(depth), 6)), **self._auth(s)})
        return {"entries": list(res.get("entries", []))[:500], "truncated": bool(res.get("truncated"))}

    def read(self, uid: str, project: str, rel: str, max_bytes: int = policy.MAX_FILE_BYTES) -> dict[str, Any]:
        s = self._session(uid, project)
        path = policy.file_path(self.root, project, rel)
        res = self._call("read_file", {"path": path, "max_bytes": max(1, min(int(max_bytes), policy.MAX_FILE_BYTES)),
                                       **self._auth(s)})
        return {"content": str(res.get("content", "")), "truncated": bool(res.get("truncated"))}

    # -- mutations: always inside the session's own covering locks ----------

    def mkdir(self, uid: str, project: str, rel: str = "") -> dict[str, Any]:
        s = self._session(uid, project)
        path = policy.file_path(self.root, project, rel, allow_root=True)
        res = self._call("create_directory", {"path": path, **self._auth(s)})
        return {"operation_id": res.get("operation_id"), "created": bool(res.get("created", True))}

    def write(self, uid: str, project: str, rel: str, content: str) -> dict[str, Any]:
        s = self._session(uid, project)
        path = policy.file_path(self.root, project, rel)
        policy.check_content(content)
        res = self._call("write_file", {"path": path, "content": content, "mode": "rewrite", **self._auth(s)})
        return {"operation_id": res.get("operation_id"), "bytes": res.get("bytes_written")}

    def move(self, uid: str, project: str, rel: str, dst: str) -> dict[str, Any]:
        s = self._session(uid, project)
        src_path = policy.file_path(self.root, project, rel)
        dst_path = policy.file_path(self.root, project, dst)
        res = self._call("move_file", {"source": src_path, "destination": dst_path, **self._auth(s)})
        return {"operation_id": res.get("operation_id")}

    def copy(self, uid: str, project: str, rel: str, dst: str) -> dict[str, Any]:
        s = self._session(uid, project)
        src_path = policy.file_path(self.root, project, rel)
        dst_path = policy.file_path(self.root, project, dst)
        res = self._call("copy_file", {"source": src_path, "destination": dst_path, **self._auth(s)})
        return {"operation_id": res.get("operation_id")}

    def delete(self, uid: str, project: str, rel: str) -> dict[str, Any]:
        s = self._session(uid, project)
        path = policy.file_path(self.root, project, rel)
        res = self._call("delete_path", {"path": path, **self._auth(s)})
        return {"operation_id": res.get("operation_id")}

    def rollback(self, uid: str, project: str, operation_id: str) -> dict[str, Any]:
        s = self._session(uid, project)
        policy.validate_uid(operation_id)  # same 32-hex shape
        res = self._call("rollback_file", {"operation_id": operation_id, **self._auth(s)})
        return {"rolled_back": bool(res.get("rolled_back"))}

    def snapshot(self, uid: str, project: str) -> dict[str, Any]:
        """Copy the whole project to .snapshots/<project>/<uid> (never overwrites)."""
        s = self._session(uid, project)
        parent = policy.snapshot_parent(self.root, project)
        try:
            self._call("create_directory", {"path": parent, **self._auth(s)})
        except GateError as exc:
            if exc.code not in {"ALREADY_EXISTS"}:
                info_ok = True
                try:
                    self._call("get_file_info", {"path": parent, **self._auth(s)})
                except GateError:
                    info_ok = False
                if not info_ok:
                    raise
        dest = policy.snapshot_path(self.root, project, uid)
        try:
            self._call("get_file_info", {"path": dest, **self._auth(s)})
            # Job resumed after a restart: the pre-job snapshot already exists and is the right restore point.
            return {"operation_id": None, "snapshot": uid, "existing": True}
        except GateError:
            pass
        res = self._call("copy_file", {"source": policy.project_path(self.root, project), "destination": dest,
                                       **self._auth(s)})
        return {"operation_id": res.get("operation_id"), "snapshot": uid}

    def restore_snapshot(self, uid: str, project: str, snapshot_uid: str) -> dict[str, Any]:
        """Move the current project to .trash and copy the snapshot back."""
        s = self._session(uid, project)
        snap = policy.snapshot_path(self.root, project, snapshot_uid)
        self._call("get_file_info", {"path": snap, **self._auth(s)})
        moved = self.trash_project(uid, project)
        res = self._call("copy_file", {"source": snap, "destination": policy.project_path(self.root, project),
                                       **self._auth(s)})
        return {"restored": True, "trash": moved.get("trash"), "operation_id": res.get("operation_id")}

    def trash_project(self, uid: str, project: str) -> dict[str, Any]:
        """Keep a copy in .trash, then delete the project tree (MCP move_file does not move directories)."""
        s = self._session(uid, project)
        parent = policy.trash_path(self.root, project, uid)
        self._call("create_directory", {"path": parent, **self._auth(s)})
        dest = f"{parent}/{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
        src = policy.project_path(self.root, project)
        copied = self._call("copy_file", {"source": src, "destination": dest, **self._auth(s)})
        deleted = self._call("delete_path", {"path": src, **self._auth(s)})
        return {"operation_id": deleted.get("operation_id"), "copy_operation_id": copied.get("operation_id"),
                "trash": dest[len(self.root) + 1:]}

    # -- tests through the MCP isolated shell (network disabled) ------------

    def run_tests(self, uid: str, project: str, kind: str = "unittest", timeout: int = 180) -> dict[str, Any]:
        s = self._session(uid, project)
        command = policy.test_command(kind)
        timeout = max(10, min(int(timeout), 900))
        cwd = policy.project_path(self.root, project)
        extra_lock: Optional[str] = None
        with self._shell_mutex, s.lock:
            if self.shell_lock_path:
                # The live agent requires a lock covering the whole shell workspace. Another
                # session may hold one inside it: wait (bounded), never steal.
                waited = 0.0
                while True:
                    try:
                        extra_lock = self._acquire(s, "shell", self.shell_lock_path,
                                                   minutes=max(2, math.ceil(timeout / 60) + 2))
                        break
                    except GateError as exc:
                        if exc.code != "LOCK_CONFLICT" or waited >= self.shell_lock_wait:
                            raise
                        self._sleep(self.shell_lock_poll)
                        waited += self.shell_lock_poll
            stop = threading.Event()
            hb: Optional[threading.Thread] = None
            enabled = False
            try:
                self._call("enable_full_shell", {"minutes": max(2, math.ceil(timeout / 60) + 1), "network": "none",
                                                 **self._auth(s)})
                enabled = True

                def beat() -> None:
                    while not stop.wait(SHELL_HEARTBEAT_SECONDS):
                        try:
                            self._call("shell_session", {"action": "heartbeat", **self._auth(s)}, 15.0)
                        except GateError as exc:
                            LOG.warning("shell heartbeat failed code=%s", exc.code)

                hb = threading.Thread(target=beat, name=f"shell-hb-{uid[:8]}", daemon=True)
                hb.start()
                started = time.monotonic()
                raw = self._call("shell_exec", {"command": command, "cwd": cwd, "timeout": timeout, **self._auth(s)},
                                 float(timeout + 30))
                res = normalize_shell_result(raw)
                shell_sid = raw.get("session_id")
                deadline = started + timeout + 30
                has_more = bool(raw.get("has_more"))
                # The live agent answers after <=3 s; longer runs continue as a session to poll.
                while shell_sid and (res["exit_code"] is None or has_more) and time.monotonic() < deadline:
                    if not has_more:
                        self._sleep(2.0)
                    raw2 = self._call("shell_session", {"action": "read", "session_id": shell_sid, **self._auth(s)},
                                      30.0)
                    part = normalize_shell_result(raw2)
                    res["stdout"] += part["stdout"]
                    res["stderr"] += part["stderr"]
                    if part["exit_code"] is not None:
                        res["exit_code"] = part["exit_code"]
                    has_more = bool(raw2.get("has_more"))
                    if not part["running"] and part["exit_code"] is None and not has_more and raw2.get("done"):
                        break
                if res["exit_code"] is None:
                    res["timed_out"] = True
                    if shell_sid:
                        try:
                            self._call("shell_session", {"action": "stop", "session_id": shell_sid, **self._auth(s)})
                        except GateError:
                            pass
            finally:
                stop.set()
                if hb is not None:
                    hb.join(timeout=2)
                if enabled:
                    try:
                        self._call("disable_full_shell", self._auth(s))
                    except GateError as exc:
                        LOG.warning("disable shell failed code=%s", exc.code)
                if extra_lock:
                    try:
                        self._call("work_lock", {"action": "release", "lock_id": extra_lock, **self._auth(s)})
                    except GateError:
                        pass
                    s.locks.pop("shell", None)
        return {
            "command": kind,
            "exit_code": res["exit_code"],
            "timed_out": res["timed_out"],
            "stdout": sanitize(res["stdout"][-20000:], 20000),
            "stderr": sanitize(res["stderr"][-20000:], 20000),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            n = len(self._sessions)
        return {"ok": True, "sessions": n, "root": self.root}

    # -- dispatcher ---------------------------------------------------------

    def handle(self, req: dict[str, Any]) -> dict[str, Any]:
        op = str(req.get("op", ""))
        uid = str(req.get("job", ""))
        project = str(req.get("project", ""))
        handlers: dict[str, Callable[[], dict[str, Any]]] = {
            "status": lambda: self.status(),
            "begin": lambda: self.begin(uid, project),
            "heartbeat": lambda: self.heartbeat(uid, project),
            "end": lambda: self.end(uid, project),
            "has_session": lambda: self.has_session(uid),
            "exists": lambda: self.exists(uid, project, str(req.get("path", ""))),
            "list": lambda: self.list(uid, project, str(req.get("path", "")), int(req.get("depth", 4))),
            "read": lambda: self.read(uid, project, str(req.get("path", ""))),
            "mkdir": lambda: self.mkdir(uid, project, str(req.get("path", ""))),
            "write": lambda: self.write(uid, project, str(req.get("path", "")), req.get("content")),
            "move": lambda: self.move(uid, project, str(req.get("path", "")), str(req.get("dest", ""))),
            "copy": lambda: self.copy(uid, project, str(req.get("path", "")), str(req.get("dest", ""))),
            "delete": lambda: self.delete(uid, project, str(req.get("path", ""))),
            "rollback": lambda: self.rollback(uid, project, str(req.get("operation_id", ""))),
            "snapshot": lambda: self.snapshot(uid, project),
            "restore_snapshot": lambda: self.restore_snapshot(uid, project, str(req.get("snapshot", ""))),
            "trash_project": lambda: self.trash_project(uid, project),
            "run_tests": lambda: self.run_tests(uid, project, str(req.get("kind", "unittest")),
                                                int(req.get("timeout", 180))),
        }
        fn = handlers.get(op)
        if fn is None:
            return {"ok": False, "error": "OP_NOT_ALLOWED"}
        started = time.monotonic()
        try:
            data = fn()
            out = {"ok": True, **data}
        except policy.PolicyError as exc:
            out = {"ok": False, "error": exc.code, "detail": sanitize(exc.detail, 200)}
        except GateError as exc:
            out = {"ok": False, "error": exc.code, "detail": exc.detail}
        except Exception as exc:  # never leak internals
            LOG.error("gate op failed op=%s type=%s", op, type(exc).__name__)
            out = {"ok": False, "error": "GATE_INTERNAL", "detail": type(exc).__name__}
        # Audit line: never content, never tokens.
        LOG.info(
            "audit op=%s job=%s project=%s path=%s ok=%s err=%s ms=%d",
            op, uid[:8], project[:40], str(req.get("path", ""))[:120], out.get("ok"), out.get("error", "-"),
            int((time.monotonic() - started) * 1000),
        )
        return out


# --------------------------------------------------------------------------
# Unix socket server
# --------------------------------------------------------------------------

def _peer_uid(conn: socket.socket) -> int:
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", creds)
    return uid


def _serve_client(core: GateCore, conn: socket.socket, allowed_uids: set[int]) -> None:
    try:
        if allowed_uids and _peer_uid(conn) not in allowed_uids:
            # Drain the (ignored) request first, bounded, so the client reads the refusal instead of
            # hitting a broken pipe while still sending.
            conn.settimeout(2.0)
            try:
                drained = 0
                while drained < 65536:
                    part = conn.recv(65536)
                    if not part:
                        break
                    drained += len(part)
                    if b"\n" in part:
                        break
            except OSError:
                pass
            conn.sendall(b'{"ok":false,"error":"PEER_NOT_ALLOWED"}\n')
            return
        conn.settimeout(30.0)
        chunks: list[bytes] = []
        size = 0
        while True:
            part = conn.recv(65536)
            if not part:
                break
            chunks.append(part)
            size += len(part)
            if size > MAX_REQUEST:
                conn.sendall(b'{"ok":false,"error":"REQUEST_TOO_LARGE"}\n')
                return
            if b"\n" in part:
                break
        raw = b"".join(chunks).split(b"\n", 1)[0]
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            conn.sendall(b'{"ok":false,"error":"INVALID_JSON"}\n')
            return
        if not isinstance(req, dict):
            conn.sendall(b'{"ok":false,"error":"INVALID_REQUEST"}\n')
            return
        conn.settimeout(None)
        out = core.handle(req)
        payload = (json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8")
        if len(payload) > MAX_RESPONSE:
            payload = b'{"ok":false,"error":"RESPONSE_TOO_LARGE"}\n'
        conn.sendall(payload)
    except Exception as exc:
        LOG.warning("gate client error: %s", type(exc).__name__)
    finally:
        conn.close()


def _allowed_uids() -> set[int]:
    out: set[int] = set()
    for name in os.environ.get("GATE_ALLOWED_USERS", "andrea-ai-team").split(","):
        name = name.strip()
        if not name:
            continue
        try:
            out.add(pwd.getpwnam(name).pw_uid)
        except KeyError:
            LOG.error("allowed gate user not found: %s", name)
    if not out:
        raise RuntimeError("no allowed gate peer")
    return out


def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    client = MCPGatewayClient(os.environ.get("MCP_GATEWAY_CONFIG", "/etc/central-mcp-gateway/gateway-test.json"))
    core = GateCore(
        client.call,
        projects_root=os.environ.get("TEAM_PROJECTS_ROOT", policy.DEFAULT_PROJECTS_ROOT),
        shell_lock_path=(os.environ.get("GATE_SHELL_LOCK_PATH", "").strip() or None),
        shell_lock_wait=float(os.environ.get("GATE_SHELL_LOCK_WAIT", "300")),
    )
    allowed = _allowed_uids()
    socket_path = Path(os.environ.get("GATE_SOCKET", "/run/andrea-ai-team-gate/gate.sock"))
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    os.chmod(socket_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)
    server.listen(16)
    LOG.info("ANDREA AI TEAM write gate listening root=%s", core.root)
    try:
        while True:
            conn, _ = server.accept()
            threading.Thread(target=_serve_client, args=(core, conn, allowed), daemon=True,
                             name="gate-client").start()
    finally:
        server.close()
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
