#!/usr/bin/env python3
"""Physical-authorized migration of only the central rented-Mac agent."""
import base64
import contextlib
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

BASE=Path('/Library/MCPAndreaMacMioV09')
AREA=Path('/Users/Shared/MCPAndreaMacMio')
OLD=Path('/Users/babo/Library/Application Support/MCPAndrea')
OLDWORK=Path('/Users/babo/MCPAndreaWorkspace')
OLDLABEL='it.andreababini.mcp-mac-mio'
OLDPLIST=Path('/Users/babo/Library/LaunchAgents')/(OLDLABEL+'.plist')
OLDHASH='4b7221e55e61affad1c0296b6985d0b27b78135267e9114e093139a672207b1d'
LABEL='it.andreababini.mcp-mac-mio-v09'
PLIST=Path('/Library/LaunchDaemons')/(LABEL+'.plist')
STAGING=Path('/Users/babo/MCPAndreaMacMioSetupV09_20261002')
WHEEL='websockets-13.1-py3-none-any.whl'
WHEELHASH='a9a396a6ad26130cdae92ae10c36af09d9bfe6cafe69670fd3b6da9b07b4044f'
PREFLIGHT=Path('/Library/MCPAndreaMacMioPreflightV09')
PREFLIGHT_HASH='a6d840a6ee89b5e8346e1427ad56d4192e315b8fc31dde174f5ccaafd62f2fd9'
USER_UUID=None
GROUP_UUID=None
PAYLOAD='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'


ACCOUNT_STATE=Path('/Library/MCPAndreaMacMioAccountV09')
ACCOUNT_HASH='c266d38a0a593db98364b42113495229125e6919c3f9d025b1088f7f2b0feec3'


def account_uuids():
    path=ACCOUNT_STATE/'receipt.json'
    for parent in path.parents:
        st=parent.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
            raise RuntimeError('unsafe account receipt parent')
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077 or st.st_nlink!=1:
            raise RuntimeError('unsafe account receipt')
        raw=f.read(8193)
    if len(raw)>8192:raise RuntimeError('account receipt too large')
    d=json.loads(raw)
    if d.get('status')!='account_ready' or d.get('source_sha256')!=ACCOUNT_HASH or d.get('uid')!=5000 or d.get('gid')!=5000:
        raise RuntimeError('account bootstrap not verified')
    ids=[d.get('user_uuid'),d.get('group_uuid')]
    if any(not isinstance(v,str) or not re.fullmatch(r'[A-F0-9]{8}(?:-[A-F0-9]{4}){3}-[A-F0-9]{12}',v) for v in ids):
        raise RuntimeError('invalid generated account identity')
    return ids


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
    global USER_UUID, GROUP_UUID
    USER_UUID, GROUP_UUID=account_uuids()
    raw=run(['/usr/sbin/ioreg','-rd1','-c','IOPlatformExpertDevice']).stdout
    match=re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"',raw)
    if not match or hashlib.sha256(match.group(1).encode()).hexdigest()!='13e94bc1b7e266b260a0eb5aa9e0b3ffa4cd322a419b6be36481c583f6454d9d':
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


def empty_old_workspace():
    count=0
    for p in OLDWORK.rglob('*'):
        count+=1
        if count>10000 or p.is_symlink() or not p.is_dir():
            raise RuntimeError('old workspace now contains data; migration needs reviewed copy')


def preinstall_check():
    destinations=(BASE,AREA,PLIST)
    if any(p.exists() or p.is_symlink() for p in destinations):raise RuntimeError('migration destination exists')
    for parent in (BASE.parent,PLIST.parent):
        s=parent.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise RuntimeError('untrusted install parent')
    original=read_regular(OLDPLIST,501)
    if hashlib.sha256(original).hexdigest()!=OLDHASH:raise RuntimeError('old agent plist changed')
    if run(['/bin/launchctl','print','gui/501/'+OLDLABEL],check=False).returncode:raise RuntimeError('old agent not loaded')
    disabled=run(['/bin/launchctl','print-disabled','gui/501']).stdout
    if re.search(re.escape(OLDLABEL)+r'"?\s*=>\s*true',disabled):raise RuntimeError('old agent explicitly disabled')
    if hashlib.sha256(read_regular(STAGING/WHEEL,501)).hexdigest()!=WHEELHASH:raise RuntimeError('dependency hash mismatch')
    empty_old_workspace()
    return {'preparation_ready':True,'machine':'mac_mio','uid':5000,'old_workspace_empty':True,
            'action':'account_preflight_then_migrate_agent','new_workspace':str(AREA/'workspace'),
            'automatic_rollback':True,'admin_telegram_route_changed':False}


def check():
    identity()
    if active():raise RuntimeError('uid5000 in use')
    result=preinstall_check()
    proof=json.loads(read_regular(PREFLIGHT/'receipt.json',0))
    if proof.get('status')!='preflight_passed' or proof.get('remaining_uid5000_processes')!=0 or len(proof.get('checks',[]))!=15 or not all(x.get('passed') is True for x in proof['checks']):
        raise RuntimeError('dedicated account preflight not passed')
    if hashlib.sha256(read_regular(PREFLIGHT/'preflight_installer.py',0)).hexdigest()!=PREFLIGHT_HASH:
        raise RuntimeError('preflight source changed')
    return result


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
    guard=os.open(str(OLD/'operations/guard'),os.O_RDWR|os.O_NOFOLLOW)
    fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        empty_old_workspace()
        BASE.mkdir(mode=0o755);(BASE/'backup').mkdir(mode=0o700)
        before={'old_plist_sha256':OLDHASH,'old_label':OLDLABEL,'old_disabled':False,'user_uuid':USER_UUID,
                'new_base_before':None,'new_workspace_before':None,'source_sha256':hashlib.sha256(source).hexdigest()}
        newfile(BASE/'backup/before.json',json.dumps(before,indent=2).encode(),0o600)
        newfile(BASE/'backup/old-agent.plist',read_regular(OLDPLIST,501),0o600)
        newfile(BASE/'installer.py',source,0o500)
        receipt={'status':'prepared','time':time.time(),'source_sha256':before['source_sha256'],'machine':'mac_mio'}
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
                    if ready.get('uid')==5000 and ready.get('version')=='0.9-personal-1' and ready.get('time',0)>=started and ready.get('connected') is True:break
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
        if sys.argv[1]=='--apply':apply()
        else:restore_old(json.loads(read_regular(BASE/'receipt.json',0)))
    finally:os.close(fd)

if __name__=='__main__':main()
