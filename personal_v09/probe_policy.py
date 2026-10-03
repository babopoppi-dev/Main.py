"""Harmless policy probe as the existing user; no lease or UID cleanup runs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from mac_policy import profile


def main():
    if sys.platform!='darwin' or os.getuid()!=501:
        raise SystemExit('read-only policy test expects the existing Mac user')
    root=Path(tempfile.mkdtemp(prefix='policy-probe-',dir=str(Path(__file__).resolve().parent)))
    work=root/'policy-workspace';work.mkdir(mode=0o700,exist_ok=False)
    sentinel=root/'denied-sentinel.txt';sentinel.write_text('MCP_TEST_SENTINEL_ONLY')
    code=r'''
import os, pathlib, socket, json, subprocess
work=pathlib.Path(os.environ['HOME'])
outside=work.parent/'denied-sentinel.txt'
results={}
(work/'ok.txt').write_text('ok')
results['workspace_read_write']=(work/'ok.txt').read_text()=='ok'
for key,fn in [
 ('outside_read',lambda:outside.read_text()),
 ('outside_write',lambda:outside.write_text('MUST_NOT_WRITE')),
 ('outside_hardlink',lambda:os.link(str(outside),str(work/'link'))),
 ('signal_parent',lambda:os.kill(int(os.environ['PROBE_PARENT_PID']),0)),
 ('privileged_executable',lambda:subprocess.run(['/usr/bin/sudo','-V'],check=True,capture_output=True)),
 ('network',lambda:socket.socket().bind(('127.0.0.1',0)))
]:
 try:fn();results[key]='UNEXPECTED_ALLOWED'
 except (PermissionError,OSError):results[key]='denied'
r=subprocess.run(['/usr/bin/sw_vers'],capture_output=True,text=True)
results['sw_vers_exit']=r.returncode
print(json.dumps(results),flush=True)
assert results['workspace_read_write'] and results['sw_vers_exit']==0
assert all(results[k]=='denied' for k in ['outside_read','outside_write','outside_hardlink','signal_parent','network','privileged_executable'])
'''
    env={'HOME':str(work),'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8',
         'PROBE_PARENT_PID':str(os.getpid()),'PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(work)}
    p=subprocess.run(['/usr/bin/sandbox-exec','-p',profile(str(work)),
                      os.path.realpath(sys.executable),'-I','-B','-c',code],env=env,
                     capture_output=True,text=True,timeout=15,cwd=str(work))
    print(p.stdout);print(p.stderr)
    assert sentinel.read_text()=='MCP_TEST_SENTINEL_ONLY'
    raise SystemExit(p.returncode)


if __name__=='__main__':main()
