from __future__ import annotations

"""
Offline test kit for ANDREA AI TEAM v3.

FakeMCP emulates the MCP Andrea semantics the gate relies on, on top of a real
temporary directory: work_session, work_lock (exclusive, parent/child conflict,
no stealing), lock-covered mutations, durable per-operation rollback owned by
the creating session, isolated shell lease and shell_exec (really runs the
allowlisted test command so test failures and fixes are genuine).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Any, Optional

import gate_policy as policy
from gate_server import GateCore, GateError, _classify_mcp_error
from write_gate import GateError as ClientGateError, WriteGateClient

VIRTUAL_WORKSPACE = "/var/lib/central-mcp-vps-agent-test/workspace"
VIRTUAL_ROOT = VIRTUAL_WORKSPACE + "/team-projects"


class FakeMCP:
    def __init__(self, base_dir: str):
        self.base = base_dir
        os.makedirs(self.real(VIRTUAL_ROOT), exist_ok=True)
        os.makedirs(self.real(VIRTUAL_ROOT + "/.snapshots"), exist_ok=True)
        os.makedirs(self.real(VIRTUAL_ROOT + "/.trash"), exist_ok=True)
        self.sessions: dict[str, dict[str, Any]] = {}
        self.locks: dict[str, dict[str, Any]] = {}
        self.ops: dict[str, dict[str, Any]] = {}
        self.shell_enabled: set[str] = set()
        self.shell_jobs: dict[str, dict[str, Any]] = {}
        self.commands: list[str] = []
        self.calls: list[str] = []
        self.unreachable = False
        self.fail_tools: set[str] = set()
        self._lock = threading.RLock()

    # -- path mapping ----------------------------------------------------------

    def real(self, vpath: str) -> str:
        if not (vpath == VIRTUAL_WORKSPACE or vpath.startswith(VIRTUAL_WORKSPACE + "/")):
            raise GateError("MCP_DENIED", "path outside allowed roots")
        rel = vpath[len(VIRTUAL_WORKSPACE):].lstrip("/")
        out = os.path.normpath(os.path.join(self.base, rel))
        if not (out == os.path.normpath(self.base) or out.startswith(os.path.normpath(self.base) + os.sep)):
            raise GateError("MCP_DENIED", "path outside allowed roots")
        return out

    # -- session / lock ----------------------------------------------------------

    def _auth(self, args: dict[str, Any]) -> str:
        sid = args.get("work_session_id")
        s = self.sessions.get(sid or "")
        if not s or s["token"] != args.get("work_session_token") or s["closed"]:
            raise GateError("SESSION_EXPIRED", "invalid work_session")
        return sid

    @staticmethod
    def _overlap(a: str, b: str) -> bool:
        return a == b or a.startswith(b + "/") or b.startswith(a + "/")

    def _covered(self, sid: str, path: str) -> bool:
        for lk in self.locks.values():
            if lk["sid"] == sid and (path == lk["path"] or path.startswith(lk["path"] + "/")):
                return True
        return False

    def _need_lock(self, sid: str, *paths: str) -> None:
        for p in paths:
            if not self._covered(sid, p):
                raise GateError("LOCK_REQUIRED", "covering work_lock required")

    def expire_sessions(self) -> None:
        """Simulate MCP lease expiry of every open session (e.g. after the whole stack died)."""
        with self._lock:
            for s in self.sessions.values():
                s["closed"] = True
            self.locks.clear()
            self.shell_enabled.clear()

    def external_lock(self, path: str) -> tuple[str, str]:
        """Simulate another chat/agent holding a lock."""
        res = self.call("work_session", {"action": "open", "label": "other-chat", "minutes": 60})
        sid, tok = res["work_session_id"], res["work_session_token"]
        lk = self.call("work_lock", {"action": "acquire", "path": path, "minutes": 60,
                                     "work_session_id": sid, "work_session_token": tok})
        return sid, lk["lock_id"]

    # -- dispatcher --------------------------------------------------------------

    def call(self, tool: str, args: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        if self.unreachable:
            raise GateError("MCP_UNREACHABLE", "URLError")
        if tool in self.fail_tools:
            raise GateError("MCP_ERROR", "Internal error")
        with self._lock:
            self.calls.append(tool)
            fn = getattr(self, "t_" + tool, None)
            if fn is None:
                raise GateError("MCP_ERROR", f"unknown tool {tool}")
        # shell_exec runs outside the global lock so concurrent jobs can test in parallel
        if tool == "shell_exec":
            return fn(args, timeout)
        with self._lock:
            return fn(args)

    def t_work_session(self, a: dict[str, Any]) -> dict[str, Any]:
        action = a["action"]
        if action == "open":
            sid = uuid.uuid4().hex
            tok = uuid.uuid4().hex[:43].ljust(43, "x")
            self.sessions[sid] = {"token": tok, "closed": False, "label": a.get("label", "")}
            return {"work_session_id": sid, "work_session_token": tok}
        sid = self._auth(a)
        if action == "renew":
            return {"renewed": True}
        if action == "close":
            self.sessions[sid]["closed"] = True
            for lid in [k for k, v in self.locks.items() if v["sid"] == sid]:
                self.locks.pop(lid)
            self.shell_enabled.discard(sid)
            return {"closed": True}
        raise GateError("MCP_ERROR", "bad action")

    def t_work_lock(self, a: dict[str, Any]) -> dict[str, Any]:
        sid = self._auth(a)
        action = a["action"]
        if action == "acquire":
            path = a["path"]
            self.real(path)
            for lk in self.locks.values():
                if lk["sid"] != sid and self._overlap(lk["path"], path):
                    # Live gateway hides the message and returns only the exception type.
                    msg = "[-32603] Internal error for work_lock: RuntimeError. Do not loop-retry"
                    raise GateError(_classify_mcp_error(msg), msg)
            lid = uuid.uuid4().hex
            self.locks[lid] = {"sid": sid, "path": path}
            return {"lock_id": lid, "path": path}
        lid = a.get("lock_id", "")
        lk = self.locks.get(lid)
        if lk is None or lk["sid"] != sid:
            raise GateError("MCP_DENIED", "not your lock")
        if action == "release":
            self.locks.pop(lid)
            return {"released": True}
        return {"renewed": True}

    def t_who_is_working(self, a: dict[str, Any]) -> dict[str, Any]:
        return {"work_locks": [{"lock_id": k, "session_id": v["sid"], "path": v["path"]}
                               for k, v in self.locks.items()]}

    def _journal(self, sid: str, kind: str, **info: Any) -> str:
        op = uuid.uuid4().hex
        self.ops[op] = {"sid": sid, "kind": kind, **info}
        return op

    def t_create_directory(self, a: dict[str, Any]) -> dict[str, Any]:
        sid = self._auth(a)
        self._need_lock(sid, a["path"])
        rp = self.real(a["path"])
        created = not os.path.isdir(rp)
        if created:
            if not os.path.isdir(os.path.dirname(rp)):
                raise GateError("MCP_ERROR", "parent missing")
            os.mkdir(rp)
        return {"path": a["path"], "created": created,
                "operation_id": self._journal(sid, "mkdir", path=rp, created=created)}

    def t_write_file(self, a: dict[str, Any]) -> dict[str, Any]:
        sid = self._auth(a)
        self._need_lock(sid, a["path"])
        rp = self.real(a["path"])
        if not os.path.isdir(os.path.dirname(rp)):
            raise GateError("MCP_ERROR", "parent missing")
        prev = None
        if os.path.exists(rp):
            with open(rp, encoding="utf-8") as fh:
                prev = fh.read()
        with open(rp, "w", encoding="utf-8") as fh:
            fh.write(a["content"])
        return {"bytes_written": len(a["content"].encode()),
                "operation_id": self._journal(sid, "write", path=rp, prev=prev, new=a["content"])}

    def t_read_file(self, a: dict[str, Any]) -> dict[str, Any]:
        rp = self.real(a["path"])
        if not os.path.isfile(rp):
            raise GateError("MCP_ERROR", "Internal error for read_file: RuntimeError")
        with open(rp, encoding="utf-8") as fh:
            return {"content": fh.read()}

    def t_get_file_info(self, a: dict[str, Any]) -> dict[str, Any]:
        rp = self.real(a["path"])
        if not os.path.exists(rp):
            raise GateError("MCP_ERROR", "Internal error for get_file_info: RuntimeError")
        return {"path": a["path"], "is_directory": os.path.isdir(rp), "size": os.path.getsize(rp)}

    def t_list_directory(self, a: dict[str, Any]) -> dict[str, Any]:
        rp = self.real(a["path"])
        if not os.path.isdir(rp):
            raise GateError("MCP_ERROR", "Internal error for list_directory: RuntimeError")
        entries = []
        depth = int(a.get("depth", 2))
        for dirpath, dirnames, filenames in os.walk(rp):
            rel = os.path.relpath(dirpath, rp)
            level = 0 if rel == "." else rel.count(os.sep) + 1
            if level >= depth:
                dirnames[:] = []
            for d in sorted(dirnames):
                entries.append("[DIR] " + os.path.normpath(os.path.join(rel, d)).replace(os.sep, "/"))
            for f in sorted(filenames):
                entries.append("[FILE] " + os.path.normpath(os.path.join(rel, f)).replace(os.sep, "/"))
        return {"path": a["path"], "entries": entries, "truncated": False}

    def t_copy_file(self, a: dict[str, Any]) -> dict[str, Any]:
        sid = self._auth(a)
        self._need_lock(sid, a["source"], a["destination"])
        src, dst = self.real(a["source"]), self.real(a["destination"])
        if os.path.exists(dst):
            raise GateError("ALREADY_EXISTS", "destination exists")
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return {"operation_id": self._journal(sid, "copy", dst=dst)}

    def t_move_file(self, a: dict[str, Any]) -> dict[str, Any]:
        sid = self._auth(a)
        self._need_lock(sid, a["source"], a["destination"])
        src, dst = self.real(a["source"]), self.real(a["destination"])
        if os.path.isdir(src):
            # Same as the live agent (verified 2026-10-06): move_file refuses directories.
            raise GateError("MCP_ERROR", "Internal error for move_file: RuntimeError")
        if os.path.exists(dst):
            raise GateError("ALREADY_EXISTS", "destination exists")
        os.rename(src, dst)
        return {"operation_id": self._journal(sid, "move", src=src, dst=dst)}

    def t_delete_path(self, a: dict[str, Any]) -> dict[str, Any]:
        sid = self._auth(a)
        self._need_lock(sid, a["path"])
        rp = self.real(a["path"])
        if not os.path.exists(rp):
            raise GateError("MCP_ERROR", "Internal error for delete_path: RuntimeError")
        backup = os.path.join(self.base, ".journal-" + uuid.uuid4().hex)
        os.rename(rp, backup)
        return {"operation_id": self._journal(sid, "delete", path=rp, backup=backup)}

    def t_rollback_file(self, a: dict[str, Any]) -> dict[str, Any]:
        sid = self._auth(a)
        op = self.ops.get(a["operation_id"])
        if op is None or op["sid"] != sid:
            raise GateError("MCP_DENIED", "operation not owned by this work_session")
        if op.get("done"):
            raise GateError("MCP_ERROR", "already rolled back")
        kind = op["kind"]
        if kind == "write":
            if op["prev"] is None:
                os.unlink(op["path"])
            else:
                with open(op["path"], "w", encoding="utf-8") as fh:
                    fh.write(op["prev"])
        elif kind == "mkdir":
            if op["created"]:
                junk = os.path.join(op["path"], "__pycache__")
                if os.path.isdir(junk):
                    shutil.rmtree(junk)
                if os.listdir(op["path"]):
                    raise GateError("MCP_ERROR", "rollback refused: directory changed")
                os.rmdir(op["path"])
        elif kind == "copy":
            shutil.rmtree(op["dst"]) if os.path.isdir(op["dst"]) else os.unlink(op["dst"])
        elif kind == "move":
            os.rename(op["dst"], op["src"])
        elif kind == "delete":
            os.rename(op["backup"], op["path"])
        op["done"] = True
        return {"operation_id": a["operation_id"], "rolled_back": True}

    def t_enable_full_shell(self, a: dict[str, Any]) -> dict[str, Any]:
        sid = self._auth(a)
        if a.get("network") != "none":
            raise GateError("MCP_DENIED", "network not allowed")
        # Live agent: a lock covering the WHOLE workspace must be held by this session.
        if not self._covered(sid, VIRTUAL_WORKSPACE):
            msg = "[-32603] Internal error for enable_full_shell: RuntimeError. Do not loop-retry"
            raise GateError(_classify_mcp_error(msg), msg)
        if self.shell_enabled - {sid}:
            raise GateError("MCP_ERROR", "Internal error for enable_full_shell: PermissionError.")
        self.shell_enabled.add(sid)
        return {"enabled": True}

    def t_disable_full_shell(self, a: dict[str, Any]) -> dict[str, Any]:
        sid = self._auth(a)
        self.shell_enabled.discard(sid)
        return {"disabled": True}

    def t_shell_session(self, a: dict[str, Any]) -> dict[str, Any]:
        self._auth(a)
        if a.get("action") == "read":
            job = self.shell_jobs[a["session_id"]]
            chunk, job["rest"] = job["rest"][:400], job["rest"][400:]
            return {"session_id": a["session_id"], "running": False, "exit_code": job["rc"], "output": chunk,
                    "has_more": bool(job["rest"])}
        return {"ok": True}

    def t_shell_exec(self, a: dict[str, Any], timeout: float) -> dict[str, Any]:
        with self._lock:
            sid = self._auth(a)
            if sid not in self.shell_enabled:
                raise GateError("MCP_DENIED", "shell lease not active")
            self._need_lock(sid, a["cwd"])
            self.commands.append(a["command"])
            cwd = self.real(a["cwd"])
        argv = a["command"].split()
        if argv[0] == "python3":
            argv[0] = sys.executable
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1",
               "HOME": cwd, "LANG": "C.UTF-8"}
        try:
            proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                                  timeout=float(a.get("timeout", 60)))
        except subprocess.TimeoutExpired:
            return {"exit_code": None, "stdout": "", "stderr": "timeout", "timed_out": True}
        # Live agent: PTY (combined output, CRLF), answers after <=3 s and the rest is read
        # through shell_session(action=read) in chunks (has_more).
        combined = (proc.stdout + proc.stderr).replace("\n", "\r\n")
        jid = uuid.uuid4().hex
        self.shell_jobs[jid] = {"rc": proc.returncode, "rest": combined[200:]}
        return {"session_id": jid, "running": True, "exit_code": None, "output": combined[:200],
                "has_more": False}


class InProcessGate(WriteGateClient):
    """WriteGateClient that talks to a GateCore in-process (same JSON contract, no socket)."""

    def __init__(self, core: GateCore):
        super().__init__(socket_path="/nonexistent")
        self.core = core
        self.projects_root = core.root
        self.offline = False

    def _request(self, payload: dict[str, Any], timeout: Optional[float] = None) -> dict[str, Any]:
        if self.offline:
            raise ClientGateError("GATE_OFFLINE")
        import json
        payload = json.loads(json.dumps(payload))  # same serialization constraints as the socket
        out = self.core.handle(payload)
        if not out.get("ok"):
            raise ClientGateError(str(out.get("error")), str(out.get("detail", "")))
        return out


def make_gate(tmpdir: str) -> tuple[FakeMCP, GateCore, InProcessGate]:
    mcp = FakeMCP(tmpdir)
    core = GateCore(mcp.call, projects_root=VIRTUAL_ROOT, shell_lock_path=VIRTUAL_WORKSPACE,
                    sleep=lambda s: None)
    return mcp, core, InProcessGate(core)


# --------------------------------------------------------------------------
# Scripted providers
# --------------------------------------------------------------------------

try:
    from team_core import ProviderResult
except Exception:  # pragma: no cover
    from project_builder import ProviderResult  # type: ignore


GOOD_APP = '''import sqlite3


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")

    def add(self, name):
        cur = self.db.execute("INSERT INTO items(name) VALUES (?)", (name,))
        return cur.lastrowid

    def names(self):
        return [r[0] for r in self.db.execute("SELECT name FROM items ORDER BY id")]
'''

BUGGY_APP = GOOD_APP.replace("ORDER BY id", "ORDER BY id DESC")

GOOD_TEST = '''import unittest

from app import Store


class StoreTest(unittest.TestCase):
    def test_add_and_list(self):
        s = Store()
        s.add("a")
        s.add("b")
        self.assertEqual(s.names(), ["a", "b"])

    def test_ids(self):
        s = Store()
        self.assertEqual(s.add("x"), 1)


if __name__ == "__main__":
    unittest.main()
'''

README = "# App\n\nUso: `python3 -m unittest`\n"


def block(path: str, content: str) -> str:
    return f"=== FILE: {path} ===\n{content}=== END FILE ===\n"


class ScriptedProvider:
    """Answers by prompt type. Every behaviour is configurable per test."""

    def __init__(self, name: str, status: str = "ONLINE"):
        self.name = name
        self.status = status
        self.files = {"app.py": GOOD_APP, "test_app.py": GOOD_TEST, "README.md": README}
        self.fix_files: dict[str, str] = {"app.py": GOOD_APP}
        self.plan = ["app.py | logica", "test_app.py | test", "README.md | doc"]
        self.verdict = "VERDICT: APPROVE\nNessun problema bloccante."
        self.project_name = "mini_app"
        self.fail_on: set[str] = set()  # analysis|plan|file|fix|review
        self.delay = 0.0
        self.extra_output = ""
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        self.on_call = None  # optional hook(kind)

    def health(self, force: bool = False) -> str:
        return self.status

    @staticmethod
    def kind(prompt: str) -> str:
        if "FASE DI ANALISI" in prompt:
            return "analysis"
        if "=== PLAN ===" in prompt and "Ora restituisci SOLO il piano" in prompt:
            return "plan"
        if "Scrivi ORA il contenuto COMPLETO del solo file" in prompt:
            return "file"
        if "FASE DI CORREZIONE" in prompt:
            return "fix"
        if "VERDICT" in prompt:
            return "review"
        return "chat"

    def run(self, prompt: str, cancel_event: threading.Event, timeout: int = 240) -> ProviderResult:
        kind = self.kind(prompt)
        with self._lock:
            self.calls.append(kind)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.on_call:
                self.on_call(kind)
            end = time.monotonic() + self.delay
            while time.monotonic() < end:
                if cancel_event.is_set():
                    return ProviderResult(False, "", self.name, cancelled=True, error_code="CANCELLED")
                time.sleep(0.01)
            if cancel_event.is_set():
                return ProviderResult(False, "", self.name, cancelled=True, error_code="CANCELLED")
            if self.status != "ONLINE":
                return ProviderResult(False, "", self.name, error_code=self.status)
            if kind in self.fail_on:
                return ProviderResult(False, "", self.name, error_code="OFFLINE")
            if kind == "analysis":
                return ProviderResult(True, f"PROJECT_NAME: {self.project_name}\nArchitettura semplice.",
                                      self.name)
            if kind == "plan":
                return ProviderResult(True, "=== PLAN ===\n" + "\n".join(self.plan) + "\n=== END PLAN ===",
                                      self.name)
            if kind == "file":
                target = prompt.split("Scrivi ORA il contenuto COMPLETO del solo file: ", 1)[1].split("\n", 1)[0]
                content = self.files.get(target, f"# {target}\n")
                return ProviderResult(True, block(target, content) + self.extra_output
                                      + "=== SUMMARY ===\nscritto " + target + "\n=== END SUMMARY ===", self.name)
            if kind == "fix":
                out = "".join(block(p, c) for p, c in self.fix_files.items())
                return ProviderResult(True, out + "=== SUMMARY ===\ncorretto\n=== END SUMMARY ===", self.name)
            if kind == "review":
                return ProviderResult(True, self.verdict, self.name)
            return ProviderResult(True, f"{self.name}: risposta", self.name)
        finally:
            with self._lock:
                self.active -= 1


def scripted_team() -> dict[str, ScriptedProvider]:
    return {n: ScriptedProvider(n) for n in ("codex", "claude", "grok")}


class FakeTelegram:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self._lock = threading.Lock()

    def send_message(self, chat_id: int, text: str) -> None:
        with self._lock:
            self.sent.append((chat_id, text))

    def texts(self) -> list[str]:
        with self._lock:
            return [t for _, t in self.sent]


class FakeMCPStatus:
    class Status:
        status = "ONLINE"
        detail = "test"
        write_gate = False

    def status(self):
        return self.Status()


def tmpdir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="aiteam-v3-")
