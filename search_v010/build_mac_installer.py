from pathlib import Path
import ast
import base64
import hashlib
import json
import shlex
import zlib

P=Path(__file__).resolve().parent
old=P.parent/'mcp-personal-v09-20261002'
names=['mac_agent.py','file_schema.py','search_tools.py','search_schema.py']
dependencies=['file_tools.py','agent_shell.py','shell_common.py','mac_guard.py','mac_clock.py','mac_policy.py','mac_child.py','mac_watchdog.py','mac_shell.py']
tests=names+dependencies+['cg_tools.py','test_search.py','test_mac_agent.py','mac_search_selftest.py']
payload={n:base64.b64encode((P/n).read_bytes()).decode() for n in names}
testdata={n:base64.b64encode((P/n).read_bytes()).decode() for n in tests}
package=base64.b64encode(zlib.compress(json.dumps({'payload':payload,'tests':testdata}).encode(),9)).decode()
original={n:hashlib.sha256((old/n).read_bytes()).hexdigest() if (old/n).exists() else None for n in names}
deps={n:hashlib.sha256((old/n).read_bytes()).hexdigest() for n in dependencies}
header='''#!/usr/bin/env python3
"""Hash-pinned local update of only the central personal-Mac agent."""
import base64,contextlib,fcntl,hashlib,json,os,plistlib,re,stat,subprocess,sys,tempfile,time,zlib
from pathlib import Path
ROOT=Path('/Library/MCPAndreaMacMioV09')
BASE=ROOT/'code'
SELF=ROOT/'upgrade_search_v010_20261002.py'
BACKUP=ROOT/'backup/search_v010_20261002'
RECEIPT=ROOT/'search_v010_receipt.json'
TEST_CODE=ROOT/'search-preflight-v010-20261002'
TEST_DATA=Path('/Users/Shared/MCPAndreaMacMio/search-preflight-v010-20261002')
GUARD=ROOT/'state/operations/guard'
LABEL='it.andreababini.mcp-mac-mio-v09'
PLIST=Path('/Library/LaunchDaemons')/(LABEL+'.plist')
PLIST_SHA='c355532f913809d9a183e0e4b4a55e226dfc850914dbe4992582d5d3bf7fd406'
PYTHON='/usr/bin/python3'
OLD_VERSION='0.9-personal-1'
NEW_VERSION='0.10-personal-search-1'
PAYLOAD={}
TESTS={}
'''
header+='ORIGINAL='+repr(original)+'\nDEPENDENCIES='+repr(deps)+'\nTEST_NAMES='+repr(tests)+'\nPACKAGE='+repr(package)+'\n'
source=(P/'upgrade_vps_template.py').read_text()
reuse={'sha','trusted_directory','read','digest','atomic','record','run','backup','restore'}
functions='\n\n'.join(ast.get_source_segment(source,node) for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name in reuse)
# Reuse the same validation for pre-stop checks and the actual restore.
marker='    for name,meta in manifest.items():'
assert functions.count(marker)==1
functions=functions.replace('def restore(strict=True):','def verify_restore(strict=True):').replace(marker,
    '    return manifest\n\n\ndef restore(strict=True):\n    manifest=verify_restore(strict)\n'+marker)
target=P/'upgrade_mac_search_v010_20261002.py'
target.write_text(header+'\n\n'+functions+'\n\n'+(P/'mac_updater_body.py').read_text())
compile(target.read_bytes(),str(target),'exec')
print(json.dumps({'file':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'original':original},indent=2))

remote='/Users/babo/MCPAndreaSearchV010_20261002/'+target.name
loader='import os,stat,hashlib,sys\npath='+repr(remote)+'\nexpected='+repr(hashlib.sha256(target.read_bytes()).hexdigest())+'''\nfd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
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
print 'MCP Andrea: aggiorna soltanto la ricerca sul Mac personale.'
print 'Crea un backup, collauda come utente non amministratore e riavvia il solo agent MCP.'
print 'Quando richiesta, inserisci la password di accesso del tuo Mac personale.'
'''+invocation+''' --check
if [[ $? == 0 ]]; then
  /usr/bin/sudo '''+invocation+''' --apply
  if [[ $? == 0 ]]; then
    print 'AGGIORNAMENTO_RICERCA_MCP_COMPLETATO. Torna nella chat e scrivi Fatto.'
  else
    print 'Aggiornamento non completato. Lascia questa finestra aperta e torna nella chat.'
  fi
else
  print 'Controllo preliminare non superato. Torna nella chat.'
fi
read -r '?Premi Invio per chiudere questa finestra...'
'''
(P/'Aggiorna_Ricerca_MCP_Andrea.command').write_text(launcher)
