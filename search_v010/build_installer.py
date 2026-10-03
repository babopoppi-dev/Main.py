from pathlib import Path
import base64
import hashlib
import json
import zlib

BASE=Path(__file__).resolve().parent
names=['agent.py','cg_tools.py','search_tools.py','search_schema.py']
tests=names+['file_tools.py','file_schema.py','isolated_shell.py','test_search.py','test_vps_agent.py']
package={key:{n:base64.b64encode((BASE/n).read_bytes()).decode() for n in files}
         for key,files in [('payload',names),('tests',tests)]}
data=base64.b64encode(zlib.compress(json.dumps(package).encode(),9)).decode()
template=(BASE/'upgrade_vps_template.py').read_text()
assert template.count('__PACKAGE__')==1
target=BASE/'upgrade_search_v010_20261002.py'
target.write_text(template.replace('__PACKAGE__',data))
compile(target.read_bytes(),str(target),'exec')
print(json.dumps({'file':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                 'payload':{n:hashlib.sha256((BASE/n).read_bytes()).hexdigest() for n in names}},indent=2))
