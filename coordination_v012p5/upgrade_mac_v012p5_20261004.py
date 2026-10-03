#!/usr/bin/env python3
"""Hash-pinned local update of the personal-Mac agent: MCP Andrea v0.12 p5 (real project folders, point E)."""
import base64,contextlib,fcntl,hashlib,json,os,plistlib,re,stat,subprocess,sys,tempfile,time,zlib
from pathlib import Path
ROOT=Path('/Library/MCPAndreaMacMioV09')
BASE=ROOT/'code'
SELF=ROOT/'upgrade_v012p5_20261004.py'
BACKUP=ROOT/'backup/v012p5_20261004'
RECEIPT=ROOT/'v012p5_20261004_receipt.json'
TEST_CODE=ROOT/'preflight-v012p5_20261004'
TEST_DATA=Path('/Users/Shared/MCPAndreaMacMio/preflight-v012p5_20261004')
GUARD=ROOT/'state/operations/guard'
LABEL='it.andreababini.mcp-mac-mio-v09'
PLIST=Path('/Library/LaunchDaemons')/(LABEL+'.plist')
PLIST_SHA='c355532f913809d9a183e0e4b4a55e226dfc850914dbe4992582d5d3bf7fd406'
PYTHON='/usr/bin/python3'
OLD_VERSION='0.12-personal-4'
NEW_VERSION='0.12-personal-5'
PAYLOAD={}
TESTS={}
SMOKE_INFO={}
SYSTEM_AGENTS=frozenset(['/usr/libexec/containermanagerd', '/usr/libexec/lsd', '/usr/libexec/secinitd', '/usr/libexec/trustd --agent', '/usr/sbin/cfprefsd agent', '/usr/sbin/distnoted agent'])
ORIGINAL={'mac_agent.py': '1ba9ae0044c667f3899b812d61dfa5dad88429ff20cfae23b607fd611a54fa35', 'mac_child.py': '24d7c1701eeab38885fbf51ea7b3bb0d368ebe102c1740c97c95efa6c6f8de1e', 'mac_policy.py': '10f7bdfbaa44eb72108dd924ab3a2d55736fcc1d0b37ab5ad898f8f569ee861e', 'mac_shell.py': 'bdb9960147174eb931671706bbd2fe6da3c61c6f7b26731a95b2ac101e8d8cff', 'mac_projects.py': None}
DEPENDENCIES={'admin_schema.py': 'a11e96523aa9571a3b64b4df9567d9b6d72f15fe6e4f09e39e2a19b4b13c5a03', 'agent_shell.py': 'd62822814d97c52468ca8aad4a43fa1bf8e424b8cd8200ac88ea4e2c9c33e21c', 'file_schema.py': 'a981512019127689a443ca2717968d76e1509f4366075d5b39f6eee28218c1a4', 'file_tools.py': '002d2382b7670e6a9a468facbb951c1f9a20431c70fbba2d8c370fffea5c24cc', 'mac_admin_client.py': '686e33d61c74dbd8c76485293c53d92ea8568297cf91ef44e79a13516d76f181', 'mac_clock.py': '6553b061c51e2da286296231538796dd086404b1dbacca37bd9299e2628dae07', 'mac_guard.py': '8d3f7afe80daae81e8f3a3471229423d14777eb84358a3f57621e74149dc57bc', 'mac_watchdog.py': '66dc9cbe74dd74931979200a9eda4032461a31c1687f5a2ca64a4441f21c4c99', 'net_proxy.py': '550deb2441af4fbbd3b89ed7e8204339e439e1049c98ca2a01e6e73c50bfd48c', 'search_schema.py': 'c6d111d440eec78bb08e27673fd832479f02446ac2abc25fb5237e12d47ee20d', 'search_tools.py': 'f5722cdf394ad1b98575e5f00d6af483a37c6c456adb7465e1213cdc002a625f', 'shell_common.py': '254dd32f26295b9376b1201cf7449832b8d9927018d0b9e208cc2a950b954f3f', 'upload_tools.py': 'fbea947e87afd04e7bbf54d1075c3c2852db3a415ac65e65e6fffde07834abc7', 'work_schema.py': '40eaf6a37998e42d9cdd6e3c28853e1f22cfeff1fc9b16bec8d391abc04817df', 'work_sessions.py': '4a7b736ef6d915c2439cd8aa63e09f0d40410325fa5e9387070f807d518b1861'}
TEST_NAMES=['mac_agent.py', 'mac_child.py', 'mac_policy.py', 'mac_shell.py', 'mac_projects.py', 'admin_schema.py', 'agent_shell.py', 'file_schema.py', 'file_tools.py', 'mac_admin_client.py', 'mac_clock.py', 'mac_guard.py', 'mac_watchdog.py', 'net_proxy.py', 'search_schema.py', 'search_tools.py', 'shell_common.py', 'upload_tools.py', 'work_schema.py', 'work_sessions.py', 'test_work_core.py', 'test_search.py', 'test_v012.py', 'test_files_v012.py', 'test_mac_admin.py', 'test_projects.py', 'mac_admin_helper.py', 'mac_v012_selftest.py', 'cg_tools.py']
SOURCE_SHA={'mac_agent.py': '88c3c918ab352ec0bb4d2403f620678595d37f18fae432f1eb1f06bf6bd0fa25', 'mac_child.py': 'b0658e64b6a243f6f981880cdb2d39d8263daa581f8c38455d597811c05b26b2', 'mac_policy.py': '83be204b38587453e7d390940215c86aecb1e0abfb40cc8057e68117e4375d4d', 'mac_shell.py': 'f77b95512308aa7daf737f7b75be2690804d55010614cde2fa3cbc9f3046f686', 'mac_projects.py': 'a34becd63436aa541e3c09820f48a9f24b7e1578a7fb8309217e0442f459c508', 'test_work_core.py': '08aa60ad5317db32fa515ba21a834b3ae22dbed014b8a240168deefa7ea15380', 'test_search.py': 'c23c7dabe8450b95aa48ae4117b4c94caa38d6a8477447b37698def327bf5a5b', 'test_v012.py': '7c3811d1899f1f623a6b20957aef484ef7640fce449e1504243dcbbd76c1864a', 'test_files_v012.py': 'b23873ec8879851d36d6032a8fe025833934896582d66b0c45dee983ef951068', 'test_mac_admin.py': '380666c26320a69804e93cd42b19a010f078ab2a2f34d182b44cb8694dd8611f', 'test_projects.py': '55b37bc710cc3de7f49fa840bf80e8ef81a52a92074f97c646a94f6e7cb920dd', 'mac_admin_helper.py': '75285c6b156f85837952e9532db8f32920bc646e89ca0a7147939800e6e20c70', 'mac_v012_selftest.py': 'daae680b726f3bd3721b4320c0a1e83655f92095ad64f9213cdf0b04c4b86496', 'cg_tools.py': '613c0c56c6bef324e7e4b28c2f2ee2c7b40da7639f87b5d3fddb0ec4f567d733'}
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
''',
'mac_child.py': r'''#!/usr/bin/env python3
"""Trusted resource-limit setup followed by exec into the seatbelt sandbox."""
import json
import os
import re
from pathlib import Path
import resource
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mac_guard import require_identity
from mac_policy import profile


def main():
    require_identity()
    if len(sys.argv) != 5:
        raise SystemExit('workspace cwd command tty required')
    workspace, cwd, command, tty_path = sys.argv[1:]
    projects = None
    raw = os.environ.get('MCP_PROJECTS')
    if raw:
        projects = json.loads(raw)
        if not isinstance(projects, dict) or set(projects) != {'rw', 'ro', 'exclude'} or \
                not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in projects.values()):
            raise SystemExit('invalid project list')
    roots = [workspace] + (projects['rw'] + projects['ro'] if projects else [])
    if not any(os.path.commonpath([r, cwd]) == r for r in roots):
        raise SystemExit('cwd outside workspace and project roots')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16777216, 16777216))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': workspace,
           'TMPDIR': workspace + '/.tmp', 'LANG': 'en_US.UTF-8', 'TERM': 'xterm'}
    # The agent passes the per-lease proxy credential in the environment,
    # never in argv (visible to every local user through ps).
    git = []
    if projects and projects['rw'] + projects['ro']:
        # The shell runs as mcp_andrea on repositories owned by Andrea; the seatbelt
        # already limits what it can read, and Apple git (2.39) knows only '*' as a pattern.
        git.append(('safe.directory', '*'))
    port, token = os.environ.get('MCP_NET_PORT'), os.environ.get('MCP_NET_TOKEN')
    net_port = None
    if port or token:
        if not (port and port.isdigit() and token and re.fullmatch(r'[A-Za-z0-9_-]{32}', token)):
            raise SystemExit('invalid network lease')
        net_port = int(port)
        proxy = 'http://mcp:%s@127.0.0.1:%d' % (token, net_port)
        env.update({'HTTPS_PROXY': proxy, 'https_proxy': proxy, 'NO_PROXY': '', 'no_proxy': '',
                    'GIT_SSL_CAINFO': '/etc/ssl/cert.pem', 'SSL_CERT_FILE': '/etc/ssl/cert.pem',
                    'GIT_TERMINAL_PROMPT': '0',
                    'PIP_PROXY': proxy, 'npm_config_https_proxy': proxy, 'npm_config_proxy': proxy})
        git.append(('http.proxyAuthMethod', 'basic'))
    if git:
        env['GIT_CONFIG_COUNT'] = str(len(git))
        for i, (key, value) in enumerate(git):
            env['GIT_CONFIG_KEY_%d' % i], env['GIT_CONFIG_VALUE_%d' % i] = key, value
    os.execve('/usr/bin/sandbox-exec', ['/usr/bin/sandbox-exec', '-p',
              profile(workspace, tty_path, net_port, projects), '/bin/bash', '--noprofile', '--norc',
              '-c', command], env)


if __name__ == '__main__':
    main()
''',
'mac_policy.py': r'''"""Seatbelt policy for one offline workspace; no shell access to agent state."""
import contextlib
import json
import re
import os
from pathlib import Path
import stat
import sys


def safe_executables():
    """Permit only checked system commands and the selected Python runtime."""
    candidates = []
    for directory in ('/bin', '/usr/bin'):
        candidates.extend(Path(directory).iterdir())
    runtime = Path(os.path.realpath(sys.executable))
    runtime_candidates = [runtime]
    # Apple's Python command forwards to its framework application executable.
    framework_app = Path(sys.base_prefix) / 'Resources/Python.app/Contents/MacOS/Python'
    if framework_app.exists():
        runtime_candidates.append(framework_app)
    allowed = set()
    for item in candidates:
        path = item.resolve()
        try:
            s = path.stat()
            if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o6022:
                continue
            if not s.st_mode & 0o111:
                continue
            for parent in path.parents:
                ps = parent.lstat()
                if not stat.S_ISDIR(ps.st_mode) or ps.st_uid != 0 or ps.st_mode & 0o022:
                    raise PermissionError('untrusted executable parent')
        except (FileNotFoundError, PermissionError):
            continue
        allowed.add(str(path))
    # Trust the selected developer Python runtime only when the service identity
    # cannot modify its executable or any parent directory.
    for item in runtime_candidates:
        path = item.resolve()
        for p in [path] + list(path.parents):
            s = p.lstat()
            if s.st_uid not in (0, 501) or s.st_mode & 0o6002:
                raise PermissionError('unsafe Python runtime ownership or mode')
            if s.st_mode & 0o020 and s.st_gid not in (0, 80):
                raise PermissionError('service-writable Python runtime')
        if not stat.S_ISREG(path.stat().st_mode):
            raise PermissionError('regular Python runtime required')
        allowed.add(str(path))
    return sorted(allowed)


