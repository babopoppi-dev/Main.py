#!/usr/bin/env python3
"""Install one scoped userns prerequisite and run harmless containment probes."""
import fcntl
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import tempfile
import time

BASE = Path('/opt/central-mcp-gateway')
SELF = BASE / 'install_isolation_20261002.py'
BINARY = BASE / 'bin/bwrap-mcp'
PROFILE = Path('/etc/apparmor.d/mcp-andrea-bwrap')
BACKUP = BASE / 'backups/pre_isolation_20261002'
RECEIPT = BASE / 'isolation_20261002_receipt.json'
SOURCE = Path('/usr/bin/bwrap')
SOURCE_SHA = 'e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71'
PROFILE_BYTES = b'abi <abi/4.0>,\ninclude <tunables/global>\n\n# Only the root-owned, group-restricted MCP Andrea binary receives this rule.\n# Filesystem/process isolation is applied by bubblewrap and the service unit.\n# The global unprivileged-userns restriction stays enabled.\nprofile mcp-andrea-bwrap /opt/central-mcp-gateway/bin/bwrap-mcp flags=(default_allow) {\n  userns,\n}\n'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data, mode=0o644, gid=0):
    if path.is_symlink():
        raise RuntimeError('symlink rejected')
    fd, temp = tempfile.mkstemp(prefix='.mcp-isolation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchown(f.fileno(), 0, gid)
            os.fchmod(f.fileno(), mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        dfd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def command(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=20,
                          env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}, **kw)


def record(status, **extra):
    atomic(RECEIPT, json.dumps(dict(status=status, time=time.time(), **extra), indent=2).encode())


def profile_command(action):
    result = command(['/sbin/apparmor_parser', action, '-K', str(PROFILE)])
    if result.returncode:
        raise RuntimeError('profile operation failed: ' + result.stderr[:400])


def probe():
    # Mount only OS executables and ephemeral storage: no home, agent config,
    # gateway state, project, host socket, or personal data is mounted.
    prefix = ['runuser', '-u', 'mcp-vps-agent', '--', 'setpriv', '--no-new-privs',
              str(BINARY), '--unshare-all', '--die-with-parent', '--new-session',
              '--cap-drop', 'ALL', '--ro-bind', '/usr', '/usr',
              '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
              '--symlink', 'usr/lib64', '/lib64', '--proc', '/proc', '--dev', '/dev',
              '--tmpfs', '/tmp', '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin']
    result = command(prefix + ['/usr/bin/id', '-u'])
    if result.returncode or result.stdout.strip() != '997':
        raise RuntimeError('isolated id failed: ' + result.stderr[:400])
    # Exact read-only status check for UID, host-path invisibility, no-new-privs
    # and zero effective capabilities. Nothing is written to host files.
    code = """import json,os
status=dict(line.split(':',1) for line in open('/proc/self/status') if ':' in line)
assert os.getuid()==997
assert status['NoNewPrivs'].strip()=='1'
assert int(status['CapEff'].strip(),16)==0
assert not os.path.exists('/home')
assert not os.path.exists('/etc/central-mcp-gateway')
assert not os.path.exists('/var/lib/central-mcp-gateway')
assert not os.path.exists('/etc/central-mcp-vps-agent')
print(json.dumps({'uid':os.getuid(),'no_new_privileges':True,'effective_capabilities':0,'host_state_visible':False}))
"""
    result = command(prefix + ['/usr/bin/python3', '-I', '-c', code])
    if result.returncode:
        raise RuntimeError('containment check failed: ' + result.stderr[:400])
    return json.loads(result.stdout)


def remove_installed():
    # Never remove a profile or executable which was replaced by another actor.
    if PROFILE.exists():
        if PROFILE.read_bytes() != PROFILE_BYTES:
            raise RuntimeError('profile rollback conflict')
        profile_command('-R')
        PROFILE.unlink()
    if BINARY.exists():
        if digest(BINARY.read_bytes()) != SOURCE_SHA:
            raise RuntimeError('binary rollback conflict')
        BINARY.unlink()
    manifest = json.loads((BACKUP / 'manifest.json').read_text())
    if manifest['created_bin_directory']:
        BINARY.parent.rmdir()  # Refuses if another task put files there.


def main(action):
    if os.geteuid() != 0 or Path(__file__).resolve() != SELF:
        raise RuntimeError('installed root helper required')
    s = SELF.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
        raise RuntimeError('unsafe installer ownership')
    fd = os.open('/run/lock/mcp-andrea-isolation.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        if action == '--apply':
            if PROFILE.exists() or PROFILE.is_symlink() or BINARY.exists() or BINARY.is_symlink():
                raise RuntimeError('target already exists; review required')
            u = pwd.getpwnam('mcp-vps-agent')
            if u.pw_uid != 997 or u.pw_gid != 987 or grp.getgrgid(u.pw_gid).gr_name != 'mcp-vps-agent':
                raise RuntimeError('service identity changed')
            source = SOURCE.read_bytes()
            if SOURCE.is_symlink() or SOURCE.stat().st_uid != 0 or digest(source) != SOURCE_SHA:
                raise RuntimeError('system bubblewrap changed')
            if Path('/proc/sys/kernel/apparmor_restrict_unprivileged_userns').read_text().strip() != '1':
                raise RuntimeError('expected global restriction is not enabled')
            created_dir = not BINARY.parent.exists()
            if not created_dir:
                s = BINARY.parent.lstat()
                if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
                    raise RuntimeError('unsafe binary directory')
            BACKUP.mkdir(mode=0o700, exist_ok=False)
            atomic(BACKUP / 'manifest.json', json.dumps({'binary_previously_absent': True,
                    'profile_previously_absent': True, 'created_bin_directory': created_dir,
                    'binary_sha256': SOURCE_SHA, 'profile_sha256': digest(PROFILE_BYTES)}).encode(), 0o600)
            loaded = False
            try:
                if created_dir:
                    BINARY.parent.mkdir(mode=0o750)
                    os.chown(BINARY.parent, 0, u.pw_gid)
                    os.chmod(BINARY.parent, 0o750)
                atomic(BINARY, source, 0o550, u.pw_gid)
                atomic(PROFILE, PROFILE_BYTES)
                profile_command('-a')
                loaded = True
                checks = probe()
                record('prerequisite_ready', checks=checks, binary=str(BINARY),
                       profile=str(PROFILE), shell_enabled=False, backup=str(BACKUP))
                print(json.dumps({'status': 'prerequisite_ready', 'checks': checks, 'shell_enabled': False}))
            except BaseException:
                # A parser failure must not leave an unloaded profile behind.
                if not loaded and PROFILE.exists() and PROFILE.read_bytes() == PROFILE_BYTES:
                    PROFILE.unlink()
                try:
                    remove_installed()
                    record('rolled_back', reason='profile or isolation probe failed')
                except BaseException:
                    record('rollback_failed')
                raise
        elif action == '--rollback':
            remove_installed()
            record('rolled_back', reason='approved rollback')
            print('ISOLATION_PREREQUISITE_REMOVED')
        else:
            raise ValueError('invalid action')
    finally:
        os.close(fd)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('one action required')
    main(sys.argv[1])
