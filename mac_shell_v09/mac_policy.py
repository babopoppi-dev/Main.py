"""Seatbelt policy for one offline workspace; no shell access to agent state."""
import json
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
    # Xcode on this hosted Mac is installed by vagrant (501), an administrator.
    # The service identity 5000 cannot write these files or their parent folders.
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


def profile(workspace, tty_path=None):
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
                 '/Applications/Xcode-26.6.0.app', '/private/var/db/dyld',
                 '/private/var/db/timezone', workspace]:
        rules.append('(allow file-read* (subpath ' + json.dumps(path) + '))')
    # dyld needs read access to the root directory itself (not its contents).
    for path in ['/', '/dev/null', '/dev/random', '/dev/urandom', '/private/etc/localtime']:
        rules.append('(allow file-read* (literal ' + json.dumps(path) + '))')
    rules.append('(allow file-write* (subpath ' + json.dumps(workspace) + '))')
    rules.append('(allow file-write* (literal "/dev/null"))')
    if tty_path:
        rules.append('(allow file-read* file-write* (literal ' + json.dumps(tty_path) + '))')
    return '\n'.join(rules) + '\n'