def trusted_tree(path):
    """A system directory the service identity cannot modify, or None."""
    path = Path(path)
    try:
        for p in [path] + list(path.parents):
            s = p.lstat()
            # Group write is tolerated only for wheel/admin; uid5000 is in neither.
            if (not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o002
                    or s.st_mode & 0o020 and s.st_gid not in (0, 80)):
                return None
    except FileNotFoundError:
        return None
    return str(path)


def developer_dirs():
    """Command Line Tools and the selected developer directory (git, xcrun)."""
    found = []
    candidates = ['/Library/Developer/CommandLineTools']
    with contextlib.suppress(OSError):
        candidates.append(os.path.realpath('/private/var/db/xcode_select_link'))
    for base in candidates:
        if not base.startswith(('/Library/Developer/', '/Applications/')):
            continue
        usr = trusted_tree(os.path.join(base, 'usr'))
        if usr and usr not in found:
            found.append(usr)
    return found


# Trust evaluation for TLS; needed only while the GitHub lease is active.
TLS_SERVICES = ('com.apple.trustd', 'com.apple.trustd.agent', 'com.apple.SecurityServer', 'com.apple.ocspd')


# Names always denied inside project roots, also for the shell (mirrors mac_projects.FORBIDDEN).
FORBIDDEN_SUBSTRINGS = ('bitcoin', 'marruca', 'lidar', 'keychain')
FORBIDDEN_NAMES = ('.ssh', '.gnupg', '.aws', '.config', 'library', '.trash')
PROJECT_PATH = re.compile(r'/Users/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+')


def _caseless(word):
    return ''.join('[%s%s]' % (c.upper(), c.lower()) if c.isalpha() else re.escape(c) for c in word)


def project_rules(projects):
    """Seatbelt rules for point E: read ro+rw roots, write/exec rw roots, deny excluded areas last."""
    rw, ro, exclude = projects.get('rw', []), projects.get('ro', []), projects.get('exclude', [])
    for p in rw + ro + exclude:
        if not isinstance(p, str) or not PROJECT_PATH.fullmatch(p) or os.path.normpath(p) != p:
            raise ValueError('invalid project path for the shell profile')
    rules = []
    for p in ro + rw:
        rules.append('(allow file-read* (subpath ' + json.dumps(p) + '))')
    for p in rw:
        rules.append('(allow file-write* (subpath ' + json.dumps(p) + '))')
        rules.append('(allow process-exec* (subpath ' + json.dumps(p) + '))')
    denied = []
    for p in exclude:
        denied.append('(subpath ' + json.dumps(p) + ')')
    roots = ro + rw
    outer = [r for r in roots if not any(r != q and r.casefold().startswith(q.casefold() + '/') for q in roots)]
    for root in outer:
        base = '^' + root.replace('.', '\\.') + '/(.*/)?'
        for word in FORBIDDEN_SUBSTRINGS:
            denied.append('(regex #"' + base + '[^/]*' + _caseless(word) + '[^/]*(/.*)?$")')
        for name in FORBIDDEN_NAMES:
            denied.append('(regex #"' + base + _caseless(name) + '(/.*)?$")')
    if denied:
        rules.append('(deny file-read* file-write* process-exec* ' + ' '.join(denied) + ')')
    return rules


def profile(workspace, tty_path=None, net_port=None, projects=None):
    workspace = os.path.realpath(workspace)
    if not workspace.startswith('/Users/') or workspace in ('/Users', '/Users/Shared'):
        raise ValueError('narrow workspace required')
    if tty_path and (not tty_path.startswith('/dev/ttys') or '/' in tty_path[5:]):
        raise ValueError('expected a macOS PTY')
    rules = ['(version 1)', '(deny default)', '(deny network*)',
             '(deny mach-lookup)', '(deny mach-register)', '(deny appleevent-send)',
             '(deny file-read*)', '(allow file-read-metadata)', '(deny file-write*)',
             '(deny file-link)', '(deny signal)',
             '(allow signal (target self))', '(allow signal (target children))']
    rules += ['(allow process-fork)', '(allow sysctl-read)']
    rules.append('(allow process-exec* (subpath ' + json.dumps(workspace) + '))')
    for executable in safe_executables():
        rules.append('(allow process-exec* (literal ' + json.dumps(executable) + '))')
    for path in ['/usr', '/bin', '/sbin', '/System', '/Library/Apple',
                 '/Library/Developer/CommandLineTools',
                 '/private/var/db/dyld',
                 '/private/var/db/timezone', workspace]:
        rules.append('(allow file-read* (subpath ' + json.dumps(path) + '))')
    # dyld needs read access to the root directory itself (not its contents).
    for path in ['/', '/dev/null', '/dev/random', '/dev/urandom', '/private/etc/localtime']:
        rules.append('(allow file-read* (literal ' + json.dumps(path) + '))')
    for usr in developer_dirs():
        rules.append('(allow file-read* (subpath ' + json.dumps(usr) + '))')
        for sub in ('bin', 'libexec'):
            rules.append('(allow process-exec* (subpath ' + json.dumps(usr + '/' + sub) + '))')
    for path in ['/private/var/db/xcode_select_link', '/private/var/select/developer_dir']:
        rules.append('(allow file-read* (literal ' + json.dumps(path) + '))')
    if net_port is not None:
        if type(net_port) is not int or not 1024 <= net_port <= 65535:
            raise ValueError('invalid proxy port')
        rules.append('(allow network-outbound (remote ip "localhost:%d"))' % net_port)
        rules.append('(allow file-read* (subpath "/private/etc/ssl"))')
        rules.append('(allow mach-lookup ' + ' '.join('(global-name %s)' % json.dumps(n) for n in TLS_SERVICES) + ')')
    rules.append('(allow file-write* (subpath ' + json.dumps(workspace) + '))')
    rules.append('(allow file-write* (literal "/dev/null"))')
    if projects:
        rules += project_rules(projects)
    if tty_path:
        rules.append('(allow file-read* file-write* (literal ' + json.dumps(tty_path) + '))')
        # Terminal control (window size, line discipline) on the session's own PTY only:
        # without it macOS readline (libedit) hangs before the Python/REPL prompt.
        rules.append('(allow file-ioctl (literal ' + json.dumps(tty_path) + '))')
    return '\n'.join(rules) + '\n'
''',
'mac_shell.py': r'''"""macOS shell lease for one work session, uid5000 only.

Up to MAX_RUNNING concurrent processes share the lease, the workspace guard
and the watchdog. Stopping one process kills its process group; the full
uid5000 cleanup runs when the last one ends, on stop of the last one and
when the lease ends. Network is off unless the lease selects a profile.
"""
import asyncio
import contextlib
import errno
import json
import fcntl
import os
from pathlib import Path
import pty
import stat
import struct
import subprocess
import sys
import termios
import time
import uuid

from shell_common import IsolatedShell
from mac_guard import require_identity, stop_dedicated_children
from mac_clock import lease_deadline
from net_proxy import GitHubProxy, PROFILES
from file_tools import FileToolError
from mac_projects import forbidden_component, shell_view



def set_winsize(fd, rows=24, cols=80):
    """Give the PTY a real size, as an interactive terminal has (Desktop Commander uses 80x24)."""
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))

