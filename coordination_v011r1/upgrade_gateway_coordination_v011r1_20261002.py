#!/usr/bin/env python3
"""Gateway catalog activation for coordination v0.11 r1. Telegram-approved admin_request only."""
import base64,contextlib,fcntl,hashlib,json,os,ssl,stat,subprocess,sys,tempfile,time,urllib.request,uuid,zlib
from pathlib import Path
BASE=Path('/opt/central-mcp-gateway')
SELF=BASE/'upgrade_gateway_coordination_v011r1_20261002.py'
BACKUP=BASE/'backups/pre_coordination_v011r1_20261002'
RECEIPT=BASE/'coordination_v011r1_20261002_receipt.json'
GATEWAY='central-mcp-gateway-test.service'
PYTHON='/usr/bin/python3'
PAYLOAD={}
ORIGINAL={'cg_tools.py': 'a6a9f4fa6ce5569fdb7622b957765e8ca1adb052f941b5e750406987e527c519', 'work_schema.py': None}
DEPENDENCIES={'cg_mcp.py': 'f8a86b9a8424f9e6a0bc335f2951c8e9233750b62e1181379d9c6be3ebb04171', 'file_schema.py': '06e579c359835daa58876d7e5de21d26ad374992fb76d9104dd1d6dd929409eb', 'search_schema.py': 'c6d111d440eec78bb08e27673fd832479f02446ac2abc25fb5237e12d47ee20d'}
PACKAGE='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'


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
    raw=json.loads(zlib.decompress(base64.b64decode(PACKAGE,validate=True)))
    PAYLOAD={n:base64.b64decode(b,validate=True) for n,b in raw.items()}
    if set(PAYLOAD)!=set(ORIGINAL):raise RuntimeError('unexpected payload')
    for name,data in PAYLOAD.items():compile(data,name,'exec')


def preflight():
    # Import the new catalog next to the live dependencies, outside BASE.
    with tempfile.TemporaryDirectory(prefix='coord-v011-gw-') as tmp:
        for name,data in PAYLOAD.items():Path(tmp,name).write_bytes(data)
        for name in DEPENDENCIES:Path(tmp,name).write_bytes(read(BASE/name))
        code=('import sys;sys.path.insert(0,'+repr(tmp)+');import cg_tools as c;'
              'n=[t["name"] for t in c.TOOLS];assert len(n)==len(set(n))==len(c.NAMES);'
              'assert {"work_session","work_lock","write_file","start_search","admin_request"}<=c.NAMES;'
              't={x["name"]:x for x in c.TOOLS};'
              'assert "work_session_id" in t["write_file"]["inputSchema"]["properties"];'
              'assert "work_session_id" not in t["admin_request"]["inputSchema"]["properties"];print(len(n))')
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
    present={'work_session','work_lock'}<=set(tools)
    if present!=expect_work:raise RuntimeError('unexpected work tool catalog')
    if expect_work and 'work_session_id' not in tools['write_file']['inputSchema']['properties']:
        raise RuntimeError('session parameters missing')
    if call('shell_exec',machine='vps',command='uname -a')['exit_code']!=0:raise RuntimeError('vps baseline failed')
    idle()
    return ['catalog '+('with' if expect_work else 'without')+' work tools','vps baseline','vps and mac_mio idle']


def install(manifest):
    for name,data in PAYLOAD.items():
        meta=manifest[name] or {'mode':manifest['cg_tools.py']['mode'],'uid':manifest['cg_tools.py']['uid'],
                                'gid':manifest['cg_tools.py']['gid']}
        atomic(BASE/name,data,meta['mode'],meta['uid'],meta['gid'])


def main(action):
    load_package()
    if os.getuid()!=0:raise RuntimeError('run through admin_request after Telegram approval')
    os.umask(0o077)
    fd=os.open('/run/mcp-andrea-coordination-gateway.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if action=='--check':
            result=validate();result['catalog_tools']=preflight();print(json.dumps(result,indent=2));return
        if action=='--apply':
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
