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
PAYLOAD = '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'


ACCOUNT_STATE=Path('/Library/MCPAndreaMacMioAccountV09')
ACCOUNT_HASH='c266d38a0a593db98364b42113495229125e6919c3f9d025b1088f7f2b0feec3'


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