class MacShell(IsolatedShell):
    LOG_LIMIT = 16 * 1024 * 1024
    MAX_RUNNING = 4

    def __init__(self, files, workspace, logs, capable=False, projects=None, ro_files=None):
        super().__init__(files, workspace, capable)
        # Point E: validated by the agent at start-up; empty means workspace only.
        self.projects = projects or {'rw': [], 'ro': [], 'exclude': []}
        self.ro_files = ro_files
        self.code = Path(__file__).resolve().parent
        self.logs = Path(logs)
        self.logs.mkdir(mode=0o700, exist_ok=True)
        self.watchdog = None
        self.network = 'none'
        self.proxy = GitHubProxy(log=self.log_network)
        self.network_log = []
        self.guard_fd = None

    def log_network(self, event):
        self.network_log.append(dict(event, time=time.time()))
        del self.network_log[:-50]

    async def enable(self, caller, minutes, network='none'):
        require_identity()
        if network != 'none' and network not in PROFILES:
            raise ValueError('network must be none or one of: ' + ', '.join(sorted(PROFILES)))
        if self.owner == caller and time.monotonic() < self.until and network != self.network:
            if any(not j['done'].is_set() for j in self.jobs.values()):
                raise PermissionError('stop the running shell before changing network access')
        result = await super().enable(caller, minutes)
        await self.proxy.stop()
        if network != 'none':
            await self.proxy.start(PROFILES[network])
        self.network = network
        if self.watchdog and self.watchdog.poll() is None:
            self.refresh_watchdog()
        result['network'] = (network + ' via agent proxy: ' + ', '.join(sorted(PROFILES[network]))
                             if network != 'none' else 'disabled')
        result['maximum_active_sessions'] = self.MAX_RUNNING
        return result

    async def disable(self):
        try:
            return await super().disable()
        finally:
            self.network = 'none'
            await self.proxy.stop()

    def child_env(self):
        env = {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
        if self.network != 'none' and self.proxy.running:
            env.update(MCP_NET_PORT=str(self.proxy.address()), MCP_NET_TOKEN=self.proxy.token)
        if self.projects['rw'] or self.projects['ro']:
            env['MCP_PROJECTS'] = json.dumps(shell_view(self.projects), sort_keys=True)
        return env

    def cwd(self, raw):
        raw = self.workspace if raw is None else raw
        engine = self.files
        if self.ro_files is not None:
            try:
                self.ro_files._path(raw)
                engine = self.ro_files
            except FileToolError:
                pass
        path, root, _ = engine._path(raw)
        if root != self.workspace:
            if root not in self.projects['rw'] + self.projects['ro']:
                raise PermissionError('cwd must be inside the shell workspace or a project root')
            if forbidden_component(path, root):
                raise PermissionError('cwd inside a forbidden area')
        with engine._directory(path):
            pass
        return path

    def _trusted_code(self):
        for name in ('mac_guard.py', 'mac_child.py', 'mac_watchdog.py', 'mac_policy.py', 'mac_clock.py'):
            s = (self.code / name).lstat()
            if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
                raise PermissionError('root-owned shell helpers required')
        for p in [self.code] + list(self.code.parents):
            s = p.lstat()
            if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
                raise PermissionError('unsafe helper parent')

    def _start_watchdog(self):
        self.watchdog = subprocess.Popen(
            [sys.executable, '-I', '-B', str(self.code / 'mac_watchdog.py')],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, start_new_session=True, cwd='/',
            env={'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'})
        self.refresh_watchdog()

    def refresh_watchdog(self):
        self.watchdog.stdin.write((str(lease_deadline(self.until)) + '\n').encode())
        self.watchdog.stdin.flush()

    def _cleanup_uid(self):
        stop_dedicated_children()
        if self.watchdog:
            if self.watchdog.stdin:
                with contextlib.suppress(BrokenPipeError):
                    self.watchdog.stdin.close()
            self.watchdog.wait(timeout=3)
            self.watchdog = None

    def _drain(self, job):
        for _ in range(16):
            try:
                chunk = os.read(job['fd'], 8192)
            except BlockingIOError:
                return
            except OSError as exc:
                if exc.errno not in (errno.EIO, errno.EBADF):
                    raise
                return
            if not chunk:
                return
            remaining = self.LOG_LIMIT - job['log_bytes']
            if remaining > 0:
                job['log'].write(chunk[:remaining])
                job['log_bytes'] += min(len(chunk), remaining)
            job['output'].extend(chunk)
            excess = len(job['output']) - self.MAX_OUTPUT
            if excess > 0:
                del job['output'][:excess]; job['base'] += excess
            if len(chunk) > remaining:
                job['log_complete'] = False
                job['stop_reason'] = 'output limit reached'
                self._kill(job)
                return

    def running(self):
        return [j for j in self.jobs.values() if not j['done'].is_set()]

    def _acquire_guard(self):
        fd = os.open('guard', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.files.state_fd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.files._check_journal()
        except BaseException:
            os.close(fd)
            raise
        self.guard_fd = fd

    def _release_guard(self):
        if self.guard_fd is not None:
            os.close(self.guard_fd)
            self.guard_fd = None

    def _kill(self, job):
        """Stop one process group, or everything when it is the last one."""
        if any(j is not job for j in self.running()):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(job['proc'].pid, 9)
        else:
            self._cleanup_uid()

    async def start(self, caller, command, cwd=None):
        require_identity()
        self.allowed(caller)
        if not isinstance(command, str) or not command.strip() or '\0' in command or len(command.encode()) > 32768:
            raise ValueError('command required; maximum32768 bytes')
        running = self.running()
        if len(running) >= self.MAX_RUNNING:
            raise PermissionError('at most %d concurrent shell processes; stop one first' % self.MAX_RUNNING)
        if running and self.guard_fd is None:
            raise RuntimeError('shell guard lost; disable the shell')
        while len(self.jobs) >= 16 and len(self.jobs) > len(running):
            done = next(k for k, j in self.jobs.items() if j['done'].is_set())
            self.jobs.pop(done)
        cwd = self.cwd(cwd)
        self._trusted_code()
        first = not running
        master = slave = -1
        log = None
        started = False
        try:
            if first:
                self._acquire_guard()
            sid = uuid.uuid4().hex
            logpath = self.logs / (sid + '.log')
            fd = os.open(str(logpath), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            log = os.fdopen(fd, 'wb', buffering=0)
            master, slave = pty.openpty()
            set_winsize(slave)
            os.set_blocking(master, False)
            started = True
            if first or not self.watchdog or self.watchdog.poll() is not None:
                self._start_watchdog()
            proc = subprocess.Popen(
                [sys.executable, '-I', '-B', str(self.code / 'mac_child.py'),
                 self.workspace, cwd, command, os.ttyname(slave)],
                stdin=slave, stdout=slave, stderr=slave, close_fds=True,
                start_new_session=True, cwd=cwd, env=self.child_env())
            os.close(slave); slave = -1
            job = {'id': sid, 'owner': caller, 'proc': proc, 'fd': master,
                   'output': bytearray(), 'base': 0, 'cursor': 0, 'command': command[:200],
                   'cwd': cwd, 'started_at': time.time(),
                   'done': asyncio.Event(), 'closed': False, 'log': log,
                   'log_path': str(logpath), 'log_bytes': 0, 'log_complete': True}
            self.jobs[sid] = job
            asyncio.get_running_loop().add_reader(master, self._drain, job)
            job['watcher'] = asyncio.create_task(self._watch_job(job))
            master = -1; log = None
            return {'session_id': sid, 'pid': proc.pid, 'running': proc.poll() is None,
                    'scope': self.workspace, 'uid': 5000, 'concurrent': len(self.running()),
                    'network': self.network if 'MCP_NET_PORT' in self.child_env() else 'disabled'}
        except BaseException:
            if first:
                if started:
                    self._cleanup_uid()
                self._release_guard()
            raise
        finally:
            for fd in (master, slave):
                if fd >= 0:
                    os.close(fd)
            if log:
                log.close()

    async def _watch_job(self, job):
        try:
            while job['proc'].poll() is None:
                if self.watchdog and self.watchdog.poll() is not None:
                    job['stop_reason'] = 'watchdog ended unexpectedly'
                    self._cleanup_uid()
                await asyncio.sleep(.05)
            # The last process also takes down daemons detached by any of them.
            if not any(j is not job for j in self.running()):
                self._cleanup_uid()
            self._drain(job)
        finally:
            if not job['closed']:
                job['closed'] = True
                asyncio.get_running_loop().remove_reader(job['fd'])
                os.close(job['fd']); job['log'].close()
            job['done'].set()
            if not self.running():
                self._release_guard()

    async def _terminate(self, job):
        if not job['done'].is_set():
            self._kill(job)
            await asyncio.wait_for(job['done'].wait(), 3)

    def processes(self):
        """Read-only inventory of uid5000 processes (the agent itself excluded)."""
        out = subprocess.run(['/bin/ps', '-axo', 'uid=,pid=,ppid=,etime=,args='], capture_output=True,
                             text=True, timeout=5, env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}).stdout
        rows = []
        for line in out.splitlines()[:5000]:
            p = line.split(None, 4)
            if len(p) >= 4 and p[0] == '5000' and int(p[1]) != os.getpid():
                rows.append({'pid': int(p[1]), 'ppid': int(p[2]), 'elapsed': p[3],
                             'command': (p[4] if len(p) == 5 else '')[:300]})
        return rows[:500]

    async def session(self, caller, args):
        action = args.get('action')
        if action == 'list':
            self.identity(caller)
            return {'sessions': [{'session_id': j['id'], 'command': j['command'], 'cwd': j['cwd'],
                                  'started_at': j['started_at'], 'running': not j['done'].is_set(),
                                  'exit_code': j['proc'].poll(), 'pid': j['proc'].pid}
                                 for j in self.jobs.values() if j['owner'] == caller],
                    'maximum_active_sessions': self.MAX_RUNNING}
        if action == 'processes':
            self.allowed(caller)
            return {'processes': self.processes()}
        return await super().session(caller, args)

    def read(self, caller, sid):
        result = super().read(caller, sid)
        job = self.lookup(caller, sid)
        result.update(log_path=job['log_path'], log_complete=job['log_complete'],
                      stop_reason=job.get('stop_reason'))
        return result

    def working(self):
        value = super().working()
        value['shell_network'] = 'github-only' if self.network == 'github' and self.proxy.running else 'disabled'
        value['network_events'] = list(self.network_log[-10:])
        return value
''',
'mac_projects.py': r'''"""Point E: controlled access to real project folders (from the reviewed mac_v013 reserve work).

The list lives in a root-owned JSON file in the agent code directory. Read-write
roots join the main file engine (writes need a work session AND a covering work
lock); read-only roots get a separate engine that refuses every mutation. A
read-write root may sit inside a read-only root: the read-only engine then
excludes it, so every path belongs to exactly one engine. The isolated shell may
read the project roots and write only the read-write ones (seatbelt profile).
"""
import json
import os
from pathlib import Path
import re
import stat

FORBIDDEN = re.compile(r'bitcoin|marruca|lidar|keychain|^\.ssh$|^\.gnupg$|^\.aws$|^\.config$|^library$|^\.trash$', re.I)
# Pre-scan only: forbidden names are also checked on every requested path and by the seatbelt.
SKIP_SCAN = frozenset({'.git', 'node_modules', 'Pods', 'DerivedData', '.build', 'build', '.venv', 'venv'})
SCAN_DEPTH = 3
SCAN_LIMIT = 200000
EMPTY = {'rw': [], 'ro': [], 'exclude': [], 'ro_exclude': []}


def forbidden_component(path, root):
    rel = os.path.relpath(path, root)
    parts = [] if rel == '.' else rel.split(os.sep)
    return any(FORBIDDEN.search(p) for p in parts)


def _inside(a, b):
    """True when a is b or lies below it (case-insensitive, like APFS)."""
    a, b = a.casefold().rstrip('/'), b.casefold().rstrip('/')
    return a == b or a.startswith(b + '/')


def _overlap(a, b):
    return _inside(a, b) or _inside(b, a)


def scan_forbidden(root, depth=SCAN_DEPTH, limit=SCAN_LIMIT):
    """Directories with forbidden names below a root become denied roots (no symlinks followed)."""
    found, seen, frontier = [], 0, [(root, 0)]
    while frontier:
        current, level = frontier.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for e in entries:
            seen += 1
            if seen > limit:
                raise ValueError('project root too large to pre-scan: ' + root)
            if not e.is_dir(follow_symlinks=False):
                continue
            if FORBIDDEN.search(e.name):
                found.append(e.path)
            elif level + 1 < depth and e.name not in SKIP_SCAN:
                frontier.append((e.path, level + 1))
    return found


def validate(cfg, protected=(), scan=scan_forbidden, check_fs=True):
    """Return {'rw', 'ro', 'exclude', 'ro_exclude'} from a parsed configuration."""
    if not isinstance(cfg, dict) or set(cfg) - {'version', 'roots', 'exclude'} or cfg.get('version') != 1:
        raise ValueError('invalid projects configuration')
    out = {k: [] for k in EMPTY}
    roots = cfg.get('roots', [])
    if not isinstance(roots, list) or len(roots) > 16:
        raise ValueError('invalid project roots')
    chosen = []
    for item in roots:
        if not isinstance(item, dict) or set(item) != {'path', 'mode'} or item['mode'] not in ('ro', 'rw'):
            raise ValueError('each root needs path and mode ro/rw')
        p = item['path']
        if not isinstance(p, str) or not re.fullmatch(r'/Users/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+', p) \
                or os.path.normpath(p) != p or p.startswith('/Users/Shared/') or '/..' in p or '/./' in p:
            raise ValueError('project roots must be plain normalized paths under /Users (not Shared): %r' % (p,))
        if check_fs and (os.path.realpath(p) != p or not os.path.isdir(p)):
            raise ValueError('project root must be an existing directory without symlinks: ' + p)
        if any(FORBIDDEN.search(x) for x in p.split('/')):
            raise ValueError('project root names a forbidden area: ' + p)
        if any(_overlap(p, q) for q in protected):
            raise ValueError('project roots must not overlap protected paths: ' + p)
        chosen.append((p, item['mode']))
    for i, (p, mode) in enumerate(chosen):
        for j, (q, other) in enumerate(chosen):
            if i == j or not _overlap(p, q):
                continue
            # Only a read-write root strictly inside a read-only root is allowed.
            if not (mode == 'rw' and other == 'ro' and _inside(p, q) and p.casefold() != q.casefold()) and \
               not (other == 'rw' and mode == 'ro' and _inside(q, p) and p.casefold() != q.casefold()):
                raise ValueError('project roots overlap: %s and %s' % (p, q))
        out[mode].append(p)
    for p in cfg.get('exclude', []):
        if not isinstance(p, str) or not os.path.isabs(p) or os.path.normpath(p) != p \
                or not any(_inside(p, q) and p.casefold() != q.casefold() for q, _ in chosen):
            raise ValueError('exclusions must lie strictly inside a project root')
        out['exclude'].append(p)
    for p, _ in chosen:
        out['exclude'].extend(scan(p))
    out['ro_exclude'] = out['exclude'] + [p for p in out['rw'] if any(_inside(p, q) for q in out['ro'])]
    return out


def load_projects(path, protected=(), owner=0, scan=scan_forbidden):
    """Read the root-owned configuration; a missing file means no projects."""
    path = Path(path)
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {k: list(v) for k, v in EMPTY.items()}
    with os.fdopen(fd, 'rb') as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != owner or st.st_mode & 0o022 or st.st_size > 65536:
            raise PermissionError('unsafe projects configuration')
        cfg = json.loads(f.read(65537))
    return validate(cfg, protected, scan)


def shell_view(projects):
    """The subset handed to the sandboxed shell launcher (already validated by the agent)."""
    return {'rw': list(projects['rw']), 'ro': list(projects['ro']), 'exclude': list(projects['exclude'])}
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
            m.assert_awaited_once_with('work:'+self.a['work_session_id'],1,'none')
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
        self.assertEqual(len(TOOLS),len(NAMES));self.assertEqual(len(TOOLS),31)
        self.assertTrue({'mac_admin_request','mac_admin_result'} <= NAMES)
        self.assertTrue({'work_session','work_lock'} <= NAMES)
        self.assertTrue({'start_search','get_more_search_results','stop_search'}<=NAMES)
        for t in TOOLS:
            m=t['inputSchema']['properties'].get('machine',{})
            if t['name'].startswith('mac_admin_'):self.assertEqual(m['enum'],['mac_mio']);continue
            if 'enum' in m:self.assertEqual(set(m['enum']),{'vps','mac_noleggio','mac_mio'})


if __name__=='__main__':unittest.main(verbosity=2)
''',
'test_v012.py': r'''"""v0.12 Mac side: GitHub-only proxy, seatbelt policy, child environment, dispatcher.

File tool tests live in test_files_v012.py.
"""
import asyncio
import contextlib
import subprocess
import types
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from file_tools import FileTools, FileToolError
import net_proxy
from net_proxy import GitHubProxy
import mac_policy
import mac_shell
from mac_agent import Dispatcher


class Proxy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        async def echo(reader, writer):
            data = await reader.read(100)
            writer.write(b'echo:' + data); await writer.drain(); writer.close()
        self.upstream = await asyncio.start_server(echo, '127.0.0.1', 0)
        port = self.upstream.sockets[0].getsockname()[1]
        async def resolve(host): return ['127.0.0.1']
        self.p = GitHubProxy(log=self.events.append, resolver=resolve, port=port)
        await self.p.start()

    async def asyncTearDown(self):
        await self.p.stop(); self.upstream.close(); await self.upstream.wait_closed()

    async def request(self, head):
        r, w = await asyncio.open_connection('127.0.0.1', self.p.address())
        w.write(head); await w.drain()
        line = await r.readline()
        return r, w, line

    def auth(self, token=None):
        value = base64.b64encode(('mcp:' + (token or self.p.token)).encode())
        return b'Proxy-Authorization: Basic ' + value + b'\r\n'

    async def test_requires_credential(self):
        _, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n\r\n'); w.close()
        self.assertIn(b'407', line)
        _, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n' + self.auth('x' * 32) + b'\r\n'); w.close()
        self.assertIn(b'407', line)

    async def test_407_announces_basic_scheme_for_curl_anyauth(self):
        r, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n\r\n')
        head = await asyncio.wait_for(r.read(500), 5); w.close()
        self.assertIn(b'407', line)
        self.assertIn(b'Proxy-Authenticate: Basic', head)

    async def test_only_allowed_hosts_port_and_method(self):
        for head in [b'CONNECT example.com:443 HTTP/1.1\r\n', b'CONNECT github.com:22 HTTP/1.1\r\n',
                     b'CONNECT evilgithub.com:443 HTTP/1.1\r\n', b'CONNECT github.com.evil.com:443 HTTP/1.1\r\n']:
            _, w, line = await self.request(head + self.auth() + b'\r\n'); w.close()
            self.assertIn(b'403', line, head)
        _, w, line = await self.request(b'GET http://github.com/ HTTP/1.1\r\n' + self.auth() + b'\r\n'); w.close()
        self.assertIn(b'405', line)

    async def test_private_addresses_refused(self):
        _, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n' + self.auth() + b'\r\n'); w.close()
        self.assertIn(b'502', line)
        for a in ['127.0.0.1', '10.0.0.1', '192.168.1.1', '169.254.169.254', '::1', '::ffff:127.0.0.1']:
            self.assertFalse(net_proxy.public_address(a), a)
        self.assertTrue(net_proxy.public_address('140.82.121.4'))

    async def test_tunnel_to_allowed_host(self):
        with patch('net_proxy.public_address', return_value=True):
            r, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n' + self.auth() + b'\r\n')
            self.assertIn(b'200', line)
            await r.readline()
            w.write(b'hello'); await w.drain()
            self.assertEqual(await asyncio.wait_for(r.read(100), 5), b'echo:hello')
            w.close()

    async def test_stop_invalidates_token_and_port(self):
        port, token = self.p.address(), self.p.token
        await self.p.stop()
        self.assertIsNone(self.p.token)
        with self.assertRaises(OSError):
            await asyncio.open_connection('127.0.0.1', port)
        await self.p.start()
        self.assertNotEqual(self.p.token, token)


class Policy(unittest.TestCase):
    def setUp(self):
        self.patch = patch('mac_policy.safe_executables', return_value=['/bin/bash'])
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_offline_profile_has_no_network(self):
        text = mac_policy.profile('/Users/Shared/X/workspace')
        self.assertIn('(deny network*)', text)
        self.assertNotIn('network-outbound', text)
        self.assertNotIn('trustd', text)

    def test_ioctl_only_on_the_session_pty(self):
        self.assertNotIn('file-ioctl', mac_policy.profile('/Users/Shared/X/workspace'))
        text = mac_policy.profile('/Users/Shared/X/workspace', tty_path='/dev/ttys004')
        rules = [l for l in text.splitlines() if 'file-ioctl' in l]
        self.assertEqual(rules, ['(allow file-ioctl (literal "/dev/ttys004"))'])
        for bad in ['/dev/disk0', '/dev/ttys004/../disk0', '/dev/tty']:
            with self.assertRaises(ValueError):
                mac_policy.profile('/Users/Shared/X/workspace', tty_path=bad)

    def test_pty_gets_terminal_size(self):
        import pty, struct, termios, fcntl
        master, slave = pty.openpty()
        try:
            mac_shell.set_winsize(slave)
            rows, cols = struct.unpack('HHHH', fcntl.ioctl(master, termios.TIOCGWINSZ, b'\0' * 8))[:2]
            self.assertEqual((rows, cols), (24, 80))
        finally:
            os.close(master); os.close(slave)

    def test_network_profile_is_loopback_port_only(self):
        text = mac_policy.profile('/Users/Shared/X/workspace', net_port=50123)
        self.assertIn('(allow network-outbound (remote ip "localhost:50123"))', text)
        self.assertNotIn('(allow network*', text)
        self.assertIn('com.apple.trustd', text)
        self.assertLess(text.index('(deny network*)'), text.index('localhost:50123'))
        for bad in [80, 0, 70000, '50123']:
            with self.assertRaises(ValueError):
                mac_policy.profile('/Users/Shared/X/workspace', net_port=bad)


class TrustedTree(unittest.TestCase):
    def fake(self, modes):
        import stat as st
        def lstat(p):
            uid, mode, gid = modes.get(str(p), (0, 0o755, 0))
            return os.stat_result((st.S_IFDIR | mode, 0, 0, 0, uid, gid, 0, 0, 0, 0))
        return patch('mac_policy.Path.lstat', lambda self: lstat(self))

    def test_root_owned_tree_accepted_admin_group_write_tolerated(self):
        with self.fake({'/Applications': (0, 0o775, 80)}):
            self.assertEqual(mac_policy.trusted_tree('/Applications/Xcode.app/Contents/Developer/usr'),
                             '/Applications/Xcode.app/Contents/Developer/usr')

    def test_unsafe_trees_rejected(self):
        for bad in [(501, 0o755, 20), (0, 0o777, 0), (0, 0o775, 20)]:
            with self.fake({'/Applications/Xcode.app': bad}):
                self.assertIsNone(mac_policy.trusted_tree('/Applications/Xcode.app/Contents/Developer/usr'), bad)


class ChildEnvironment(unittest.TestCase):
    def test_git_uses_basic_proxy_auth_and_token_not_in_argv(self):
        import mac_child
        captured = {}
        def fake_exec(path, argv, env): captured.update(argv=argv, env=env)
        env = {'MCP_NET_PORT': '50123', 'MCP_NET_TOKEN': 'A' * 32}
        with patch.object(mac_child, 'require_identity'), patch.object(mac_child.resource, 'setrlimit'), \
                patch.object(mac_child.os, 'execve', side_effect=fake_exec), patch.dict(mac_child.os.environ, env, clear=True), \
                patch.object(mac_child, 'profile', return_value='(version 1)'), \
                patch.object(mac_child.sys, 'argv', ['c', '/Users/Shared/w', '/Users/Shared/w', 'git status', '/dev/ttys001']):
            mac_child.main()
        self.assertEqual(captured['env']['GIT_CONFIG_KEY_0'], 'http.proxyAuthMethod')
        self.assertEqual(captured['env']['GIT_CONFIG_VALUE_0'], 'basic')
        self.assertIn('A' * 32, captured['env']['HTTPS_PROXY'])
        self.assertNotIn('A' * 32, ' '.join(captured['argv']))

    def test_offline_child_has_no_proxy(self):
        import mac_child
        captured = {}
        with patch.object(mac_child, 'require_identity'), patch.object(mac_child.resource, 'setrlimit'), \
                patch.object(mac_child.os, 'execve', side_effect=lambda p, a, e: captured.update(env=e)), \
                patch.dict(mac_child.os.environ, {}, clear=True), patch.object(mac_child, 'profile', return_value='x') as prof, \
                patch.object(mac_child.sys, 'argv', ['c', '/Users/Shared/w', '/Users/Shared/w', 'ls', '/dev/ttys001']):
            mac_child.main()
        self.assertNotIn('HTTPS_PROXY', captured['env'])
        self.assertIsNone(prof.call_args.args[2])


class AgentV012(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); r = Path(self.tmp.name)
        self.work = r / 'work'; self.state = r / 'state'
        self.work.mkdir(mode=0o700); self.state.mkdir(mode=0o700)
        self.d = Dispatcher(self.work, self.state)
        self.a = await self.call('work_session', {'action': 'open', 'label': 'A', 'minutes': 10})
        self.b = await self.call('work_session', {'action': 'open', 'label': 'B', 'minutes': 10})

    async def asyncTearDown(self):
        await self.d.close(); self.tmp.cleanup()

    async def call(self, op, args, s=None):
        if s:
            args = {**args, **{k: s[k] for k in ['work_session_id', 'work_session_token']}}
        return await self.d.dispatch({'type': 'request', 'id': uuid.uuid4().hex, 'caller': 'test:client', 'op': op, 'args': args})

    async def test_new_mutations_require_session(self):
        (self.work / 'f').write_text('x')
        for op, args in [('delete_path', {'path': str(self.work / 'f')}),
                         ('copy_file', {'source': str(self.work / 'f'), 'destination': str(self.work / 'g')}),
                         ('upload_file', {'action': 'begin', 'path': str(self.work / 'h'), 'size': 1, 'sha256': '0' * 64})]:
            with self.assertRaises(PermissionError):
                await self.call(op, args)
        r = await self.call('read_binary', {'path': str(self.work / 'f')})
        self.assertEqual(base64.b64decode(r['content_base64']), b'x')

    async def test_upload_and_delete_through_dispatcher(self):
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10}, self.a)
        data = b'\x89PNG\r\n\x1a\n' + os.urandom(1000)
        b = await self.call('upload_file', {'action': 'begin', 'path': str(self.work / 'i.png'), 'size': len(data),
                                            'sha256': hashlib.sha256(data).hexdigest()}, self.a)
        with self.assertRaises(FileToolError):
            await self.call('upload_file', {'action': 'commit', 'upload_id': b['upload_id']}, self.b)
        await self.call('upload_file', {'action': 'chunk', 'upload_id': b['upload_id'], 'offset': 0,
                                        'data': base64.b64encode(data).decode()}, self.a)
        await self.call('upload_file', {'action': 'commit', 'upload_id': b['upload_id']}, self.a)
        self.assertEqual((self.work / 'i.png').read_bytes(), data)
        r = await self.call('delete_path', {'path': str(self.work / 'i.png')}, self.a)
        self.assertFalse((self.work / 'i.png').exists())
        await self.call('rollback_file', {'operation_id': r['operation_id']}, self.a)
        self.assertEqual((self.work / 'i.png').read_bytes(), data)

    async def test_close_drops_own_uploads(self):
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10}, self.a)
        await self.call('upload_file', {'action': 'begin', 'path': str(self.work / 'z'), 'size': 1, 'sha256': '0' * 64}, self.a)
        await self.call('work_session', {'action': 'close'}, self.a)
        self.assertEqual(self.d.uploads.jobs, {})

    async def test_enable_network_argument_validated_and_forwarded(self):
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10}, self.a)
        with patch.object(self.d.shell, 'enable', new=AsyncMock(return_value={'enabled': True})) as m:
            await self.call('enable_full_shell', {'minutes': 1, 'network': 'github'}, self.a)
            m.assert_awaited_once_with('work:' + self.a['work_session_id'], 1, 'github')
        with self.assertRaises(ValueError):
            await self.call('enable_full_shell', {'minutes': 1, 'proxy': 'x'}, self.a)

    async def test_shell_network_lease_starts_and_stops_proxy(self):
        shell = self.d.shell; identity = 'work:' + self.a['work_session_id']
        with patch('mac_shell.require_identity'):
            with self.assertRaises(ValueError):
                await shell.enable(identity, 1, 'internet')
            r = await shell.enable(identity, 1, 'github')
            self.assertTrue(shell.proxy.running)
            self.assertIn('github', r['network'])
            env = shell.child_env()
            self.assertEqual(env['MCP_NET_PORT'], str(shell.proxy.address()))
            await shell.enable(identity, 1, 'none')
            self.assertFalse(shell.proxy.running)
            self.assertNotIn('MCP_NET_PORT', shell.child_env())
            await shell.enable(identity, 1, 'github')
            await shell.disable()
            self.assertFalse(shell.proxy.running)
            self.assertEqual(shell.network, 'none')

    async def test_session_and_lock_operations_audited_with_session_id(self):
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10}, self.a)
        recent = (await self.call('who_is_working', {}))['recent_work_operations']
        sid = self.a['work_session_id']
        ops = [(x['operation'], x['work_session_id']) for x in recent if 'request_id' in x]
        self.assertIn(('work_session', sid), ops)
        self.assertIn(('work_lock', sid), ops)
        self.assertIn(('work_session', self.b['work_session_id']), ops)

    async def test_metadata_advertises_new_capabilities(self):
        import mac_agent
        meta = mac_agent.metadata()
        for name in ['delete_path', 'copy_file', 'read_binary', 'upload_file']:
            self.assertIn(name, meta['capabilities'])
        self.assertIn('github.com', meta['shell_network_hosts'])


