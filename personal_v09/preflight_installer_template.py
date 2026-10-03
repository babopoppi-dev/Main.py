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

BASE = Path('/Library/MCPAndreaMacMioPreflightV09')
AREA = Path('/Users/Shared/MCPAndreaMacMioPreflightV09')
USER_UUID = None
GROUP_UUID = None
HARDWARE = '13e94bc1b7e266b260a0eb5aa9e0b3ffa4cd322a419b6be36481c583f6454d9d'
PAYLOAD = '__PAYLOAD__'


ACCOUNT_STATE=Path('/Library/MCPAndreaMacMioAccountV09')
ACCOUNT_HASH='__ACCOUNT_HASH__'


def account_uuids():
    path=ACCOUNT_STATE/'receipt.json'
    for parent in path.parents:
        st=parent.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
            raise RuntimeError('unsafe account receipt parent')
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077 or st.st_nlink!=1:
            raise RuntimeError('unsafe account receipt')
        raw=f.read(8193)
    if len(raw)>8192:raise RuntimeError('account receipt too large')
    d=json.loads(raw)
    if d.get('status')!='account_ready' or d.get('source_sha256')!=ACCOUNT_HASH or d.get('uid')!=5000 or d.get('gid')!=5000:
        raise RuntimeError('account bootstrap not verified')
    ids=[d.get('user_uuid'),d.get('group_uuid')]
    if any(not isinstance(v,str) or not re.fullmatch(r'[A-F0-9]{8}(?:-[A-F0-9]{4}){3}-[A-F0-9]{12}',v) for v in ids):
        raise RuntimeError('invalid generated account identity')
    return ids


def run(argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=15,
                          env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C'})


def identity():
    if sys.platform != 'darwin':
        raise RuntimeError('macOS required')
    global USER_UUID, GROUP_UUID
    USER_UUID, GROUP_UUID=account_uuids()
    raw = run(['/usr/sbin/ioreg', '-rd1', '-c', 'IOPlatformExpertDevice']).stdout
    m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', raw)
    if not m or hashlib.sha256(m.group(1).encode()).hexdigest() != HARDWARE:
        raise RuntimeError('installer is bound to the personal Mac')
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
    return {'ready': True, 'machine': 'mac_mio', 'uid': 5000,
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
        p = child([str(BASE / 'code/preflight_worker.py'), 'normal'], 90)
        print(p.stdout, end='')
        write(BASE / 'worker-normal.log', (p.stdout + '\n' + p.stderr).encode()[-65536:])
        receipt['checks'] = [json.loads(x) for x in p.stdout.splitlines() if x.startswith('{')]
        if p.returncode:
            print(p.stderr[-3000:])
            raise RuntimeError('dedicated shell preflight failed, exit ' + str(p.returncode))
        if active():
            raise RuntimeError('normal worker left dedicated processes')
        p = child([str(BASE / 'code/preflight_worker.py'), 'agent-death'], 30)
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
