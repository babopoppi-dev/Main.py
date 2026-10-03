"""Bounded, offline Linux workspace shell; no gateway secrets enter the child."""
import asyncio
import errno
import fcntl
import json
import math
import os
import pty
import re
import signal
import stat
import subprocess
import time
import uuid


class IsolatedShell:
    MAX_OUTPUT = 262144
    BWRAP = '/opt/central-mcp-gateway/bin/bwrap-mcp'

    def __init__(self, files, workspace, capable=False):
        self.files = files
        self.workspace, self.root, parts = files._path(workspace)
        if parts or self.root != self.workspace:
            raise ValueError('shell workspace must be a configured root')
        self.capable = capable
        self.owner = None
        self.until = 0.0
        self.jobs = {}
        self.lease_task = None

    @staticmethod
    def identity(caller):
        if not isinstance(caller, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}', caller):
            raise PermissionError('authenticated gateway identity required')
        return caller

    def allowed(self, caller):
        self.identity(caller)
        if not self.capable or self.owner != caller or time.monotonic() >= self.until:
            raise PermissionError('enable the isolated shell for this client first')

    async def enable(self, caller, minutes):
        self.identity(caller)
        if not self.capable:
            raise PermissionError('isolated shell has not been installed and verified')
        if type(minutes) is not int or not 1 <= minutes <= 240:
            raise ValueError('minutes must be an integer from 1 to 240')
        if self.owner is not None and time.monotonic() < self.until and self.owner != caller:
            raise PermissionError('another client holds the workspace shell lease')
        if self.owner is not None and time.monotonic() >= self.until:
            await self.disable()
        self.owner, self.until = caller, time.monotonic() + minutes * 60
        if self.lease_task is None or self.lease_task.done():
            self.lease_task = asyncio.create_task(self._watch_lease())
        return {'enabled': True, 'minutes': minutes, 'expires_at_epoch': time.time() + minutes * 60,
                'scope': self.workspace, 'network': 'disabled', 'maximum_active_sessions': 1,
                'identity_scope': 'OAuth authorization, not an individual chat'}

    async def _watch_lease(self):
        try:
            while self.owner is not None:
                if time.monotonic() >= self.until:
                    await self.disable()
                    return
                await asyncio.sleep(min(.2, max(.01, self.until - time.monotonic())))
        except asyncio.CancelledError:
            pass

    async def disable(self):
        self.until = 0.0
        self.owner = None
        task, self.lease_task = self.lease_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        for job in list(self.jobs.values()):
            await self._terminate(job)
        return {'enabled': False, 'running_sessions': 0}

    def cwd(self, raw):
        raw = self.workspace if raw is None else raw
        canonical, root, parts = self.files._path(raw)
        if root != self.workspace:
            raise PermissionError('shell cwd must be inside its workspace')
        with self.files._directory(canonical):
            pass
        return '/workspace' + ('/' + '/'.join(parts) if parts else '')

    def argv(self, command, cwd, rootfd, infofd):
        return ['/usr/bin/prlimit', '--nproc=64', '--nofile=128', '--as=1073741824',
                '--fsize=16777216', '--core=0', '--cpu=120', self.BWRAP,
                '--unshare-all', '--unshare-user', '--disable-userns', '--die-with-parent', '--new-session',
                '--cap-drop', 'ALL', '--ro-bind', '/usr', '/usr',
                '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
                '--symlink', 'usr/lib64', '/lib64', '--proc', '/proc', '--dev', '/dev',
                '--size', '67108864', '--tmpfs', '/tmp', '--dir', '/run',
                '--bind-fd', str(rootfd), '/workspace', '--chdir', cwd,
                '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin',
                '--setenv', 'HOME', '/workspace', '--setenv', 'LANG', 'C.UTF-8',
                '--setenv', 'TERM', 'xterm', '--info-fd', str(infofd),
                '--', '/bin/bash', '--noprofile', '--norc', '-c', command]

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
            job['output'].extend(chunk)
            excess = len(job['output']) - self.MAX_OUTPUT
            if excess > 0:
                del job['output'][:excess]
                job['base'] += excess

    async def start(self, caller, command, cwd=None):
        self.allowed(caller)
        if not isinstance(command, str) or not command.strip() or '\0' in command or len(command.encode()) > 32768:
            raise ValueError('command required; maximum 32768 bytes')
        if any(j['proc'].poll() is None for j in self.jobs.values()):
            raise PermissionError('workspace already has a running shell; stop or reuse it')
        # Drop completed sessions in bounded order; active sessions are never evicted.
        while len(self.jobs) >= 16:
            self.jobs.pop(next(iter(self.jobs)))
        sandbox_cwd = self.cwd(cwd)
        guard = os.open('guard', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.files.state_fd)
        master = slave = info_read = info_write = -1
        proc = None
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.files._check_journal()
            # The exact directory inode, already checked by cwd(), is mounted.
            rootfd = self.files.root_fds[self.workspace]
            st = os.stat(self.BWRAP, follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o6022:
                raise PermissionError('unsafe sandbox executable')
            master, slave = pty.openpty()
            info_read, info_write = os.pipe()
            os.set_blocking(master, False)
            os.set_blocking(info_read, False)
            proc = subprocess.Popen(self.argv(command, sandbox_cwd, rootfd, info_write),
                                    stdin=slave, stdout=slave, stderr=slave, close_fds=True,
                                    pass_fds=(rootfd, info_write), start_new_session=True,
                                    cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
            os.close(slave); slave = -1
            os.close(info_write); info_write = -1
            info = bytearray()
            limit = time.monotonic() + 3
            while time.monotonic() < limit:
                try:
                    chunk = os.read(info_read, 4096)
                    info.extend(chunk)
                    if len(info) > 4096:
                        raise RuntimeError('sandbox status exceeded limit')
                    if not chunk or info.rstrip().endswith(b'}'):
                        break
                except BlockingIOError:
                    pass
                await asyncio.sleep(.01)
            if not info:
                try:
                    diagnostic = os.read(master, 2048).decode('utf-8', errors='replace').strip()
                except (BlockingIOError, OSError):
                    diagnostic = 'no diagnostic output'
                raise RuntimeError('sandbox initialization failed: ' + diagnostic)
            value = json.loads(info)
            if type(value.get('child-pid')) is not int or value['child-pid'] <= 1:
                raise RuntimeError('sandbox failed to initialize')
            sid = uuid.uuid4().hex
            job = {'id': sid, 'owner': caller, 'proc': proc, 'fd': master, 'guard': guard,
                   'output': bytearray(), 'base': 0, 'cursor': 0,
                   'done': asyncio.Event(), 'closed': False}
            self.jobs[sid] = job
            asyncio.get_running_loop().add_reader(master, self._drain, job)
            job['watcher'] = asyncio.create_task(self._watch_job(job))
            master = guard = -1
            return {'session_id': sid, 'pid': proc.pid, 'running': proc.poll() is None,
                    'scope': self.workspace, 'network': 'disabled'}
        except BaseException:
            if proc is not None:
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=3)
            raise
        finally:
            for fd in (master, slave, info_read, info_write, guard):
                if fd >= 0:
                    os.close(fd)

    async def _watch_job(self, job):
        try:
            while job['proc'].poll() is None:
                await asyncio.sleep(.05)
            self._drain(job)
        finally:
            if not job['closed']:
                job['closed'] = True
                asyncio.get_running_loop().remove_reader(job['fd'])
                os.close(job['fd'])
                os.close(job['guard'])
            job['done'].set()

    async def _terminate(self, job):
        # Kill bubblewrap's monitor: --die-with-parent kills namespace PID1,
        # which tears down every descendant, including processes using setsid().
        if job['proc'].poll() is None:
            job['proc'].kill()
        await asyncio.wait_for(job['done'].wait(), 3)

    def lookup(self, caller, sid):
        self.identity(caller)
        if not isinstance(sid, str) or not re.fullmatch(r'[a-f0-9]{32}', sid):
            raise ValueError('invalid session id')
        job = self.jobs.get(sid)
        if job is None or job['owner'] != caller:
            raise PermissionError('session unavailable to this client')
        return job

    def read(self, caller, sid):
        job = self.lookup(caller, sid)
        start = max(job['cursor'], job['base'])
        end = min(job['base'] + len(job['output']), start + 65536)
        data = bytes(job['output'][start - job['base']:end - job['base']])
        truncated = job['cursor'] < job['base']
        job['cursor'] = end
        return {'session_id': sid, 'running': not job['done'].is_set(),
                'exit_code': job['proc'].poll(), 'output': data.decode('utf-8', errors='replace'),
                'truncated': truncated, 'has_more': end < job['base'] + len(job['output'])}

    async def session(self, caller, args):
        action = args.get('action')
        if action == 'start':
            return await self.start(caller, args.get('command'), args.get('cwd'))
        job = self.lookup(caller, args.get('session_id'))
        if action == 'read':
            return self.read(caller, job['id'])
        if action == 'stop':
            await self._terminate(job)
            return {'session_id': job['id'], 'stopped': True, 'exit_code': job['proc'].returncode}
        if action == 'send':
            self.allowed(caller)
            data = args.get('data')
            if not isinstance(data, str) or len(data.encode()) > 16384:
                raise ValueError('input must be text of at most 16384 bytes')
            if job['closed'] or job['proc'].poll() is not None:
                raise ValueError('session already ended')
            try:
                count = os.write(job['fd'], data.encode())
            except BlockingIOError:
                count = 0
            return {'session_id': job['id'], 'bytes_sent': count}
        raise ValueError('unknown session action')

    async def execute(self, caller, args):
        timeout = args.get('timeout', 120)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('positive finite timeout required')
        started = await self.start(caller, args.get('command'), args.get('cwd'))
        job = self.jobs[started['session_id']]
        try:
            # Keep the gateway responsive; longer work continues as a session.
            await asyncio.wait_for(job['done'].wait(), min(timeout, 3))
        except asyncio.TimeoutError:
            pass
        return self.read(caller, job['id'])

    def working(self):
        active = [{'session_id': j['id'], 'owner': j['owner'], 'path': self.workspace}
                  for j in self.jobs.values() if not j['done'].is_set()]
        return {'active_locks': active, 'coordination': 'exclusive workspace shell and shared file-journal lock',
                'shell_enabled': self.owner is not None and time.monotonic() < self.until,
                'identity_scope': 'OAuth authorization; separate chats can share an authorization'}
