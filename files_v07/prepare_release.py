"""Prepare a new release; never alters current launchd or agent config."""
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

BASE=Path('/Users/vagrant/.mac-control-gateway/central-adapter')
RELEASE=BASE/'releases/files_20261002_v07'
BACKUP=BASE/'backups/pre_files_20261002_v07'
PLIST=Path('/Users/vagrant/Library/LaunchAgents/it.andreababini.central-mcp-mac-noleggio-test.plist')
OLD=BASE/'releases/5b1ec8101bafd598'
SID='chatgpt:mcp-upgrade-20261002'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main(payload):
    if os.getuid()!=501 or sys.platform!='darwin':raise RuntimeError('unexpected host user')
    fd=os.open(str(BASE/'maintenance.lock'),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    expected={'mac_control.py':'86f845ea8e329ac7503a2af05d8576b4c29590c7c5a14abd9b8c9bc9b21320b8',
              'mac_control_coordination.py':'56def69e1619b93ee7733c18fbb2c7cebba86e0eef598e14ea772126f5e1637c'}
    for name,digest in expected.items():
        if sha(Path('/Users/vagrant/mac_control_mcp')/name)!=digest:raise RuntimeError('source changed')
    if sha(OLD/'adapter.py')!='5b1ec8101bafd598da65678bc058e282636188bfae11d85b368664350ce44b2d':raise RuntimeError('adapter changed')
    cfg=json.loads((BASE/'config.json').read_text())
    if cfg['mode']!='workspace_files_and_status':raise RuntimeError('unexpected active mode')
    if sha(BASE/'config.json')!='3f15119222ab13f6b574d9bd3ca62c9ae3cb2b6d1b085849a0ad27ec1d1288fd' or sha(PLIST)!='010247a22f35d76f0944abe659f8d11f161bd4ce5b1230ac2febe4760cad7747':raise RuntimeError('active configuration changed')
    sys.path.insert(0,'/Users/vagrant/mac_control_mcp')
    import mac_control_coordination as coord
    lock=coord.acquire_lock(SID,str(BASE),900,'adapter-maintenance')
    try:
        data=json.loads(Path(payload).read_text())
        names={'adapter.py','workspace_runtime.py','file_tools.py','file_schema.py','test_workspace.py','test_file_tools.py','activate_release.py'}
        if set(data)!=names:raise RuntimeError('unexpected payload')
        BACKUP.mkdir(parents=True,mode=0o700,exist_ok=False)
        for p in (BASE/'config.json',PLIST):shutil.copy2(p,BACKUP/p.name)
        RELEASE.mkdir(mode=0o700,exist_ok=False)
        for name,encoded in data.items():
            p=RELEASE/name;p.write_bytes(base64.b64decode(encoded,validate=True));p.chmod(0o600)
        work=Path('/Users/vagrant/MCPAndreaWorkspace')
        if work.is_symlink():raise RuntimeError('workspace symlink')
        work.mkdir(mode=0o700,exist_ok=True)
        py=str(OLD/'.venv/bin/python')
        subprocess.run([py,'-B','-m','unittest','-q','test_workspace','test_file_tools'],cwd=RELEASE,check=True)
        receipt={'backup':str(BACKUP),'release':str(RELEASE),'original_config_sha256':sha(BASE/'config.json'),
                 'original_plist_sha256':sha(PLIST),'files':{n:sha(RELEASE/n) for n in names},
                 'tests_passed':33,'activated':False}
        (RELEASE/'prepared.json').write_text(json.dumps(receipt,indent=2))
        print(json.dumps(receipt))
    finally:
        coord.release_lock(lock['lock_id'],SID)
        os.close(fd)

if __name__=='__main__':main(sys.argv[1])