class ConcurrentShell(unittest.IsolatedAsyncioTestCase):
    """Real processes through MacShell's job machinery (bash replaces the seatbelt child)."""

    async def asyncSetUp(self):
        import mac_shell
        self.ms = mac_shell
        self.tmp = tempfile.TemporaryDirectory(); r = Path(self.tmp.name)
        (r / 'work').mkdir(mode=0o700)
        self.f = FileTools([str(r / 'work')], str(r / 'journal'))
        self.work = str(r / 'work')
        self.cleanups = 0
        def cleanup():
            # Like stop_dedicated_children: every uid5000 process goes.
            self.cleanups += 1
            for j in self.shell.jobs.values():
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(j['proc'].pid, 9)
        real = subprocess.Popen
        def popen(argv, **kw):
            if len(argv) != 8 or not str(argv[3]).endswith('mac_child.py'):
                return real(argv, **kw)
            kw['env'] = {'PATH': '/usr/bin:/bin'}
            return real(['/bin/bash', '-c', argv[6]], **kw)
        self.patches = [patch.object(mac_shell, 'require_identity'), patch.object(mac_shell.subprocess, 'Popen', side_effect=popen)]
        for p in self.patches: p.start()
        self.shell = mac_shell.MacShell(self.f, self.work, str(r / 'logs'), capable=True)
        self.shell._trusted_code = lambda: None
        self.shell._start_watchdog = lambda: None
        self.shell._cleanup_uid = cleanup
        self.me = 'work:' + 'a' * 32
        await self.shell.enable(self.me, 1)

    async def asyncTearDown(self):
        for j in self.shell.running():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(j['proc'].pid, 9)
        for j in list(self.shell.jobs.values()):
            await asyncio.wait_for(j['done'].wait(), 5)
        self.shell.owner = None
        for p in self.patches: p.stop()
        self.f.close(); self.tmp.cleanup()

    async def wait_done(self, sid):
        await asyncio.wait_for(self.shell.jobs[sid]['done'].wait(), 5)

    async def test_four_concurrent_processes_with_separate_output(self):
        ids = [(await self.shell.start(self.me, 'echo out%d; sleep 3' % i))['session_id'] for i in range(4)]
        with self.assertRaises(PermissionError):
            await self.shell.start(self.me, 'true')
        await asyncio.sleep(.3)
        outs = [self.shell.read(self.me, i)['output'] for i in ids]
        for i, out in enumerate(outs):
            self.assertIn('out%d' % i, out)
        listed = await self.shell.session(self.me, {'action': 'list'})
        self.assertEqual(sum(x['running'] for x in listed['sessions']), 4)
        other = await self.shell.session('work:' + 'b' * 32, {'action': 'list'})
        self.assertEqual(other['sessions'], [])

    async def test_guard_held_while_any_runs_and_released_after_last(self):
        a = (await self.shell.start(self.me, 'sleep 3'))['session_id']
        b = (await self.shell.start(self.me, 'sleep 0.2'))['session_id']
        await self.wait_done(b)
        self.assertEqual(self.cleanups, 0, 'one process ending must not clean up the others')
        self.assertIsNotNone(self.shell.guard_fd)
        with self.assertRaises(FileToolError):
            self.f.write_file(self.work + '/x', 'x', session_id=self.me)
        await self.shell.session(self.me, {'action': 'stop', 'session_id': a})
        self.assertGreaterEqual(self.cleanups, 1)
        self.assertIsNone(self.shell.guard_fd)
        self.f.write_file(self.work + '/x', 'x', session_id=self.me)

    async def test_stop_one_keeps_others_running(self):
        a = (await self.shell.start(self.me, 'sleep 5'))['session_id']
        b = (await self.shell.start(self.me, 'sleep 5'))['session_id']
        r = await self.shell.session(self.me, {'action': 'stop', 'session_id': a})
        self.assertTrue(r['stopped'])
        self.assertTrue(self.shell.jobs[a]['done'].is_set())
        self.assertFalse(self.shell.jobs[b]['done'].is_set())
        self.assertEqual(self.cleanups, 0)

    async def test_disable_stops_everything(self):
        for _ in range(3):
            await self.shell.start(self.me, 'sleep 5')
        await self.shell.disable()
        self.assertEqual(self.shell.running(), [])
        self.assertIsNone(self.shell.guard_fd)

    async def test_processes_requires_lease(self):
        with patch.object(self.ms.subprocess, 'run', return_value=types.SimpleNamespace(
                stdout='5000 10 1 00:05 /bin/bash -c sleep\n501 11 1 00:01 other\n')):
            r = await self.shell.session(self.me, {'action': 'processes'})
        self.assertEqual([p['pid'] for p in r['processes']], [10])
        with self.assertRaises(PermissionError):
            await self.shell.session('work:' + 'b' * 32, {'action': 'processes'})

    async def test_network_profiles(self):
        with self.assertRaises(ValueError):
            await self.shell.enable(self.me, 1, 'internet')
        r = await self.shell.enable(self.me, 1, 'packages')
        self.assertIn('pypi.org', r['network'])
        self.assertIn('registry.npmjs.org', self.shell.proxy.hosts)
        await self.shell.enable(self.me, 1, 'github')
        self.assertNotIn('pypi.org', self.shell.proxy.hosts)
        await self.shell.enable(self.me, 1, 'none')
        self.assertFalse(self.shell.proxy.running)


