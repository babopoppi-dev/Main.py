#!/usr/bin/env python3
"""Gateway catalog update v0.14 (shell network flag). Telegram-approved admin_request only."""
import base64,contextlib,fcntl,hashlib,json,os,ssl,stat,subprocess,sys,tempfile,time,urllib.request,uuid,zlib
from pathlib import Path
BASE=Path('/opt/central-mcp-gateway')
SELF=BASE/'upgrade_gateway_v014_20261003.py'
BACKUP=BASE/'backups/pre_v014_20261003'
RECEIPT=BASE/'v014_20261003_receipt.json'
GATEWAY='central-mcp-gateway-test.service'
PYTHON='/usr/bin/python3'
PAYLOAD={}
ORIGINAL={'cg_tools.py': '9e216e48d7761bedcbfc33cb1f1b6298a1a92866778992d2630e84726ffff2fa', 'network_schema.py': None}
DEPENDENCIES={'cg_mcp.py': 'f8a86b9a8424f9e6a0bc335f2951c8e9233750b62e1181379d9c6be3ebb04171', 'file_schema.py': '06e579c359835daa58876d7e5de21d26ad374992fb76d9104dd1d6dd929409eb', 'search_schema.py': 'c6d111d440eec78bb08e27673fd832479f02446ac2abc25fb5237e12d47ee20d', 'work_schema.py': '9204940d1c304ca41236785b2248c449a93f8102fcd1e15fae4d76c478db9ee9', 'admin_schema.py': 'a11e96523aa9571a3b64b4df9567d9b6d72f15fe6e4f09e39e2a19b4b13c5a03', 'process_schema.py': 'b885baebf9f3d20cc00131a111945f64ff8678a3f3ce5f5b71917ed6d9a91849'}
PAYLOAD_SHA={'cg_tools.py': 'a1d14ada34695f6c1012128a1136ca9785f0b2355d3f95a39c660906f068e89f', 'network_schema.py': '498e8f74f375806a429b6b0357bdbbb9d1836694764f541ea38d2ed9524be680'}
SOURCES={
'cg_tools.py': r'''TOOLS=[{'name': 'list_machines', 'description': 'List registered machines and online status.', 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}, {'name': 'shell_exec', 'description': 'Execute a command. VPS arbitrary commands need a temporary isolated-shell lease; network is disabled and access is limited to its workspace. Long commands return a session_id; poll shell_session read. Baseline status commands work without enabling.', 'inputSchema': {'type': 'object', 'required': ['machine', 'command'], 'properties': {'machine': {'type': 'string'}, 'command': {'type': 'string'}, 'cwd': {'type': 'string'}, 'timeout': {'type': 'number'}}}}, {'name': 'shell_session', 'description': 'Manage an isolated PTY: start/send/read/stop. Session belongs to its OAuth authorization. VPS allows one active workspace session; disable/expiry stops descendants. Read may return has_more.', 'inputSchema': {'type': 'object', 'required': ['machine', 'action'], 'properties': {'machine': {'type': 'string'}, 'action': {'type': 'string'}, 'session_id': {'type': 'string'}, 'command': {'type': 'string'}, 'data': {'type': 'string'}}}}, {'name': 'read_file', 'description': 'Read file through agent.', 'inputSchema': {'type': 'object', 'required': ['machine', 'path'], 'properties': {'machine': {'type': 'string'}, 'path': {'type': 'string'}, 'max_bytes': {'type': 'integer'}}}}, {'name': 'write_file', 'description': 'Write file with rollback operation id.', 'inputSchema': {'type': 'object', 'required': ['machine', 'path', 'content'], 'properties': {'machine': {'type': 'string'}, 'path': {'type': 'string'}, 'content': {'type': 'string'}}}}, {'name': 'rollback_file', 'description': 'Rollback write operation.', 'inputSchema': {'type': 'object', 'required': ['machine', 'operation_id'], 'properties': {'machine': {'type': 'string'}, 'operation_id': {'type': 'string'}}}}, {'name': 'enable_full_shell', 'description': 'Acquire a temporary shell lease for the authenticated authorization. Available only on machines with verified containment; VPS shell is workspace-only and offline. Multiple chats can share the same authorization.', 'inputSchema': {'type': 'object', 'required': ['machine', 'minutes'], 'properties': {'machine': {'type': 'string'}, 'minutes': {'type': 'integer', 'minimum': 1, 'maximum': 240}}}}, {'name': 'disable_full_shell', 'description': 'Disable temporary shell access and terminate its active sessions and descendants.', 'inputSchema': {'type': 'object', 'required': ['machine'], 'properties': {'machine': {'type': 'string'}}}}, {'name': 'who_is_working', 'description': 'Show active cross-session locks and recent operations on a Mac.', 'inputSchema': {'type': 'object', 'required': ['machine'], 'properties': {'machine': {'type': 'string'}}}}, {'name': 'xcode_list', 'description': 'List the Xcode container and simulators on a Mac.', 'inputSchema': {'type': 'object', 'required': ['machine'], 'properties': {'machine': {'type': 'string'}, 'project': {'type': 'string'}, 'workspace': {'type': 'string'}}}}, {'name': 'xcode_build', 'description': 'Build an Xcode project on a Mac (validated parameters; operation=test for the QA suite).', 'inputSchema': {'type': 'object', 'required': ['machine', 'scheme', 'configuration', 'destination'], 'properties': {'machine': {'type': 'string'}, 'project': {'type': 'string'}, 'workspace': {'type': 'string'}, 'scheme': {'type': 'string'}, 'configuration': {'type': 'string'}, 'destination': {'type': 'string'}, 'operation': {'type': 'string'}, 'action': {'type': 'string'}, 'job_id': {'type': 'string'}, 'result_name': {'type': 'string'}}}}, {'name': 'xcode_test', 'description': 'Run the fixed La Marruca QA tests on a Mac (start/status/artifacts).', 'inputSchema': {'type': 'object', 'required': ['machine', 'project', 'scheme', 'configuration', 'destination'], 'properties': {'machine': {'type': 'string'}, 'project': {'type': 'string'}, 'scheme': {'type': 'string'}, 'configuration': {'type': 'string'}, 'destination': {'type': 'string'}, 'action': {'type': 'string'}, 'job_id': {'type': 'string'}, 'result_name': {'type': 'string'}}}}, {'name': 'admin_request', 'description': 'Request execution of an administrator (root) command on the VPS. The exact command is sent to Andrea on Telegram; it runs only after he approves. Returns a request_id: poll admin_result.', 'inputSchema': {'type': 'object', 'required': ['command', 'reason'], 'properties': {'command': {'type': 'string'}, 'reason': {'type': 'string'}}}}, {'name': 'admin_result', 'description': 'Get status/output of an admin_request (waiting, done, rejected, expired, error).', 'inputSchema': {'type': 'object', 'required': ['request_id'], 'properties': {'request_id': {'type': 'string'}}}}]
NAMES={x["name"] for x in TOOLS}

from file_schema import install_schema
TOOLS=install_schema(TOOLS)
NAMES={x['name'] for x in TOOLS}

from search_schema import SEARCH_TOOLS, SEARCH_NAMES
TOOLS = [t for t in TOOLS if t['name'] not in SEARCH_NAMES] + SEARCH_TOOLS
NAMES = {t['name'] for t in TOOLS}

from work_schema import install_schema as install_work_schema
TOOLS = install_work_schema(TOOLS)
NAMES = {t["name"] for t in TOOLS}

from admin_schema import install_schema as install_admin_schema
TOOLS = install_admin_schema(TOOLS)
NAMES = {t["name"] for t in TOOLS}

from process_schema import install_schema as install_process_schema
TOOLS = install_process_schema(TOOLS)
NAMES = {t["name"] for t in TOOLS}

from network_schema import install_schema as install_network_schema
TOOLS = install_network_schema(TOOLS)
NAMES = {t["name"] for t in TOOLS}
''',
'network_schema.py': r'''"""Gateway catalog change for point F: optional network flag on enable_full_shell (personal Mac only)."""
import copy

NETWORK_PROPERTY = {'type': 'boolean',
                    'description': 'Personal Mac only: also allow HTTPS through the allowlist proxy '
                                   '(domains listed by list_machines network_domains). Default false.'}


def install_schema(tools):
    out = copy.deepcopy(tools)
    for t in out:
        if t['name'] == 'enable_full_shell':
            t['inputSchema'].setdefault('properties', {})['network'] = copy.deepcopy(NETWORK_PROPERTY)
    return out
''',
}


