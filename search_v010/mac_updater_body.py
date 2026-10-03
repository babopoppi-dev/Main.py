"""Appended to the root-pinned Mac search installer by build_mac_installer.py."""


def identity():
    if sys.platform!='darwin':raise RuntimeError('macOS required')
    if run(['/usr/bin/id','-u','mcp_andrea']).stdout.strip()!='5000':raise RuntimeError('wrong dedicated UID')
    if run(['/usr/bin/id','-g','mcp_andrea']).stdout.strip()!='5000':raise RuntimeError('wrong dedicated GID')
    if {'0','80'} & set(run(['/usr/bin/id','-G','mcp_andrea']).stdout.split()):raise RuntimeError('dedicated account is an administrator')
    if sha(read(PLIST))!=PLIST_SHA:raise RuntimeError('daemon configuration changed')
    plist=plistlib.loads(read(PLIST))
    if plist.get('UserName')!='mcp_andrea' or plist.get('GroupName')!='mcp_andrea':raise RuntimeError('wrong daemon account')


def active_pid():
    text=run(['/bin/launchctl','print','system/'+LABEL]).stdout
    match=re.search(r'\bpid = (\d+)\b',text)
    if not match:raise RuntimeError('daemon has no running PID')
    pid=int(match.group(1))
    uid=run(['/bin/ps','-o','uid=','-p',str(pid)]).stdout.strip()
    if uid!='5000':raise RuntimeError('daemon PID has wrong UID')
    return pid


def no_other_processes(daemon_pid=None):
    text=run(['/bin/ps','-axo','uid=,pid=,stat=']).stdout
    pids=[int(p[1]) for row in text.splitlines() if len(p:=row.split())==3 and p[0]=='5000' and not p[2].startswith('Z')]
    if set(pids)!=(set() if daemon_pid is None else {daemon_pid}):raise RuntimeError('dedicated account busy')


def check_sources():
    identity();trusted_directory(BASE)
    for name,expected in {**ORIGINAL,**DEPENDENCIES}.items():
        if digest(BASE/name)!=expected:raise RuntimeError('live source changed: '+name)
    active_pid()
    return {'source_check_passed':True,'target':'mac_mio','new_version':NEW_VERSION,
            'administrative_preflight_pending':True,'rental_touched':False}


def load_package():
    global PAYLOAD,TESTS
    raw=json.loads(zlib.decompress(base64.b64decode(PACKAGE,validate=True)))
    PAYLOAD={n:base64.b64decode(b,validate=True) for n,b in raw['payload'].items()}
    TESTS={n:base64.b64decode(b,validate=True) for n,b in raw['tests'].items()}
    if set(PAYLOAD)!=set(ORIGINAL):raise RuntimeError('unexpected payload')
    if set(TESTS)!=set(TEST_NAMES):raise RuntimeError('unexpected test payload')
    for name,data in {**PAYLOAD,**TESTS}.items():compile(data,name,'exec')


def child(code,timeout=45):
    return subprocess.run([PYTHON,'-I','-B','-c',code],
        user=5000,group=5000,extra_groups=[5000],umask=0o077,cwd='/',close_fds=True,
        env={'PATH':'/usr/bin:/bin','HOME':'/var/empty','TMPDIR':str(TEST_DATA),'LANG':'en_US.UTF-8'},
        capture_output=True,text=True,timeout=timeout)


def preflight():
    for p in (TEST_CODE,TEST_DATA):
        if p.exists() or p.is_symlink():raise RuntimeError('preflight exists; inspect before retry')
    TEST_CODE.mkdir(mode=0o755);TEST_CODE.chmod(0o755)
    TEST_DATA.mkdir(mode=0o700);os.chown(str(TEST_DATA),5000,5000)
    for name,data in TESTS.items():atomic(TEST_CODE/name,data,0o444)
    for name in ORIGINAL:
        if TESTS.get(name)!=PAYLOAD[name]:raise RuntimeError('test and deployed module differ')
    for name,expected in DEPENDENCIES.items():
        if sha(TESTS[name])!=expected:raise RuntimeError('test dependency differs')
    code="import sys,unittest;sys.path.insert(0,"+repr(str(TEST_CODE))+");s=unittest.defaultTestLoader.loadTestsFromNames(['test_search','test_mac_agent']);r=unittest.TextTestRunner(verbosity=2).run(s);sys.exit(0 if r.wasSuccessful() else 1)"
    r=child(code)
    atomic(TEST_CODE/'result.log',(r.stdout+r.stderr).encode()[-65536:])
    if r.returncode:raise RuntimeError('UID5000 preflight failed: '+r.stderr[-1000:])


@contextlib.contextmanager
def workspace_guard():
    fd=os.open(str(GUARD),os.O_RDWR|os.O_NOFOLLOW)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=5000 or st.st_nlink!=1 or st.st_mode&0o077:
            raise RuntimeError('unsafe workspace guard')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:os.close(fd)


