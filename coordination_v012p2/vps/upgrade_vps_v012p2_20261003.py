#!/usr/bin/env python3
"""VPS agent v0.12 p2 (journal fix, session ids in the log). Telegram-approved admin_request only."""
import base64,contextlib,fcntl,hashlib,json,os,ssl,stat,subprocess,sys,tempfile,time,urllib.request,uuid,zlib
from pathlib import Path
BASE=Path('/opt/central-mcp-gateway')
SELF=BASE/'upgrade_vps_v012p2_20261003.py'
BACKUP=BASE/'backups/pre_vps_v012p2_20261003'
RECEIPT=BASE/'vps_v012p2_20261003_receipt.json'
TEST_CODE=BASE/'preflight-vps_v012p2_20261003'
TEST_DATA=Path('/var/lib/central-mcp-vps-agent-test/tmp/preflight-vps_v012p2_20261003')
WORK=Path('/var/lib/central-mcp-vps-agent-test/workspace')
GUARD=Path('/var/lib/central-mcp-vps-agent-test/file-operations-v07/guard')
AGENT='central-mcp-vps-agent-test.service'
GATEWAY='central-mcp-gateway-test.service'
PAYLOAD={}
TESTS={}
OLD_VERSION='0.12-vps-1'
NEW_VERSION='0.12-vps-2'
ORIGINAL={'agent.py': 'e305c73e8d574edf8eb894e883043f14968f30680c9d404f83121cc330793324', 'file_tools.py': 'c4e8af4bf9b6542e02c1c6c442160998125335010a2b1009becb220146a01e76'}
DEPENDENCIES={'search_schema.py': 'c6d111d440eec78bb08e27673fd832479f02446ac2abc25fb5237e12d47ee20d', 'isolated_shell.py': '254dd32f26295b9376b1201cf7449832b8d9927018d0b9e208cc2a950b954f3f', 'cg_mcp.py': 'f8a86b9a8424f9e6a0bc335f2951c8e9233750b62e1181379d9c6be3ebb04171', 'cg_agents.py': '7e891890ccb076aa06404fdcd481668a3e4aa780e104acb7230448f79e5fe6a1', 'file_schema.py': ['06e579c359835daa58876d7e5de21d26ad374992fb76d9104dd1d6dd929409eb', 'a981512019127689a443ca2717968d76e1509f4366075d5b39f6eee28218c1a4'], 'work_schema.py': ['9204940d1c304ca41236785b2248c449a93f8102fcd1e15fae4d76c478db9ee9', '40eaf6a37998e42d9cdd6e3c28853e1f22cfeff1fc9b16bec8d391abc04817df'], 'cg_tools.py': ['515b27df01b2195027d3de283f0a619cd568641a100158b7d310fdb80703a567', '0df2f955e3de20a5fb13565fcb347c52c8c738963f8c418de0873dc0c123fbd1'], 'search_tools.py': 'f5722cdf394ad1b98575e5f00d6af483a37c6c456adb7465e1213cdc002a625f', 'work_sessions.py': '4a7b736ef6d915c2439cd8aa63e09f0d40410325fa5e9387070f807d518b1861', 'upload_tools.py': 'fbea947e87afd04e7bbf54d1075c3c2852db3a415ac65e65e6fffde07834abc7'}
LIVE_TEST_DEPS=['search_schema.py', 'isolated_shell.py']
TEST_NAMES=['agent.py', 'cg_tools.py', 'file_schema.py', 'file_tools.py', 'isolated_shell.py', 'search_schema.py', 'search_tools.py', 'test_files_v012.py', 'test_search.py', 'test_vps_agent.py', 'upload_tools.py', 'work_schema.py', 'work_sessions.py']
SOURCE_SHA={'agent.py': '8cbba71e28ce3bece276ba11f1290bf4d37dc35157b3442d4aa3c5352f8ab91a', 'cg_tools.py': '0df2f955e3de20a5fb13565fcb347c52c8c738963f8c418de0873dc0c123fbd1', 'file_schema.py': 'a981512019127689a443ca2717968d76e1509f4366075d5b39f6eee28218c1a4', 'file_tools.py': '002d2382b7670e6a9a468facbb951c1f9a20431c70fbba2d8c370fffea5c24cc', 'search_tools.py': 'f5722cdf394ad1b98575e5f00d6af483a37c6c456adb7465e1213cdc002a625f', 'test_files_v012.py': 'b23873ec8879851d36d6032a8fe025833934896582d66b0c45dee983ef951068', 'test_search.py': '907e711f24fdf773db95d5c36d73702db4331d3ced1375cc4bfe43ee5b88db5c', 'test_vps_agent.py': '7ee8decbf864d1d3f82118f8531a41d7afdb0fa39cb19123fad92f0df0e16768', 'upload_tools.py': 'fbea947e87afd04e7bbf54d1075c3c2852db3a415ac65e65e6fffde07834abc7', 'work_schema.py': '40eaf6a37998e42d9cdd6e3c28853e1f22cfeff1fc9b16bec8d391abc04817df', 'work_sessions.py': '4a7b736ef6d915c2439cd8aa63e09f0d40410325fa5e9387070f807d518b1861'}
SOURCES={
'agent.py': r'''#!/usr/bin/env python3
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
            'agent_version': '0.12-vps-2', 'coordination_version': '0.11.0', 'work_session_required': True,
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
''',
'cg_tools.py': r'''TOOLS=[{'name': 'list_machines', 'description': 'List registered machines and online status.', 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}, {'name': 'shell_exec', 'description': 'Execute a command. VPS arbitrary commands need a temporary isolated-shell lease; network is disabled and access is limited to its workspace. Long commands return a session_id; poll shell_session read. Baseline status commands work without enabling.', 'inputSchema': {'type': 'object', 'required': ['machine', 'command'], 'properties': {'machine': {'type': 'string'}, 'command': {'type': 'string'}, 'cwd': {'type': 'string'}, 'timeout': {'type': 'number'}}}}, {'name': 'shell_session', 'description': 'Manage an isolated PTY: start/send/read/stop. Session belongs to its OAuth authorization. VPS allows one active workspace session; disable/expiry stops descendants. Read may return has_more.', 'inputSchema': {'type': 'object', 'required': ['machine', 'action'], 'properties': {'machine': {'type': 'string'}, 'action': {'type': 'string'}, 'session_id': {'type': 'string'}, 'command': {'type': 'string'}, 'data': {'type': 'string'}}}}, {'name': 'read_file', 'description': 'Read file through agent.', 'inputSchema': {'type': 'object', 'required': ['machine', 'path'], 'properties': {'machine': {'type': 'string'}, 'path': {'type': 'string'}, 'max_bytes': {'type': 'integer'}}}}, {'name': 'write_file', 'description': 'Write file with rollback operation id.', 'inputSchema': {'type': 'object', 'required': ['machine', 'path', 'content'], 'properties': {'machine': {'type': 'string'}, 'path': {'type': 'string'}, 'content': {'type': 'string'}}}}, {'name': 'rollback_file', 'description': 'Rollback write operation.', 'inputSchema': {'type': 'object', 'required': ['machine', 'operation_id'], 'properties': {'machine': {'type': 'string'}, 'operation_id': {'type': 'string'}}}}, {'name': 'enable_full_shell', 'description': 'Acquire a temporary shell lease for the authenticated authorization. Available only on machines with verified containment; VPS shell is workspace-only and offline. Multiple chats can share the same authorization.', 'inputSchema': {'type': 'object', 'required': ['machine', 'minutes'], 'properties': {'machine': {'type': 'string'}, 'minutes': {'type': 'integer', 'minimum': 1, 'maximum': 240}}}}, {'name': 'disable_full_shell', 'description': 'Disable temporary shell access and terminate its active sessions and descendants.', 'inputSchema': {'type': 'object', 'required': ['machine'], 'properties': {'machine': {'type': 'string'}}}}, {'name': 'who_is_working', 'description': 'Show active cross-session locks and recent operations on a Mac.', 'inputSchema': {'type': 'object', 'required': ['machine'], 'properties': {'machine': {'type': 'string'}}}}, {'name': 'xcode_list', 'description': 'List the Xcode container and simulators on a Mac.', 'inputSchema': {'type': 'object', 'required': ['machine'], 'properties': {'machine': {'type': 'string'}, 'project': {'type': 'string'}, 'workspace': {'type': 'string'}}}}, {'name': 'xcode_build', 'description': 'Build an Xcode project on a Mac (validated parameters; operation=test for the QA suite).', 'inputSchema': {'type': 'object', 'required': ['machine', 'scheme', 'configuration', 'destination'], 'properties': {'machine': {'type': 'string'}, 'project': {'type': 'string'}, 'workspace': {'type': 'string'}, 'scheme': {'type': 'string'}, 'configuration': {'type': 'string'}, 'destination': {'type': 'string'}, 'operation': {'type': 'string'}, 'action': {'type': 'string'}, 'job_id': {'type': 'string'}, 'result_name': {'type': 'string'}}}}, {'name': 'xcode_test', 'description': 'Run the fixed La Marruca QA tests on a Mac (start/status/artifacts).', 'inputSchema': {'type': 'object', 'required': ['machine', 'project', 'scheme', 'configuration', 'destination'], 'properties': {'machine': {'type': 'string'}, 'project': {'type': 'string'}, 'scheme': {'type': 'string'}, 'configuration': {'type': 'string'}, 'destination': {'type': 'string'}, 'action': {'type': 'string'}, 'job_id': {'type': 'string'}, 'result_name': {'type': 'string'}}}}, {'name': 'admin_request', 'description': 'Request execution of an administrator (root) command on the VPS. The exact command is sent to Andrea on Telegram; it runs only after he approves. Returns a request_id: poll admin_result.', 'inputSchema': {'type': 'object', 'required': ['command', 'reason'], 'properties': {'command': {'type': 'string'}, 'reason': {'type': 'string'}}}}, {'name': 'admin_result', 'description': 'Get status/output of an admin_request (waiting, done, rejected, expired, error).', 'inputSchema': {'type': 'object', 'required': ['request_id'], 'properties': {'request_id': {'type': 'string'}}}}]
NAMES={x["name"] for x in TOOLS}

from file_schema import install_schema
TOOLS=install_schema(TOOLS)
NAMES={x['name'] for x in TOOLS}

from search_schema import SEARCH_TOOLS, SEARCH_NAMES
TOOLS = [t for t in TOOLS if t['name'] not in SEARCH_NAMES] + SEARCH_TOOLS
NAMES = {t['name'] for t in TOOLS}

from work_schema import install_schema as install_work_schema
TOOLS = install_work_schema(TOOLS)
NAMES = {t["name"] for t in TOOLS}

# v0.12: optional GitHub-only network for the Mac shell lease.
for _t in TOOLS:
    if _t['name'] == 'enable_full_shell':
        _t['inputSchema']['properties']['network'] = {'type': 'string', 'enum': ['none', 'github', 'packages'], 'default': 'none'}
        _t['description'] += " On mac_mio, network='github' lets the shell reach only GitHub over HTTPS through the agent proxy; 'packages' adds pypi and the npm registry; default 'none'."
    if _t['name'] == 'shell_session':
        _t['description'] += " Actions: start, send, read, stop, list (this session's processes), processes (uid5000 inventory, mac_mio). On mac_mio up to 4 processes run concurrently in one lease."
''',
'file_schema.py': r'''"""MCP file interface. Routing machine is always required; identity is internal."""
def tool(name, description, fields, required):
    return {'name': name, 'description': description, 'inputSchema': {
        'type': 'object', 'additionalProperties': False,
        'required': ['machine'] + required,
        'properties': {'machine': {'type': 'string', 'enum': ['vps', 'mac_noleggio', 'mac_mio']}, **fields}}}


PATH = {'type': 'string', 'description': 'Absolute path within the allowed project roots.'}
FILE_TOOLS = [
    tool('read_file', 'Read UTF-8 text in allowed roots; offset/length select lines, max_bytes selects bytes. Do not combine the two modes. Negative offset reads from the end.',
         {'path': PATH, 'offset': {'type': 'integer', 'default': 0},
          'length': {'type': 'integer', 'minimum': 0, 'maximum': 10000, 'default': 1000},
          'max_bytes': {'type': 'integer', 'minimum': 1, 'maximum': 524288}}, ['path']),
    tool('read_multiple_files', 'Read up to 20 text files; each result has its own success or error.',
         {'paths': {'type': 'array', 'items': PATH, 'minItems': 1, 'maxItems': 20}}, ['paths']),
    tool('write_file', 'Write text with durable rollback. Append bounded chunks to build a larger file.',
         {'path': PATH, 'content': {'type': 'string'},
          'mode': {'type': 'string', 'enum': ['rewrite', 'append'], 'default': 'rewrite'}}, ['path', 'content']),
    tool('edit_block', 'Replace exact text only when occurrence count matches; otherwise leave file unchanged.',
         {'file_path': PATH, 'old_string': {'type': 'string', 'minLength': 1},
          'new_string': {'type': 'string'},
          'expected_replacements': {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'default': 1}},
         ['file_path', 'old_string', 'new_string']),
    tool('list_directory', 'Bounded recursive listing with [FILE] and [DIR] prefixes; links are not followed.',
         {'path': PATH, 'depth': {'type': 'integer', 'minimum': 0, 'maximum': 8, 'default': 2}}, ['path']),
    tool('create_directory', 'Create intermediate directories with persistent rollback.', {'path': PATH}, ['path']),
    tool('move_file', 'Move or rename a regular file without replacing an existing destination; persistent rollback.',
         {'source': PATH, 'destination': PATH}, ['source', 'destination']),
    tool('get_file_info', 'Get size, permissions, timestamps and text line count; unavailable birth time is null.',
         {'path': PATH}, ['path']),
    tool('rollback_file', 'Undo a committed operation if its resulting files have not changed; persistent across restarts.',
         {'operation_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'}}, ['operation_id']),
    tool('delete_path', 'Delete a file or a directory tree (max 500 entries, no links) with persistent rollback; requires a covering work lock.',
         {'path': PATH}, ['path']),
    tool('copy_file', 'Copy a file or directory tree to a new destination (no overwrite, max 500 entries and 64 MiB) with persistent rollback.',
         {'source': PATH, 'destination': PATH}, ['source', 'destination']),
    tool('read_binary', 'Read any regular file as base64 chunks (max 196608 bytes each); returns total size and sha256 of the whole file.',
         {'path': PATH, 'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
          'length': {'type': 'integer', 'minimum': 1, 'maximum': 196608, 'default': 196608}}, ['path']),
    tool('upload_file', 'Upload a binary file in base64 chunks: begin (path, size, sha256, overwrite), chunk (upload_id, offset, data), commit or abort. Data is staged privately and written once, verified, with persistent rollback.',
         {'action': {'type': 'string', 'enum': ['begin', 'chunk', 'commit', 'abort']},
          'path': PATH, 'size': {'type': 'integer', 'minimum': 0, 'maximum': 8388608},
          'sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
          'overwrite': {'type': 'boolean', 'default': False},
          'upload_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'},
          'offset': {'type': 'integer', 'minimum': 0},
          'data': {'type': 'string', 'maxLength': 262144}}, ['action'])
]
FILE_NAMES = {t['name'] for t in FILE_TOOLS}


def install_schema(existing):
    return [t for t in existing if t['name'] not in FILE_NAMES] + FILE_TOOLS
''',
'file_tools.py': r'''"""Bounded POSIX file tools, Python 3.9, durable rollback, no shell execution.

Trusted configuration is supplied by the agent, never by tool arguments. All
descent uses directory descriptors and O_NOFOLLOW. User symlinks are rejected.
Callers must wire cross-client locks through lock_provider for a live deployment.
"""
import base64
import contextlib
import difflib
import fcntl
import hashlib
import json
import os
import re
import stat
import time
import uuid


class FileToolError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details

    def result(self):
        return {"error": {"code": self.code, "message": str(self), **self.details}}


class FileTools:
    def __init__(self, allowed_roots, state_root, denied_roots=(), lock_provider=None,
                 max_file_bytes=8 * 1024 * 1024, max_chunk_bytes=256 * 1024,
                 max_results=1000, deadline_seconds=15):
        if any(not isinstance(r, str) or not os.path.isabs(r) for r in allowed_roots):
            raise ValueError('absolute roots required')
        self.aliases = sorted([(os.path.normpath(r), os.path.realpath(r)) for r in allowed_roots],
                              key=lambda item: len(item[0]), reverse=True)
        self.roots = sorted({r[1] for r in self.aliases}, key=len, reverse=True)
        if not self.roots or any(not os.path.isabs(r) or r == '/' for r in self.roots):
            raise ValueError('explicit narrow absolute roots required')
        self.state = os.path.realpath(state_root)
        self.denied = tuple(os.path.realpath(r) for r in denied_roots) + (self.state,)
        self.lock_provider = lock_provider
        self.max_file = max_file_bytes
        self.max_chunk = max_chunk_bytes
        self.max_results = max_results
        self.deadline = deadline_seconds
        for r in self.roots:
            if not os.path.isdir(r):
                raise ValueError('allowed root must already exist: ' + r)
            if any(self._inside(r, d) for d in self.denied):
                raise ValueError('allowed root overlaps a denied directory')
        os.makedirs(self.state, mode=0o700, exist_ok=True)
        st = os.stat(self.state)
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise ValueError('rollback state must be private and owned by agent')
        self.state_fd = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.root_fds = {r: os.open(r, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) for r in self.roots}

    def close(self):
        for fd in list(self.root_fds.values()) + [self.state_fd]:
            os.close(fd)
        self.root_fds.clear()

    @staticmethod
    def _inside(path, root):
        return path == root or path.startswith(root.rstrip('/') + '/')

    def _path(self, path, allow_root=True):
        if not isinstance(path, str) or not os.path.isabs(path) or '\0' in path or len(path.encode('utf-8')) > 4096:
            raise FileToolError('INVALID_PATH', 'absolute path required')
        if '..' in path.split('/'):
            raise FileToolError('INVALID_PATH', 'parent traversal is rejected')
        path = os.path.normpath(path)
        # Canonicalize only administrator-approved root aliases (e.g. /tmp or
        # /var on macOS); never resolve untrusted descendant symlinks.
        for alias, real in self.aliases:
            if self._inside(path, alias):
                path = real + path[len(alias):]
                break
        if any(self._inside(path, d) for d in self.denied):
            raise FileToolError('ACCESS_DENIED', 'protected path')
        for root in self.roots:
            if self._inside(path, root):
                now = os.stat(root, follow_symlinks=False)
                pinned = os.fstat(self.root_fds[root])
                if (now.st_dev, now.st_ino) != (pinned.st_dev, pinned.st_ino):
                    raise FileToolError('ROOT_CHANGED', 'allowed root changed; restart after review')
                if path == root and not allow_root:
                    raise FileToolError('ACCESS_DENIED', 'cannot mutate an allowed root')
                parts = path[len(root):].strip('/').split('/') if path != root else []
                if len(parts) > 64:
                    raise FileToolError('LIMIT', 'path nesting exceeds 64 components')
                return path, root, parts
        raise FileToolError('ACCESS_DENIED', 'path outside allowed roots')

    @contextlib.contextmanager
    def _parent(self, path):
        path, root, parts = self._path(path, allow_root=False)
        fd = os.dup(self.root_fds[root])
        try:
            for part in parts[:-1]:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
            yield fd, parts[-1]
        except OSError as exc:
            if exc.errno in (20, 40):
                raise FileToolError('SYMLINK_OR_NOT_DIRECTORY', 'symlink or non-directory in path') from None
            raise
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def _directory(self, path):
        path, root, parts = self._path(path)
        fd = os.dup(self.root_fds[root])
        try:
            for part in parts:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
            yield fd
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def _locked(self, paths, session_id):
        if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}', session_id):
            raise FileToolError('INVALID_SESSION', 'trusted session identity required')
        for path in paths:
            self._path(path, allow_root=False)
        # Serializes durable journal changes across agent processes. The optional
        # provider additionally participates in the existing mac_control lock tree.
        fd = os.open('guard', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.state_fd)
        try:
            end = time.monotonic() + 3
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= end:
                        raise FileToolError('LOCK_BUSY', 'file operation already in progress')
                    time.sleep(0.02)
            with contextlib.ExitStack() as stack:
                self._check_journal()
                if self.lock_provider:
                    for p in sorted(set(paths)):
                        stack.enter_context(self.lock_provider(session_id, p))
                yield
        finally:
            os.close(fd)

    def _check_journal(self):
        count, total = 0, 0
        with os.scandir(self.state_fd) as iterator:
            for item in iterator:
                count += 1
                if count > 2048:
                    raise FileToolError('JOURNAL_LIMIT', 'rollback storage requires reviewed archival')
                st = item.stat(follow_symlinks=False)
                if not stat.S_ISREG(st.st_mode):
                    raise FileToolError('JOURNAL_CORRUPT', 'unexpected rollback state entry')
                total += st.st_size
                if total > 128 * 1024 * 1024:
                    raise FileToolError('JOURNAL_LIMIT', 'rollback storage exceeds 128 MiB')
                if re.fullmatch(r'[a-f0-9]{32}\.json', item.name):
                    fd = os.open(item.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.state_fd)
                    with os.fdopen(fd, 'r') as handle:
                        record = json.loads(handle.read(1024 * 1024))
                    if record.get('status') not in ('committed', 'rolled_back'):
                        raise FileToolError('RECOVERY_REQUIRED', 'interrupted operation requires reviewed recovery',
                                            operation_id=record.get('operation_id'))
        return count, total

    @staticmethod
    def _metadata(st):
        return {'mode': stat.S_IMODE(st.st_mode), 'uid': st.st_uid, 'gid': st.st_gid,
                'atime_ns': st.st_atime_ns, 'mtime_ns': st.st_mtime_ns}

    def _read(self, path):
        with self._parent(path) as (parent, name):
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except OSError as exc:
                if exc.errno == 40:
                    raise FileToolError('SYMLINK', 'symlinks are rejected') from None
                raise
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode):
                    raise FileToolError('NOT_REGULAR_FILE', 'regular file required')
                if st.st_size > self.max_file:
                    raise FileToolError('LIMIT', 'file exceeds bounded size', max_bytes=self.max_file)
                chunks, count = [], 0
                while True:
                    chunk = os.read(fd, min(65536, self.max_file + 1 - count))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    count += len(chunk)
                    if count > self.max_file:
                        raise FileToolError('LIMIT', 'file grew beyond size limit')
                return b''.join(chunks), self._metadata(st)
            finally:
                os.close(fd)

    @staticmethod
    def _text(data):
        if b'\0' in data:
            raise FileToolError('BINARY_FILE', 'binary file: text tool cannot decode it')
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            raise FileToolError('BINARY_FILE', 'file is not UTF-8 text') from None

    def read_file(self, path, offset=0, length=1000):
        if type(offset) is not int or type(length) is not int or not 0 <= length <= 10000:
            raise FileToolError('INVALID_ARGUMENT', 'offset/length must be integers; length 0..10000')
        data, _ = self._read(path)
        lines = self._text(data).splitlines(keepends=True)
        start = max(0, len(lines) + offset) if offset < 0 else min(offset, len(lines))
        returned, count = [], 0
        for line in lines[start:start + length]:
            size = len(line.encode('utf-8'))
            if count + size > self.max_chunk:
                if not returned:
                    raise FileToolError('LIMIT', 'single line exceeds response limit')
                break
            returned.append(line)
            count += size
        return {'path': path, 'content': ''.join(returned), 'offset': start,
                'lines_returned': len(returned), 'total_lines': len(lines),
                'next_offset': start + len(returned), 'truncated': start + len(returned) < len(lines)}

    def read_multiple_files(self, paths):
        if not isinstance(paths, list) or not 1 <= len(paths) <= 20:
            raise FileToolError('INVALID_ARGUMENT', 'paths requires 1..20 files')
        results, remaining = [], self.max_chunk
        for path in paths:
            try:
                value = self.read_file(path)
                size = len(value['content'].encode('utf-8'))
                if size > remaining:
                    raise FileToolError('LIMIT', 'batch response budget exhausted')
                remaining -= size
                results.append({'path': path, 'success': True, **value})
            except (FileToolError, OSError) as exc:
                error = exc.result()['error'] if isinstance(exc, FileToolError) else {'code': 'IO_ERROR', 'message': type(exc).__name__}
                results.append({'path': path, 'success': False, 'error': error})
        return {'files': results}

    def _snapshot(self, path):
        try:
            with self._parent(path) as (fd, name):
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(st.st_mode):
                    raise FileToolError('SYMLINK', 'symlinks are rejected')
                if stat.S_ISDIR(st.st_mode):
                    return {'kind': 'directory', 'metadata': self._metadata(st)}
            data, meta = self._read(path)
            return {'kind': 'file', 'data': data, 'metadata': meta}
        except FileNotFoundError:
            return {'kind': 'missing'}

    def _signature(self, path):
        s = self._snapshot(path)
        if s['kind'] == 'file':
            return {'kind': 'file', 'sha256': hashlib.sha256(s['data']).hexdigest(),
                    'mode': s['metadata']['mode'], 'uid': s['metadata']['uid'], 'gid': s['metadata']['gid']}
        if s['kind'] == 'directory':
            with self._directory(path) as fd:
                st = os.fstat(fd)
                return {'kind': 'directory', 'inode': st.st_ino, 'device': st.st_dev,
                        'mode': stat.S_IMODE(st.st_mode)}
        return {'kind': 'missing'}

    def _state_write(self, name, data):
        temp = uuid.uuid4().hex + '.tmp'
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.state_fd)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, name, src_dir_fd=self.state_fd, dst_dir_fd=self.state_fd)
            os.fsync(self.state_fd)
        finally:
            try:
                os.unlink(temp, dir_fd=self.state_fd)
            except FileNotFoundError:
                pass

    def _record(self, record):
        data = json.dumps(record, sort_keys=True).encode()
        if len(data) > 1024 * 1024:
            raise FileToolError('JOURNAL_LIMIT', 'operation record exceeds limit')
        self._state_write(record['operation_id'] + '.json', data)

    def _begin(self, action, paths, session_id):
        rid = uuid.uuid4().hex
        entries = []
        snapshots = [(path, self._snapshot(path)) for path in paths]
        count, total = self._check_journal()
        reserve = sum(len(snap.get('data', b'')) for _, snap in snapshots) + 1024 * 1024
        if total + reserve > 128 * 1024 * 1024 or count + len(paths) + 2 > 2048:
            raise FileToolError('JOURNAL_LIMIT', 'not enough rollback budget; reviewed archival required')
        for i, (path, snap) in enumerate(snapshots):
            if 'data' in snap:
                backup = rid + '.' + str(i) + '.bin'
                self._state_write(backup, snap.pop('data'))
                snap['backup'] = backup
            entries.append({'path': path, **snap})
        r = {'operation_id': rid, 'action': action, 'session_id': session_id,
             'created_at': time.time(), 'status': 'prepared', 'before': entries}
        self._record(r)
        return r

    def _finish(self, r):
        r['after'] = {e['path']: self._signature(e['path']) for e in r['before']}
        r['status'] = 'committed'
        self._record(r)
        return {'operation_id': r['operation_id'], 'rollback_persistent': True}

    @contextlib.contextmanager
    def _journaled(self, r, undo=None):
        # A failure after _begin must close the record; a 'prepared' record left
        # behind blocks every later operation until reviewed recovery.
        try:
            yield
        except BaseException:
            if undo:
                undo()
            self._abort(r)
            raise

    def _require_parent(self, path):
        try:
            with self._parent(path):
                pass
        except FileNotFoundError:
            raise FileToolError('PARENT_MISSING', 'parent directory does not exist; create it first') from None

    def _atomic_file(self, path, data, metadata=None):
        with self._parent(path) as (fd, name):
            temp = '.mcp-write-' + uuid.uuid4().hex
            output = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                with os.fdopen(output, 'wb') as f:
                    f.write(data)
                    f.flush()
                    if metadata:
                        st = os.fstat(f.fileno())
                        if (st.st_uid, st.st_gid) != (metadata['uid'], metadata['gid']):
                            os.fchown(f.fileno(), metadata['uid'], metadata['gid'])
                        os.fchmod(f.fileno(), metadata['mode'])
                        os.utime(f.fileno(), ns=(metadata['atime_ns'], metadata['mtime_ns']))
                    os.fsync(f.fileno())
                os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
            finally:
                try:
                    os.unlink(temp, dir_fd=fd)
                except FileNotFoundError:
                    pass

    def write_file(self, path, content, mode='rewrite', session_id=None):
        if mode not in ('rewrite', 'append') or not isinstance(content, str):
            raise FileToolError('INVALID_ARGUMENT', 'mode rewrite|append and string content required')
        data = content.encode('utf-8')
        if len(data) > self.max_chunk:
            raise FileToolError('LIMIT', 'chunk too large; append smaller chunks')
        with self._locked([path], session_id):
            before = self._snapshot(path)
            if before['kind'] == 'directory':
                raise FileToolError('NOT_REGULAR_FILE', 'cannot write a directory')
            if mode == 'append' and before['kind'] == 'file':
                self._text(before['data'])
                data = before['data'] + data
            if len(data) > self.max_file:
                raise FileToolError('LIMIT', 'result exceeds file size limit')
            self._require_parent(path)
            r = self._begin('write_file', [path], session_id)
            meta = before.get('metadata')
            if meta:
                meta = dict(meta, mtime_ns=time.time_ns())
            # _atomic_file publishes with one rename: on failure the target is unchanged.
            with self._journaled(r):
                self._atomic_file(path, data, meta)
            return {'path': path, 'bytes_written': len(data), **self._finish(r)}

    def edit_block(self, file_path, old_string, new_string, expected_replacements=1, session_id=None):
        if not isinstance(old_string, str) or not old_string or not isinstance(new_string, str):
            raise FileToolError('INVALID_ARGUMENT', 'non-empty old_string and string new_string required')
        if type(expected_replacements) is not int or not 1 <= expected_replacements <= 1000:
            raise FileToolError('INVALID_ARGUMENT', 'expected_replacements must be 1..1000')
        if len((old_string + new_string).encode()) > self.max_chunk:
            raise FileToolError('LIMIT', 'edit text exceeds request limit')
        with self._locked([file_path], session_id):
            data, meta = self._read(file_path)
            text = self._text(data)
            found = text.count(old_string)
            if found != expected_replacements:
                details = {'occurrences_found': found, 'expected_replacements': expected_replacements}
                if found == 0:
                    # Bounded line-level hint; never a quadratic full-file diff.
                    lines = text.splitlines()[:1000]
                    hint = difflib.get_close_matches(old_string[:512], [s[:512] for s in lines], n=1, cutoff=0.1)
                    details['closest_text'] = hint[0] if hint else ''
                raise FileToolError('REPLACEMENT_COUNT', 'occurrence count differs; file unchanged', **details)
            out = text.replace(old_string, new_string).encode('utf-8')
            if len(out) > self.max_file:
                raise FileToolError('LIMIT', 'edited file exceeds size limit')
            r = self._begin('edit_block', [file_path], session_id)
            with self._journaled(r):
                self._atomic_file(file_path, out, dict(meta, mtime_ns=time.time_ns()))
            return {'path': file_path, 'replacements': found, **self._finish(r)}

    def create_directory(self, path, session_id=None):
        with self._locked([path], session_id):
            path, root, parts = self._path(path, allow_root=False)
            fd = os.dup(self.root_fds[root])
            missing, current = [], root
            try:
                for i, part in enumerate(parts):
                    current += '/' + part
                    try:
                        new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    except FileNotFoundError:
                        missing = [root + '/' + '/'.join(parts[:j + 1]) for j in range(i, len(parts))]
                        break
                    os.close(fd)
                    fd = new
            finally:
                os.close(fd)
            # Always provide a persistent operation, including an idempotent call.
            r = self._begin('create_directory', missing, session_id)
            made = []
            with self._journaled(r, lambda: self._undo_created(made)):
                for p in missing:
                    with self._parent(p) as (fd, name):
                        os.mkdir(name, 0o750, dir_fd=fd)
                        made.append(p)
                        os.fsync(fd)
            return {'path': path, 'created': bool(missing), **self._finish(r)}

    def move_file(self, source, destination, session_id=None):
        if os.path.normpath(source) == os.path.normpath(destination):
            raise FileToolError('INVALID_ARGUMENT', 'source and destination must differ')
        with self._locked([source, destination], session_id):
            src = self._snapshot(source)
            if src['kind'] != 'file':
                raise FileToolError('NOT_REGULAR_FILE', 'phase 1 move supports regular files only')
            if self._snapshot(destination)['kind'] != 'missing':
                raise FileToolError('DESTINATION_EXISTS', 'destination exists; no overwrite')
            with self._parent(source) as (sfd, sn), self._parent(destination) as (dfd, dn):
                if os.fstat(sfd).st_dev != os.fstat(dfd).st_dev:
                    raise FileToolError('CROSS_DEVICE', 'cross-device move is not supported')
                r = self._begin('move_file', [source, destination], session_id)
                stage = []

                def undo():
                    # Put the source back if it was already unlinked, then drop the new link.
                    if 'unlinked' in stage:
                        os.link(dn, sn, src_dir_fd=dfd, dst_dir_fd=sfd, follow_symlinks=False)
                    if 'linked' in stage:
                        with contextlib.suppress(FileNotFoundError):
                            os.unlink(dn, dir_fd=dfd)

                with self._journaled(r, undo):
                    # Exclusive hard-link publication prevents overwriting a destination
                    # created by a concurrent external process (rename would overwrite).
                    os.link(sn, dn, src_dir_fd=sfd, dst_dir_fd=dfd, follow_symlinks=False)
                    stage.append('linked')
                    if not stat.S_ISREG(os.stat(dn, dir_fd=dfd, follow_symlinks=False).st_mode):
                        raise FileToolError('SYMLINK', 'source changed during move')
                    os.fsync(dfd)
                    os.unlink(sn, dir_fd=sfd)
                    stage.append('unlinked')
                    os.fsync(sfd)
            return {'source': source, 'destination': destination, **self._finish(r)}

    MAX_TREE = 500
    MAX_COPY_BYTES = 64 * 1024 * 1024
    MAX_BINARY_CHUNK = 196608

    def _make_directory(self, path, mode):
        with self._parent(path) as (fd, name):
            os.mkdir(name, 0o700, dir_fd=fd)
            new = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                os.fchmod(new, mode)
            finally:
                os.close(new)
            os.fsync(fd)

    def _set_mode(self, path, mode):
        with self._parent(path) as (fd, name):
            new = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                if not stat.S_ISREG(os.fstat(new).st_mode):
                    raise FileToolError('NOT_REGULAR_FILE', 'regular file required')
                os.fchmod(new, mode)
                os.fsync(new)
            finally:
                os.close(new)

    def _tree(self, path):
        """Pre-order (path, kind, size) list of a bounded tree without links."""
        end = time.monotonic() + self.deadline
        items = []

        def visit(p):
            with self._parent(p) as (fd, name):
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(st.st_mode):
                raise FileToolError('SYMLINK', 'symlinks are rejected', path=p)
            if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                raise FileToolError('NOT_REGULAR_FILE', 'only regular files and directories are supported', path=p)
            if any(self._inside(p, d) for d in self.denied):
                raise FileToolError('ACCESS_DENIED', 'protected path', path=p)
            items.append((p, 'directory' if stat.S_ISDIR(st.st_mode) else 'file', st.st_size))
            if len(items) > self.MAX_TREE:
                raise FileToolError('LIMIT', 'tree exceeds entry limit; use the shell', max_entries=self.MAX_TREE)
            if time.monotonic() > end:
                raise FileToolError('LIMIT', 'tree scan exceeded time limit')
            if stat.S_ISDIR(st.st_mode):
                with self._directory(p) as dfd:
                    names = sorted(os.listdir(dfd))
                for child in names:
                    visit(p.rstrip('/') + '/' + child)

        visit(self._path(path, allow_root=False)[0])
        return items

    def _undo_created(self, paths):
        # Best-effort reversal of a failed copy/upload before it is committed.
        for p in reversed(paths):
            with contextlib.suppress(FileNotFoundError, FileToolError), self._parent(p) as (fd, name):
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(st.st_mode):
                    os.rmdir(name, dir_fd=fd)
                else:
                    os.unlink(name, dir_fd=fd)
                os.fsync(fd)

    def _abort(self, r):
        r['status'] = 'rolled_back'
        r['aborted'] = True
        r['after'] = {}
        r['rolled_back_at'] = time.time()
        self._record(r)

    def delete_path(self, path, session_id=None):
        with self._locked([path], session_id):
            items = self._tree(path)
            for p, kind, size in items:
                if kind == 'file' and size > self.max_file:
                    raise FileToolError('LIMIT', 'file too large for a reversible delete; use the shell',
                                        path=p, max_bytes=self.max_file)
            # Backups are read into memory by _begin: bound them before reading.
            if sum(size for _, kind, size in items if kind == 'file') > self.MAX_COPY_BYTES:
                raise FileToolError('LIMIT', 'tree too large for a reversible delete; use the shell',
                                    max_total_bytes=self.MAX_COPY_BYTES)
            r = self._begin('delete_path', [p for p, _, _ in items], session_id)
            try:
                for p, kind, _ in reversed(items):
                    with self._parent(p) as (fd, name):
                        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if stat.S_ISDIR(st.st_mode) != (kind == 'directory'):
                            raise FileToolError('CHANGED', 'tree changed during delete', path=p)
                        if kind == 'directory':
                            os.rmdir(name, dir_fd=fd)
                        else:
                            os.unlink(name, dir_fd=fd)
                        os.fsync(fd)
            except BaseException:
                # Put back what was already removed, then close the record.
                for e in r['before']:
                    if e['kind'] == 'directory' and self._snapshot(e['path'])['kind'] == 'missing':
                        self._make_directory(e['path'], e['metadata']['mode'])
                for e in r['before']:
                    if e['kind'] == 'file' and self._snapshot(e['path'])['kind'] == 'missing':
                        fd = os.open(e['backup'], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.state_fd)
                        with os.fdopen(fd, 'rb') as f:
                            self._atomic_file(e['path'], f.read(self.max_file + 1), e['metadata'])
                self._abort(r)
                raise
            files = sum(1 for _, kind, _ in items if kind == 'file')
            return {'path': path, 'deleted_files': files, 'deleted_directories': len(items) - files,
                    **self._finish(r)}

    def copy_file(self, source, destination, session_id=None):
        src = self._path(source)[0]
        dst = self._path(destination, allow_root=False)[0]
        if self._inside(dst, src) or self._inside(src, dst):
            raise FileToolError('INVALID_ARGUMENT', 'source and destination must not contain each other')
        with self._locked([destination], session_id):
            if self._snapshot(destination)['kind'] != 'missing':
                raise FileToolError('DESTINATION_EXISTS', 'destination exists; no overwrite')
            items = self._tree(source)
            total = sum(size for _, kind, size in items if kind == 'file')
            if total > self.MAX_COPY_BYTES or any(k == 'file' and s > self.max_file for _, k, s in items):
                raise FileToolError('LIMIT', 'copy exceeds size limits; use the shell',
                                    max_total_bytes=self.MAX_COPY_BYTES, max_file_bytes=self.max_file)
            targets = [dst + p[len(src):] for p, _, _ in items]
            r = self._begin('copy_file', targets, session_id)
            try:
                for (p, kind, _), target in zip(items, targets):
                    if kind == 'directory':
                        with self._directory(p) as dfd:
                            mode = stat.S_IMODE(os.fstat(dfd).st_mode)
                        self._make_directory(target, mode | 0o700)
                    else:
                        data, meta = self._read(p)
                        self._atomic_file(target, data)
                        self._set_mode(target, (meta['mode'] | 0o600) & 0o777)
            except BaseException:
                self._undo_created(targets)
                self._abort(r)
                raise
            return {'source': source, 'destination': destination, 'entries': len(items),
                    'bytes_copied': total, **self._finish(r)}

    def read_binary(self, path, offset=0, length=MAX_BINARY_CHUNK):
        if type(offset) is not int or type(length) is not int or offset < 0 or not 1 <= length <= self.MAX_BINARY_CHUNK:
            raise FileToolError('INVALID_ARGUMENT', 'offset >= 0 and length 1..%d required' % self.MAX_BINARY_CHUNK)
        data, _ = self._read(path)
        chunk = data[offset:offset + length]
        return {'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                'offset': min(offset, len(data)), 'length': len(chunk),
                'content_base64': base64.b64encode(chunk).decode('ascii'),
                'eof': offset + len(chunk) >= len(data)}

    def write_bytes(self, path, data, overwrite=False, session_id=None):
        """Journaled binary write used by verified uploads."""
        if not isinstance(data, bytes) or len(data) > self.max_file:
            raise FileToolError('LIMIT', 'binary content exceeds file size limit', max_bytes=self.max_file)
        with self._locked([path], session_id):
            before = self._snapshot(path)
            if before['kind'] == 'directory':
                raise FileToolError('NOT_REGULAR_FILE', 'cannot write a directory')
            if before['kind'] == 'file' and not overwrite:
                raise FileToolError('DESTINATION_EXISTS', 'destination exists; pass overwrite=true')
            self._require_parent(path)
            r = self._begin('upload_file', [path], session_id)
            meta = before.get('metadata')
            with self._journaled(r):
                self._atomic_file(path, data, dict(meta, mtime_ns=time.time_ns()) if meta else None)
            return {'path': path, 'bytes_written': len(data),
                    'sha256': hashlib.sha256(data).hexdigest(), **self._finish(r)}

    def rollback_file(self, operation_id, session_id=None):
        if not isinstance(operation_id, str) or not re.fullmatch(r'[a-f0-9]{32}', operation_id):
            raise FileToolError('INVALID_ARGUMENT', 'invalid operation_id')
        fd = os.open(operation_id + '.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.state_fd)
        with os.fdopen(fd, 'r') as f:
            r = json.load(f)
        paths = [e['path'] for e in r['before']]
        with self._locked(paths, session_id):
            if r['status'] != 'committed':
                raise FileToolError('ROLLBACK_STATE', 'operation is not committed or was already rolled back')
            for p, signature in r['after'].items():
                if self._signature(p) != signature:
                    raise FileToolError('ROLLBACK_CONFLICT', 'file changed since operation; rollback refused', path=p)
            # Check every created directory before removing any. Descendants created
            # by this operation are expected; anything else blocks the whole rollback.
            produced = {e['path'] for e in r['before'] if e['kind'] == 'missing'}
            created = {p for p in produced if r['after'][p]['kind'] == 'directory'}
            for p in created:
                with self._directory(p) as fd:
                    if any(p + '/' + name not in produced for name in os.listdir(fd)):
                        raise FileToolError('ROLLBACK_CONFLICT', 'created directory is no longer empty', path=p)
            r['status'] = 'rollback_prepared'
            self._record(r)
            # Directories removed by the operation come back first, parents
            # before children, so their files can be restored inside them.
            for e in r['before']:
                if e['kind'] == 'directory' and r['after'][e['path']]['kind'] == 'missing':
                    self._make_directory(e['path'], e['metadata']['mode'])
            for e in reversed(r['before']):
                p = e['path']
                if e['kind'] == 'missing':
                    with self._parent(p) as (fd, name):
                        try:
                            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                            if stat.S_ISDIR(st.st_mode):
                                os.rmdir(name, dir_fd=fd)
                            else:
                                os.unlink(name, dir_fd=fd)
                            os.fsync(fd)
                        except FileNotFoundError:
                            pass
                elif e['kind'] == 'file':
                    fd = os.open(e['backup'], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.state_fd)
                    with os.fdopen(fd, 'rb') as f:
                        data = f.read(self.max_file + 1)
                    self._atomic_file(p, data, e['metadata'])
            r['status'] = 'rolled_back'
            r['rolled_back_at'] = time.time()
            self._record(r)
            return {'operation_id': operation_id, 'rolled_back': True, 'persistent': True}

    def list_directory(self, path, depth=2):
        if type(depth) is not int or not 0 <= depth <= 8:
            raise FileToolError('INVALID_ARGUMENT', 'depth must be 0..8')
        entries, truncated = [], False
        end = time.monotonic() + self.deadline

        def visit(p, level, prefix=''):
            nonlocal truncated
            if level >= depth:
                return
            with self._directory(p) as fd:
                # Do not allocate an unbounded list for very large directories.
                with os.scandir(fd) as iterator:
                    for item in iterator:
                        if len(entries) >= self.max_results or time.monotonic() > end:
                            truncated = True
                            return
                        name = prefix + item.name
                        if item.is_symlink():
                            entries.append('[SYMLINK BLOCKED] ' + name)
                            continue
                        child = p.rstrip('/') + '/' + item.name
                        if any(self._inside(child, d) for d in self.denied):
                            continue
                        directory = item.is_dir(follow_symlinks=False)
                        entries.append(('[DIR] ' if directory else '[FILE] ') + name)
                        if directory:
                            visit(child, level + 1, name + '/')
                            if truncated:
                                return
        self._path(path)
        visit(path, 0)
        return {'path': path, 'entries': entries, 'truncated': truncated}

    def get_file_info(self, path):
        normalized, root, parts = self._path(path)
        if not parts:
            st = os.fstat(self.root_fds[root])
        else:
            with self._parent(path) as (fd, name):
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISLNK(st.st_mode):
            raise FileToolError('SYMLINK', 'symlinks are rejected')
        value = {'path': path, 'size': st.st_size, 'permissions': oct(stat.S_IMODE(st.st_mode)),
                 'uid': st.st_uid, 'gid': st.st_gid, 'modified': st.st_mtime,
                 'metadata_changed': st.st_ctime, 'created': getattr(st, 'st_birthtime', None),
                 'creation_time_available': hasattr(st, 'st_birthtime'),
                 'is_directory': stat.S_ISDIR(st.st_mode), 'line_count': None}
        if stat.S_ISREG(st.st_mode) and st.st_size <= self.max_file:
            data, _ = self._read(path)
            try:
                value['line_count'] = len(self._text(data).splitlines())
                value['is_text'] = True
            except FileToolError:
                value['is_text'] = False
        return value

    def dispatch(self, name, arguments, session_id):
        a = dict(arguments)
        if 'machine' in a or 'session_id' in a:
            raise FileToolError('INVALID_ARGUMENT', 'routing and identity are supplied by gateway')
        methods = {'read_file', 'read_multiple_files', 'write_file', 'edit_block',
                   'list_directory', 'create_directory', 'move_file', 'get_file_info', 'rollback_file',
                   'delete_path', 'copy_file', 'read_binary'}
        if name not in methods:
            raise FileToolError('UNKNOWN_TOOL', 'unknown file tool')
        if name in {'write_file', 'edit_block', 'create_directory', 'move_file', 'rollback_file',
                    'delete_path', 'copy_file'}:
            a['session_id'] = session_id
        try:
            return getattr(self, name)(**a)
        except TypeError:
            raise FileToolError('INVALID_ARGUMENT', 'missing or unexpected parameters') from None
''',
'search_tools.py': r'''"""Read-only progressive searches inside pinned FileTools roots; Python 3.9+."""
import asyncio
import contextlib
import fcntl
import json
import os
import re
import stat
import time
import uuid

from file_tools import FileToolError

SEARCH_NAMES = {'start_search', 'get_more_search_results', 'stop_search'}
MUTATIONS = {'write_file', 'edit_block', 'create_directory', 'move_file', 'rollback_file',
             'delete_path', 'copy_file', 'upload_file'}


def glob_match(text, pattern):
    """Only * and ? wildcards, without user-supplied regular expressions."""
    i = j = 0
    star = -1
    mark = 0
    while i < len(text):
        if j < len(pattern) and (pattern[j] == '?' or pattern[j] == text[i]):
            i += 1; j += 1
        elif j < len(pattern) and pattern[j] == '*':
            star = j; j += 1; mark = i
        elif star >= 0:
            j = star + 1; mark += 1; i = mark
        else:
            return False
    return all(c == '*' for c in pattern[j:])


class SearchTools:
    MAX_JOBS = 8
    MAX_ACTIVE = 2
    FILE_BYTES = 1024 * 1024
    TOTAL_BYTES = 32 * 1024 * 1024
    RESULT_BYTES = 512 * 1024
    MAX_ENTRIES = 20000
    TTL = 300

    def __init__(self, files):
        self.files = files
        self.jobs = {}

    @staticmethod
    def identity(caller):
        if not isinstance(caller, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}', caller):
            raise PermissionError('authenticated search owner required')

    @staticmethod
    def integer(value, low, high, name):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(name + ' outside permitted range')
        return value

    def purge(self):
        now = time.monotonic()
        for sid, job in list(self.jobs.items()):
            if job['finished'] is not None and now - job['finished'] >= self.TTL:
                del self.jobs[sid]

    def active(self):
        return [{'search_id': j['id'], 'owner': j['owner'], 'path': j['path'], 'mode': 'read',
                 'kind': 'search'} for j in self.jobs.values() if j['status'] == 'running']

    def guard_mutation(self, operation):
        if operation in MUTATIONS and self.active():
            raise PermissionError('search holds a read lock; stop it before modifying files')

    def owned(self, caller, sid):
        self.identity(caller); self.purge()
        if not isinstance(sid, str) or not re.fullmatch(r'[a-f0-9]{32}', sid):
            raise ValueError('invalid search_id')
        job = self.jobs.get(sid)
        if job is None or job['owner'] != caller:
            raise PermissionError('search unavailable for this authorization')
        return job

    def release(self, job):
        if job['guard'] is not None:
            os.close(job['guard']); job['guard'] = None

    async def start(self, caller, args):
        self.identity(caller); self.purge()
        allowed = {'path', 'pattern', 'search_type', 'match_mode', 'file_pattern', 'ignore_case',
                   'include_hidden', 'max_results', 'context_lines', 'depth', 'timeout_seconds'}
        if set(args) - allowed or not {'path', 'pattern'} <= set(args):
            raise ValueError('missing or unexpected search arguments')
        options = dict(search_type='content', match_mode='literal', file_pattern='*',
                       ignore_case=True, include_hidden=False, max_results=1000,
                       context_lines=1, depth=8, timeout_seconds=30)
        options.update(args)
        for key in ('pattern', 'file_pattern'):
            p = options[key]
            if not isinstance(p, str) or not p or len(p.encode('utf-8')) > 256 or any(c in p for c in '\0\r\n'):
                raise ValueError(key + ' requires 1..256 UTF-8 bytes on one line')
        if options['search_type'] not in ('files', 'content') or options['match_mode'] not in ('literal', 'glob'):
            raise ValueError('invalid search_type or match_mode')
        if options['search_type'] == 'content' and options['match_mode'] != 'literal':
            raise ValueError('content searches accept literal text only')
        for key in ('ignore_case', 'include_hidden'):
            if type(options[key]) is not bool:raise ValueError(key + ' must be boolean')
        for key, lo, hi in [('max_results',1,1000), ('context_lines',0,3), ('depth',1,16), ('timeout_seconds',1,60)]:
            self.integer(options[key], lo, hi, key)
        canonical, root, _ = self.files._path(options['path'])
        with self.files._directory(canonical):pass
        if len(self.jobs) >= self.MAX_JOBS or len(self.active()) >= self.MAX_ACTIVE:
            raise PermissionError('search capacity reached; completed searches expire after five minutes')
        guard = os.open('guard', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.files.state_fd)
        try:
            st = os.fstat(guard)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_mode & 0o077:
                raise PermissionError('unsafe file journal guard')
            fcntl.flock(guard, fcntl.LOCK_SH | fcntl.LOCK_NB)
            self.files._check_journal()
        except BaseException:
            os.close(guard); raise
        now = time.monotonic(); sid = uuid.uuid4().hex
        job = dict(id=sid, owner=caller, path=canonical, root=root, options=options, guard=guard,
                   status='running', results=[], result_bytes=0, entries=0, bytes_read=0,
                   skipped={}, limits=[], finished=None, deadline=now+options['timeout_seconds'])
        self.jobs[sid] = job
        job['task'] = asyncio.create_task(self.scan(job))
        job['task'].add_done_callback(lambda task:self.release(job))
        return self.page(job, 0, 100)

    def page(self, job, offset, length):
        self.integer(offset, 0, 1000, 'offset'); self.integer(length, 1, 100, 'length')
        rows = job['results'][offset:offset+length]
        return {'search_id':job['id'], 'status':job['status'], 'path':job['path'], 'results':rows,
                'offset':offset, 'next_offset':offset+len(rows), 'total_results':len(job['results']),
                'has_more':offset+len(rows)<len(job['results']), 'running':job['status']=='running',
                'truncated':bool(job['limits']), 'limits_reached':list(job['limits']),
                'entries_scanned':job['entries'], 'bytes_read':job['bytes_read'],
                'skipped':dict(job['skipped']), 'retention_seconds_after_finish':self.TTL,
                'identity_scope':'OAuth authorization; chats may share an authorization',
                **({'error':job['error']} if 'error' in job else {})}

    def skip(self, job, reason):
        job['skipped'][reason] = job['skipped'].get(reason, 0) + 1

    def limited(self, job, reason):
        if reason not in job['limits']:job['limits'].append(reason)

    def budget(self, job):
        if time.monotonic() >= job['deadline']:self.limited(job, 'timeout')
        return not job['limits']

    def add(self, job, row):
        size = len(json.dumps(row, ensure_ascii=True).encode('utf-8'))
        if job['result_bytes'] + size > self.RESULT_BYTES:
            self.limited(job, 'result_bytes'); return
        job['results'].append(row); job['result_bytes'] += size
        if len(job['results']) >= job['options']['max_results']:self.limited(job, 'max_results')

    def folded(self, job, text):
        return text.casefold() if job['options']['ignore_case'] else text

    async def read_text(self, job, directory_fd, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                self.skip(job, 'not_regular_or_hardlink'); return None
            if st.st_size > self.FILE_BYTES:
                self.skip(job, 'large_file'); return None
            chunks=[]; count=0
            while self.budget(job):
                await asyncio.sleep(0)
                remaining = self.TOTAL_BYTES-job['bytes_read']
                if remaining <= 0:self.limited(job,'total_bytes'); return None
                chunk=os.read(fd,min(65536,self.FILE_BYTES+1-count,remaining))
                if not chunk:break
                count+=len(chunk);job['bytes_read']+=len(chunk);chunks.append(chunk)
                if count>self.FILE_BYTES:
                    self.skip(job,'large_file');return None
            if not self.budget(job):return None
            after=os.fstat(fd)
            if (st.st_size,st.st_mtime_ns,st.st_ctime_ns,st.st_nlink)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns,after.st_nlink):
                self.skip(job,'changed_file');return None
            data=b''.join(chunks)
            try:return self.files._text(data)
            except FileToolError:self.skip(job,'binary_file');return None
        finally:os.close(fd)

    async def visit(self, job, path, level):
        options=job['options']
        with self.files._directory(path) as fd:
            with os.scandir(fd) as entries:
                for item in entries:
                    await asyncio.sleep(0)
                    if not self.budget(job):return
                    job['entries']+=1
                    if job['entries']>self.MAX_ENTRIES:self.limited(job,'entries');return
                    if not options['include_hidden'] and item.name.startswith('.'):
                        self.skip(job,'hidden');continue
                    child=path.rstrip('/')+'/'+item.name
                    try:
                        self.files._path(child)
                        st=os.stat(item.name,dir_fd=fd,follow_symlinks=False)
                        if stat.S_ISLNK(st.st_mode):self.skip(job,'symlink');continue
                        if st.st_dev!=os.fstat(self.files.root_fds[job['root']]).st_dev:
                            self.skip(job,'different_device');continue
                        if stat.S_ISDIR(st.st_mode):
                            if level>=options['depth']:
                                job['depth_skipped']=True
                            else:await self.visit(job,child,level+1)
                            continue
                        if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:
                            self.skip(job,'not_regular_or_hardlink');continue
                        name=self.folded(job,item.name)
                        if not glob_match(name,self.folded(job,options['file_pattern'])):continue
                        pattern=self.folded(job,options['pattern'])
                        if options['search_type']=='files':
                            matches=glob_match(name,pattern) if options['match_mode']=='glob' else pattern in name
                            if matches:self.add(job,{'path':child,'type':'file'})
                        else:
                            text=await self.read_text(job,fd,item.name)
                            if text is None:continue
                            lines=text.splitlines()
                            for index,line in enumerate(lines):
                                if index%64==0:
                                    await asyncio.sleep(0)
                                    if not self.budget(job):return
                                if pattern in self.folded(job,line):
                                    lo=max(0,index-options['context_lines']);hi=min(len(lines),index+options['context_lines']+1)
                                    snippet='\n'.join(lines[lo:hi])
                                    encoded=snippet.encode('utf-8')
                                    self.add(job,{'path':child,'line':index+1,'context_start_line':lo+1,
                                        'text':encoded[:2048].decode('utf-8','ignore'),'text_truncated':len(encoded)>2048})
                                    if not self.budget(job):return
                    except FileToolError:self.skip(job,'protected_or_changed_path')
                    except OSError:self.skip(job,'unreadable_or_changed')

    async def scan(self, job):
        try:
            await self.visit(job,job['path'],1)
            if job.get('depth_skipped'):self.limited(job,'depth')
            job['status']='limited' if job['limits'] else 'completed'
        except asyncio.CancelledError:
            job['status']='cancelled'
        except Exception as exc:
            job['status']='error';job['error']=type(exc).__name__
        finally:
            job['finished']=time.monotonic();self.release(job)

    async def stop(self, caller, sid):
        job=self.owned(caller,sid)
        if job['status']=='running':
            job['status']='cancelled';job['task'].cancel()
            with contextlib.suppress(asyncio.CancelledError):await job['task']
            job['finished']=time.monotonic();self.release(job)
        return self.page(job,0,100)

    async def close(self):
        for job in list(self.jobs.values()):
            if job['status']=='running':await self.stop(job['owner'],job['id'])
        self.jobs.clear()

    async def dispatch(self, op, args, caller):
        if not isinstance(args,dict):raise ValueError('arguments must be an object')
        if op=='start_search':return await self.start(caller,args)
        if op=='get_more_search_results':
            if set(args)-{'search_id','offset','length'}:raise ValueError('unexpected search arguments')
            return self.page(self.owned(caller,args.get('search_id')),args.get('offset',0),args.get('length',100))
        if op=='stop_search' and set(args)=={'search_id'}:return await self.stop(caller,args['search_id'])
        raise ValueError('invalid search operation')
''',
'test_files_v012.py': r'''"""v0.12 reversible file tools: delete_path, copy_file, read_binary, upload_file.

Platform-neutral (runs in the Mac and VPS preflights).
"""
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from file_tools import FileTools, FileToolError
from work_sessions import WorkSessions
from upload_tools import Uploads


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.work = self.root / 'work'; self.work.mkdir(mode=0o700)
        self.f = FileTools([str(self.work)], str(self.root / 'journal'))
        self.w = WorkSessions(str(self.root / 'sessions'), self.f, boot='boot1')
        self.f.lock_provider = self.w.lock_provider
        self.a = self.w.open('test:client', 'chat A', 10)
        self.b = self.w.open('test:client', 'chat B', 10)

    def tearDown(self):
        self.w.close(); self.f.close(); self.tmp.cleanup()

    def auth(self, s): return ('test:client', s['work_session_id'], s['work_session_token'])
    def ident(self, s): return self.w.authenticate(*self.auth(s))
    def lock(self, s, path=None): return self.w.acquire(*self.auth(s), str(path or self.work), 5)

    def tree(self):
        base = self.work / 'proj'
        (base / 'src' / 'deep').mkdir(parents=True)
        (base / 'a.txt').write_text('alpha')
        (base / 'src' / 'b.bin').write_bytes(bytes(range(256)) * 4)
        (base / 'src' / 'deep' / 'c.txt').write_text('gamma')
        os.chmod(base / 'a.txt', 0o640)
        os.chmod(base / 'src', 0o711)
        return base

    def listing(self, base):
        out = {}
        for dirpath, dirs, files in os.walk(base):
            for name in dirs + files:
                p = Path(dirpath) / name
                st = p.lstat()
                out[str(p.relative_to(base))] = (oct(st.st_mode), p.read_bytes() if p.is_file() else None)
        return out


class Delete(Base):
    def test_requires_covering_lock(self):
        (self.work / 'x').write_text('x')
        with self.assertRaises(PermissionError):
            self.f.delete_path(str(self.work / 'x'), session_id=self.ident(self.a))
        self.lock(self.b, self.work / 'x')
        with self.assertRaises(PermissionError):
            self.f.delete_path(str(self.work / 'x'), session_id=self.ident(self.a))
        self.assertTrue((self.work / 'x').exists())

    def test_file_delete_and_rollback_restores_content_and_mode(self):
        p = self.work / 'x'; p.write_bytes(b'\x00\x01data'); os.chmod(p, 0o604)
        self.lock(self.a)
        r = self.f.delete_path(str(p), session_id=self.ident(self.a))
        self.assertEqual((r['deleted_files'], r['deleted_directories']), (1, 0))
        self.assertFalse(p.exists())
        self.f.rollback_file(r['operation_id'], session_id=self.ident(self.a))
        self.assertEqual(p.read_bytes(), b'\x00\x01data')
        self.assertEqual(p.stat().st_mode & 0o777, 0o604)

    def test_tree_delete_and_rollback_restores_everything(self):
        base = self.tree(); before = self.listing(base)
        self.lock(self.a)
        r = self.f.delete_path(str(base), session_id=self.ident(self.a))
        self.assertEqual((r['deleted_files'], r['deleted_directories']), (3, 3))
        self.assertFalse(base.exists())
        self.f.rollback_file(r['operation_id'], session_id=self.ident(self.a))
        self.assertEqual(self.listing(base), before)

    def test_rollback_refused_when_path_recreated(self):
        p = self.work / 'x'; p.write_text('old'); self.lock(self.a)
        r = self.f.delete_path(str(p), session_id=self.ident(self.a))
        p.write_text('new')
        with self.assertRaises(FileToolError) as e:
            self.f.rollback_file(r['operation_id'], session_id=self.ident(self.a))
        self.assertEqual(e.exception.code, 'ROLLBACK_CONFLICT')
        self.assertEqual(p.read_text(), 'new')

    def test_symlink_inside_tree_refuses_whole_delete(self):
        base = self.tree(); (base / 'src' / 'link').symlink_to(self.root)
        self.lock(self.a)
        with self.assertRaises(FileToolError):
            self.f.delete_path(str(base), session_id=self.ident(self.a))
        self.assertTrue((base / 'a.txt').exists())

    def test_root_and_missing_refused(self):
        self.lock(self.a)
        with self.assertRaises(FileToolError):
            self.f.delete_path(str(self.work), session_id=self.ident(self.a))
        with self.assertRaises(FileNotFoundError):
            self.f.delete_path(str(self.work / 'none'), session_id=self.ident(self.a))

    def test_total_size_bounded_before_reading(self):
        d = self.work / 'big'; d.mkdir()
        for i in range(3):
            (d / str(i)).write_bytes(b'x')
        self.lock(self.a)
        with patch.object(FileTools, 'MAX_COPY_BYTES', 2), patch.object(self.f, '_begin') as begin:
            with self.assertRaises(FileToolError):
                self.f.delete_path(str(d), session_id=self.ident(self.a))
            begin.assert_not_called()

    def test_entry_limit(self):
        d = self.work / 'many'; d.mkdir()
        for i in range(FileTools.MAX_TREE + 1):
            (d / str(i)).write_text('x')
        self.lock(self.a)
        with self.assertRaises(FileToolError) as e:
            self.f.delete_path(str(d), session_id=self.ident(self.a))
        self.assertEqual(e.exception.code, 'LIMIT')

    def test_failure_midway_restores_tree_and_journal_stays_usable(self):
        base = self.tree(); before = self.listing(base); self.lock(self.a)
        real = os.rmdir; calls = []
        def flaky(name, dir_fd=None):
            calls.append(name)
            if len(calls) == 2:
                raise OSError('simulated')
            return real(name, dir_fd=dir_fd)
        with patch('file_tools.os.rmdir', side_effect=flaky):
            with self.assertRaises(OSError):
                self.f.delete_path(str(base), session_id=self.ident(self.a))
        self.assertEqual(self.listing(base), before)
        self.f.write_file(str(self.work / 'after'), 'ok', session_id=self.ident(self.a))


class Copy(Base):
    def test_copy_tree_and_rollback(self):
        base = self.tree(); before = self.listing(base); self.lock(self.a, self.work / 'copy')
        r = self.f.copy_file(str(base), str(self.work / 'copy'), session_id=self.ident(self.a))
        self.assertEqual(r['entries'], 6)
        copied = self.listing(self.work / 'copy')
        self.assertEqual({k: v[1] for k, v in copied.items()}, {k: v[1] for k, v in before.items()})
        self.assertEqual(copied['a.txt'][0], before['a.txt'][0])
        self.f.rollback_file(r['operation_id'], session_id=self.ident(self.a))
        self.assertFalse((self.work / 'copy').exists())
        self.assertEqual(self.listing(base), before)

    def test_copy_rollback_refused_if_new_file_added(self):
        base = self.tree(); self.lock(self.a, self.work / 'copy')
        r = self.f.copy_file(str(base), str(self.work / 'copy'), session_id=self.ident(self.a))
        (self.work / 'copy' / 'src' / 'extra').write_text('mine')
        with self.assertRaises(FileToolError):
            self.f.rollback_file(r['operation_id'], session_id=self.ident(self.a))
        self.assertTrue((self.work / 'copy' / 'a.txt').exists())

    def test_no_overwrite_no_self_copy_and_lock_on_destination(self):
        base = self.tree(); (self.work / 'exists').write_text('x')
        with self.assertRaises(PermissionError):
            self.f.copy_file(str(base / 'a.txt'), str(self.work / 'n'), session_id=self.ident(self.a))
        self.lock(self.a)
        with self.assertRaises(FileToolError):
            self.f.copy_file(str(base / 'a.txt'), str(self.work / 'exists'), session_id=self.ident(self.a))
        with self.assertRaises(FileToolError):
            self.f.copy_file(str(base), str(base / 'src' / 'inner'), session_id=self.ident(self.a))
        r = self.f.copy_file(str(base / 'src' / 'b.bin'), str(self.work / 'b2'), session_id=self.ident(self.a))
        self.assertEqual((self.work / 'b2').read_bytes(), (base / 'src' / 'b.bin').read_bytes())
        self.assertEqual(r['bytes_copied'], 1024)

    def test_failed_copy_leaves_nothing(self):
        base = self.tree(); self.lock(self.a)
        real = self.f._atomic_file; calls = []
        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('disk full')
            return real(*a, **k)
        with patch.object(self.f, '_atomic_file', side_effect=flaky):
            with self.assertRaises(OSError):
                self.f.copy_file(str(base), str(self.work / 'copy'), session_id=self.ident(self.a))
        self.assertFalse((self.work / 'copy').exists())
        self.f.write_file(str(self.work / 'after'), 'ok', session_id=self.ident(self.a))


class Binary(Base):
    def test_read_binary_chunks_reassemble(self):
        data = os.urandom(500000); (self.work / 'blob').write_bytes(data)
        parts, offset = [], 0
        while True:
            r = self.f.read_binary(str(self.work / 'blob'), offset)
            parts.append(base64.b64decode(r['content_base64'])); offset += r['length']
            if r['eof']:
                break
        self.assertEqual(b''.join(parts), data)
        self.assertEqual(r['sha256'], hashlib.sha256(data).hexdigest())
        with self.assertRaises(FileToolError):
            self.f.read_binary(str(self.work / 'blob'), 0, 196609)

    def uploads(self):
        return Uploads(self.f, str(self.root / 'uploads'))

    def send(self, u, ident, path, data, overwrite=False, chunk=100000):
        b = u.begin(ident, path, len(data), hashlib.sha256(data).hexdigest(), overwrite)
        for i in range(0, len(data), chunk):
            u.chunk(ident, b['upload_id'], i, base64.b64encode(data[i:i + chunk]).decode())
        return u.commit(ident, b['upload_id'])

    def test_upload_commit_rollback_and_overwrite(self):
        u = self.uploads(); self.lock(self.a); ident = self.ident(self.a)
        p = str(self.work / 'img.png'); data = os.urandom(250000)
        r = self.send(u, ident, p, data)
        self.assertEqual(Path(p).read_bytes(), data)
        with self.assertRaises(FileToolError):
            u.begin(ident, p, 1, '0' * 64)
        r2 = self.send(u, ident, p, b'new', overwrite=True)
        self.assertEqual(Path(p).read_bytes(), b'new')
        self.f.rollback_file(r2['operation_id'], session_id=ident)
        self.assertEqual(Path(p).read_bytes(), data)
        self.f.rollback_file(r['operation_id'], session_id=ident)
        self.assertFalse(Path(p).exists())
        self.assertEqual(os.listdir(self.root / 'uploads'), [])
        u.close()

    def test_upload_rejects_bad_offset_checksum_owner_and_lock(self):
        u = self.uploads(); ia, ib = self.ident(self.a), self.ident(self.b)
        with self.assertRaises(PermissionError):
            u.begin(ia, str(self.work / 'x'), 3, hashlib.sha256(b'abc').hexdigest())
        self.lock(self.a)
        b = u.begin(ia, str(self.work / 'x'), 3, hashlib.sha256(b'abc').hexdigest())
        with self.assertRaises(FileToolError):
            u.chunk(ib, b['upload_id'], 0, base64.b64encode(b'abc').decode())
        with self.assertRaises(FileToolError):
            u.chunk(ia, b['upload_id'], 1, base64.b64encode(b'abc').decode())
        with self.assertRaises(FileToolError):
            u.chunk(ia, b['upload_id'], 0, 'not base64!')
        u.chunk(ia, b['upload_id'], 0, base64.b64encode(b'abd').decode())
        with self.assertRaises(FileToolError) as e:
            u.commit(ia, b['upload_id'])
        self.assertEqual(e.exception.code, 'CHECKSUM_MISMATCH')
        self.assertFalse((self.work / 'x').exists())
        u.close()

    def test_staging_bounded_and_cleared_on_restart(self):
        u = self.uploads(); self.lock(self.a); ia = self.ident(self.a)
        ids = [u.begin(ia, str(self.work / str(i)), 10, '0' * 64)['upload_id'] for i in range(4)]
        with self.assertRaises(FileToolError):
            u.begin(ia, str(self.work / 'five'), 10, '0' * 64)
        u.chunk(ia, ids[0], 0, base64.b64encode(b'12345').decode())
        u.close()
        (self.root / 'uploads' / (uuid.uuid4().hex + '.part')).write_bytes(b'left')
        u = self.uploads()
        self.assertEqual(os.listdir(self.root / 'uploads'), [])
        u.close()

    def test_expired_upload_is_dropped(self):
        now = [0.0]
        u = Uploads(self.f, str(self.root / 'uploads'), clock=lambda: now[0])
        self.lock(self.a); ia = self.ident(self.a)
        b = u.begin(ia, str(self.work / 'x'), 1, '0' * 64)
        now[0] += Uploads.TTL + 1
        with self.assertRaises(FileToolError):
            u.dispatch(ia, {'action': 'chunk', 'upload_id': b['upload_id'], 'offset': 0, 'data': 'YQ=='})
        u.close()


class JournalNeverLeftPrepared(Base):
    """A failed operation must close its record: 'prepared' blocks every later write."""

    def statuses(self):
        import json
        return sorted(json.loads((self.root / 'journal' / n).read_text())['status']
                      for n in os.listdir(self.root / 'journal') if n.endswith('.json'))

    def assert_usable(self, ident):
        self.assertNotIn('prepared', self.statuses())
        r = self.f.write_file(str(self.work / 'after.txt'), 'ok', session_id=ident)
        self.f.rollback_file(r['operation_id'], session_id=ident)

    def test_upload_commit_with_missing_parent(self):
        # Exact 2026-10-03 incident: commit into a directory that does not exist.
        u = Uploads(self.f, str(self.root / 'uploads')); self.lock(self.a); ia = self.ident(self.a)
        p = str(self.work / 'missing' / 'probe.bin'); data = os.urandom(1003)
        b = u.begin(ia, p, len(data), hashlib.sha256(data).hexdigest())
        u.chunk(ia, b['upload_id'], 0, base64.b64encode(data).decode())
        with self.assertRaises(FileToolError) as e:
            u.commit(ia, b['upload_id'])
        self.assertEqual(e.exception.code, 'PARENT_MISSING')
        self.assert_usable(ia)
        # The staged upload survives: create the directory and commit again.
        self.f.create_directory(str(self.work / 'missing'), session_id=ia)
        r = u.commit(ia, b['upload_id'])
        self.assertEqual(Path(p).read_bytes(), data)
        self.f.rollback_file(r['operation_id'], session_id=ia)
        self.assertFalse(Path(p).exists())
        u.close()

    def test_write_file_with_missing_parent(self):
        self.lock(self.a); ia = self.ident(self.a)
        with self.assertRaises(FileToolError) as e:
            self.f.write_file(str(self.work / 'nope' / 'x.txt'), 'x', session_id=ia)
        self.assertEqual(e.exception.code, 'PARENT_MISSING')
        self.assertEqual(self.statuses(), [])
        self.assert_usable(ia)

    def test_failed_publication_aborts_write_edit_and_upload(self):
        self.lock(self.a); ia = self.ident(self.a)
        target = self.work / 't.txt'; target.write_text('original')
        real = os.replace

        def failing(src, dst, **kw):
            if str(src).startswith('.mcp-write-'):
                raise OSError(28, 'No space left on device')
            return real(src, dst, **kw)

        with patch('file_tools.os.replace', failing):
            with self.assertRaises(OSError):
                self.f.write_file(str(target), 'new', session_id=ia)
            with self.assertRaises(OSError):
                self.f.edit_block(str(target), 'original', 'edited', session_id=ia)
            with self.assertRaises(OSError):
                self.f.write_bytes(str(target), b'bin', overwrite=True, session_id=ia)
        self.assertEqual(target.read_text(), 'original')
        self.assertEqual([n for n in os.listdir(self.work) if n.startswith('.mcp-write-')], [])
        self.assertEqual(self.statuses(), ['rolled_back'] * 3)
        self.assert_usable(ia)

    def test_failed_create_directory_removes_partial_tree(self):
        self.lock(self.a); ia = self.ident(self.a)
        real, calls = os.mkdir, []

        def failing(name, mode=0o777, **kw):
            calls.append(name)
            if len(calls) == 2:
                raise OSError(28, 'No space left on device')
            return real(name, mode, **kw)

        with patch('file_tools.os.mkdir', failing):
            with self.assertRaises(OSError):
                self.f.create_directory(str(self.work / 'a' / 'b' / 'c'), session_id=ia)
        self.assertFalse((self.work / 'a').exists())
        self.assertEqual(self.statuses(), ['rolled_back'])
        self.assert_usable(ia)

    def test_failed_move_keeps_source(self):
        self.lock(self.a); ia = self.ident(self.a)
        src = self.work / 's.txt'; src.write_text('keep'); dst = self.work / 'd.txt'
        real = os.fsync
        count = []

        def failing(fd):
            # Fail the fsync that follows unlinking the source (after the journal writes).
            if count == ['arm']:
                count.append('fired')
                raise OSError(5, 'I/O error')
            return real(fd)

        real_unlink = os.unlink

        def unlink(name, **kw):
            if name == 's.txt':
                count.append('arm')
            return real_unlink(name, **kw)

        with patch('file_tools.os.fsync', failing), patch('file_tools.os.unlink', unlink):
            with self.assertRaises(OSError):
                self.f.move_file(str(src), str(dst), session_id=ia)
        self.assertEqual(src.read_text(), 'keep')
        self.assertFalse(dst.exists())
        self.assertEqual(self.statuses(), ['rolled_back'])
        self.assert_usable(ia)

    def test_failed_move_before_unlink_drops_link(self):
        self.lock(self.a); ia = self.ident(self.a)
        src = self.work / 's.txt'; src.write_text('keep'); dst = self.work / 'd.txt'
        real_unlink = os.unlink

        def unlink(name, **kw):
            if name == 's.txt':
                raise OSError(1, 'Operation not permitted')
            return real_unlink(name, **kw)

        with patch('file_tools.os.unlink', unlink):
            with self.assertRaises(OSError):
                self.f.move_file(str(src), str(dst), session_id=ia)
        self.assertEqual(src.read_text(), 'keep')
        self.assertFalse(dst.exists())
        self.assertEqual(self.statuses(), ['rolled_back'])
        self.assert_usable(ia)


if __name__ == '__main__':
    unittest.main()
''',
'test_search.py': r'''import asyncio
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from file_tools import FileTools, FileToolError
from search_tools import SearchTools, glob_match

OWNER='chatgpt:searchtest1'
OTHER='claude:searchtest2'


class Searches(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.root=self.base/'workspace';self.root.mkdir()
        self.secret=self.root/'protected';self.secret.mkdir()
        self.files=FileTools([str(self.root)],str(self.base/'journal'),denied_roots=[str(self.secret)])
        self.search=SearchTools(self.files)

    async def asyncTearDown(self):
        await self.search.close();self.files.close();self.tmp.cleanup()

    async def start(self, **kwargs):
        return await self.search.start(OWNER,{'path':str(self.root),'pattern':'needle',**kwargs})

    async def finish(self, initial):
        j=self.search.jobs[initial['search_id']]
        await asyncio.wait_for(j['task'],3)
        return await self.search.dispatch('get_more_search_results',{'search_id':j['id']},OWNER)

    async def test_text_casefold_and_context(self):
        (self.root/'code.py').write_text('prima\nNEEDLE utf8 '+chr(0xe8)+'\ndopo\n')
        r=await self.finish(await self.start())
        self.assertEqual(r['status'],'completed');self.assertEqual(r['results'][0]['line'],2)
        self.assertEqual(r['results'][0]['text'],'prima\nNEEDLE utf8 '+chr(0xe8)+'\ndopo')

    async def test_filename_glob_and_filter(self):
        for n in ('User.py','user.js','test.txt'):(self.root/n).write_text('')
        r=await self.finish(await self.start(search_type='files',match_mode='glob',pattern='*USER*',file_pattern='*.py'))
        self.assertEqual([Path(x['path']).name for x in r['results']],['User.py'])

    async def test_literal_punctuation(self):
        (self.root/'code.py').write_text('a.*(x)\nnot a match\n')
        r=await self.finish(await self.start(pattern='a.*(x)',context_lines=0))
        self.assertEqual(r['total_results'],1)

    async def test_no_outside_traversal(self):
        for path in (str(self.base),str(self.root/'..'),str(self.secret)):
            with self.assertRaises(FileToolError):await self.start(path=path)
        self.assertFalse(self.search.jobs)

    async def test_links_and_special_files_not_read(self):
        outside=self.base/'outside';outside.write_text('needle SECRET')
        os.symlink(outside,self.root/'link.txt');os.symlink(self.base,self.root/'dirlink')
        os.link(outside,self.root/'hard.txt');os.mkfifo(self.root/'pipe')
        r=await self.finish(await self.start())
        self.assertEqual(r['total_results'],0)
        self.assertEqual(r['skipped']['symlink'],2)
        self.assertEqual(r['skipped']['not_regular_or_hardlink'],2)

    async def test_symlink_requested_directory(self):
        os.symlink(self.base,self.root/'link')
        with self.assertRaises((FileToolError,OSError)):await self.start(path=str(self.root/'link'))

    async def test_hidden_and_protected(self):
        (self.root/'.hidden').write_text('needle');(self.secret/'secret').write_text('needle')
        r=await self.finish(await self.start())
        self.assertEqual(r['total_results'],0)
        r=await self.finish(await self.start(include_hidden=True))
        self.assertEqual(r['total_results'],1)
        self.assertEqual(r['skipped']['protected_or_changed_path'],1)

    async def test_binary_and_large_skip(self):
        (self.root/'null').write_bytes(b'needle\0');(self.root/'bad').write_bytes(b'needle'+bytes([255]))
        (self.root/'big').write_bytes(b'a'*(self.search.FILE_BYTES+1))
        r=await self.finish(await self.start())
        self.assertEqual(r['total_results'],0);self.assertEqual(r['skipped']['binary_file'],2)
        self.assertEqual(r['skipped']['large_file'],1)

    async def test_page_stability(self):
        (self.root/'many').write_text('needle\n'*120)
        r=await self.finish(await self.start(context_lines=0));sid=r['search_id']
        self.assertEqual(len(r['results']),100);self.assertTrue(r['has_more'])
        args={'search_id':sid,'offset':100,'length':100}
        tail=await self.search.dispatch('get_more_search_results',args,OWNER)
        self.assertEqual(len(tail['results']),20);self.assertFalse(tail['has_more'])
        self.assertEqual(tail,await self.search.dispatch('get_more_search_results',args,OWNER))

    async def test_limit_results(self):
        (self.root/'many').write_text('needle\n'*20)
        r=await self.finish(await self.start(max_results=3))
        self.assertEqual(r['total_results'],3);self.assertEqual(r['status'],'limited')
        self.assertIn('max_results',r['limits_reached'])

    async def test_depth_truncation_does_not_stop_siblings(self):
        (self.root/'d').mkdir();(self.root/'d'/'deep').write_text('needle')
        (self.root/'root').write_text('needle')
        r=await self.finish(await self.start(depth=1))
        self.assertEqual(r['total_results'],1);self.assertIn('depth',r['limits_reached'])

    async def test_read_budget(self):
        self.search.TOTAL_BYTES=10
        (self.root/'big').write_text('needle'*10)
        r=await self.finish(await self.start())
        self.assertLessEqual(r['bytes_read'],10);self.assertIn('total_bytes',r['limits_reached'])

    async def test_entry_budget(self):
        self.search.MAX_ENTRIES=2
        for i in range(10):(self.root/str(i)).write_text('needle')
        r=await self.finish(await self.start())
        self.assertIn('entries',r['limits_reached']);self.assertLessEqual(r['total_results'],2)

    async def test_response_budget_and_long_line(self):
        self.search.RESULT_BYTES=9000
        (self.root/'big').write_text(('needle'+chr(0xe8)*4000+'\n')*10)
        r=await self.finish(await self.start(context_lines=0))
        self.assertIn('result_bytes',r['limits_reached'])
        self.assertTrue(r['results'][0]['text_truncated'])
        self.assertLessEqual(len(r['results'][0]['text'].encode()),2048)

    async def test_owner_isolation(self):
        r=await self.start();sid=r['search_id']
        with self.assertRaises(PermissionError):self.search.owned(OTHER,sid)
        with self.assertRaises(PermissionError):await self.search.stop(OTHER,sid)
        await self.search.stop(OWNER,sid)

    async def test_cancel_before_worker_starts_releases_guard(self):
        r=await self.start();s=await self.search.stop(OWNER,r['search_id'])
        self.assertEqual(s['status'],'cancelled');self.assertFalse(self.search.active())
        with self.files._locked([str(self.root/'new')],OWNER):pass

    async def test_active_search_blocks_writes(self):
        r=await self.start()
        with self.assertRaises(PermissionError):self.search.guard_mutation('write_file')
        fd=os.open('guard',os.O_RDWR,dir_fd=self.files.state_fd)
        try:
            with self.assertRaises(BlockingIOError):fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        finally:os.close(fd)
        await self.search.stop(OWNER,r['search_id'])
        self.search.guard_mutation('write_file')

    async def test_existing_exclusive_lock_blocks_search(self):
        with self.files._locked([str(self.root/'new')],OWNER):
            with self.assertRaises(BlockingIOError):await self.start()
        self.assertFalse(self.search.jobs)

    async def test_disconnect_cancels_and_clears(self):
        await self.start();await self.start();await self.search.close()
        self.assertFalse(self.search.jobs)
        with self.files._locked([str(self.root/'new')],OWNER):pass

    async def test_capacity_and_expiration(self):
        self.search.MAX_JOBS=2
        for _ in range(2):await self.finish(await self.start())
        with self.assertRaises(PermissionError):await self.start()
        for j in self.search.jobs.values():j['finished']=time.monotonic()-301
        r=await self.start();self.assertEqual(len(self.search.jobs),1)
        await self.search.stop(OWNER,r['search_id'])

    async def test_timeout(self):
        r=await self.start();self.search.jobs[r['search_id']]['deadline']=time.monotonic()-1
        (self.root/'a').write_text('needle')
        r=await self.finish(r);self.assertIn('timeout',r['limits_reached'])

    async def test_root_replaced(self):
        old=self.base/'old';self.root.rename(old);self.root.mkdir()
        with self.assertRaises(FileToolError):await self.start()

    async def test_validation(self):
        bad=[{'pattern':''},{'pattern':'a\nb'},{'pattern':'x'*257},{'search_type':'oops'},
             {'match_mode':'regex'},{'match_mode':'glob'}, {'ignore_case':1}, {'depth':True},
             {'max_results':1001},{'timeout_seconds':0},{'extra':'bad'},{'include_hidden':'yes'}]
        for kw in bad:
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):await self.start(**kw)

    async def test_pagination_validation(self):
        r=await self.finish(await self.start());sid=r['search_id']
        for args in ({'offset':-1},{'length':0},{'length':101},{'length':True},{'extra':1}):
            with self.assertRaises(ValueError):await self.search.dispatch('get_more_search_results',{'search_id':sid,**args},OWNER)

    async def test_filename_replaced_with_link_before_read(self):
        target=self.root/'race';target.write_text('needle safe')
        outside=self.base/'outside';outside.write_text('needle SECRET')
        original=self.search.read_text
        async def swap(job,fd,name):
            target.unlink();target.symlink_to(outside)
            return await original(job,fd,name)
        with patch.object(self.search,'read_text',swap):r=await self.finish(await self.start())
        self.assertEqual(r['total_results'],0);self.assertNotIn('SECRET',json.dumps(r))

    async def test_regular_read_detects_change(self):
        target=self.root/'a';target.write_text('needle')
        original=os.read
        def changed(fd,count):
            value=original(fd,count)
            if value:target.write_text('changed size!')
            return value
        with patch('search_tools.os.read',changed):r=await self.finish(await self.start())
        self.assertEqual(r['total_results'],0);self.assertEqual(r['skipped']['changed_file'],1)


class Schema(unittest.TestCase):
    def test_glob(self):
        for text,pattern,expected in [('abc','a*',True),('abc','a?c',True),('abc','*d',False),
                                       ('a.py','*.py',True),('x[0]','x[0]',True),('','*',True)]:
            self.assertEqual(glob_match(text,pattern),expected)

    def test_tools_unique_and_machines(self):
        from cg_tools import TOOLS,NAMES
        self.assertEqual(len(TOOLS),len(NAMES));self.assertEqual(len(TOOLS),29)
        self.assertTrue({'work_session','work_lock'} <= NAMES)
        self.assertTrue({'start_search','get_more_search_results','stop_search'}<=NAMES)
        for t in TOOLS:
            m=t['inputSchema']['properties'].get('machine',{})
            if 'enum' in m:self.assertEqual(set(m['enum']),{'vps','mac_noleggio','mac_mio'})


if __name__=='__main__':unittest.main(verbosity=2)
''',
'test_vps_agent.py': r'''"""VPS agent v0.12: sessions, locks, new file tools, shell and search ownership."""
import asyncio
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch
import uuid

HERE = Path(__file__).resolve().parent
# The copy under test must win over a deployed sibling directory.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE.parent) not in sys.path:
    sys.path.append(str(HERE.parent))
try:
    import isolated_shell  # noqa: F401  (deployed name on the VPS)
except ImportError:
    import shell_common
    sys.modules['isolated_shell'] = shell_common
sys.modules.setdefault('aiohttp', types.ModuleType('aiohttp'))

TMP = tempfile.TemporaryDirectory()
ROOT = Path(TMP.name)
WORKDIR = ROOT / 'workspace'; SCRATCH = ROOT / 'tmp'; DATA = ROOT / 'data'
for d in (WORKDIR, SCRATCH, DATA):
    d.mkdir(mode=0o700)
(DATA / 'protected').mkdir(mode=0o700)
CONFIG = ROOT / 'agent.json'
CONFIG.write_text(json.dumps({'data_root': str(DATA), 'token_file': str(ROOT / 'token'),
                              'allowed_roots': [str(WORKDIR), str(SCRATCH)],
                              'protected_paths': [str(DATA / 'protected')],
                              'full_shell_capable': False, 'shell_backend': 'bwrap-v08',
                              'tls_sha256': '00', 'gateway_url': 'wss://example.invalid'}))
os.environ['CENTRAL_MCP_AGENT_CONFIG'] = str(CONFIG)
agent = importlib.import_module('agent')


def tearDownModule():
    agent.UPLOADS.close(); agent.WORK.close(); agent.FILE_ENGINE.close(); TMP.cleanup()


class VpsAgent(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.a = await self.call('work_session', {'action': 'open', 'label': 'A', 'minutes': 10})
        self.b = await self.call('work_session', {'action': 'open', 'label': 'B', 'minutes': 10})

    async def asyncTearDown(self):
        await agent.SHELL.disable()
        for s in (self.a, self.b):
            try:
                await self.call('work_session', {'action': 'close'}, s)
            except PermissionError:
                pass
        if agent.WATCHDOG:
            agent.WATCHDOG.cancel()
            with __import__('contextlib').suppress(asyncio.CancelledError):
                await agent.WATCHDOG
            agent.WATCHDOG = None
        await agent.SEARCH.close()

    async def call(self, op, args, s=None, caller='claude:testclient'):
        if s:
            args = {**args, 'work_session_id': s['work_session_id'], 'work_session_token': s['work_session_token']}
        return await agent.dispatch(op, args, caller, uuid.uuid4().hex)

    async def lock(self, s, path=WORKDIR):
        return await self.call('work_lock', {'action': 'acquire', 'path': str(path), 'minutes': 10}, s)

    def folder(self):
        return WORKDIR / ('t' + uuid.uuid4().hex)

    async def test_writes_require_session_and_lock(self):
        f = self.folder()
        with self.assertRaises(PermissionError):
            await self.call('create_directory', {'path': str(f)})
        with self.assertRaises(PermissionError):
            await self.call('create_directory', {'path': str(f)}, self.a)
        await self.lock(self.a, f)
        r = await self.call('create_directory', {'path': str(f)}, self.a)
        with self.assertRaises(PermissionError):
            await self.call('write_file', {'path': str(f / 'x'), 'content': 'x'}, self.b)
        with self.assertRaises(PermissionError):
            await self.lock(self.b, f / 'x')
        await self.call('rollback_file', {'operation_id': r['operation_id']}, self.a)
        self.assertFalse(f.exists())

    async def test_reads_and_baseline_without_session(self):
        (WORKDIR / 'plain.txt').write_text('ciao')
        self.assertEqual((await self.call('read_file', {'path': str(WORKDIR / 'plain.txt')}))['content'], 'ciao')
        r = await self.call('read_binary', {'path': str(WORKDIR / 'plain.txt')})
        self.assertEqual(base64.b64decode(r['content_base64']), b'ciao')
        with patch.object(agent, 'run_baseline', new=AsyncMock(return_value={'exit_code': 0})):
            self.assertEqual((await self.call('shell_exec', {'command': 'uname -a'}))['exit_code'], 0)
        (WORKDIR / 'plain.txt').unlink()

    async def test_new_tools_delete_copy_upload_with_rollback(self):
        f = self.folder(); await self.lock(self.a, f)
        await self.call('create_directory', {'path': str(f / 'src')}, self.a)
        await self.call('write_file', {'path': str(f / 'src' / 'a.txt'), 'content': 'alpha'}, self.a)
        c = await self.call('copy_file', {'source': str(f / 'src'), 'destination': str(f / 'dst')}, self.a)
        self.assertEqual((f / 'dst' / 'a.txt').read_text(), 'alpha')
        d = await self.call('delete_path', {'path': str(f / 'src')}, self.a)
        self.assertFalse((f / 'src').exists())
        with self.assertRaises(PermissionError):
            await self.call('rollback_file', {'operation_id': d['operation_id']}, self.b)
        await self.call('rollback_file', {'operation_id': d['operation_id']}, self.a)
        self.assertEqual((f / 'src' / 'a.txt').read_text(), 'alpha')
        await self.call('rollback_file', {'operation_id': c['operation_id']}, self.a)
        data = os.urandom(5000)
        b = await self.call('upload_file', {'action': 'begin', 'path': str(f / 'bin'), 'size': len(data),
                                            'sha256': hashlib.sha256(data).hexdigest()}, self.a)
        with self.assertRaises(Exception):
            await self.call('upload_file', {'action': 'commit', 'upload_id': b['upload_id']}, self.b)
        await self.call('upload_file', {'action': 'chunk', 'upload_id': b['upload_id'], 'offset': 0,
                                        'data': base64.b64encode(data).decode()}, self.a)
        await self.call('upload_file', {'action': 'commit', 'upload_id': b['upload_id']}, self.a)
        self.assertEqual((f / 'bin').read_bytes(), data)

    async def test_scratch_root_also_locked(self):
        p = SCRATCH / ('s' + uuid.uuid4().hex)
        with self.assertRaises(PermissionError):
            await self.call('write_file', {'path': str(p), 'content': 'x'}, self.a)
        await self.lock(self.a, p)
        await self.call('write_file', {'path': str(p), 'content': 'x'}, self.a)
        p.unlink()

    async def test_protected_path_still_refused(self):
        with self.assertRaises(Exception):
            await self.call('work_lock', {'action': 'acquire', 'path': str(DATA / 'protected'), 'minutes': 5}, self.a)

    async def test_shell_needs_whole_workspace_lock_and_is_offline(self):
        with self.assertRaises(PermissionError):
            await self.call('enable_full_shell', {'minutes': 1}, self.a)
        await self.lock(self.a)
        with self.assertRaises(ValueError):
            await self.call('enable_full_shell', {'minutes': 1, 'network': 'github'}, self.a)
        with self.assertRaises(PermissionError):
            await self.call('enable_full_shell', {'minutes': 11}, self.a)
        with patch.object(agent.SHELL, 'enable', new=AsyncMock(return_value={'enabled': True})) as m:
            await self.call('enable_full_shell', {'minutes': 1}, self.a)
            m.assert_awaited_once_with('work:' + self.a['work_session_id'], 1)
        with self.assertRaises(PermissionError):
            await self.call('shell_exec', {'command': 'ls'}, self.b)

    async def test_foreign_disable_refused_and_close_revokes_shell(self):
        await self.lock(self.a); identity = 'work:' + self.a['work_session_id']
        agent.SHELL.owner = identity; agent.SHELL.until = __import__('time').monotonic() + 60
        with self.assertRaises(PermissionError):
            await self.call('disable_full_shell', {}, self.b)
        with self.assertRaises(PermissionError):
            lock_id = (await self.call('who_is_working', {}))['work_locks'][0]['lock_id']
            await self.call('work_lock', {'action': 'release', 'lock_id': lock_id}, self.a)
        await self.call('work_session', {'action': 'close'}, self.a)
        self.assertIsNone(agent.SHELL.owner)
        await self.lock(self.b)

    async def test_expired_session_reaps_shell_before_new_lock(self):
        await self.lock(self.a); identity = 'work:' + self.a['work_session_id']
        agent.SHELL.owner = identity; agent.SHELL.until = __import__('time').monotonic() + 60
        with agent.WORK.transaction() as d:
            d['sessions'][self.a['work_session_id']]['deadline'] = 0
        await self.lock(self.b)
        self.assertIsNone(agent.SHELL.owner)

    async def test_search_private_to_session(self):
        f = self.folder(); await self.lock(self.a, f)
        await self.call('create_directory', {'path': str(f)}, self.a)
        await self.call('write_file', {'path': str(f / 'n.txt'), 'content': 'needle_vps'}, self.a)
        r = await self.call('start_search', {'path': str(f), 'pattern': 'needle_vps'}, self.a)
        await agent.SEARCH.jobs[r['search_id']]['task']
        with self.assertRaises(PermissionError):
            await self.call('get_more_search_results', {'search_id': r['search_id']}, self.b)
        self.assertEqual((await self.call('get_more_search_results', {'search_id': r['search_id']}, self.a))['total_results'], 1)
        with self.assertRaises(PermissionError):
            await self.call('start_search', {'path': str(f), 'pattern': 'x'})

    async def test_who_is_working_and_meta_without_tokens(self):
        await self.lock(self.a)
        state = await self.call('who_is_working', {})
        self.assertEqual(len(state['work_locks']), 1)
        self.assertNotIn(self.a['work_session_token'], json.dumps(state))
        meta = agent.hello_meta()
        self.assertEqual(meta['coordination_version'], '0.11.0')
        for n in ('work_session', 'work_lock', 'delete_path', 'copy_file', 'read_binary', 'upload_file'):
            self.assertIn(n, meta['capabilities'])

    async def test_session_and_lock_operations_audited_with_session_id(self):
        await self.lock(self.a)
        recent = (await self.call('who_is_working', {}))['recent_work_operations']
        ops = [(x['operation'], x['work_session_id']) for x in recent if 'request_id' in x]
        self.assertIn(('work_lock', self.a['work_session_id']), ops)
        self.assertIn(('work_session', self.b['work_session_id']), ops)

    async def test_legacy_rollback_requires_lock(self):
        op = uuid.uuid4().hex; target = WORKDIR / ('legacy' + op)
        (agent.OPS_ROOT / op).mkdir(mode=0o700)
        (agent.OPS_ROOT / op / 'meta.json').write_text(json.dumps({'operation_id': op, 'target': str(target),
                                                                   'existed': False, 'mode': None, 'rolled_back': False}))
        target.write_text('created by old agent')
        with self.assertRaises(PermissionError):
            await self.call('rollback_file', {'operation_id': op}, self.a)
        await self.lock(self.a, target)
        await self.call('rollback_file', {'operation_id': op}, self.a)
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
''',
'upload_tools.py': r'''"""Chunked binary uploads, staged privately and committed as one journaled write.

Chunks never touch the project tree. Only commit, after size and SHA-256 match,
writes the destination through FileTools, so rollback keeps one backup per file
instead of one per chunk. Staging is bounded, owner-bound and expires.
"""
import base64
import binascii
import hashlib
import os
import re
import stat
import time
import uuid

from file_tools import FileToolError

ID = re.compile(r'[a-f0-9]{32}')
SHA = re.compile(r'[a-f0-9]{64}')


class Uploads:
    MAX_ACTIVE = 4
    MAX_STAGED = 32 * 1024 * 1024
    TTL = 30 * 60
    MAX_CHUNK_BASE64 = 262144

    def __init__(self, files, directory, clock=time.monotonic):
        self.files, self.clock = files, clock
        self.path = os.path.abspath(directory)
        os.makedirs(self.path, mode=0o700, exist_ok=True)
        s = os.lstat(self.path)
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
            raise PermissionError('private upload directory required')
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        # Staged data does not survive an agent restart: clients start again.
        for name in os.listdir(self.fd):
            if re.fullmatch(r'[a-f0-9]{32}\.part', name):
                os.unlink(name, dir_fd=self.fd)
            else:
                raise PermissionError('unexpected upload staging entry')
        self.jobs = {}

    def close(self):
        for uid in list(self.jobs):
            self._drop(uid)
        os.close(self.fd)

    def _drop(self, uid):
        self.jobs.pop(uid, None)
        try:
            os.unlink(uid + '.part', dir_fd=self.fd)
        except FileNotFoundError:
            pass

    def purge(self):
        now = self.clock()
        for uid, job in list(self.jobs.items()):
            if now >= job['deadline']:
                self._drop(uid)

    def _job(self, identity, upload_id):
        if not isinstance(upload_id, str) or not ID.fullmatch(upload_id):
            raise FileToolError('INVALID_ARGUMENT', 'invalid upload_id')
        job = self.jobs.get(upload_id)
        if job is None or job['owner'] != identity:
            raise FileToolError('UPLOAD_UNKNOWN', 'upload missing, expired, or owned by another session')
        return job

    def begin(self, identity, path, size, sha256, overwrite=False):
        if type(size) is not int or not 0 <= size <= self.files.max_file:
            raise FileToolError('LIMIT', 'size must be 0..%d bytes' % self.files.max_file)
        if not isinstance(sha256, str) or not SHA.fullmatch(sha256):
            raise FileToolError('INVALID_ARGUMENT', 'lowercase hex sha256 required')
        if type(overwrite) is not bool:
            raise FileToolError('INVALID_ARGUMENT', 'overwrite must be boolean')
        if len(self.jobs) >= self.MAX_ACTIVE:
            raise FileToolError('LIMIT', 'too many active uploads; commit or abort one')
        if sum(j['size'] for j in self.jobs.values()) + size > self.MAX_STAGED:
            raise FileToolError('LIMIT', 'upload staging quota reached')
        # Fail early when the destination is not covered by this session's lock.
        with self.files._locked([path], identity):
            kind = self.files._snapshot(path)['kind']
        if kind == 'directory' or kind == 'file' and not overwrite:
            raise FileToolError('DESTINATION_EXISTS', 'destination exists; pass overwrite=true for a file')
        uid = uuid.uuid4().hex
        fd = os.open(uid + '.part', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        os.close(fd)
        self.jobs[uid] = {'owner': identity, 'path': path, 'size': size, 'sha256': sha256,
                          'overwrite': overwrite, 'received': 0, 'deadline': self.clock() + self.TTL}
        return {'upload_id': uid, 'path': path, 'size': size, 'received': 0,
                'max_chunk_base64': self.MAX_CHUNK_BASE64, 'expires_in_seconds': self.TTL}

    def chunk(self, identity, upload_id, offset, data):
        job = self._job(identity, upload_id)
        if type(offset) is not int or offset != job['received']:
            raise FileToolError('OFFSET_MISMATCH', 'offset must equal bytes received', received=job['received'])
        if not isinstance(data, str) or not data or len(data) > self.MAX_CHUNK_BASE64:
            raise FileToolError('INVALID_ARGUMENT', 'data must be 1..%d base64 characters' % self.MAX_CHUNK_BASE64)
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise FileToolError('INVALID_ARGUMENT', 'data is not valid base64') from None
        if job['received'] + len(raw) > job['size']:
            raise FileToolError('LIMIT', 'chunk exceeds declared size')
        fd = os.open(upload_id + '.part', os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            if os.fstat(fd).st_size != job['received']:
                raise FileToolError('UPLOAD_CORRUPT', 'staged data changed; abort and restart')
            os.write(fd, raw)
        finally:
            os.close(fd)
        job['received'] += len(raw)
        return {'upload_id': upload_id, 'received': job['received'], 'size': job['size'],
                'complete': job['received'] == job['size']}

    def commit(self, identity, upload_id):
        job = self._job(identity, upload_id)
        if job['received'] != job['size']:
            raise FileToolError('INCOMPLETE', 'upload incomplete', received=job['received'], size=job['size'])
        fd = os.open(upload_id + '.part', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        with os.fdopen(fd, 'rb') as f:
            data = f.read(job['size'] + 1)
        if len(data) != job['size'] or hashlib.sha256(data).hexdigest() != job['sha256']:
            self._drop(upload_id)
            raise FileToolError('CHECKSUM_MISMATCH', 'size or sha256 differs; upload discarded')
        result = self.files.write_bytes(job['path'], data, job['overwrite'], identity)
        self._drop(upload_id)
        return {'upload_id': upload_id, **result}

    def abort(self, identity, upload_id):
        self._job(identity, upload_id)
        self._drop(upload_id)
        return {'upload_id': upload_id, 'aborted': True}

    def dispatch(self, identity, args):
        self.purge()
        a = dict(args)
        action = a.pop('action', None)
        allowed = {'begin': {'path', 'size', 'sha256', 'overwrite'}, 'chunk': {'upload_id', 'offset', 'data'},
                   'commit': {'upload_id'}, 'abort': {'upload_id'}}
        if action not in allowed or set(a) - allowed[action]:
            raise FileToolError('INVALID_ARGUMENT', 'action begin|chunk|commit|abort with its own fields')
        try:
            return getattr(self, action)(identity, **a)
        except TypeError:
            raise FileToolError('INVALID_ARGUMENT', 'missing or unexpected parameters') from None

    def owned_by(self, identity):
        return [uid for uid, j in self.jobs.items() if j['owner'] == identity]
''',
'work_schema.py': r'''"""Explicit work sessions, separate from terminal session IDs."""
import copy

AUTH = {'work_session_id': {'type':'string','pattern':'^[a-f0-9]{32}$'},
        'work_session_token': {'type':'string','minLength':43,'maxLength':43}}
MACHINE = {'type':'string','enum':['mac_mio','vps','mac_noleggio']}
MINUTES = {'type':'integer','minimum':1,'maximum':240}
WORK_TOOLS = [
 {'name':'work_session','description':'Open, renew or close a logical work session. Open once per chat; retain the returned id and capability token privately. Closing cancels its searches and shell before releasing locks. Distinct chats must not share the token.',
  'inputSchema':{'type':'object','additionalProperties':False,'required':['machine','action'],
   'properties':{'machine':MACHINE,'action':{'type':'string','enum':['open','renew','close']},
                 'label':{'type':'string','minLength':1,'maxLength':80},'minutes':MINUTES,**AUTH}}},
 {'name':'work_lock','description':'Acquire, renew or release a durable exclusive path reservation. Acquire a covering lock before writes; a whole-workspace lock is required for the isolated shell. Conflicts name the owning work session. No lock stealing.',
  'inputSchema':{'type':'object','additionalProperties':False,'required':['machine','action','work_session_id','work_session_token'],
   'properties':{'machine':MACHINE,'action':{'type':'string','enum':['acquire','renew','release']},
                 'path':{'type':'string'},'lock_id':{'type':'string','pattern':'^[a-f0-9]{32}$'},
                 'minutes':MINUTES,**AUTH}}}
]
WORK_NAMES = {t['name'] for t in WORK_TOOLS}
SCOPED = {'read_file','read_multiple_files','write_file','edit_block','create_directory',
          'move_file','get_file_info','list_directory','rollback_file','shell_exec','shell_session',
          'enable_full_shell','disable_full_shell','start_search','get_more_search_results','stop_search',
          'delete_path','copy_file','read_binary','upload_file'}


def install_schema(tools):
    result = copy.deepcopy([t for t in tools if t['name'] not in WORK_NAMES])
    for t in result:
        if t['name'] in SCOPED:
            t['inputSchema']['properties'].update(copy.deepcopy(AUTH))
            t['description'] += ' If the selected machine advertises coordination_version, supply work_session_id and work_session_token for writes, searches and shell operations. Read-only calls remain available without them.'
    return result + copy.deepcopy(WORK_TOOLS)
''',
'work_sessions.py': r'''"""Durable cooperative work sessions. No OAuth credentials are stored here.

Each logical client opens a session and keeps its random capability token.
Tokens separate cooperating chats sharing one OAuth authorization; they are not
proof of a platform chat ID and cannot protect a token deliberately shared.
Only the agent's protected state directory may contain this store.
"""
import contextlib
import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import sys
import threading
import time
import unicodedata
import uuid

ID = re.compile(r'[a-f0-9]{32}')
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}')
CALLER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}')
MUTATIONS = {'write_file', 'edit_block', 'create_directory', 'move_file', 'rollback_file',
             'delete_path', 'copy_file', 'upload_file'}


def boot_identity():
    if sys.platform == 'darwin':
        # kern.boottime is shifted by calendar steps (NTP); the boot session
        # UUID is stable for the whole boot.
        # sysctlbyname needs no subprocess and is also allowed by the seatbelt.
        import ctypes, ctypes.util
        libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
        size = ctypes.c_size_t(64); buf = ctypes.create_string_buffer(64)
        if libc.sysctlbyname(b'kern.bootsessionuuid', buf, ctypes.byref(size), None, ctypes.c_size_t(0)):
            raise RuntimeError('boot identity unavailable')
        raw = buf.raw[:size.value].rstrip(b'\0')
        if not re.fullmatch(rb'[0-9A-Fa-f-]{36}', raw):
            raise RuntimeError('boot identity unavailable')
    elif sys.platform.startswith('linux'):
        with open('/proc/sys/kernel/random/boot_id', 'rb') as f:
            raw = f.read(100)
    else:
        raise RuntimeError('unsupported boot clock')
    if not raw.strip():
        raise RuntimeError('boot identity unavailable')
    return hashlib.sha256(raw.strip()).hexdigest()


def shared_clock():
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)


class WorkSessions:
    MAX_BYTES = 1024 * 1024
    MAX_SESSIONS = 64
    MAX_LOCKS = 256

    def __init__(self, directory, files, wall=time.time, clock=shared_clock, boot=None):
        self.path = os.path.abspath(directory)
        self.files, self.wall, self.clock = files, wall, clock
        self.boot = boot if boot is not None else boot_identity()
        os.makedirs(self.path, mode=0o700, exist_ok=True)
        s = os.lstat(self.path)
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
            raise PermissionError('private work-session directory required')
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.mutex = threading.RLock()
        self.depth, self.current = 0, None
        with self.transaction():
            pass

    def close(self):
        os.close(self.fd)

    @staticmethod
    def minutes(value):
        if type(value) is not int or not 1 <= value <= 240:
            raise ValueError('minutes must be 1..240')
        return value

    def times(self):
        wall, tick = self.wall(), self.clock()
        if not all(math.isfinite(x) and x >= 0 for x in (wall, tick)):
            raise RuntimeError('invalid clock')
        return wall, tick

    def private(self, fd):
        s = os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_nlink != 1 or s.st_mode & 0o077:
            raise PermissionError('unsafe work-session state')

    def read_state(self):
        try:
            fd = os.open('state.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        except FileNotFoundError:
            return {'version': 1, 'sessions': {}, 'locks': {}, 'recent': []}
        with os.fdopen(fd, 'rb') as f:
            self.private(f.fileno())
            raw = f.read(self.MAX_BYTES + 1)
        if len(raw) > self.MAX_BYTES:
            raise RuntimeError('session state exceeds limit')
        d = json.loads(raw)
        if (set(d) != {'version', 'sessions', 'locks', 'recent'} or d['version'] != 1
                or not isinstance(d['sessions'], dict) or not isinstance(d['locks'], dict)
                or not isinstance(d['recent'], list)):
            raise RuntimeError('invalid session state; manual review required')
        return d

    def write_state(self, d):
        raw = json.dumps(d, ensure_ascii=True, separators=(',', ':')).encode()
        if len(raw) > self.MAX_BYTES:
            raise RuntimeError('session state exceeds limit')
        name = '.state-' + uuid.uuid4().hex
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(raw); f.flush(); os.fsync(f.fileno())
            os.replace(name, 'state.json', src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            with contextlib.suppress(FileNotFoundError): os.unlink(name, dir_fd=self.fd)

    def purge(self, d):
        wall, tick = self.times()
        for sid, s in list(d['sessions'].items()):
            if s['boot'] != self.boot or wall >= s['expires_at'] or tick >= s['deadline']:
                del d['sessions'][sid]
        for lid, l in list(d['locks'].items()):
            if l['session_id'] not in d['sessions'] or wall >= l['expires_at'] or tick >= l['deadline']:
                del d['locks'][lid]

    @contextlib.contextmanager
    def transaction(self):
        with self.mutex:
            if self.depth:
                self.depth += 1
                try:
                    self.purge(self.current)
                    yield self.current
                finally: self.depth -= 1
                return
            lock = os.open('guard', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            try:
                self.private(lock)
                # Never block the event loop on a concurrent client or process.
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                d = self.read_state()
                before = json.dumps(d, sort_keys=True)
                self.purge(d)
                self.current, self.depth = d, 1
                try:
                    yield d
                finally:
                    # Read-only checks (watchdog every 0.5s) must not fsync.
                    if json.dumps(d, sort_keys=True) != before:
                        self.write_state(d)
                    self.current, self.depth = None, 0
            finally:
                self.current, self.depth = None, 0
                os.close(lock)

    def canonical(self, path):
        p, _, parts = self.files._path(path)
        # Inspect every existing component. Missing descendants may be reserved.
        root = p
        for _ in parts: root = os.path.dirname(root)
        current = root
        for part in parts:
            current = os.path.join(current, part)
            try: s = os.lstat(current)
            except FileNotFoundError: break
            if stat.S_ISLNK(s.st_mode):
                raise PermissionError('symlink lock paths are rejected')
        return p

    @staticmethod
    def key(path):
        # Conservative on case-sensitive volumes, correct on ordinary Mac APFS.
        return unicodedata.normalize('NFD', path).casefold().rstrip('/')

    @classmethod
    def contains(cls, parent, child):
        a, b = cls.key(parent), cls.key(child)
        return a == b or b.startswith(a + '/')

    def event(self, d, sid, operation, **fields):
        d['recent'].append({'time': self.wall(), 'work_session_id': sid, 'operation': operation, **fields})
        del d['recent'][:-100]

    def open(self, caller, label, minutes=30):
        if not isinstance(caller, str) or not CALLER.fullmatch(caller):
            raise PermissionError('authenticated caller required')
        if not isinstance(label, str) or not 1 <= len(label) <= 80 or any(ord(c) < 32 for c in label):
            raise ValueError('label requires 1..80 printable characters')
        self.minutes(minutes)
        with self.transaction() as d:
            if len(d['sessions']) >= self.MAX_SESSIONS:
                raise PermissionError('work session capacity reached')
            sid, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
            wall, tick = self.times()
            d['sessions'][sid] = {'caller': caller, 'label': label,
                'token_hash': hashlib.sha256(token.encode()).hexdigest(), 'boot': self.boot,
                'created_at': wall, 'expires_at': wall + minutes*60, 'deadline': tick + minutes*60}
            self.event(d, sid, 'session_open', label=label)
            return {'work_session_id': sid, 'work_session_token': token,
                    'expires_at': wall + minutes*60, 'label': label,
                    'identity_scope': 'explicit work session; do not share its capability token'}

    def auth(self, d, caller, sid, token):
        if not isinstance(sid, str) or not ID.fullmatch(sid) or not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise PermissionError('valid work session credentials required')
        s = d['sessions'].get(sid)
        if not s or s['caller'] != caller or not hmac.compare_digest(s['token_hash'], hashlib.sha256(token.encode()).hexdigest()):
            raise PermissionError('invalid or expired work session')
        return s

    def authenticate(self, caller, sid, token):
        with self.transaction() as d:
            self.auth(d, caller, sid, token)
        return 'work:' + sid

    def renew(self, caller, sid, token, minutes=30):
        self.minutes(minutes)
        with self.transaction() as d:
            s = self.auth(d, caller, sid, token)
            wall, tick = self.times()
            s.update(expires_at=wall + minutes*60, deadline=tick + minutes*60)
            self.event(d, sid, 'session_renew')
            return {'work_session_id': sid, 'expires_at': s['expires_at'],
                    'note': 'locks retain their own expiry; renew them separately'}

    def end(self, caller, sid, token):
        with self.transaction() as d:
            self.auth(d, caller, sid, token)
            del d['sessions'][sid]
            d['locks'] = {k:v for k,v in d['locks'].items() if v['session_id'] != sid}
            self.event(d, sid, 'session_close')
            return {'work_session_id': sid, 'closed': True}

    def acquire(self, caller, sid, token, path, minutes=30):
        path = self.canonical(path); self.minutes(minutes)
        with self.transaction() as d:
            s = self.auth(d, caller, sid, token)
            if len(d['locks']) >= self.MAX_LOCKS:
                raise PermissionError('work lock capacity reached')
            for l in d['locks'].values():
                if self.contains(l['path'], path) or self.contains(path, l['path']):
                    if l['session_id'] != sid:
                        raise PermissionError('path locked by work session ' + l['session_id'])
                    if self.key(l['path']) == self.key(path):
                        raise ValueError('path already locked by this session; renew the lock')
            wall, tick = self.times(); lid = uuid.uuid4().hex
            l = {'lock_id': lid, 'session_id': sid, 'path': path,
                 'expires_at': min(s['expires_at'], wall + minutes*60),
                 'deadline': min(s['deadline'], tick + minutes*60)}
            d['locks'][lid] = l
            self.event(d, sid, 'lock_acquire', path=path, lock_id=lid)
            return self.public_lock(l)

    def change_lock(self, caller, sid, token, lock_id, minutes=None):
        if not isinstance(lock_id, str) or not ID.fullmatch(lock_id):
            raise ValueError('invalid lock id')
        with self.transaction() as d:
            s = self.auth(d, caller, sid, token)
            l = d['locks'].get(lock_id)
            if not l or l['session_id'] != sid:
                raise PermissionError('lock missing, expired, or owned by another session')
            if minutes is None:
                del d['locks'][lock_id]
                self.event(d, sid, 'lock_release', lock_id=lock_id)
                return {'lock_id': lock_id, 'released': True}
            self.minutes(minutes); wall, tick = self.times()
            l.update(expires_at=min(s['expires_at'], wall + minutes*60),
                     deadline=min(s['deadline'], tick + minutes*60))
            self.event(d, sid, 'lock_renew', lock_id=lock_id)
            return self.public_lock(l)

    @staticmethod
    def public_lock(l):
        return {k:v for k,v in l.items() if k != 'deadline'}

    def require(self, d, identity, path):
        if not isinstance(identity, str) or not identity.startswith('work:'):
            raise PermissionError('open a work session before changing files')
        sid = identity[5:]
        if sid not in d['sessions']:
            raise PermissionError('work session expired')
        if not any(l['session_id'] == sid and self.contains(l['path'], path) for l in d['locks'].values()):
            raise PermissionError('acquire an unexpired work lock covering the path first')
        return d['sessions'][sid]

    @contextlib.contextmanager
    def lock_provider(self, identity, path):
        path = self.canonical(path)
        with self.transaction() as d:
            self.require(d, identity, path)
            yield

    def remaining(self, identity, path):
        path = self.canonical(path)
        with self.transaction() as d:
            s = self.require(d, identity, path)
            wall, tick = self.times()
            locks = [l for l in d['locks'].values() if l['session_id'] == identity[5:] and self.contains(l['path'], path)]
            lock_remaining = max(min(l['expires_at']-wall, l['deadline']-tick) for l in locks)
            return max(0, min(s['expires_at']-wall, s['deadline']-tick, lock_remaining))

    def audit(self, identity, operation, ok, request_id):
        with self.transaction() as d:
            sid = identity[5:] if isinstance(identity, str) and identity.startswith('work:') else None
            self.event(d, sid, operation, ok=bool(ok), request_id=request_id)

    def snapshot(self):
        with self.transaction() as d:
            return {'coordination_version': '0.11.0',
                    'identity_scope': 'explicit work session; cooperating clients must keep separate tokens',
                    'work_sessions': [{'work_session_id': k, 'label': s['label'], 'caller': s['caller'],
                                       'expires_at': s['expires_at']} for k,s in d['sessions'].items()],
                    'work_locks': [self.public_lock(l) for l in d['locks'].values()],
                    'recent_work_operations': list(d['recent'][-30:])}
''',
}


