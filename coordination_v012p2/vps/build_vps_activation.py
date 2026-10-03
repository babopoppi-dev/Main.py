"""Build the hash-pinned VPS agent update v0.12 p2 (0.12-vps-1 -> 0.12-vps-2).

Live state: the corrected v0.12 VPS activation (vps_v012_fix, fcf8e9b4), active
since 2026-10-03. Its logic is reused verbatim except for the header, the
reconnection check (agent_version instead of coordination_version, which is
0.11.0 before and after), the unit name and one extra live smoke check.
Payload: file_tools.py (journal never left 'prepared') and agent.py (session ids
in the audit log, from r2). The shared catalog cg_tools.py may be r1 or p2.
Deposit and run via admin_request (Telegram).
"""
from pathlib import Path
import hashlib
import json
import re

V = Path(__file__).resolve().parent          # vps/
P = V.parent                                 # coordination_v012p2/
PREVIOUS = P.parent / 'vps_v012_fix' / 'upgrade_vps_v012_20261003.py'
assert hashlib.sha256(PREVIOUS.read_bytes()).hexdigest() == \
    'fcf8e9b4a9c5a19bcbd9c50b8e0b1e0e30076e958c92829f039a783a0b2826bb'
OLD_STAMP, STAMP = 'vps_v012_20261003', 'vps_v012p2_20261003'
OLD_VERSION, NEW_VERSION = '0.12-vps-1', '0.12-vps-2'
previous = PREVIOUS.read_text()
cut = previous.index('def sha(data):')
live = {}
exec(previous[:cut], live)
installed = {n: hashlib.sha256(live['SOURCES'][n].encode()).hexdigest() for n in live['ORIGINAL']}
assert installed == {n: live['SOURCE_SHA'][n] for n in live['ORIGINAL']}
assert "'agent_version': %r" % OLD_VERSION in live['SOURCES']['agent.py']

payload_src = {'agent.py': V / 'agent.py', 'file_tools.py': P / 'file_tools.py'}
original = {n: installed[n] for n in payload_src}
deps = dict(live['DEPENDENCIES'])
for n in ('search_tools.py', 'work_sessions.py', 'upload_tools.py'):
    assert hashlib.sha256((P / n).read_bytes()).hexdigest() == installed[n], n
    deps[n] = installed[n]
# The gateway p2 activation replaces the shared catalog: accept r1 and p2.
cg_p2 = hashlib.sha256((P / 'cg_tools.py').read_bytes()).hexdigest()
deps['cg_tools.py'] = [live['DEPENDENCIES']['cg_tools.py'][1], cg_p2]
assert "'agent_version': %r" % NEW_VERSION in (V / 'agent.py').read_text()

tests_src = {'test_search.py': P / 'test_search.py', 'test_files_v012.py': P / 'test_files_v012.py',
             'test_vps_agent.py': V / 'test_vps_agent.py', 'file_schema.py': P / 'file_schema.py',
             'work_schema.py': P / 'work_schema.py', 'cg_tools.py': P / 'cg_tools.py',
             'search_tools.py': P / 'search_tools.py', 'work_sessions.py': P / 'work_sessions.py',
             'upload_tools.py': P / 'upload_tools.py'}
carried_src = {**payload_src, **tests_src}
assert sorted(set(carried_src) | set(live['LIVE_TEST_DEPS'])) == sorted(live['TEST_NAMES'])
sources = {}
for n, path in sorted(carried_src.items()):
    text = path.read_text()
    assert text.isascii() and "'''" not in text and not text.endswith('\\'), n
    sources[n] = text
source_sha = {n: hashlib.sha256(t.encode()).hexdigest() for n, t in sources.items()}

logic = previous[cut:]


def swap(old, new):
    global logic
    assert logic.count(old) == 1, old
    logic = logic.replace(old, new)


swap("""            if machine['online'] and (machine['meta'].get('coordination_version')=='0.11.0')==expect_new:return""",
     """            if machine['online'] and machine['meta'].get('agent_version')==(NEW_VERSION if expect_new else OLD_VERSION):return""")
swap("'--unit=central-mcp-vps-v012-20261003'", "'--unit=central-mcp-vps-v012p2-20261003'")
swap("""        operations.append(scall(a,'create_directory',path=folder)['operation_id'])""",
     """        # p2: a write into a missing directory fails cleanly and the journal stays usable.
        bad=rpc('tools/call',{'name':'write_file','arguments':dict(machine='vps',path=folder+'/missing/x',content='x',
            work_session_id=a['work_session_id'],work_session_token=a['work_session_token'])})
        if not bad.get('isError') or 'parent directory does not exist' not in bad['content'][0]['text']:raise RuntimeError('missing parent not refused cleanly')
        checks.append('missing parent refused; journal usable')
        operations.append(scall(a,'create_directory',path=folder)['operation_id'])""")

header = previous[:previous.index('PAYLOAD={}')].replace(OLD_STAMP, STAMP).replace(
    'VPS agent v0.12 (work sessions, locks, reversible file tools).', 'VPS agent v0.12 p2 (journal fix, session ids in the log).')
assert header.count(STAMP) == 5
header += ('PAYLOAD={}\nTESTS={}\nOLD_VERSION=%r\nNEW_VERSION=%r\n' % (OLD_VERSION, NEW_VERSION)
           + 'ORIGINAL=' + repr(original) + '\nDEPENDENCIES=' + repr(deps)
           + '\nLIVE_TEST_DEPS=' + repr(live['LIVE_TEST_DEPS']) + '\nTEST_NAMES=' + repr(live['TEST_NAMES'])
           + '\nSOURCE_SHA=' + repr(source_sha) + '\nSOURCES={\n'
           + ''.join(repr(n) + ": r'''" + t + "''',\n" for n, t in sources.items()) + '}\n\n\n')
target = V / ('upgrade_' + STAMP + '.py')
target.write_text(header + logic)
compile(target.read_bytes(), str(target), 'exec')
digest = hashlib.sha256(target.read_bytes()).hexdigest()
remote = '/opt/central-mcp-gateway/' + target.name
cmds = {'ADMIN_REQUEST_V1_download_vps.txt': None,   # filled with the pinned commit after push
        'ADMIN_REQUEST_V2_hash_vps.txt': 'sha256sum ' + remote,
        'ADMIN_REQUEST_V3_permessi_vps.txt': 'chmod 0555 ' + remote,
        'ADMIN_REQUEST_V4_apply_vps.txt': '/usr/bin/python3 -I -B ' + remote + ' --apply',
        'ADMIN_REQUEST_V5_ricevuta_vps.txt': 'cat /opt/central-mcp-gateway/' + STAMP + '_receipt.json',
        'ADMIN_REQUEST_V_rollback_vps.txt': '/usr/bin/python3 -I -B ' + remote + ' --rollback'}
for name, cmd in cmds.items():
    if cmd is None:
        continue
    assert re.fullmatch(r"[A-Za-z0-9_./:=@%+, -]+", cmd) and len(cmd) <= 3000, cmd
    (V / name).write_text(cmd + '\n')
print(json.dumps({'file': target.name, 'sha256': digest, 'bytes': target.stat().st_size,
                  'original': original, 'cg_tools_accepted': deps['cg_tools.py']}, indent=2))
