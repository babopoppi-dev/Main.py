"""Build the hash-pinned gateway activation (catalog only) for coordination v0.11 r1.

Deposit and execution go through admin_request with Telegram approval.
VPS and Mac agents are not modified by this script.
"""
from pathlib import Path
import ast
import base64
import hashlib
import json
import zlib

P=Path(__file__).resolve().parent
prev=P.parent/'search_v010'           # gateway sources live after search v0.10
names=['cg_tools.py','work_schema.py']
original={'cg_tools.py':hashlib.sha256((prev/'cg_tools.py').read_bytes()).hexdigest(),'work_schema.py':None}
deps={'cg_mcp.py':'f8a86b9a8424f9e6a0bc335f2951c8e9233750b62e1181379d9c6be3ebb04171',
      'file_schema.py':hashlib.sha256((prev/'file_schema.py').read_bytes()).hexdigest(),
      'search_schema.py':hashlib.sha256((prev/'search_schema.py').read_bytes()).hexdigest()}
assert hashlib.sha256((P.parent/'shell_v08'/'cg_mcp.py').read_bytes()).hexdigest()==deps['cg_mcp.py']
for n in ('file_schema.py','search_schema.py'):assert (P/n).read_bytes()==(prev/n).read_bytes(),n
sources={}
for n in names:
    text=(P/n).read_text()
    assert "'''" not in text and '\\' not in text and 'MCPEOF' not in text,n
    sources[n]=text
payload_sha={n:hashlib.sha256((P/n).read_bytes()).hexdigest() for n in names}
STAMP='coordination_v011r1_20261002'
header='''#!/usr/bin/env python3
"""Gateway catalog activation for coordination v0.11 r1. Telegram-approved admin_request only."""
import base64,contextlib,fcntl,hashlib,json,os,ssl,stat,subprocess,sys,tempfile,time,urllib.request,uuid,zlib
from pathlib import Path
BASE=Path('/opt/central-mcp-gateway')
SELF=BASE/'upgrade_gateway_%(s)s.py'
BACKUP=BASE/'backups/pre_%(s)s'
RECEIPT=BASE/'%(s)s_receipt.json'
GATEWAY='central-mcp-gateway-test.service'
PYTHON='/usr/bin/python3'
PAYLOAD={}
'''%{'s':STAMP}
header+='ORIGINAL='+repr(original)+'\nDEPENDENCIES='+repr(deps)+'\nPAYLOAD_SHA='+repr(payload_sha)+'\nSOURCES={\n'+''.join(repr(n)+": r'''"+t+"''',\n" for n,t in sources.items())+'}\n'
source=(P/'upgrade_vps_template.py').read_text()
reuse={'sha','trusted_directory','read','digest','atomic','record','run','rpc','call','backup','restore'}
functions='\n\n'.join(ast.get_source_segment(source,node) for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name in reuse)
target=P/('upgrade_gateway_'+STAMP+'.py')
target.write_text(header+'\n\n'+functions+'\n\n'+(P/'gateway_updater_body.py').read_text())
compile(target.read_bytes(),str(target),'exec')
data=target.read_bytes();digest=hashlib.sha256(data).hexdigest()
remote='/opt/central-mcp-gateway/'+target.name
staging='/var/lib/central-mcp-vps-agent-test/workspace/'+target.name
cmds={'ADMIN_REQUEST_1_deposito_gateway.txt':'install -o root -g root -m 0555 '+staging+' '+remote,
      'ADMIN_REQUEST_2_check_gateway.txt':'/usr/bin/python3 -I -B '+remote+' --check',
      'ADMIN_REQUEST_3_apply_gateway.txt':'/usr/bin/python3 -I -B '+remote+' --apply',
      'ADMIN_REQUEST_rollback_gateway.txt':'/usr/bin/python3 -I -B '+remote+' --rollback'}
import re
for name,cmd in cmds.items():
    assert re.fullmatch(r"[A-Za-z0-9_./:=@%+, -]+",cmd) and len(cmd)<=3000,cmd
    (P/name).write_text(cmd+'\n')
deposit=cmds['ADMIN_REQUEST_1_deposito_gateway.txt']
print(json.dumps({'file':target.name,'sha256':digest,'deposit_command_bytes':len(deposit),'original':original},indent=2))
