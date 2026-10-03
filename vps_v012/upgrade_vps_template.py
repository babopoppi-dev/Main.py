#!/usr/bin/env python3
"""VPS agent v0.12: work sessions and locks (coordination 0.11). Every step requires Telegram approval."""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zlib

BASE=Path('/opt/central-mcp-gateway')
SELF=BASE/'upgrade_vps_v012_20261003.py'
BACKUP=BASE/'backups/pre_vps_v012_20261003'
RECEIPT=BASE/'vps_v012_receipt.json'
TEST_CODE=BASE/'vps-preflight-v012-20261003'
TEST_DATA=Path('/var/lib/central-mcp-vps-agent-test/tmp/vps-preflight-v012-20261003')
WORK=Path('/var/lib/central-mcp-vps-agent-test/workspace')
GUARD=Path('/var/lib/central-mcp-vps-agent-test/file-operations-v07/guard')
AGENT='central-mcp-vps-agent-test.service'
GATEWAY='central-mcp-gateway-test.service'
ORIGINAL={
    'agent.py':'a6a9573ed8faf425d9e81897c2c7aaf7b07cd0a6a4d3470d4475ad3354b22ea2',
    'work_sessions.py':None}
DEPENDENCIES={
    'file_tools.py':'8a830b3e4ed62fec5b28c5c600a616899c5b706547155d5ed3684a1d8309d54e',
    'file_schema.py':'06e579c359835daa58876d7e5de21d26ad374992fb76d9104dd1d6dd929409eb',
    'isolated_shell.py':'254dd32f26295b9376b1201cf7449832b8d9927018d0b9e208cc2a950b954f3f',
    'search_tools.py':'ebc7358ce73cd449d452363943b4fa66cfc3d740858ade3efc0ee6132513235b',
    'search_schema.py':'c6d111d440eec78bb08e27673fd832479f02446ac2abc25fb5237e12d47ee20d',
    'work_schema.py':'9204940d1c304ca41236785b2248c449a93f8102fcd1e15fae4d76c478db9ee9',
    'cg_mcp.py':'f8a86b9a8424f9e6a0bc335f2951c8e9233750b62e1181379d9c6be3ebb04171'}
VERSION='0.12-vps-work-1'
PACKAGE='__PACKAGE__'
PAYLOAD={}
TESTS={}


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


def idle():
    state=call('who_is_working',machine='vps')
    if state.get('active_locks') or state.get('shell_enabled') or state.get('work_locks') or state.get('work_sessions'):
        raise RuntimeError('VPS busy; active locks or shell authorization present')


@contextlib.contextmanager
def workspace_guard():
    fd=os.open(str(GUARD),os.O_RDWR|os.O_NOFOLLOW)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=997 or st.st_nlink!=1 or st.st_mode&0o077:
            raise RuntimeError('unsafe workspace guard')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:os.close(fd)


def validate():
    if BACKUP.exists() or BACKUP.is_symlink():raise RuntimeError('backup already exists; inspect receipt before retry')
    for name,expected in {**ORIGINAL,**DEPENDENCIES}.items():
        if digest(BASE/name)!=expected:raise RuntimeError('live source changed: '+name)
    for service,user in [(AGENT,'mcp-vps-agent'),(GATEWAY,'mcp-gateway')]:  # gateway is only checked
        if run(['systemctl','show',service,'-p','User','--value']).stdout.strip()!=user:
            raise RuntimeError('service identity changed')
        if run(['systemctl','is-active',service]).stdout.strip()!='active':raise RuntimeError('service not active')
    idle()


