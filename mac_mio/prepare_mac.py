#!/usr/bin/env python3
"""Prepare a new non-root mac_mio agent without touching older connectors."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import shutil
import subprocess
import sys

BASE=Path('/Users/babo/Library/Application Support/MCPAndrea')
WORK=Path('/Users/babo/MCPAndreaWorkspace')
PLIST=Path('/Users/babo/Library/LaunchAgents/it.andreababini.mcp-mac-mio.plist')
SOURCE=Path(__file__).resolve().parent

def main():
    if sys.platform != 'darwin' or os.getuid() != 501:
        raise SystemExit('expected Mac user uid 501')
    os.umask(0o077)
    for path in (BASE,WORK,PLIST):
        if path.exists() or path.is_symlink():
            raise SystemExit('target already exists; review and backup required: '+str(path))
        if any(p.is_symlink() for p in path.parents):
            raise SystemExit('symlink parent rejected')
    BASE.mkdir(mode=0o700)
    lock=os.open(str(BASE/'maintenance.lock'),os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    wheel=SOURCE/'wheelhouse/websockets-13.1-py3-none-any.whl'
    if hashlib.sha256(wheel.read_bytes()).hexdigest()!='a9a396a6ad26130cdae92ae10c36af09d9bfe6cafe69670fd3b6da9b07b4044f':
        raise SystemExit('wheel hash mismatch')
    subprocess.run([sys.executable,'-m','venv',str(BASE/'venv')],check=True)
    py=str(BASE/'venv/bin/python3')
    subprocess.run([py,'-m','pip','install','--no-index','--disable-pip-version-check',
                    '--require-hashes','--find-links',str(SOURCE/'wheelhouse'),'-r',str(SOURCE/'requirements.lock')],check=True)
    for name in ['mac_mio_agent.py','file_tools.py','file_schema.py','test_mac_mio.py','test_file_tools.py']:
        shutil.copyfile(SOURCE/name,BASE/name)
        (BASE/name).chmod(0o600)
    subprocess.run([py,'-B','-m','unittest','-q','test_mac_mio','test_file_tools'],cwd=str(BASE),check=True)
    WORK.mkdir(mode=0o700)
    token=secrets.token_urlsafe(32)
    fd=os.open(str(BASE/'agent.token'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:
        f.write(token);f.flush();os.fsync(f.fileno())
    digest=hashlib.sha256(token.encode()).hexdigest()
    (BASE/'agent.sha256').write_text(digest)
    lines=['(version 1)','(allow default)','(deny process-exec)','(deny file-write*)']
    allowed=[os.path.realpath(py),py,'/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python','/usr/bin/sw_vers']
    for p in allowed: lines.append('(allow process-exec (literal '+json.dumps(p)+'))')
    for p in [str(WORK),str(BASE/'operations')]: lines.append('(allow file-write* (subpath '+json.dumps(p)+'))')
    for p in ['/dev/null',str(BASE/'agent.lock')]+[str(BASE/('agent.log'+s)) for s in ['', '.1','.2','.3']]:
        lines.append('(allow file-write* (literal '+json.dumps(p)+'))')
    profile=BASE/'agent.sb'
    profile.write_text('\n'.join(lines)+'\n');profile.chmod(0o600)
    subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),py,'-B','-c',
                    'import subprocess; subprocess.run(["/usr/bin/sw_vers"],check=True)'],check=True)
    config={'Label':'it.andreababini.mcp-mac-mio','ProgramArguments':['/usr/bin/sandbox-exec','-f',str(profile),py,'-B',str(BASE/'mac_mio_agent.py')],
            'WorkingDirectory':str(BASE),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,
            'EnvironmentVariables':{'PATH':'/usr/bin:/bin','PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'},
            'StandardOutPath':str(BASE/'launchd.log'),'StandardErrorPath':str(BASE/'launchd-error.log')}
    with PLIST.open('xb') as f: plistlib.dump(config,f)
    PLIST.chmod(0o600)
    (BASE/'PREPARED.json').write_text(json.dumps({'prepared':True,'active':False,'machine':'mac_mio',
         'uid':os.getuid(),'full_shell_capable':False,'workspace':str(WORK),'token_sha256':digest},indent=2)+'\n')
    print(json.dumps({'prepared':True,'active':False,'machine':'mac_mio','token_sha256':digest,
                      'tests':29,'launchagent':str(PLIST),'workspace':str(WORK)}))
    os.close(lock)

if __name__=='__main__': main()
