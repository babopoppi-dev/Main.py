import base64
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
payload = {}
for name in ['file_tools.py', 'file_schema.py', 'cg_tools.py', 'agent.py']:
    data = (root / name).read_bytes()
    payload[name] = {'data': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()}
source = (root / 'upgrade_files.py').read_text()
needle = 'PAYLOAD = {}  # Filled by build_installer.py, not taken from command arguments.'
assert source.count(needle) == 1
source = source.replace(needle, 'PAYLOAD = ' + repr(payload))
compile(source, 'upgrade_files_v07r2_20261002.py', 'exec')
target = root / 'upgrade_files_v07r2_20261002.py'
target.write_text(source)
print(json.dumps({'installer_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                  'files': {n: p['sha256'] for n, p in payload.items()}}))
