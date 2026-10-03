"""Durable cooperative work sessions. No OAuth credentials are stored here.

Each logical client opens a session and keeps its random capability token.
Tokens separate cooperating chats sharing one OAuth authorization; they are not
proof of a platform chat ID and cannot protect a token deliberately shared.
Only the agent's protected state directory may contain this store.
"""
import contextlib
import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import sys
import threading
import time
import unicodedata
import uuid

ID = re.compile(r'[a-f0-9]{32}')
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}')
CALLER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}')
MUTATIONS = {'write_file', 'edit_block', 'create_directory', 'move_file', 'rollback_file',
             'delete_path', 'copy_file', 'upload_file'}


def boot_identity():
    if sys.platform == 'darwin':
        # kern.boottime is shifted by calendar steps (NTP); the boot session
        # UUID is stable for the whole boot.
        # sysctlbyname needs no subprocess and is also allowed by the seatbelt.
        import ctypes, ctypes.util
        libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
        size = ctypes.c_size_t(64); buf = ctypes.create_string_buffer(64)
        if libc.sysctlbyname(b'kern.bootsessionuuid', buf, ctypes.byref(size), None, ctypes.c_size_t(0)):
            raise RuntimeError('boot identity unavailable')
        raw = buf.raw[:size.value].rstrip(b'\0')
        if not re.fullmatch(rb'[0-9A-Fa-f-]{36}', raw):
            raise RuntimeError('boot identity unavailable')
    elif sys.platform.startswith('linux'):
        with open('/proc/sys/kernel/random/boot_id', 'rb') as f:
            raw = f.read(100)
    else:
        raise RuntimeError('unsupported boot clock')
    if not raw.strip():
        raise RuntimeError('boot identity unavailable')
    return hashlib.sha256(raw.strip()).hexdigest()


def shared_clock():
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)


