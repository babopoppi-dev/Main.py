"""Appended to the v0.12 Mac installer by build_mac_v012.py: Telegram pairing and the root helper."""

ADMIN_ROOT=Path('/Library/MCPAndreaMacAdmin')
ADMIN_LABEL='it.andreababini.mcp-mac-admin'
ADMIN_PLIST=Path('/Library/LaunchDaemons')/(ADMIN_LABEL+'.plist')
ADMIN_BACKUP=BACKUP/'admin'
KNOWN_SYSTEM={'/usr/sbin/distnoted':('agent',),'/usr/sbin/cfprefsd':('agent',),
              '/usr/libexec/trustd':('--agent',),'/usr/libexec/secinitd':(),
              '/usr/libexec/lsd':(),'/usr/libexec/containermanagerd':()}


def executable(pid):
    """Kernel view of the program image; argv in ps can be rewritten by the process itself."""
    import ctypes
    lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
    buf=ctypes.create_string_buffer(4096)
    n=lib.proc_pidpath(ctypes.c_int(pid),buf,ctypes.c_uint32(4096))
    return os.fsdecode(buf.raw[:n]) if n>0 else None


def known_system(p):
    """Only per-user macOS agents started by launchd, verified by kernel image path."""
    if len(p)!=5 or p[2]!='1':return False
    args=p[4].split()
    if not args or args[0] not in KNOWN_SYSTEM or tuple(args[1:])!=KNOWN_SYSTEM[args[0]]:return False
    try:return executable(int(p[1]))==args[0]
    except Exception:return False


def helper_namespace():
    ns={'__name__':'mac_admin_helper_embedded'}
    exec(compile(SOURCES['mac_admin_helper.py'],'mac_admin_helper.py','exec'),ns)
    return ns


def admin_conf_path():
    return ADMIN_ROOT/'conf'/'telegram.json'


def ensure_admin_dirs():
    if ADMIN_ROOT.is_symlink():raise RuntimeError('unsafe admin root')
    layout=[(ADMIN_ROOT,0,0,0o755),(ADMIN_ROOT/'conf',0,0,0o700),(ADMIN_ROOT/'code',0,0,0o755),
            (ADMIN_ROOT/'outbox',5000,5000,0o700),(ADMIN_ROOT/'results',0,5000,0o750),(ADMIN_ROOT/'claims',0,0,0o700)]
    for path,uid,gid,mode in layout:
        if path.is_symlink():raise RuntimeError('unsafe admin path: '+str(path))
        if not path.exists():path.mkdir(mode=mode)
        os.chown(str(path),uid,gid);os.chmod(str(path),mode)
        st=path.lstat()
        if not stat.S_ISDIR(st.st_mode) or (st.st_uid,st.st_gid,stat.S_IMODE(st.st_mode))!=(uid,gid,mode):
            raise RuntimeError('admin layout not applied: '+str(path))


def telegram_setup(prompt=input,secret=None,clock=time.monotonic):
    """Pair a NEW Telegram bot (not the VPS one) with Andrea's private chat.

    Idempotent: a valid existing configuration is reused after a getMe check.
    """
    import getpass,secrets
    secret=secret or getpass.getpass
    ns=helper_namespace()
    ensure_admin_dirs()
    path=admin_conf_path()
    if path.exists() or path.is_symlink():
        tg,chat=ns['load_config'](ADMIN_ROOT)
        me=tg('getMe')
        print('Bot Telegram gia configurato: @%s' % me.get('username'))
        return {'bot':me.get('username'),'chat_id':chat,'reused':True}
    print('Serve un bot Telegram NUOVO, dedicato al Mac (non quello del VPS).')
    print('In Telegram: @BotFather, /newbot, poi copia qui il token.')
    for attempt in range(3):
        token=secret('Token del nuovo bot (non viene mostrato): ').strip()
        try:
            tg=ns['Telegram'](token);me=tg('getMe');break
        except Exception as e:
            print('Token non valido o Telegram non raggiungibile (%s).' % type(e).__name__)
    else:raise RuntimeError('Telegram token not verified')
    if not me.get('is_bot') or not me.get('username'):raise RuntimeError('not a bot token')
    offset=None
    for u in tg('getUpdates',timeout=0):offset=u['update_id']+1
    code='%06d' % secrets.randbelow(1000000)
    print('Apri la chat con @%s, premi Avvia e invia questo codice: %s' % (me['username'],code))
    end=clock()+300;chat=None
    while clock()<end and chat is None:
        params={'timeout':20,'allowed_updates':['message']}
        if offset is not None:params['offset']=offset
        for u in tg('getUpdates',**params):
            offset=u['update_id']+1
            m=u.get('message') or {}
            c=m.get('chat') or {};f=m.get('from') or {}
            if (m.get('text') or '').strip()==code and c.get('type')=='private' and f.get('id')==c.get('id') and not f.get('is_bot'):
                chat=c['id']
    if chat is None:raise RuntimeError('Telegram pairing code not received within 5 minutes')
    if offset is not None:tg('getUpdates',offset=offset,timeout=0)
    data=json.dumps({'bot_token':token,'chat_id':chat,'bot':me['username'],'paired_at':int(time.time())}).encode()
    atomic(path,data,0o600,0,0)
    tg('sendMessage',chat_id=chat,text='MCP Andrea: questo bot approvera i comandi amministratore del Mac personale. Ogni comando va approvato singolarmente.')
    print('Abbinamento Telegram completato.')
    return {'bot':me['username'],'chat_id':chat,'reused':False}


