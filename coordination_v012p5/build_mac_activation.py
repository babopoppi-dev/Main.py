"""Build the hash-pinned local Mac update v0.12 p5 (0.12-personal-4 -> 0.12-personal-5).

Live state: the v0.12 p4 installation (installer c22b98ad, commit 4bb3e6a,
ATTIVAZIONE_V012P4_MCP_COMPLETATA). p5 adds point E (real project folders),
ported from the reviewed mac_v013 reserve work onto the p4 line:
- ~/Developer read-only and ~/Developer/MCPAndrea read-write (decision of Andrea, 04/10),
  for the file tools and for the isolated shell (seatbelt: read ro+rw, write/exec rw;
  Bitcoin, La Marruca, LiDAR, Library, keychains and credential folders always denied);
- the installer creates both folders (owner Andrea), sets the ACLs for mcp_andrea and
  writes the root-owned projects.json BEFORE stopping the agent: a failure there leaves
  the agent untouched. Rollback removes projects.json and the explicit ACL entries.
The generic agent-only installer logic of p2b is reused; the Telegram helper is untouched.
"""
from pathlib import Path
import hashlib
import json
import shlex

P = Path(__file__).resolve().parent
LIVE_INSTALLER = P.parent / 'coordination_v012p4' / 'upgrade_mac_v012p4_20261004.py'
assert hashlib.sha256(LIVE_INSTALLER.read_bytes()).hexdigest() == \
    'c22b98ad07c47add369c38b69c7dab21c146cea8248eaf5bf8d6be3a39043665'
LOGIC_INSTALLER = P.parent / 'coordination_v012p2' / 'upgrade_mac_v012p2b_20261003.py'
assert hashlib.sha256(LOGIC_INSTALLER.read_bytes()).hexdigest() == \
    'fecdbab5a4fe1318c8e73b7d928e7dc0e9fa81f3e96b0e993d94c4025a74e3a2'
STAMP = 'v012p5_20261004'
FOLDER = '/Users/babo/MCPAndreaV012p5'
OLD_VERSION, NEW_VERSION = '0.12-personal-4', '0.12-personal-5'

previous = LIVE_INSTALLER.read_text()
live = {}
exec(previous[:previous.index('def sha(data):')], live)
installed = {n: live['SOURCES'][n].encode() for n in live['ORIGINAL']}
assert {n: hashlib.sha256(b).hexdigest() for n, b in installed.items()} == \
    {n: live['SOURCE_SHA'][n] for n in live['ORIGINAL']}
added = ['mac_projects.py']
live_hash = {**{n: hashlib.sha256(b).hexdigest() for n, b in installed.items()}, **live['DEPENDENCIES']}
assert live['NEW_VERSION'] == OLD_VERSION

modules = sorted(live_hash)
changed = [n for n in modules if hashlib.sha256((P / n).read_bytes()).hexdigest() != live_hash[n]]
dependencies = [n for n in modules if n not in changed]
assert changed == ['mac_agent.py', 'mac_child.py', 'mac_policy.py', 'mac_shell.py'], changed
original = {**{n: live_hash[n] for n in changed}, **{n: None for n in added}}
deps = {n: live_hash[n] for n in dependencies}
tests = changed + added + dependencies + ['test_work_core.py', 'test_search.py', 'test_v012.py', 'test_files_v012.py',
                                          'test_mac_admin.py', 'test_projects.py', 'mac_admin_helper.py',
                                          'mac_v012_selftest.py', 'cg_tools.py']
carried = [n for n in tests if n not in dependencies]
# Helper and its tests are the installed p3 ones, byte for byte.
for n in ('admin_schema.py', 'mac_admin_client.py', 'mac_admin_helper.py', 'test_mac_admin.py', 'cg_tools.py'):
    assert (P / n).read_bytes() == (P.parent / 'coordination_v012p4' / n).read_bytes(), n
