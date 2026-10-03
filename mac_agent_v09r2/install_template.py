#!/usr/bin/env python3
"""Physical-authorized migration of only the central rented-Mac agent."""
import base64
import contextlib
import ctypes
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib

BASE=Path('/Library/MCPAndreaMacNoleggioV09R2')
AREA=Path('/Users/Shared/MCPAndreaMacNoleggioR2')
OLD=Path('/Users/vagrant/.mac-control-gateway/central-adapter')
OLDWORK=Path('/Users/vagrant/MCPAndreaWorkspace')
OLDLABEL='it.andreababini.central-mcp-mac-noleggio-test'
OLDPLIST=Path('/Users/vagrant/Library/LaunchAgents')/(OLDLABEL+'.plist')
OLDHASH='9ecb17283993ddb25736909d66288b4af05d761a701ebd848f4e3bc8e9bd6c0f'
LABEL='it.andreababini.mcp-mac-noleggio-v09r2'
PLIST=Path('/Library/LaunchDaemons')/(LABEL+'.plist')
STAGING=Path('/Users/vagrant/MCPAndreaMacAgentSetupV09R2_20261002')
WHEEL='websockets-13.1-py3-none-any.whl'
WHEELHASH='a9a396a6ad26130cdae92ae10c36af09d9bfe6cafe69670fd3b6da9b07b4044f'
PREFLIGHT=Path('/Library/MCPAndreaShellPreflightR2_20261002')
PREFLIGHT_HASH='506636dda780016d3f5c3e81084062a12ebdb1e802aee339c82d8fef395a4b8e'
USER_UUID='51157D7E-6C57-4928-8CA7-DA0A4F9A9086'
GROUP_UUID='64F2EE1E-8D97-4161-8B66-D045B7287459'
PREVIOUS=Path('/Library/MCPAndreaMacNoleggioV09')
PREVIOUS_HASH='322c27c45652760b97326d53be33814f83f1d94de0c325de6652fcd98e38abcd'
GUARD_HASH='8d3f7afe80daae81e8f3a3471229423d14777eb84358a3f57621e74149dc57bc'
PAYLOAD='__PAYLOAD__'


def run(argv,check=True,timeout=20):
    p=subprocess.run(argv,check=False,capture_output=True,text=True,timeout=timeout,
                     env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C'})
    if check and p.returncode:raise RuntimeError('command failed: '+argv[0]+' exit '+str(p.returncode))
    return p


def read_regular(path,owner,max_bytes=2097152,private=False):
    for parent in path.parents:
        if parent.is_symlink():raise RuntimeError('symlink parent rejected')
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=owner or s.st_nlink!=1 or s.st_mode&(0o077 if private else 0o022):
            raise RuntimeError('unsafe source file')
        data=f.read(max_bytes+1)
    if len(data)>max_bytes:raise RuntimeError('source too large')
    return data


def identity():
    if sys.platform!='darwin':raise RuntimeError('macOS required')
    raw=run(['/usr/sbin/ioreg','-rd1','-c','IOPlatformExpertDevice']).stdout
    match=re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"',raw)
    if not match or hashlib.sha256(match.group(1).encode()).hexdigest()!='2b9d73883351aa41e92d596b14e725b4ca557d3c596df090fdee4b35ece64784':
        raise RuntimeError('wrong Mac')
    for kind,expected in [('Users',USER_UUID),('Groups',GROUP_UUID)]:
        raw=run(['/usr/bin/dscl','-plist','.','-read','/'+kind+'/mcp_andrea','GeneratedUID','PrimaryGroupID']).stdout
        d={k.split(':')[-1]:v for k,v in plistlib.loads(raw.encode()).items()}
        if d.get('GeneratedUID')!=[expected] or d.get('PrimaryGroupID')!=['5000']:raise RuntimeError('dedicated identity changed')
    if run(['/usr/bin/id','-u','mcp_andrea']).stdout.strip()!='5000':raise RuntimeError('wrong uid')
    if {'0','80'}&set(run(['/usr/bin/id','-G','mcp_andrea']).stdout.split()):raise RuntimeError('admin group refused')
    attrs=['UserShell','NFSHomeDirectory']
    if os.geteuid()==0:attrs+=['AuthenticationAuthority','Password']
    raw=run(['/usr/bin/dscl','-plist','.','-read','/Users/mcp_andrea']+attrs).stdout
    d={k.split(':')[-1]:v for k,v in plistlib.loads(raw.encode()).items()}
    expected={'UserShell':['/usr/bin/false'],'NFSHomeDirectory':['/var/empty'],
              'AuthenticationAuthority':[';DisabledUser;'],'Password':['*']}
    if any(d.get(key)!=expected[key] for key in attrs):raise RuntimeError('dedicated login configuration changed')


def active():
    raw=run(['/bin/ps','-axo','uid=,pid=,stat=']).stdout
    return [int(x.split()[1]) for x in raw.splitlines() if len(x.split())==3 and x.split()[0]=='5000' and not x.split()[2].startswith('Z')]


def previous_rollback():
    d=json.loads(read_regular(PREVIOUS/'receipt.json',0))
    if d.get('status')!='rolled_back' or d.get('source_sha256')!=PREVIOUS_HASH or d.get('old_agent_restored') is not True:
        raise RuntimeError('previous attempt not safely rolled back')


def cleanup_candidate():
    rows=run(['/bin/ps','-axo','uid=,pid=,ppid=,stat=,comm=']).stdout.splitlines()
    result=[]
    for row in rows:
        fields=row.split(None,4)
        if len(fields)!=5:raise RuntimeError('invalid process metadata')
        if fields[0]!='5000' or fields[3].startswith('Z'):continue
        if fields[2]!='1' or fields[4]!='/usr/sbin/distnoted':raise RuntimeError('dedicated account in use')
        result.append(int(fields[1]))
    return result


def cleanup_previous_attempt():
    # Only this prior failed installation can authorize cleanup of its UID5000
    # Apple notification helper; never terminate user501 or unrelated services.
    previous_rollback()
    candidates=cleanup_candidate()
    if not candidates:return
    lib=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True)
    lib.proc_pidpath.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32]
    lib.proc_pidpath.restype=ctypes.c_int
    for pid in candidates:
        buffer=ctypes.create_string_buffer(4096)
        if lib.proc_pidpath(pid,buffer,len(buffer))<=0 or buffer.value!=b'/usr/sbin/distnoted':
            raise RuntimeError('cleanup executable identity not verified')
    guard=PREFLIGHT/'code/mac_guard.py'
    if hashlib.sha256(read_regular(guard,0)).hexdigest()!=GUARD_HASH:raise RuntimeError('cleanup helper changed')
    for parent in guard.parents:
        s=parent.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise RuntimeError('unsafe cleanup helper parent')
    result=child(['-c','import sys;sys.path.insert(0,'+repr(str(guard.parent))+');from mac_guard import stop_dedicated_children;stop_dedicated_children()'],10)
    if result.returncode or active():raise RuntimeError('previous dedicated helper cleanup incomplete')
    print(json.dumps({'previous_uid5000_notification_helper_stopped':True}),flush=True)


