#!/usr/bin/env python3
"""Hash-pinned local update of only the central personal-Mac agent: coordination v0.11 r1."""
import base64,contextlib,fcntl,hashlib,json,os,plistlib,re,stat,subprocess,sys,tempfile,time,zlib
from pathlib import Path
ROOT=Path('/Library/MCPAndreaMacMioV09')
BASE=ROOT/'code'
SELF=ROOT/'upgrade_coordination_v011r1_20261002.py'
BACKUP=ROOT/'backup/coordination_v011r1_20261002'
RECEIPT=ROOT/'coordination_v011r1_20261002_receipt.json'
TEST_CODE=ROOT/'preflight-coordination_v011r1_20261002'
TEST_DATA=Path('/Users/Shared/MCPAndreaMacMio/preflight-coordination_v011r1_20261002')
GUARD=ROOT/'state/operations/guard'
LABEL='it.andreababini.mcp-mac-mio-v09'
PLIST=Path('/Library/LaunchDaemons')/(LABEL+'.plist')
PLIST_SHA='c355532f913809d9a183e0e4b4a55e226dfc850914dbe4992582d5d3bf7fd406'
PYTHON='/usr/bin/python3'
OLD_VERSION='0.10-personal-search-1'
NEW_VERSION='0.11-personal-work-2'
PAYLOAD={}
TESTS={}
ORIGINAL={'mac_agent.py': 'a043138883eada66cbcc44e8d35b38a663efba67936a542ca89be8f086691a64', 'work_sessions.py': None, 'work_schema.py': None}
DEPENDENCIES={'file_tools.py': '8a830b3e4ed62fec5b28c5c600a616899c5b706547155d5ed3684a1d8309d54e', 'file_schema.py': '06e579c359835daa58876d7e5de21d26ad374992fb76d9104dd1d6dd929409eb', 'search_tools.py': 'ebc7358ce73cd449d452363943b4fa66cfc3d740858ade3efc0ee6132513235b', 'search_schema.py': 'c6d111d440eec78bb08e27673fd832479f02446ac2abc25fb5237e12d47ee20d', 'agent_shell.py': 'd62822814d97c52468ca8aad4a43fa1bf8e424b8cd8200ac88ea4e2c9c33e21c', 'shell_common.py': '254dd32f26295b9376b1201cf7449832b8d9927018d0b9e208cc2a950b954f3f', 'mac_guard.py': '8d3f7afe80daae81e8f3a3471229423d14777eb84358a3f57621e74149dc57bc', 'mac_clock.py': '6553b061c51e2da286296231538796dd086404b1dbacca37bd9299e2628dae07', 'mac_policy.py': 'ae04120908a35656258243d73fc30e7069077388a4e863cd815444b14f2e53e0', 'mac_child.py': '99416031aa2404ec2e49798ca2e33797cc492f19f15f92048bea382a9cf29856', 'mac_watchdog.py': '66dc9cbe74dd74931979200a9eda4032461a31c1687f5a2ca64a4441f21c4c99', 'mac_shell.py': 'fad744a688debf755e17b04257a3d3d2afb2ed492426b1d2332b9f8475a11d67'}
TEST_NAMES=['mac_agent.py', 'work_sessions.py', 'work_schema.py', 'file_tools.py', 'file_schema.py', 'search_tools.py', 'search_schema.py', 'agent_shell.py', 'shell_common.py', 'mac_guard.py', 'mac_clock.py', 'mac_policy.py', 'mac_child.py', 'mac_watchdog.py', 'mac_shell.py', 'test_work_core.py', 'test_search.py', 'mac_coordination_selftest.py', 'cg_tools.py']
SOURCE_SHA={'mac_agent.py': 'f099f621d41b17f834105393c3161cc5428681f8ddf22b07dcdafb542e6d0104', 'work_sessions.py': '707604271f3570ec6f03a42e68c19430200623cfad341691fef620522b0f0f67', 'work_schema.py': '9204940d1c304ca41236785b2248c449a93f8102fcd1e15fae4d76c478db9ee9', 'test_work_core.py': '7113af7fd7db7df411a02c99f23f59cf76100b26ec661554d1abe94cb02fa45f', 'test_search.py': 'f613d49223e3c5ce250c50cbae9efe5462f31c2a5f0102fac09874acb68ae988', 'mac_coordination_selftest.py': '9c8e9cc6fe845d05a2ac589b38eee3ba98e22c0d74dc1c893184647705303553', 'cg_tools.py': '8282e608be40003e9475dc789ddf7d90e8676aa88776d9f8b3923b33087d02a1'}
SOURCES={
'mac_agent.py': r'''#!/usr/bin/env python3
"""Dedicated non-admin agent; root-owned code, private state, offline shell."""
import asyncio
import contextlib
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import stat
import subprocess
import sys
import time

CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / 'vendor'))
from file_tools import FileTools
from file_schema import FILE_NAMES
from search_tools import SearchTools, SEARCH_NAMES
from agent_shell import AgentShell
from work_sessions import WorkSessions, MUTATIONS
from work_schema import WORK_NAMES
from mac_guard import require_identity, stop_dedicated_children
from mac_policy import profile

BASE = Path('/Library/MCPAndreaMacMioV09')
STATE = BASE / 'state'
WORK = Path('/Users/Shared/MCPAndreaMacMio/workspace')
URL = 'wss://mcp.andreababini.it/agent/ws/mac_mio'
VERSION = '0.11-personal-work-2'
LOG = logging.getLogger('mcp-andrea-mac-mio')
RID = re.compile(r'[a-f0-9]{32}')
CALLER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}')
COMMANDS = {'sw_vers': ('/usr/bin/sw_vers',)}


def baseline_argv(command, work):
    return ['/usr/bin/sandbox-exec','-p',profile(str(work))]+list(COMMANDS[command])


async def status_output(proc, timeout=15):
    task=asyncio.create_task(proc.communicate())
    timed_out=False
    try:
        output,_=await asyncio.wait_for(asyncio.shield(task),timeout)
    except asyncio.TimeoutError:
        timed_out=True
        with contextlib.suppress(ProcessLookupError):os.killpg(proc.pid,signal.SIGKILL)
        output,_=await asyncio.wait_for(task,3)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):os.killpg(proc.pid,signal.SIGKILL)
        with contextlib.suppress(Exception,asyncio.CancelledError):await asyncio.wait_for(task,3)
        raise
    return {'exit_code':proc.returncode,'output':output[-65536:].decode(errors='replace'),
            'truncated':len(output)>65536,'timed_out':timed_out}


def trusted_token():
    path = BASE / 'private/agent.token'
    for p in [path.parent] + list(path.parent.parents):
        s = p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise PermissionError('unsafe credential directory')
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r') as f:
        s = os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_gid != 5000 or s.st_mode & 0o137 or s.st_nlink != 1:
            raise PermissionError('unsafe credential file')
        token = f.read(257).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{43,256}', token):
        raise ValueError('invalid agent credential')
    return token


class Dispatcher:
    def __init__(self, work=WORK, state=STATE):
        self.work, self.state = Path(work), Path(state)
        self.files = FileTools([str(self.work)], str(self.state / 'operations'))
        self.shell = AgentShell(self.files, str(self.work), str(self.state / 'shell-logs'), capable=True)
        self.logs = FileTools([str(self.state / 'shell-logs')], str(self.state / 'log-reader'), max_file_bytes=16*1024*1024)
        self.search = SearchTools(self.files)
        self.recent = []
        self.work_sessions = WorkSessions(str(self.state / 'work-sessions'), self.files)
        self.files.lock_provider = self.work_sessions.lock_provider
        self.work_watchdog = None

    def file_call(self, op, args, identity):
        self.search.guard_mutation(op)
        path = args.get('path')
        log_root = str(self.state / 'shell-logs')
        is_log = isinstance(path, str) and (path == log_root or path.startswith(log_root + '/'))
        engine = self.logs if is_log else self.files
        if is_log and op not in ('read_file', 'get_file_info', 'list_directory'):
            raise PermissionError('shell logs are read-only')
        if op == 'read_file' and not ({'offset', 'length'} & set(args)):
            if set(args) - {'path', 'max_bytes'}:
                raise ValueError('unexpected read arguments')
            limit = args.get('max_bytes', 262144)
            if type(limit) is not int or not 1 <= limit <= 1048576:
                raise ValueError('invalid read size')
            data, _ = engine._read(path); engine._text(data)
            return {'path': path, 'content': data[:limit].decode('utf-8', errors='replace'),
                    'bytes_returned': min(len(data), limit), 'truncated': len(data) > limit}
        return engine.dispatch(op, args, identity)

    async def baseline(self, args):
        if set(args) - {'command', 'cwd', 'timeout'} or args.get('command') not in COMMANDS:
            raise ValueError('invalid baseline arguments')
        if args.get('cwd') not in (None, str(self.work)):
            raise ValueError('invalid status cwd')
        if self.shell.working()['active_locks']:
            raise PermissionError('use the active shell session before running a separate status command')
        proc = await asyncio.create_subprocess_exec(*baseline_argv(args['command'],self.work),
            stdin=subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            cwd=str(self.work), start_new_session=True,
            env={'PATH': '/usr/bin:/bin', 'HOME': str(self.work), 'CFFIXED_USER_HOME':str(self.work),
                 'TMPDIR': str(self.work / '.tmp')})
        return await status_output(proc)

    async def reap_expired_work(self):
        # The request loop is serialized. Reap BEFORE accepting a new work lock,
        # so an expired shell cannot race a new owner of the same workspace.
        if self.shell.owner:
            try:
                remaining = self.work_sessions.remaining(self.shell.owner, str(self.work))
            except PermissionError:
                remaining = 0
            if remaining <= 0:
                await self.shell.disable()
        active = {x['work_session_id'] for x in self.work_sessions.snapshot()['work_sessions']}
        for job in list(self.search.jobs.values()):
            if job['status'] == 'running' and job['owner'].startswith('work:') and job['owner'][5:] not in active:
                await self.search.stop(job['owner'], job['id'])

    async def watch_work(self):
        try:
            while True:
                await asyncio.sleep(.5)
                await self.reap_expired_work()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A corrupt/unavailable coordination store must not leave a shell
            # running under a lease that can no longer be verified.
            await self.shell.disable()
            await self.search.close()
            LOG.exception('work coordination watchdog failed')

    async def work_call(self, op, args, caller):
        a = dict(args)
        action = a.pop('action', None)
        sid = a.pop('work_session_id', None)
        token = a.pop('work_session_token', None)
        if op == 'work_session' and action == 'open':
            if sid is not None or token is not None or set(a) - {'label','minutes'}:
                raise ValueError('unexpected session open arguments')
            return self.work_sessions.open(caller, a.get('label'), a.get('minutes',30))
        identity = self.work_sessions.authenticate(caller, sid, token)
        if op == 'work_session' and action == 'renew':
            if set(a) - {'minutes'}:raise ValueError('unexpected session renew arguments')
            return self.work_sessions.renew(caller,sid,token,a.get('minutes',30))
        if op == 'work_session' and action == 'close' and not a:
            if self.shell.owner == identity:await self.shell.disable()
            for job in list(self.search.jobs.values()):
                if job['owner'] == identity and job['status'] == 'running':
                    await self.search.stop(identity,job['id'])
            return self.work_sessions.end(caller,sid,token)
        if op == 'work_lock' and action == 'acquire':
            if set(a)-{'path','minutes'}:raise ValueError('unexpected lock arguments')
            return self.work_sessions.acquire(caller,sid,token,a.get('path'),a.get('minutes',30))
        if op == 'work_lock' and action in ('renew','release'):
            if set(a)-{'lock_id','minutes'} or action=='release' and 'minutes' in a:
                raise ValueError('unexpected lock arguments')
            if action=='release' and self.shell.owner==identity:
                raise PermissionError('disable the session shell before releasing its work lock')
            return self.work_sessions.change_lock(caller,sid,token,a.get('lock_id'),
                                                 a.get('minutes',30) if action=='renew' else None)
        raise ValueError('unsupported work action')

    async def dispatch(self, message):
        if not isinstance(message, dict) or message.get('type') != 'request':
            raise ValueError('invalid request')
        caller, rid = message.get('caller'), message.get('id')
        if not isinstance(caller, str) or not CALLER.fullmatch(caller) or not isinstance(rid, str) or not RID.fullmatch(rid):
            raise PermissionError('authenticated caller and request id required')
        op, args = message.get('op'), message.get('args')
        if not isinstance(args, dict):raise ValueError('arguments must be an object')
        if self.work_watchdog is None or self.work_watchdog.done():
            self.work_watchdog = asyncio.create_task(self.watch_work())
        await self.reap_expired_work()
        args = dict(args)
        work_id = args.get('work_session_id')
        work_token = args.get('work_session_token')
        identity = caller
        ok = False
        try:
            if op not in WORK_NAMES:
                args.pop('work_session_id',None);args.pop('work_session_token',None)
                required = op in MUTATIONS | SEARCH_NAMES | {'enable_full_shell','disable_full_shell','shell_session'} or op=='shell_exec' and args.get('command') not in COMMANDS
                if required or work_id is not None or work_token is not None:
                    identity = self.work_sessions.authenticate(caller,work_id,work_token)
            if op in WORK_NAMES:
                result = await self.work_call(op,args,caller)
            elif op in SEARCH_NAMES:
                result = await self.search.dispatch(op, args, identity)
            elif op in FILE_NAMES:
                result = self.file_call(op, args, identity)
            elif op == 'enable_full_shell':
                if set(args) != {'minutes'}:raise ValueError('unexpected enable arguments')
                if args['minutes']*60 > self.work_sessions.remaining(identity,str(self.work)):
                    raise PermissionError('work session and workspace lock must outlast the shell lease')
                result = await self.shell.enable(identity, args['minutes'])
            elif op == 'disable_full_shell' and not args:
                if self.shell.owner is not None and self.shell.owner != identity:
                    raise PermissionError('shell lease belongs to another work session')
                result = await self.shell.disable()
            elif op == 'shell_exec':
                if set(args) - {'command','cwd','timeout'}:raise ValueError('unexpected shell arguments')
                if args.get('command') in COMMANDS:
                    result = await self.baseline(args)
                else:
                    self.work_sessions.remaining(identity,str(self.work))
                    result = await self.shell.execute(identity, args)
            elif op == 'shell_session':
                if set(args) - {'action','command','cwd','data','session_id'}:raise ValueError('unexpected session arguments')
                if args.get('action') == 'start':
                    self.work_sessions.remaining(identity,str(self.work))
                result = await self.shell.session(identity, args)
            elif op == 'who_is_working' and not args:
                result = {**self.shell.working(), 'recent_operations': self.recent[-20:], 'search_version': '0.10.1'}
                result['active_locks'] += self.search.active()
                result.update(self.work_sessions.snapshot())
            else:raise ValueError('unsupported operation')
            ok = True; return result
        finally:
            record = {'time': time.time(), 'caller': caller, 'work_session_id': work_id, 'request_id': rid, 'operation': op, 'ok': ok}
            if op in ('shell_exec', 'shell_session') and isinstance(args.get('command'), str):
                record['command'] = args['command'][:32768]
            LOG.info(json.dumps(record, ensure_ascii=True))
            self.recent.append({k:v for k,v in record.items() if k != 'command'})
            del self.recent[:-100]
            try:self.work_sessions.audit(identity,op,ok,rid)
            except Exception:LOG.exception('work audit failed request_id=%s',rid)

    async def close(self):
        if self.work_watchdog:
            self.work_watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):await self.work_watchdog
        await self.search.close(); await self.shell.disable()
        self.work_sessions.close(); self.files.close(); self.logs.close()


def metadata():
    return {'hostname': socket.gethostname(), 'platform': 'darwin', 'python': sys.version.split()[0],
            'uid': os.getuid(), 'machine': 'mac_mio', 'agent_version': VERSION,
            'full_shell_capable': True, 'file_tools_version': '0.7', 'search_version': '0.10.1',
            'shell_backend': 'seatbelt-v09', 'shell_network': 'disabled', 'shell_scope': str(WORK),
            'allowed_roots': [str(WORK)], 'read_only_log_root': str(STATE / 'shell-logs'),
            'coordination_version':'0.11.0', 'work_session_required':True,
            'capabilities': sorted(FILE_NAMES | SEARCH_NAMES | WORK_NAMES | {'shell_exec','shell_session','enable_full_shell','disable_full_shell','who_is_working'}),
            'baseline_shell_commands': sorted(COMMANDS), 'reconnect': 'automatic; shell revoked on disconnect'}


def connected_receipt(connected=True):
    value = {'pid': os.getpid(), 'uid': os.getuid(), 'time': time.time(), 'version': VERSION, 'connected': connected}
    path = STATE / 'connected.json'
    temp = STATE / ('connected-' + str(os.getpid()) + '.tmp')
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:json.dump(value, f); f.flush(); os.fsync(f.fileno())
    os.replace(str(temp), str(path))


async def end_connection(heartbeat, dispatcher):
    heartbeat.cancel()
    try:
        with contextlib.suppress(asyncio.CancelledError, Exception):await heartbeat
    finally:
        try:
            await dispatcher.search.close()
            await dispatcher.shell.disable()
        finally:connected_receipt(False)


async def connection(dispatcher):
    from websockets.legacy.client import connect, WebSocketClientProtocol
    from websockets.exceptions import RedirectHandshake
    class NoRedirect(WebSocketClientProtocol):
        async def handshake(self, *args, **kwargs):
            try:return await super().handshake(*args, **kwargs)
            except RedirectHandshake:raise RuntimeError('redirect rejected') from None
    async with connect(URL, extra_headers={'Authorization': 'Bearer ' + trusted_token()},
                       ssl=ssl.create_default_context(), create_protocol=NoRedirect,
                       open_timeout=15, close_timeout=5, ping_interval=20, ping_timeout=20,
                       max_size=2*1024*1024, max_queue=8, compression=None) as ws:
        await ws.send(json.dumps({'type':'hello','meta':metadata()}))
        connected_receipt()
        async def beat():
            while True:
                await asyncio.sleep(15)
                await ws.send(json.dumps({'type':'hello','meta':metadata()}))
        heartbeat=asyncio.create_task(beat())
        try:
            async for raw in ws:
                rid=None
                try:
                    msg=json.loads(raw); rid=msg.get('id') if isinstance(msg,dict) else None
                    if not isinstance(rid,str) or not RID.fullmatch(rid):raise ValueError('request id required')
                    value=await dispatcher.dispatch(msg)
                    reply={'type':'result','id':rid,'ok':True,'result':value}
                except Exception as exc:
                    if not isinstance(rid,str) or not RID.fullmatch(rid):continue
                    reply={'type':'result','id':rid,'ok':False,'error':type(exc).__name__+': '+str(exc)[:300]}
                await ws.send(json.dumps(reply))
        finally:
            await end_connection(heartbeat, dispatcher)


async def run():
    dispatcher=Dispatcher()
    try:
        while True:
            try:await connection(dispatcher)
            except asyncio.CancelledError:raise
            except Exception as exc:LOG.warning('connection ended category=%s',type(exc).__name__)
            await asyncio.sleep(5)
    finally:await dispatcher.close()


def main():
    require_identity(); os.umask(0o077)
    fd=os.open(str(STATE/'agent.lock'),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    stop_dedicated_children()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s',handlers=[
        RotatingFileHandler(STATE/'audit.log',maxBytes=2*1024*1024,backupCount=4)])
    loop=asyncio.new_event_loop();asyncio.set_event_loop(loop)
    task=loop.create_task(run())
    for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,task.cancel)
    try:
        with contextlib.suppress(asyncio.CancelledError):loop.run_until_complete(task)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens());loop.close();os.close(fd)


if __name__=='__main__':main()
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
MUTATIONS = {'write_file', 'edit_block', 'create_directory', 'move_file', 'rollback_file'}


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
          'enable_full_shell','disable_full_shell','start_search','get_more_search_results','stop_search'}


def install_schema(tools):
    result = copy.deepcopy([t for t in tools if t['name'] not in WORK_NAMES])
    for t in result:
        if t['name'] in SCOPED:
            t['inputSchema']['properties'].update(copy.deepcopy(AUTH))
            t['description'] += ' If the selected machine advertises coordination_version, supply work_session_id and work_session_token for writes, searches and shell operations. Read-only calls remain available without them.'
    return result + copy.deepcopy(WORK_TOOLS)
''',
'test_work_core.py': r'''"""Necessary isolation, persistence and dispatcher regression checks."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from file_tools import FileTools, FileToolError
from work_sessions import WorkSessions
from mac_agent import Dispatcher
from work_schema import install_schema, WORK_NAMES


class SessionCore(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.work=self.root/'work';self.work.mkdir(mode=0o700)
        self.f=FileTools([str(self.work)],str(self.root/'journal'))
        self.wall=1000.;self.tick=200.
        self.w=WorkSessions(str(self.root/'sessions'),self.f,wall=lambda:self.wall,clock=lambda:self.tick,boot='boot1')
        self.f.lock_provider=self.w.lock_provider
        self.a=self.w.open('test:client','chat A',10)
        self.b=self.w.open('test:client','chat B',10)
    def test_read_only_transaction_does_not_rewrite_state(self):
        st=self.root/'sessions'/'state.json';before=os.stat(st)
        self.w.snapshot();self.ident(self.a)
        after=os.stat(st)
        self.assertEqual((before.st_ino,before.st_mtime_ns),(after.st_ino,after.st_mtime_ns))
        self.tick+=601;self.w.snapshot()
        self.assertNotEqual(before.st_ino,os.stat(st).st_ino)
    def tearDown(self):
        self.w.close();self.f.close();self.tmp.cleanup()
    def auth(self,s):return ('test:client',s['work_session_id'],s['work_session_token'])
    def ident(self,s):return self.w.authenticate(*self.auth(s))
    def lock(self,s,path=None,minutes=5):return self.w.acquire(*self.auth(s),str(path or self.work),minutes)
    def test_same_oauth_distinct_sessions_cannot_impersonate(self):
        with self.assertRaises(PermissionError):
            self.w.authenticate('test:client',self.a['work_session_id'],self.b['work_session_token'])
        with self.assertRaises(PermissionError):
            self.w.authenticate('test:other',self.a['work_session_id'],self.a['work_session_token'])
    def test_prefix_overlap_and_component_boundary(self):
        self.lock(self.a,self.work/'app')
        for p in [self.work,self.work/'app',self.work/'app'/'file']:
            with self.assertRaises(PermissionError):self.lock(self.b,p)
        self.lock(self.b,self.work/'apple')
    def test_case_and_unicode_alias_overlap(self):
        self.lock(self.a,self.work/('Caf'+chr(0xe9)))
        with self.assertRaises(PermissionError):self.lock(self.b,self.work/('CAFE'+chr(0x301))/'x')
    def test_write_requires_lock_and_rollback_is_protected(self):
        p=str(self.work/'a')
        with self.assertRaises(PermissionError):self.f.write_file(p,'bad',session_id=self.ident(self.a))
        self.lock(self.a)
        r=self.f.write_file(p,'good',session_id=self.ident(self.a))
        with self.assertRaises(PermissionError):self.f.rollback_file(r['operation_id'],session_id=self.ident(self.b))
        self.f.rollback_file(r['operation_id'],session_id=self.ident(self.a))
        self.assertFalse(Path(p).exists())
    def test_move_checks_both_paths_and_reentrant_provider(self):
        (self.work/'a').write_text('content')
        self.lock(self.a,self.work/'a');self.lock(self.b,self.work/'b')
        with self.assertRaises(PermissionError):self.f.move_file(str(self.work/'a'),str(self.work/'b'),session_id=self.ident(self.a))
        self.w.end(*self.auth(self.b));self.lock(self.a,self.work/'b')
        self.f.move_file(str(self.work/'a'),str(self.work/'b'),session_id=self.ident(self.a))
        self.assertEqual((self.work/'b').read_text(),'content')
    def test_restart_preserves_lock_and_no_plain_tokens(self):
        self.lock(self.a);self.w.close()
        self.w=WorkSessions(str(self.root/'sessions'),self.f,wall=lambda:self.wall,clock=lambda:self.tick,boot='boot1')
        with self.assertRaises(PermissionError):self.lock(self.b)
        self.assertTrue(self.ident(self.a).startswith('work:'))
        state=(self.root/'sessions'/'state.json').read_text()
        for s in [self.a,self.b]:self.assertNotIn(s['work_session_token'],state+json.dumps(self.w.snapshot()))
    def test_lock_expiry_and_clock_rollback(self):
        self.lock(self.a,minutes=1)
        self.wall-=100;self.tick+=61
        self.lock(self.b)
        with self.assertRaises(PermissionError):self.w.remaining(self.ident(self.a),str(self.work))
    def test_session_expiry_and_reboot(self):
        self.lock(self.a);self.tick+=601
        with self.assertRaises(PermissionError):self.ident(self.a)
        self.assertFalse(self.w.snapshot()['work_locks'])
        c=self.w.open('test:client','new',10);self.lock(c)
        self.w.close();self.w=WorkSessions(str(self.root/'sessions'),self.f,wall=lambda:self.wall,clock=lambda:self.tick,boot='boot2')
        self.assertFalse(self.w.snapshot()['work_locks'])
        with self.assertRaises(PermissionError):self.ident(c)
    def test_outside_and_symlink_locks_refused(self):
        with self.assertRaises(FileToolError):self.lock(self.a,self.root/'outside')
        (self.work/'link').symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(PermissionError):self.lock(self.a,self.work/'link'/'a')
    def test_foreign_lock_release_refused_and_renew_bounded(self):
        l=self.lock(self.a,minutes=1)
        with self.assertRaises(PermissionError):self.w.change_lock(*self.auth(self.b),l['lock_id'])
        r=self.w.change_lock(*self.auth(self.a),l['lock_id'],240)
        self.assertEqual(r['expires_at'],self.a['expires_at'])
    def test_corrupt_store_and_symlink_fail_closed(self):
        p=self.root/'sessions'/'state.json';p.write_text('{}')
        with self.assertRaises(RuntimeError):self.w.snapshot()
        p.unlink();p.symlink_to(self.root/'outside')
        with self.assertRaises(OSError):self.w.snapshot()


class AgentCore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();r=Path(self.tmp.name)
        self.work=r/'work';self.state=r/'state'
        self.work.mkdir(mode=0o700);self.state.mkdir(mode=0o700)
        self.d=Dispatcher(self.work,self.state)
        self.a=await self.call('work_session',{'action':'open','label':'chat A','minutes':10})
        self.b=await self.call('work_session',{'action':'open','label':'chat B','minutes':10})
    async def asyncTearDown(self):
        await self.d.close();self.tmp.cleanup()
    async def call(self,op,args,s=None):
        if s:args={**args,**{k:s[k] for k in ['work_session_id','work_session_token']}}
        return await self.d.dispatch({'type':'request','id':uuid.uuid4().hex,'caller':'test:client','op':op,'args':args})
    async def lock(self,s):return await self.call('work_lock',{'action':'acquire','path':str(self.work),'minutes':10},s)
    async def test_authenticated_write_read_rollback_and_legacy_write_refused(self):
        p=str(self.work/'file')
        with self.assertRaises(PermissionError):await self.call('write_file',{'path':p,'content':'bad'})
        await self.lock(self.a)
        r=await self.call('write_file',{'path':p,'content':'good'},self.a)
        self.assertEqual((await self.call('read_file',{'path':p}))['content'],'good')
        with self.assertRaises(PermissionError):await self.call('write_file',{'path':p,'content':'other'},self.b)
        await self.call('rollback_file',{'operation_id':r['operation_id']},self.a)
        self.assertFalse(Path(p).exists())
    async def test_search_results_private_between_same_oauth_chats(self):
        (self.work/'f').write_text('needle')
        r=await self.call('start_search',{'path':str(self.work),'pattern':'needle'},self.a)
        await self.d.search.jobs[r['search_id']]['task']
        with self.assertRaises(PermissionError):await self.call('get_more_search_results',{'search_id':r['search_id']},self.b)
        self.assertEqual((await self.call('get_more_search_results',{'search_id':r['search_id']},self.a))['total_results'],1)
    async def test_shell_requires_whole_workspace_lock_and_separate_identity(self):
        with self.assertRaises(PermissionError):await self.call('enable_full_shell',{'minutes':1},self.a)
        await self.lock(self.a)
        with patch.object(self.d.shell,'enable',new=AsyncMock(return_value={'enabled':True})) as m:
            await self.call('enable_full_shell',{'minutes':1},self.a)
            m.assert_awaited_once_with('work:'+self.a['work_session_id'],1)
        with self.assertRaises(PermissionError):await self.call('enable_full_shell',{'minutes':11},self.a)
    async def test_foreign_disable_refused_close_revokes_own_shell(self):
        await self.lock(self.a);identity='work:'+self.a['work_session_id']
        self.d.shell.owner=identity;self.d.shell.until=__import__('time').monotonic()+60
        with self.assertRaises(PermissionError):await self.call('disable_full_shell',{},self.b)
        with patch.object(self.d.shell,'disable',new=AsyncMock()) as m:
            await self.call('work_session',{'action':'close'},self.a)
            m.assert_awaited_once_with()
        self.d.shell.owner=None
        self.assertFalse((await self.call('who_is_working',{}))['work_locks'])
    async def test_expiry_reaps_before_accepting_new_lock(self):
        await self.lock(self.a);identity='work:'+self.a['work_session_id']
        self.d.shell.owner=identity;self.d.shell.until=__import__('time').monotonic()+60
        with self.d.work_sessions.transaction() as d:
            d['sessions'][self.a['work_session_id']]['deadline']=0
        async def disable():self.d.shell.owner=None
        with patch.object(self.d.shell,'disable',new=AsyncMock(side_effect=disable)) as m:
            await self.lock(self.b)
            m.assert_awaited_once_with()
    async def test_durable_audit_contains_session_id_not_secret(self):
        await self.lock(self.a)
        await self.call('write_file',{'path':str(self.work/'x'),'content':'x'},self.a)
        state=await self.call('who_is_working',{})
        self.assertTrue(any(x['work_session_id']==self.a['work_session_id'] and x['operation']=='write_file' for x in state['recent_work_operations']))
        self.assertNotIn(self.a['work_session_token'],json.dumps(state))
    async def test_audit_failure_does_not_mask_result(self):
        await self.lock(self.a)
        with patch.object(self.d.work_sessions,'audit',side_effect=BlockingIOError()):
            r=await self.call('write_file',{'path':str(self.work/'y'),'content':'y'},self.a)
        self.assertIn('operation_id',r)
    async def test_close_cancels_search_and_releases_locks(self):
        await self.lock(self.a)
        r=await self.call('start_search',{'path':str(self.work),'pattern':'x'},self.a)
        await self.call('work_session',{'action':'close'},self.a)
        self.assertFalse(self.d.search.jobs[r['search_id']]['status']=='running')
        await self.lock(self.b)


class Schema(unittest.TestCase):
    def test_schema_additive_and_idempotent(self):
        original=[{'name':'shell_session','description':'terminal','inputSchema':{'type':'object','properties':{'session_id':{'type':'string'}}}}]
        result=install_schema(original)
        self.assertEqual(len({x['name'] for x in result}),len(result))
        self.assertTrue(WORK_NAMES.issubset({x['name'] for x in result}))
        self.assertNotIn('work_session_id',original[0]['inputSchema']['properties'])
        self.assertIn('session_id',result[0]['inputSchema']['properties'])
        self.assertIn('work_session_id',result[0]['inputSchema']['properties'])

if __name__=='__main__':unittest.main()
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
        self.assertEqual(len(TOOLS),len(NAMES));self.assertEqual(len(TOOLS),25)
        self.assertTrue({'work_session','work_lock'} <= NAMES)
        self.assertTrue({'start_search','get_more_search_results','stop_search'}<=NAMES)
        for t in TOOLS:
            m=t['inputSchema']['properties'].get('machine',{})
            if 'enum' in m:self.assertEqual(set(m['enum']),{'vps','mac_noleggio','mac_mio'})


if __name__=='__main__':unittest.main(verbosity=2)
''',
'mac_coordination_selftest.py': r'''"""UID5000 coordination smoke test, only while the central Mac daemon is stopped."""
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid
sys.path.insert(0,'/Library/MCPAndreaMacMioV09/code')
from mac_agent import Dispatcher, WORK
from mac_guard import require_identity


async def main():
    require_identity();d=Dispatcher();operations=[];checks=[];sessions=[]
    caller='deployment:coordination-v011'
    async def call(op,s=None,**args):
        if s:args.update(work_session_id=s['work_session_id'],work_session_token=s['work_session_token'])
        return await d.dispatch({'type':'request','id':uuid.uuid4().hex,'caller':caller,'op':op,'args':args})
    async def refused(op,s=None,**args):
        try:await call(op,s,**args)
        except PermissionError:return
        raise AssertionError(op+' was not refused')
    folder=str(WORK/('coordination_selftest_'+uuid.uuid4().hex))
    try:
        a=await call('work_session',action='open',label='selftest A',minutes=5);sessions.append(a)
        b=await call('work_session',action='open',label='selftest B',minutes=5);sessions.append(b)
        await refused('create_directory',a,path=folder)
        await refused('create_directory',path=folder)
        checks.append('writes need session and lock')
        lock=await call('work_lock',a,action='acquire',path=folder,minutes=5)
        await refused('work_lock',b,action='acquire',path=folder+'/x',minutes=5)
        checks.append('descendant conflict between sessions')
        operations.append((await call('create_directory',a,path=folder))['operation_id'])
        path=folder+'/prova.txt'
        operations.append((await call('write_file',a,path=path,content='MCP_COORD_MAC_OK\n'))['operation_id'])
        await refused('write_file',b,path=path,content='other')
        await refused('rollback_file',b,operation_id=operations[-1])
        checks.append('foreign write and rollback refused')
        r=await call('start_search',a,path=folder,pattern='MCP_COORD_MAC_OK')
        await asyncio.wait_for(d.search.jobs[r['search_id']]['task'],5)
        await refused('get_more_search_results',b,search_id=r['search_id'])
        assert (await call('get_more_search_results',a,search_id=r['search_id']))['total_results']==1
        checks.append('search private to its session')
        state=await call('who_is_working')
        assert any(l['lock_id']==lock['lock_id'] for l in state['work_locks']),state
        assert a['work_session_token'] not in json.dumps(state),'token leaked'
        checks.append('who_is_working lists lock without tokens')
        r=await call('shell_exec',command='sw_vers')
        assert r['exit_code']==0 and not r['timed_out'],r
        checks.append('baseline sw_vers without session')
    finally:
        await d.search.close()
        for operation in reversed(operations):await call('rollback_file',sessions[0],operation_id=operation)
        for s in sessions:await call('work_session',s,action='close')
        state=await call('who_is_working')
        await d.close()
    assert not state['work_sessions'] and not state['work_locks'] and not state['shell_enabled'],state
    assert not Path(folder).exists()
    checks.append('sessions closed, locks released, test files rolled back')
    print(json.dumps({'passed':True,'uid':os.getuid(),'checks':checks}))


if __name__=='__main__':asyncio.run(main())
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
    fd,name=tempfile.mkstemp(prefix='.search-v010-',dir=str(path.parent))
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

def verify_restore(strict=True):
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
    return manifest


def restore(strict=True):
    manifest=verify_restore(strict)
    for name,meta in manifest.items():
        if meta is None:
            if (BASE/name).exists():(BASE/name).unlink()
        else:atomic(BASE/name,read(BACKUP/name),meta['mode'],meta['uid'],meta['gid'])

"""Appended to the root-pinned Mac search installer by build_mac_installer.py."""


def identity():
    if sys.platform!='darwin':raise RuntimeError('macOS required')
    if run(['/usr/bin/id','-u','mcp_andrea']).stdout.strip()!='5000':raise RuntimeError('wrong dedicated UID')
    if run(['/usr/bin/id','-g','mcp_andrea']).stdout.strip()!='5000':raise RuntimeError('wrong dedicated GID')
    if {'0','80'} & set(run(['/usr/bin/id','-G','mcp_andrea']).stdout.split()):raise RuntimeError('dedicated account is an administrator')
    if sha(read(PLIST))!=PLIST_SHA:raise RuntimeError('daemon configuration changed')
    plist=plistlib.loads(read(PLIST))
    if plist.get('UserName')!='mcp_andrea' or plist.get('GroupName')!='mcp_andrea':raise RuntimeError('wrong daemon account')


def active_pid():
    text=run(['/bin/launchctl','print','system/'+LABEL]).stdout
    match=re.search(r'\bpid = (\d+)\b',text)
    if not match:raise RuntimeError('daemon has no running PID')
    pid=int(match.group(1))
    uid=run(['/bin/ps','-o','uid=','-p',str(pid)]).stdout.strip()
    if uid!='5000':raise RuntimeError('daemon PID has wrong UID')
    return pid


def no_other_processes(daemon_pid=None):
    text=run(['/bin/ps','-axo','uid=,pid=,ppid=,stat=,args=']).stdout
    pids=set()
    for row in text.splitlines():
        p=row.split(None,4)
        if len(p)<4 or p[0]!='5000' or p[3].startswith('Z'):continue
        # macOS starts this per-user notification agent on demand from launchd.
        if p[2]=='1' and len(p)==5 and p[4].strip()=='/usr/sbin/distnoted agent':continue
        pids.add(int(p[1]))
    if pids!=(set() if daemon_pid is None else {daemon_pid}):raise RuntimeError('dedicated account busy')


def service_state():
    result=subprocess.run(['/bin/launchctl','print','system/'+LABEL],
        capture_output=True,text=True,timeout=10,
        env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C.UTF-8'})
    if result.returncode==0:
        match=re.search(r'\bpid = (\d+)\b',result.stdout)
        return {'loaded':True,'pid':int(match.group(1)) if match else None}
    if result.returncode==113 and 'Could not find service' in result.stderr:
        return {'loaded':False,'pid':None}
    raise RuntimeError('cannot inspect daemon: '+result.stderr[-400:])


def check_sources():
    identity();trusted_directory(BASE)
    for name,expected in {**ORIGINAL,**DEPENDENCIES}.items():
        if digest(BASE/name)!=expected:raise RuntimeError('live source changed: '+name)
    state=service_state()
    if state['pid'] is not None:
        if active_pid()!=state['pid']:raise RuntimeError('daemon changed during preflight')
    no_other_processes(state['pid'])
    return {'source_check_passed':True,'target':'mac_mio','new_version':NEW_VERSION,
            'daemon_loaded':state['loaded'],'administrative_preflight_pending':True,'rental_touched':False}


def load_package():
    global PAYLOAD,TESTS
    carried={n:src.encode() for n,src in SOURCES.items()}
    if {n:sha(b) for n,b in carried.items()}!=SOURCE_SHA:raise RuntimeError('unexpected embedded sources')
    PAYLOAD={n:carried[n] for n in ORIGINAL}
    # Unchanged dependencies come from the live, hash-pinned installation.
    TESTS={n:carried[n] if n in carried else read(BASE/n) for n in TEST_NAMES}
    for n,h in DEPENDENCIES.items():
        if sha(TESTS[n])!=h:raise RuntimeError('live dependency changed: '+n)
    for name,data in {**PAYLOAD,**TESTS}.items():compile(data,name,'exec')


def child(code,timeout=45):
    return subprocess.run([PYTHON,'-I','-B','-c',code],
        user=5000,group=5000,extra_groups=[5000],umask=0o077,cwd='/',close_fds=True,
        env={'PATH':'/usr/bin:/bin','HOME':'/var/empty','TMPDIR':str(TEST_DATA),'LANG':'en_US.UTF-8'},
        capture_output=True,text=True,timeout=timeout)


def preflight():
    for p in (TEST_CODE,TEST_DATA):
        if p.exists() or p.is_symlink():raise RuntimeError('preflight exists; inspect before retry')
    TEST_CODE.mkdir(mode=0o755);TEST_CODE.chmod(0o755)
    TEST_DATA.mkdir(mode=0o700);os.chown(str(TEST_DATA),5000,5000)
    for name,data in TESTS.items():atomic(TEST_CODE/name,data,0o444)
    for name in ORIGINAL:
        if TESTS.get(name)!=PAYLOAD[name]:raise RuntimeError('test and deployed module differ')
    for name,expected in DEPENDENCIES.items():
        if sha(TESTS[name])!=expected:raise RuntimeError('test dependency differs')
    code="import sys,unittest;sys.path.insert(0,"+repr(str(TEST_CODE))+");s=unittest.defaultTestLoader.loadTestsFromNames(['test_work_core','test_search']);r=unittest.TextTestRunner(verbosity=2).run(s);sys.exit(0 if r.wasSuccessful() else 1)"
    r=child(code)
    atomic(TEST_CODE/'result.log',(r.stdout+r.stderr).encode()[-65536:])
    if r.returncode:raise RuntimeError('UID5000 preflight failed: '+r.stderr[-1000:])


@contextlib.contextmanager
def workspace_guard():
    fd=os.open(str(GUARD),os.O_RDWR|os.O_NOFOLLOW)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=5000 or st.st_nlink!=1 or st.st_mode&0o077:
            raise RuntimeError('unsafe workspace guard')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:os.close(fd)


def stop_daemon():
    state=service_state()
    if state['pid'] is not None:
        if active_pid()!=state['pid']:raise RuntimeError('daemon changed before stop')
    no_other_processes(state['pid'])
    if state['loaded']:run(['/bin/launchctl','bootout','system/'+LABEL],30)
    # launchd removes the job asynchronously; wait for BOTH the job and its
    # processes. Never treat a failed status probe as proof of absence.
    end=time.monotonic()+20
    while time.monotonic()<end:
        state=service_state()
        if not state['loaded']:
            try:no_other_processes();return
            except RuntimeError:pass
        time.sleep(.2)
    raise RuntimeError('daemon or dedicated processes did not exit within 20 seconds')


def prepare_backup():
    if BACKUP.exists() or BACKUP.is_symlink():raise RuntimeError('backup exists; inspect before retry')
    return backup()


def start_daemon(expected_version):
    if service_state()['loaded']:raise RuntimeError('refusing to bootstrap an already loaded daemon')
    no_other_processes()
    started=time.time()
    run(['/bin/launchctl','bootstrap','system',str(PLIST)],30)
    for _ in range(60):
        try:
            ready=json.loads(read(ROOT/'state/connected.json',owner=5000))
            if ready.get('connected') is True and ready.get('version')==expected_version and ready.get('time',0)>=started and ready.get('uid')==5000:
                if ready.get('pid')==active_pid():return ready
        except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError):pass
        time.sleep(1)
    raise RuntimeError('gateway reconnect not verified')


def selftest():
    code="import runpy;runpy.run_path("+repr(str(TEST_CODE/'mac_coordination_selftest.py'))+",run_name='__main__')"
    r=child(code)
    atomic(TEST_CODE/'selftest.log',(r.stdout+r.stderr).encode()[-65536:])
    if r.returncode:raise RuntimeError('coordination smoke failed: '+r.stderr[-1000:])
    result=json.loads(r.stdout.strip())
    if result.get('passed') is not True or result.get('uid')!=5000:raise RuntimeError('invalid smoke receipt')
    no_other_processes()
    return result['checks']


def bootstrap(source):
    # The local launcher already verified the complete source hash in memory.
    trusted_directory(ROOT)
    if SELF.exists() or SELF.is_symlink():
        if read(SELF)!=source:raise RuntimeError('root helper already exists with different contents')
    else:atomic(SELF,source,0o555)
    os.execv(PYTHON,[PYTHON,'-I','-B',str(SELF),'--apply'])


def main(action):
    load_package()
    if action=='--check':print(json.dumps(check_sources(),indent=2));return
    if os.getuid()!=0 or os.geteuid()!=0:raise RuntimeError('local administrator approval required')
    source=globals().get('APPROVED_SOURCE')
    if source is not None:
        if not isinstance(source,bytes) or action!='--apply':raise RuntimeError('invalid bootstrap')
        bootstrap(source)
    if Path(__file__).resolve()!=SELF:raise RuntimeError('installed root helper required')
    trusted_directory(ROOT);read(SELF);identity();os.umask(0o077)
    fd=os.open('/var/run/mcp-andrea-shell-preflight.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_nlink!=1 or st.st_mode&0o077:raise RuntimeError('unsafe maintenance lock')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if action=='--apply':
            check_sources()
            try:preflight()
            except Exception as e:
                record('preflight_failed',reason=str(e)[:1200],live_modules_modified=False);raise
            check_sources()
            stopped=False;installed=False
            try:
                with workspace_guard():
                    check_sources();manifest=prepare_backup();stopped=True;stop_daemon()
                    for name,data in PAYLOAD.items():
                        meta=manifest[name] or {'mode':0o444,'uid':0,'gid':0}
                        atomic(BASE/name,data,meta['mode'],meta['uid'],meta['gid'])
                    installed=True
                checks=selftest();ready=start_daemon(NEW_VERSION);stopped=False
                record('active',version=NEW_VERSION,uid=5000,agent_pid=ready['pid'],checks=checks,
                       backup=str(BACKUP),hashes={n:sha(b) for n,b in PAYLOAD.items()},rental_touched=False)
                print(json.dumps({'status':'active','checks':checks,'uid':5000},indent=2))
            except Exception as error:
                try:
                    if installed and not stopped:
                        with workspace_guard():stop_daemon();stopped=True
                    if stopped:
                        # A failed bootstrap can leave a loaded daemon: stop only this label.
                        with workspace_guard():
                            stop_daemon()
                            restore(strict=False)
                        start_daemon(OLD_VERSION)
                    record('rolled_back',reason=str(error)[:1200])
                except Exception as rollback:
                    record('rollback_requires_review',reason=str(error)[:1200],rollback_error=str(rollback)[:1200])
                raise
        elif action=='--rollback':
            with workspace_guard():
                verify_restore()
                stop_daemon()
                try:restore()
                except Exception:
                    start_daemon(NEW_VERSION);raise
            try:
                ready=start_daemon(OLD_VERSION)
                record('rolled_back',agent_pid=ready['pid'],reason='local approved rollback')
                print(json.dumps({'status':'rolled_back'}))
            except Exception as e:
                record('rollback_requires_review',reason=str(e)[:1200]);raise
        else:raise ValueError('use --check, --apply or --rollback')
    finally:os.close(fd)


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('one action required')
    main(sys.argv[1])
