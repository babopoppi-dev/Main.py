#!/usr/bin/env python3
"""One physical invocation: create the dedicated account, prove isolation, migrate."""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
import types
import zlib

PAYLOAD='__COMPONENTS__'


def components():
    data=json.loads(zlib.decompress(base64.b64decode(PAYLOAD)))
    if set(data)!={'bootstrap_account.py','preflight_installer.py','install_mac_agent.py'}:
        raise RuntimeError('unexpected setup component')
    loaded={}
    for name,source in data.items():
        raw=source.encode()
        module=types.ModuleType('mcp_personal_'+name[:-3])
        module.__dict__.update(__file__=name,APPROVED_SOURCE=raw)
        exec(compile(raw,name,'exec'),module.__dict__)
        loaded[name]=module
    return loaded['bootstrap_account.py'],loaded['preflight_installer.py'],loaded['install_mac_agent.py']


def check(account,preflight,migration):
    account.preflight()
    if migration.active():raise RuntimeError('uid5000 already active')
    for p in (preflight.BASE,preflight.AREA):
        if p.exists() or p.is_symlink():raise RuntimeError('preflight destination exists')
    return migration.preinstall_check()


def apply(account,preflight,migration):
    check(account,preflight,migration)
    source=globals().get('APPROVED_SOURCE')
    if not isinstance(source,bytes):raise RuntimeError('use SHA-verifying physical launcher')
    state={'status':'starting','time':time.time(),'machine':'mac_mio','source_sha256':hashlib.sha256(source).hexdigest()}
    try:
        print('Fase1/3: creazione account dedicato non amministratore.',flush=True)
        account.apply()
        account.atomic(account.STATE/'setup_personal.py',source,0o500)
        state.update(status='account_ready',account_created=True)
        print('Fase2/3: collaudo isolamento, terminale e ripristino.',flush=True)
        preflight.apply()
        state.update(status='preflight_passed')
        print('Fase3/3: installazione agent e collegamento al gateway.',flush=True)
        migration.apply()
        state.update(status='active',agent_uid=5000,disabled_account_retained=True)
    except (Exception,SystemExit) as exc:
        state.update(status='stopped',failure=type(exc).__name__+': '+str(exc)[:300],
                     previous_stage=state.get('status'))
        raise
    finally:
        state['time']=time.time()
        if account.STATE.exists():
            account.atomic(account.STATE/'setup_receipt.json',json.dumps(state,indent=2).encode())
        print(json.dumps(state,indent=2),flush=True)


def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ('--check','--apply'):raise SystemExit('use --check/--apply')
    if sys.argv[1]=='--apply' and (os.getuid()!=0 or os.geteuid()!=0):
        raise SystemExit('physical administrator authorization required')
    account,preflight,migration=components()
    if sys.argv[1]=='--check':print(json.dumps(check(account,preflight,migration),indent=2));return
    account.machine_check();os.umask(0o022)
    with contextlib.ExitStack() as locks:
        for name in ('/var/run/mcp-andrea-account-bootstrap.lock','/var/run/mcp-andrea-shell-preflight.lock'):
            fd=os.open(name,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
            locks.callback(os.close,fd)
            s=os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o077 or s.st_nlink!=1:
                raise RuntimeError('unsafe maintenance lock')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        apply(account,preflight,migration)


if __name__=='__main__':main()
