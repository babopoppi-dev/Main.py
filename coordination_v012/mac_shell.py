"""macOS shell lease for one work session, uid5000 only.

Up to MAX_RUNNING concurrent processes share the lease, the workspace guard
and the watchdog. Stopping one process kills its process group; the full
uid5000 cleanup runs when the last one ends, on stop of the last one and
when the lease ends. Network is off unless the lease selects a profile.
"""
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
from net_proxy import GitHubProxy, PROFILES


class MacShell(IsolatedShell):
    LOG_LIMIT = 16 * 1024 * 1024
    MAX_RUNNING = 4

    def __init__(self, files, workspace, logs, capable=False):
        super().__init__(files, workspace, capable)
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
        return env

    def cwd(self, raw):
        path, root, _ = self.files._path(self.workspace if raw is None else raw)
        if root != self.workspace:
            raise PermissionError('cwd must be inside the shell workspace')
        with self.files._directory(path):
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
