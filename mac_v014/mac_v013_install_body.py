"""Appended to the v0.13 Mac installer: tolerated per-user macOS agents (same as v0.12)."""

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
