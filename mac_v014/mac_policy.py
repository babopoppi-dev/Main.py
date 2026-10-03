"""Seatbelt policy for one workspace; offline, or only the local allowlist proxy (point F)."""
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


TRUST_SERVICES = ('com.apple.trustd', 'com.apple.trustd.agent')


def profile(workspace, tty_path=None, proxy_port=None):
    workspace = os.path.realpath(workspace)
    if not workspace.startswith('/Users/') or workspace in ('/Users', '/Users/Shared'):
        raise ValueError('narrow workspace required')
    if tty_path and (not tty_path.startswith('/dev/ttys') or '/' in tty_path[5:]):
        raise ValueError('expected a macOS PTY')
    if proxy_port is not None and (type(proxy_port) is not int or not 1024 <= proxy_port <= 65535):
        raise ValueError('invalid proxy port')
    rules = ['(version 1)', '(deny default)']
    if proxy_port is None:
        rules += ['(deny network*)', '(deny mach-lookup)']
    else:
        # Only one outbound TCP connection: the agent's allowlist proxy on loopback.
        # Certificate validation for system TLS clients (curl, git) needs trustd.
        rules.append('(allow network-outbound (remote tcp ' + json.dumps('localhost:%d' % proxy_port) + '))')
        rules.append('(allow mach-lookup ' + ' '.join('(global-name %s)' % json.dumps(n) for n in TRUST_SERVICES) + ')')
        rules.append('(allow file-read* (subpath "/Library/Keychains") (subpath "/private/var/db/mds"))')
    rules += ['(deny mach-register)', '(deny appleevent-send)',
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
    rules.append('(allow file-write* (subpath ' + json.dumps(workspace) + '))')
    rules.append('(allow file-write* (literal "/dev/null"))')
    if tty_path:
        rules.append('(allow file-read* file-write* (literal ' + json.dumps(tty_path) + '))')
    return '\n'.join(rules) + '\n'
