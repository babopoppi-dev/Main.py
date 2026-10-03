#!/usr/bin/env python3
import asyncio
import json
import os
import platform
import pty
import re
import shutil
import signal
import socket
import subprocess
import time
import uuid
from pathlib import Path

import aiohttp
from file_tools import FileTools
from file_schema import FILE_NAMES

BASE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("CENTRAL_MCP_AGENT_CONFIG",
                                  str(BASE / "config/agent_vps.json")))
CFG = json.loads(CONFIG_PATH.read_text())

DATA_ROOT = Path(CFG["data_root"])
OPS_ROOT = DATA_ROOT / "operations"
STATE_ROOT = DATA_ROOT / "state"
OPS_ROOT.mkdir(parents=True, exist_ok=True)
STATE_ROOT.mkdir(parents=True, exist_ok=True)
os.chmod(DATA_ROOT, 0o700)

sessions = {}
full_shell_until = 0.0


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def token():
    return Path(CFG["token_file"]).read_text().strip()


def full_shell_enabled():
    return bool(CFG.get("full_shell_capable", False) and
                full_shell_until > time.time())


def save_shell_state():
    path = STATE_ROOT / "full_shell.json"
    payload = {
        "enabled": full_shell_enabled(),
        "until_epoch": full_shell_until if full_shell_enabled() else 0,
        "updated": now_iso(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    os.chmod(path, 0o600)


def normalize_target(raw):
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise ValueError("path must be absolute")
    return p.resolve(strict=False)


def under(path, root):
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        return False


ALLOWED_ROOTS = [Path(p).resolve() for p in CFG["allowed_roots"]]
PROTECTED_PATHS = [Path(p).resolve(strict=False) for p in CFG["protected_paths"]]


def validate_file_path(raw, write=False):
    path = normalize_target(raw)
    if not any(under(path, root) for root in ALLOWED_ROOTS):
        raise PermissionError("path is outside allowed roots")
    if write and any(under(path, protected) for protected in PROTECTED_PATHS):
        raise PermissionError("writes to protected paths are blocked")
    return path


def command_forbidden(command):
    lowered = command.lower()
    patterns = [
        r"(^|[;&|()\s])sudo(\s|$)",
        r"(^|[;&|()\s])su(\s|$)",
        r"\bdiskutil\s+erase\b",
        r"\brm\s+[^\n;]*-[^\s]*r[^\s]*f[^\s]*\s+(/|~)(\s|$)",
        r"\brm\s+[^\n;]*-[^\s]*f[^\s]*r[^\s]*\s+(/|~)(\s|$)",
    ]
    if any(re.search(p, lowered, flags=re.I) for p in patterns):
        return "command matches the destructive-command denylist"
    for raw in CFG.get("shell_forbidden_substrings", []):
        if raw.lower() in lowered:
            return "command references a protected path or component"
    return None


def validate_cwd(raw):
    if not raw:
        return None
    cwd = normalize_target(raw)
    for protected in PROTECTED_PATHS:
        if under(cwd, protected):
            raise PermissionError("cwd is protected")
    return str(cwd)


async def run_command(command, cwd=None, timeout=120):
    baseline = command.strip() in CFG.get("baseline_shell_commands", [])
    if not baseline:
        if not full_shell_enabled():
            raise PermissionError("full shell is disabled")
        reason = command_forbidden(command)
        if reason:
            raise PermissionError(reason)

    timeout = max(1, min(float(timeout), 1200))
    proc = await asyncio.create_subprocess_exec(
        "/bin/bash", "-c", command,
        cwd=validate_cwd(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    timed_out = False
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
        output = b""

    cap = 200 * 1024
    truncated = len(output) > cap
    output = output[-cap:]
    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "output": output.decode("utf-8", errors="replace"),
        "truncated": truncated,
    }


def read_file(args):
    path = validate_file_path(args["path"], write=False)
    max_bytes = max(1, min(int(args.get("max_bytes", 262144)), 1048576))
    data = path.read_bytes()
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    return {
        "path": str(path),
        "content": data.decode("utf-8", errors="replace"),
        "truncated": truncated,
        "bytes_returned": len(data),
    }


def write_file(args):
    path = validate_file_path(args["path"], write=True)
    content = args["content"].encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)

    op_id = uuid.uuid4().hex
    op_dir = OPS_ROOT / op_id
    op_dir.mkdir(parents=True, mode=0o700)
    existed = path.exists()
    if existed and not path.is_file():
        raise ValueError("target exists and is not a regular file")

    mode = None
    if existed:
        mode = path.stat().st_mode & 0o777
        shutil.copy2(path, op_dir / "backup")

    meta = {
        "operation_id": op_id,
        "target": str(path),
        "existed": existed,
        "mode": mode,
        "created": now_iso(),
        "rolled_back": False,
    }
    (op_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    tmp = path.parent / f".central_mcp_tmp_{op_id}"
    tmp.write_bytes(content)
    os.chmod(tmp, mode if mode is not None else 0o600)
    os.replace(tmp, path)

    return {
        "operation_id": op_id,
        "path": str(path),
        "bytes_written": len(content),
        "backup_persisted": True,
    }


def rollback_file(args):
    op_id = args["operation_id"]
    if not re.fullmatch(r"[0-9a-f]{32}", op_id):
        raise ValueError("invalid operation_id")
    op_dir = OPS_ROOT / op_id
    meta_path = op_dir / "meta.json"
    meta = json.loads(meta_path.read_text())
    path = validate_file_path(meta["target"], write=True)

    if meta["existed"]:
        backup = op_dir / "backup"
        if not backup.is_file():
            raise RuntimeError("backup is missing")
        tmp = path.parent / f".central_mcp_rollback_{op_id}"
        shutil.copy2(backup, tmp)
        os.replace(tmp, path)
        if meta.get("mode") is not None:
            os.chmod(path, int(meta["mode"]))
    else:
        if path.exists():
            if not path.is_file():
                raise RuntimeError("rollback target changed type")
            path.unlink()

    meta["rolled_back"] = True
    meta["rolled_back_at"] = now_iso()
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    return {"operation_id": op_id, "path": str(path), "rolled_back": True}


def enable_full_shell(args):
    global full_shell_until
    if not CFG.get("full_shell_capable", False):
        raise PermissionError(
            "full shell is fail-closed until the dedicated non-admin OS identity is installed")
    minutes = max(1, min(int(args["minutes"]), 240))
    full_shell_until = time.time() + minutes * 60
    save_shell_state()
    return {"enabled": True, "expires_at_epoch": full_shell_until, "minutes": minutes}


def disable_full_shell(_args):
    global full_shell_until
    full_shell_until = 0
    save_shell_state()
    return {"enabled": False}


def session_start(args):
    command = args.get("command", "")
    if not full_shell_enabled():
        raise PermissionError("full shell is disabled")
    reason = command_forbidden(command)
    if reason:
        raise PermissionError(reason)

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        ["/bin/bash", "-c", command],
        stdin=slave, stdout=slave, stderr=slave,
        start_new_session=True, close_fds=True,
    )
    os.close(slave)
    os.set_blocking(master, False)
    sid = uuid.uuid4().hex
    sessions[sid] = {"proc": proc, "fd": master, "created": time.time()}
    return {"session_id": sid, "pid": proc.pid}


def session_send(args):
    sid = args["session_id"]
    entry = sessions[sid]
    data = args.get("data", "").encode()
    os.write(entry["fd"], data)
    return {"session_id": sid, "bytes_sent": len(data)}


def session_read(args):
    sid = args["session_id"]
    entry = sessions[sid]
    chunks = []
    total = 0
    while total < 65536:
        try:
            part = os.read(entry["fd"], min(4096, 65536 - total))
        except BlockingIOError:
            break
        except OSError:
            break
        if not part:
            break
        chunks.append(part)
        total += len(part)
    proc = entry["proc"]
    return {
        "session_id": sid,
        "running": proc.poll() is None,
        "exit_code": proc.poll(),
        "output": b"".join(chunks).decode("utf-8", errors="replace"),
    }


def session_stop(args):
    sid = args["session_id"]
    entry = sessions.pop(sid)
    proc = entry["proc"]
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=3)
    try:
        os.close(entry["fd"])
    except OSError:
        pass
    return {"session_id": sid, "stopped": True, "exit_code": proc.returncode}


def shell_session(args):
    action = args["action"]
    if action == "start":
        return session_start(args)
    if action == "send":
        return session_send(args)
    if action == "read":
        return session_read(args)
    if action == "stop":
        return session_stop(args)
    raise ValueError("unknown session action")


FILE_ENGINE = FileTools(CFG['allowed_roots'], str(DATA_ROOT / 'file-operations-v07'),
                        denied_roots=CFG['protected_paths'])


def file_dispatch(op, args, caller, request_id):
    if not isinstance(caller, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}', caller):
        raise ValueError('authenticated gateway caller required')
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id):
        raise ValueError('invalid request id')
    identity = caller[:60] + ':' + request_id
    if op == 'read_file' and not ({'offset', 'length'} & set(args)):
        if set(args) - {'path', 'max_bytes'}:
            raise ValueError('unexpected read arguments')
        limit = args.get('max_bytes', 262144)
        if type(limit) is not int or not 1 <= limit <= 1048576:
            raise ValueError('invalid read size')
        data, _ = FILE_ENGINE._read(args['path'])
        FILE_ENGINE._text(data)
        return {'path': args['path'], 'content': data[:limit].decode('utf-8', errors='replace'),
                'truncated': len(data) > limit, 'bytes_returned': min(limit, len(data))}
    if op == 'rollback_file':
        rid = args.get('operation_id')
        if not isinstance(rid, str) or not re.fullmatch(r'[a-f0-9]{32}', rid):
            raise ValueError('invalid operation id')
        # Preserve the historical journal. Never route a v0.7 record to the old
        # implementation, including a v0.7 record whose rollback was rejected.
        if not (DATA_ROOT / 'file-operations-v07' / (rid + '.json')).exists() and (OPS_ROOT / rid).is_dir():
            if set(args) != {'operation_id'}:
                raise ValueError('unexpected rollback arguments')
            return rollback_file(args)
    return FILE_ENGINE.dispatch(op, args, identity)


