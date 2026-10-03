import base64
import hashlib
import json
from pathlib import Path

here=Path(__file__).resolve().parent
files={name:(here/name).read_bytes() for name in ('agent.py','cg_mcp.py','cg_tools.py','isolated_shell.py')}
payload={name:{'data':base64.b64encode(data).decode(),'sha256':hashlib.sha256(data).hexdigest()} for name,data in files.items()}
template=(here/'upgrade_shell.py').read_text()
out=template.replace('PAYLOAD = {}  # Embedded by build_installer.py.','PAYLOAD = '+repr(payload))
test_files={name:(here/name).read_bytes() for name in ('isolated_shell.py','probe_shell.py')}
test_files['file_tools.py']=(here.parent/'mcp-files-v07-20261002/file_tools.py').read_bytes()
tests={name:{'data':base64.b64encode(data).decode(),'sha256':hashlib.sha256(data).hexdigest()} for name,data in test_files.items()}
out=out.replace('TEST_PAYLOAD = {}  # Embedded preflight; never taken from a writable external file.','TEST_PAYLOAD = '+repr(tests))
target=here/'upgrade_shell_v08r3_20261002.py';target.write_text(out)
print(json.dumps({'file':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'payload':{n:v['sha256'] for n,v in payload.items()}}))
