from pathlib import Path
import json,zlib,base64,hashlib
p=Path(__file__).resolve().parent
names=['file_tools.py','file_schema.py','shell_common.py','mac_guard.py','mac_clock.py','mac_policy.py','mac_child.py','mac_watchdog.py','mac_shell.py','agent_shell.py','mac_agent.py','selftest.py']
payload=base64.b64encode(zlib.compress(json.dumps({n:(p/n).read_text() for n in names}).encode())).decode()
s=(p/'install_template.py').read_text().replace('__PAYLOAD__',payload)
(p/'install_mac_agent.py').write_text(s)
print(json.dumps({'bytes':len(s.encode()),'sha256':hashlib.sha256(s.encode()).hexdigest()}))
