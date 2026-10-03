"""Scoped files and fixed status; shares mac_control locks, no full shell."""
import asyncio
import contextlib
import importlib.util
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from file_tools import FileTools

WORK = Path('/Users/vagrant/MCPAndreaWorkspace')
BASE = Path('/Users/vagrant/.mac-control-gateway/central-adapter')
COORDINATION = Path('/Users/vagrant/mac_control_mcp/mac_control_coordination.py')
CALLER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}')
COMMANDS = {'sw_vers': ('/usr/bin/sw_vers',),
            'xcodebuild -version': ('/usr/bin/xcodebuild', '-version')}


class WorkspaceRuntime:
    def __init__(self, work=WORK, state=None, coordination=None):
        self.work = Path(work)
        self.recent = []
        if coordination is None:
            spec = importlib.util.spec_from_file_location('andrea_coordination', COORDINATION)
            coordination = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(coordination)
        self.coord = coordination
        self.engine = FileTools([str(self.work)], str(state or BASE / 'workspace-operations'),
                                lock_provider=self.lock)

    @contextlib.contextmanager
    def lock(self, caller, path):
        # Unique operation identity prevents concurrent chats sharing one OAuth
        # family from reusing the same lock. The authenticated caller is retained.
        try:
            lock = self.coord.acquire_lock(caller, path, 120, 'central-workspace')
        except Exception:
            raise PermissionError('shared lock unavailable; operation refused') from None
        try:
            yield
        finally:
            self.coord.release_lock(lock['lock_id'], caller)

    async def dispatch(self, backend, message):
        caller = message.get('caller')
        if not isinstance(caller, str) or not CALLER.fullmatch(caller):
            raise ValueError('authenticated gateway caller required')
        op, args = message['op'], message['args']
        identity = caller[:60] + ':' + message['id']
        ok = False
        try:
            if op == 'read_file':
                if set(args) - {'path', 'max_bytes'}:
                    raise ValueError('invalid read arguments')
                limit = args.get('max_bytes', 512 * 1024)
                if type(limit) is not int or not 1 <= limit <= 512 * 1024:
                    raise ValueError('invalid max_bytes')
                path = args.get('path')
                if isinstance(path, str) and (path == str(self.work) or path.startswith(str(self.work) + '/')):
                    data, _ = self.engine._read(path)
                    self.engine._text(data)
                else:
                    result = await backend.call('mac_control', {'action': 'read', 'path': path, 'session_id': identity})
                    data = result['content'].encode('utf-8')
                result = {'path': path, 'content': data[:limit].decode('utf-8', errors='replace'),
                          'truncated': len(data) > limit, 'bytes_returned': min(limit, len(data))}
            elif op in ('write_file', 'rollback_file'):
                result = self.engine.dispatch(op, args, identity)
            elif op == 'who_is_working' and not args:
                result = await backend.call('who_is_working', {'session_id': identity})
                result['gateway_recent_operations'] = self.recent[-20:]
                result['identity_limitation'] = 'OAuth family plus request ID; no persistent identity per chat'
            elif op == 'shell_exec':
                result = await self.status(args)
            elif op == 'disable_full_shell' and not args:
                result = {'enabled': False, 'scope': 'central gateway adapter'}
            elif op in ('enable_full_shell', 'shell_session'):
                raise PermissionError('dedicated non-admin shell service is not installed')
            else:
                raise ValueError('operation not enabled')
            ok = True
            return result
        finally:
            self.recent.append({'time': time.time(), 'caller': caller, 'request_id': message['id'],
                                'operation': op, 'ok': ok})
            del self.recent[:-100]

    async def status(self, args):
        if set(args) - {'command', 'cwd', 'timeout'} or args.get('command') not in COMMANDS:
            raise PermissionError('only fixed system status commands are enabled')
        if args.get('cwd') not in (None, str(self.work)):
            raise ValueError('invalid cwd')
        timeout = args.get('timeout', 30)
        if type(timeout) not in (int, float) or not 0 < timeout <= 120:
            raise ValueError('invalid timeout')
        proc = await asyncio.create_subprocess_exec(*COMMANDS[args['command']],
            cwd=str(self.work), stdin=subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, start_new_session=True,
            env={'HOME': '/Users/vagrant', 'PATH': '/usr/bin:/bin', 'PYTHONNOUSERSITE': '1'})
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), min(timeout, 30))
        except (asyncio.TimeoutError, asyncio.CancelledError):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            raise
        return {'exit_code': proc.returncode, 'output': out[:65536].decode(errors='replace'),
                'truncated': len(out) > 65536, 'timed_out': False}

    def close(self):
        self.engine.close()
