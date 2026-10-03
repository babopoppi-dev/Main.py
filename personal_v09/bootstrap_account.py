#!/usr/bin/env python3
"""Create only the dedicated, disabled-login account on the personal Mac.

No agent migration, sudo rule, service installation, network request or project edit.
Run --check without privileges. --apply/--rollback require explicit local approval.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid

NAME = 'mcp_andrea'
IDENT = 5000
FINGERPRINT = '13e94bc1b7e266b260a0eb5aa9e0b3ffa4cd322a419b6be36481c583f6454d9d'
STATE = Path('/Library/MCPAndreaMacMioAccountV09')
RECORDS = {'user': '/Users/' + NAME, 'group': '/Groups/' + NAME}


def run(argv, check=True):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=20,
                       env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C'})
    if check and p.returncode:
        raise RuntimeError('command failed: ' + argv[0] + ' ' + str(p.returncode))
    return p


def record(path):
    p = run(['/usr/bin/dscl', '-plist', '.', '-read', path], check=False)
    if p.returncode:
        if 'eDSRecordNotFound' in p.stdout + p.stderr:
            return None
        raise RuntimeError('directory service read failed')
    raw = plistlib.loads(p.stdout.encode())
    return {k.split(':')[-1]: v for k, v in raw.items()}


def identifiers(category, field):
    text = run(['/usr/bin/dscl', '.', '-list', '/' + category, field]).stdout
    return {int(row.split()[-1]) for row in text.splitlines() if row.strip()}


def machine_check():
    if sys.platform != 'darwin':
        raise RuntimeError('macOS required')
    out = run(['/usr/sbin/ioreg', '-rd1', '-c', 'IOPlatformExpertDevice']).stdout
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
    if not match or hashlib.sha256(match.group(1).encode()).hexdigest() != FINGERPRINT:
        raise RuntimeError('this installer is bound to mac_mio')


def preflight():
    machine_check()
    if STATE.exists() or STATE.is_symlink():
        raise RuntimeError('previous bootstrap state exists; review before retry')
    for path in RECORDS.values():
        if record(path) is not None:
            raise RuntimeError('existing account/group will not be changed')
    for category, field in [('Users', 'UniqueID'), ('Groups', 'PrimaryGroupID')]:
        if IDENT in identifiers(category, field):
            raise RuntimeError('UID/GID 5000 already in use')
    return {'ready': True, 'machine': 'mac_mio', 'account': NAME,
            'uid': IDENT, 'gid': IDENT, 'login': 'disabled', 'admin': False,
            'agent_changed': False, 'projects_changed': False}


def trusted_directory(path):
    for p in [path] + list(path.parents):
        s = p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise RuntimeError('root-owned, non-writable parent required')


def atomic(path, data, mode=0o600):
    if path.is_symlink():
        raise RuntimeError('symlink rejected')
    fd, name = tempfile.mkstemp(prefix='.bootstrap-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), mode)
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(data):
    atomic(STATE / 'receipt.json', json.dumps(data, indent=2).encode())


def set_attribute(path, key, value):
    run(['/usr/bin/dscl', '.', '-create', path, key, str(value)])


def active_processes():
    p = run(['/bin/ps', '-axo', 'uid=,pid='])
    return [int(row.split()[1]) for row in p.stdout.splitlines()
            if len(row.split()) == 2 and int(row.split()[0]) == IDENT]


def rollback(receipt):
    # Refuse to remove a reused identity, a running service or new group members.
    if active_processes():
        raise RuntimeError('account has running processes; stop and review')
    for kind in ('user', 'group'):
        current = record(RECORDS[kind])
        if current is None:
            continue
        if current.get('GeneratedUID') != [receipt[kind + '_uuid']]:
            raise RuntimeError('rollback identity conflict')
        key = 'UniqueID' if kind == 'user' else 'PrimaryGroupID'
        if current.get(key) not in (None, [str(IDENT)]):
            raise RuntimeError('rollback numeric identity conflict')
        if kind == 'user':
            expected = {'UserShell': ['/usr/bin/false'], 'NFSHomeDirectory': ['/var/empty'],
                        'Password': ['*'], 'AuthenticationAuthority': [';DisabledUser;']}
            if any(current.get(k) not in (None, v) for k, v in expected.items()):
                raise RuntimeError('account has been repurposed; review required')
        if kind == 'group' and any(current.get(x) for x in
                                    ('GroupMembership', 'GroupMembers', 'NestedGroups')):
            raise RuntimeError('group now has members; review required')
    for kind in ('user', 'group'):
        if record(RECORDS[kind]) is not None:
            run(['/usr/bin/dscl', '.', '-delete', RECORDS[kind]])
    receipt['status'] = 'rolled_back'
    save(receipt)


def apply():
    preflight()
    trusted_directory(STATE.parent)
    data = globals().get('APPROVED_SOURCE')
    if not isinstance(data, bytes):
        raise RuntimeError('use the supplied SHA256-verifying in-memory launcher')
    STATE.mkdir(mode=0o700)
    receipt = {'status': 'prepared', 'time': time.time(), 'account': NAME,
               'uid': IDENT, 'gid': IDENT, 'previous_user': None, 'previous_group': None,
               'user_uuid': str(uuid.uuid4()).upper(),
               'group_uuid': str(uuid.uuid4()).upper(),
               'source_sha256': hashlib.sha256(data).hexdigest()}
    # Snapshot of original absence and immutable rollback copy precede changes.
    atomic(STATE / 'before.json', json.dumps(receipt, indent=2).encode())
    atomic(STATE / 'bootstrap_account.py', data, 0o500)
    save(receipt)
    try:
        group = RECORDS['group']; user = RECORDS['user']
        set_attribute(group, 'GeneratedUID', receipt['group_uuid'])
        set_attribute(group, 'PrimaryGroupID', IDENT)
        set_attribute(group, 'RealName', 'MCP Andrea service')
        set_attribute(user, 'GeneratedUID', receipt['user_uuid'])
        set_attribute(user, 'AuthenticationAuthority', ';DisabledUser;')
        set_attribute(user, 'Password', '*')
        set_attribute(user, 'UserShell', '/usr/bin/false')
        set_attribute(user, 'NFSHomeDirectory', '/var/empty')
        set_attribute(user, 'RealName', 'MCP Andrea service')
        set_attribute(user, 'PrimaryGroupID', IDENT)
        set_attribute(user, 'UniqueID', IDENT)
        u = record(user); g = record(group)
        expected = {'UniqueID': [str(IDENT)], 'PrimaryGroupID': [str(IDENT)],
                    'UserShell': ['/usr/bin/false'], 'Password': ['*'],
                    'AuthenticationAuthority': [';DisabledUser;']}
        if any(u.get(k) != v for k, v in expected.items()):
            raise RuntimeError('account verification failed')
        if g.get('PrimaryGroupID') != [str(IDENT)]:
            raise RuntimeError('group verification failed')
        groups = run(['/usr/bin/id', '-G', NAME]).stdout.split()
        if {'0', '80'} & set(groups) or str(IDENT) not in groups:
            raise RuntimeError('unexpected administrator/group membership')
        receipt.update(status='account_ready', login='disabled', administrator=False,
                       agent_migrated=False, home_created=False)
        save(receipt)
        print(json.dumps(receipt, indent=2))
    except Exception:
        try:
            rollback(receipt)
        except Exception:
            receipt['status'] = 'rollback_requires_review'; save(receipt)
        raise


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('--check', '--apply', '--rollback'):
        raise SystemExit('use --check, --apply or --rollback')
    action = sys.argv[1]
    if action == '--check':
        print(json.dumps(preflight(), indent=2)); return
    if os.geteuid() != 0:
        raise SystemExit('explicit local administrator approval required')
    machine_check()
    os.umask(0o077)
    fd = os.open('/var/run/mcp-andrea-account-bootstrap.lock',
                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        s = os.fstat(fd)
        if s.st_uid != 0 or s.st_mode & 0o077:
            raise RuntimeError('unsafe maintenance lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if action == '--apply':
            apply()
        else:
            trusted_directory(STATE)
            rollback(json.loads((STATE / 'receipt.json').read_text()))
            print('rolled_back; original agent and projects were not changed')
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
