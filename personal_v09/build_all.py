from pathlib import Path
import base64,hashlib,json,zlib

p=Path(__file__).resolve().parent
def pack(names):
    return base64.b64encode(zlib.compress(json.dumps({n:(p/n).read_text() for n in names}).encode())).decode()
def sha(name):return hashlib.sha256((p/name).read_bytes()).hexdigest()
account=sha('bootstrap_account.py')
pre=['file_tools.py','shell_common.py','mac_guard.py','mac_policy.py','mac_child.py','mac_watchdog.py','mac_shell.py','preflight_worker.py','mac_clock.py']
s=(p/'preflight_installer_template.py').read_text().replace('__ACCOUNT_HASH__',account).replace('__PAYLOAD__',pack(pre))
(p/'preflight_installer.py').write_text(s)
agent=['file_tools.py','file_schema.py','shell_common.py','mac_guard.py','mac_clock.py','mac_policy.py','mac_child.py','mac_watchdog.py','mac_shell.py','agent_shell.py','mac_agent.py','selftest.py']
s=(p/'install_template.py').read_text().replace('__ACCOUNT_HASH__',account).replace('__PREFLIGHT_HASH__',sha('preflight_installer.py')).replace('__PAYLOAD__',pack(agent))
(p/'install_mac_agent.py').write_text(s)
s=(p/'setup_template.py').read_text().replace('__COMPONENTS__',pack(['bootstrap_account.py','preflight_installer.py','install_mac_agent.py']))
(p/'setup_personal.py').write_text(s)
print(json.dumps({n:{'bytes':(p/n).stat().st_size,'sha256':sha(n)} for n in ('bootstrap_account.py','preflight_installer.py','install_mac_agent.py','setup_personal.py')},indent=2))
