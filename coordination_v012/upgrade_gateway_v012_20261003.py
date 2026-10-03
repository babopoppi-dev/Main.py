#!/usr/bin/env python3
"""Gateway catalog activation for MCP Andrea v0.12. Telegram-approved admin_request only."""
import base64,contextlib,fcntl,hashlib,json,os,ssl,stat,subprocess,sys,tempfile,time,urllib.request,uuid,zlib
from pathlib import Path
BASE=Path('/opt/central-mcp-gateway')
SELF=BASE/'upgrade_gateway_v012_20261003.py'
BACKUP=BASE/'backups/pre_v012_20261003'
RECEIPT=BASE/'v012_20261003_receipt.json'
GATEWAY='central-mcp-gateway-test.service'
PYTHON='/usr/bin/python3'
PAYLOAD={}
ORIGINAL={'cg_tools.py': '8282e608be40003e9475dc789ddf7d90e8676aa88776d9f8b3923b33087d02a1', 'file_schema.py': '06e579c359835daa58876d7e5de21d26ad374992fb76d9104dd1d6dd929409eb', 'work_schema.py': '9204940d1c304ca41236785b2248c449a93f8102fcd1e15fae4d76c478db9ee9'}
DEPENDENCIES={'cg_mcp.py': 'f8a86b9a8424f9e6a0bc335f2951c8e9233750b62e1181379d9c6be3ebb04171', 'search_schema.py': 'c6d111d440eec78bb08e27673fd832479f02446ac2abc25fb5237e12d47ee20d'}
PAYLOAD_SHA={'cg_tools.py': '0df2f955e3de20a5fb13565fcb347c52c8c738963f8c418de0873dc0c123fbd1', 'file_schema.py': 'a981512019127689a443ca2717968d76e1509f4366075d5b39f6eee28218c1a4', 'work_schema.py': '40eaf6a37998e42d9cdd6e3c28853e1f22cfeff1fc9b16bec8d391abc04817df'}
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

# v0.12: optional GitHub-only network for the Mac shell lease.
for _t in TOOLS:
    if _t['name'] == 'enable_full_shell':
        _t['inputSchema']['properties']['network'] = {'type': 'string', 'enum': ['none', 'github', 'packages'], 'default': 'none'}
        _t['description'] += " On mac_mio, network='github' lets the shell reach only GitHub over HTTPS through the agent proxy; 'packages' adds pypi and the npm registry; default 'none'."
    if _t['name'] == 'shell_session':
        _t['description'] += " Actions: start, send, read, stop, list (this session's processes), processes (uid5000 inventory, mac_mio). On mac_mio up to 4 processes run concurrently in one lease."
''',
'file_schema.py': r'''"""MCP file interface. Routing machine is always required; identity is internal."""
def tool(name, description, fields, required):
    return {'name': name, 'description': description, 'inputSchema': {
        'type': 'object', 'additionalProperties': False,
        'required': ['machine'] + required,
        'properties': {'machine': {'type': 'string', 'enum': ['vps', 'mac_noleggio', 'mac_mio']}, **fields}}}