def preflight():
    for p in (TEST_CODE,TEST_DATA):
        if p.exists() or p.is_symlink():raise RuntimeError('preflight directory already exists; inspect before retry')
    TEST_CODE.mkdir(mode=0o755);TEST_CODE.chmod(0o755)
    TEST_DATA.mkdir(mode=0o700);os.chown(str(TEST_DATA),997,987)
    for name,data in TESTS.items():atomic(TEST_CODE/name,data,0o444)
    for name in ORIGINAL:
        if TESTS.get(name)!=PAYLOAD[name]:raise RuntimeError('preflight differs from deployment')
    for name in DEPENDENCIES:
        if name in TESTS and sha(TESTS[name])!=DEPENDENCIES[name]:raise RuntimeError('preflight dependency differs')
    code="import sys,unittest;sys.path.insert(0,"+repr(str(TEST_CODE))+");s=unittest.defaultTestLoader.loadTestsFromNames(['test_search','test_vps_agent']);r=unittest.TextTestRunner(verbosity=2).run(s);sys.exit(0 if r.wasSuccessful() else 1)"
    result=subprocess.run([str(BASE/'.venv/bin/python'),'-I','-B','-c',code],
        user=997,group=987,extra_groups=[987],umask=0o077,cwd='/',close_fds=True,
        env={'PATH':'/usr/bin:/bin','HOME':'/var/empty','TMPDIR':str(TEST_DATA),'LANG':'C.UTF-8'},
        capture_output=True,text=True,timeout=45)
    atomic(TEST_CODE/'result.log',(result.stdout+result.stderr).encode()[-65536:])
    if result.returncode!=0:raise RuntimeError('non-admin preflight failed: '+result.stderr[-1000:])


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


def restart(expect_new):
    # Only the VPS agent restarts; the gateway and the Mac connection stay up.
    run(['systemctl','restart',AGENT],90)
    end=time.monotonic()+45
    while time.monotonic()<end:
        try:
            machine=next(m for m in call('list_machines')['machines'] if m['machine']=='vps')
            if machine['online'] and (machine['meta'].get('agent_version')==VERSION)==expect_new:return
        except Exception:pass
        time.sleep(1)
    raise RuntimeError('VPS reconnection check failed')


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


def smoke():
    checks=[];operations=[];searches=[];sessions=[]
    folder=str(WORK/('vps_v012_live_'+uuid.uuid4().hex))
    def auth(x):return {'work_session_id':x['work_session_id'],'work_session_token':x['work_session_token']}
    def refused(name,**args):
        r=rpc('tools/call',{'name':name,'arguments':args})
        if not r.get('isError'):raise RuntimeError(name+' was not refused')
    try:
        a=call('work_session',machine='vps',action='open',label='v012 smoke A',minutes=5);sessions.append(a)
        b=call('work_session',machine='vps',action='open',label='v012 smoke B',minutes=5);sessions.append(b)
        refused('create_directory',machine='vps',path=folder)
        refused('create_directory',machine='vps',path=folder,**auth(a))
        checks.append('writes need session and lock')
        call('work_lock',machine='vps',action='acquire',path=folder,minutes=5,**auth(a))
        refused('work_lock',machine='vps',action='acquire',path=folder+'/x',minutes=5,**auth(b))
        checks.append('lock conflict between sessions')
        operations.append(call('create_directory',machine='vps',path=folder,**auth(a))['operation_id'])
        path=folder+'/test.txt'
        operations.append(call('write_file',machine='vps',path=path,content='MCP_VPS_V012_OK\n',**auth(a))['operation_id'])
        refused('write_file',machine='vps',path=path,content='x',**auth(b))
        refused('rollback_file',machine='vps',operation_id=operations[-1],**auth(b))
        checks.append('foreign write and rollback refused')
        result=call('start_search',machine='vps',path=folder,pattern='MCP_VPS_V012_OK',**auth(a));sid=result['search_id'];searches.append(sid)
        end=time.monotonic()+10
        while result['running'] and time.monotonic()<end:
            time.sleep(.1);result=call('get_more_search_results',machine='vps',search_id=sid,**auth(a))
        if result['status']!='completed' or result['total_results']!=1:raise RuntimeError('live search mismatch')
        refused('get_more_search_results',machine='vps',search_id=sid,**auth(b))
        checks.append('search private to its session')
        state=call('who_is_working',machine='vps')
        if a['work_session_token'] in json.dumps(state) or not state.get('work_locks'):raise RuntimeError('who_is_working mismatch')
        if not any(x.get('work_session_id')==a['work_session_id'] and x.get('operation')=='write_file' for x in state['recent_work_operations']):
            raise RuntimeError('audit without session id')
        checks.append('who_is_working lists lock and session audit without tokens')
        if call('shell_exec',machine='vps',command='uname -a')['exit_code']!=0:raise RuntimeError('baseline status failed')
        checks.append('baseline uname without session')
    finally:
        for sid in searches:
            with contextlib.suppress(Exception):call('stop_search',machine='vps',search_id=sid,**auth(sessions[0]))
        for operation in reversed(operations):call('rollback_file',machine='vps',operation_id=operation,**auth(sessions[0]))
        for x in sessions:
            with contextlib.suppress(Exception):call('work_session',machine='vps',action='close',**auth(x))
    if Path(folder).exists():raise RuntimeError('smoke rollback left a test directory')
    idle();checks.append('sessions closed, locks released, test files rolled back')
    return checks