sources = {}
for n in carried:
    text = (P / n).read_text()
    assert text.isascii() and "'''" not in text and not text.endswith('\\'), n
    sources[n] = text
source_sha = {n: hashlib.sha256((P / n).read_bytes()).hexdigest() for n in carried}

logic = LOGIC_INSTALLER.read_text()
logic = logic[logic.index('def sha(data):'):]


def swap(old, new_text):
    global logic
    assert logic.count(old) == 1, old
    logic = logic.replace(old, new_text)


swap("['test_work_core','test_search','test_v012','test_files_v012']",
     "['test_work_core','test_search','test_v012','test_files_v012','test_mac_admin','test_projects']")
swap("'v0.12 p2 smoke failed: '", "'v0.12 p5 smoke failed: '")
swap("""            check_sources()
            stopped=False;installed=False""", """            check_sources()
            # Point E before any stop: folders, ACLs and projects.json (ignored by the p4 agent).
            try:project_info=projects_setup()
            except Exception as e:
                record('projects_setup_failed',reason=str(e)[:1200],cleanup_errors=projects_remove(),
                       live_modules_modified=False);raise
            stopped=False;installed=False""")
swap("""            except Exception as error:
                try:
                    if installed and not stopped:""", """            except Exception as error:
                project_info['cleanup_errors']=projects_remove()
                try:
                    if installed and not stopped:""")
swap("                record('active',version=NEW_VERSION,uid=5000,",
     "                record('active',projects=project_info,version=NEW_VERSION,uid=5000,")
swap("""            with workspace_guard():
                verify_restore()
                stop_daemon()""", """            with workspace_guard():
                verify_restore()
                cleanup=projects_remove()
                stop_daemon()""")
assert logic.count('\n\nif __name__==') == 1
logic = logic.replace('\n\nif __name__==', '\n' + (P / 'mac_projects_install_body.py').read_text() + '\n\nif __name__==', 1)
# The smoke now also drives an interactive REPL: leave more room than p2b's 120 s.
swap("    r=child(code,timeout=120)\n", "    r=child(code,timeout=240)\n")

header = '''#!/usr/bin/env python3
"""Hash-pinned local update of the personal-Mac agent: MCP Andrea v0.12 p5 (real project folders, point E)."""
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
print 'MCP Andrea v0.12 p5: progetti reali (0.12-personal-4 -> 0.12-personal-5).'
print 'Crea ~/Developer (sola lettura per MCP) e ~/Developer/MCPAndrea (lettura e scrittura), imposta i permessi,'
print 'crea un backup, collauda come utente non amministratore, riavvia il solo agent MCP.'
print 'Bitcoin, La Marruca, LiDAR, Library e credenziali restano sempre esclusi. Helper Telegram non toccato.'
print 'In caso di errore ripristina la 0.12-personal-4 e toglie configurazione e permessi.'
print 'Hash atteso installer: ''' + digest + ''''
/usr/bin/shasum -a 256 ''' + shlex.quote(remote) + '''
print 'Quando richiesta, inserisci la password di accesso del tuo Mac personale.'
''' + invocation + ''' --check
if [[ $? == 0 ]]; then
  /usr/bin/sudo ''' + invocation + ''' --apply
  if [[ $? == 0 ]]; then
    print 'ATTIVAZIONE_V012P5_MCP_COMPLETATA. Torna nella chat e scrivi Fatto.'
  else
    print 'Attivazione non completata. Lascia questa finestra aperta e torna nella chat.'
  fi
else
  print 'Controllo preliminare non superato. Torna nella chat.'
fi
read -r '?Premi Invio per chiudere questa finestra...'
'''
(P / 'Attiva_MCP_Andrea_v012p5.command').write_text(launcher)
print(json.dumps({'file': target.name, 'sha256': digest, 'bytes': target.stat().st_size, 'remote': remote,
                  'launcher_sha256': hashlib.sha256(launcher.encode()).hexdigest(),
                  'changed': changed, 'added': added, 'dependencies': dependencies}, indent=2))