def empty_old_workspace():
    count=0
    for p in OLDWORK.rglob('*'):
        count+=1
        if count>10000 or p.is_symlink() or not p.is_dir():
            raise RuntimeError('old workspace now contains data; migration needs reviewed copy')


def check():
    identity()
    cleanup_pending=False
    if active():
        if os.geteuid()==0:raise RuntimeError('uid5000 in use')
        previous_rollback();cleanup_candidate();cleanup_pending=True
    previous_rollback()
    destinations=(BASE,AREA,PLIST) if os.geteuid()==0 else (BASE,AREA)
    if any(p.exists() or p.is_symlink() for p in destinations):raise RuntimeError('migration destination exists')
    for parent in (BASE.parent,PLIST.parent):
        s=parent.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise RuntimeError('untrusted install parent')
    original=read_regular(OLDPLIST,501)
    if hashlib.sha256(original).hexdigest()!=OLDHASH:raise RuntimeError('old agent plist changed')
    if run(['/bin/launchctl','print','gui/501/'+OLDLABEL],check=False).returncode:raise RuntimeError('old agent not loaded')
    disabled=run(['/bin/launchctl','print-disabled','gui/501']).stdout
    if re.search(re.escape(OLDLABEL)+r'"?\s*=>\s*true',disabled):raise RuntimeError('old agent explicitly disabled')
    proof=json.loads(read_regular(PREFLIGHT/'receipt.json',0))
    if proof.get('status')!='preflight_passed' or proof.get('remaining_uid5000_processes')!=0 or len(proof.get('checks',[]))!=15 or not all(x.get('passed') is True for x in proof['checks']):
        raise RuntimeError('dedicated account preflight not passed')
    if os.geteuid()==0 and hashlib.sha256(read_regular(PREFLIGHT/'preflight_installer.py',0)).hexdigest()!=PREFLIGHT_HASH:
        raise RuntimeError('preflight source changed')
    if hashlib.sha256(read_regular(STAGING/WHEEL,501)).hexdigest()!=WHEELHASH:raise RuntimeError('dependency hash mismatch')
    empty_old_workspace()
    return {'preparation_ready':True,'previous_helper_cleanup_pending':cleanup_pending,
            'root_checks_pending':[] if os.geteuid()==0 else
            ['daemon_destination_absent','preflight_source_sha256','login_disabled'],
            'machine':'mac_noleggio','uid':5000,'old_workspace_empty':True,
            'action':'migrate_central_agent_only','new_workspace':str(AREA/'workspace'),
            'automatic_rollback':True,'admin_telegram_route_changed':False}


