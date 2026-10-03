"""Activate/rollback only the user LaunchAgent; preserve the old release."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time

BASE=Path('/Users/vagrant/.mac-control-gateway/central-adapter')
REL=BASE/'releases/workspace_20261002_v1_1'
BAK=BASE/'backups/pre_workspace_20261002_v1_1'
PLIST=Path('/Users/vagrant/Library/LaunchAgents/it.andreababini.central-mcp-mac-noleggio-test.plist')
LABEL='gui/501/it.andreababini.central-mcp-mac-noleggio-test'
SID='chatgpt:mcp-activate-20261002'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args,check=True):return subprocess.run(args,capture_output=True,text=True,check=check,timeout=30)
def bootstrap():
    # bootout may return while launchd is still removing the previous job.
    # Never treat this transition as proof that the replacement is running.
    for attempt in range(20):
        if run(['launchctl','print',LABEL],False).returncode==0:
            time.sleep(1);continue
        result=run(['launchctl','bootstrap','gui/501',str(PLIST)],False)
        if result.returncode==0:return
        if result.returncode!=5:
            raise RuntimeError('launchd bootstrap failed: '+result.stderr[:300])
        time.sleep(1)
    raise RuntimeError('launchd did not release the previous job within 20 seconds')
def atomic(p,data,mode):
    fd,name=tempfile.mkstemp(prefix='.activation-',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)
def restore():
    run(['launchctl','bootout',LABEL],False)
    atomic(BASE/'config.json',(BAK/'config.json').read_bytes(),0o600)
    atomic(PLIST,(BAK/PLIST.name).read_bytes(),0o644)
    bootstrap()

def main(rollback=False):
    if os.getuid()!=501 or sys.platform!='darwin':raise RuntimeError('unexpected host/user')
    fd=os.open(str(BASE/'maintenance.lock'),os.O_RDWR|os.O_NOFOLLOW)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    sys.path.insert(0,'/Users/vagrant/mac_control_mcp')
    import mac_control_coordination as coord
    lock=coord.acquire_lock(SID,str(BASE),120,'adapter-activation')
    try:
        prep=json.loads((REL/'prepared.json').read_text())
        for name,digest in prep['files'].items():
            if sha(REL/name)!=digest:raise RuntimeError('prepared source changed')
        if rollback:
            act=json.loads((REL/'activated.json').read_text())
            if sha(BASE/'config.json')!=act['config_sha256'] or sha(PLIST)!=act['plist_sha256']:
                raise RuntimeError('rollback conflict: active files changed')
            restore();print('ROLLBACK_RESTORED');return
        if sha(BASE/'config.json')!=prep['original_config_sha256'] or sha(PLIST)!=prep['original_plist_sha256']:
            raise RuntimeError('activation conflict: active files changed')
        cfg=json.loads((BASE/'config.json').read_text())
        for name,key in [('mac_control.py','source_sha256'),('mac_control_coordination.py','coordination_sha256')]:
            if sha(Path('/Users/vagrant/mac_control_mcp')/name)!=cfg[key]:raise RuntimeError('backend changed')
        cfg['mode']='workspace_files_and_status'
        plist=plistlib.loads(PLIST.read_bytes())
        plist['ProgramArguments'][2]=str(REL/'adapter.py')
        plist['WorkingDirectory']=str(REL)
        log=BASE/'logs/adapter.log';offset=log.stat().st_size if log.exists() else 0
        run(['launchctl','bootout',LABEL])
        try:
            atomic(BASE/'config.json',json.dumps(cfg,indent=2).encode()+b'\n',0o600)
            atomic(PLIST,plistlib.dumps(plist),0o644)
            bootstrap()
            ready=False
            for attempt in range(20):
                time.sleep(1)
                status=run(['launchctl','print',LABEL],False)
                with log.open('rb') as f:
                    f.seek(offset);tail=f.read()
                if status.returncode==0 and 'state = running' in status.stdout and b'connected workspace_files_and_status' in tail:
                    ready=True;break
            if not ready:raise RuntimeError('new agent did not connect within 20 seconds')
        except BaseException:
            restore();raise
        receipt={'config_sha256':sha(BASE/'config.json'),'plist_sha256':sha(PLIST),'activated_at':time.time(),
                 'connected':True,'rollback':'/usr/bin/python3 -B '+str(REL/'activate_release.py')+' --rollback'}
        atomic(REL/'activated.json',json.dumps(receipt,indent=2).encode(),0o600)
        print(json.dumps(receipt))
    finally:
        coord.release_lock(lock['lock_id'],SID);os.close(fd)

if __name__=='__main__':main(sys.argv[1:] == ['--rollback'])