def admin_plist():
    return plistlib.dumps({'Label':ADMIN_LABEL,'UserName':'root','GroupName':'wheel',
        'ProgramArguments':[PYTHON,'-I','-B',str(ADMIN_ROOT/'code'/'mac_admin_helper.py')],
        'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'WorkingDirectory':'/var/root',
        'StandardOutPath':str(ADMIN_ROOT/'helper.log'),'StandardErrorPath':str(ADMIN_ROOT/'helper.log'),
        'EnvironmentVariables':{'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'}})


def admin_state():
    r=subprocess.run(['/bin/launchctl','print','system/'+ADMIN_LABEL],capture_output=True,text=True,timeout=10,
                     env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C.UTF-8'})
    if r.returncode==0:
        m=re.search(r'\bpid = (\d+)\b',r.stdout)
        return {'loaded':True,'pid':int(m.group(1)) if m else None}
    if r.returncode==113 and 'Could not find service' in r.stderr:return {'loaded':False,'pid':None}
    raise RuntimeError('cannot inspect admin helper: '+r.stderr[-300:])


def admin_remove():
    if admin_state()['loaded']:run(['/bin/launchctl','bootout','system/'+ADMIN_LABEL],30)
    end=time.monotonic()+20
    while admin_state()['loaded']:
        if time.monotonic()>end:raise RuntimeError('admin helper did not stop')
        time.sleep(.2)
    if ADMIN_PLIST.exists() or ADMIN_PLIST.is_symlink():ADMIN_PLIST.unlink()


def admin_activate():
    ensure_admin_dirs()
    if admin_state()['loaded']:admin_remove()
    code=SOURCES['mac_admin_helper.py'].encode()
    if sha(code)!=SOURCE_SHA['mac_admin_helper.py']:raise RuntimeError('helper source changed')
    target=ADMIN_ROOT/'code'/'mac_admin_helper.py'
    if target.exists():
        ADMIN_BACKUP.mkdir(mode=0o700,parents=True,exist_ok=True)
        atomic(ADMIN_BACKUP/'mac_admin_helper.py',read(target),0o600)
    atomic(target,code,0o444,0,0)
    atomic(ADMIN_PLIST,admin_plist(),0o644,0,0)
    started=time.time()
    run(['/bin/launchctl','bootstrap','system',str(ADMIN_PLIST)],30)
    for _ in range(45):
        try:
            beat=json.loads(read(ADMIN_ROOT/'results'/'helper_status.json'))
            state=admin_state()
            if beat.get('version')==helper_namespace()['VERSION'] and beat.get('time',0)>=started and beat.get('pid')==state['pid']:
                return {'helper_pid':state['pid'],'helper_version':beat['version']}
        except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError):pass
        time.sleep(1)
    raise RuntimeError('admin helper heartbeat not verified')


def admin_phase(conf):
    try:
        info=admin_activate()
    except Exception as e:
        try:admin_remove()
        except Exception as cleanup:e=RuntimeError(str(e)+'; cleanup: '+str(cleanup))
        record('active_agent_admin_failed',version=NEW_VERSION,reason=str(e)[:1200],backup=str(BACKUP))
        print(json.dumps({'status':'agent_active_admin_failed','reason':str(e)[:300]},indent=2))
        raise
    record('active',version=NEW_VERSION,backup=str(BACKUP),admin=info,telegram_bot=conf.get('bot'),
           hashes={n:sha(b) for n,b in PAYLOAD.items()},helper_sha256=SOURCE_SHA['mac_admin_helper.py'],rental_touched=False)
    print(json.dumps({'status':'active','admin':info,'telegram_bot':conf.get('bot')},indent=2))
