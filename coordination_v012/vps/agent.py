#!/usr/bin/env python3
"""VPS agent v0.12: explicit work sessions and locks, reversible file tools."""
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
from file_schema import FILE_NAMES as CATALOG_FILE_NAMES
# Route the v0.12 file tools whether the shared catalog module is v0.11 or v0.12.
FILE_NAMES = CATALOG_FILE_NAMES | {'delete_path', 'copy_file', 'read_binary', 'upload_file'}
from search_tools import SearchTools, SEARCH_NAMES
from isolated_shell import IsolatedShell
from work_sessions import WorkSessions, MUTATIONS
from work_schema import WORK_NAMES
from upload_tools import Uploads

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

def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def token():
    return Path(CFG["token_file"]).read_text().strip()


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


async def run_baseline(args):
    if args.get('command', '').strip() != 'uname -a':
        raise PermissionError('unknown baseline command')
    proc = await asyncio.create_subprocess_exec(
        '/usr/bin/uname', '-a', stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, cwd='/',
        env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), 5)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise
    return {'exit_code': proc.returncode, 'output': output[:4096].decode('utf-8', errors='replace'),
            'timed_out': False, 'truncated': len(output)>4096}


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


FILE_ENGINE = FileTools(CFG['allowed_roots'], str(DATA_ROOT / 'file-operations-v07'),
                        denied_roots=CFG['protected_paths'])
SHELL = IsolatedShell(FILE_ENGINE, CFG['allowed_roots'][0],
                      capable=CFG.get('full_shell_capable') is True and CFG.get('shell_backend') == 'bwrap-v08')


SEARCH = SearchTools(FILE_ENGINE)
WORK = WorkSessions(str(DATA_ROOT / 'work-sessions'), FILE_ENGINE)
FILE_ENGINE.lock_provider = WORK.lock_provider
UPLOADS = Uploads(FILE_ENGINE, str(DATA_ROOT / 'uploads'))
WORKSPACE = SHELL.workspace
RECENT = []
WATCHDOG = None


def file_dispatch(op, args, identity):
    SEARCH.guard_mutation(op)
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
            target = json.loads((OPS_ROOT / rid / 'meta.json').read_text())['target']
            with WORK.lock_provider(identity, target):
                return rollback_file(args)
    return FILE_ENGINE.dispatch(op, args, identity)


async def reap_expired_work():
    # Requests are serialized; reap BEFORE accepting a new lock so an expired
    # shell cannot race a new owner of the same workspace.
    if SHELL.owner:
        try:
            remaining = WORK.remaining(SHELL.owner, WORKSPACE)
        except PermissionError:
            remaining = 0
        if remaining <= 0:
            await SHELL.disable()
    active = {x['work_session_id'] for x in WORK.snapshot()['work_sessions']}
    for job in list(SEARCH.jobs.values()):
        if job['status'] == 'running' and job['owner'].startswith('work:') and job['owner'][5:] not in active:
            await SEARCH.stop(job['owner'], job['id'])
    for uid, job in list(UPLOADS.jobs.items()):
        if job['owner'][5:] not in active:
            UPLOADS._drop(uid)


async def watch_work():
    try:
        while True:
            await asyncio.sleep(.5)
            await reap_expired_work()
    except asyncio.CancelledError:
        raise
    except Exception:
        # An unverifiable coordination store must not leave a shell running.
        await SHELL.disable()
        await SEARCH.close()


async def work_call(op, args, caller):
    a = dict(args)
    action = a.pop('action', None)
    sid = a.pop('work_session_id', None)
    tok = a.pop('work_session_token', None)
    if op == 'work_session' and action == 'open':
        if sid is not None or tok is not None or set(a) - {'label', 'minutes'}:
            raise ValueError('unexpected session open arguments')
        return WORK.open(caller, a.get('label'), a.get('minutes', 30))
    identity = WORK.authenticate(caller, sid, tok)
    if op == 'work_session' and action == 'renew':
        if set(a) - {'minutes'}:
            raise ValueError('unexpected session renew arguments')
        return WORK.renew(caller, sid, tok, a.get('minutes', 30))
    if op == 'work_session' and action == 'close' and not a:
        if SHELL.owner == identity:
            await SHELL.disable()
        for job in list(SEARCH.jobs.values()):
            if job['owner'] == identity and job['status'] == 'running':
                await SEARCH.stop(identity, job['id'])
        for uid in UPLOADS.owned_by(identity):
            UPLOADS._drop(uid)
        return WORK.end(caller, sid, tok)
    if op == 'work_lock' and action == 'acquire':
        if set(a) - {'path', 'minutes'}:
            raise ValueError('unexpected lock arguments')
        return WORK.acquire(caller, sid, tok, a.get('path'), a.get('minutes', 30))
    if op == 'work_lock' and action in ('renew', 'release'):
        if set(a) - {'lock_id', 'minutes'} or action == 'release' and 'minutes' in a:
            raise ValueError('unexpected lock arguments')
        if action == 'release' and SHELL.owner == identity:
            raise PermissionError('disable the session shell before releasing its work lock')
        return WORK.change_lock(caller, sid, tok, a.get('lock_id'),
                                a.get('minutes', 30) if action == 'renew' else None)
    raise ValueError('unsupported work action')


