"""Fail closed before cleanup; only the dedicated macOS account may signal."""
import os
import pwd
import signal
import subprocess
import sys
import time

UID = 5000
NAME = 'mcp_andrea'


def require_identity():
    if sys.platform != 'darwin' or os.getuid() != UID or os.geteuid() != UID:
        raise PermissionError('dedicated macOS uid5000 required; root and uid501 forbidden')
    if os.getgid() != UID or os.getegid() != UID or {0, 80} & set(os.getgroups()):
        raise PermissionError('dedicated non-admin group required')
    if pwd.getpwuid(UID).pw_name != NAME:
        raise PermissionError('dedicated identity changed')


def parse_processes(output, scanner_pid, own_pid):
    targets = set()
    if len(output) > 1048576:
        raise RuntimeError('process inventory too large')
    for line in output.splitlines():
        fields = line.split()
        if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
            raise RuntimeError('invalid process inventory')
        uid, pid = int(fields[0]), int(fields[1])
        if uid == UID and pid > 1 and pid not in (scanner_pid, own_pid) and not fields[2].startswith('Z'):
            targets.add(pid)
    return targets


def targets():
    require_identity()
    with subprocess.Popen(['/bin/ps', '-axo', 'uid=,pid=,stat='],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          close_fds=True, env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}) as proc:
        try:
            output, _ = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.communicate()
            raise RuntimeError('process inventory timed out') from None
        if proc.returncode:
            raise RuntimeError('process inventory failed')
        return parse_processes(output, proc.pid, os.getpid())


def signal_target(pid, sig):
    require_identity()
    if type(pid) is not int or pid <= 1 or pid == os.getpid():
        raise PermissionError('explicit child PID required; broadcast and self forbidden')
    try:
        # Even if a PID is reused between ps and kill, the kernel permits this
        # non-root caller to signal only the same dedicated identity.
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def stop_dedicated_children():
    require_identity()
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        batch = targets()
        if not batch:
            return
        # Freeze before terminating, then re-scan to catch a child born just
        # before its parent stopped. Never rely on kill(-1) sender exclusion.
        for pid in sorted(batch):
            signal_target(pid, signal.SIGSTOP)
        for pid in sorted(batch):
            signal_target(pid, signal.SIGKILL)
        time.sleep(.02)
    if targets():
        raise RuntimeError('dedicated processes remain after cleanup')
