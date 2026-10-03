#!/usr/bin/env python3
"""Pinned VPS-only shell deployment. Root actions require Telegram approval."""
import base64
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

BASE = Path('/opt/central-mcp-gateway')
SELF = BASE / 'upgrade_shell_v08r3_20261002.py'
BACKUP = BASE / 'backups/pre_shell_v08r3_20261002'
RECEIPT = BASE / 'shell_v08r3_receipt.json'
CONFIG = Path('/etc/central-mcp-vps-agent/agent-test.json')
DROPIN = Path('/etc/systemd/system/central-mcp-vps-agent-test.service.d/80-mcp-shell-v08.conf')
DROPIN_DATA = b'[Service]\nMemoryMax=512M\nTasksMax=128\nCPUQuota=100%\nTimeoutStopSec=10s\n# Required for unprivileged private proc and nested-userns disabling.\n# NoNewPrivileges, non-admin identity and remaining restrictions stay enabled.\nProtectKernelTunables=no\nProtectKernelLogs=no\n'
SERVICES = ['central-mcp-vps-agent-test.service','central-mcp-gateway-test.service']
ORIGINAL = {'agent.py':'d16fa5dc84953513ff8cab0c60fcf204f5c64c888d290e49c12cdfab6f21ef00',
            'cg_tools.py':'94e364be3794082f7f29c5c1cd6217abc843c575b5cc651204f56297dd37ef89',
            'cg_mcp.py':'a1a9a7c66c0f003f8de9bf98f421bd89726f13c5f3f24b0ae1b9a8b155419844',
            'isolated_shell.py':None}
PAYLOAD = {}  # Embedded by build_installer.py.
TEST_PAYLOAD = {}  # Embedded preflight; never taken from a writable external file.
TEST_CODE = BASE / 'shell-preflight-v08r3-20261002'
TEST_DATA = Path('/var/lib/central-mcp-vps-agent-test/tmp/collaudo_shell_v08r3_20261002')


def sha(data): return hashlib.sha256(data).hexdigest()


