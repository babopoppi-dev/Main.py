"""Build the hash-pinned local Mac update v0.12 p3 (0.12-personal-2 -> 0.12-personal-3).

Live state: the v0.12 p2b installation (installer fecdbab5, commit ada54b7,
ATTIVAZIONE_V012P2B_MCP_COMPLETATA). Its embedded SOURCES and DEPENDENCIES are
exactly the modules installed on the Mac. The p2b installer logic is reused
verbatim; p3 adds point C of the reserve work (mac_v012/, reviewed 03/10):
mac_admin_request/mac_admin_result in the agent, Telegram pairing of a NEW bot
dedicated to the Mac and the separate root helper LaunchDaemon.
"""
from pathlib import Path
import hashlib
import json
import shlex

P = Path(__file__).resolve().parent
PREVIOUS = P.parent / 'coordination_v012p2' / 'upgrade_mac_v012p2b_20261003.py'
assert hashlib.sha256(PREVIOUS.read_bytes()).hexdigest() == \
    'fecdbab5a4fe1318c8e73b7d928e7dc0e9fa81f3e96b0e993d94c4025a74e3a2'
STAMP = 'v012p3_20261003'
FOLDER = '/Users/babo/MCPAndreaV012p3'
OLD_VERSION, NEW_VERSION = '0.12-personal-2', '0.12-personal-3'

previous = PREVIOUS.read_text()
live = {}
exec(previous[:previous.index('def sha(data):')], live)
installed = {n: live['SOURCES'][n].encode() for n in live['ORIGINAL']}
assert {n: hashlib.sha256(b).hexdigest() for n, b in installed.items()} == \
    {n: live['SOURCE_SHA'][n] for n in live['ORIGINAL']}
live_hash = {**{n: hashlib.sha256(b).hexdigest() for n, b in installed.items()}, **live['DEPENDENCIES']}
assert live['NEW_VERSION'] == OLD_VERSION

added = ['admin_schema.py', 'mac_admin_client.py']
modules = sorted(live_hash)
changed = [n for n in modules if hashlib.sha256((P / n).read_bytes()).hexdigest() != live_hash[n]]
dependencies = [n for n in modules if n not in changed]
assert changed == ['mac_agent.py'], changed
original = {**{n: live_hash[n] for n in changed}, **{n: None for n in added}}
deps = {n: live_hash[n] for n in dependencies}
tests = changed + added + dependencies + ['test_work_core.py', 'test_search.py', 'test_v012.py', 'test_files_v012.py',
                                          'test_mac_admin.py', 'mac_admin_helper.py', 'mac_v012_selftest.py', 'cg_tools.py']
carried = [n for n in tests if n not in dependencies]
# The root helper is carried unchanged from the reviewed reserve work.
for n in ('admin_schema.py', 'mac_admin_client.py', 'mac_admin_helper.py', 'test_mac_admin.py'):
    assert (P / n).read_bytes() == (P.parent / 'mac_v012' / n).read_bytes(), n
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


swap("['test_work_core','test_search','test_v012','test_files_v012']",
     "['test_work_core','test_search','test_v012','test_files_v012','test_mac_admin']")
swap("'v0.12 p2 smoke failed: '", "'v0.12 p3 smoke failed: '")
swap("""        if action=='--apply':
            check_sources()
            try:preflight()""", """        if action=='--apply':
            check_sources()
            # Interactive pairing first: a failure here leaves the agent untouched.
            admin_conf=telegram_setup()
            try:preflight()""")
swap("                record('active',version=NEW_VERSION,uid=5000,",
     "                record('agent_active',version=NEW_VERSION,uid=5000,")
swap("                print(json.dumps({'status':'active','checks':checks,",
     "                print(json.dumps({'status':'agent_active','checks':checks,")
swap("""                raise
        elif action=='--rollback':
            with workspace_guard():""", """                raise
            # The agent stays on p3 if only the helper fails (helper removed, receipt says so).
            admin_phase(admin_conf)
        elif action=='--rollback':
            admin_remove()
            with workspace_guard():""")
assert logic.count('\n\nif __name__==') == 1
logic = logic.replace('\n\nif __name__==', '\n' + (P / 'mac_admin_install_body.py').read_text() + '\n\nif __name__==', 1)

header = '''#!/usr/bin/env python3
"""Hash-pinned local update of the personal-Mac agent and the Telegram admin helper: MCP Andrea v0.12 p3."""
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
SYSTEM_AGENTS=frozenset(%(agents)r)
''' % {'s': STAMP, 'plist': live['PLIST_SHA'], 'old': OLD_VERSION, 'new': NEW_VERSION,
       'agents': sorted(live['SYSTEM_AGENTS'])}
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
print 'MCP Andrea v0.12 p3: amministrazione del Mac via Telegram (0.12-personal-2 -> 0.12-personal-3).'
print 'Serve un bot Telegram NUOVO dedicato al Mac (@BotFather, /newbot): il token resta solo su questo Mac.'
print 'Abbina il bot, crea un backup, collauda come utente non amministratore, riavvia il solo agent MCP'
print 'e installa l helper root separato. In caso di errore sull agent ripristina la 0.12-personal-2.'
print 'Hash atteso installer: ''' + digest + ''''
/usr/bin/shasum -a 256 ''' + shlex.quote(remote) + '''
print 'Quando richiesta, inserisci la password di accesso del tuo Mac personale.'
''' + invocation + ''' --check
if [[ $? == 0 ]]; then
  /usr/bin/sudo ''' + invocation + ''' --apply
  if [[ $? == 0 ]]; then
    print 'ATTIVAZIONE_V012P3_MCP_COMPLETATA. Torna nella chat e scrivi Fatto.'
  else
    print 'Attivazione non completata. Lascia questa finestra aperta e torna nella chat.'
  fi
else
  print 'Controllo preliminare non superato. Torna nella chat.'
fi
read -r '?Premi Invio per chiudere questa finestra...'
'''
(P / 'Attiva_MCP_Andrea_v012p3.command').write_text(launcher)
print(json.dumps({'file': target.name, 'sha256': digest, 'bytes': target.stat().st_size, 'remote': remote,
                  'launcher_sha256': hashlib.sha256(launcher.encode()).hexdigest(),
                  'changed': changed, 'added': added, 'dependencies': dependencies}, indent=2))
