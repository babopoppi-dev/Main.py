#!/usr/bin/env python3
"""Hash-pinned local update of the personal-Mac agent to v0.12 and the Telegram admin helper."""
import base64,contextlib,fcntl,hashlib,json,os,plistlib,re,stat,subprocess,sys,tempfile,time,zlib
from pathlib import Path
ROOT=Path('/Library/MCPAndreaMacMioV09')
BASE=ROOT/'code'
SELF=ROOT/'upgrade_v012_20261003.py'
BACKUP=ROOT/'backup/v012_20261003'
RECEIPT=ROOT/'v012_20261003_receipt.json'
TEST_CODE=ROOT/'preflight-v012_20261003'
TEST_DATA=Path('/Users/Shared/MCPAndreaMacMio/preflight-v012_20261003')
GUARD=ROOT/'state/operations/guard'
LABEL='it.andreababini.mcp-mac-mio-v09'
PLIST=Path('/Library/LaunchDaemons')/(LABEL+'.plist')
PLIST_SHA='c355532f913809d9a183e0e4b4a55e226dfc850914dbe4992582d5d3bf7fd406'
PYTHON='/usr/bin/python3'
OLD_VERSION='0.11-personal-work-2'
NEW_VERSION='0.12-personal-admin-1'
PAYLOAD={}
TESTS={}
ORIGINAL={'mac_agent.py': 'f099f621d41b17f834105393c3161cc5428681f8ddf22b07dcdafb542e6d0104', 'admin_schema.py': None, 'mac_admin_client.py': None}
DEPENDENCIES={'file_tools.py': '8a830b3e4ed62fec5b28c5c600a616899c5b706547155d5ed3684a1d8309d54e', 'file_schema.py': '06e579c359835daa58876d7e5de21d26ad374992fb76d9104dd1d6dd929409eb', 'search_tools.py': 'ebc7358ce73cd449d452363943b4fa66cfc3d740858ade3efc0ee6132513235b', 'search_schema.py': 'c6d111d440eec78bb08e27673fd832479f02446ac2abc25fb5237e12d47ee20d', 'agent_shell.py': 'd62822814d97c52468ca8aad4a43fa1bf8e424b8cd8200ac88ea4e2c9c33e21c', 'shell_common.py': '254dd32f26295b9376b1201cf7449832b8d9927018d0b9e208cc2a950b954f3f', 'mac_guard.py': '8d3f7afe80daae81e8f3a3471229423d14777eb84358a3f57621e74149dc57bc', 'mac_clock.py': '6553b061c51e2da286296231538796dd086404b1dbacca37bd9299e2628dae07', 'mac_policy.py': 'ae04120908a35656258243d73fc30e7069077388a4e863cd815444b14f2e53e0', 'mac_child.py': '99416031aa2404ec2e49798ca2e33797cc492f19f15f92048bea382a9cf29856', 'mac_watchdog.py': '66dc9cbe74dd74931979200a9eda4032461a31c1687f5a2ca64a4441f21c4c99', 'mac_shell.py': 'fad744a688debf755e17b04257a3d3d2afb2ed492426b1d2332b9f8475a11d67', 'work_sessions.py': '707604271f3570ec6f03a42e68c19430200623cfad341691fef620522b0f0f67', 'work_schema.py': '9204940d1c304ca41236785b2248c449a93f8102fcd1e15fae4d76c478db9ee9'}
TEST_NAMES=['mac_agent.py', 'admin_schema.py', 'mac_admin_client.py', 'file_tools.py', 'file_schema.py', 'search_tools.py', 'search_schema.py', 'agent_shell.py', 'shell_common.py', 'mac_guard.py', 'mac_clock.py', 'mac_policy.py', 'mac_child.py', 'mac_watchdog.py', 'mac_shell.py', 'work_sessions.py', 'work_schema.py', 'test_work_core.py', 'test_search.py', 'test_mac_admin.py', 'mac_admin_helper.py', 'mac_coordination_selftest.py', 'cg_tools.py']
SOURCE_SHA={'mac_agent.py': 'be237fab0a3d23209f32e186a8bcc206ab878f67abb5638a8138c413f56c760a', 'admin_schema.py': 'a11e96523aa9571a3b64b4df9567d9b6d72f15fe6e4f09e39e2a19b4b13c5a03', 'mac_admin_client.py': '686e33d61c74dbd8c76485293c53d92ea8568297cf91ef44e79a13516d76f181', 'test_work_core.py': 'b5e4d90c7a443dbada567e46c16d6ac60b95292f28b0b74bc0295572a2303229', 'test_search.py': 'cef517cca93ceeb964c84e0c7b05a5cae737e5564c22cdf3e846bf443ae566f6', 'test_mac_admin.py': '6934256c817d50f9bca2aee4791467f8055d315a25472f8738c403e2f9bb76e2', 'mac_admin_helper.py': 'fcf391cf59ef593eec4869ac6a793360532f1f758fcafb213b3946f0b6ef5932', 'mac_coordination_selftest.py': '9c8e9cc6fe845d05a2ac589b38eee3ba98e22c0d74dc1c893184647705303553', 'cg_tools.py': 'ffcdafdef99731bcaecd903eacbf2c9bdfea26e0bd790e28b9a9b13493a924dc'}
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
from admin_schema import ADMIN_NAMES
from mac_admin_client import AdminClient
from mac_guard import require_identity, stop_dedicated_children
from mac_policy import profile