class Catalog(unittest.TestCase):
    def test_gateway_catalog_has_new_tools_with_session_fields(self):
        import cg_tools
        tools = {t['name']: t for t in cg_tools.TOOLS}
        self.assertEqual(len(tools), len(cg_tools.TOOLS))
        for name in ['delete_path', 'copy_file', 'read_binary', 'upload_file']:
            self.assertIn('work_session_id', tools[name]['inputSchema']['properties'])
        self.assertEqual(tools['enable_full_shell']['inputSchema']['properties']['network']['enum'], ['none', 'github', 'packages'])
        self.assertIn('processes', tools['shell_session']['description'])
        json.dumps(cg_tools.TOOLS)


if __name__ == '__main__':
    unittest.main()
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

    def test_flood_is_bounded(self):
        for i in range(25):
            self.put(uuid.uuid4().hex + '.json', '{bad')
        self.helper.scan()
        self.assertEqual(len(os.listdir(self.root / 'outbox')), 15)
        old = H.KEEP_RESULTS
        H.KEEP_RESULTS = 4
        try:
            self.helper.prune()
        finally:
            H.KEEP_RESULTS = old
        names = [n for n in os.listdir(self.root / 'results') if n != 'helper_status.json']
        self.assertEqual(len(names), 4)

    def test_prune_keeps_pending(self):
        r = self.ask()
        self.helper.scan()
        self.clock[0] += H.RESULT_TTL + 10
        os.utime(self.root / 'results' / (r['request_id'] + '.json'), (0, 0))
        self.helper.prune()
        self.assertTrue((self.root / 'results' / (r['request_id'] + '.json')).exists())

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
'test_projects.py': r'''"""Point E (p5): real project roots, ro with a nested rw root, for file tools and the shell."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from mac_agent import Dispatcher, metadata
from mac_projects import load_projects, validate, forbidden_component, EMPTY
import mac_policy

DEV, MCP = '/Users/babo/Developer', '/Users/babo/Developer/MCPAndrea'


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.cfg = self.base / 'projects.json'

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, roots, exclude=()):
        return validate({'version': 1, 'roots': roots, 'exclude': list(exclude)}, scan=lambda p: [], check_fs=False)

    def test_missing_file_means_no_projects(self):
        self.assertEqual(load_projects(self.base / 'none.json'), EMPTY)

    def test_andrea_layout_rw_nested_in_ro(self):
        out = self.check([{'path': DEV, 'mode': 'ro'}, {'path': MCP, 'mode': 'rw'}])
        self.assertEqual((out['ro'], out['rw']), ([DEV], [MCP]))
        self.assertEqual(out['ro_exclude'], [MCP])
        self.assertEqual(out['exclude'], [])

    def test_other_overlaps_rejected(self):
        for roots in ([{'path': DEV, 'mode': 'rw'}, {'path': MCP, 'mode': 'ro'}],
                      [{'path': DEV, 'mode': 'ro'}, {'path': MCP, 'mode': 'ro'}],
                      [{'path': DEV, 'mode': 'rw'}, {'path': MCP, 'mode': 'rw'}],
                      [{'path': DEV, 'mode': 'ro'}, {'path': DEV, 'mode': 'rw'}],
                      [{'path': DEV, 'mode': 'ro'}, {'path': '/Users/babo/developer', 'mode': 'rw'}]):
            with self.assertRaises(ValueError, msg=roots):
                self.check(roots)

    def test_rejections(self):
        bad = [[{'path': '/etc', 'mode': 'ro'}],
               [{'path': '/Users/Shared/x', 'mode': 'ro'}],
               [{'path': '/Users/babo', 'mode': 'ro'}],
               [{'path': '/Users/babo/Bitcoin', 'mode': 'ro'}],
               [{'path': '/Users/babo/Dev/LaMarrucaApp', 'mode': 'rw'}],
               [{'path': '/Users/babo/x/../y', 'mode': 'ro'}],
               [{'path': '/Users/babo/a b', 'mode': 'ro'}],
               [{'path': '/Users/babo/Library', 'mode': 'ro'}],
               [{'path': DEV, 'mode': 'admin'}]]
        for roots in bad:
            with self.assertRaises((ValueError, PermissionError), msg=roots):
                self.check(roots)
        with self.assertRaises(ValueError):
            validate({'version': 2, 'roots': []}, check_fs=False)
        with self.assertRaises(ValueError):
            self.check([{'path': DEV, 'mode': 'ro'}], exclude=['/Users/babo/elsewhere'])

    def test_unsafe_file_refused(self):
        self.cfg.write_text(json.dumps({'version': 1, 'roots': []}))
        os.chmod(self.cfg, 0o666)
        with self.assertRaises(PermissionError):
            load_projects(self.cfg, owner=os.getuid())
        os.chmod(self.cfg, 0o644)
        with self.assertRaises(PermissionError):
            load_projects(self.cfg, owner=os.getuid() + 1)

    def test_forbidden_component(self):
        self.assertTrue(forbidden_component('/r/a/La Marruca/x', '/r'))
        self.assertTrue(forbidden_component('/r/.ssh/id', '/r'))
        self.assertTrue(forbidden_component('/r/MyBitcoinWallet', '/r'))
        self.assertFalse(forbidden_component('/r/app/src', '/r'))


class Projects(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        b = Path(self.tmp.name)
        for d in ('work', 'state', 'dev', 'dev/mcp', 'dev/LiDAR', 'dev/mcp/bitcoin', 'dev/app'):
            (b / d).mkdir(mode=0o700)
        (b / 'dev' / 'app' / 'readme.txt').write_text('ciao\n')
        (b / 'dev' / 'LiDAR' / 'scan.txt').write_text('segreto\n')
        (b / 'dev' / 'mcp' / 'bitcoin' / 'w.txt').write_text('no\n')
        self.b = b
        ex = [str(b / 'dev' / 'LiDAR'), str(b / 'dev' / 'mcp' / 'bitcoin')]
        self.projects = {'rw': [str(b / 'dev' / 'mcp')], 'ro': [str(b / 'dev')], 'exclude': ex,
                         'ro_exclude': ex + [str(b / 'dev' / 'mcp')]}
        self.d = Dispatcher(b / 'work', b / 'state', projects=self.projects)
        self.s = await self.call('work_session', {'action': 'open', 'label': 'p', 'minutes': 5})

    async def asyncTearDown(self):
        await self.d.close()
        self.tmp.cleanup()

    async def call(self, op, args, auth=False):
        args = dict(args)
        if auth:
            args.update(work_session_id=self.s['work_session_id'], work_session_token=self.s['work_session_token'])
        return await self.d.dispatch({'type': 'request', 'id': uuid.uuid4().hex, 'caller': 'claude:abcdef12',
                                      'op': op, 'args': args})

    async def lock(self, path):
        return await self.call('work_lock', {'action': 'acquire', 'path': str(path), 'minutes': 5}, auth=True)

    async def test_read_only_root(self):
        p = str(self.b / 'dev' / 'app' / 'readme.txt')
        self.assertEqual((await self.call('read_file', {'path': p}))['content'], 'ciao\n')
        self.assertEqual((await self.call('read_binary', {'path': p}))['size'], 5)
        listing = await self.call('list_directory', {'path': str(self.b / 'dev'), 'depth': 2})
        self.assertNotIn('LiDAR', json.dumps(listing))
        with self.assertRaises(Exception):
            await self.call('read_file', {'path': str(self.b / 'dev' / 'LiDAR' / 'scan.txt')})
        with self.assertRaises(Exception):
            await self.lock(self.b / 'dev' / 'app')
        with self.assertRaises(PermissionError):
            await self.call('write_file', {'path': p, 'content': 'x'}, auth=True)
        with self.assertRaises(PermissionError):
            await self.call('move_file', {'source': p, 'destination': str(self.b / 'work' / 'r.txt')}, auth=True)
        self.assertEqual(Path(p).read_text(), 'ciao\n')

    async def test_nested_read_write_root_needs_lock_and_has_rollback(self):
        p = str(self.b / 'dev' / 'mcp' / 'nuovo.txt')
        with self.assertRaises(PermissionError):
            await self.call('write_file', {'path': p, 'content': 'x'}, auth=True)
        await self.lock(self.b / 'dev' / 'mcp')
        r = await self.call('write_file', {'path': p, 'content': 'x'}, auth=True)
        self.assertEqual((await self.call('read_file', {'path': p}))['content'], 'x')
        with self.assertRaises(Exception):
            await self.call('write_file', {'path': str(self.b / 'dev' / 'mcp' / 'bitcoin' / 'w.txt'), 'content': 'x'}, auth=True)
        with self.assertRaises(PermissionError):
            await self.call('copy_file', {'source': str(self.b / 'dev' / 'app' / 'readme.txt'), 'destination': p + '2'}, auth=True)
        await self.call('rollback_file', {'operation_id': r['operation_id']}, auth=True)
        self.assertFalse(Path(p).exists())
        self.assertEqual((self.b / 'dev' / 'mcp' / 'bitcoin' / 'w.txt').read_text(), 'no\n')

    async def test_search_in_read_only_root(self):
        r = await self.call('start_search', {'path': str(self.b / 'dev'), 'pattern': 'ciao'}, auth=True)
        await self.d.ro_search.jobs[r['search_id']]['task']
        self.assertEqual((await self.call('get_more_search_results', {'search_id': r['search_id']}, auth=True))['total_results'], 1)
        r = await self.call('start_search', {'path': str(self.b / 'dev'), 'pattern': 'segreto'}, auth=True)
        await self.d.ro_search.jobs[r['search_id']]['task']
        self.assertEqual((await self.call('get_more_search_results', {'search_id': r['search_id']}, auth=True))['total_results'], 0)
        state = await self.call('who_is_working', {})
        self.assertIsInstance(state['active_locks'], list)

    async def test_metadata_lists_roots(self):
        m = metadata(self.d)
        self.assertEqual(m['project_roots'], {'rw': [str(self.b / 'dev' / 'mcp')], 'ro': [str(self.b / 'dev')]})
        self.assertIn(str(self.b / 'dev'), m['allowed_roots'])
        self.assertIsNone(m['projects_error'])

    async def test_shell_cwd_and_environment(self):
        sh = self.d.shell
        self.assertEqual(sh.cwd(str(self.b / 'dev' / 'app')), str(self.b / 'dev' / 'app'))
        self.assertEqual(sh.cwd(str(self.b / 'dev' / 'mcp')), str(self.b / 'dev' / 'mcp'))
        for bad in (self.b / 'dev' / 'LiDAR', self.b / 'dev' / 'mcp' / 'bitcoin', self.b / 'state', Path('/etc')):
            with self.assertRaises(Exception, msg=bad):
                sh.cwd(str(bad))
        env = json.loads(sh.child_env()['MCP_PROJECTS'])
        self.assertEqual(env, {'rw': self.projects['rw'], 'ro': self.projects['ro'], 'exclude': self.projects['exclude']})

    async def test_shell_needs_locks_on_workspace_and_read_write_roots(self):
        ident = 'work:' + self.s['work_session_id']
        await self.lock(self.b / 'work')
        with self.assertRaises(PermissionError):
            self.d.shell_remaining(ident)
        await self.lock(self.b / 'dev' / 'mcp')
        self.assertGreater(self.d.shell_remaining(ident), 0)

    async def test_bad_configuration_fails_closed(self):
        with patch('mac_agent.load_projects', side_effect=ValueError('boom')), patch('mac_agent.WORK', self.b / 'work'):
            d = Dispatcher(self.b / 'work', self.b / 'state2')
        try:
            self.assertEqual(d.projects['rw'] + d.projects['ro'], [])
            self.assertIn('boom', d.projects_error)
            self.assertNotIn('MCP_PROJECTS', d.shell.child_env())
        finally:
            await d.close()


class ShellProfile(unittest.TestCase):
    def setUp(self):
        self.patch = patch('mac_policy.safe_executables', return_value=['/bin/bash'])
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_project_rules(self):
        text = mac_policy.profile('/Users/Shared/X/workspace', '/dev/ttys003', None,
                                  {'rw': [MCP], 'ro': [DEV], 'exclude': [DEV + '/old']})
        lines = text.splitlines()
        self.assertIn('(allow file-read* (subpath "%s"))' % DEV, lines)
        self.assertIn('(allow file-write* (subpath "%s"))' % MCP, lines)
        self.assertIn('(allow process-exec* (subpath "%s"))' % MCP, lines)
        self.assertNotIn('(allow file-write* (subpath "%s"))' % DEV, lines)
        deny = [l for l in lines if l.startswith('(deny file-read* file-write* process-exec*')]
        self.assertEqual(len(deny), 1)
        self.assertIn('(subpath "%s/old")' % DEV, deny[0])
        self.assertIn('[Mm][Aa][Rr][Rr][Uu][Cc][Aa]', deny[0])
        self.assertIn('\\.[Ss][Ss][Hh]', deny[0])
        self.assertNotIn('#"^' + MCP, deny[0])  # nested root covered by the outer one
        self.assertGreater(lines.index(deny[0]), lines.index('(allow file-write* (subpath "%s"))' % MCP))

    def test_regexes_catch_forbidden_names(self):
        import re
        rules = mac_policy.project_rules({'rw': [MCP], 'ro': [DEV], 'exclude': []})
        regexes = re.findall(r'#"([^"]+)"', rules[-1])
        def denied(path):
            return any(re.search(r, path) for r in regexes)
        for p in (DEV + '/LaMarrucaApp', DEV + '/x/my_BITCOIN/a', MCP + '/.ssh/id', DEV + '/a/Library',
                  DEV + '/.config', DEV + '/LiDAR'):
            self.assertTrue(denied(p), p)
        for p in (DEV + '/app/src/main.py', MCP + '/repo/.git/HEAD', DEV + '/libraryx', DEV + '/my.sshkeys'):
            self.assertFalse(denied(p), p)

    def test_invalid_project_paths_refused(self):
        for bad in ({'rw': ['/etc'], 'ro': [], 'exclude': []}, {'rw': [], 'ro': ['/Users/b/a"b'], 'exclude': []},
                    {'rw': [], 'ro': ['/Users/b/x/../y'], 'exclude': []}):
            with self.assertRaises(ValueError):
                mac_policy.project_rules(bad)


class ChildProjects(unittest.TestCase):
    def run_child(self, cwd, projects):
        import mac_child
        captured = {}
        env = {'MCP_PROJECTS': json.dumps(projects)} if projects is not None else {}
        with patch.object(mac_child, 'require_identity'), patch.object(mac_child.resource, 'setrlimit'), \
                patch.object(mac_child.os, 'execve', side_effect=lambda p, a, e: captured.update(env=e)), \
                patch.dict(mac_child.os.environ, env, clear=True), patch.object(mac_child, 'profile', return_value='x') as prof, \
                patch.object(mac_child.sys, 'argv', ['c', '/Users/Shared/w', cwd, 'git status', '/dev/ttys001']):
            mac_child.main()
        return captured['env'], prof.call_args.args

    def test_project_cwd_and_git_trust(self):
        projects = {'rw': [MCP], 'ro': [DEV], 'exclude': []}
        env, args = self.run_child(MCP + '/repo', projects)
        self.assertEqual(args[3], projects)
        self.assertEqual((env['GIT_CONFIG_KEY_0'], env['GIT_CONFIG_VALUE_0']), ('safe.directory', '*'))
        self.assertNotIn('HTTPS_PROXY', env)

    def test_cwd_outside_roots_refused(self):
        with self.assertRaises(SystemExit):
            self.run_child('/Users/babo/Documents', {'rw': [MCP], 'ro': [DEV], 'exclude': []})
        with self.assertRaises(SystemExit):
            self.run_child(DEV, None)
        with self.assertRaises(SystemExit):
            self.run_child(DEV, {'rw': [MCP]})


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
MAX_SCAN = 10          # outbox entries handled per loop (flood control)
KEEP_RESULTS = 500     # newest result files kept
RESULT_TTL = 7 * 86400
AUDIT_MAX = 5 * 1024 * 1024
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
        try:
            if os.lstat(str(self.audit_path)).st_size > AUDIT_MAX:
                os.replace(str(self.audit_path), str(self.audit_path) + '.1')
        except FileNotFoundError:
            pass
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

    def prune(self):
        """Bound the results directory: drop old or excess finished results (never pending ones)."""
        dfd = os.open(str(self.results), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            items = []
            for name in os.listdir(dfd):
                if name.endswith('.json') and HEX32.fullmatch(name[:-5]) and name[:-5] not in self.pending:
                    try:
                        items.append((os.lstat(name, dir_fd=dfd).st_mtime, name))
                    except FileNotFoundError:
                        pass
            items.sort(reverse=True)
            now = self.now()
            for i, (mtime, name) in enumerate(items):
                if i >= KEEP_RESULTS or now - mtime > RESULT_TTL:
                    try:
                        os.unlink(name, dir_fd=dfd)
                    except FileNotFoundError:
                        pass
        finally:
            os.close(dfd)

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
            handled = 0
            for name in sorted(os.listdir(dfd)):
                if handled >= MAX_SCAN:
                    break
                rid = name[:-5] if name.endswith('.json') else None
                if rid is None or not HEX32.fullmatch(rid):
                    try:
                        # A young temp file may be a request being written: skip it, uncounted.
                        if name.endswith('.tmp') and self.now() - os.lstat(name, dir_fd=dfd).st_mtime < 60:
                            continue
                        handled += 1
                        os.unlink(name, dir_fd=dfd)
                    except (FileNotFoundError, IsADirectoryError, PermissionError):
                        pass
                    continue
                handled += 1
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
            helper.prune()
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
'mac_v012_selftest.py': r'''"""UID5000 v0.12 smoke test, only while the central Mac daemon is stopped.

Covers the v0.11 coordination checks, the new reversible file tools, and the
real seatbelt behaviour of the shell child with and without the GitHub lease.
"""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import pty
import subprocess
import sys
import time
import uuid
sys.path.insert(0, '/Library/MCPAndreaMacMioV09/code')
from mac_agent import Dispatcher, WORK, CODE
from mac_guard import require_identity, stop_dedicated_children
from net_proxy import GitHubProxy

