from pathlib import Path
import hashlib

root=Path(__file__).resolve().parent
profile=(root/'mcp-andrea-bwrap').read_bytes()
source=(root/'install_isolation.py').read_text()
needle="PROFILE_BYTES = b''  # Pinned by build_installer.py."
assert source.count(needle)==1
source=source.replace(needle,'PROFILE_BYTES = '+repr(profile))
compile(source,'install_isolation_20261002.py','exec')
target=root/'install_isolation_20261002.py'
target.write_text(source)
print('installer_sha256',hashlib.sha256(target.read_bytes()).hexdigest())
