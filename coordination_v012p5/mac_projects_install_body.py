PROJECTS_FILE=BASE/'projects.json'
OWNER_NAME='babo'
OWNER_UID=501
HOME=Path('/Users/babo')
DEV=HOME/'Developer'
MCP=DEV/'MCPAndrea'
PROJECTS_CONFIG={'version':1,'roots':[{'path':str(DEV),'mode':'ro'},{'path':str(MCP),'mode':'rw'}],'exclude':[]}
# Directory-style names apply to files too (same bits: list=read, search=execute, add_file=write).
ACL_TRAVERSE='mcp_andrea allow search'
ACL_RO='mcp_andrea allow list,search,readattr,readextattr,readsecurity,file_inherit,directory_inherit'
ACL_RW_RIGHTS='allow list,add_file,search,delete,add_subdirectory,delete_child,readattr,writeattr,readextattr,writeextattr,readsecurity,file_inherit,directory_inherit'
ACL_RW='mcp_andrea '+ACL_RW_RIGHTS
# Files created by mcp_andrea (UID 5000) stay fully usable by Andrea.
ACL_OWNER=OWNER_NAME+' '+ACL_RW_RIGHTS


def acl_plan():
    return [(HOME,ACL_TRAVERSE,False),(DEV,ACL_RO,False),(MCP,ACL_RW,True),(MCP,ACL_OWNER,True)]


def owner_directory(path):
    try:st=os.lstat(str(path))
    except FileNotFoundError:
        os.mkdir(str(path),0o755);os.chown(str(path),OWNER_UID,20);os.chmod(str(path),0o755)
        st=os.lstat(str(path))
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=OWNER_UID:raise RuntimeError('project folder is not a directory owned by Andrea: '+str(path))
    if os.path.realpath(str(path))!=str(path):raise RuntimeError('project folder must not be a symlink: '+str(path))


def chmod_acl(sign,entry,path,recursive):
    argv=['/bin/chmod']+(['-R'] if recursive else [])+[sign+'a',entry,str(path)]
    return subprocess.run(argv,capture_output=True,text=True,timeout=600,
        env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C.UTF-8'})


def projects_setup():
    import pwd
    u=pwd.getpwnam(OWNER_NAME)
    if u.pw_uid!=OWNER_UID or u.pw_dir!=str(HOME):raise RuntimeError('unexpected owner account')
    if os.path.realpath(str(HOME))!=str(HOME):raise RuntimeError('home must not be a symlink')
    owner_directory(DEV);owner_directory(MCP)
    for path,entry,recursive in acl_plan():
        chmod_acl('-',entry,path,recursive)  # no duplicates on a retry; absence is fine
        r=chmod_acl('+',entry,path,recursive)
        if r.returncode:raise RuntimeError('ACL failed on %s: %s'%(path,(r.stderr or r.stdout)[-300:]))
    atomic(PROJECTS_FILE,(json.dumps(PROJECTS_CONFIG,indent=1)+'\n').encode(),0o644,0,0)
    return {'projects':PROJECTS_CONFIG,'acl':[[str(p),e] for p,e,_ in acl_plan()]}


def projects_remove():
    """Best effort: configuration first (the agent then has no projects), then the explicit ACL entries."""
    errors=[]
    try:
        if PROJECTS_FILE.exists() or PROJECTS_FILE.is_symlink():PROJECTS_FILE.unlink()
    except OSError as e:errors.append('projects.json: '+str(e))
    for path,entry,recursive in reversed(acl_plan()):
        if path.exists():
            r=chmod_acl('-',entry,path,recursive)
            if r.returncode and 'No such' not in (r.stderr or ''):errors.append('%s: %s'%(path,(r.stderr or '')[-200:]))
    return errors
