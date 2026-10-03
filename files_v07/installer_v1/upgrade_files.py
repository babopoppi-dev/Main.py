#!/usr/bin/env python3
"""Pinned root installer for file tools; run only after Telegram approval."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

BASE = Path('/opt/central-mcp-gateway')
SELF = BASE / 'upgrade_files_v07_20261002.py'
BACKUP = BASE / 'backups/pre_files_v07_20261002'
RECEIPT = BASE / 'files_v07_receipt.json'
SERVICES = ['central-mcp-vps-agent-test.service', 'central-mcp-gateway-test.service']
ORIGINAL = {'agent.py': '10d72908db298e613a071a1f3bb759f95b1d31818c20aa066e8c1b213e56fd58',
            'cg_tools.py': '4f11a2e6786ff514dfcb9e28f6b7f88972660c349446b6c0ea4eb3f9925a7283',
            'file_tools.py': None, 'file_schema.py': None}
PAYLOAD = {}  # Filled by build_installer.py, not taken from command arguments.


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data, mode=0o644, uid=0, gid=0):
    if path.is_symlink():
        raise RuntimeError('symlink rejected')
    fd, tmp = tempfile.mkstemp(prefix='.files-v07-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            os.fchown(handle.fileno(), uid, gid)
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dfd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def record(status, **extra):
    atomic(RECEIPT, json.dumps(dict(status=status, time=time.time(), **extra), indent=2).encode())


def rpc(method, params):
    cfg = json.loads(Path('/etc/central-mcp-gateway/gateway-test.json').read_text())
    context = ssl.create_default_context(cafile=cfg['tls_cert'])
    context.check_hostname = False  # Local address, certificate still verified.
    token = Path(cfg['mcp_token_file']).read_text().strip()
    data = json.dumps({'jsonrpc': '2.0', 'id': uuid.uuid4().hex,
                       'method': method, 'params': params}).encode()
    req = urllib.request.Request('https://127.0.0.1:' + str(cfg['port']) + '/mcp', data=data,
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    # The static token is sent only over verified TLS to loopback, never printed.
    with urllib.request.urlopen(req, context=context, timeout=8) as response:
        value = json.load(response)
    if 'error' in value:
        raise RuntimeError('gateway RPC rejected')
    return value['result']


def call(name, **args):
    result = rpc('tools/call', {'name': name, 'arguments': args})
    if result.get('isError'):
        raise RuntimeError('smoke operation rejected: ' + name)
    return json.loads(result['content'][0]['text'])


def restart():
    for service in SERVICES:
        subprocess.run(['systemctl', 'restart', service], check=True, capture_output=True, timeout=20)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            machines = call('list_machines')['machines']
            if any(x['machine'] == 'vps' and x['online'] for x in machines):
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError('gateway/VPS agent did not reconnect')


def restore():
    manifest = json.loads((BACKUP / 'manifest.json').read_text())
    for name, meta in manifest.items():
        if meta is None:
            path = BASE / name
            if path.exists():
                if sha(path.read_bytes()) != PAYLOAD[name]['sha256']:
                    raise RuntimeError('new module changed before rollback')
                path.unlink()
        else:
            data = (BACKUP / name).read_bytes()
            if sha(data) != ORIGINAL[name]:
                raise RuntimeError('backup changed')
            atomic(BASE / name, data, meta['mode'], meta['uid'], meta['gid'])
    restart()


def smoke():
    names = {t['name'] for t in rpc('tools/list', {})['tools']}
    required = {'create_directory', 'list_directory', 'read_multiple_files',
                'get_file_info', 'edit_block', 'move_file', 'admin_request', 'admin_result'}
    if not required <= names:
        raise RuntimeError('public catalog incomplete')
    roots = {'vps': '/var/lib/central-mcp-vps-agent-test/workspace',
             'mac_noleggio': '/Users/vagrant/MCPAndreaWorkspace',
             'mac_mio': '/Users/babo/MCPAndreaWorkspace'}
    checked = []
    for machine, root in roots.items():
        directory = root + '/collaudo_file_v07_' + uuid.uuid4().hex[:12]
        src, dst = directory + '/a.txt', directory + '/b.txt'
        journal = []
        def op(name, **args):
            value = call(name, machine=machine, **args)
            if 'operation_id' in value:
                journal.append(value['operation_id'])
            return value
        try:
            op('create_directory', path=directory)
            op('write_file', path=src, content='MCP Andrea\nprova\n')
            op('edit_block', file_path=src, old_string='prova', new_string='verificato')
            op('move_file', source=src, destination=dst)
            assert call('read_file', machine=machine, path=dst, offset=-1, length=1)['content'] == 'verificato\n'
            call('list_directory', machine=machine, path=directory, depth=1)
            call('get_file_info', machine=machine, path=dst)
            batch = call('read_multiple_files', machine=machine, paths=[dst])
            assert batch['files'][0]['success']
        finally:
            for operation_id in reversed(journal):
                call('rollback_file', machine=machine, operation_id=operation_id)
        checked.append({'machine': machine, 'file_tools': 'passed', 'rollback': 'completed', 'test_path': directory})
    return checked


def main(action):
    if os.geteuid() != 0 or Path(__file__).resolve() != SELF:
        raise RuntimeError('installed root helper required')
    st = SELF.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise RuntimeError('unsafe installer ownership')
    fd = os.open('/run/lock/mcp-andrea-files-maintenance.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        if action == '--apply':
            if set(PAYLOAD) != set(ORIGINAL):
                raise RuntimeError('invalid embedded payload')
            for name, expected in ORIGINAL.items():
                path = BASE / name
                if path.is_symlink() or (sha(path.read_bytes()) if path.exists() else None) != expected:
                    raise RuntimeError('live source changed: ' + name)
                candidate = base64.b64decode(PAYLOAD[name]['data'], validate=True)
                if sha(candidate) != PAYLOAD[name]['sha256']:
                    raise RuntimeError('payload hash mismatch')
                compile(candidate, name, 'exec')
            BACKUP.mkdir(mode=0o700, exist_ok=False)
            manifest = {}
            for name in ORIGINAL:
                path = BASE / name
                if path.exists():
                    st = path.stat()
                    manifest[name] = {'mode': stat.S_IMODE(st.st_mode), 'uid': st.st_uid, 'gid': st.st_gid}
                    atomic(BACKUP / name, path.read_bytes(), 0o600)
                else:
                    manifest[name] = None
            atomic(BACKUP / 'manifest.json', json.dumps(manifest).encode(), 0o600)
            try:
                for name in ['file_tools.py', 'file_schema.py', 'agent.py', 'cg_tools.py']:
                    atomic(BASE / name, base64.b64decode(PAYLOAD[name]['data']))
                restart()
                checks = smoke()
                record('active', backup=str(BACKUP), checks=checks,
                       hashes={name: value['sha256'] for name, value in PAYLOAD.items()})
                print(json.dumps({'status': 'active', 'checks': checks, 'backup': str(BACKUP)}))
            except BaseException:
                try:
                    restore()
                    record('rolled_back', reason='installation or verification failed')
                except BaseException:
                    record('rollback_failed')
                raise
        elif action == '--rollback':
            for name, value in PAYLOAD.items():
                if sha((BASE / name).read_bytes()) != value['sha256']:
                    raise RuntimeError('rollback conflict')
            restore()
            record('rolled_back', reason='approved rollback')
            print('ROLLBACK_COMPLETED')
        else:
            raise ValueError('invalid action')
    finally:
        os.close(fd)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('exactly one action required')
    main(sys.argv[1])
