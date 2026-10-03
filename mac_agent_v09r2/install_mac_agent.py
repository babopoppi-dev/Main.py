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
PAYLOAD='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'


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