def stop_daemon():
    try:pid=active_pid()
    except (RuntimeError,subprocess.CalledProcessError):pid=None
    no_other_processes(pid)
    run(['/bin/launchctl','bootout','system/'+LABEL],30)
    if subprocess.run(['/bin/launchctl','print','system/'+LABEL],capture_output=True).returncode==0:
        raise RuntimeError('daemon still loaded')
    end=time.monotonic()+10
    while time.monotonic()<end:
        try:no_other_processes();return
        except RuntimeError:time.sleep(.2)
    raise RuntimeError('dedicated processes did not exit')


def start_daemon(expected_version):
    started=time.time()
    run(['/bin/launchctl','bootstrap','system',str(PLIST)],30)
    for _ in range(60):
        try:
            ready=json.loads(read(ROOT/'state/connected.json',owner=5000))
            if ready.get('connected') is True and ready.get('version')==expected_version and ready.get('time',0)>=started and ready.get('uid')==5000:
                if ready.get('pid')==active_pid():return ready
        except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError):pass
        time.sleep(1)
    raise RuntimeError('gateway reconnect not verified')


def selftest():
    code="import runpy;runpy.run_path("+repr(str(TEST_CODE/'mac_search_selftest.py'))+",run_name='__main__')"
    r=child(code)
    atomic(TEST_CODE/'selftest.log',(r.stdout+r.stderr).encode()[-65536:])
    if r.returncode:raise RuntimeError('search smoke failed: '+r.stderr[-1000:])
    result=json.loads(r.stdout.strip())
    if result.get('passed') is not True or result.get('uid')!=5000:raise RuntimeError('invalid smoke receipt')
    no_other_processes()
    return result['checks']


def bootstrap(source):
    # The local launcher already verified the complete source hash in memory.
    trusted_directory(ROOT)
    if SELF.exists() or SELF.is_symlink():
        if read(SELF)!=source:raise RuntimeError('root helper already exists with different contents')
    else:atomic(SELF,source,0o555)
    os.execv(PYTHON,[PYTHON,'-I','-B',str(SELF),'--apply'])


def main(action):
    load_package()
    if action=='--check':print(json.dumps(check_sources(),indent=2));return
    if os.getuid()!=0 or os.geteuid()!=0:raise RuntimeError('local administrator approval required')
    source=globals().get('APPROVED_SOURCE')
    if source is not None:
        if not isinstance(source,bytes) or action!='--apply':raise RuntimeError('invalid bootstrap')
        bootstrap(source)
    if Path(__file__).resolve()!=SELF:raise RuntimeError('installed root helper required')
    trusted_directory(ROOT);read(SELF);identity();os.umask(0o077)
    fd=os.open('/var/run/mcp-andrea-shell-preflight.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_nlink!=1 or st.st_mode&0o077:raise RuntimeError('unsafe maintenance lock')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if action=='--apply':
            check_sources();no_other_processes(active_pid())
            if BACKUP.exists() or BACKUP.is_symlink():raise RuntimeError('backup exists; inspect receipt instead of repeating install')
            try:preflight()
            except Exception as e:
                record('preflight_failed',reason=str(e)[:1200],live_modules_modified=False);raise
            check_sources()
            stopped=False;installed=False
            try:
                with workspace_guard():
                    no_other_processes(active_pid());manifest=backup();stopped=True;stop_daemon()
                    for name,data in PAYLOAD.items():
                        meta=manifest[name] or {'mode':0o444,'uid':0,'gid':0}
                        atomic(BASE/name,data,meta['mode'],meta['uid'],meta['gid'])
                    installed=True
                checks=selftest();ready=start_daemon(NEW_VERSION);stopped=False
                record('active',version=NEW_VERSION,uid=5000,agent_pid=ready['pid'],checks=checks,
                       backup=str(BACKUP),hashes={n:sha(b) for n,b in PAYLOAD.items()},rental_touched=False)
                print(json.dumps({'status':'active','checks':checks,'uid':5000},indent=2))
            except Exception as error:
                try:
                    if installed and not stopped:
                        with workspace_guard():stop_daemon();stopped=True
                    if stopped:
                        # A failed bootstrap can leave a loaded daemon: stop only this label.
                        check=subprocess.run(['/bin/launchctl','print','system/'+LABEL],capture_output=True)
                        if check.returncode==0:stop_daemon()
                        with workspace_guard():restore(strict=False)
                        start_daemon(OLD_VERSION)
                    record('rolled_back',reason=str(error)[:1200])
                except Exception as rollback:
                    record('rollback_requires_review',reason=str(error)[:1200],rollback_error=str(rollback)[:1200])
                raise
        elif action=='--rollback':
            with workspace_guard():
                verify_restore()
                stop_daemon()
                try:restore()
                except Exception:
                    start_daemon(NEW_VERSION);raise
            try:
                ready=start_daemon(OLD_VERSION)
                record('rolled_back',agent_pid=ready['pid'],reason='local approved rollback')
                print(json.dumps({'status':'rolled_back'}))
            except Exception as e:
                record('rollback_requires_review',reason=str(e)[:1200]);raise
        else:raise ValueError('use --check, --apply or --rollback')
    finally:os.close(fd)


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('one action required')
    main(sys.argv[1])
