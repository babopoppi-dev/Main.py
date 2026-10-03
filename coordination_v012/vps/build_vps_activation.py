"""Build the hash-pinned VPS agent activation for v0.12 (sessions, locks, new tools).

Reuses the executed search v0.10 VPS installer flow (template helpers, preflight
as the agent user, backup, stop/replace/restart, smoke, automatic rollback).
Requires the gateway v0.12 catalog first: file_schema.py and work_schema.py
are pinned at their v0.12 hashes. Deposit and run via admin_request (Telegram).
"""
from pathlib import Path
import hashlib
import json
import re

V = Path(__file__).resolve().parent          # vps/
P = V.parent                                 # coordination_v012/
TEMPLATE = P.parent / 'coordination_v011r1' / 'upgrade_vps_template.py'
STAMP = 'vps_v012_20261003'
LIVE = json.loads((V / 'live_hashes.json').read_text())

payload_src = {'agent.py': V / 'agent.py', 'file_tools.py': P / 'file_tools.py',
               'search_tools.py': P / 'search_tools.py', 'work_sessions.py': P / 'work_sessions.py',
               'upload_tools.py': P / 'upload_tools.py'}
original = {n: LIVE.get(n) for n in payload_src}
assert original['work_sessions.py'] is None and original['upload_tools.py'] is None
assert original['agent.py'] == hashlib.sha256((V / 'agent_live.py').read_bytes()).hexdigest(), 'transcription differs'
# Catalog modules shared with the gateway may be v0.11 (live today) or v0.12
# (after the gateway activation): the VPS agent works with both.
LIVE11 = json.loads((V / 'live_hashes.json').read_text())['_v011']
deps = {n: LIVE[n] for n in ('search_schema.py', 'isolated_shell.py', 'cg_mcp.py', 'cg_agents.py')}
for n in ('file_schema.py', 'work_schema.py', 'cg_tools.py'):
    v012 = hashlib.sha256((P / n).read_bytes()).hexdigest()
    assert LIVE[n] == v012, n
    deps[n] = [LIVE11[n], v012]
assert deps['isolated_shell.py'] == hashlib.sha256((P / 'shell_common.py').read_bytes()).hexdigest()
assert deps['search_schema.py'] == hashlib.sha256((P / 'search_schema.py').read_bytes()).hexdigest()
# The preflight imports the v0.12 catalog copies carried here, so it is the
# same suite whatever catalog version is live.
tests_src = {'test_search.py': P / 'test_search.py', 'test_files_v012.py': P / 'test_files_v012.py',
             'test_vps_agent.py': V / 'test_vps_agent.py', 'file_schema.py': P / 'file_schema.py',
             'work_schema.py': P / 'work_schema.py', 'cg_tools.py': P / 'cg_tools.py'}
live_deps = ['search_schema.py', 'isolated_shell.py']
test_names = sorted(list(payload_src) + live_deps + list(tests_src))
sources = {}
for n, path in {**payload_src, **tests_src}.items():
    text = path.read_text()
    assert text.isascii() and "'''" not in text and not text.endswith('\\'), n
    sources[n] = text
source_sha = {n: hashlib.sha256(t.encode()).hexdigest() for n, t in sources.items()}

template = TEMPLATE.read_text()
logic = template[template.index('def sha(data):'):]


def cut(start, end, new):
    global logic
    a = logic.index(start); b = logic.index(end)
    logic = logic[:a] + new + logic[b:]


def swap(old, new):
    global logic
    assert logic.count(old) == 1, old
    logic = logic.replace(old, new)


swap("""    for name,expected in {**ORIGINAL,**DEPENDENCIES}.items():
        if digest(BASE/name)!=expected:raise RuntimeError('live source changed: '+name)""",
     """    for name,expected in {**ORIGINAL,**DEPENDENCIES}.items():
        if digest(BASE/name) not in (expected if isinstance(expected,list) else [expected]):
            raise RuntimeError('live source changed: '+name)""")
swap("""    if state.get('active_locks') or state.get('shell_enabled'):
        raise RuntimeError('VPS busy; active locks or shell authorization present')""",
     """    if state.get('active_locks') or state.get('shell_enabled') or state.get('work_locks') or state.get('work_sessions'):
        raise RuntimeError('VPS busy; active locks, work sessions or shell authorization present')""")
