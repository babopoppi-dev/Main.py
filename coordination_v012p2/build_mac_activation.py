"""Build the hash-pinned local Mac update v0.12 p2 (0.12-personal-1 -> 0.12-personal-2).

The live state is the v0.12 r1 installation (installer 2ceaaf84, commit a1d98356):
its embedded SOURCES are exactly the modules installed on the Mac. The installer
logic of r1 (executed successfully on 2026-10-03) is reused verbatim except for
the header and the system-agent tolerance introduced by r2 (commit 7222ffe).
p2 = r2 (processes, network profiles, session ids in the log) + journal fix.
"""
from pathlib import Path
import hashlib
import json
import shlex

P = Path(__file__).resolve().parent
PREVIOUS = P / 'live_r1' / 'upgrade_mac_v012_20261003.py'
assert hashlib.sha256(PREVIOUS.read_bytes()).hexdigest() == \
    '2ceaaf845f09107d2b09ea47905ed70f204f72263bd462e1f484df8989cc8147'
STAMP = 'v012p2_20261003'
FOLDER = '/Users/babo/MCPAndreaV012p2'
OLD_VERSION, NEW_VERSION = '0.12-personal-1', '0.12-personal-2'

previous = PREVIOUS.read_text()
live = {}
exec(previous[:previous.index('def sha(data):')], live)
installed = {n: live['SOURCES'][n].encode() for n in live['ORIGINAL']}
assert {n: hashlib.sha256(b).hexdigest() for n, b in installed.items()} == \
    {n: live['SOURCE_SHA'][n] for n in live['ORIGINAL']}
live_hash = {**{n: hashlib.sha256(b).hexdigest() for n, b in installed.items()}, **live['DEPENDENCIES']}
assert live['NEW_VERSION'] == OLD_VERSION

modules = sorted(live_hash)
changed = [n for n in modules if hashlib.sha256((P / n).read_bytes()).hexdigest() != live_hash[n]]
dependencies = [n for n in modules if n not in changed]
assert changed == ['file_tools.py', 'mac_agent.py', 'mac_child.py', 'mac_shell.py', 'net_proxy.py'], changed
original = {n: live_hash[n] for n in changed}
deps = {n: live_hash[n] for n in dependencies}
tests = changed + dependencies + ['test_work_core.py', 'test_search.py', 'test_v012.py', 'test_files_v012.py',
                                  'mac_v012_selftest.py', 'cg_tools.py']
carried = [n for n in tests if n not in dependencies]
sources = {}
for n in carried:
    text = (P / n).read_text()
    assert text.isascii() and "'''" not in text and not text.endswith('\\'), n
    sources[n] = text
source_sha = {n: hashlib.sha256((P / n).read_bytes()).hexdigest() for n in carried}

logic = previous[previous.index('def sha(data):'):]


def swap(old, new_text):
    global logic
    assert logic.count(old) == 1, old
    logic = logic.replace(old, new_text)


# Tolerate only per-user macOS agents that launchd starts on demand for any
# account (exact SIP-protected path and arguments, parent launchd). From r2.
swap("""        # macOS starts this per-user notification agent on demand from launchd.
        if p[2]=='1' and len(p)==5 and p[4].strip()=='/usr/sbin/distnoted agent':continue""",
     """        # macOS starts these per-user agents on demand from launchd (exact path and arguments).
        if p[2]=='1' and len(p)==5 and p[4].strip() in SYSTEM_AGENTS:continue""")
swap("'v0.12 smoke failed: '", "'v0.12 p2 smoke failed: '")

header = '''#!/usr/bin/env python3
"""Hash-pinned local update of only the central personal-Mac agent: MCP Andrea v0.12 p2."""
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
PLIST_SHA=%(plist)r
PYTHON='/usr/bin/python3'
OLD_VERSION=%(old)r
NEW_VERSION=%(new)r
PAYLOAD={}
TESTS={}
SMOKE_INFO={}
SYSTEM_AGENTS=frozenset({'/usr/sbin/distnoted agent','/usr/sbin/cfprefsd agent','/usr/libexec/trustd --agent',
    '/usr/libexec/secinitd','/usr/libexec/lsd','/usr/libexec/containermanagerd'})
''' % {'s': STAMP, 'plist': live['PLIST_SHA'], 'old': OLD_VERSION, 'new': NEW_VERSION}
header += ('ORIGINAL=' + repr(original) + '\nDEPENDENCIES=' + repr(deps) + '\nTEST_NAMES=' + repr(tests)
           + '\nSOURCE_SHA=' + repr(source_sha) + '\nSOURCES={\n'
           + ''.join(repr(n) + ": r'''" + t + "''',\n" for n, t in sources.items()) + '}\n\n\n')

target = P / ('upgrade_mac_' + STAMP + '.py')
target.write_text(header + logic)
compile(target.read_bytes(), str(target), 'exec')
digest = hashlib.sha256(target.read_bytes()).hexdigest()
remote = FOLDER + '/' + target.name
loader = 'import os,stat,hashlib,sys\npath=' + repr(remote) + '\nexpected=' + repr(digest) + '''\nfd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
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
compile(loader, 'launcher loader', 'exec')
invocation = '/usr/bin/python3 -I -B -c ' + shlex.quote(loader)
launcher = '''#!/bin/zsh
print 'MCP Andrea v0.12 p2: aggiorna soltanto l agent del Mac personale (0.12-personal-1 -> 0.12-personal-2).'
print 'Novita: fino a 4 processi nella shell, elenco e stop dei processi, rete per pacchetti (pypi, npm),'
print 'e correzione del blocco del registro dopo un errore (incidente del 03/10).'
print 'Crea un backup, collauda come utente non amministratore e riavvia il solo agent MCP.'
print 'In caso di errore ripristina automaticamente la versione 0.12-personal-1.'
print 'Quando richiesta, inserisci la password di accesso del tuo Mac personale.'
''' + invocation + ''' --check
if [[ $? == 0 ]]; then
  /usr/bin/sudo ''' + invocation + ''' --apply
  if [[ $? == 0 ]]; then
    print 'ATTIVAZIONE_V012P2_MCP_COMPLETATA. Torna nella chat e scrivi Fatto.'
  else
    print 'Attivazione non completata. Lascia questa finestra aperta e torna nella chat.'
  fi
else
  print 'Controllo preliminare non superato. Torna nella chat.'
fi
read -r '?Premi Invio per chiudere questa finestra...'
'''
(P / 'Attiva_MCP_Andrea_v012p2.command').write_text(launcher)
print(json.dumps({'file': target.name, 'sha256': digest, 'bytes': target.stat().st_size, 'remote': remote,
                  'launcher_sha256': hashlib.sha256(launcher.encode()).hexdigest(),
                  'changed': changed, 'dependencies': dependencies}, indent=2))