PATH = {'type': 'string', 'description': 'Absolute path within the allowed project roots.'}
FILE_TOOLS = [
    tool('read_file', 'Read UTF-8 text in allowed roots; offset/length select lines, max_bytes selects bytes. Do not combine the two modes. Negative offset reads from the end.',
         {'path': PATH, 'offset': {'type': 'integer', 'default': 0},
          'length': {'type': 'integer', 'minimum': 0, 'maximum': 10000, 'default': 1000},
          'max_bytes': {'type': 'integer', 'minimum': 1, 'maximum': 524288}}, ['path']),
    tool('read_multiple_files', 'Read up to 20 text files; each result has its own success or error.',
         {'paths': {'type': 'array', 'items': PATH, 'minItems': 1, 'maxItems': 20}}, ['paths']),
    tool('write_file', 'Write text with durable rollback. Append bounded chunks to build a larger file.',
         {'path': PATH, 'content': {'type': 'string'},
          'mode': {'type': 'string', 'enum': ['rewrite', 'append'], 'default': 'rewrite'}}, ['path', 'content']),
    tool('edit_block', 'Replace exact text only when occurrence count matches; otherwise leave file unchanged.',
         {'file_path': PATH, 'old_string': {'type': 'string', 'minLength': 1},
          'new_string': {'type': 'string'},
          'expected_replacements': {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'default': 1}},
         ['file_path', 'old_string', 'new_string']),
    tool('list_directory', 'Bounded recursive listing with [FILE] and [DIR] prefixes; links are not followed.',
         {'path': PATH, 'depth': {'type': 'integer', 'minimum': 0, 'maximum': 8, 'default': 2}}, ['path']),
    tool('create_directory', 'Create intermediate directories with persistent rollback.', {'path': PATH}, ['path']),
    tool('move_file', 'Move or rename a regular file without replacing an existing destination; persistent rollback.',
         {'source': PATH, 'destination': PATH}, ['source', 'destination']),
    tool('get_file_info', 'Get size, permissions, timestamps and text line count; unavailable birth time is null.',
         {'path': PATH}, ['path']),
    tool('rollback_file', 'Undo a committed operation if its resulting files have not changed; persistent across restarts.',
         {'operation_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'}}, ['operation_id']),
    tool('delete_path', 'Delete a file or a directory tree (max 500 entries, no links) with persistent rollback; requires a covering work lock.',
         {'path': PATH}, ['path']),
    tool('copy_file', 'Copy a file or directory tree to a new destination (no overwrite, max 500 entries and 64 MiB) with persistent rollback.',
         {'source': PATH, 'destination': PATH}, ['source', 'destination']),
    tool('read_binary', 'Read any regular file as base64 chunks (max 196608 bytes each); returns total size and sha256 of the whole file.',
         {'path': PATH, 'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
          'length': {'type': 'integer', 'minimum': 1, 'maximum': 196608, 'default': 196608}}, ['path']),
    tool('upload_file', 'Upload a binary file in base64 chunks: begin (path, size, sha256, overwrite), chunk (upload_id, offset, data), commit or abort. Data is staged privately and written once, verified, with persistent rollback.',
         {'action': {'type': 'string', 'enum': ['begin', 'chunk', 'commit', 'abort']},
          'path': PATH, 'size': {'type': 'integer', 'minimum': 0, 'maximum': 8388608},
          'sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
          'overwrite': {'type': 'boolean', 'default': False},
          'upload_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'},
          'offset': {'type': 'integer', 'minimum': 0},
          'data': {'type': 'string', 'maxLength': 262144}}, ['action'])
]
FILE_NAMES = {t['name'] for t in FILE_TOOLS}


def install_schema(existing):
    return [t for t in existing if t['name'] not in FILE_NAMES] + FILE_TOOLS
''',
'work_schema.py': r'''"""Explicit work sessions, separate from terminal session IDs."""
import copy

AUTH = {'work_session_id': {'type':'string','pattern':'^[a-f0-9]{32}$'},
        'work_session_token': {'type':'string','minLength':43,'maxLength':43}}
MACHINE = {'type':'string','enum':['mac_mio','vps','mac_noleggio']}
MINUTES = {'type':'integer','minimum':1,'maximum':240}
WORK_TOOLS = [
 {'name':'work_session','description':'Open, renew or close a logical work session. Open once per chat; retain the returned id and capability token privately. Closing cancels its searches and shell before releasing locks. Distinct chats must not share the token.',
  'inputSchema':{'type':'object','additionalProperties':False,'required':['machine','action'],
   'properties':{'machine':MACHINE,'action':{'type':'string','enum':['open','renew','close']},
                 'label':{'type':'string','minLength':1,'maxLength':80},'minutes':MINUTES,**AUTH}}},
 {'name':'work_lock','description':'Acquire, renew or release a durable exclusive path reservation. Acquire a covering lock before writes; a whole-workspace lock is required for the isolated shell. Conflicts name the owning work session. No lock stealing.',
  'inputSchema':{'type':'object','additionalProperties':False,'required':['machine','action','work_session_id','work_session_token'],
   'properties':{'machine':MACHINE,'action':{'type':'string','enum':['acquire','renew','release']},
                 'path':{'type':'string'},'lock_id':{'type':'string','pattern':'^[a-f0-9]{32}$'},
                 'minutes':MINUTES,**AUTH}}}
]
WORK_NAMES = {t['name'] for t in WORK_TOOLS}
SCOPED = {'read_file','read_multiple_files','write_file','edit_block','create_directory',
          'move_file','get_file_info','list_directory','rollback_file','shell_exec','shell_session',
          'enable_full_shell','disable_full_shell','start_search','get_more_search_results','stop_search',
          'delete_path','copy_file','read_binary','upload_file'}


