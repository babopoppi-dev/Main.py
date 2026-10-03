"""Build the reviewed v0.7 approver update from the previously used helper."""
import base64
import hashlib
from pathlib import Path

base = Path(__file__).resolve().parent
previous = base.parent / 'mcp-approver-20261002'
old = (previous / 'approver.py').read_bytes()
new = (base / 'approver.py').read_bytes()
old_hash = hashlib.sha256(old).hexdigest()
assert old_hash == '85bcdce1a05ae06bde9c9a85c3bd4e938ed47ff26f3db4f30f932d83f2db60dc'
new_hash = hashlib.sha256(new).hexdigest()
source = (previous / 'upgrade_approver.py').read_text()
lines = []
for line in source.splitlines():
    if line.startswith('ORIGINAL_SHA='):
        line = 'ORIGINAL_SHA=' + repr(old_hash)
    elif line.startswith('CANDIDATE_SHA='):
        line = 'CANDIDATE_SHA=' + repr(new_hash)
    elif line.startswith('PAYLOAD='):
        line = 'PAYLOAD=' + repr(base64.b64encode(new).decode())
    else:
        line = line.replace('v06', 'v07r2').replace('v0.6', 'v0.7')
        line = line.replace('for _ in range(20):', 'for _ in range(120):')
        line = line.replace("restart_and_check('approver avviato v0.7')",
                            "restart_and_check('approver pronto v0.7')")
    lines.append(line)
source = '\n'.join(lines) + '\n'
compile(source, 'upgrade_approver.py', 'exec')
(base / 'upgrade_approver.py').write_text(source)
(base / 'upgrade_approver_v07r2_20261002.py').write_text(source)
(base / 'test_upgrade.py').write_text(
    (previous / 'test_upgrade.py').read_text().replace('v0.6', 'v0.7'))
print('candidate_sha256', new_hash)
print('installer_sha256', hashlib.sha256(source.encode()).hexdigest())
