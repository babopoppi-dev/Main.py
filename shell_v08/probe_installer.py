#!/usr/bin/env python3
"""Root-owned, pinned temporary test only. Does not update the live agent."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

BASE = Path('/opt/central-mcp-gateway')
SELF = BASE / 'probe_shell_v08r3_20261002.py'
CODE = BASE / 'shell-probe-v08r3-20261002'
DATA = Path('/var/lib/central-mcp-vps-agent-test/tmp/collaudo_shell_v08r3_20261002')
RECEIPT = BASE / 'shell_probe_v08r3_receipt.json'
UNIT = 'mcp-andrea-shell-probe-v08r3-20261002'
PAYLOAD = {}  # Embedded and hashed by build_probe.py.


def main():
    if sys.argv[1:] != ['--probe'] or os.geteuid() != 0 or Path(__file__).resolve() != SELF:
        raise RuntimeError('installed root helper with --probe required')
    st = SELF.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid or st.st_mode & 0o022:
        raise RuntimeError('unsafe helper')
    lock = os.open('/run/lock/mcp-andrea-shell-probe.lock', os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    if CODE.exists() or CODE.is_symlink() or DATA.exists() or DATA.is_symlink():
        raise RuntimeError('test path already exists; inspect before retry')
    CODE.mkdir(mode=0o755)
    CODE.chmod(0o755)
    DATA.mkdir(mode=0o700)
    os.chown(DATA,997,987)
    for name in ('workspace','journal'):
        p = DATA/name; p.mkdir(mode=0o700); os.chown(p,997,987)
    for name, payload in PAYLOAD.items():
        assert name in {'file_tools.py','isolated_shell.py','probe_shell.py'}
        data = base64.b64decode(payload['base64'])
        assert hashlib.sha256(data).hexdigest() == payload['sha256']
        fd = os.open(CODE/name, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o444)
        with os.fdopen(fd,'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
            os.fchmod(out.fileno(),0o444)
    # The outer service bounds total resources, including forked descendants.
    argv = ['systemd-run','--unit='+UNIT,'--collect','--wait','--pipe',
            '--property=User=mcp-vps-agent','--property=Group=mcp-vps-agent',
            '--property=NoNewPrivileges=yes','--property=PrivateTmp=yes',
            '--property=PrivateDevices=yes','--property=ProtectHome=yes',
            '--property=ProtectSystem=strict','--property=RestrictSUIDSGID=yes',
            '--property=LockPersonality=yes','--property=ProtectKernelModules=yes',
            '--property=ProtectControlGroups=yes','--property=ProtectKernelTunables=no',
            '--property=ProtectKernelLogs=no',
            '--property=ReadWritePaths='+str(DATA), '--property=TasksMax=128',
            '--property=MemoryMax=512M','--property=CPUQuota=100%',
            '--property=RuntimeMaxSec=45','--property=KillMode=control-group',
            '/opt/central-mcp-gateway/.venv/bin/python','-B',str(CODE/'probe_shell.py')]
    result = None
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=55,
                                env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'})
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        receipt = {'status':'passed' if result.returncode==0 and 'SHELL_PROBE_OK' in result.stdout else 'failed',
                   'exit_code':result.returncode,'output':result.stdout[-10000:],
                   'diagnostic':result.stderr[-6000:],'time':time.time(),'live_agent_modified':False,
                   'code':str(CODE),'data':str(DATA),'payload_hashes':{k:v['sha256'] for k,v in PAYLOAD.items()}}
        RECEIPT.write_text(json.dumps(receipt,indent=2)); RECEIPT.chmod(0o644)
        if receipt['status'] != 'passed': raise RuntimeError('isolated shell probe failed; no live changes made')
    finally:
        # Even if the parent times out, no transient test service is left running.
        subprocess.run(['systemctl','stop',UNIT+'.service'],capture_output=True,timeout=10)
        os.close(lock)


if __name__=='__main__': main()
