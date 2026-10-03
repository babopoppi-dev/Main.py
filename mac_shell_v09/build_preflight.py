from pathlib import Path
import base64, hashlib, json, zlib
base=Path(__file__).resolve().parent
names=['file_tools.py','shell_common.py','mac_guard.py','mac_policy.py','mac_child.py','mac_watchdog.py','mac_shell.py','preflight_worker.py','mac_clock.py']
payload=base64.b64encode(zlib.compress(json.dumps({n:(base/n).read_text() for n in names}).encode())).decode()
source=(base/'preflight_installer_template.py').read_text().replace('__PAYLOAD__',payload)
(base/'preflight_installer.py').write_text(source)
print(json.dumps({'file':'preflight_installer.py','sha256':hashlib.sha256(source.encode()).hexdigest(),'bytes':len(source.encode())}))