PROBE = r"""
import base64, os, socket, sys
port = int(sys.argv[1]); token = sys.argv[2]
def attempt(addr):
    try:
        s = socket.create_connection(addr, 3)
    except OSError as e:
        return 'blocked:' + type(e).__name__
    return s
s = attempt(('127.0.0.1', port))
if isinstance(s, str):
    print('PROXY', s)
else:
    auth = base64.b64encode(('mcp:' + token).encode())
    s.sendall(b'CONNECT example.com:443 HTTP/1.1\r\nProxy-Authorization: Basic ' + auth + b'\r\n\r\n')
    print('PROXY', s.recv(64).split(b'\r\n')[0].decode())
d = attempt(('1.1.1.1', 443))
print('DIRECT', d if isinstance(d, str) else 'open')
"""


def sandboxed(command, cwd, proxy=None, timeout=30):
    """Run through the real mac_child exactly as the shell does.

    Blocking: call it in a worker thread so the proxy keeps serving the loop.
    """
    master, slave = pty.openpty()
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
    if proxy:
        env.update(MCP_NET_PORT=str(proxy.address()), MCP_NET_TOKEN=proxy.token)
    proc = subprocess.Popen([sys.executable, '-I', '-B', str(CODE / 'mac_child.py'), str(WORK), cwd,
                             command, os.ttyname(slave)], stdin=slave, stdout=slave, stderr=slave,
                            close_fds=True, start_new_session=True, cwd=cwd, env=env)
    os.close(slave)
    os.set_blocking(master, False)
    output = bytearray(); end = time.monotonic() + timeout
    try:
        while time.monotonic() < end:
            try:
                chunk = os.read(master, 65536)
                if chunk:
                    output.extend(chunk)
            except BlockingIOError:
                pass
            except OSError:
                break
            if proc.poll() is not None:
                with __import__('contextlib').suppress(OSError):
                    output.extend(os.read(master, 65536))
                break
            time.sleep(.05)
        else:
            proc.kill()
    finally:
        os.close(master)
        if proc.poll() is None:
            proc.kill()
        proc.wait(5)
        stop_dedicated_children()
    return proc.returncode, output.decode(errors='replace')


