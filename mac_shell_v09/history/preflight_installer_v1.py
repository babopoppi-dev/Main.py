#!/usr/bin/env python3
"""Authorized physical preflight only: no live agent/service/account changes."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
import zlib

BASE = Path('/Library/MCPAndreaShellPreflight20261002')
AREA = Path('/Users/Shared/MCPAndreaShellPreflight20261002')
USER_UUID = '51157D7E-6C57-4928-8CA7-DA0A4F9A9086'
GROUP_UUID = '64F2EE1E-8D97-4161-8B66-D045B7287459'
HARDWARE = '2b9d73883351aa41e92d596b14e725b4ca557d3c596df090fdee4b35ece64784'
PAYLOAD = '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'


def run(argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=15,
                          env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C'})


def identity():
    if sys.platform != 'darwin':
        raise RuntimeError('macOS required')
    raw = run(['/usr/sbin/ioreg', '-rd1', '-c', 'IOPlatformExpertDevice']).stdout
    m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', raw)
    if not m or hashlib.sha256(m.group(1).encode()).hexdigest() != HARDWARE:
        raise RuntimeError('installer is bound to the rented Mac')
    for kind, expected in [('Users', USER_UUID), ('Groups', GROUP_UUID)]:
        fields = ['GeneratedUID', 'PrimaryGroupID']
        if kind == 'Users':
            fields += ['UniqueID', 'UserShell', 'NFSHomeDirectory']
        raw = run(['/usr/bin/dscl', '-plist', '.', '-read', '/' + kind + '/mcp_andrea'] + fields).stdout
        d = {k.split(':')[-1]: v for k, v in plistlib.loads(raw.encode()).items()}
        if d.get('GeneratedUID') != [expected] or d.get('PrimaryGroupID') != ['5000']:
            raise RuntimeError('account/group identity changed')
        if kind == 'Users' and any(d.get(k) != v for k, v in {
            'UniqueID': ['5000'], 'UserShell': ['/usr/bin/false'], 'NFSHomeDirectory': ['/var/empty']}.items()):
            raise RuntimeError('dedicated account changed')
    groups = set(run(['/usr/bin/id', '-G', 'mcp_andrea']).stdout.split())
    if {'0', '80'} & groups or '5000' not in groups:
        raise RuntimeError('dedicated non-admin group required')


def active():
    raw = run(['/bin/ps', '-axo', 'uid=,pid=']).stdout
    return [int(row.split()[1]) for row in raw.splitlines()
            if len(row.split()) == 2 and row.split()[0] == '5000']


def check():
    identity()
    if active():
        raise RuntimeError('uid5000 already running; test refused')
    if any(p.exists() or p.is_symlink() for p in (BASE, AREA)):
        raise RuntimeError('previous preflight exists; inspect instead of overwriting')
    return {'ready': True, 'machine': 'mac_noleggio', 'uid': 5000,
            'action': 'isolated_preflight_only', 'live_agent_changed': False}


def write(path, data, mode=0o644, owner=0):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as f:
        os.fchown(f.fileno(), owner, owner)
        os.fchmod(f.fileno(), mode)
        f.write(data); f.flush(); os.fsync(f.fileno())


def child(argv, timeout):
    # Parent only prepares the isolated area; every shell/cleanup runs as5000.
    return subprocess.run([os.path.realpath(sys.executable), '-I', '-B'] + argv,
                          user=5000, group=5000, extra_groups=[5000], umask=0o077,
                          cwd='/', close_fds=True, start_new_session=True,
                          env={'PATH': '/usr/bin:/bin', 'HOME': '/var/empty', 'LANG': 'en_US.UTF-8'},
                          capture_output=True, text=True, timeout=timeout)


def clear_test_processes():
    if active():
        p = child(['-c', 'import sys;sys.path.insert(0,' + repr(str(BASE / 'code')) + ');'
                   'from mac_guard import stop_dedicated_children;stop_dedicated_children()'], 5)
        if p.returncode:
            raise RuntimeError('non-root test cleanup failed')
    for _ in range(40):
        if not active():
            return
        time.sleep(.1)
    raise RuntimeError('dedicated test processes remain')


def apply():
    check()
    source = globals().get('APPROVED_SOURCE')
    if not isinstance(source, bytes):
        raise RuntimeError('use the supplied SHA-verifying launcher')
    payload = json.loads(zlib.decompress(base64.b64decode(PAYLOAD)))
    expected = {'file_tools.py', 'shell_common.py', 'mac_guard.py', 'mac_policy.py',
                'mac_child.py', 'mac_watchdog.py', 'mac_shell.py', 'preflight_worker.py'}
    if set(payload) != expected:
        raise RuntimeError('unexpected payload')
    BASE.mkdir(mode=0o755)
    before = {'schema': 1, 'user_uuid': USER_UUID, 'group_uuid': GROUP_UUID,
              'source_sha256': hashlib.sha256(source).hexdigest(),
              'original_base': None, 'original_area': None, 'time': time.time()}
    write(BASE / 'before.json', json.dumps(before).encode(), 0o600)
    write(BASE / 'preflight_installer.py', source, 0o500)
    receipt = {'status': 'prepared', 'live_agent_changed': False, 'uid': 5000, 'checks': []}
    try:
        AREA.mkdir(mode=0o755)
        (BASE / 'code').mkdir(mode=0o755)
        for name, body in payload.items():
            write(BASE / 'code' / name, body.encode(), 0o444)
        (BASE / 'run').mkdir(mode=0o700); os.chown(str(BASE / 'run'), 5000, 5000)
        (AREA / 'workspace').mkdir(mode=0o700); os.chown(str(AREA / 'workspace'), 5000, 5000)
        (AREA / 'workspace/.tmp').mkdir(mode=0o700); os.chown(str(AREA / 'workspace/.tmp'), 5000, 5000)
        p = child([str(BASE / 'code/preflight_worker.py'), 'normal'], 45)
        print(p.stdout, end='')
        if p.returncode:
            print(p.stderr[-3000:])
            raise RuntimeError('dedicated shell preflight failed, exit ' + str(p.returncode))
        receipt['checks'] = [json.loads(x) for x in p.stdout.splitlines() if x.startswith('{')]
        if active():
            raise RuntimeError('normal worker left dedicated processes')
        p = child([str(BASE / 'code/preflight_worker.py'), 'agent-death'], 15)
        if p.returncode != 23:
            raise RuntimeError('agent-death test did not reach injection point')
        for _ in range(40):
            if not active():
                break
            time.sleep(.1)
        if active():
            raise RuntimeError('watchdog did not clean agent descendants')
        receipt['checks'].append({'check': 'agent_death_stops_detached', 'passed': True})
        receipt['status'] = 'preflight_passed'
    except Exception as exc:
        receipt['status'] = 'preflight_failed'
        receipt['failure'] = type(exc).__name__ + ': ' + str(exc)[:300]
    finally:
        try:
            clear_test_processes()
            receipt['remaining_uid5000_processes'] = 0
        except Exception as exc:
            receipt['status'] = 'cleanup_requires_review'
            receipt['cleanup_failure'] = type(exc).__name__
        receipt['time'] = time.time()
        write(BASE / 'receipt.json', json.dumps(receipt, indent=2).encode())
        print(json.dumps(receipt, indent=2))
    if receipt['status'] != 'preflight_passed':
        raise SystemExit(1)


def rollback():
    identity()
    if active():
        raise RuntimeError('active uid5000 processes; rollback refused')
    b = BASE.lstat()
    if not stat.S_ISDIR(b.st_mode) or b.st_uid != 0 or b.st_mode & 0o022:
        raise RuntimeError('unsafe preflight state')
    before = json.loads((BASE / 'before.json').read_text())
    if before['user_uuid'] != USER_UUID or before['group_uuid'] != GROUP_UUID:
        raise RuntimeError('rollback identity mismatch')
    if AREA.exists():
        s = AREA.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise RuntimeError('unsafe preflight workspace')
        shutil.rmtree(str(AREA))
    shutil.rmtree(str(BASE))
    print(json.dumps({'status': 'rolled_back', 'live_agent_changed': False}))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('--check', '--apply', '--rollback'):
        raise SystemExit('use --check, --apply or --rollback')
    if sys.argv[1] == '--check':
        print(json.dumps(check(), indent=2)); return
    if os.getuid() != 0 or os.geteuid() != 0:
        raise SystemExit('new explicit physical administrator authorization required')
    os.umask(0o022)
    fd = os.open('/var/run/mcp-andrea-shell-preflight.lock',
                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        apply() if sys.argv[1] == '--apply' else rollback()
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
