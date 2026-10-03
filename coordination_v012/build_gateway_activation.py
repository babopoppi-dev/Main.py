"""Build the hash-pinned gateway catalog activation for v0.12.

Reuses the executed v0.11 r1 gateway script (helpers and flow) verbatim except
for the payload, preflight assertions, smoke expectations and unit name.
Deposit and execution go through admin_request with Telegram approval.
Agents are not modified by this script.
"""
from pathlib import Path
import hashlib
import json
import re

P = Path(__file__).resolve().parent
LIVE = P.parent / 'coordination_v011r1'
PREVIOUS = LIVE / 'upgrade_gateway_coordination_v011r1_20261002.py'
assert hashlib.sha256(PREVIOUS.read_bytes()).hexdigest() == \
    '2204193c45aa44afed384b0e4f49376b705e712809a68922818e597aea3607e5'
STAMP = 'v012_20261003'
names = ['cg_tools.py', 'file_schema.py', 'work_schema.py']
original = {n: hashlib.sha256((LIVE / n).read_bytes()).hexdigest() for n in names}
assert original['cg_tools.py'] == '8282e608be40003e9475dc789ddf7d90e8676aa88776d9f8b3923b33087d02a1'
assert original['work_schema.py'] == '9204940d1c304ca41236785b2248c449a93f8102fcd1e15fae4d76c478db9ee9'
assert (P / 'search_schema.py').read_bytes() == (LIVE / 'search_schema.py').read_bytes()
deps = {'cg_mcp.py': 'f8a86b9a8424f9e6a0bc335f2951c8e9233750b62e1181379d9c6be3ebb04171',
        'search_schema.py': hashlib.sha256((LIVE / 'search_schema.py').read_bytes()).hexdigest()}
sources = {}
for n in names:
    text = (P / n).read_text()
    assert text.isascii() and "'''" not in text and '\\' not in text and 'MCPEOF' not in text, n
    sources[n] = text
payload_sha = {n: hashlib.sha256((P / n).read_bytes()).hexdigest() for n in names}

previous = PREVIOUS.read_text()
logic = previous[previous.index('def sha(data):'):]


def swap(old, new):
    global logic
    assert logic.count(old) == 1, old
    logic = logic.replace(old, new)


swap("prefix='coord-v011-gw-'", "prefix='mcp-v012-gw-'")
swap("""'assert {"work_session","work_lock","write_file","start_search","admin_request"}<=c.NAMES;'""",
     """'assert {"work_session","work_lock","write_file","start_search","admin_request","delete_path","copy_file","read_binary","upload_file"}<=c.NAMES;'""")
swap("""'assert "work_session_id" not in t["admin_request"]["inputSchema"]["properties"];print(len(n))')""",
     """'assert "work_session_id" not in t["admin_request"]["inputSchema"]["properties"];'
              'assert "work_session_id" in t["upload_file"]["inputSchema"]["properties"];'
              'assert t["enable_full_shell"]["inputSchema"]["properties"]["network"]["enum"]==["none","github","packages"];print(len(n))')""")
start = logic.index('def smoke(expect_work):')
end = logic.index('def install(manifest):')
logic = logic[:start] + '''NEW_TOOLS={'delete_path','copy_file','read_binary','upload_file'}


def smoke(expect_new):
    tools={t['name']:t for t in rpc('tools/list',{})['tools']}
    if not {'work_session','work_lock'}<=set(tools):raise RuntimeError('work tools missing')
    if (NEW_TOOLS<=set(tools))!=expect_new or (not expect_new and NEW_TOOLS&set(tools)):
        raise RuntimeError('unexpected v0.12 tool catalog')
    if ('network' in tools['enable_full_shell']['inputSchema']['properties'])!=expect_new:
        raise RuntimeError('unexpected network option')
    if expect_new and 'work_session_id' not in tools['delete_path']['inputSchema']['properties']:
        raise RuntimeError('session parameters missing')
    if call('shell_exec',machine='vps',command='uname -a')['exit_code']!=0:raise RuntimeError('vps baseline failed')
    idle()
    return ['catalog '+('with' if expect_new else 'without')+' v0.12 tools','vps baseline','vps and mac_mio idle']


''' + logic[end:]
swap("'--unit=central-mcp-coordination-v011r1-20261002'", "'--unit=central-mcp-v012-20261003'")

header = '''#!/usr/bin/env python3
"""Gateway catalog activation for MCP Andrea v0.12. Telegram-approved admin_request only."""
import base64,contextlib,fcntl,hashlib,json,os,ssl,stat,subprocess,sys,tempfile,time,urllib.request,uuid,zlib
from pathlib import Path
BASE=Path('/opt/central-mcp-gateway')
SELF=BASE/'upgrade_gateway_%(s)s.py'
BACKUP=BASE/'backups/pre_%(s)s'
RECEIPT=BASE/'%(s)s_receipt.json'
GATEWAY='central-mcp-gateway-test.service'
PYTHON='/usr/bin/python3'
PAYLOAD={}
''' % {'s': STAMP}
header += ('ORIGINAL=' + repr(original) + '\nDEPENDENCIES=' + repr(deps) + '\nPAYLOAD_SHA=' + repr(payload_sha)
           + '\nSOURCES={\n' + ''.join(repr(n) + ": r'''" + t + "''',\n" for n, t in sources.items()) + '}\n\n\n')
target = P / ('upgrade_gateway_' + STAMP + '.py')
target.write_text(header + logic)
compile(target.read_bytes(), str(target), 'exec')
digest = hashlib.sha256(target.read_bytes()).hexdigest()
remote = '/opt/central-mcp-gateway/' + target.name
staging = '/var/lib/central-mcp-vps-agent-test/workspace/' + target.name
# admin_request runs argv without a shell: one command per request.
cmds = {'ADMIN_REQUEST_0_hash_deposito_gateway.txt': 'sha256sum ' + staging,
        'ADMIN_REQUEST_1_deposito_gateway.txt': 'install -o root -g root -m 0555 ' + staging + ' ' + remote,
        'ADMIN_REQUEST_2_check_gateway.txt': '/usr/bin/python3 -I -B ' + remote + ' --check',
        'ADMIN_REQUEST_3_apply_gateway.txt': '/usr/bin/python3 -I -B ' + remote + ' --apply',
        'ADMIN_REQUEST_4_ricevuta_gateway.txt': 'cat /opt/central-mcp-gateway/' + STAMP + '_receipt.json',
        'ADMIN_REQUEST_rollback_gateway.txt': '/usr/bin/python3 -I -B ' + remote + ' --rollback'}
for name, cmd in cmds.items():
    assert re.fullmatch(r"[A-Za-z0-9_./:=@%+, -]+", cmd) and len(cmd) <= 3000, cmd
    (P / name).write_text(cmd + '\n')
print(json.dumps({'file': target.name, 'sha256': digest, 'bytes': target.stat().st_size,
                  'original': original, 'payload': payload_sha}, indent=2))
