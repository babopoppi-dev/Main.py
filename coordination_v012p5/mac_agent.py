#!/usr/bin/env python3
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
from file_tools import FileTools, FileToolError
from file_schema import FILE_NAMES
from search_tools import SearchTools, SEARCH_NAMES
from agent_shell import AgentShell
from work_sessions import WorkSessions, MUTATIONS
from work_schema import WORK_NAMES
from upload_tools import Uploads
from net_proxy import ALLOWED_HOSTS, PROFILES
from admin_schema import ADMIN_NAMES
from mac_admin_client import AdminClient
from mac_guard import require_identity, stop_dedicated_children
from mac_policy import profile
from mac_projects import load_projects, forbidden_component

BASE = Path('/Library/MCPAndreaMacMioV09')
STATE = BASE / 'state'
WORK = Path('/Users/Shared/MCPAndreaMacMio/workspace')
URL = 'wss://mcp.andreababini.it/agent/ws/mac_mio'
VERSION = '0.12-personal-5'
# Absolute: the install-time selftest runs the agent code from its preflight copy.
PROJECTS = BASE / 'code' / 'projects.json'
READ_OPS = {'read_file', 'read_multiple_files', 'list_directory', 'get_file_info', 'read_binary'}
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
    def __init__(self, work=WORK, state=STATE, projects=None):
        self.work, self.state = Path(work), Path(state)
        protected = (str(self.work), str(self.state), str(BASE), '/Library', '/System', '/Users/Shared')
        self.projects_error = None
        if projects is None and self.work != WORK:
            projects = {'rw': [], 'ro': [], 'exclude': [], 'ro_exclude': []}  # test agents: never the real list
        if projects is None:
            try:
                projects = load_projects(PROJECTS, protected)
            except Exception as exc:
                # Fail closed but stay reachable: no project roots, error visible in metadata.
                LOG.error('projects configuration rejected: %s', exc)
                self.projects_error = type(exc).__name__ + ': ' + str(exc)[:200]
                projects = {'rw': [], 'ro': [], 'exclude': [], 'ro_exclude': []}
        self.projects = projects
        self.files = FileTools([str(self.work)] + projects['rw'], str(self.state / 'operations'),
                               denied_roots=projects['exclude'])
        self.ro = FileTools(projects['ro'], str(self.state / 'operations-ro'),
                            denied_roots=projects['ro_exclude']) if projects['ro'] else None
        self.ro_search = SearchTools(self.ro) if self.ro else None
        self.shell = AgentShell(self.files, str(self.work), str(self.state / 'shell-logs'), capable=True,
                                projects=projects, ro_files=self.ro)
        self.logs = FileTools([str(self.state / 'shell-logs')], str(self.state / 'log-reader'), max_file_bytes=16*1024*1024)
        self.search = SearchTools(self.files)
        self.recent = []
        self.work_sessions = WorkSessions(str(self.state / 'work-sessions'), self.files)
        self.files.lock_provider = self.work_sessions.lock_provider
        self.uploads = Uploads(self.files, str(self.state / 'uploads'))
        self.admin = AdminClient()
        self.work_watchdog = None

    def project_engine(self, args):
        """'ro' for read-only project paths, 'main' for workspace and read-write roots; never mixed."""
        paths = [args[k] for k in ('path', 'file_path', 'source', 'destination') if isinstance(args.get(k), str)]
        if isinstance(args.get('paths'), list):
            paths += [x for x in args['paths'] if isinstance(x, str)]
        def owner(engine, p):
            if engine is None:return None
            try:
                _, root, _ = engine._path(p)
                return root
            except FileToolError:
                return None
        kinds = set()
        for p in paths:
            root = owner(self.ro, p)
            if root is None:
                root = owner(self.files, p); kinds.add('main')
            else:
                kinds.add('ro')
            if root and root != str(self.work) and forbidden_component(os.path.normpath(p), root):
                raise PermissionError('path inside a forbidden area (Bitcoin, La Marruca, LiDAR, credentials)')
        if len(kinds) > 1:
            raise PermissionError('one call cannot mix read-only projects with other roots')
        return 'ro' if kinds == {'ro'} else 'main'

    def file_call(self, op, args, identity):
        self.search.guard_mutation(op)
        path = args.get('path')
        log_root = str(self.state / 'shell-logs')
        is_log = isinstance(path, str) and (path == log_root or path.startswith(log_root + '/'))
        engine = self.logs if is_log else self.files
        if is_log and op not in ('read_file', 'get_file_info', 'list_directory', 'read_binary'):
            raise PermissionError('shell logs are read-only')
        if not is_log and self.project_engine(args) == 'ro':
            if op not in READ_OPS:
                raise PermissionError('read-only project root')
            engine = self.ro
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
                remaining = self.shell_remaining(self.shell.owner)
            except PermissionError:
                remaining = 0
            if remaining <= 0:
                await self.shell.disable()
        active = {x['work_session_id'] for x in self.work_sessions.snapshot()['work_sessions']}
        for engine in self.searches():
            for job in list(engine.jobs.values()):
                if job['status'] == 'running' and job['owner'].startswith('work:') and job['owner'][5:] not in active:
                    await engine.stop(job['owner'], job['id'])
        for uid, job in list(self.uploads.jobs.items()):
            if job['owner'][5:] not in active:
                self.uploads._drop(uid)

    def searches(self):
        return [self.search] + ([self.ro_search] if self.ro_search else [])

    def shell_remaining(self, identity):
        """The shell writes the workspace and the read-write project roots: all must be locked."""
        return min(self.work_sessions.remaining(identity, p) for p in [str(self.work)] + self.projects['rw'])

    async def search_call(self, op, args, identity):
        if self.ro_search is not None:
            if op == 'start_search' and isinstance(args.get('path'), str) and self.project_engine(args) == 'ro':
                return await self.ro_search.dispatch(op, args, identity)
            if op != 'start_search' and args.get('search_id') in self.ro_search.jobs:
                return await self.ro_search.dispatch(op, args, identity)
        elif op == 'start_search' and isinstance(args.get('path'), str):
            self.project_engine(args)
        return await self.search.dispatch(op, args, identity)

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
            for engine in self.searches():await engine.close()
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
            for engine in self.searches():
                for job in list(engine.jobs.values()):
                    if job['owner'] == identity and job['status'] == 'running':
                        await engine.stop(identity,job['id'])
            for uid in self.uploads.owned_by(identity):self.uploads._drop(uid)
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
                result = await self.work_call(op,args,caller)
                # Successful session/lock calls are recorded under their session.
                sid = result.get('work_session_id') if op=='work_session' and isinstance(result,dict) else work_id
                if isinstance(sid,str):identity = 'work:'+sid
            elif op in SEARCH_NAMES:
                result = await self.search_call(op, args, identity)
            elif op == 'upload_file':
                if args.get('action') == 'commit':self.search.guard_mutation(op)
                result = self.uploads.dispatch(identity, args)
            elif op == 'mac_admin_request':
                result = self.admin.request(caller, identity, args)
            elif op == 'mac_admin_result':
                result = self.admin.result(caller, args)
            elif op in FILE_NAMES:
                result = self.file_call(op, args, identity)
            elif op == 'enable_full_shell':
                if 'minutes' not in args or set(args) - {'minutes','network'}:raise ValueError('unexpected enable arguments')
                if args['minutes']*60 > self.shell_remaining(identity):
                    raise PermissionError('work session and locks on the workspace and on every read-write project root must outlast the shell lease')
                result = await self.shell.enable(identity, args['minutes'], args.get('network','none'))
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
                for engine in self.searches():result['active_locks'] += engine.active()
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
        for engine in self.searches():await engine.close()
        await self.shell.disable()
        self.uploads.close(); self.work_sessions.close(); self.files.close(); self.logs.close()
        if self.ro:self.ro.close()


