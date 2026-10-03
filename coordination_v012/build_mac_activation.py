"""Build the hash-pinned local Mac activation for v0.12.

The logic of the reviewed and executed v0.11 r1 installer is reused verbatim
(everything from `def sha(` to the end); only the header data, the preflight
test list, the selftest module and its timeout change.
"""
from pathlib import Path
import hashlib
import json
import shlex

P = Path(__file__).resolve().parent
LIVE = P.parent / 'coordination_v011r1'       # sources installed by v0.11 r1
PREVIOUS = LIVE / 'upgrade_mac_coordination_v011r1_20261002.py'
assert hashlib.sha256(PREVIOUS.read_bytes()).hexdigest() == \
    '622d1d676e91a2b57e4089b84f617173862cc92953026077a8c45672bd3f7291'
STAMP = 'v012_20261003'
FOLDER = '/Users/babo/MCPAndreaV012_20261003'

changed = ['mac_agent.py', 'work_sessions.py', 'work_schema.py', 'file_tools.py', 'file_schema.py',
           'search_tools.py', 'mac_policy.py', 'mac_child.py', 'mac_shell.py']
new = ['net_proxy.py', 'upload_tools.py']
names = changed + new
dependencies = ['agent_shell.py', 'shell_common.py', 'mac_guard.py', 'mac_clock.py',
                'mac_watchdog.py', 'search_schema.py']
tests = names + dependencies + ['test_work_core.py', 'test_search.py', 'test_v012.py',
                                'mac_v012_selftest.py', 'cg_tools.py']

for n in dependencies:
    assert (P / n).read_bytes() == (LIVE / n).read_bytes(), n
for n in changed:
    assert (P / n).read_bytes() != (LIVE / n).read_bytes(), n
for n in new:
    assert not (LIVE / n).exists(), n
original = {n: hashlib.sha256((LIVE / n).read_bytes()).hexdigest() if n in changed else None for n in names}
deps = {n: hashlib.sha256((LIVE / n).read_bytes()).hexdigest() for n in dependencies}
carried = [n for n in tests if n not in dependencies]
sources = {}
for n in carried:
    text = (P / n).read_text()
    assert text.isascii() and "'''" not in text and not text.endswith('\\'), n
    sources[n] = text
source_sha = {n: hashlib.sha256((P / n).read_bytes()).hexdigest() for n in carried}

previous = PREVIOUS.read_text()
logic = previous[previous.index('def sha(data):'):]


def swap(old, new_text):
    global logic
    assert logic.count(old) == 1, old
    logic = logic.replace(old, new_text)


swap("loadTestsFromNames(['test_work_core','test_search'])",
     "loadTestsFromNames(['test_work_core','test_search','test_v012'])")
swap("TEST_CODE/'mac_coordination_selftest.py'", "TEST_CODE/'mac_v012_selftest.py'")
swap("""    r=child(code)
    atomic(TEST_CODE/'selftest.log'""", """    r=child(code,timeout=120)
    atomic(TEST_CODE/'selftest.log'""")
swap("'coordination smoke failed: '", "'v0.12 smoke failed: '")
swap("""                record('active',version=NEW_VERSION,uid=5000,agent_pid=ready['pid'],checks=checks,""",
     """                record('active',version=NEW_VERSION,uid=5000,agent_pid=ready['pid'],checks=checks,info=SMOKE_INFO,""")
swap("""    result=json.loads(r.stdout.strip())
    if result.get('passed') is not True or result.get('uid')!=5000:raise RuntimeError('invalid smoke receipt')""",
     """    result=json.loads(r.stdout.strip().splitlines()[-1])
    if result.get('passed') is not True or result.get('uid')!=5000:raise RuntimeError('invalid smoke receipt')
    SMOKE_INFO.update(result.get('info',{}))""")
swap("""                print(json.dumps({'status':'active','checks':checks,'uid':5000},indent=2))""",
     """                print(json.dumps({'status':'active','checks':checks,'info':SMOKE_INFO,'uid':5000},indent=2))""")

header = '''#!/usr/bin/env python3
"""Hash-pinned local update of only the central personal-Mac agent: MCP Andrea v0.12."""
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
NEW_VERSION='0.12-personal-1'
PAYLOAD={}
TESTS={}
SMOKE_INFO={}
''' % {'s': STAMP}
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
print 'MCP Andrea v0.12: aggiorna soltanto l agent del Mac personale.'
print 'Nuovi strumenti: elimina, copia, binari; rete della shell solo GitHub su richiesta.'
print 'Crea un backup, collauda come utente non amministratore e riavvia il solo agent MCP.'
print 'In caso di errore ripristina automaticamente la versione 0.11.'
print 'Quando richiesta, inserisci la password di accesso del tuo Mac personale.'
''' + invocation + ''' --check
if [[ $? == 0 ]]; then
  /usr/bin/sudo ''' + invocation + ''' --apply
  if [[ $? == 0 ]]; then
    print 'ATTIVAZIONE_V012_MCP_COMPLETATA. Torna nella chat e scrivi Fatto.'
  else
    print 'Attivazione non completata. Lascia questa finestra aperta e torna nella chat.'
  fi
else
  print 'Controllo preliminare non superato. Torna nella chat.'
fi
read -r '?Premi Invio per chiudere questa finestra...'
'''
(P / 'Attiva_MCP_Andrea_v012.command').write_text(launcher)
print(json.dumps({'file': target.name, 'sha256': digest, 'bytes': target.stat().st_size, 'remote': remote,
                  'launcher_sha256': hashlib.sha256(launcher.encode()).hexdigest(),
                  'original': original}, indent=2))