class WorkSessions:
    MAX_BYTES = 1024 * 1024
    MAX_SESSIONS = 64
    MAX_LOCKS = 256

    def __init__(self, directory, files, wall=time.time, clock=shared_clock, boot=None):
        self.path = os.path.abspath(directory)
        self.files, self.wall, self.clock = files, wall, clock
        self.boot = boot if boot is not None else boot_identity()
        os.makedirs(self.path, mode=0o700, exist_ok=True)
        s = os.lstat(self.path)
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
            raise PermissionError('private work-session directory required')
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.mutex = threading.RLock()
        self.depth, self.current = 0, None
        with self.transaction():
            pass

    def close(self):
        os.close(self.fd)

    @staticmethod
    def minutes(value):
        if type(value) is not int or not 1 <= value <= 240:
            raise ValueError('minutes must be 1..240')
        return value

    def times(self):
        wall, tick = self.wall(), self.clock()
        if not all(math.isfinite(x) and x >= 0 for x in (wall, tick)):
            raise RuntimeError('invalid clock')
        return wall, tick

    def private(self, fd):
        s = os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_nlink != 1 or s.st_mode & 0o077:
            raise PermissionError('unsafe work-session state')

    def read_state(self):
        try:
            fd = os.open('state.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        except FileNotFoundError:
            return {'version': 1, 'sessions': {}, 'locks': {}, 'recent': []}
        with os.fdopen(fd, 'rb') as f:
            self.private(f.fileno())
            raw = f.read(self.MAX_BYTES + 1)
        if len(raw) > self.MAX_BYTES:
            raise RuntimeError('session state exceeds limit')
        d = json.loads(raw)
        if (set(d) != {'version', 'sessions', 'locks', 'recent'} or d['version'] != 1
                or not isinstance(d['sessions'], dict) or not isinstance(d['locks'], dict)
                or not isinstance(d['recent'], list)):
            raise RuntimeError('invalid session state; manual review required')
        return d

    def write_state(self, d):
        raw = json.dumps(d, ensure_ascii=True, separators=(',', ':')).encode()
        if len(raw) > self.MAX_BYTES:
            raise RuntimeError('session state exceeds limit')
        name = '.state-' + uuid.uuid4().hex
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(raw); f.flush(); os.fsync(f.fileno())
            os.replace(name, 'state.json', src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            with contextlib.suppress(FileNotFoundError): os.unlink(name, dir_fd=self.fd)

    def purge(self, d):
        wall, tick = self.times()
        for sid, s in list(d['sessions'].items()):
            if s['boot'] != self.boot or wall >= s['expires_at'] or tick >= s['deadline']:
                del d['sessions'][sid]
        for lid, l in list(d['locks'].items()):
            if l['session_id'] not in d['sessions'] or wall >= l['expires_at'] or tick >= l['deadline']:
                del d['locks'][lid]

    @contextlib.contextmanager
    def transaction(self):
        with self.mutex:
            if self.depth:
                self.depth += 1
                try:
                    self.purge(self.current)
                    yield self.current
                finally: self.depth -= 1
                return
            lock = os.open('guard', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            try:
                self.private(lock)
                # Never block the event loop on a concurrent client or process.
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                d = self.read_state()
                before = json.dumps(d, sort_keys=True)
                self.purge(d)
                self.current, self.depth = d, 1
                try:
                    yield d
                finally:
                    # Read-only checks (watchdog every 0.5s) must not fsync.
                    if json.dumps(d, sort_keys=True) != before:
                        self.write_state(d)
                    self.current, self.depth = None, 0
            finally:
                self.current, self.depth = None, 0
                os.close(lock)

    def canonical(self, path):
        p, _, parts = self.files._path(path)
        # Inspect every existing component. Missing descendants may be reserved.
        root = p
        for _ in parts: root = os.path.dirname(root)
        current = root
        for part in parts:
            current = os.path.join(current, part)
            try: s = os.lstat(current)
            except FileNotFoundError: break
            if stat.S_ISLNK(s.st_mode):
                raise PermissionError('symlink lock paths are rejected')
        return p

    @staticmethod
    def key(path):
        # Conservative on case-sensitive volumes, correct on ordinary Mac APFS.
        return unicodedata.normalize('NFD', path).casefold().rstrip('/')

    @classmethod
    def contains(cls, parent, child):
        a, b = cls.key(parent), cls.key(child)
        return a == b or b.startswith(a + '/')

    def event(self, d, sid, operation, **fields):
        d['recent'].append({'time': self.wall(), 'work_session_id': sid, 'operation': operation, **fields})
        del d['recent'][:-100]

    def open(self, caller, label, minutes=30):
        if not isinstance(caller, str) or not CALLER.fullmatch(caller):
            raise PermissionError('authenticated caller required')
        if not isinstance(label, str) or not 1 <= len(label) <= 80 or any(ord(c) < 32 for c in label):
            raise ValueError('label requires 1..80 printable characters')
        self.minutes(minutes)
        with self.transaction() as d:
            if len(d['sessions']) >= self.MAX_SESSIONS:
                raise PermissionError('work session capacity reached')
            sid, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
            wall, tick = self.times()
            d['sessions'][sid] = {'caller': caller, 'label': label,
                'token_hash': hashlib.sha256(token.encode()).hexdigest(), 'boot': self.boot,
                'created_at': wall, 'expires_at': wall + minutes*60, 'deadline': tick + minutes*60}
            self.event(d, sid, 'session_open', label=label)
            return {'work_session_id': sid, 'work_session_token': token,
                    'expires_at': wall + minutes*60, 'label': label,
                    'identity_scope': 'explicit work session; do not share its capability token'}

    def auth(self, d, caller, sid, token):
        if not isinstance(sid, str) or not ID.fullmatch(sid) or not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise PermissionError('valid work session credentials required')
        s = d['sessions'].get(sid)
        if not s or s['caller'] != caller or not hmac.compare_digest(s['token_hash'], hashlib.sha256(token.encode()).hexdigest()):
            raise PermissionError('invalid or expired work session')
        return s

    def authenticate(self, caller, sid, token):
        with self.transaction() as d:
            self.auth(d, caller, sid, token)
        return 'work:' + sid

    def renew(self, caller, sid, token, minutes=30):
        self.minutes(minutes)
        with self.transaction() as d:
            s = self.auth(d, caller, sid, token)
            wall, tick = self.times()
            s.update(expires_at=wall + minutes*60, deadline=tick + minutes*60)
            self.event(d, sid, 'session_renew')
            return {'work_session_id': sid, 'expires_at': s['expires_at'],
                    'note': 'locks retain their own expiry; renew them separately'}

    def end(self, caller, sid, token):
        with self.transaction() as d:
            self.auth(d, caller, sid, token)
            del d['sessions'][sid]
            d['locks'] = {k:v for k,v in d['locks'].items() if v['session_id'] != sid}
            self.event(d, sid, 'session_close')
            return {'work_session_id': sid, 'closed': True}

    def acquire(self, caller, sid, token, path, minutes=30):
        path = self.canonical(path); self.minutes(minutes)
        with self.transaction() as d:
            s = self.auth(d, caller, sid, token)
            if len(d['locks']) >= self.MAX_LOCKS:
                raise PermissionError('work lock capacity reached')
            for l in d['locks'].values():
                if self.contains(l['path'], path) or self.contains(path, l['path']):
                    if l['session_id'] != sid:
                        raise PermissionError('path locked by work session ' + l['session_id'])
                    if self.key(l['path']) == self.key(path):
                        raise ValueError('path already locked by this session; renew the lock')
            wall, tick = self.times(); lid = uuid.uuid4().hex
            l = {'lock_id': lid, 'session_id': sid, 'path': path,
                 'expires_at': min(s['expires_at'], wall + minutes*60),
                 'deadline': min(s['deadline'], tick + minutes*60)}
            d['locks'][lid] = l
            self.event(d, sid, 'lock_acquire', path=path, lock_id=lid)
            return self.public_lock(l)

    def change_lock(self, caller, sid, token, lock_id, minutes=None):
        if not isinstance(lock_id, str) or not ID.fullmatch(lock_id):
            raise ValueError('invalid lock id')
        with self.transaction() as d:
            s = self.auth(d, caller, sid, token)
            l = d['locks'].get(lock_id)
            if not l or l['session_id'] != sid:
                raise PermissionError('lock missing, expired, or owned by another session')
            if minutes is None:
                del d['locks'][lock_id]
                self.event(d, sid, 'lock_release', lock_id=lock_id)
                return {'lock_id': lock_id, 'released': True}
            self.minutes(minutes); wall, tick = self.times()
            l.update(expires_at=min(s['expires_at'], wall + minutes*60),
                     deadline=min(s['deadline'], tick + minutes*60))
            self.event(d, sid, 'lock_renew', lock_id=lock_id)
            return self.public_lock(l)

    @staticmethod
    def public_lock(l):
        return {k:v for k,v in l.items() if k != 'deadline'}

    def require(self, d, identity, path):
        if not isinstance(identity, str) or not identity.startswith('work:'):
            raise PermissionError('open a work session before changing files')
        sid = identity[5:]
        if sid not in d['sessions']:
            raise PermissionError('work session expired')
        if not any(l['session_id'] == sid and self.contains(l['path'], path) for l in d['locks'].values()):
            raise PermissionError('acquire an unexpired work lock covering the path first')
        return d['sessions'][sid]

    @contextlib.contextmanager
    def lock_provider(self, identity, path):
        path = self.canonical(path)
        with self.transaction() as d:
            self.require(d, identity, path)
            yield

    def remaining(self, identity, path):
        path = self.canonical(path)
        with self.transaction() as d:
            s = self.require(d, identity, path)
            wall, tick = self.times()
            locks = [l for l in d['locks'].values() if l['session_id'] == identity[5:] and self.contains(l['path'], path)]
            lock_remaining = max(min(l['expires_at']-wall, l['deadline']-tick) for l in locks)
            return max(0, min(s['expires_at']-wall, s['deadline']-tick, lock_remaining))

    def audit(self, identity, operation, ok, request_id):
        with self.transaction() as d:
            sid = identity[5:] if isinstance(identity, str) and identity.startswith('work:') else None
            self.event(d, sid, operation, ok=bool(ok), request_id=request_id)

    def snapshot(self):
        with self.transaction() as d:
            return {'coordination_version': '0.11.0',
                    'identity_scope': 'explicit work session; cooperating clients must keep separate tokens',
                    'work_sessions': [{'work_session_id': k, 'label': s['label'], 'caller': s['caller'],
                                       'expires_at': s['expires_at']} for k,s in d['sessions'].items()],
                    'work_locks': [self.public_lock(l) for l in d['locks'].values()],
                    'recent_work_operations': list(d['recent'][-30:])}