def load_package():
    global PAYLOAD,TESTS
    raw=json.loads(zlib.decompress(base64.b64decode(PACKAGE,validate=True)))
    PAYLOAD={n:base64.b64decode(v,validate=True) for n,v in raw['payload'].items()}
    TESTS={n:base64.b64decode(v,validate=True) for n,v in raw['tests'].items()}
    if set(PAYLOAD)!=set(ORIGINAL):raise RuntimeError('unexpected deployment payload')
    if set(TESTS)!={'agent.py','work_sessions.py','work_schema.py','cg_tools.py','admin_schema.py','search_tools.py','search_schema.py','file_tools.py','file_schema.py','isolated_shell.py','test_search.py','test_vps_agent.py'}:
        raise RuntimeError('unexpected test payload')
    for name,data in {**PAYLOAD,**TESTS}.items():compile(data,name,'exec')


def main(action):
    if os.getuid()!=0 or os.geteuid()!=0 or Path(__file__).resolve()!=SELF:raise RuntimeError('installed root helper required')
    trusted_directory(BASE);read(SELF);load_package();os.umask(0o077)
    lock=os.open('/run/lock/mcp-andrea-files-maintenance.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    st=os.fstat(lock)
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_nlink!=1 or st.st_mode&0o077:
        os.close(lock);raise RuntimeError('unsafe maintenance lock')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        if action=='--check':
            validate();print(json.dumps({'check_passed':True,'helper_sha256':sha(read(SELF)),'version':VERSION,'gateway_touched':False}));return
        if action=='--apply':
            validate()
            run(['systemd-run','--unit=central-mcp-vps-v012-20261003','--on-active=5s','--collect',
                 '/usr/bin/python3',str(SELF),'--activate'])
            record('activation_scheduled');print(json.dumps({'status':'activation_scheduled','receipt':str(RECEIPT)}));return
        if action=='--activate':
            validate()
            try:preflight()
            except Exception as exc:
                record('preflight_failed',reason=str(exc)[:1200],live_modules_modified=False);raise
            validate()
            try:
                with workspace_guard():
                    # Stop only the VPS agent before replacing its modules.
                    manifest=backup();run(['systemctl','stop',AGENT],90)
                    try:
                        for name,data in PAYLOAD.items():
                            meta=manifest[name] or {'mode':0o644,'uid':0,'gid':0}
                            atomic(BASE/name,data,meta['mode'],meta['uid'],meta['gid'])
                    except Exception:
                        restore(strict=False);raise
            except Exception as exc:
                if BACKUP.exists():
                    with contextlib.suppress(Exception):restart(False)
                record('apply_failed',reason=str(exc)[:1200]);raise
            try:
                restart(True);checks=smoke()
                record('active',checks=checks,backup=str(BACKUP),preflight_uid=997,
                       hashes={n:sha(b) for n,b in PAYLOAD.items()},rental_touched=False)
                print(json.dumps({'status':'active','checks':checks}))
            except Exception as exc:
                try:
                    # A newly active client must not be interrupted for rollback.
                    idle()
                    with workspace_guard():
                        run(['systemctl','stop',AGENT],90);restore(strict=False)
                    restart(False)
                    record('rolled_back',reason=str(exc)[:1200])
                except Exception as rollback:
                    record('rollback_requires_review',reason=str(exc)[:1200],rollback_error=str(rollback)[:1200])
                raise
        elif action=='--rollback':
            idle()
            with workspace_guard():
                # Validate conflicts before any service is stopped.
                for name,data in PAYLOAD.items():
                    if digest(BASE/name)!=sha(data):raise RuntimeError('rollback conflict: '+name)
                run(['systemctl','stop',AGENT],90);restore()
            restart(False);record('rolled_back',reason='approved rollback')
            print(json.dumps({'status':'rolled_back'}))
        else:raise ValueError('use --check, --apply, --activate or --rollback')
    finally:os.close(lock)


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('one action required')
    main(sys.argv[1])
