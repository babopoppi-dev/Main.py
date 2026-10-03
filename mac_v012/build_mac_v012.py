"""Build the hash-pinned local Mac installer v0.12: points B (audit, installer) and C (admin via Telegram).

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
live=P.parent/'coordination_v011r1'   # copies matching the live 0.11-personal-work-2 install
names=['mac_agent.py','admin_schema.py','mac_admin_client.py']
dependencies=['file_tools.py','file_schema.py','search_tools.py','search_schema.py','agent_shell.py',
              'shell_common.py','mac_guard.py','mac_clock.py','mac_policy.py','mac_child.py',
              'mac_watchdog.py','mac_shell.py','work_sessions.py','work_schema.py']
tests=names+dependencies+['test_work_core.py','test_search.py','test_mac_admin.py','mac_admin_helper.py','mac_coordination_selftest.py','cg_tools.py']
before={'mac_agent.py':live/'mac_agent.py'}
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
STAMP='v012_20261003'
header='''#!/usr/bin/env python3
"""Hash-pinned local update of the personal-Mac agent to v0.12 and the Telegram admin helper."""
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
OLD_VERSION='0.11-personal-work-2'
NEW_VERSION='0.12-personal-admin-1'
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
swap("['test_search','test_mac_agent']","['test_work_core','test_search','test_mac_admin']")
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
swap("            check_sources()\n            stopped=False;installed=False","            admin_conf=telegram_setup()\n            check_sources()\n            stopped=False;installed=False")
swap("                raise\n        elif action=='--rollback':\n            with workspace_guard():","                raise\n            admin_phase(admin_conf)\n        elif action=='--rollback':\n            admin_remove()\n            with workspace_guard():")
swap("                record('active',version=NEW_VERSION,","                record('agent_active',version=NEW_VERSION,")
assert body.count('\n\nif __name__==')==1
body=body.replace('\n\nif __name__==',chr(10)+(P/'mac_admin_install_body.py').read_text()+'\n\nif __name__==',1)
target=P/('upgrade_mac_'+STAMP+'.py')
target.write_text(header+'\n\n'+functions+'\n\n'+body)
compile(target.read_bytes(),str(target),'exec')
digest=hashlib.sha256(target.read_bytes()).hexdigest()
remote='/Users/babo/MCPAndreaRepo/mac_v012/'+target.name
loader='import os,stat,hashlib,sys\npath='+repr(remote)+'\nexpected='+repr(digest)+'''\nfd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
with os.fdopen(fd,'rb') as f:
 st=os.fstat(f.fileno())
 if not stat.S_ISREG(st.st_mode) or st.st_uid!=501 or st.st_nlink!=1 or st.st_mode&0o022:raise SystemExit('File installer non sicuro')
 raw=f.read(2097153)
if hashlib.sha256(raw).hexdigest()!=expected:raise SystemExit('Hash installer diverso: operazione fermata')
if len(sys.argv)!=2 or sys.argv[1] not in ('--check','--apply'):raise SystemExit('Azione non valida')
action=sys.argv[1]
sys.argv=[path,action]
context={'__name__':'__main__','__file__':path}
if action=='--apply':context['APPROVED_SOURCE']=raw
exec(compile(raw,path,'exec'),context)
'''
compile(loader,'launcher loader','exec')
invocation='/usr/bin/python3 -I -B -c '+shlex.quote(loader)
launcher='''#!/bin/zsh
print 'MCP Andrea v0.12 sul Mac personale: agent 0.12 e amministrazione via Telegram.'
print 'Crea un backup, collauda come utente non amministratore, abbina un bot Telegram nuovo'
print 'e riavvia il solo agent MCP. In caso di errore ripristina la versione 0.11.'
print 'Hash atteso installer: ''+digest+'
/usr/bin/shasum -a 256 ''+remote+''
print 'Quando richiesta, inserisci la password di accesso del tuo Mac personale.'
'''+invocation+''' --check
if [[ $? == 0 ]]; then
  /usr/bin/sudo '''+invocation+''' --apply
  if [[ $? == 0 ]]; then
    print 'ATTIVAZIONE_MCP_V012_COMPLETATA. Torna nella chat e scrivi Fatto.'
  else
    print 'Attivazione non completata. Lascia questa finestra aperta e torna nella chat.'
  fi
else
  print 'Controllo preliminare non superato. Torna nella chat.'
fi
read -r '?Premi Invio per chiudere questa finestra...'
'''
(P/'Attiva_MCP_Andrea_v012.command').write_text(launcher)
(P/'Attiva_MCP_Andrea_v012.command').chmod(0o755)
print(json.dumps({'file':str(target.name),'sha256':digest,'remote':remote,'original':original},indent=2))