swap("""    for name in ('file_tools.py','file_schema.py','isolated_shell.py'):
        if sha(TESTS[name])!=DEPENDENCIES[name]:raise RuntimeError('preflight dependency differs')""",
     """    for name in LIVE_TEST_DEPS:
        if sha(TESTS[name])!=DEPENDENCIES[name]:raise RuntimeError('preflight dependency differs')""")
swap("loadTestsFromNames(['test_search','test_vps_agent'])",
     "loadTestsFromNames(['test_search','test_files_v012','test_vps_agent'])")
swap("capture_output=True,text=True,timeout=45)", "capture_output=True,text=True,timeout=120)")
swap("""def restart(expect_search):""", """def restart(expect_new):""")
swap("""            if machine['online'] and (not expect_search or machine['meta'].get('search_version')=='0.10.1'):return""",
     """            if machine['online'] and (machine['meta'].get('coordination_version')=='0.11.0')==expect_new:return""")
cut('def smoke():', 'def load_package():', '''def smoke():
    names={t['name'] for t in rpc('tools/list',{})['tools']}
    if not {'work_session','work_lock'}<=names:raise RuntimeError('work tools missing from catalog')
    # The new file tools are exercised only once the gateway exposes them.
    new={'delete_path','copy_file','read_binary','upload_file'}<=names
    checks=[];operations=[];sessions=[]
    folder=str(WORK/('vps_v012_live_'+uuid.uuid4().hex))
    def scall(s,name,**args):
        return call(name,machine='vps',work_session_id=s['work_session_id'],work_session_token=s['work_session_token'],**args)
    def refused(name,**args):
        if not rpc('tools/call',{'name':name,'arguments':dict(machine='vps',**args)}).get('isError'):
            raise RuntimeError(name+' was not refused')
    try:
        a=call('work_session',machine='vps',action='open',label='installer A',minutes=5);sessions.append(a)
        b=call('work_session',machine='vps',action='open',label='installer B',minutes=5);sessions.append(b)
        refused('create_directory',path=folder)
        refused('create_directory',path=folder,work_session_id=a['work_session_id'],work_session_token=a['work_session_token'])
        checks.append('writes need session and lock')
        scall(a,'work_lock',action='acquire',path=folder,minutes=5)
        refused('work_lock',action='acquire',path=folder+'/x',minutes=5,work_session_id=b['work_session_id'],work_session_token=b['work_session_token'])
        checks.append('descendant lock conflict between sessions')
        operations.append(scall(a,'create_directory',path=folder)['operation_id'])
        path=folder+'/test.txt'
        operations.append(scall(a,'write_file',path=path,content='MCP_VPS_V012_OK\\n')['operation_id'])
        refused('write_file',path=path,content='x',work_session_id=b['work_session_id'],work_session_token=b['work_session_token'])
        result=scall(a,'start_search',path=folder,pattern='MCP_VPS_V012_OK');sid=result['search_id']
        end=time.monotonic()+10
        while result['running'] and time.monotonic()<end:
            time.sleep(.1);result=scall(a,'get_more_search_results',search_id=sid)
        if result['status']!='completed' or result['total_results']!=1:raise RuntimeError('live search mismatch')
        checks.append('search with session')
        if new:
          data=b'\\x00\\x01v012'
          up=scall(a,'upload_file',action='begin',path=folder+'/bin',size=len(data),sha256=hashlib.sha256(data).hexdigest())
          scall(a,'upload_file',action='chunk',upload_id=up['upload_id'],offset=0,data=base64.b64encode(data).decode())
          operations.append(scall(a,'upload_file',action='commit',upload_id=up['upload_id'])['operation_id'])
          if call('read_binary',machine='vps',path=folder+'/bin')['sha256']!=hashlib.sha256(data).hexdigest():
              raise RuntimeError('binary round trip mismatch')
          operations.append(scall(a,'copy_file',source=path,destination=folder+'/copy.txt')['operation_id'])
          removed=scall(a,'delete_path',path=folder+'/copy.txt')
          scall(a,'rollback_file',operation_id=removed['operation_id'])
          checks.append('upload, read_binary, copy, delete and rollback')
        if call('shell_exec',machine='vps',command='uname -a')['exit_code']!=0:raise RuntimeError('baseline status failed')
        checks.append('baseline status without session')
    finally:
        for operation in reversed(operations):
            if sessions:scall(sessions[0],'rollback_file',operation_id=operation)
        for s in sessions:
            with contextlib.suppress(Exception):scall(s,'work_session',action='close')
    if Path(folder).exists():raise RuntimeError('smoke rollback left a test directory')
    idle();checks.append('test files rolled back; no sessions, locks or shell left')
    return checks


''')
cut('def load_package():', 'def main(action):', '''def load_package():
    global PAYLOAD,TESTS
    carried={n:src.encode() for n,src in SOURCES.items()}
    if {n:sha(b) for n,b in carried.items()}!=SOURCE_SHA:raise RuntimeError('unexpected embedded sources')
    PAYLOAD={n:carried[n] for n in ORIGINAL}
    # Unchanged dependencies come from the live, hash-pinned installation.
    TESTS={n:carried[n] if n in carried else read(BASE/n) for n in TEST_NAMES}
    for n in LIVE_TEST_DEPS:
        if sha(TESTS[n])!=DEPENDENCIES[n]:raise RuntimeError('live dependency changed: '+n)
    for name,data in {**PAYLOAD,**TESTS}.items():compile(data,name,'exec')


''')
swap("'--unit=central-mcp-search-v010-20261002'", "'--unit=central-mcp-vps-v012-20261003'")
swap("prefix='.search-v010-'", "prefix='.vps-v012-'")