async def dispatch(op, args, caller=None, request_id=None):
    global WATCHDOG
    IsolatedShell.identity(caller)
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id):
        raise ValueError('invalid request id')
    if not isinstance(args, dict):
        raise ValueError('arguments must be an object')
    if WATCHDOG is None or WATCHDOG.done():
        WATCHDOG = asyncio.create_task(watch_work())
    await reap_expired_work()
    args = dict(args)
    work_id = args.get('work_session_id')
    work_token = args.get('work_session_token')
    identity = caller
    ok = False
    try:
        if op not in WORK_NAMES:
            args.pop('work_session_id', None); args.pop('work_session_token', None)
            baseline = op == 'shell_exec' and args.get('command', '').strip() == 'uname -a'
            required = op in MUTATIONS | SEARCH_NAMES | {'enable_full_shell', 'disable_full_shell', 'shell_session'} \
                or op == 'shell_exec' and not baseline
            if required or work_id is not None or work_token is not None:
                identity = WORK.authenticate(caller, work_id, work_token)
        if op in WORK_NAMES:
            result = await work_call(op, args, caller)
            # Successful session/lock calls are recorded under their session.
            sid = result.get('work_session_id') if op == 'work_session' and isinstance(result, dict) else work_id
            if isinstance(sid, str):
                identity = 'work:' + sid
        elif op in SEARCH_NAMES:
            result = await SEARCH.dispatch(op, args, identity)
        elif op == 'upload_file':
            if args.get('action') == 'commit':
                SEARCH.guard_mutation(op)
            result = UPLOADS.dispatch(identity, args)
        elif op in FILE_NAMES:
            result = file_dispatch(op, args, identity)
        elif op == 'who_is_working' and not args:
            result = SHELL.working()
            result['active_locks'] += SEARCH.active()
            result['search_version'] = '0.10.1'
            result['recent_operations'] = RECENT[-20:]
            result.update(WORK.snapshot())
        elif op == 'shell_exec':
            if set(args) - {'command', 'cwd', 'timeout'}:
                raise ValueError('unexpected shell arguments')
            if baseline:
                result = await run_baseline(args)
            else:
                WORK.remaining(identity, WORKSPACE)
                result = await SHELL.execute(identity, args)
        elif op == 'shell_session':
            if set(args) - {'action', 'command', 'cwd', 'data', 'session_id'}:
                raise ValueError('unexpected session arguments')
            if args.get('action') == 'start':
                WORK.remaining(identity, WORKSPACE)
            result = await SHELL.session(identity, args)
        elif op == 'enable_full_shell':
            if 'minutes' not in args or set(args) - {'minutes', 'network'} or args.get('network', 'none') != 'none':
                raise ValueError('the VPS shell is offline: only minutes (and network none) are accepted')
            minutes = args['minutes']
            if type(minutes) is not int or minutes * 60 > WORK.remaining(identity, WORKSPACE):
                raise PermissionError('work session and workspace lock must outlast the shell lease')
            result = await SHELL.enable(identity, minutes)
        elif op == 'disable_full_shell' and not args:
            if SHELL.owner is not None and SHELL.owner != identity:
                raise PermissionError('shell lease belongs to another work session')
            result = await SHELL.disable()
        else:
            raise ValueError('unsupported operation: ' + str(op))
        ok = True
        return result
    finally:
        RECENT.append({'time': time.time(), 'caller': caller, 'work_session_id': work_id,
                       'request_id': request_id, 'operation': op, 'ok': ok})
        del RECENT[:-100]
        try:
            WORK.audit(identity, op, ok, request_id)
        except Exception:
            pass


def hello_meta():
    capabilities = FILE_NAMES | SEARCH_NAMES | WORK_NAMES | {'shell_exec', 'who_is_working', 'disable_full_shell'}
    if SHELL.capable:
        capabilities |= {'enable_full_shell', 'shell_session'}
    return {'hostname': socket.gethostname(), 'platform': platform.platform(),
            'python': platform.python_version(), 'uid': os.getuid(),
            'agent_version': '0.12-vps-1', 'coordination_version': '0.11.0', 'work_session_required': True,
            'full_shell_capable': SHELL.capable, 'file_tools_version': '0.8', 'search_version': '0.10.1',
            'shell_backend': 'bwrap-v08', 'shell_network': 'disabled',
            'shell_scope': SHELL.workspace, 'capabilities': sorted(capabilities),
            'baseline_shell_commands': ['uname -a'], 'allowed_roots': CFG['allowed_roots']}


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
            await SEARCH.close()
            await SHELL.disable()
            for uid in list(UPLOADS.jobs):
                UPLOADS._drop(uid)
            try:
                await heart
            except asyncio.CancelledError:
                pass


async def main():
    task = asyncio.current_task()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            delay = 2
            while True:
                try:
                    await connected_loop(session)
                    delay = 2
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await SHELL.disable()
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30)
    finally:
        await SEARCH.close()
        await SHELL.disable()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except asyncio.CancelledError:
        pass