BASE = Path('/Library/MCPAndreaMacMioV09')
STATE = BASE / 'state'
WORK = Path('/Users/Shared/MCPAndreaMacMio/workspace')
URL = 'wss://mcp.andreababini.it/agent/ws/mac_mio'
VERSION = '0.12-personal-admin-1'
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
        self.admin = AdminClient()

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
                required = op in MUTATIONS | SEARCH_NAMES | {'enable_full_shell','disable_full_shell','shell_session','mac_admin_request'} or op=='shell_exec' and args.get('command') not in COMMANDS
                if required or work_id is not None or work_token is not None:
                    identity = self.work_sessions.authenticate(caller,work_id,work_token)
            if op in WORK_NAMES:
                # The durable audit names the authenticated session (or the one
                # just opened); unauthenticated attempts stay anonymous.
                if args.get('action') != 'open':
                    identity = self.work_sessions.authenticate(caller,work_id,work_token)
                result = await self.work_call(op,args,caller)
                if args.get('action') == 'open' and isinstance(result, dict) and RID.fullmatch(str(result.get('work_session_id'))):
                    identity = 'work:' + result['work_session_id']
            elif op == 'mac_admin_request':
                result = self.admin.request(caller, identity, args)
            elif op == 'mac_admin_result':
                result = self.admin.result(caller, args)
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
            'mac_admin_version':'0.12.0', 'mac_admin':'each root command approved individually on Telegram',
            'capabilities': sorted(FILE_NAMES | SEARCH_NAMES | WORK_NAMES | ADMIN_NAMES | {'shell_exec','shell_session','enable_full_shell','disable_full_shell','who_is_working'}),
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
'admin_schema.py': r'''"""Mac administration through Telegram: shared validation and gateway catalog entries.

The agent (UID 5000) only queues requests. A separate root helper with its own
Telegram bot shows the exact command to Andrea and runs it only after approval.
Nothing is pre-authorized.
"""
import re
import shlex

ADMIN_NAMES = {'mac_admin_request', 'mac_admin_result'}
CHARSET = re.compile(r'[A-Za-z0-9_./:=@%+, -]+')
MAX_COMMAND = 3000
MAX_REASON = 500
DEFAULT_TIMEOUT = 300
MAX_TIMEOUT = 900
EXPIRE_S = 600
AUTH = {'work_session_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'},
        'work_session_token': {'type': 'string', 'minLength': 43, 'maxLength': 43}}

ADMIN_TOOLS = [
    {'name': 'mac_admin_request',
     'description': 'Ask Andrea to run ONE administrator (root) command on his personal Mac. '
                    'The exact command is shown on Telegram by a separate Mac bot and runs only after '
                    'his approval (sensitive commands need a second confirmation); nothing is pre-authorized. '
                    'No shell: absolute program path, characters [A-Za-z0-9_./:=@%+, -] only, max 3000. '
                    'Requires an open work session. Returns request_id; poll mac_admin_result (expires in 10 min).',
     'inputSchema': {'type': 'object', 'additionalProperties': False,
                     'required': ['machine', 'command', 'reason', 'work_session_id', 'work_session_token'],
                     'properties': {'machine': {'type': 'string', 'enum': ['mac_mio']},
                                    'command': {'type': 'string', 'minLength': 1, 'maxLength': MAX_COMMAND},
                                    'reason': {'type': 'string', 'minLength': 1, 'maxLength': MAX_REASON},
                                    'timeout': {'type': 'integer', 'minimum': 1, 'maximum': MAX_TIMEOUT},
                                    **AUTH}}},
    {'name': 'mac_admin_result',
     'description': 'Status and output of a mac_admin_request (queued, waiting, done, rejected, expired, error). '
                    'Only the requesting authorization can read it.',
     'inputSchema': {'type': 'object', 'additionalProperties': False,
                     'required': ['machine', 'request_id'],
                     'properties': {'machine': {'type': 'string', 'enum': ['mac_mio']},
                                    'request_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'}}}},
]


def parse_command(command):
    """Return argv for an admin command, or raise ValueError. No shell is ever used."""
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND:
        raise ValueError('command required (max %d characters)' % MAX_COMMAND)
    if not CHARSET.fullmatch(command):
        raise ValueError('unsupported command character')
    argv = shlex.split(command, posix=True)
    if not argv or not argv[0].startswith('/') or '/../' in argv[0] + '/' or argv[0].endswith('/'):
        raise ValueError('the program must be an absolute path')
    return argv


def parse_timeout(value):
    if value is None:
        return DEFAULT_TIMEOUT
    if type(value) is not int or not 1 <= value <= MAX_TIMEOUT:
        raise ValueError('timeout must be 1..%d seconds' % MAX_TIMEOUT)
    return value


def install_schema(tools):
    """Additive and idempotent catalog update for the gateway."""
    import copy
    return copy.deepcopy([t for t in tools if t['name'] not in ADMIN_NAMES]) + copy.deepcopy(ADMIN_TOOLS)
''',
'mac_admin_client.py': r'''"""Agent side of Mac administration: queue a request, read its result.

The agent never runs privileged code. It writes one JSON request into the
outbox (owned by the agent, inside a root-owned directory) and reads results
that only the root helper can write.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

from admin_schema import EXPIRE_S, MAX_REASON, parse_command, parse_timeout

ROOT = Path('/Library/MCPAndreaMacAdmin')
RID = re.compile(r'[a-f0-9]{32}')
MAX_PENDING = 3
HEARTBEAT_MAX_AGE = 120
MAX_RESULT = 256 * 1024


class AdminClient:
    def __init__(self, root=ROOT, helper_uid=0, now=time.time):
        self.root = Path(root)
        self.outbox, self.results = self.root / 'outbox', self.root / 'results'
        self.helper_uid, self.now = helper_uid, now

    def _dir(self, path, owner):
        fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        st = os.fstat(fd)
        if st.st_uid != owner or st.st_mode & 0o002:
            os.close(fd)
            raise PermissionError('unsafe Mac admin directory')
        return fd

    def _read(self, dfd, name, limit):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
        with os.fdopen(fd, 'rb') as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != self.helper_uid or st.st_mode & 0o022 or st.st_size > limit:
                raise PermissionError('unsafe Mac admin result')
            return json.loads(f.read(limit + 1))

    def helper_alive(self):
        try:
            dfd = self._dir(self.results, self.helper_uid)
        except FileNotFoundError:
            raise RuntimeError('Mac admin helper not installed') from None
        try:
            beat = self._read(dfd, 'helper_status.json', 4096)
        except FileNotFoundError:
            raise RuntimeError('Mac admin helper not running') from None
        finally:
            os.close(dfd)
        if not isinstance(beat.get('time'), (int, float)):
            raise RuntimeError('Mac admin helper not running')
        busy = beat.get('busy_until') if isinstance(beat.get('busy_until'), (int, float)) else 0
        if self.now() - beat['time'] > HEARTBEAT_MAX_AGE and self.now() > busy:
            raise RuntimeError('Mac admin helper not running')
        return beat

    def request(self, caller, identity, args):
        if set(args) - {'command', 'reason', 'timeout'}:
            raise ValueError('unexpected admin arguments')
        if not isinstance(identity, str) or not identity.startswith('work:'):
            raise PermissionError('an open work session is required')
        command = args.get('command')
        argv = parse_command(command)
        timeout = parse_timeout(args.get('timeout'))
        reason = args.get('reason')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON:
            raise ValueError('reason required (max %d characters)' % MAX_REASON)
        self.helper_alive()
        dfd = self._dir(self.outbox, os.getuid())
        try:
            if os.fstat(dfd).st_mode & 0o077:
                raise PermissionError('unsafe Mac admin outbox')
            pending = [n for n in os.listdir(dfd) if RID.fullmatch(n[:-5] if n.endswith('.json') else '')]
            if len(pending) >= MAX_PENDING:
                raise PermissionError('too many pending Mac admin requests')
            rid, created = uuid.uuid4().hex, int(self.now())
            req = {'id': rid, 'command': command, 'argv': argv,
                   'sha256': hashlib.sha256(command.encode()).hexdigest(),
                   'reason': reason, 'timeout': timeout, 'caller': caller,
                   'work_session_id': identity[5:], 'created_at': created,
                   'expires_at': created + EXPIRE_S}
            temp = '.' + rid + '.tmp'
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(req, f, ensure_ascii=True)
                    f.flush()
                    os.fsync(f.fileno())
                os.rename(temp, rid + '.json', src_dir_fd=dfd, dst_dir_fd=dfd)
            except BaseException:
                try:
                    os.unlink(temp, dir_fd=dfd)
                except FileNotFoundError:
                    pass
                raise
            os.fsync(dfd)
        finally:
            os.close(dfd)
        return {'request_id': rid, 'sha256': req['sha256'], 'expires_at': req['expires_at'],
                'status': 'sent to Andrea on Telegram (Mac admin bot) for approval; poll mac_admin_result'}

    def result(self, caller, args):
        if set(args) != {'request_id'} or not isinstance(args['request_id'], str) or not RID.fullmatch(args['request_id']):
            raise ValueError('invalid request_id')
        rid = args['request_id']
        try:
            dfd = self._dir(self.results, self.helper_uid)
        except FileNotFoundError:
            raise RuntimeError('Mac admin helper not installed') from None
        try:
            data = self._read(dfd, rid + '.json', MAX_RESULT)
        except FileNotFoundError:
            data = None
        finally:
            os.close(dfd)
        if data is None:
            try:
                os.lstat(str(self.outbox / (rid + '.json')))
                return {'id': rid, 'status': 'queued'}
            except FileNotFoundError:
                return {'id': rid, 'status': 'unknown'}
        if data.get('id') != rid or data.get('caller') != caller:
            raise PermissionError('this admin request belongs to another authorization')
        return data
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
    async def test_work_operations_audited_with_session_id(self):
        await self.lock(self.a)
        with self.assertRaises(PermissionError):await self.lock(self.b)
        state=await self.call('who_is_working',{})
        ops=[(x['operation'],x['work_session_id'],x.get('ok')) for x in state['recent_work_operations'] if x['operation']=='work_lock']
        self.assertIn(('work_lock',self.a['work_session_id'],True),ops)
        self.assertIn(('work_lock',self.b['work_session_id'],False),ops)
        self.assertFalse([x for x in state['recent_work_operations'] if x['operation'] in ('work_lock','work_session') and x['work_session_id'] is None])
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
        self.assertEqual(len(TOOLS),len(NAMES));self.assertEqual(len(TOOLS),27)
        self.assertTrue({'mac_admin_request','mac_admin_result'} <= NAMES)
        self.assertTrue({'work_session','work_lock'} <= NAMES)
        self.assertTrue({'start_search','get_more_search_results','stop_search'}<=NAMES)
        for t in TOOLS:
            m=t['inputSchema']['properties'].get('machine',{})
            if t['name'].startswith('mac_admin_'):self.assertEqual(m['enum'],['mac_mio']);continue
            if 'enum' in m:self.assertEqual(set(m['enum']),{'vps','mac_noleggio','mac_mio'})


if __name__=='__main__':unittest.main(verbosity=2)
''',
'test_mac_admin.py': r'''"""Mac admin via Telegram: agent client, root helper (simulated) and dispatcher."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from admin_schema import ADMIN_TOOLS, ADMIN_NAMES, install_schema, parse_command
from mac_admin_client import AdminClient
import mac_admin_helper as H

CHAT = 4242


class FakeTelegram:
    def __init__(self):
        self.calls = []
        self.next_id = 100
        self.fail = set()

    def __call__(self, method, **params):
        params.pop('_http_timeout', None)
        self.calls.append((method, params))
        if method in self.fail:
            raise RuntimeError('telegram %s failed' % method)
        if method == 'sendMessage':
            self.next_id += 1
            return {'message_id': self.next_id}
        return True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'admin'
        self.root.mkdir(mode=0o755)
        os.chmod(self.root, 0o755)
        for name, mode in (('outbox', 0o700), ('results', 0o750), ('claims', 0o700)):
            (self.root / name).mkdir(mode=mode)
            os.chmod(self.root / name, mode)
        self.clock = [1_000_000.0]
        now = lambda: self.clock[0]
        uid, gid = os.getuid(), os.getgid()
        self.tg = FakeTelegram()
        self.helper = H.Helper(self.root, tg=self.tg, chat_id=CHAT, agent_uid=uid, agent_gid=gid,
                               owner_uid=uid, now=now, cwd=self.tmp.name)
        self.client = AdminClient(self.root, helper_uid=uid, now=now)
        self.helper.check_layout()
        self.helper.heartbeat()

    def tearDown(self):
        self.tmp.cleanup()

    def ask(self, command='/bin/echo ciao', caller='claude:abcdef12', reason='prova', **extra):
        args = {'command': command, 'reason': reason, **extra}
        return self.client.request(caller, 'work:' + 'a' * 32, args)

    def tap(self, kind, rid, user=CHAT, msg=None, short=None):
        p = self.helper.pending.get(rid)
        data = kind + ':' + rid + ('' if kind == 'r' else ':' + (short or p['req']['sha256'][:16]))
        self.helper.on_callback({'id': 'x', 'data': data, 'from': {'id': user},
                                 'message': {'chat': {'id': user}, 'message_id': msg or (p['msg_id'] if p else 0)}})

    def result(self, rid, caller='claude:abcdef12'):
        return self.client.result(caller, {'request_id': rid})


class Validation(unittest.TestCase):
    def test_parse_command(self):
        self.assertEqual(parse_command('/bin/launchctl print system'), ['/bin/launchctl', 'print', 'system'])
        for bad in ('ls -la', '/bin/ls; rm', '/bin/echo $(id)', '/bin/ls | cat', '/bin/../bin/sh', '', 'x' * 3001, '/bin/a"b'):
            with self.assertRaises(ValueError):
                parse_command(bad)

    def test_catalog_additive(self):
        tools = install_schema(install_schema([{'name': 'list_machines', 'inputSchema': {}}]))
        self.assertEqual([t['name'] for t in tools].count('mac_admin_request'), 1)
        self.assertEqual({t['name'] for t in ADMIN_TOOLS}, ADMIN_NAMES)
        req = [t for t in tools if t['name'] == 'mac_admin_request'][0]['inputSchema']
        self.assertEqual(req['properties']['machine']['enum'], ['mac_mio'])
        self.assertIn('work_session_token', req['required'])

    def test_sensitive_patterns(self):
        for cmd in ('/bin/rm -f /tmp/x', '/usr/bin/dscl . -list /Users', '/bin/launchctl bootout system/x',
                    '/usr/bin/python3 /tmp/x.py', '/bin/ls /Users/babo/Bitcoin', '/usr/bin/git pull'):
            self.assertTrue(H.SENSITIVE.search(cmd), cmd)
        for cmd in ('/usr/bin/sw_vers', '/bin/launchd_x', '/usr/bin/uptime', '/bin/df -h'):
            self.assertFalse(H.SENSITIVE.search(cmd), cmd)


class Flow(Base):
    def test_approve_runs_exact_command_once(self):
        r = self.ask()
        self.assertEqual(self.result(r['request_id'])['status'], 'queued')
        self.helper.scan()
        self.assertEqual(self.result(r['request_id'])['status'], 'waiting')
        method, params = self.tg.calls[-1]
        self.assertEqual(method, 'sendMessage')
        self.assertIn('/bin/echo ciao', params['text'])
        self.tap('a', r['request_id'])
        res = self.result(r['request_id'])
        self.assertEqual((res['status'], res['exit_code'], res['output']), ('done', 0, 'ciao\n'))
        self.assertTrue((self.root / 'claims' / (r['request_id'] + '.json')).exists())
        self.tap('a', r['request_id'], msg=101, short=res['sha256'][:16])  # stale repeated tap
        executed = [l for l in (self.root / 'audit.jsonl').read_text().splitlines() if '"executed"' in l]
        self.assertEqual(len(executed), 1)

    def test_foreign_user_wrong_hash_and_wrong_message_ignored(self):
        r = self.ask()
        self.helper.scan()
        rid = r['request_id']
        self.tap('a', rid, user=999)
        self.tap('a', rid, short='0' * 16)
        self.tap('a', rid, msg=1)
        self.assertEqual(self.result(rid)['status'], 'waiting')

    def test_sensitive_needs_second_confirmation(self):
        target = Path(self.tmp.name) / 'victim'
        target.write_text('x')
        r = self.ask('/bin/rm ' + str(target))
        self.helper.scan()
        rid = r['request_id']
        self.tap('a', rid)
        self.tap('a', rid)
        self.assertTrue(target.exists())
        self.tap('c', rid)
        self.assertFalse(target.exists())
        self.assertEqual(self.result(rid)['status'], 'done')

    def test_reject_and_expiry(self):
        a, b = self.ask(), self.ask()
        self.helper.scan()
        self.tap('r', a['request_id'])
        self.assertEqual(self.result(a['request_id'])['status'], 'rejected')
        self.clock[0] += 601
        self.helper.expire()
        self.assertEqual(self.result(b['request_id'])['status'], 'expired')

    def test_late_tap_after_expiry_does_not_run(self):
        target = Path(self.tmp.name) / 'late'
        r = self.ask('/usr/bin/touch ' + str(target))
        self.helper.scan()
        self.clock[0] += 600
        self.tap('a', r['request_id'])
        self.assertFalse(target.exists())
        self.assertEqual(self.result(r['request_id'])['status'], 'expired')

    def test_timeout_kills_command(self):
        r = self.ask('/bin/sleep 5', timeout=1)
        self.helper.scan()
        self.tap('a', r['request_id'])
        self.assertEqual(self.result(r['request_id'])['exit_code'], 124)

    def test_other_caller_cannot_read_result(self):
        r = self.ask()
        self.helper.scan()
        with self.assertRaises(PermissionError):
            self.result(r['request_id'], caller='chatgpt:zzzzzzzz')

    def test_pending_limit_and_session_required(self):
        for _ in range(3):
            self.ask()
        with self.assertRaises(PermissionError):
            self.ask()
        with self.assertRaises(PermissionError):
            self.client.request('claude:abcdef12', 'claude:abcdef12', {'command': '/bin/echo', 'reason': 'x'})

    def test_helper_down_refuses_queue(self):
        self.clock[0] += 121
        with self.assertRaises(RuntimeError):
            self.ask()
        self.helper.heartbeat(busy_until=self.clock[0] + 300)
        self.clock[0] += 200
        self.ask()

    def test_telegram_failure_reports_error(self):
        self.tg.fail.add('sendMessage')
        r = self.ask()
        self.helper.scan()
        self.assertEqual(self.result(r['request_id'])['status'], 'error')


class Hostile(Base):
    """The outbox is written by the agent account: treat every file as hostile."""
    def put(self, name, data):
        path = self.root / 'outbox' / name
        path.write_text(json.dumps(data) if not isinstance(data, str) else data)
        return path

    def good(self, **change):
        r = self.ask()
        path = self.root / 'outbox' / (r['request_id'] + '.json')
        data = json.loads(path.read_text())
        data.update(change)
        path.write_text(json.dumps(data))
        return r['request_id']

    def test_tampered_fields_rejected(self):
        cases = [dict(command='/bin/echo altro'), dict(argv=['/bin/sh', '-c', 'id']), dict(timeout=10000),
                 dict(expires_at=2_000_000), dict(created_at=2_000_000), dict(caller='bad caller'),
                 dict(extra=1)]
        for change in cases:
            rid = self.good(**change)
            self.helper.scan()
            self.assertEqual(self.result(rid, caller=change.get('caller', 'claude:abcdef12'))['status'], 'error', change)
            self.assertNotIn(rid, self.helper.pending)
        self.assertFalse([c for c in self.tg.calls if c[0] == 'sendMessage'])

    def test_symlink_and_junk_removed(self):
        secret = Path(self.tmp.name) / 'secret.json'
        secret.write_text('{}')
        rid = uuid.uuid4().hex
        os.symlink(str(secret), str(self.root / 'outbox' / (rid + '.json')))
        self.put('junk.txt', 'x')
        self.helper.scan()
        self.assertEqual(os.listdir(self.root / 'outbox'), [])
        self.assertTrue(secret.exists())
        with self.assertRaises(PermissionError):  # error result recorded, caller unknown
            self.result(rid)
        self.assertEqual(json.loads((self.root / 'results' / (rid + '.json')).read_text())['status'], 'error')

    def test_replay_of_executed_id_rejected(self):
        r = self.ask()
        raw = (self.root / 'outbox' / (r['request_id'] + '.json')).read_text()
        self.helper.scan()
        self.tap('a', r['request_id'])
        self.put(r['request_id'] + '.json', raw)
        self.helper.scan()
        self.assertEqual(self.result(r['request_id'])['status'], 'done')
        self.assertNotIn(r['request_id'], self.helper.pending)

    def test_layout_check_rejects_open_outbox(self):
        os.chmod(self.root / 'outbox', 0o777)
        with self.assertRaises(RuntimeError):
            self.helper.check_layout()


class Dispatch(unittest.IsolatedAsyncioTestCase):
    """mac_admin_request needs a work session and is audited with its id (point B too)."""
    async def asyncSetUp(self):
        from mac_agent import Dispatcher
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        (base / 'work').mkdir(mode=0o700)
        (base / 'state').mkdir(mode=0o700)
        self.d = Dispatcher(base / 'work', base / 'state')
        root = base / 'admin'
        root.mkdir(mode=0o755)
        for name, mode in (('outbox', 0o700), ('results', 0o750), ('claims', 0o700)):
            (root / name).mkdir(mode=mode)
            os.chmod(root / name, mode)
        self.helper = H.Helper(root, tg=FakeTelegram(), chat_id=CHAT, agent_uid=os.getuid(), agent_gid=os.getgid(),
                               owner_uid=os.getuid(), cwd=self.tmp.name)
        self.helper.heartbeat()
        self.d.admin = AdminClient(root, helper_uid=os.getuid())

    async def asyncTearDown(self):
        await self.d.close()
        self.tmp.cleanup()

    async def call(self, op, args, s=None, caller='claude:abcdef12'):
        args = dict(args)
        if s:
            args.update(work_session_id=s['work_session_id'], work_session_token=s['work_session_token'])
        return await self.d.dispatch({'type': 'request', 'id': uuid.uuid4().hex, 'caller': caller, 'op': op, 'args': args})

    async def test_admin_request_requires_session_and_is_audited(self):
        with self.assertRaises(PermissionError):
            await self.call('mac_admin_request', {'command': '/bin/echo x', 'reason': 'r'})
        s = await self.call('work_session', {'action': 'open', 'label': 'admin', 'minutes': 5})
        r = await self.call('mac_admin_request', {'command': '/bin/echo x', 'reason': 'r'}, s)
        self.assertEqual((await self.call('mac_admin_result', {'request_id': r['request_id']}))['status'], 'queued')
        state = await self.call('who_is_working', {})
        ops = {(x['operation'], x['work_session_id']) for x in state['recent_work_operations']}
        sid = s['work_session_id']
        self.assertIn(('mac_admin_request', sid), ops)
        self.assertIn(('work_session', sid), ops)  # B: open is audited with its new id
        await self.call('work_session', {'action': 'close'}, s)
        state = await self.call('who_is_working', {})
        self.assertEqual(sum(1 for x in state['recent_work_operations'] if x == {**x, 'operation': 'work_session', 'work_session_id': sid}), 2)


if __name__ == '__main__':
    unittest.main()
''',
'mac_admin_helper.py': r'''#!/usr/bin/env python3
"""MCP Andrea Mac admin helper (root LaunchDaemon), v0.12.

Reads requests queued by the non-admin agent (UID 5000), shows the exact
command to Andrea through a dedicated Telegram bot (not the VPS bot), and runs
it as root only after his approval. Every command is approved individually;
there is no allowlist. Sensitive commands need a second confirmation.
Self-contained on purpose: no imports from the agent tree.
"""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request

VERSION = '0.12-mac-admin-1'
ROOT = Path(os.environ.get('MCP_MAC_ADMIN_ROOT', '/Library/MCPAndreaMacAdmin'))
AGENT_UID = 5000
AGENT_GID = 5000
EXPIRE_S = 600
MAX_COMMAND = 3000
MAX_TIMEOUT = 900
MAX_PENDING = 3
MAX_REQUEST = 16384
MAX_OUT = 20000
CHARSET = re.compile(r'[A-Za-z0-9_./:=@%+, -]+')
HEX32 = re.compile(r'[0-9a-f]{32}')
CALLER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}')
SENSITIVE = re.compile(
    r'(^|/)(rm|rmdir|mv|dd|dscl|dseditgroup|sysadminctl|csrutil|nvram|diskutil|fdesetup|'
    r'security|chmod|chown|chflags|launchctl|kill|killall|pkill|shutdown|reboot|halt|'
    r'spctl|tccutil|pfctl|profiles|systemsetup|networksetup|softwareupdate|installer|'
    r'tmutil|pmset|scutil|visudo|sudo|su|bash|zsh|sh|python3?|perl|ruby|osascript|curl|git)( |$)'
    r'|/etc/|/System/|/Library/Launch|/Library/MCPAndrea|/Users/|\.ssh|keychain|bitcoin|marruca|lidar',
    re.I)
ENV = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_US.UTF-8', 'HOME': '/var/root'}


class ExpiredRequest(ValueError):
    pass


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def parse_argv(command):
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND or not CHARSET.fullmatch(command):
        raise ValueError('unsupported command')
    argv = shlex.split(command, posix=True)
    if not argv or not argv[0].startswith('/') or '/../' in argv[0] + '/' or argv[0].endswith('/'):
        raise ValueError('the program must be an absolute path')
    return argv


class Telegram:
    """Minimal Bot API client. Never log URLs or exception text: they carry the token."""
    def __init__(self, token):
        if not re.fullmatch(r'[0-9]{5,15}:[A-Za-z0-9_-]{30,64}', token or ''):
            raise ValueError('invalid bot token format')
        self.api = 'https://api.telegram.org/bot%s/' % token

    def __call__(self, method, **params):
        timeout = params.pop('_http_timeout', 40)
        data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                       for k, v in params.items()}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.api + method, data=data), timeout=timeout) as r:
                out = json.loads(r.read())
        except Exception as exc:
            raise RuntimeError('telegram %s failed (%s)' % (method, type(exc).__name__)) from None
        if not out.get('ok'):
            raise RuntimeError('telegram %s failed' % method)
        return out['result']


class Helper:
    def __init__(self, root=ROOT, tg=None, chat_id=None, agent_uid=AGENT_UID, agent_gid=AGENT_GID,
                 owner_uid=0, now=time.time, cwd='/var/root'):
        self.root = Path(root)
        self.outbox, self.results = self.root / 'outbox', self.root / 'results'
        self.claims, self.audit_path = self.root / 'claims', self.root / 'audit.jsonl'
        self.tg, self.chat = tg, chat_id
        self.agent_uid, self.agent_gid, self.owner_uid = agent_uid, agent_gid, owner_uid
        self.now, self.cwd = now, cwd
        self.pending = {}

    # ---------- storage ----------
    def check_layout(self):
        def need(path, uid, gid, mode):
            st = os.lstat(str(path))
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != uid or (gid is not None and st.st_gid != gid) or stat.S_IMODE(st.st_mode) != mode:
                raise RuntimeError('unsafe layout: ' + str(path))
        need(self.root, self.owner_uid, None, 0o755)
        need(self.outbox, self.agent_uid, self.agent_gid, 0o700)
        need(self.results, self.owner_uid, self.agent_gid, 0o750)
        need(self.claims, self.owner_uid, None, 0o700)

    def audit(self, event, **kw):
        kw.update(event=event, ts=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self.now())))
        fd = os.open(str(self.audit_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as f:
            f.write(json.dumps(kw, ensure_ascii=False) + '\n')

    def write_result(self, rid, **kw):
        kw['id'] = rid
        kw['updated'] = int(self.now())
        self._publish(rid + '.json', kw)

    def _publish(self, name, value):
        dfd = os.open(str(self.results), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            temp = '.%s.%d.tmp' % (name, os.getpid())
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640, dir_fd=dfd)
            with os.fdopen(fd, 'w') as f:
                json.dump(value, f, ensure_ascii=False)
                f.flush()
                os.fchmod(f.fileno(), 0o640)
                if os.geteuid() == 0:
                    os.fchown(f.fileno(), self.owner_uid, self.agent_gid)
                os.fsync(f.fileno())
            os.rename(temp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        finally:
            os.close(dfd)

    def result_exists(self, rid):
        return os.path.lexists(str(self.results / (rid + '.json'))) or os.path.lexists(str(self.claims / (rid + '.json')))

    def heartbeat(self, busy_until=None):
        self._publish('helper_status.json', {'time': self.now(), 'version': VERSION, 'pid': os.getpid(),
                                             'pending': len(self.pending), 'busy_until': busy_until})

    # ---------- requests ----------
    def validate(self, raw):
        if not isinstance(raw, dict) or set(raw) != {'id', 'command', 'argv', 'sha256', 'reason', 'timeout', 'caller',
                                                     'work_session_id', 'created_at', 'expires_at'}:
            raise ValueError('unexpected request fields')
        rid, cmd = raw['id'], raw['command']
        if not isinstance(rid, str) or not HEX32.fullmatch(rid):
            raise ValueError('invalid request id')
        argv = parse_argv(cmd)
        if raw['argv'] != argv or raw['sha256'] != sha(cmd):
            raise ValueError('command hash or arguments mismatch')
        if not isinstance(raw['caller'], str) or not CALLER.fullmatch(raw['caller']):
            raise ValueError('invalid caller')
        if not isinstance(raw['work_session_id'], str) or not HEX32.fullmatch(raw['work_session_id']):
            raise ValueError('invalid work session')
        if type(raw['timeout']) is not int or not 1 <= raw['timeout'] <= MAX_TIMEOUT:
            raise ValueError('invalid timeout')
        reason = raw['reason']
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise ValueError('invalid reason')
        created, expires, now = raw['created_at'], raw['expires_at'], self.now()
        if type(created) is not int or type(expires) is not int or created > now + 5 or expires - created != EXPIRE_S or now >= expires:
            raise ValueError('request expired or invalid ttl')
        req = dict(raw)
        req['sensitive'] = bool(SENSITIVE.search(cmd))
        return req

    def take_outbox(self):
        """Read and remove queued files; the outbox is agent-owned and untrusted."""
        dfd = os.open(str(self.outbox), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        out = []
        try:
            st = os.fstat(dfd)
            if st.st_uid != self.agent_uid or stat.S_IMODE(st.st_mode) != 0o700:
                raise RuntimeError('unsafe outbox')
            for name in sorted(os.listdir(dfd)):
                rid = name[:-5] if name.endswith('.json') else None
                if rid is None or not HEX32.fullmatch(rid):
                    try:
                        if name.endswith('.tmp') and self.now() - os.lstat(name, dir_fd=dfd).st_mtime < 60:
                            continue
                        os.unlink(name, dir_fd=dfd)
                    except (FileNotFoundError, IsADirectoryError, PermissionError):
                        pass
                    continue
                data, error = None, None
                try:
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
                    with os.fdopen(fd, 'rb') as f:
                        fst = os.fstat(f.fileno())
                        if not stat.S_ISREG(fst.st_mode) or fst.st_uid != self.agent_uid or fst.st_nlink != 1 or fst.st_size > MAX_REQUEST:
                            raise ValueError('unsafe request file')
                        data = json.loads(f.read(MAX_REQUEST + 1))
                except Exception as exc:
                    error = str(exc)[:200]
                try:
                    os.unlink(name, dir_fd=dfd)
                except (FileNotFoundError, IsADirectoryError):
                    pass
                out.append((rid, data, error))
        finally:
            os.close(dfd)
        return out

    def text_for(self, req, header):
        warn = '\n\u26a0\ufe0f <b>COMANDO SENSIBILE: richiede doppia conferma</b>' if req.get('sensitive') else ''
        return ('%s\n<b>Mac:</b> mac_mio (root)\n<b>Da:</b> %s\n<b>Sessione:</b> %s\n<b>Motivo:</b> %s\n'
                '<b>Timeout:</b> %ss\n<b>ID:</b> <code>%s</code> \u00b7 sha <code>%s</code>%s\n\n<pre>%s</pre>'
                % (header, html.escape(req['caller']), req['work_session_id'][:8], html.escape(req['reason']),
                   req['timeout'], req['id'][:8], req['sha256'][:12], warn, html.escape(req['command'])))

    def buttons(self, req, stage):
        hh = req['sha256'][:16]
        ok = ('\u2705 Approva', 'a:%s:%s' % (req['id'], hh)) if stage == 1 else \
             ('\u26a0\ufe0f CONFERMA DEFINITIVA', 'c:%s:%s' % (req['id'], hh))
        return {'inline_keyboard': [[{'text': ok[0], 'callback_data': ok[1]},
                                     {'text': '\u274c Rifiuta', 'callback_data': 'r:%s' % req['id']}]]}

    def scan(self):
        for rid, data, error in self.take_outbox():
            caller = data.get('caller') if isinstance(data, dict) and isinstance(data.get('caller'), str) else '?'
            try:
                if error:
                    raise ValueError(error)
                if data.get('id') != rid:
                    raise ValueError('file name and request id differ')
                if rid in self.pending or self.result_exists(rid):
                    raise ValueError('duplicate request id')
                if len(self.pending) >= MAX_PENDING:
                    raise ValueError('too many pending requests')
                req = self.validate(data)
            except Exception as exc:
                self.audit('rejected_malformed', id=rid, error=str(exc)[:200])
                if not self.result_exists(rid) and rid not in self.pending:
                    self.write_result(rid, status='error', error='richiesta non valida: %s' % str(exc)[:200], caller=caller)
                continue
            self.audit('requested', id=rid, caller=req['caller'], sha256=req['sha256'], command=req['command'],
                       reason=req['reason'], work_session_id=req['work_session_id'])
            try:
                msg = self.tg('sendMessage', chat_id=self.chat, parse_mode='HTML',
                              text=self.text_for(req, '\U0001f510 <b>Richiesta amministratore Mac</b>'),
                              reply_markup=self.buttons(req, 1))
            except Exception as exc:
                self.audit('telegram_send_failed', id=rid, error_type=type(exc).__name__)
                self.write_result(rid, status='error', error='Telegram non raggiungibile; comando non eseguito',
                                  caller=req['caller'])
                continue
            self.pending[rid] = {'req': req, 'msg_id': msg['message_id'], 'stage': 1}
            self.write_result(rid, status='waiting', caller=req['caller'], sha256=req['sha256'])

    def finish(self, p, header, extra=''):
        try:
            self.tg('editMessageText', chat_id=self.chat, message_id=p['msg_id'], parse_mode='HTML',
                    text=self.text_for(p['req'], header) + extra)
        except Exception as exc:
            self.audit('edit_failed', error_type=type(exc).__name__)

    def on_callback(self, cq):
        try:
            self.tg('answerCallbackQuery', callback_query_id=cq['id'], _http_timeout=3)
        except Exception as exc:
            self.audit('callback_ack_failed', error_type=type(exc).__name__)
        if cq.get('from', {}).get('id') != self.chat or cq.get('message', {}).get('chat', {}).get('id') != self.chat:
            self.audit('callback_rejected_foreign_user', from_id=cq.get('from', {}).get('id'))
            return
        parts = (cq.get('data') or '').split(':')
        kind, rid = parts[0], parts[1] if len(parts) > 1 else ''
        p = self.pending.get(rid)
        if not p or cq.get('message', {}).get('message_id') != p['msg_id']:
            return
        req = p['req']
        if self.now() >= req['expires_at']:
            self.expire(force=rid)
            return
        if kind == 'r':
            self.pending.pop(rid)
            self.write_result(rid, status='rejected', caller=req['caller'])
            self.audit('rejected', id=rid, caller=req['caller'])
            self.finish(p, '\u274c <b>Rifiutato</b>')
            return
        if len(parts) != 3 or parts[2] != req['sha256'][:16]:
            return
        if kind == 'a' and req['sensitive']:
            p['stage'] = 2
            try:
                self.tg('editMessageText', chat_id=self.chat, message_id=p['msg_id'], parse_mode='HTML',
                        text=self.text_for(req, '\u26a0\ufe0f <b>Seconda conferma richiesta</b>'), reply_markup=self.buttons(req, 2))
            except Exception as exc:
                self.audit('second_confirmation_display_failed', id=rid, error_type=type(exc).__name__)
            return
        if (kind == 'a' and p['stage'] == 1) or (kind == 'c' and p['stage'] == 2):
            self.pending.pop(rid)
            self.audit('approved', id=rid, caller=req['caller'], stage=p['stage'])
            self.finish(p, '\u23f3 <b>Approvato, in esecuzione\u2026</b>')
            try:
                code, out = self.run(req)
                tail = html.escape(out[-1500:]) if out else '(nessun output)'
                self.finish(p, '\u2705 <b>Eseguito</b> (exit %s)' % code, '\n<b>Output:</b>\n<pre>%s</pre>' % tail)
            except ExpiredRequest as exc:
                self.write_result(rid, status='expired', error=str(exc), caller=req['caller'])
                self.finish(p, '\u231b <b>Scaduto</b> (comando non eseguito)')
            except Exception as exc:
                self.write_result(rid, status='error', error=str(exc)[:300], caller=req['caller'])
                self.finish(p, '\U0001f4a5 <b>Errore</b>: %s' % html.escape(str(exc)[:300]))

    def claim(self, req):
        dfd = os.open(str(self.claims), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(req['id'] + '.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
            with os.fdopen(fd, 'w') as f:
                json.dump({'id': req['id'], 'sha256': req['sha256'], 'claimed_at': self.now()}, f)
                f.flush()
                os.fsync(f.fileno())
            os.fsync(dfd)
        finally:
            os.close(dfd)

    def run(self, req):
        if self.now() >= req['expires_at']:
            raise ExpiredRequest('request expired; command was not executed')
        if parse_argv(req['command']) != req['argv'] or sha(req['command']) != req['sha256']:
            raise RuntimeError('command changed after display')
        self.claim(req)
        self.heartbeat(busy_until=self.now() + req['timeout'] + 30)
        started = time.monotonic()
        proc = subprocess.Popen(req['argv'], shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, cwd=self.cwd, env=dict(ENV), start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=req['timeout'])
            code = proc.returncode
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, _ = proc.communicate()
            code = 124
        text = out.decode('utf-8', errors='replace')
        truncated = len(text) > MAX_OUT
        text = text[-MAX_OUT:]
        self.write_result(req['id'], status='done', exit_code=code, output=text, truncated=truncated,
                          seconds=round(time.monotonic() - started, 1), caller=req['caller'], sha256=req['sha256'])
        self.audit('executed', id=req['id'], caller=req['caller'], sha256=req['sha256'], command=req['command'],
                   exit_code=code, output=text[-4000:])
        return code, text

    def expire(self, force=None):
        now = self.now()
        for rid in [r for r, p in self.pending.items() if r == force or p['req']['expires_at'] <= now]:
            p = self.pending.pop(rid)
            self.write_result(rid, status='expired', caller=p['req']['caller'])
            self.audit('expired', id=rid)
            self.finish(p, '\u231b <b>Scaduto</b> (comando non eseguito)')

    def startup_cleanup(self):
        dfd = os.open(str(self.results), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            names = os.listdir(dfd)
        finally:
            os.close(dfd)
        for name in names:
            if name.endswith('.json') and HEX32.fullmatch(name[:-5]):
                try:
                    with open(str(self.results / name)) as f:
                        r = json.load(f)
                    if r.get('status') == 'waiting':
                        self.write_result(name[:-5], status='expired', caller=r.get('caller', '?'), error='helper riavviato')
                except Exception:
                    pass


def load_config(root=ROOT):
    path = root / 'conf' / 'telegram.json'
    for p in (root / 'conf', path):
        st = os.lstat(str(p))
        if st.st_uid != 0 or stat.S_IMODE(st.st_mode) & 0o077:
            raise RuntimeError('unsafe Telegram configuration')
    with open(str(path)) as f:
        conf = json.load(f)
    if type(conf.get('chat_id')) is not int:
        raise RuntimeError('invalid chat id')
    return Telegram(conf['bot_token']), conf['chat_id']


def main():
    if os.geteuid() != 0 or sys.platform != 'darwin':
        raise SystemExit('root on macOS required')
    os.umask(0o077)
    tg, chat = load_config()
    helper = Helper(tg=tg, chat_id=chat)
    helper.check_layout()
    helper.startup_cleanup()
    offset = None
    for u in tg('getUpdates', timeout=0):
        offset = u['update_id'] + 1
    tg('sendMessage', chat_id=chat, text='\U0001f7e2 Helper amministrazione Mac (MCP Andrea) avviato.')
    helper.audit('started', version=VERSION, pid=os.getpid())
    while True:
        try:
            helper.heartbeat()
            helper.scan()
            params = {'timeout': 5, 'allowed_updates': ['callback_query']}
            if offset is not None:
                params['offset'] = offset
            for u in tg('getUpdates', **params):
                offset = u['update_id'] + 1
                if 'callback_query' in u:
                    helper.on_callback(u['callback_query'])
            helper.expire()
        except Exception as exc:
            helper.audit('loop_error', error_type=type(exc).__name__, error=str(exc)[:200])
            time.sleep(5)


if __name__ == '__main__':
    main()
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

from admin_schema import install_schema as install_admin_schema
TOOLS = install_admin_schema(TOOLS)
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
        # Per-user macOS agents started on demand by launchd (kernel-verified image).
        if known_system(p):continue
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
    code="import sys,unittest;sys.path.insert(0,"+repr(str(TEST_CODE))+");s=unittest.defaultTestLoader.loadTestsFromNames(['test_work_core','test_search','test_mac_admin']);r=unittest.TextTestRunner(verbosity=2).run(s);sys.exit(0 if r.wasSuccessful() else 1)"
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
            admin_conf=telegram_setup()
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
                record('agent_active',version=NEW_VERSION,uid=5000,agent_pid=ready['pid'],checks=checks,
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
            admin_phase(admin_conf)
        elif action=='--rollback':
            admin_remove()
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

"""Appended to the v0.12 Mac installer by build_mac_v012.py: Telegram pairing and the root helper."""

ADMIN_ROOT=Path('/Library/MCPAndreaMacAdmin')
ADMIN_LABEL='it.andreababini.mcp-mac-admin'
ADMIN_PLIST=Path('/Library/LaunchDaemons')/(ADMIN_LABEL+'.plist')
ADMIN_BACKUP=BACKUP/'admin'
KNOWN_SYSTEM={'/usr/sbin/distnoted':('agent',),'/usr/sbin/cfprefsd':('agent',),
              '/usr/libexec/trustd':('--agent',),'/usr/libexec/secinitd':(),
              '/usr/libexec/lsd':(),'/usr/libexec/containermanagerd':()}


def executable(pid):
    """Kernel view of the program image; argv in ps can be rewritten by the process itself."""
    import ctypes
    lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
    buf=ctypes.create_string_buffer(4096)
    n=lib.proc_pidpath(ctypes.c_int(pid),buf,ctypes.c_uint32(4096))
    return os.fsdecode(buf.raw[:n]) if n>0 else None


def known_system(p):
    """Only per-user macOS agents started by launchd, verified by kernel image path."""
    if len(p)!=5 or p[2]!='1':return False
    args=p[4].split()
    if not args or args[0] not in KNOWN_SYSTEM or tuple(args[1:])!=KNOWN_SYSTEM[args[0]]:return False
    try:return executable(int(p[1]))==args[0]
    except Exception:return False


def helper_namespace():
    ns={'__name__':'mac_admin_helper_embedded'}
    exec(compile(SOURCES['mac_admin_helper.py'],'mac_admin_helper.py','exec'),ns)
    return ns


def admin_conf_path():
    return ADMIN_ROOT/'conf'/'telegram.json'


def ensure_admin_dirs():
    if ADMIN_ROOT.is_symlink():raise RuntimeError('unsafe admin root')
    layout=[(ADMIN_ROOT,0,0,0o755),(ADMIN_ROOT/'conf',0,0,0o700),(ADMIN_ROOT/'code',0,0,0o755),
            (ADMIN_ROOT/'outbox',5000,5000,0o700),(ADMIN_ROOT/'results',0,5000,0o750),(ADMIN_ROOT/'claims',0,0,0o700)]
    for path,uid,gid,mode in layout:
        if path.is_symlink():raise RuntimeError('unsafe admin path: '+str(path))
        if not path.exists():path.mkdir(mode=mode)
        os.chown(str(path),uid,gid);os.chmod(str(path),mode)
        st=path.lstat()
        if not stat.S_ISDIR(st.st_mode) or (st.st_uid,st.st_gid,stat.S_IMODE(st.st_mode))!=(uid,gid,mode):
            raise RuntimeError('admin layout not applied: '+str(path))


def telegram_setup(prompt=input,secret=None,clock=time.monotonic):
    """Pair a NEW Telegram bot (not the VPS one) with Andrea's private chat.

    Idempotent: a valid existing configuration is reused after a getMe check.
    """
    import getpass,secrets
    secret=secret or getpass.getpass
    ns=helper_namespace()
    ensure_admin_dirs()
    path=admin_conf_path()
    if path.exists() or path.is_symlink():
        tg,chat=ns['load_config'](ADMIN_ROOT)
        me=tg('getMe')
        print('Bot Telegram gia configurato: @%s' % me.get('username'))
        return {'bot':me.get('username'),'chat_id':chat,'reused':True}
    print('Serve un bot Telegram NUOVO, dedicato al Mac (non quello del VPS).')
    print('In Telegram: @BotFather, /newbot, poi copia qui il token.')
    for attempt in range(3):
        token=secret('Token del nuovo bot (non viene mostrato): ').strip()
        try:
            tg=ns['Telegram'](token);me=tg('getMe');break
        except Exception as e:
            print('Token non valido o Telegram non raggiungibile (%s).' % type(e).__name__)
    else:raise RuntimeError('Telegram token not verified')
    if not me.get('is_bot') or not me.get('username'):raise RuntimeError('not a bot token')
    offset=None
    for u in tg('getUpdates',timeout=0):offset=u['update_id']+1
    code='%06d' % secrets.randbelow(1000000)
    print('Apri la chat con @%s, premi Avvia e invia questo codice: %s' % (me['username'],code))
    end=clock()+300;chat=None
    while clock()<end and chat is None:
        params={'timeout':20,'allowed_updates':['message']}
        if offset is not None:params['offset']=offset
        for u in tg('getUpdates',**params):
            offset=u['update_id']+1
            m=u.get('message') or {}
            c=m.get('chat') or {};f=m.get('from') or {}
            if (m.get('text') or '').strip()==code and c.get('type')=='private' and f.get('id')==c.get('id') and not f.get('is_bot'):
                chat=c['id']
    if chat is None:raise RuntimeError('Telegram pairing code not received within 5 minutes')
    if offset is not None:tg('getUpdates',offset=offset,timeout=0)
    data=json.dumps({'bot_token':token,'chat_id':chat,'bot':me['username'],'paired_at':int(time.time())}).encode()
    atomic(path,data,0o600,0,0)
    tg('sendMessage',chat_id=chat,text='MCP Andrea: questo bot approvera i comandi amministratore del Mac personale. Ogni comando va approvato singolarmente.')
    print('Abbinamento Telegram completato.')
    return {'bot':me['username'],'chat_id':chat,'reused':False}


def admin_plist():
    return plistlib.dumps({'Label':ADMIN_LABEL,'UserName':'root','GroupName':'wheel',
        'ProgramArguments':[PYTHON,'-I','-B',str(ADMIN_ROOT/'code'/'mac_admin_helper.py')],
        'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'WorkingDirectory':'/var/root',
        'StandardOutPath':str(ADMIN_ROOT/'helper.log'),'StandardErrorPath':str(ADMIN_ROOT/'helper.log'),
        'EnvironmentVariables':{'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'}})


def admin_state():
    r=subprocess.run(['/bin/launchctl','print','system/'+ADMIN_LABEL],capture_output=True,text=True,timeout=10,
                     env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C.UTF-8'})
    if r.returncode==0:
        m=re.search(r'\bpid = (\d+)\b',r.stdout)
        return {'loaded':True,'pid':int(m.group(1)) if m else None}
    if r.returncode==113 and 'Could not find service' in r.stderr:return {'loaded':False,'pid':None}
    raise RuntimeError('cannot inspect admin helper: '+r.stderr[-300:])


def admin_remove():
    if admin_state()['loaded']:run(['/bin/launchctl','bootout','system/'+ADMIN_LABEL],30)
    end=time.monotonic()+20
    while admin_state()['loaded']:
        if time.monotonic()>end:raise RuntimeError('admin helper did not stop')
        time.sleep(.2)
    if ADMIN_PLIST.exists() or ADMIN_PLIST.is_symlink():ADMIN_PLIST.unlink()


def admin_activate():
    ensure_admin_dirs()
    if admin_state()['loaded']:admin_remove()
    code=SOURCES['mac_admin_helper.py'].encode()
    if sha(code)!=SOURCE_SHA['mac_admin_helper.py']:raise RuntimeError('helper source changed')
    target=ADMIN_ROOT/'code'/'mac_admin_helper.py'
    if target.exists():
        ADMIN_BACKUP.mkdir(mode=0o700,parents=True,exist_ok=True)
        atomic(ADMIN_BACKUP/'mac_admin_helper.py',read(target),0o600)
    atomic(target,code,0o444,0,0)
    atomic(ADMIN_PLIST,admin_plist(),0o644,0,0)
    started=time.time()
    run(['/bin/launchctl','bootstrap','system',str(ADMIN_PLIST)],30)
    for _ in range(45):
        try:
            beat=json.loads(read(ADMIN_ROOT/'results'/'helper_status.json'))
            state=admin_state()
            if beat.get('version')==helper_namespace()['VERSION'] and beat.get('time',0)>=started and beat.get('pid')==state['pid']:
                return {'helper_pid':state['pid'],'helper_version':beat['version']}
        except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError):pass
        time.sleep(1)
    raise RuntimeError('admin helper heartbeat not verified')


def admin_phase(conf):
    try:
        info=admin_activate()
    except Exception as e:
        try:admin_remove()
        except Exception as cleanup:e=RuntimeError(str(e)+'; cleanup: '+str(cleanup))
        record('active_agent_admin_failed',version=NEW_VERSION,reason=str(e)[:1200],backup=str(BACKUP))
        print(json.dumps({'status':'agent_active_admin_failed','reason':str(e)[:300]},indent=2))
        raise
    record('active',version=NEW_VERSION,backup=str(BACKUP),admin=info,telegram_bot=conf.get('bot'),
           hashes={n:sha(b) for n,b in PAYLOAD.items()},helper_sha256=SOURCE_SHA['mac_admin_helper.py'],rental_touched=False)
    print(json.dumps({'status':'active','admin':info,'telegram_bot':conf.get('bot')},indent=2))


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('one action required')
    main(sys.argv[1])