def sha(data):return hashlib.sha256(data).hexdigest()


def trusted_directory(path):
    for p in [path]+list(path.parents):
        st=p.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
            raise RuntimeError('untrusted directory: '+str(p))


def read(path, owner=0):
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=owner or st.st_mode&0o022 or st.st_nlink!=1:
            raise RuntimeError('unsafe file: '+str(path))
        data=f.read(2*1024*1024+1)
    if len(data)>2*1024*1024:raise RuntimeError('file exceeds limit')
    return data


def digest(path):
    if path.is_symlink():raise RuntimeError('symlink destination rejected')
    return sha(read(path)) if path.exists() else None


def atomic(path,data,mode=0o644,uid=0,gid=0):
    trusted_directory(path.parent)
    if path.is_symlink():raise RuntimeError('symlink destination rejected')
    fd,name=tempfile.mkstemp(prefix='.vps-v012-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchown(f.fileno(),uid,gid);os.fchmod(f.fileno(),mode)
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,str(path))
        dfd=os.open(str(path.parent),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:
        if os.path.exists(name):os.unlink(name)


def record(status,**fields):
    atomic(RECEIPT,json.dumps(dict(status=status,time=time.time(),**fields),indent=2).encode())


def run(argv,timeout=30):
    return subprocess.run(argv,check=True,capture_output=True,text=True,timeout=timeout,
                          env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C.UTF-8'})


def rpc(method,params):
    cfg=json.loads(read(Path('/etc/central-mcp-gateway/gateway-test.json')))
    ctx=ssl.create_default_context(cafile=cfg['tls_cert']);ctx.check_hostname=False
    token=read(Path(cfg['mcp_token_file'])).decode().strip()
    req=urllib.request.Request('https://127.0.0.1:'+str(cfg['port'])+'/mcp',
        data=json.dumps({'jsonrpc':'2.0','id':uuid.uuid4().hex,'method':method,'params':params}).encode(),
        headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
    with urllib.request.urlopen(req,context=ctx,timeout=10) as r:out=json.load(r)
    if 'error' in out:raise RuntimeError('local MCP request failed')
    return out['result']


def call(name,**args):
    value=rpc('tools/call',{'name':name,'arguments':args})
    if value.get('isError'):raise RuntimeError(name+': '+value['content'][0]['text'][:300])
    return json.loads(value['content'][0]['text'])


def idle():
    state=call('who_is_working',machine='vps')
    if state.get('active_locks') or state.get('shell_enabled') or state.get('work_locks') or state.get('work_sessions'):
        raise RuntimeError('VPS busy; active locks, work sessions or shell authorization present')


@contextlib.contextmanager
def workspace_guard():
    fd=os.open(str(GUARD),os.O_RDWR|os.O_NOFOLLOW)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=997 or st.st_nlink!=1 or st.st_mode&0o077:
            raise RuntimeError('unsafe workspace guard')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:os.close(fd)


def validate():
    if BACKUP.exists() or BACKUP.is_symlink():raise RuntimeError('backup already exists; inspect receipt before retry')
    for name,expected in {**ORIGINAL,**DEPENDENCIES}.items():
        if digest(BASE/name) not in (expected if isinstance(expected,list) else [expected]):
            raise RuntimeError('live source changed: '+name)
    for service,user in [(AGENT,'mcp-vps-agent'),(GATEWAY,'mcp-gateway')]:
        if run(['systemctl','show',service,'-p','User','--value']).stdout.strip()!=user:
            raise RuntimeError('service identity changed')
        if run(['systemctl','is-active',service]).stdout.strip()!='active':raise RuntimeError('service not active')
    idle()


def preflight():
    for p in (TEST_CODE,TEST_DATA):
        if p.exists() or p.is_symlink():raise RuntimeError('preflight directory already exists; inspect before retry')
    TEST_CODE.mkdir(mode=0o755);TEST_CODE.chmod(0o755)
    TEST_DATA.mkdir(mode=0o700);os.chown(str(TEST_DATA),997,987)
    for name,data in TESTS.items():atomic(TEST_CODE/name,data,0o444)
    for name in ORIGINAL:
        if TESTS.get(name)!=PAYLOAD[name]:raise RuntimeError('preflight differs from deployment')
    for name in LIVE_TEST_DEPS:
        if sha(TESTS[name])!=DEPENDENCIES[name]:raise RuntimeError('preflight dependency differs')
    code="import sys,unittest;sys.path.insert(0,"+repr(str(TEST_CODE))+");s=unittest.defaultTestLoader.loadTestsFromNames(['test_search','test_files_v012','test_vps_agent']);r=unittest.TextTestRunner(verbosity=2).run(s);sys.exit(0 if r.wasSuccessful() else 1)"
    result=subprocess.run([str(BASE/'.venv/bin/python'),'-I','-B','-c',code],
        user=997,group=987,extra_groups=[987],umask=0o077,cwd='/',close_fds=True,
        env={'PATH':'/usr/bin:/bin','HOME':'/var/empty','TMPDIR':str(TEST_DATA),'LANG':'C.UTF-8'},
        capture_output=True,text=True,timeout=120)
    atomic(TEST_CODE/'result.log',(result.stdout+result.stderr).encode()[-65536:])
    if result.returncode!=0:raise RuntimeError('non-admin preflight failed: '+result.stderr[-1000:])


def backup():
    trusted_directory(BACKUP.parent)
    BACKUP.mkdir(mode=0o700)
    manifest={}
    for name in ORIGINAL:
        path=BASE/name
        if ORIGINAL[name] is None:manifest[name]=None;continue
        data=read(path);st=path.lstat()
        manifest[name]={'sha256':sha(data),'mode':stat.S_IMODE(st.st_mode),'uid':st.st_uid,'gid':st.st_gid}
        atomic(BACKUP/name,data,0o600)
    atomic(BACKUP/'manifest.json',json.dumps(manifest,indent=2).encode(),0o600)
    return manifest


def restart(expect_new):
    run(['systemctl','restart',AGENT],90);run(['systemctl','restart',GATEWAY],90)
    end=time.monotonic()+45
    while time.monotonic()<end:
        try:
            machine=next(m for m in call('list_machines')['machines'] if m['machine']=='vps')
            if machine['online'] and machine['meta'].get('agent_version')==(NEW_VERSION if expect_new else OLD_VERSION):return
        except Exception:pass
        time.sleep(1)
    raise RuntimeError('VPS reconnection check failed')


def restore(strict=True):
    manifest=json.loads(read(BACKUP/'manifest.json'))
    if set(manifest)!=set(ORIGINAL):raise RuntimeError('unexpected backup manifest')
    # Check every destination and every backup before restoring any file.
    for name,old in ORIGINAL.items():
        current=digest(BASE/name)
        accepted={sha(PAYLOAD[name])} if strict else {old,sha(PAYLOAD[name])}
        if current not in accepted:raise RuntimeError('rollback conflict: '+name)
        if old is not None:
            if not manifest[name] or sha(read(BACKUP/name))!=old or manifest[name]['sha256']!=old:
                raise RuntimeError('backup mismatch: '+name)
    for name,meta in manifest.items():
        if meta is None:
            if (BASE/name).exists():(BASE/name).unlink()
        else:atomic(BASE/name,read(BACKUP/name),meta['mode'],meta['uid'],meta['gid'])


def smoke():
    names={t['name'] for t in rpc('tools/list',{})['tools']}
    if not {'work_session','work_lock'}<=names:raise RuntimeError('work tools missing from catalog')
    # The new file tools are exercised only once the gateway exposes them.
    new={'delete_path','copy_file','read_binary','upload_file'}<=names
    checks=[];operations=[];sessions=[]
    folder=str(WORK/('vps_v012_live_'+uuid.uuid4().hex))
    def scall(s,name,**args):
        return call(name,machine='vps',work_session_id=s['work_session_id'],work_session_token=s['work_session_token'],**args)
    def refused(name,**args):
        if not rpc('tools/call',{'name':name,'arguments':dict(machine='vps',**args)}).get('isError'):
            raise RuntimeError(name+' was not refused')
    try:
        a=call('work_session',machine='vps',action='open',label='installer A',minutes=5);sessions.append(a)
        b=call('work_session',machine='vps',action='open',label='installer B',minutes=5);sessions.append(b)
        refused('create_directory',path=folder)
        refused('create_directory',path=folder,work_session_id=a['work_session_id'],work_session_token=a['work_session_token'])
        checks.append('writes need session and lock')
        scall(a,'work_lock',action='acquire',path=folder,minutes=5)
        refused('work_lock',action='acquire',path=folder+'/x',minutes=5,work_session_id=b['work_session_id'],work_session_token=b['work_session_token'])
        checks.append('descendant lock conflict between sessions')
        # p2: a write into a missing directory fails cleanly and the journal stays usable.
        bad=rpc('tools/call',{'name':'write_file','arguments':dict(machine='vps',path=folder+'/missing/x',content='x',
            work_session_id=a['work_session_id'],work_session_token=a['work_session_token'])})
        if not bad.get('isError') or 'parent directory does not exist' not in bad['content'][0]['text']:raise RuntimeError('missing parent not refused cleanly')
        checks.append('missing parent refused; journal usable')
        operations.append(scall(a,'create_directory',path=folder)['operation_id'])
        path=folder+'/test.txt'
        operations.append(scall(a,'write_file',path=path,content='MCP_VPS_V012_OK\n')['operation_id'])
        refused('write_file',path=path,content='x',work_session_id=b['work_session_id'],work_session_token=b['work_session_token'])
        result=scall(a,'start_search',path=folder,pattern='MCP_VPS_V012_OK');sid=result['search_id']
        end=time.monotonic()+10
        while result['running'] and time.monotonic()<end:
            time.sleep(.1);result=scall(a,'get_more_search_results',search_id=sid)
        if result['status']!='completed' or result['total_results']!=1:raise RuntimeError('live search mismatch')
        checks.append('search with session')
        if new:
          data=b'\x00\x01v012'
          up=scall(a,'upload_file',action='begin',path=folder+'/bin',size=len(data),sha256=hashlib.sha256(data).hexdigest())
          scall(a,'upload_file',action='chunk',upload_id=up['upload_id'],offset=0,data=base64.b64encode(data).decode())
          operations.append(scall(a,'upload_file',action='commit',upload_id=up['upload_id'])['operation_id'])
          if call('read_binary',machine='vps',path=folder+'/bin')['sha256']!=hashlib.sha256(data).hexdigest():
              raise RuntimeError('binary round trip mismatch')
          operations.append(scall(a,'copy_file',source=path,destination=folder+'/copy.txt')['operation_id'])
          removed=scall(a,'delete_path',path=folder+'/copy.txt')
          scall(a,'rollback_file',operation_id=removed['operation_id'])
          checks.append('upload, read_binary, copy, delete and rollback')
        if call('shell_exec',machine='vps',command='uname -a')['exit_code']!=0:raise RuntimeError('baseline status failed')
        checks.append('baseline status without session')
    finally:
        for operation in reversed(operations):
            if sessions:scall(sessions[0],'rollback_file',operation_id=operation)
        for s in sessions:
            with contextlib.suppress(Exception):scall(s,'work_session',action='close')
    if Path(folder).exists():raise RuntimeError('smoke rollback left a test directory')
    idle();checks.append('test files rolled back; no sessions, locks or shell left')
    return checks


def load_package():
    global PAYLOAD,TESTS
    carried={n:src.encode() for n,src in SOURCES.items()}
    if {n:sha(b) for n,b in carried.items()}!=SOURCE_SHA:raise RuntimeError('unexpected embedded sources')
    PAYLOAD={n:carried[n] for n in ORIGINAL}
    # Unchanged dependencies come from the live, hash-pinned installation.
    TESTS={n:carried[n] if n in carried else read(BASE/n) for n in TEST_NAMES}
    for n in LIVE_TEST_DEPS:
        if sha(TESTS[n])!=DEPENDENCIES[n]:raise RuntimeError('live dependency changed: '+n)
    for name,data in {**PAYLOAD,**TESTS}.items():compile(data,name,'exec')


def main(action):
    if os.getuid()!=0 or os.geteuid()!=0 or Path(__file__).resolve()!=SELF:raise RuntimeError('installed root helper required')
    trusted_directory(BASE);read(SELF);load_package();os.umask(0o077)
    lock=os.open('/run/lock/mcp-andrea-files-maintenance.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    st=os.fstat(lock)
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_nlink!=1 or st.st_mode&0o077:
        os.close(lock);raise RuntimeError('unsafe maintenance lock')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        if action=='--apply':
            validate()
            run(['systemd-run','--unit=central-mcp-vps-v012p2-20261003','--on-active=5s','--collect',
                 '/usr/bin/python3',str(SELF),'--activate'])
            record('activation_scheduled');print(json.dumps({'status':'activation_scheduled','receipt':str(RECEIPT)}));return
        if action=='--activate':
            validate()
            try:preflight()
            except Exception as exc:
                record('preflight_failed',reason=str(exc)[:1200],live_modules_modified=False);raise
            validate()
            try:
                with workspace_guard():
                    # Stop only the VPS agent before replacing its modules.
                    manifest=backup();run(['systemctl','stop',AGENT],90)
                    try:
                        for name,data in PAYLOAD.items():
                            meta=manifest[name] or {'mode':0o644,'uid':0,'gid':0}
                            atomic(BASE/name,data,meta['mode'],meta['uid'],meta['gid'])
                    except Exception:
                        restore(strict=False);raise
            except Exception as exc:
                if BACKUP.exists():
                    with contextlib.suppress(Exception):restart(False)
                record('apply_failed',reason=str(exc)[:1200]);raise
            try:
                restart(True);checks=smoke()
                record('active',checks=checks,backup=str(BACKUP),preflight_uid=997,
                       hashes={n:sha(b) for n,b in PAYLOAD.items()},rental_touched=False)
                print(json.dumps({'status':'active','checks':checks}))
            except Exception as exc:
                try:
                    # A newly active client must not be interrupted for rollback.
                    idle()
                    with workspace_guard():
                        run(['systemctl','stop',AGENT],90);restore(strict=False)
                    restart(False)
                    record('rolled_back',reason=str(exc)[:1200])
                except Exception as rollback:
                    record('rollback_requires_review',reason=str(exc)[:1200],rollback_error=str(rollback)[:1200])
                raise
        elif action=='--rollback':
            idle()
            with workspace_guard():
                # Validate conflicts before any service is stopped.
                for name,data in PAYLOAD.items():
                    if digest(BASE/name)!=sha(data):raise RuntimeError('rollback conflict: '+name)
                run(['systemctl','stop',AGENT],90);restore()
            restart(False);record('rolled_back',reason='approved rollback')
            print(json.dumps({'status':'rolled_back'}))
        else:raise ValueError('use --apply, --activate or --rollback')
    finally:os.close(lock)


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('one action required')
    main(sys.argv[1])