header = '''#!/usr/bin/env python3
"""VPS agent v0.12 (work sessions, locks, reversible file tools). Telegram-approved admin_request only."""
import base64,contextlib,fcntl,hashlib,json,os,ssl,stat,subprocess,sys,tempfile,time,urllib.request,uuid,zlib
from pathlib import Path
BASE=Path('/opt/central-mcp-gateway')
SELF=BASE/'upgrade_%(s)s.py'
BACKUP=BASE/'backups/pre_%(s)s'
RECEIPT=BASE/'%(s)s_receipt.json'
TEST_CODE=BASE/'preflight-%(s)s'
TEST_DATA=Path('/var/lib/central-mcp-vps-agent-test/tmp/preflight-%(s)s')
WORK=Path('/var/lib/central-mcp-vps-agent-test/workspace')
GUARD=Path('/var/lib/central-mcp-vps-agent-test/file-operations-v07/guard')
AGENT='central-mcp-vps-agent-test.service'
GATEWAY='central-mcp-gateway-test.service'
PAYLOAD={}
TESTS={}
''' % {'s': STAMP}
header += ('ORIGINAL=' + repr(original) + '\nDEPENDENCIES=' + repr(deps) + '\nLIVE_TEST_DEPS=' + repr(live_deps)
           + '\nTEST_NAMES=' + repr(test_names) + '\nSOURCE_SHA=' + repr(source_sha) + '\nSOURCES={\n'
           + ''.join(repr(n) + ": r'''" + t + "''',\n" for n, t in sources.items()) + '}\n\n\n')
target = V / ('upgrade_' + STAMP + '.py')
target.write_text(header + logic)
compile(target.read_bytes(), str(target), 'exec')
digest = hashlib.sha256(target.read_bytes()).hexdigest()
remote = '/opt/central-mcp-gateway/' + target.name
staging = '/var/lib/central-mcp-vps-agent-test/workspace/' + target.name
cmds = {'ADMIN_REQUEST_V1_installa_script.txt': 'install -o root -g root -m 0555 ' + staging + ' ' + remote,
        'ADMIN_REQUEST_V2_attiva.txt': '/usr/bin/python3 -I -B ' + remote + ' --apply',
        'ADMIN_REQUEST_V3_ricevuta.txt': 'cat /opt/central-mcp-gateway/' + STAMP + '_receipt.json',
        'ADMIN_REQUEST_V_rollback.txt': '/usr/bin/python3 -I -B ' + remote + ' --rollback'}
for name, cmd in cmds.items():
    assert re.fullmatch(r"[A-Za-z0-9_./:=@%+, -]+", cmd) and len(cmd) <= 3000, cmd
    (V / name).write_text(cmd + '\n')
print(json.dumps({'file': target.name, 'sha256': digest, 'bytes': target.stat().st_size,
                  'original': original}, indent=2))
