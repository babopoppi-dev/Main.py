"""Build the hash-pinned gateway catalog activation v0.12 p2.

Live state: the v0.12 r1 gateway activation (a10e73e2, commit a1d98356), active
since 2026-10-03. Its logic is reused verbatim except for the payload (cg_tools.py
only: network profile 'packages' and shell_session list/processes), preflight
assertion, smoke expectations, temp prefix and unit name.
Deposit and execution go through admin_request with Telegram approval.
Agents are not modified by this script.
"""
from pathlib import Path
import hashlib
import json
import re

P = Path(__file__).resolve().parent
PREVIOUS = P / 'live_r1' / 'upgrade_gateway_v012_20261003.py'
assert hashlib.sha256(PREVIOUS.read_bytes()).hexdigest() == \
    'a10e73e20f79c2365eeb16a8ea4562ec899d99c7c0b5509024344625c6e87520'
STAMP = 'v012p2_20261003'
previous = PREVIOUS.read_text()
live = {}
exec(previous[:previous.index('def sha(data):')], live)
live_hash = {n: hashlib.sha256(t.encode()).hexdigest() for n, t in live['SOURCES'].items()}
assert live_hash == live['PAYLOAD_SHA']

names = ['cg_tools.py']
original = {n: live_hash[n] for n in names}
deps = dict(live['DEPENDENCIES'])
for n in ('file_schema.py', 'work_schema.py'):
    assert hashlib.sha256((P / n).read_bytes()).hexdigest() == live_hash[n], n
    deps[n] = live_hash[n]
assert hashlib.sha256((P / 'search_schema.py').read_bytes()).hexdigest() == deps['search_schema.py']
sources = {}
for n in names:
    text = (P / n).read_text()
    assert text.isascii() and "'''" not in text and '\\' not in text and 'MCPEOF' not in text, n
    sources[n] = text
payload_sha = {n: hashlib.sha256((P / n).read_bytes()).hexdigest() for n in names}
assert payload_sha != original

logic = previous[previous.index('def sha(data):'):]


def swap(old, new):
    global logic
    assert logic.count(old) == 1, old
    logic = logic.replace(old, new)


swap("prefix='mcp-v012-gw-'", "prefix='mcp-v012p2-gw-'")
swap("""'assert t["enable_full_shell"]["inputSchema"]["properties"]["network"]["enum"]==["none","github"];print(len(n))')""",
     """'assert t["enable_full_shell"]["inputSchema"]["properties"]["network"]["enum"]==["none","github","packages"];'
              'assert "processes" in t["shell_session"]["description"];print(len(n))')""")
start = logic.index('def smoke(expect_new):')
end = logic.index('def install(manifest):')
logic = logic[:start] + '''def smoke(expect_p2):
    tools={t['name']:t for t in rpc('tools/list',{})['tools']}
    if not {'work_session','work_lock'}<=set(tools) or not NEW_TOOLS<=set(tools):raise RuntimeError('v0.12 tools missing')
    enum=tools['enable_full_shell']['inputSchema']['properties']['network']['enum']
    if enum!=(['none','github','packages'] if expect_p2 else ['none','github']):raise RuntimeError('unexpected network profiles')
    if ('processes' in tools['shell_session']['description'])!=expect_p2:raise RuntimeError('unexpected shell_session actions')
    if 'work_session_id' not in tools['delete_path']['inputSchema']['properties']:raise RuntimeError('session parameters missing')
    if call('shell_exec',machine='vps',command='uname -a')['exit_code']!=0:raise RuntimeError('vps baseline failed')
    idle()
    return ['catalog '+('p2 (packages, processes)' if expect_p2 else 'r1'),'vps baseline','vps and mac_mio idle']


''' + logic[end:]
swap("'--unit=central-mcp-v012-20261003'", "'--unit=central-mcp-v012p2-20261003'")

header = '''#!/usr/bin/env python3
"""Gateway catalog activation for MCP Andrea v0.12 p2. Telegram-approved admin_request only."""
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
cmds = {'ADMIN_REQUEST_G0_hash_deposito_gateway.txt': 'sha256sum ' + staging,
        'ADMIN_REQUEST_G1_deposito_gateway.txt': 'install -o root -g root -m 0555 ' + staging + ' ' + remote,
        'ADMIN_REQUEST_G2_check_gateway.txt': '/usr/bin/python3 -I -B ' + remote + ' --check',
        'ADMIN_REQUEST_G3_apply_gateway.txt': '/usr/bin/python3 -I -B ' + remote + ' --apply',
        'ADMIN_REQUEST_G4_ricevuta_gateway.txt': 'cat /opt/central-mcp-gateway/' + STAMP + '_receipt.json',
        'ADMIN_REQUEST_G_rollback_gateway.txt': '/usr/bin/python3 -I -B ' + remote + ' --rollback'}
for name, cmd in cmds.items():
    assert re.fullmatch(r"[A-Za-z0-9_./:=@%+, -]+", cmd) and len(cmd) <= 3000, cmd
    (P / name).write_text(cmd + '\n')
print(json.dumps({'file': target.name, 'sha256': digest, 'bytes': target.stat().st_size,
                  'original': original, 'payload': payload_sha}, indent=2))
