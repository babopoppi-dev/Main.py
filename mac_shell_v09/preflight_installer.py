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

BASE = Path('/Library/MCPAndreaShellPreflightR2_20261002')
AREA = Path('/Users/Shared/MCPAndreaShellPreflightR2_20261002')
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
                'mac_child.py', 'mac_watchdog.py', 'mac_shell.py', 'preflight_worker.py', 'mac_clock.py'}
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
        write(BASE / 'worker-normal.log', (p.stdout + '\n' + p.stderr).encode()[-65536:])
        receipt['checks'] = [json.loads(x) for x in p.stdout.splitlines() if x.startswith('{')]
        if p.returncode:
            print(p.stderr[-3000:])
            raise RuntimeError('dedicated shell preflight failed, exit ' + str(p.returncode))
        if active():
            raise RuntimeError('normal worker left dedicated processes')
        p = child([str(BASE / 'code/preflight_worker.py'), 'agent-death'], 15)
        write(BASE / 'worker-agent-death.log', (p.stdout + '\n' + p.stderr).encode()[-65536:])
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