def lines(text, key):
    return [l.split(None, 1)[1].strip() for l in text.splitlines() if l.startswith(key + ' ')]


async def main():
    require_identity(); d = Dispatcher(); operations = []; checks = []; sessions = []; info = {}
    caller = 'deployment:coordination-v012'
    async def call(op, s=None, **args):
        if s: args.update(work_session_id=s['work_session_id'], work_session_token=s['work_session_token'])
        return await d.dispatch({'type': 'request', 'id': uuid.uuid4().hex, 'caller': caller, 'op': op, 'args': args})
    async def refused(op, s=None, **args):
        try: await call(op, s, **args)
        except PermissionError: return
        raise AssertionError(op + ' was not refused')
    folder = str(WORK / ('v012_selftest_' + uuid.uuid4().hex))
    proxy = GitHubProxy()
    try:
        a = await call('work_session', action='open', label='selftest A', minutes=5); sessions.append(a)
        b = await call('work_session', action='open', label='selftest B', minutes=5); sessions.append(b)
        await refused('create_directory', a, path=folder)
        await refused('create_directory', path=folder)
        checks.append('writes need session and lock')
        lock = await call('work_lock', a, action='acquire', path=folder, minutes=5)
        await refused('work_lock', b, action='acquire', path=folder + '/x', minutes=5)
        checks.append('descendant conflict between sessions')
        operations.append((await call('create_directory', a, path=folder))['operation_id'])
        path = folder + '/prova.txt'
        operations.append((await call('write_file', a, path=path, content='MCP_V012_MAC_OK\n'))['operation_id'])
        await refused('write_file', b, path=path, content='other')
        await refused('rollback_file', b, operation_id=operations[-1])
        checks.append('foreign write and rollback refused')
        r = await call('start_search', a, path=folder, pattern='MCP_V012_MAC_OK')
        await asyncio.wait_for(d.search.jobs[r['search_id']]['task'], 5)
        await refused('get_more_search_results', b, search_id=r['search_id'])
        assert (await call('get_more_search_results', a, search_id=r['search_id']))['total_results'] == 1
        checks.append('search private to its session')

        data = bytes(range(256)) * 300
        up = await call('upload_file', a, action='begin', path=folder + '/blob.bin', size=len(data),
                        sha256=hashlib.sha256(data).hexdigest())
        await refused('upload_file', b, action='begin', path=folder + '/b.bin', size=1, sha256='0' * 64)
        await call('upload_file', a, action='chunk', upload_id=up['upload_id'], offset=0,
                   data=base64.b64encode(data).decode())
        operations.append((await call('upload_file', a, action='commit', upload_id=up['upload_id']))['operation_id'])
        got = await call('read_binary', path=folder + '/blob.bin')
        assert got['sha256'] == hashlib.sha256(data).hexdigest() and got['size'] == len(data), got
        checks.append('verified binary upload and read')
        await call('create_directory', a, path=folder + '/albero/sotto')
        await call('write_file', a, path=folder + '/albero/sotto/f.txt', content='albero')
        operations.append((await call('copy_file', a, source=folder + '/albero', destination=folder + '/copia'))['operation_id'])
        assert Path(folder + '/copia/sotto/f.txt').read_text() == 'albero'
        removed = await call('delete_path', a, path=folder + '/albero')
        assert not Path(folder + '/albero').exists()
        await refused('rollback_file', b, operation_id=removed['operation_id'])
        await call('rollback_file', a, operation_id=removed['operation_id'])
        assert Path(folder + '/albero/sotto/f.txt').read_text() == 'albero'
        removed = await call('delete_path', a, path=folder + '/albero')
        checks.append('copy and delete trees with rollback')

        state = await call('who_is_working')
        assert any(l['lock_id'] == lock['lock_id'] for l in state['work_locks']), state
        assert a['work_session_token'] not in json.dumps(state), 'token leaked'
        checks.append('who_is_working lists lock without tokens')
        r = await call('shell_exec', command='sw_vers')
        assert r['exit_code'] == 0 and not r['timed_out'], r
        checks.append('baseline sw_vers without session')

        code, out = await asyncio.to_thread(sandboxed, '/usr/bin/true', folder)
        assert code == 0, out
        checks.append('offline seatbelt profile with developer tools compiles')
        await proxy.start()
        script = folder + '/net_probe.py'
        Path(script).write_text(PROBE)
        probe = '%s -I -B %s %d %s' % (os.path.realpath(sys.executable), script, proxy.address(), proxy.token)
        code, out = await asyncio.to_thread(sandboxed, probe, folder, proxy)
        info['network_probe'] = out[-600:]
        assert lines(out, 'PROXY') == ['HTTP/1.1 403 Forbidden'], out
        assert lines(out, 'DIRECT') and lines(out, 'DIRECT')[0].startswith('blocked'), out
        checks.append('network lease: only the proxy port, non-GitHub host refused, direct internet blocked')
        code, out = await asyncio.to_thread(sandboxed, probe, folder, None)
        assert lines(out, 'PROXY') and lines(out, 'PROXY')[0].startswith('blocked'), out
        assert lines(out, 'DIRECT')[0].startswith('blocked'), out
        checks.append('offline shell cannot reach the proxy or internet')
        code, out = await asyncio.to_thread(sandboxed, '/usr/bin/git ls-remote https://github.com/git/git HEAD', folder, proxy, 25)
        info['github_git_ls_remote'] = 'ok' if code == 0 and 'HEAD' in out else 'failed: ' + out[-400:]
        os.unlink(script)

        rw, ro = d.projects['rw'], d.projects['ro']
        assert d.projects_error is None, d.projects_error
        project_locks = []
        if rw or ro:
            # p5 point E: file tools on the real project roots.
            for root in rw:
                project_locks.append(await call('work_lock', a, action='acquire', path=root, minutes=5))
                target = root + '/.mcp_selftest_' + uuid.uuid4().hex
                op = await call('write_file', a, path=target, content='PROGETTO_OK\n')
                assert (await call('read_file', path=target))['content'] == 'PROGETTO_OK\n'
                await call('rollback_file', a, operation_id=op['operation_id'])
                assert not Path(target).exists()
            for root in ro:
                await call('list_directory', path=root)
                try:
                    await call('write_file', a, path=root + '/.mcp_selftest_ro', content='x')
                    raise AssertionError('write into a read-only project root was accepted')
                except PermissionError:
                    pass
            checks.append('project roots: rw write with lock and rollback, ro listing, ro write refused')
        whole = await call('work_lock', a, action='acquire', path=str(WORK), minutes=5)
        await call('enable_full_shell', a, minutes=2)
        if rw:
            # The shell works inside the rw root; forbidden names and personal folders stay denied.
            sub = '.mcp_selftest_sh_' + uuid.uuid4().hex
            probe = ('mkdir %s && echo SH_RW_OK > %s/f && cat %s/f && rm -rf %s; '
                     'mkdir x_bitcoin_x 2>/dev/null && echo FORBIDDEN_CREATED || echo FORBIDDEN_DENIED; '
                     '/bin/ls /Users/babo/Documents >/dev/null 2>&1 && echo DOCS_VISIBLE || echo DOCS_DENIED; '
                     'touch %s/.mcp_ro_probe 2>/dev/null && echo RO_WRITTEN || echo RO_DENIED; '
                     '/bin/ls %s >/dev/null 2>&1 && echo RO_READ_OK || echo RO_READ_FAILED'
                     % (sub, sub, sub, sub, ro[0] if ro else '/nonexistent', ro[0] if ro else rw[0]))
            s4 = await call('shell_session', a, action='start', command=probe, cwd=rw[0])
            seen, end = '', time.monotonic() + 25
            while time.monotonic() < end:
                r4 = await call('shell_session', a, action='read', session_id=s4['session_id'])
                seen += r4['output']
                if not r4['running']:
                    break
                await asyncio.sleep(.25)
            info['project_shell'] = seen[-400:]
            for word in ('SH_RW_OK', 'FORBIDDEN_DENIED', 'DOCS_DENIED', 'RO_READ_OK'):
                assert word in seen, (word, seen[-400:])
            assert 'RO_WRITTEN' not in seen and 'FORBIDDEN_CREATED' not in seen, seen[-400:]
            assert not Path(rw[0], 'x_bitcoin_x').exists() and not Path(rw[0], sub).exists()
            checks.append('project shell: works in rw root, forbidden name denied, Documents denied, ro not writable')
        s1 = await call('shell_session', a, action='start', command='sleep 20', cwd=folder)
        s2 = await call('shell_session', a, action='start', command='echo CONCURRENT_OK; sleep 20', cwd=folder)
        await refused('shell_session', b, action='start', command='true')
        listed = await call('shell_session', a, action='list')
        assert sum(x['running'] for x in listed['sessions']) == 2, listed
        await call('shell_session', a, action='stop', session_id=s1['session_id'])
        # A seatbelt shell needs ~1.5-2 s on the Mac before its first output: wait for it.
        seen, end = '', time.monotonic() + 15
        while time.monotonic() < end:
            r2 = await call('shell_session', a, action='read', session_id=s2['session_id'])
            seen += r2['output']
            assert r2['running'], r2
            if 'CONCURRENT_OK' in seen:
                break
            await asyncio.sleep(.25)
        assert 'CONCURRENT_OK' in seen, (seen, r2)
        procs = await call('shell_session', a, action='processes')
        assert procs['processes'], procs
        await call('shell_session', a, action='stop', session_id=s2['session_id'])
        # p4: interactive Python REPL (readline/libedit) must reach its prompt and answer.
        s3 = await call('shell_session', a, action='start', command='/usr/bin/python3 -i', cwd=folder)
        seen, sent, end = '', False, time.monotonic() + 25
        while time.monotonic() < end:
            r3 = await call('shell_session', a, action='read', session_id=s3['session_id'])
            seen += r3['output']
            if not sent and '>>>' in seen:
                await call('shell_session', a, action='send', session_id=s3['session_id'], data='6*7\n')
                sent = True
            if sent and '42' in seen.split('6*7', 1)[-1]:
                break
            await asyncio.sleep(.25)
        assert sent and '42' in seen.split('6*7', 1)[-1], seen[-400:]
        await call('shell_session', a, action='send', session_id=s3['session_id'], data='exit()\n')
        checks.append('interactive python3 -i REPL answers in the shell')
        await call('disable_full_shell', a)
        await call('work_lock', a, action='release', lock_id=whole['lock_id'])
        for l in project_locks:
            await call('work_lock', a, action='release', lock_id=l['lock_id'])
        checks.append('two concurrent shell processes, stop one keeps the other, disable stops all')
    finally:
        await d.shell.disable()
        await proxy.stop()
        await d.search.close()
        for operation in reversed(operations):
            await call('rollback_file', sessions[0], operation_id=operation)
        for s in sessions: await call('work_session', s, action='close')
        state = await call('who_is_working')
        await d.close()
    assert not state['work_sessions'] and not state['work_locks'] and not state['shell_enabled'], state
    assert not Path(folder).exists(), 'selftest folder left behind'
    checks.append('sessions closed, locks released, test files rolled back')
    print(json.dumps({'passed': True, 'uid': os.getuid(), 'checks': checks, 'info': info}))


