from __future__ import annotations

"""
Orchestrator-side client of the ANDREA AI TEAM write gate.

The orchestrator never holds MCP credentials. It can only ask the gate for a
small set of operations on (job uid, project, relative path); the gate turns
them into MCP Andrea calls under a dedicated work_session and work_lock.
"""

import json
import os
import socket
from typing import Any, Optional


class GateError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}{': ' + detail if detail else ''}")
        self.code = code
        self.detail = detail


class WriteGateClient:
    def __init__(self, socket_path: Optional[str] = None, timeout: float = 120.0):
        self.socket_path = socket_path or os.environ.get("GATE_SOCKET", "/run/andrea-ai-team-gate/gate.sock")
        self.timeout = timeout
        self.projects_root = os.environ.get(
            "TEAM_PROJECTS_ROOT", "/var/lib/central-mcp-vps-agent-test/workspace/team-projects"
        ).rstrip("/")

    def _request(self, payload: dict[str, Any], timeout: Optional[float] = None) -> dict[str, Any]:
        raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout or self.timeout)
            sock.connect(self.socket_path)
            sock.sendall(raw)
            chunks: list[bytes] = []
            size = 0
            while True:
                part = sock.recv(65536)
                if not part:
                    break
                chunks.append(part)
                size += len(part)
                if size > 3 * 1024 * 1024:
                    raise GateError("GATE_RESPONSE_TOO_LARGE")
                if b"\n" in part:
                    break
        except GateError:
            raise
        except (FileNotFoundError, ConnectionRefusedError):
            raise GateError("GATE_OFFLINE") from None
        except (TimeoutError, socket.timeout):
            raise GateError("GATE_TIMEOUT") from None
        except OSError as exc:
            raise GateError("GATE_OFFLINE", type(exc).__name__) from None
        finally:
            sock.close()
        try:
            obj = json.loads(b"".join(chunks).split(b"\n", 1)[0].decode("utf-8"))
        except Exception:
            raise GateError("GATE_PROTOCOL") from None
        if not isinstance(obj, dict):
            raise GateError("GATE_PROTOCOL")
        if not obj.get("ok"):
            raise GateError(str(obj.get("error", "GATE_ERROR")), str(obj.get("detail", "")))
        return obj

    def op(self, op: str, job: str = "", project: str = "", timeout: Optional[float] = None,
           **kw: Any) -> dict[str, Any]:
        return self._request({"op": op, "job": job, "project": project, **kw}, timeout=timeout)

    # Convenience wrappers ---------------------------------------------------
    def status(self) -> dict[str, Any]:
        return self.op("status", timeout=10)

    def begin(self, job: str, project: str) -> dict[str, Any]:
        return self.op("begin", job, project)

    def heartbeat(self, job: str, project: str) -> dict[str, Any]:
        return self.op("heartbeat", job, project, timeout=60)

    def end(self, job: str, project: str) -> dict[str, Any]:
        return self.op("end", job, project)

    def has_session(self, job: str) -> bool:
        return bool(self.op("has_session", job).get("active"))

    def exists(self, job: str, project: str, path: str = "") -> dict[str, Any]:
        return self.op("exists", job, project, path=path)

    def list(self, job: str, project: str, path: str = "", depth: int = 4) -> dict[str, Any]:
        return self.op("list", job, project, path=path, depth=depth)

    def read(self, job: str, project: str, path: str) -> str:
        return str(self.op("read", job, project, path=path).get("content", ""))

    def mkdir(self, job: str, project: str, path: str = "") -> dict[str, Any]:
        return self.op("mkdir", job, project, path=path)

    def write(self, job: str, project: str, path: str, content: str) -> dict[str, Any]:
        return self.op("write", job, project, path=path, content=content)

    def delete(self, job: str, project: str, path: str) -> dict[str, Any]:
        return self.op("delete", job, project, path=path)

    def move(self, job: str, project: str, path: str, dest: str) -> dict[str, Any]:
        return self.op("move", job, project, path=path, dest=dest)

    def copy(self, job: str, project: str, path: str, dest: str) -> dict[str, Any]:
        return self.op("copy", job, project, path=path, dest=dest)

    def rollback(self, job: str, project: str, operation_id: str) -> dict[str, Any]:
        return self.op("rollback", job, project, operation_id=operation_id)

    def snapshot(self, job: str, project: str) -> dict[str, Any]:
        return self.op("snapshot", job, project, timeout=300)

    def restore_snapshot(self, job: str, project: str, snapshot: str) -> dict[str, Any]:
        return self.op("restore_snapshot", job, project, snapshot=snapshot, timeout=300)

    def trash_project(self, job: str, project: str) -> dict[str, Any]:
        return self.op("trash_project", job, project, timeout=120)

    def run_tests(self, job: str, project: str, kind: str = "unittest", timeout: int = 180) -> dict[str, Any]:
        return self._request(
            {"op": "run_tests", "job": job, "project": project, "kind": kind, "timeout": timeout},
            timeout=float(timeout + 90),
        )
