"""Build the hash-pinned Mac installer v0.14: F (allowlist network proxy for the shell; inactive without network.json).
Run as root through mac_admin_request; no local launcher, no Telegram pairing.

Reuses the reviewed v0.11 r1 installer machinery (template functions + body).
The agent part replaces mac_agent.py and adds two modules; the admin part pairs
a dedicated Telegram bot and installs a separate root helper LaunchDaemon.
"""
from pathlib import Path
import ast
import base64
import hashlib
import json
import shlex
import zlib

P=Path(__file__).resolve().parent
live=P.parent/'mac_v013'   # copies matching the 0.13-personal-projects-1 install
names=['mac_agent.py','agent_shell.py','mac_shell.py','mac_policy.py','mac_child.py','mac_netproxy.py']
dependencies=['file_tools.py','file_schema.py','search_tools.py','search_schema.py',
              'shell_common.py','mac_guard.py','mac_clock.py','mac_watchdog.py',
              'work_sessions.py','work_schema.py','admin_schema.py','mac_admin_client.py',
              'mac_projects.py','mac_processes.py','process_schema.py']
tests=names+dependencies+['test_work_core.py','test_search.py','test_mac_admin.py','test_projects_processes.py','test_netproxy.py','test_network_integration.py','network_schema.py','mac_admin_helper.py','mac_coordination_selftest.py','cg_tools.py']
before={n:live/n for n in names if (live/n).exists()}
original={n:hashlib.sha256(before[n].read_bytes()).hexdigest() if n in before else None for n in names}
deps={n:hashlib.sha256((live/n).read_bytes()).hexdigest() for n in dependencies}
for n in dependencies:assert (P/n).read_bytes()==(live/n).read_bytes(),n
carried=[n for n in tests if n not in dependencies]
sources={}
for n in carried:
    text=(P/n).read_text()
    assert text.isascii() and "'''" not in text and not text.endswith('\\'),n
    sources[n]=text
source_sha={n:hashlib.sha256((P/n).read_bytes()).hexdigest() for n in carried}
STAMP='v014_20261003'
header='''#!/usr/bin/env python3
"""Hash-pinned local update of the personal-Mac agent to v0.13 (run as root via mac_admin_request)."""
import base64,contextlib,fcntl,hashlib,json,os,plistlib,re,stat,subprocess,sys,tempfile,time,zlib
from pathlib import Path
ROOT=Path('/Library/MCPAndreaMacMioV09')
BASE=ROOT/'code'
SELF=ROOT/'upgrade_%(s)s.py'
BACKUP=ROOT/'backup/%(s)s'
RECEIPT=ROOT/'%(s)s_receipt.json'
TEST_CODE=ROOT/'preflight-%(s)s'
TEST_DATA=Path('/Users/Shared/MCPAndreaMacMio/preflight-%(s)s')
GUARD=ROOT/'state/operations/guard'
LABEL='it.andreababini.mcp-mac-mio-v09'
PLIST=Path('/Library/LaunchDaemons')/(LABEL+'.plist')
PLIST_SHA='c355532f913809d9a183e0e4b4a55e226dfc850914dbe4992582d5d3bf7fd406'
PYTHON='/usr/bin/python3'
OLD_VERSION='0.13-personal-projects-1'
NEW_VERSION='0.14-personal-network-1'
PAYLOAD={}
TESTS={}
'''%{'s':STAMP}
header+='ORIGINAL='+repr(original)+'\nDEPENDENCIES='+repr(deps)+'\nTEST_NAMES='+repr(tests)+'\nSOURCE_SHA='+repr(source_sha)+'\nSOURCES={\n'+''.join(repr(n)+": r'''"+t+"''',\n" for n,t in sources.items())+'}\n'
source=(P/'upgrade_vps_template.py').read_text()
reuse={'sha','trusted_directory','read','digest','atomic','record','run','backup','restore'}
functions='\n\n'.join(ast.get_source_segment(source,node) for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name in reuse)
marker='    for name,meta in manifest.items():'
assert functions.count(marker)==1
functions=functions.replace('def restore(strict=True):','def verify_restore(strict=True):').replace(marker,
    '    return manifest\n\n\ndef restore(strict=True):\n    manifest=verify_restore(strict)\n'+marker)
body=(P/'mac_updater_body_r2.py').read_text()
def swap(old,new):
    global body
    assert body.count(old)==1,old
    body=body.replace(old,new)