def atomic(path,data,mode=0o644,uid=0,gid=0):
    if path.is_symlink(): raise RuntimeError('symlink rejected')
    fd,tmp = tempfile.mkstemp(prefix='.shell-v08-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            os.fchown(out.fileno(),uid,gid);os.fchmod(out.fileno(),mode)
            out.write(data);out.flush();os.fsync(out.fileno())
        os.replace(tmp,path)
        dfd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def record(status,**extra):
    atomic(RECEIPT,json.dumps(dict(status=status,time=time.time(),**extra),indent=2).encode())


def run(argv,timeout=20):
    return subprocess.run(argv,check=True,capture_output=True,text=True,timeout=timeout,
                          env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'})


def rpc(method,params):
    cfg=json.loads(Path('/etc/central-mcp-gateway/gateway-test.json').read_text())
    context=ssl.create_default_context(cafile=cfg['tls_cert']);context.check_hostname=False
    token=Path(cfg['mcp_token_file']).read_text().strip()
    data=json.dumps({'jsonrpc':'2.0','id':uuid.uuid4().hex,'method':method,'params':params}).encode()
    req=urllib.request.Request('https://127.0.0.1:'+str(cfg['port'])+'/mcp',data=data,
          headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
    with urllib.request.urlopen(req,context=context,timeout=10) as response: value=json.load(response)
    if 'error' in value: raise RuntimeError('gateway RPC rejected')
    return value['result']


def call(name,**args):
    result=rpc('tools/call',{'name':name,'arguments':args})
    if result.get('isError'): raise RuntimeError('smoke operation failed: '+name+' '+result['content'][0]['text'][:200])
    return json.loads(result['content'][0]['text'])


def restart():
    run(['systemctl','daemon-reload'])
    for service in SERVICES: run(['systemctl','restart',service],timeout=110)
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
        try:
            machines=call('list_machines')['machines']
            if all(any(x['machine']==m and x['online'] for x in machines)
                   for m in ('vps','mac_noleggio','mac_mio')): return
        except Exception: pass
        time.sleep(1)
    raise RuntimeError('three agents did not reconnect')


def completed_command(command):
    result=call('shell_exec',machine='vps',command=command)
    output=result.get('output','')
    deadline=time.monotonic()+12
    while result.get('running') or result.get('has_more'):
        if time.monotonic()>=deadline:
            raise RuntimeError('smoke command did not finish: '+str(result)[:400])
        time.sleep(.1)
        result=call('shell_session',machine='vps',action='read',session_id=result['session_id'])
        output+=result.get('output','')
    result['output']=output
    return result


def preflight_probe():
    if TEST_CODE.exists() or TEST_CODE.is_symlink() or TEST_DATA.exists() or TEST_DATA.is_symlink():
        raise RuntimeError('preflight paths already exist; inspect before retry')
    TEST_CODE.mkdir(mode=0o755);TEST_CODE.chmod(0o755)
    TEST_DATA.mkdir(mode=0o700);os.chown(TEST_DATA,997,987)
    for name in ('workspace','journal'):
        p=TEST_DATA/name;p.mkdir(mode=0o700);os.chown(p,997,987)
    for name,payload in TEST_PAYLOAD.items():
        if name not in {'file_tools.py','isolated_shell.py','probe_shell.py'}: raise RuntimeError('unexpected preflight module')
        data=base64.b64decode(payload['data'],validate=True)
        if sha(data)!=payload['sha256']: raise RuntimeError('preflight payload mismatch')
        atomic(TEST_CODE/name,data,0o444)
    if TEST_PAYLOAD['isolated_shell.py']['sha256']!=PAYLOAD['isolated_shell.py']['sha256']:
        raise RuntimeError('probe and deployed runtime must be identical')
    unit='mcp-andrea-shell-preflight-v08r3-20261002'
    argv=['systemd-run','--unit='+unit,'--collect','--wait','--pipe',
          '--property=User=mcp-vps-agent','--property=Group=mcp-vps-agent',
          '--property=NoNewPrivileges=yes','--property=PrivateTmp=yes','--property=PrivateDevices=yes',
          '--property=ProtectHome=yes','--property=ProtectSystem=strict','--property=RestrictSUIDSGID=yes',
          '--property=LockPersonality=yes','--property=ProtectKernelModules=yes','--property=ProtectControlGroups=yes',
          '--property=ProtectKernelTunables=no','--property=ProtectKernelLogs=no',
          '--property=ReadOnlyPaths=/opt/central-mcp-gateway','--property=ReadOnlyPaths=/etc/central-mcp-vps-agent',
          '--property=ReadWritePaths='+str(TEST_DATA),'--property=TasksMax=128','--property=MemoryMax=512M',
          '--property=CPUQuota=100%','--property=RuntimeMaxSec=45','--property=KillMode=control-group',
          '/opt/central-mcp-gateway/.venv/bin/python','-B',str(TEST_CODE/'probe_shell.py')]
    record('preflight_running',live_agent_modified=False)
    try:
        result=subprocess.run(argv,capture_output=True,text=True,timeout=55,
                              env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'})
        record('preflight_passed' if result.returncode==0 else 'preflight_failed',
               output=result.stdout[-8000:],diagnostic=result.stderr[-6000:],live_agent_modified=False)
        if result.returncode!=0 or 'SHELL_PROBE_OK' not in result.stdout:
            raise RuntimeError('preflight failed: '+result.stderr[-1200:])
        return json.loads(result.stdout.strip())['checks']
    finally:
        subprocess.run(['systemctl','stop',unit+'.service'],capture_output=True,timeout=10)


def smoke():
    results=[]
    record('testing',step='metadata')
    machines=call('list_machines')['machines']
    vps=next(x for x in machines if x['machine']=='vps')
    assert vps['meta']['full_shell_capable'], 'new agent did not advertise full shell capability'
    assert vps['meta']['shell_backend']=='bwrap-v08', 'new agent backend missing'
    assert call('shell_exec',machine='vps',command='uname -a')['exit_code']==0, 'baseline uname failed'
    results.append('baseline and new VPS metadata')
    name='/var/lib/central-mcp-vps-agent-test/workspace/collaudo_shell_live_'+uuid.uuid4().hex+'.txt'
    operation=None
    try:
        record('testing',step='enable and id')
        call('enable_full_shell',machine='vps',minutes=1)
        result=completed_command('id -u')
        record('testing',step='isolated id result',id_result=result)
        assert result['exit_code']==0 and result['output'].strip()=='997', 'isolated id returned unexpected result: '+str(result)[:400]
        record('testing',step='PTY')
        sid=call('shell_session',machine='vps',action='start',command='cat')['session_id']
        call('shell_session',machine='vps',action='send',session_id=sid,data='MCP_V08_LIVE\n')
        output=''
        for _ in range(15):
            output+=call('shell_session',machine='vps',action='read',session_id=sid)['output']
            if 'MCP_V08_LIVE' in output: break
            time.sleep(.1)
        assert 'MCP_V08_LIVE' in output, 'PTY input/output marker missing'
        record('testing',step='disable and refusal')
        call('disable_full_shell',machine='vps')
        ended=call('shell_session',machine='vps',action='read',session_id=sid)
        assert not ended['running'], 'session still running after disable'
        denied=rpc('tools/call',{'name':'shell_exec','arguments':{'machine':'vps','command':'id'}})
        assert denied.get('isError') and 'enable the isolated shell' in denied['content'][0]['text'], 'command not correctly refused after disable: '+str(denied)[:400]
        results.append('temporary enable exec PTY input/output disable and denial after disable')
        record('testing',step='file rollback')
        operation=call('write_file',machine='vps',path=name,content='v08 rollback probe\n')['operation_id']
        assert call('read_file',machine='vps',path=name)['content']=='v08 rollback probe\n', 'file read mismatch'
        call('rollback_file',machine='vps',operation_id=operation);operation=None
        results.append('file write read rollback after releasing shell lock')
    finally:
        call('disable_full_shell',machine='vps')
        if operation is not None: call('rollback_file',machine='vps',operation_id=operation)
    return results


def validate():
    if BACKUP.exists(): raise RuntimeError('backup already exists; inspect before another deployment')
    receipt=json.loads((BASE/'shell_probe_v08r2_receipt.json').read_text())
    if receipt.get('status')!='passed' or receipt['payload_hashes']['isolated_shell.py']!=PAYLOAD['isolated_shell.py']['sha256']:
        raise RuntimeError('matching live isolation probe required')
    for name,expected in ORIGINAL.items():
        p=BASE/name
        if p.is_symlink() or (sha(p.read_bytes()) if p.exists() else None)!=expected:
            raise RuntimeError('live code changed: '+name)
        data=base64.b64decode(PAYLOAD[name]['data'],validate=True)
        if sha(data)!=PAYLOAD[name]['sha256']: raise RuntimeError('payload changed')
        compile(data,name,'exec')
    cfg=json.loads(CONFIG.read_text())
    if CONFIG.is_symlink() or cfg.get('full_shell_capable') is not False or cfg.get('shell_backend'):
        raise RuntimeError('agent configuration already changed')
    if cfg.get('data_root')!='/var/lib/central-mcp-vps-agent-test' or cfg.get('allowed_roots')!=[
        '/var/lib/central-mcp-vps-agent-test/workspace','/var/lib/central-mcp-vps-agent-test/tmp']:
        raise RuntimeError('unexpected data roots')
    if run(['systemctl','show',SERVICES[0],'-p','User','--value']).stdout.strip()!='mcp-vps-agent':
        raise RuntimeError('service identity changed')
    if DROPIN.exists() or DROPIN.is_symlink(): raise RuntimeError('drop-in already exists')
    if DROPIN.parent.exists():
        st=DROPIN.parent.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
            raise RuntimeError('unsafe drop-in directory')
    return cfg


def backup(cfg):
    BACKUP.mkdir(mode=0o700,exist_ok=False);BACKUP.chmod(0o700)
    manifest={'files':{},'dropin_directory_created':not DROPIN.parent.exists()}
    for name in list(ORIGINAL)+['agent-config.json']:
        p=CONFIG if name=='agent-config.json' else BASE/name
        if p.exists():
            st=p.stat();data=p.read_bytes()
            manifest['files'][name]={'mode':stat.S_IMODE(st.st_mode),'uid':st.st_uid,'gid':st.st_gid,'sha256':sha(data)}
            atomic(BACKUP/name,data,0o600)
        else: manifest['files'][name]=None
    cfg=dict(cfg,full_shell_capable=True,shell_backend='bwrap-v08')
    new_cfg=(json.dumps(cfg,indent=2)+'\n').encode()
    manifest['installed_config_sha256']=sha(new_cfg)
    atomic(BACKUP/'manifest.json',json.dumps(manifest).encode(),0o600)
    return manifest,new_cfg


def restore(strict=True):
    manifest=json.loads((BACKUP/'manifest.json').read_text())
    # Review all conflicts before mutating any file during an explicit rollback.
    if strict:
        for name,payload in PAYLOAD.items():
            if sha((BASE/name).read_bytes())!=payload['sha256']: raise RuntimeError('module rollback conflict')
        if sha(CONFIG.read_bytes())!=manifest['installed_config_sha256']: raise RuntimeError('config rollback conflict')
        if DROPIN.read_bytes()!=DROPIN_DATA: raise RuntimeError('unit rollback conflict')
    for name,meta in manifest['files'].items():
        p=CONFIG if name=='agent-config.json' else BASE/name
        if meta is None:
            if p.exists():
                if sha(p.read_bytes())!=PAYLOAD[name]['sha256']: raise RuntimeError('new module rollback conflict')
                p.unlink()
        else:
            data=(BACKUP/name).read_bytes()
            if sha(data)!=meta['sha256']: raise RuntimeError('backup changed')
            atomic(p,data,meta['mode'],meta['uid'],meta['gid'])
    if DROPIN.exists():
        if DROPIN.read_bytes()!=DROPIN_DATA: raise RuntimeError('unit rollback conflict')
        DROPIN.unlink()
    if manifest['dropin_directory_created'] and DROPIN.parent.exists(): DROPIN.parent.rmdir()
    restart()


def main(action):
    if os.geteuid()!=0 or Path(__file__).resolve()!=SELF: raise RuntimeError('installed root helper required')
    st=SELF.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022: raise RuntimeError('unsafe helper')
    lock=os.open('/run/lock/mcp-andrea-files-maintenance.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        if action in ('--apply','--activate'):
            cfg=validate()
            if action=='--apply':
                run(['systemd-run','--unit=central-mcp-shell-v08r3-20261002','--on-active=5s','--collect',
                     '/usr/bin/python3',str(SELF),'--activate'])
                record('activation_scheduled')
                print(json.dumps({'status':'activation_scheduled','receipt':str(RECEIPT)}));return
            # Test under the actual proposed service restrictions before changing
            # any live module, unit property or agent configuration.
            try:
                preflight_checks=preflight_probe()
            except BaseException as exc:
                record('preflight_failed',reason=type(exc).__name__+': '+str(exc)[:1500],live_agent_modified=False)
                raise
            manifest,new_cfg=backup(cfg)
            try:
                for name,payload in PAYLOAD.items(): atomic(BASE/name,base64.b64decode(payload['data']))
                meta=manifest['files']['agent-config.json']
                atomic(CONFIG,new_cfg,meta['mode'],meta['uid'],meta['gid'])
                if not DROPIN.parent.exists(): DROPIN.parent.mkdir(mode=0o755);DROPIN.parent.chmod(0o755)
                atomic(DROPIN,DROPIN_DATA)
                restart()
                checks=smoke()
                record('active',backup=str(BACKUP),checks=checks,preflight_checks=preflight_checks,full_shell_enabled=False,
                       hashes={n:v['sha256'] for n,v in PAYLOAD.items()})
                print(json.dumps({'status':'active','checks':checks,'full_shell_enabled':False}))
            except BaseException as exc:
                try:
                    restore(strict=False)
                    record('rolled_back',reason=type(exc).__name__+': '+str(exc)[:300])
                except BaseException as rollback_exc:
                    record('rollback_failed',reason=type(rollback_exc).__name__+': '+str(rollback_exc)[:300])
                raise
        elif action=='--rollback':
            restore();record('rolled_back',reason='approved rollback');print('ROLLBACK_COMPLETED')
        else: raise ValueError('invalid action')
    finally: os.close(lock)


if __name__=='__main__':
    if len(sys.argv)!=2: raise SystemExit('one action required')
    main(sys.argv[1])
