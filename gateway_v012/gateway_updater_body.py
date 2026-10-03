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
    with tempfile.TemporaryDirectory(prefix='gw-v012-') as tmp:
        for name,data in PAYLOAD.items():Path(tmp,name).write_bytes(data)
        for name in DEPENDENCIES:Path(tmp,name).write_bytes(read(BASE/name))
        code=('import sys;sys.path.insert(0,'+repr(tmp)+');import cg_tools as c;'
              'n=[t["name"] for t in c.TOOLS];assert len(n)==len(set(n))==len(c.NAMES);'
              'assert {"work_session","work_lock","write_file","start_search","admin_request"}<=c.NAMES;'
              't={x["name"]:x for x in c.TOOLS};'
              'assert "work_session_id" in t["write_file"]["inputSchema"]["properties"];'
              'assert "work_session_id" not in t["admin_request"]["inputSchema"]["properties"];'
              'assert {"mac_admin_request","mac_admin_result"}<=c.NAMES;'
              'assert t["mac_admin_request"]["inputSchema"]["properties"]["machine"]["enum"]==["mac_mio"];print(len(n))')
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
    if not {'work_session','work_lock'}<=set(tools):raise RuntimeError('work tools missing')
    present={'mac_admin_request','mac_admin_result'}<=set(tools)
    if present!=expect_work:raise RuntimeError('unexpected Mac admin tool catalog')
    if call('shell_exec',machine='vps',command='uname -a')['exit_code']!=0:raise RuntimeError('vps baseline failed')
    idle()
    return ['catalog '+('with' if expect_work else 'without')+' Mac admin tools','vps baseline','vps and mac_mio idle']


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
            run(['systemd-run','--unit=central-mcp-gateway-v012-20261003','--on-active=5s','--collect',
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