# Fresh backup only: the r2 interrupted-run recovery does not apply here.
start=body.index('def prepare_backup():');end=body.index('def start_daemon(')
body=body[:start]+'''def prepare_backup():
    if BACKUP.exists() or BACKUP.is_symlink():raise RuntimeError('backup exists; inspect before retry')
    return backup()


'''+body[end:]
start=body.index('def load_package():');end=body.index('def child(')
body=body[:start]+"""def load_package():
    global PAYLOAD,TESTS
    carried={n:src.encode() for n,src in SOURCES.items()}
    if {n:sha(b) for n,b in carried.items()}!=SOURCE_SHA:raise RuntimeError('unexpected embedded sources')
    PAYLOAD={n:carried[n] for n in ORIGINAL}
    # Unchanged dependencies come from the live, hash-pinned installation.
    TESTS={n:carried[n] if n in carried else read(BASE/n) for n in TEST_NAMES}
    for n,h in DEPENDENCIES.items():
        if sha(TESTS[n])!=h:raise RuntimeError('live dependency changed: '+n)
    for name,data in {**PAYLOAD,**TESTS}.items():compile(data,name,'exec')


"""+body[end:]
swap("['test_search','test_mac_agent']","['test_work_core','test_search','test_mac_admin','test_projects_processes','test_netproxy','test_network_integration']")
old_nop=body[body.index('def no_other_processes('):body.index('def service_state(')]
body=body.replace(old_nop,"""def no_other_processes(daemon_pid=None):
    text=run(['/bin/ps','-axo','uid=,pid=,ppid=,stat=,args=']).stdout
    pids=set()
    for row in text.splitlines():
        p=row.split(None,4)
        if len(p)<4 or p[0]!='5000' or p[3].startswith('Z'):continue
        # Per-user macOS agents started on demand by launchd (kernel-verified image).
        if known_system(p):continue
        pids.add(int(p[1]))
    if pids!=(set() if daemon_pid is None else {daemon_pid}):raise RuntimeError('dedicated account busy')


""")
swap("TEST_CODE/'mac_search_selftest.py'","TEST_CODE/'mac_coordination_selftest.py'")
swap("'search smoke failed: '","'coordination smoke failed: '")
swap("    if action=='--check':print(json.dumps(check_sources(),indent=2));return","    if action=='--check':\n        result=check_sources()\n        if SELF.exists():result['installer_sha256']=sha(read(SELF))\n        print(json.dumps(result,indent=2));return")
swap("    if os.getuid()!=0 or os.geteuid()!=0:raise RuntimeError('local administrator approval required')","    if os.getuid()!=0 or os.geteuid()!=0:raise RuntimeError('root required (mac_admin_request)')")
assert body.count('\n\nif __name__==')==1
body=body.replace('\n\nif __name__==',chr(10)+(P/'mac_v014_install_body.py').read_text()+'\n\nif __name__==',1)
target=P/('upgrade_mac_'+STAMP+'.py')
target.write_text(header+'\n\n'+functions+'\n\n'+body)
compile(target.read_bytes(),str(target),'exec')
digest=hashlib.sha256(target.read_bytes()).hexdigest()
import re,sys
commit=sys.argv[1] if len(sys.argv)>1 else 'COMMIT'
remote='/Library/MCPAndreaMacMioV09/upgrade_'+STAMP+'.py'
url='https://raw.githubusercontent.com/babopoppi-dev/Main.py/'+commit+'/mac_v014/'+target.name
cmds={'MAC_ADMIN_1_download.txt':'/usr/bin/curl -fsS --proto =https --max-time 60 -o '+remote+' '+url,
      'MAC_ADMIN_2_check.txt':'/usr/bin/python3 -I -B '+remote+' --check',
      'MAC_ADMIN_3_apply.txt':'/usr/bin/python3 -I -B '+remote+' --apply',
      'MAC_ADMIN_rollback.txt':'/usr/bin/python3 -I -B '+remote+' --rollback'}
for name,cmd in cmds.items():
    assert re.fullmatch(r"[A-Za-z0-9_./:=@%+, -]+",cmd) and len(cmd)<=3000,cmd
    (P/name).write_text(cmd+'\n')
print(json.dumps({'file':str(target.name),'sha256':digest,'remote':remote,'original':original},indent=2))
