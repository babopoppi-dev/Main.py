#!/usr/bin/env python3
"""Root maintenance helper: enroll only mac_mio; preserve all other settings.

Run only through MCP Andrea admin_request after installing this reviewed helper
root-owned and verifying its SHA-256. Never accepts a token or arbitrary path.
"""
import fcntl
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import sys
import time

CONFIG=Path('/etc/central-mcp-gateway/gateway-test.json')
VERIFY=Path('/etc/central-mcp-gateway/mac_mio_v2.sha256')
BACKUP=Path('/opt/central-mcp-gateway/backups/mac_mio_v2_20261002')
RECEIPT=BACKUP/'receipt.json'
SERVICE='central-mcp-gateway-test.service'
SOURCE_ROOT=Path('/opt/central-mcp-gateway')
LOCK=Path('/run/lock/mcp-andrea-gateway-maintenance.lock')
DIGEST='660d1caa821bda5e92629b949b9624ada35f487d85a316d0148cd0a9dcb9b4fe'
EXPECTED={'agent.py':'10d72908db298e613a071a1f3bb759f95b1d31818c20aa066e8c1b213e56fd58',
          'cg_mcp.py':'a1a9a7c66c0f003f8de9bf98f421bd89726f13c5f3f24b0ae1b9a8b155419844',
          'cg_tools.py':'4f11a2e6786ff514dfcb9e28f6b7f88972660c349446b6c0ea4eb3f9925a7283',
          'cg_agents.py':'7e891890ccb076aa06404fdcd481668a3e4aa780e104acb7230448f79e5fe6a1',
          'gateway.py':'70b8f7ceba12665bbcc6791d841d2438357f5c683c99ff5b688d18b6afe6d0bd'}

def sha(data): return hashlib.sha256(data).hexdigest()

def no_links(p):
    if any(q.is_symlink() for q in [p]+list(p.parents)):
        raise RuntimeError('symlink rejected')

def atomic_config(data,mode,uid,gid):
    tmp=CONFIG.with_name('gateway-test.json.mac-mio-tmp')
    fd=os.open(str(tmp),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data);f.flush()
            os.fchown(f.fileno(),uid,gid)
            os.fchmod(f.fileno(),mode)
            os.fsync(f.fileno())
        os.replace(tmp,CONFIG)
        d=os.open(str(CONFIG.parent),os.O_RDONLY)
        try: os.fsync(d)
        finally: os.close(d)
    finally:
        if tmp.exists(): tmp.unlink()

def restart():
    subprocess.run(['/usr/bin/systemctl','restart',SERVICE],check=True,timeout=45)
    # Type=simple can report active before Python has read its configuration.
    # Confirm sustained service state, then readiness of the actual gateway.
    import urllib.request
    for _ in range(3):
        time.sleep(1)
        subprocess.run(['/usr/bin/systemctl','is-active','--quiet',SERVICE],check=True,timeout=5)
    with urllib.request.urlopen('https://mcp.andreababini.it/healthz',timeout=5) as response:
        data=json.load(response)
        if data.get('ok') is not True: raise RuntimeError('gateway readiness check failed')

def verify_reader():
    subprocess.run(['/usr/sbin/runuser','-u','mcp-gateway','--','/usr/bin/python3','-c',
                    'import json; json.load(open("/etc/central-mcp-gateway/gateway-test.json"))'],
                   check=True,timeout=10,capture_output=True)

def main():
    if os.geteuid()!=0 or sys.argv[1:] not in (['--apply'],['--rollback']):
        raise SystemExit('root and exactly --apply or --rollback required')
    os.umask(0o077)
    for p in [CONFIG,VERIFY,BACKUP,Path(__file__).resolve()]: no_links(p)
    own=Path(__file__).stat()
    if own.st_uid!=0 or own.st_mode & 0o022:
        raise SystemExit('helper must be root-owned and immutable by other users')
    lock=os.open(str(LOCK),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return locked_main()
    finally:
        os.close(lock)

def locked_main():
    meta=CONFIG.stat()
    if meta.st_uid!=0 or not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o022:
        raise RuntimeError('unexpected configuration ownership')
    raw=CONFIG.read_bytes()
    if sys.argv[1]=='--rollback':
        receipt=json.loads(RECEIPT.read_text())
        if sha(raw)!=receipt['installed_sha256']:
            raise RuntimeError('configuration changed after enrollment; rollback refused')
        original=(BACKUP/'gateway-test.json').read_bytes()
        if sha(original)!=receipt['original_sha256']: raise RuntimeError('backup digest mismatch')
        atomic_config(original,stat.S_IMODE(meta.st_mode),meta.st_uid,meta.st_gid)
        try: restart()
        except Exception:
            atomic_config(raw,stat.S_IMODE(meta.st_mode),meta.st_uid,meta.st_gid)
            restart();raise
        VERIFY.unlink()
        print(json.dumps({'rolled_back':True,'machine':'mac_mio','backup':str(BACKUP)}))
        return
    for name,digest in EXPECTED.items():
        if sha((SOURCE_ROOT/name).read_bytes())!=digest:
            raise RuntimeError('live source changed; review required: '+name)
    cfg=json.loads(raw)
    if not isinstance(cfg.get('agents'),dict) or 'vps' not in cfg['agents'] or 'mac_noleggio' not in cfg['agents']:
        raise RuntimeError('unexpected existing agent registry')
    if 'mac_mio' in cfg['agents'] or VERIFY.exists() or BACKUP.exists():
        raise RuntimeError('mac_mio enrollment or backup already exists; no overwrite')
    BACKUP.mkdir(mode=0o700)
    shutil.copy2(CONFIG,BACKUP/'gateway-test.json')
    os.chmod(BACKUP/'gateway-test.json',0o600)
    uid=pwd.getpwnam('mcp-gateway').pw_uid
    gid=grp.getgrnam('mcp-gateway').gr_gid
    fd=os.open(str(VERIFY),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
    with os.fdopen(fd,'w') as f:
        f.write(DIGEST);f.flush();os.fsync(f.fileno());os.fchown(f.fileno(),uid,gid)
    cfg['agents']['mac_mio']={'token_sha256_file':str(VERIFY),'monitor':True}
    new=(json.dumps(cfg,indent=2)+'\n').encode()
    try:
        if CONFIG.read_bytes()!=raw: raise RuntimeError('concurrent configuration change')
        atomic_config(new,stat.S_IMODE(meta.st_mode),meta.st_uid,meta.st_gid)
        verify_reader()
        restart()
    except Exception:
        if CONFIG.read_bytes()==new:
            atomic_config(raw,stat.S_IMODE(meta.st_mode),meta.st_uid,meta.st_gid)
            restart()
        VERIFY.unlink()
        raise
    receipt={'machine':'mac_mio','original_sha256':sha(raw),'installed_sha256':sha(new),
             'applied_at':time.time(),'backup':str(BACKUP),'gateway_active':True,
             'rollback_command':'python3 /opt/central-mcp-gateway/enroll_mac_mio_v2_20261002.py --rollback'}
    RECEIPT.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))

if __name__=='__main__': main()
