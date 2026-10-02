"""Build the hash-pinned local Mac activation for coordination v0.11 r1.

Reuses the reviewed search v0.10 r2 installer (template functions + body);
only the payload, pinned hashes, preflight tests and smoke test change.
"""
from pathlib import Path
import ast
import base64
import hashlib
import json
import shlex
import zlib

P=Path(__file__).resolve().parent
live=P.parent/'coordination_v011'   # copies matching the live 0.10.1 install
names=['mac_agent.py','work_sessions.py','work_schema.py']
dependencies=['file_tools.py','file_schema.py','search_tools.py','search_schema.py','agent_shell.py',
              'shell_common.py','mac_guard.py','mac_clock.py','mac_policy.py','mac_child.py',
              'mac_watchdog.py','mac_shell.py']
tests=names+dependencies+['test_work_core.py','test_search.py','mac_coordination_selftest.py']
before={'mac_agent.py':live/'mac_agent_before.py'}
original={n:hashlib.sha256(before[n].read_bytes()).hexdigest() if n in before else None for n in names}
deps={n:hashlib.sha256((live/n).read_bytes()).hexdigest() for n in dependencies}
for n in dependencies:assert (P/n).read_bytes()==(live/n).read_bytes(),n
payload={n:base64.b64encode((P/n).read_bytes()).decode() for n in names}
testdata={n:base64.b64encode((P/n).read_bytes()).decode() for n in tests}
package=base64.b64encode(zlib.compress(json.dumps({'payload':payload,'tests':testdata}).encode(),9)).decode()
STAMP='coordination_v011r1_20261002'
header='''#!/usr/bin/env python3
"""Hash-pinned local update of only the central personal-Mac agent: coordination v0.11 r1."""
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
OLD_VERSION='0.10-personal-search-1'
NEW_VERSION='0.11-personal-work-2'
PAYLOAD={}
TESTS={}
'''%{'s':STAMP}
header+='ORIGINAL='+repr(original)+'\nDEPENDENCIES='+repr(deps)+'\nTEST_NAMES='+repr(tests)+'\nPACKAGE='+repr(package)+'\n'
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
swap("['test_search','test_mac_agent']","['test_work_core','test_search']")
swap("TEST_CODE/'mac_search_selftest.py'","TEST_CODE/'mac_coordination_selftest.py'")
swap("'search smoke failed: '","'coordination smoke failed: '")
target=P/('upgrade_mac_'+STAMP+'.py')
target.write_text(header+'\n\n'+functions+'\n\n'+body)
compile(target.read_bytes(),str(target),'exec')
digest=hashlib.sha256(target.read_bytes()).hexdigest()
remote='/Users/babo/MCPAndreaCoordV011_20261002/'+target.name
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
print 'MCP Andrea: attiva soltanto il coordinamento v0.11 sul Mac personale.'
print 'Crea un backup, collauda come utente non amministratore e riavvia il solo agent MCP.'
print 'In caso di errore ripristina automaticamente la versione 0.10.1.'
print 'Quando richiesta, inserisci la password di accesso del tuo Mac personale.'
'''+invocation+''' --check
if [[ $? == 0 ]]; then
  /usr/bin/sudo '''+invocation+''' --apply
  if [[ $? == 0 ]]; then
    print 'ATTIVAZIONE_COORDINAMENTO_MCP_COMPLETATA. Torna nella chat e scrivi Fatto.'
  else
    print 'Attivazione non completata. Lascia questa finestra aperta e torna nella chat.'
  fi
else
  print 'Controllo preliminare non superato. Torna nella chat.'
fi
read -r '?Premi Invio per chiudere questa finestra...'
'''
(P/'Attiva_Coordinamento_MCP_Andrea.command').write_text(launcher)
print(json.dumps({'file':str(target.name),'sha256':digest,'remote':remote,'original':original},indent=2))