def newfile(path,data,mode=0o644,uid=0,gid=0):
    fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as f:
        os.fchown(f.fileno(),uid,gid);os.fchmod(f.fileno(),mode)
        f.write(data);f.flush();os.fsync(f.fileno())


def save_receipt(receipt):
    fd,name=tempfile.mkstemp(dir=str(BASE),prefix='.receipt-')
    with os.fdopen(fd,'w') as f:
        os.fchmod(f.fileno(),0o644);json.dump(receipt,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(name,str(BASE/'receipt.json'))


def child(args,timeout=40):
    return subprocess.run([os.path.realpath(sys.executable),'-I','-B']+args,
        user=5000,group=5000,extra_groups=[5000],umask=0o077,close_fds=True,start_new_session=True,
        cwd='/',env={'PATH':'/usr/bin:/bin','HOME':'/var/empty','LANG':'en_US.UTF-8'},
        capture_output=True,text=True,timeout=timeout)


def clear_children():
    if active():
        p=child(['-c','import sys;sys.path.insert(0,'+repr(str(BASE/'code'))+');from mac_guard import stop_dedicated_children;stop_dedicated_children()'],10)
        if p.returncode:raise RuntimeError('dedicated cleanup failed')
    if active():raise RuntimeError('dedicated processes remain')


def restore_old(receipt):
    if PLIST.exists():
        data=read_regular(PLIST,0)
        if hashlib.sha256(data).hexdigest()!=receipt.get('new_plist_sha256'):raise RuntimeError('new plist changed; rollback refused')
        run(['/bin/launchctl','bootout','system/'+LABEL],check=False)
        if run(['/bin/launchctl','print','system/'+LABEL],check=False).returncode==0:
            raise RuntimeError('new daemon still loaded; rollback stopped')
        os.replace(str(PLIST),str(BASE/'backup/new-daemon-disabled.plist'))
    clear_children()
    if hashlib.sha256(read_regular(OLDPLIST,501)).hexdigest()!=OLDHASH:raise RuntimeError('old plist changed; restore refused')
    run(['/bin/launchctl','enable','gui/501/'+OLDLABEL])
    if run(['/bin/launchctl','print','gui/501/'+OLDLABEL],check=False).returncode:
        run(['/bin/launchctl','bootstrap','gui/501',str(OLDPLIST)])
    run(['/bin/launchctl','print','gui/501/'+OLDLABEL])
    receipt.update(status='rolled_back',time=time.time(),old_agent_restored=True,new_data_preserved=True)
    save_receipt(receipt)


def apply():
    check()
    source=globals().get('APPROVED_SOURCE')
    if not isinstance(source,bytes):raise RuntimeError('use the SHA-verifying local launcher')
    payload=json.loads(zlib.decompress(base64.b64decode(PAYLOAD)))
    expected={'file_tools.py','file_schema.py','shell_common.py','mac_guard.py','mac_clock.py','mac_policy.py','mac_child.py','mac_watchdog.py','mac_shell.py','agent_shell.py','mac_agent.py','selftest.py'}
    if set(payload)!=expected:raise RuntimeError('unexpected code payload')
    wheel=read_regular(STAGING/WHEEL,501)
    if hashlib.sha256(wheel).hexdigest()!=WHEELHASH:raise RuntimeError('dependency changed')
    token=read_regular(OLD/'agent.token',501,4096,True).strip()
    if not re.fullmatch(rb'[A-Za-z0-9_-]{43,256}',token):raise RuntimeError('invalid existing credential')
    guard=os.open(str(OLD/'workspace-operations/guard'),os.O_RDWR|os.O_NOFOLLOW)
    fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        empty_old_workspace()
        BASE.mkdir(mode=0o755);(BASE/'backup').mkdir(mode=0o700)
        before={'old_plist_sha256':OLDHASH,'old_label':OLDLABEL,'old_disabled':False,'user_uuid':USER_UUID,
                'new_base_before':None,'new_workspace_before':None,'source_sha256':hashlib.sha256(source).hexdigest()}
        newfile(BASE/'backup/before.json',json.dumps(before,indent=2).encode(),0o600)
        newfile(BASE/'backup/old-agent.plist',read_regular(OLDPLIST,501),0o600)
        newfile(BASE/'installer.py',source,0o500)
        receipt={'status':'prepared','time':time.time(),'source_sha256':before['source_sha256'],'machine':'mac_noleggio'}
        save_receipt(receipt)
        try:
            AREA.mkdir(mode=0o755)
            for p in (AREA/'workspace',AREA/'workspace/.tmp',BASE/'state'):
                p.mkdir(mode=0o700);os.chown(str(p),5000,5000)
            (BASE/'private').mkdir(mode=0o750);os.chown(str(BASE/'private'),0,5000)
            newfile(BASE/'private/agent.token',token+b'\n',0o640,0,5000)
            del token
            (BASE/'code').mkdir(mode=0o755)
            for name,body in payload.items():newfile(BASE/'code'/name,body.encode(),0o444)
            vendor=BASE/'code/vendor';vendor.mkdir(mode=0o755)
            with zipfile.ZipFile(io.BytesIO(wheel)) as z:
                if len(z.infolist())>200 or sum(x.file_size for x in z.infolist())>10485760:
                    raise RuntimeError('dependency archive too large')
                for item in z.infolist():
                    parts=Path(item.filename).parts
                    if not parts or Path(item.filename).is_absolute() or '..' in parts or item.file_size>2097152 or stat.S_ISLNK(item.external_attr>>16):raise RuntimeError('unsafe dependency archive')
                    dest=vendor/item.filename
                    if item.is_dir():dest.mkdir(mode=0o755,parents=True,exist_ok=True)
                    else:
                        dest.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
                        newfile(dest,z.read(item),0o444)
            p=child([str(BASE/'code/selftest.py')])
            newfile(BASE/'selftest.log',(p.stdout+'\n'+p.stderr).encode()[-65536:])
            if p.returncode:raise RuntimeError('new agent selftest failed; see selftest.log')
            if active():raise RuntimeError('selftest left running processes')
            data=plistlib.dumps({'Label':LABEL,'ProgramArguments':[os.path.realpath(sys.executable),'-I','-B',str(BASE/'code/mac_agent.py')],
                'UserName':'mcp_andrea','GroupName':'mcp_andrea','WorkingDirectory':str(AREA/'workspace'),
                'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'ExitTimeOut':10,'ProcessType':'Background',
                'Umask':63,'StandardOutPath':'/dev/null','StandardErrorPath':'/dev/null',
                'EnvironmentVariables':{'PATH':'/usr/bin:/bin','HOME':str(AREA/'workspace'),'PYTHONDONTWRITEBYTECODE':'1'}},sort_keys=True)
            receipt['new_plist_sha256']=hashlib.sha256(data).hexdigest();save_receipt(receipt)
            run(['/bin/launchctl','disable','gui/501/'+OLDLABEL])
            run(['/bin/launchctl','bootout','gui/501/'+OLDLABEL])
            empty_old_workspace()
            newfile(PLIST,data,0o644)
            started=time.time()
            run(['/bin/launchctl','bootstrap','system',str(PLIST)])
            ready=None
            for _ in range(90):
                path=BASE/'state/connected.json'
                if path.exists():
                    ready=json.loads(read_regular(path,5000,4096,True))
                    if ready.get('uid')==5000 and ready.get('version')=='0.9-rental-2' and ready.get('time',0)>=started and ready.get('connected') is True:break
                time.sleep(1)
            else:raise RuntimeError('new agent gateway connection timeout')
            status=run(['/bin/launchctl','print','system/'+LABEL]).stdout
            if not re.search(r'\bpid = '+str(ready['pid'])+r'\b',status):raise RuntimeError('agent PID mismatch')
            receipt.update(status='active',time=time.time(),uid=5000,agent_pid=ready['pid'],new_workspace=str(AREA/'workspace'),
                shell_default='disabled',shell_network='disabled',rollback_available=True,old_files_preserved=True,boot_start=True)
            save_receipt(receipt)
        except Exception as exc:
            receipt['failure']=type(exc).__name__+': '+str(exc)[:300]
            try:restore_old(receipt)
            except Exception as cleanup:
                receipt.update(status='rollback_requires_review',rollback_failure=type(cleanup).__name__+': '+str(cleanup)[:300]);save_receipt(receipt)
            print(json.dumps(receipt,indent=2));raise SystemExit(1)
        print(json.dumps(receipt,indent=2))
    finally:os.close(guard)


def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ('--check','--apply','--rollback'):raise SystemExit('use --check/--apply/--rollback')
    if sys.argv[1]=='--check':print(json.dumps(check(),indent=2));return
    if os.getuid()!=0 or os.geteuid()!=0:raise SystemExit('physical administrator authorization required')
    identity();os.umask(0o022)
    # Shared with both preflight versions: never run their uid5000 jobs together.
    fd=os.open('/var/run/mcp-andrea-shell-preflight.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        if sys.argv[1]=='--apply':cleanup_previous_attempt();apply()
        else:restore_old(json.loads(read_regular(BASE/'receipt.json',0)))
    finally:os.close(fd)

if __name__=='__main__':main()