def install_schema(tools):
    result = copy.deepcopy([t for t in tools if t['name'] not in WORK_NAMES])
    for t in result:
        if t['name'] in SCOPED:
            t['inputSchema']['properties'].update(copy.deepcopy(AUTH))
            t['description'] += ' If the selected machine advertises coordination_version, supply work_session_id and work_session_token for writes, searches and shell operations. Read-only calls remain available without them.'
    return result + copy.deepcopy(WORK_TOOLS)
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
    with tempfile.TemporaryDirectory(prefix='mcp-v012-gw-') as tmp:
        for name,data in PAYLOAD.items():Path(tmp,name).write_bytes(data)
        for name in DEPENDENCIES:Path(tmp,name).write_bytes(read(BASE/name))
        code=('import sys;sys.path.insert(0,'+repr(tmp)+');import cg_tools as c;'
              'n=[t["name"] for t in c.TOOLS];assert len(n)==len(set(n))==len(c.NAMES);'
              'assert {"work_session","work_lock","write_file","start_search","admin_request","delete_path","copy_file","read_binary","upload_file"}<=c.NAMES;'
              't={x["name"]:x for x in c.TOOLS};'
              'assert "work_session_id" in t["write_file"]["inputSchema"]["properties"];'
              'assert "work_session_id" not in t["admin_request"]["inputSchema"]["properties"];'
              'assert "work_session_id" in t["upload_file"]["inputSchema"]["properties"];'
              'assert t["enable_full_shell"]["inputSchema"]["properties"]["network"]["enum"]==["none","github","packages"];print(len(n))')
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


NEW_TOOLS={'delete_path','copy_file','read_binary','upload_file'}


def smoke(expect_new):
    tools={t['name']:t for t in rpc('tools/list',{})['tools']}
    if not {'work_session','work_lock'}<=set(tools):raise RuntimeError('work tools missing')
    if (NEW_TOOLS<=set(tools))!=expect_new or (not expect_new and NEW_TOOLS&set(tools)):
        raise RuntimeError('unexpected v0.12 tool catalog')
    if ('network' in tools['enable_full_shell']['inputSchema']['properties'])!=expect_new:
        raise RuntimeError('unexpected network option')
    if expect_new and 'work_session_id' not in tools['delete_path']['inputSchema']['properties']:
        raise RuntimeError('session parameters missing')
    if call('shell_exec',machine='vps',command='uname -a')['exit_code']!=0:raise RuntimeError('vps baseline failed')
    idle()
    return ['catalog '+('with' if expect_new else 'without')+' v0.12 tools','vps baseline','vps and mac_mio idle']


def install(manifest):
    for name,data in PAYLOAD.items():
        meta=manifest[name] or {'mode':manifest['cg_tools.py']['mode'],'uid':manifest['cg_tools.py']['uid'],
                                'gid':manifest['cg_tools.py']['gid']}
        atomic(BASE/name,data,meta['mode'],meta['uid'],meta['gid'])


def main(action):
    load_package()
    if os.getuid()!=0 or os.geteuid()!=0 or Path(__file__).resolve()!=SELF:
        raise RuntimeError('installed root helper required; run through admin_request after Telegram approval')
    trusted_directory(BASE);own=sha(read(SELF));os.umask(0o077)
    fd=os.open('/run/lock/mcp-andrea-files-maintenance.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if action=='--check':
            result=validate();result['catalog_tools']=preflight();result['helper_sha256']=own
            print(json.dumps(result,indent=2));return
        if action=='--apply':
            # Detach from the approval runner before the gateway restarts.
            validate();preflight()
            run(['systemd-run','--unit=central-mcp-v012-20261003','--on-active=5s','--collect',
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
