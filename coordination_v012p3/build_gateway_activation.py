"""Build the hash-pinned gateway catalog activation v0.12 p3.

Live state: the v0.12 p2 gateway activation (43c63ff8, commit 3ad45a8), active
since 2026-10-03. Its logic is reused verbatim except for the payload
(cg_tools.py + new admin_schema.py: mac_admin_request and mac_admin_result for
mac_mio), preflight assertions, smoke expectations, temp prefix and unit name.
cg_mcp.py is unchanged: it forwards the two tools to the mac_mio agent.
Deposit and execution go through admin_request with Telegram approval.
Agents are not modified by this script.
"""
from pathlib import Path
import hashlib
import json
import re

P = Path(__file__).resolve().parent
PREVIOUS = P.parent / 'coordination_v012p2' / 'upgrade_gateway_v012p2_20261003.py'
assert hashlib.sha256(PREVIOUS.read_bytes()).hexdigest() == \
    '43c63ff86aed474a7ba3c26282798ea74f64fcd2ab560345b4c74a28b1457368'
STAMP = 'v012p3_20261003'
import sys
COMMIT = sys.argv[1] if len(sys.argv) > 1 else 'COMMIT_DA_FISSARE'
assert COMMIT == 'COMMIT_DA_FISSARE' or re.fullmatch('[0-9a-f]{40}', COMMIT), COMMIT
previous = PREVIOUS.read_text()
live = {}
exec(previous[:previous.index('def sha(data):')], live)
live_hash = {n: hashlib.sha256(t.encode()).hexdigest() for n, t in live['SOURCES'].items()}
assert live_hash == live['PAYLOAD_SHA']

names = ['cg_tools.py', 'admin_schema.py']
original = {'cg_tools.py': live_hash['cg_tools.py'], 'admin_schema.py': None}
deps = dict(live['DEPENDENCIES'])
for n in ('file_schema.py', 'work_schema.py', 'search_schema.py'):
    assert hashlib.sha256((P / n).read_bytes()).hexdigest() == deps[n], n
assert (P / 'admin_schema.py').read_bytes() == (P.parent / 'mac_v012' / 'admin_schema.py').read_bytes()
sources = {}
for n in names:
    text = (P / n).read_text()
    assert text.isascii() and "'''" not in text and '\\' not in text and 'MCPEOF' not in text, n
    sources[n] = text
payload_sha = {n: hashlib.sha256((P / n).read_bytes()).hexdigest() for n in names}
assert payload_sha['cg_tools.py'] != original['cg_tools.py']

logic = previous[previous.index('def sha(data):'):]


def swap(old, new):
    global logic
    assert logic.count(old) == 1, old
    logic = logic.replace(old, new)


swap("prefix='mcp-v012p2-gw-'", "prefix='mcp-v012p3-gw-'")
swap("""'assert "processes" in t["shell_session"]["description"];print(len(n))')""",
     """'assert "processes" in t["shell_session"]["description"];'
              'assert {"mac_admin_request","mac_admin_result"}<=c.NAMES;'
              'assert t["mac_admin_request"]["inputSchema"]["properties"]["machine"]["enum"]==["mac_mio"];'
              'assert {"work_session_id","work_session_token"}<=set(t["mac_admin_request"]["inputSchema"]["required"]);'
              'assert "work_session_id" not in t["mac_admin_result"]["inputSchema"]["properties"];print(len(n))')""")
start = logic.index('def smoke(expect_p2):')
end = logic.index('def install(manifest):')
logic = logic[:start] + '''ADMIN_TOOLS={'mac_admin_request','mac_admin_result'}


def smoke(expect_p3):
    tools={t['name']:t for t in rpc('tools/list',{})['tools']}
    if not {'work_session','work_lock'}<=set(tools) or not NEW_TOOLS<=set(tools):raise RuntimeError('v0.12 tools missing')
    if tools['enable_full_shell']['inputSchema']['properties']['network']['enum']!=['none','github','packages']:
        raise RuntimeError('unexpected network profiles')
    if 'processes' not in tools['shell_session']['description']:raise RuntimeError('unexpected shell_session actions')
    if 'work_session_id' not in tools['delete_path']['inputSchema']['properties']:raise RuntimeError('session parameters missing')
    if ADMIN_TOOLS&set(tools)!=(ADMIN_TOOLS if expect_p3 else set()):raise RuntimeError('unexpected Mac admin tools')
    if call('shell_exec',machine='vps',command='uname -a')['exit_code']!=0:raise RuntimeError('vps baseline failed')
    idle()
    return ['catalog '+('p3 (Mac admin via Telegram)' if expect_p3 else 'p2'),'vps baseline','vps and mac_mio idle']


''' + logic[end:]
swap("'--unit=central-mcp-v012p2-20261003'", "'--unit=central-mcp-v012p3-20261003'")

header = '''#!/usr/bin/env python3
"""Gateway catalog activation for MCP Andrea v0.12 p3. Telegram-approved admin_request only."""
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
url = 'https://raw.githubusercontent.com/babopoppi-dev/Main.py/' + COMMIT + '/coordination_v012p3/' + target.name
# admin_request runs argv without a shell: one command per request.
cmds = {'ADMIN_REQUEST_G1_download_gateway.txt': '/usr/bin/curl -fsS --proto =https --max-time 60 -o ' + remote + ' ' + url,
        'ADMIN_REQUEST_G1b_hash_gateway.txt': 'sha256sum ' + remote,
        'ADMIN_REQUEST_G2_check_gateway.txt': '/usr/bin/python3 -I -B ' + remote + ' --check',
        'ADMIN_REQUEST_G3_apply_gateway.txt': '/usr/bin/python3 -I -B ' + remote + ' --apply',
        'ADMIN_REQUEST_G4_ricevuta_gateway.txt': 'cat /opt/central-mcp-gateway/' + STAMP + '_receipt.json',
        'ADMIN_REQUEST_G_rollback_gateway.txt': '/usr/bin/python3 -I -B ' + remote + ' --rollback'}
for name, cmd in cmds.items():
    assert re.fullmatch(r"[A-Za-z0-9_./:=@%+, -]+", cmd) and len(cmd) <= 3000, cmd
    (P / name).write_text(cmd + '\n')
print(json.dumps({'file': target.name, 'sha256': digest, 'bytes': target.stat().st_size,
                  'original': original, 'payload': payload_sha}, indent=2))
