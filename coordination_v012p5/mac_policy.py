"""Seatbelt policy for one offline workspace; no shell access to agent state."""
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
