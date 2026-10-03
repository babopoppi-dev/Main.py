import base64
import hashlib
import json
from pathlib import Path

here=Path(__file__).resolve().parent
files={name:(here/name).read_bytes() for name in ('isolated_shell.py','probe_shell.py')}
files['file_tools.py']=(here.parent/'mcp-files-v07-20261002/file_tools.py').read_bytes()
payload={name:{'base64':base64.b64encode(data).decode(),'sha256':hashlib.sha256(data).hexdigest()}
         for name,data in files.items()}
template=(here/'probe_installer.py').read_text()
out=template.replace('PAYLOAD = {}  # Embedded and hashed by build_probe.py.','PAYLOAD = '+repr(payload))
target=here/'probe_shell_v08r3_20261002.py'
target.write_text(out)
print(json.dumps({'file':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))