def sha(data):return hashlib.sha256(data).hexdigest()

def trusted_directory(path):
    for p in [path]+list(path.parents):
        st=p.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
            raise RuntimeError('untrusted directory: '+str(p))

def read(path, owner=0):
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=owner or st.st_mode&0o022 or st.st_nlink!=1:
            raise RuntimeError('unsafe file: '+str(path))
        data=f.read(2*1024*1024+1)
    if len(data)>2*1024*1024:raise RuntimeError('file exceeds limit')
    return data

def digest(path):
    if path.is_symlink():raise RuntimeError('symlink destination rejected')
    return sha(read(path)) if path.exists() else None

def atomic(path,data,mode=0o644,uid=0,gid=0):
    trusted_directory(path.parent)
    if path.is_symlink():raise RuntimeError('symlink destination rejected')
    fd,name=tempfile.mkstemp(prefix='.search-v010-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchown(f.fileno(),uid,gid);os.fchmod(f.fileno(),mode)
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,str(path))
        dfd=os.open(str(path.parent),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:
        if os.path.exists(name):os.unlink(name)

def record(status,**fields):
    atomic(RECEIPT,json.dumps(dict(status=status,time=time.time(),**fields),indent=2).encode())

def run(argv,timeout=30):
    return subprocess.run(argv,check=True,capture_output=True,text=True,timeout=timeout,
                          env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C.UTF-8'})

def rpc(method,params):
    cfg=json.loads(read(Path('/etc/central-mcp-gateway/gateway-test.json')))
    ctx=ssl.create_default_context(cafile=cfg['tls_cert']);ctx.check_hostname=False
    token=read(Path(cfg['mcp_token_file'])).decode().strip()
    req=urllib.request.Request('https://127.0.0.1:'+str(cfg['port'])+'/mcp',
        data=json.dumps({'jsonrpc':'2.0','id':uuid.uuid4().hex,'method':method,'params':params}).encode(),
        headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
    with urllib.request.urlopen(req,context=ctx,timeout=10) as r:out=json.load(r)
    if 'error' in out:raise RuntimeError('local MCP request failed')
    return out['result']

def call(name,**args):
    value=rpc('tools/call',{'name':name,'arguments':args})
    if value.get('isError'):raise RuntimeError(name+': '+value['content'][0]['text'][:300])
    return json.loads(value['content'][0]['text'])

def backup():
    trusted_directory(BACKUP.parent)
    BACKUP.mkdir(mode=0o700)
    manifest={}
    for name in ORIGINAL:
        path=BASE/name
        if ORIGINAL[name] is None:manifest[name]=None;continue
        data=read(path);st=path.lstat()
        manifest[name]={'sha256':sha(data),'mode':stat.S_IMODE(st.st_mode),'uid':st.st_uid,'gid':st.st_gid}
        atomic(BACKUP/name,data,0o600)
    atomic(BACKUP/'manifest.json',json.dumps(manifest,indent=2).encode(),0o600)
    return manifest

def restore(strict=True):
    manifest=json.loads(read(BACKUP/'manifest.json'))
    if set(manifest)!=set(ORIGINAL):raise RuntimeError('unexpected backup manifest')
    # Check every destination and every backup before restoring any file.
    for name,old in ORIGINAL.items():
        current=digest(BASE/name)
        accepted={sha(PAYLOAD[name])} if strict else {old,sha(PAYLOAD[name])}
        if current not in accepted:raise RuntimeError('rollback conflict: '+name)
        if old is not None:
            if not manifest[name] or sha(read(BACKUP/name))!=old or manifest[name]['sha256']!=old:
                raise RuntimeError('backup mismatch: '+name)
    for name,meta in manifest.items():
        if meta is None:
            if (BASE/name).exists():(BASE/name).unlink()
        else:atomic(BASE/name,read(BACKUP/name),meta['mode'],meta['uid'],meta['gid'])

"""Appended to the gateway activation by build_gateway_activation.py."""


def idle():
    for machine in ('vps','mac_mio'):
        state=call('who_is_working',machine=machine)
        if state.get('active_locks') or state.get('shell_enabled') or state.get('work_locks'):
            raise RuntimeError(machine+' busy; active locks or shell authorization present')


def validate():
    if BACKUP.exists() or BACKUP.is_symlink():raise RuntimeError('backup already exists; inspect receipt before retry')
    trusted_directory(BASE)
    for name,expected in {**ORIGINAL,**DEPENDENCIES}.items():
        if digest(BASE/name)!=expected:raise RuntimeError('live source changed: '+name)
    if run(['systemctl','show',GATEWAY,'-p','User','--value']).stdout.strip()!='mcp-gateway':
        raise RuntimeError('gateway identity changed')
    if run(['systemctl','is-active',GATEWAY]).stdout.strip()!='active':raise RuntimeError('gateway not active')
    idle()
    return {'check_passed':True,'gateway':GATEWAY,'agents_touched':False}


def load_package():
    global PAYLOAD
    PAYLOAD={n:src.encode() for n,src in SOURCES.items()}
    if set(PAYLOAD)!=set(ORIGINAL) or {n:sha(b) for n,b in PAYLOAD.items()}!=PAYLOAD_SHA:
        raise RuntimeError('unexpected payload')
    for name,data in PAYLOAD.items():compile(data,name,'exec')


def preflight():
    # Import the new catalog next to the live dependencies, outside BASE.
    with tempfile.TemporaryDirectory(prefix='gw-v014-') as tmp:
        for name,data in PAYLOAD.items():Path(tmp,name).write_bytes(data)
        for name in DEPENDENCIES:Path(tmp,name).write_bytes(read(BASE/name))
        code=('import sys;sys.path.insert(0,'+repr(tmp)+');import cg_tools as c;'
              'n=[t["name"] for t in c.TOOLS];assert len(n)==len(set(n))==len(c.NAMES);'
              'assert {"work_session","work_lock","write_file","start_search","admin_request"}<=c.NAMES;'
              't={x["name"]:x for x in c.TOOLS};'
              'assert "work_session_id" in t["write_file"]["inputSchema"]["properties"];'
              'assert "work_session_id" not in t["admin_request"]["inputSchema"]["properties"];'
              'assert {"mac_admin_request","mac_admin_result"}<=c.NAMES;'
              'assert {"process_list","process_stop"}<=c.NAMES;'
              'assert t["process_stop"]["inputSchema"]["properties"]["machine"]["enum"]==["mac_mio"];'
              'assert t["enable_full_shell"]["inputSchema"]["properties"]["network"]["type"]=="boolean";print(len(n))')
        r=subprocess.run([PYTHON,'-I','-B','-c',code],capture_output=True,text=True,timeout=30,cwd=tmp,
                         env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
        if r.returncode:raise RuntimeError('catalog preflight failed: '+r.stderr[-800:])
        return int(r.stdout.strip())


def restart():
    run(['systemctl','restart',GATEWAY],90)
    end=time.monotonic()+45
    while time.monotonic()<end:
        try:
            machines={m['machine']:m for m in call('list_machines')['machines']}
            if machines['vps']['online'] and machines['mac_mio']['online']:return
        except Exception:pass
        time.sleep(1)
    raise RuntimeError('gateway or agent reconnection check failed')


def smoke(expect_work):
    tools={t['name']:t for t in rpc('tools/list',{})['tools']}
    if not {'work_session','work_lock','mac_admin_request','mac_admin_result','process_list','process_stop'}<=set(tools):raise RuntimeError('tools missing')
    present='network' in tools['enable_full_shell']['inputSchema'].get('properties',{})
    if present!=expect_work:raise RuntimeError('unexpected enable_full_shell schema')
    if call('shell_exec',machine='vps',command='uname -a')['exit_code']!=0:raise RuntimeError('vps baseline failed')
    idle()
    return ['catalog '+('with' if expect_work else 'without')+' shell network flag','vps baseline','vps and mac_mio idle']


def install(manifest):
    for name,data in PAYLOAD.items():
        meta=manifest[name] or {'mode':manifest['cg_tools.py']['mode'],'uid':manifest['cg_tools.py']['uid'],
                                'gid':manifest['cg_tools.py']['gid']}
        atomic(BASE/name,data,meta['mode'],meta['uid'],meta['gid'])


def maintenance_lock(fd,action):
    # Detached activations wait for each other (gateway and VPS agent share the
    # lock) instead of failing; interactive actions never wait.
    end=time.monotonic()+(240 if action=='--activate' else 0)
    while True:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);return
        except BlockingIOError:
            if time.monotonic()>=end:raise RuntimeError('another maintenance is running; retry later')
            time.sleep(2)


def main(action):
    load_package()
    if os.getuid()!=0 or os.geteuid()!=0 or Path(__file__).resolve()!=SELF:
        raise RuntimeError('installed root helper required; run through admin_request after Telegram approval')
    trusted_directory(BASE);own=sha(read(SELF));os.umask(0o077)
    fd=os.open('/run/lock/mcp-andrea-files-maintenance.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        maintenance_lock(fd,action)
        if action=='--check':
            result=validate();result['catalog_tools']=preflight();result['helper_sha256']=own
            print(json.dumps(result,indent=2));return
        if action=='--apply':
            # Detach from the approval runner before the gateway restarts.
            validate();preflight()
            run(['systemd-run','--unit=central-mcp-gateway-v014-20261003','--on-active=5s','--collect',
                 PYTHON,'-I','-B',str(SELF),'--activate'])
            record('activation_scheduled');print(json.dumps({'status':'activation_scheduled','receipt':str(RECEIPT)}));return
        if action=='--activate':
            validate();count=preflight();validate()
            manifest=backup();installed=False
            try:
                install(manifest);installed=True
                restart();checks=smoke(True)
                record('active',checks=checks,catalog_tools=count,backup=str(BACKUP),
                       hashes={n:sha(b) for n,b in PAYLOAD.items()},agents_touched=False)
                print(json.dumps({'status':'active','checks':checks},indent=2))
            except Exception as error:
                try:
                    restore(strict=False)
                    if installed:restart()
                    record('rolled_back',reason=str(error)[:1200])
                except Exception as rollback:
                    record('rollback_requires_review',reason=str(error)[:1200],rollback_error=str(rollback)[:1200])
                raise
        elif action=='--rollback':
            idle();restore();restart();checks=smoke(False)
            record('rolled_back',reason='approved rollback',checks=checks)
            print(json.dumps({'status':'rolled_back','checks':checks}))
        else:raise ValueError('use --check, --apply or --rollback')
    finally:os.close(fd)


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('one action required')
    main(sys.argv[1])