async def dispatch(op, args, caller=None, request_id=None):
    if op in FILE_NAMES:
        return file_dispatch(op, args, caller, request_id)
    if op == 'who_is_working' and not args:
        return {'active_locks': [], 'coordination': 'serialized agent and file journal',
                'limitation': 'no persistent project lease across separate chats'}
    if op == "shell_exec":
        return await run_command(args["command"], args.get("cwd"), args.get("timeout", 120))
    if op == "shell_session":
        return shell_session(args)
    if op == "read_file":
        return read_file(args)
    if op == "write_file":
        return write_file(args)
    if op == "rollback_file":
        return rollback_file(args)
    if op == "enable_full_shell":
        return enable_full_shell(args)
    if op == "disable_full_shell":
        return disable_full_shell(args)
    raise ValueError(f"unsupported operation: {op}")


def hello_meta():
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "full_shell_capable": CFG.get("full_shell_capable", False),
        "file_tools_version": "0.7",
        "capabilities": sorted(FILE_NAMES | {"shell_exec", "who_is_working", "disable_full_shell"}),
        "baseline_shell_commands": CFG.get("baseline_shell_commands", []),
        "allowed_roots": CFG.get("allowed_roots", []),
    }


async def connected_loop(session):
    fingerprint = bytes.fromhex(CFG["tls_sha256"])
    headers = {"Authorization": "Bearer " + token()}
    async with session.ws_connect(
        CFG["gateway_url"],
        headers=headers,
        ssl=aiohttp.Fingerprint(fingerprint),
        heartbeat=20,
        max_msg_size=2 * 1024 * 1024,
    ) as ws:
        await ws.send_json({"type": "hello", "meta": hello_meta()})

        async def heartbeat():
            while not ws.closed:
                await asyncio.sleep(10)
                await ws.send_json({"type": "heartbeat", "ts": now_iso()})

        heart = asyncio.create_task(heartbeat())
        try:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                if data.get("type") != "request":
                    continue
                req_id = data["id"]
                try:
                    result = await dispatch(data["op"], data.get("args", {}), data.get("caller"), req_id)
                    reply = {"type": "result", "id": req_id, "ok": True,
                             "result": result}
                except Exception as exc:
                    reply = {"type": "result", "id": req_id, "ok": False,
                             "error": f"{type(exc).__name__}: {exc}"}
                await ws.send_json(reply)
        finally:
            heart.cancel()


async def main():
    global full_shell_until
    full_shell_until = 0
    save_shell_state()
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        delay = 2
        while True:
            try:
                await connected_loop(session)
                delay = 2
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)


if __name__ == "__main__":
    asyncio.run(main())

