"""Build the hash-pinned VPS agent v0.12 (coordination) installer and its admin_request commands."""
from pathlib import Path
import base64
import hashlib
import json
import re
import sys
import zlib

BASE=Path(__file__).resolve().parent
names=['agent.py','work_sessions.py']
tests=names+['work_schema.py','cg_tools.py','admin_schema.py','search_tools.py','search_schema.py','file_tools.py',
             'file_schema.py','isolated_shell.py','test_search.py','test_vps_agent.py']
for n in ('work_sessions.py','work_schema.py'):
    assert (BASE/n).read_bytes()==(BASE.parent/'coordination_v011r1'/n).read_bytes(),n
package={key:{n:base64.b64encode((BASE/n).read_bytes()).decode() for n in files}
         for key,files in [('payload',names),('tests',tests)]}
data=base64.b64encode(zlib.compress(json.dumps(package).encode(),9)).decode()
template=(BASE/'upgrade_vps_template.py').read_text()
assert template.count('__PACKAGE__')==1
target=BASE/'upgrade_vps_v012_20261003.py'
target.write_text(template.replace('__PACKAGE__',data))
compile(target.read_bytes(),str(target),'exec')
digest=hashlib.sha256(target.read_bytes()).hexdigest()
commit=sys.argv[1] if len(sys.argv)>1 else 'COMMIT'
remote='/opt/central-mcp-gateway/'+target.name
url='https://raw.githubusercontent.com/babopoppi-dev/Main.py/'+commit+'/vps_v012/'+target.name
cmds={'ADMIN_REQUEST_1_download_vps.txt':'/usr/bin/curl -fsS --proto =https --max-time 60 -o '+remote+' '+url,
      'ADMIN_REQUEST_2_check_vps.txt':'/usr/bin/python3 -I -B '+remote+' --check',
      'ADMIN_REQUEST_3_apply_vps.txt':'/usr/bin/python3 -I -B '+remote+' --apply',
      'ADMIN_REQUEST_rollback_vps.txt':'/usr/bin/python3 -I -B '+remote+' --rollback'}
for name,cmd in cmds.items():
    assert re.fullmatch(r"[A-Za-z0-9_./:=@%+, -]+",cmd) and len(cmd)<=3000,cmd
    (BASE/name).write_text(cmd+'\n')
print(json.dumps({'file':target.name,'sha256':digest,'payload':{n:hashlib.sha256((BASE/n).read_bytes()).hexdigest() for n in names}},indent=2))
