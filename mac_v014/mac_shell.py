"""One offline macOS shell, leased to an OAuth authorization, uid5000 only."""
import asyncio
import contextlib
import errno
import fcntl
import os
from pathlib import Path
import pty
import stat
import subprocess
import sys
import time
import uuid

from shell_common import IsolatedShell
from mac_guard import require_identity, stop_dedicated_children
from mac_clock import lease_deadline


class MacShell(IsolatedShell):
    LOG_LIMIT = 16 * 1024 * 1024

    def __init__(self, files, workspace, logs, capable=False):
        super().__init__(files, workspace, capable)
        self.code = Path(__file__).resolve().parent
        self.logs = Path(logs)
        self.logs.mkdir(mode=0o700, exist_ok=True)
        self.watchdog = None

    async def enable(self, caller, minutes):
        require_identity()
        result = await super().enable(caller, minutes)
        if self.watchdog and self.watchdog.poll() is None:
            self.refresh_watchdog()
        return result

    def cwd(self, raw):
        path, root, _ = self.files._path(self.workspace if raw is None else raw)
        if root != self.workspace:
            raise PermissionError('cwd must be inside the shell workspace')
        with self.files._directory(path):
            pass
        return path

    def child_env(self):
        return {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}

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
                self._cleanup_uid()
                return

    async def start(self, caller, command, cwd=None):
        require_identity()
        self.allowed(caller)
        if not isinstance(command, str) or not command.strip() or '\0' in command or len(command.encode()) > 32768:
            raise ValueError('command required; maximum32768 bytes')
        if any(not j['done'].is_set() for j in self.jobs.values()):
            raise PermissionError('workspace already has a running shell')
        while len(self.jobs) >= 16:
            self.jobs.pop(next(iter(self.jobs)))
        cwd = self.cwd(cwd)
        self._trusted_code()
        guard = os.open('guard', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                        0o600, dir_fd=self.files.state_fd)
        master = slave = -1
        log = None
        started = False
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.files._check_journal()
            sid = uuid.uuid4().hex
            logpath = self.logs / (sid + '.log')
            fd = os.open(str(logpath), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            log = os.fdopen(fd, 'wb', buffering=0)
            master, slave = pty.openpty()
            os.set_blocking(master, False)
            started = True
            self._start_watchdog()
            proc = subprocess.Popen(
                [sys.executable, '-I', '-B', str(self.code / 'mac_child.py'),
                 self.workspace, cwd, command, os.ttyname(slave)],
                stdin=slave, stdout=slave, stderr=slave, close_fds=True,
                start_new_session=True, cwd=cwd, env=self.child_env())
            os.close(slave); slave = -1
            job = {'id': sid, 'owner': caller, 'proc': proc, 'fd': master,
                   'guard': guard, 'output': bytearray(), 'base': 0, 'cursor': 0,
                   'done': asyncio.Event(), 'closed': False, 'log': log,
                   'log_path': str(logpath), 'log_bytes': 0, 'log_complete': True}
            self.jobs[sid] = job
            asyncio.get_running_loop().add_reader(master, self._drain, job)
            job['watcher'] = asyncio.create_task(self._watch_job(job))
            master = guard = -1; log = None
            return {'session_id': sid, 'pid': proc.pid, 'running': proc.poll() is None,
                    'scope': self.workspace, 'network': 'disabled', 'uid': 5000}
        except BaseException:
            if started:
                self._cleanup_uid()
            raise
        finally:
            for fd in (master, slave, guard):
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
            # Also catches daemons that detached before the foreground command ended.
            self._cleanup_uid()
            self._drain(job)
        finally:
            if not job['closed']:
                job['closed'] = True
                asyncio.get_running_loop().remove_reader(job['fd'])
                os.close(job['fd']); os.close(job['guard']); job['log'].close()
            job['done'].set()

    async def _terminate(self, job):
        if not job['done'].is_set():
            self._cleanup_uid()
            await asyncio.wait_for(job['done'].wait(), 3)

    def read(self, caller, sid):
        result = super().read(caller, sid)
        job = self.lookup(caller, sid)
        result.update(log_path=job['log_path'], log_complete=job['log_complete'],
                      stop_reason=job.get('stop_reason'))
        return result