def metadata(dispatcher=None):
    projects = dispatcher.projects if dispatcher else {'rw': [], 'ro': []}
    return {'hostname': socket.gethostname(), 'platform': 'darwin', 'python': sys.version.split()[0],
            'uid': os.getuid(), 'machine': 'mac_mio', 'agent_version': VERSION,
            'full_shell_capable': True, 'file_tools_version': '0.8', 'search_version': '0.10.1',
            'shell_backend': 'seatbelt-v09', 'shell_network': 'disabled; profiles on request',
            'shell_network_profiles': {k: sorted(v) for k, v in PROFILES.items()},
            'shell_network_hosts': sorted(ALLOWED_HOSTS), 'shell_scope': str(WORK),
            'allowed_roots': [str(WORK)] + projects['rw'] + projects['ro'],
            'project_roots': {'rw': projects['rw'], 'ro': projects['ro']}, 'projects_version': '0.12.5',
            'projects_error': getattr(dispatcher, 'projects_error', None),
            'projects_policy': 'rw: writes need work session + covering lock; ro: read and search only; shell reads ro+rw, writes rw (needs locks on rw roots); Bitcoin, La Marruca, LiDAR, Library, keychains and credential folders always denied',
            'read_only_log_root': str(STATE / 'shell-logs'),
            'coordination_version':'0.11.0', 'work_session_required':True,
            'mac_admin_version': '0.12.0', 'mac_admin': 'each root command approved individually on Telegram',
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
            for engine in dispatcher.searches():await engine.close()
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
        await ws.send(json.dumps({'type':'hello','meta':metadata(dispatcher)}))
        connected_receipt()
        async def beat():
            while True:
                await asyncio.sleep(15)
                await ws.send(json.dumps({'type':'hello','meta':metadata(dispatcher)}))
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