if __name__ == '__main__': asyncio.run(main())
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

# v0.12 p3: Mac administration through a dedicated Telegram bot (root helper on the Mac).
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
        # macOS starts these per-user agents on demand from launchd (exact path and arguments).
        if p[2]=='1' and len(p)==5 and p[4].strip() in SYSTEM_AGENTS:continue
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
    code="import sys,unittest;sys.path.insert(0,"+repr(str(TEST_CODE))+");s=unittest.defaultTestLoader.loadTestsFromNames(['test_work_core','test_search','test_v012','test_files_v012','test_mac_admin','test_projects']);r=unittest.TextTestRunner(verbosity=2).run(s);sys.exit(0 if r.wasSuccessful() else 1)"
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
    code="import runpy;runpy.run_path("+repr(str(TEST_CODE/'mac_v012_selftest.py'))+",run_name='__main__')"
    r=child(code,timeout=240)
    atomic(TEST_CODE/'selftest.log',(r.stdout+r.stderr).encode()[-65536:])
    if r.returncode:raise RuntimeError('v0.12 p5 smoke failed: '+r.stderr[-1000:])
    result=json.loads(r.stdout.strip().splitlines()[-1])
    if result.get('passed') is not True or result.get('uid')!=5000:raise RuntimeError('invalid smoke receipt')
    SMOKE_INFO.update(result.get('info',{}))
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
            # Point E before any stop: folders, ACLs and projects.json (ignored by the p4 agent).
            try:project_info=projects_setup()
            except Exception as e:
                record('projects_setup_failed',reason=str(e)[:1200],cleanup_errors=projects_remove(),
                       live_modules_modified=False);raise
            stopped=False;installed=False
            try:
                with workspace_guard():
                    check_sources();manifest=prepare_backup();stopped=True;stop_daemon()
                    for name,data in PAYLOAD.items():
                        meta=manifest[name] or {'mode':0o444,'uid':0,'gid':0}
                        atomic(BASE/name,data,meta['mode'],meta['uid'],meta['gid'])
                    installed=True
                checks=selftest();ready=start_daemon(NEW_VERSION);stopped=False
                record('active',projects=project_info,version=NEW_VERSION,uid=5000,agent_pid=ready['pid'],checks=checks,info=SMOKE_INFO,
                       backup=str(BACKUP),hashes={n:sha(b) for n,b in PAYLOAD.items()},rental_touched=False)
                print(json.dumps({'status':'active','checks':checks,'info':SMOKE_INFO,'uid':5000},indent=2))
            except Exception as error:
                project_info['cleanup_errors']=projects_remove()
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
                cleanup=projects_remove()
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

PROJECTS_FILE=BASE/'projects.json'
OWNER_NAME='babo'
OWNER_UID=501
HOME=Path('/Users/babo')
DEV=HOME/'Developer'
MCP=DEV/'MCPAndrea'
PROJECTS_CONFIG={'version':1,'roots':[{'path':str(DEV),'mode':'ro'},{'path':str(MCP),'mode':'rw'}],'exclude':[]}
# Directory-style names apply to files too (same bits: list=read, search=execute, add_file=write).
ACL_TRAVERSE='mcp_andrea allow search'
ACL_RO='mcp_andrea allow list,search,readattr,readextattr,readsecurity,file_inherit,directory_inherit'
ACL_RW_RIGHTS='allow list,add_file,search,delete,add_subdirectory,delete_child,readattr,writeattr,readextattr,writeextattr,readsecurity,file_inherit,directory_inherit'
ACL_RW='mcp_andrea '+ACL_RW_RIGHTS
# Files created by mcp_andrea (UID 5000) stay fully usable by Andrea.
ACL_OWNER=OWNER_NAME+' '+ACL_RW_RIGHTS


def acl_plan():
    return [(HOME,ACL_TRAVERSE,False),(DEV,ACL_RO,False),(MCP,ACL_RW,True),(MCP,ACL_OWNER,True)]


def owner_directory(path):
    try:st=os.lstat(str(path))
    except FileNotFoundError:
        os.mkdir(str(path),0o755);os.chown(str(path),OWNER_UID,20);os.chmod(str(path),0o755)
        st=os.lstat(str(path))
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=OWNER_UID:raise RuntimeError('project folder is not a directory owned by Andrea: '+str(path))
    if os.path.realpath(str(path))!=str(path):raise RuntimeError('project folder must not be a symlink: '+str(path))


def chmod_acl(sign,entry,path,recursive):
    argv=['/bin/chmod']+(['-R'] if recursive else [])+[sign+'a',entry,str(path)]
    return subprocess.run(argv,capture_output=True,text=True,timeout=600,
        env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C.UTF-8'})


def projects_setup():
    import pwd
    u=pwd.getpwnam(OWNER_NAME)
    if u.pw_uid!=OWNER_UID or u.pw_dir!=str(HOME):raise RuntimeError('unexpected owner account')
    if os.path.realpath(str(HOME))!=str(HOME):raise RuntimeError('home must not be a symlink')
    owner_directory(DEV);owner_directory(MCP)
    for path,entry,recursive in acl_plan():
        chmod_acl('-',entry,path,recursive)  # no duplicates on a retry; absence is fine
        r=chmod_acl('+',entry,path,recursive)
        if r.returncode:raise RuntimeError('ACL failed on %s: %s'%(path,(r.stderr or r.stdout)[-300:]))
    atomic(PROJECTS_FILE,(json.dumps(PROJECTS_CONFIG,indent=1)+'\n').encode(),0o644,0,0)
    return {'projects':PROJECTS_CONFIG,'acl':[[str(p),e] for p,e,_ in acl_plan()]}


def projects_remove():
    """Best effort: configuration first (the agent then has no projects), then the explicit ACL entries."""
    errors=[]
    try:
        if PROJECTS_FILE.exists() or PROJECTS_FILE.is_symlink():PROJECTS_FILE.unlink()
    except OSError as e:errors.append('projects.json: '+str(e))
    for path,entry,recursive in reversed(acl_plan()):
        if path.exists():
            r=chmod_acl('-',entry,path,recursive)
            if r.returncode and 'No such' not in (r.stderr or ''):errors.append('%s: %s'%(path,(r.stderr or '')[-200:]))
    return errors


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('one action required')
    main(sys.argv[1])
