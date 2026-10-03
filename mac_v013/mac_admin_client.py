"""Agent side of Mac administration: queue a request, read its result.

The agent never runs privileged code. It writes one JSON request into the
outbox (owned by the agent, inside a root-owned directory) and reads results
that only the root helper can write.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

from admin_schema import EXPIRE_S, MAX_REASON, parse_command, parse_timeout

ROOT = Path('/Library/MCPAndreaMacAdmin')
RID = re.compile(r'[a-f0-9]{32}')
MAX_PENDING = 3
HEARTBEAT_MAX_AGE = 120
MAX_RESULT = 256 * 1024


class AdminClient:
    def __init__(self, root=ROOT, helper_uid=0, now=time.time):
        self.root = Path(root)
        self.outbox, self.results = self.root / 'outbox', self.root / 'results'
        self.helper_uid, self.now = helper_uid, now

    def _dir(self, path, owner):
        fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        st = os.fstat(fd)
        if st.st_uid != owner or st.st_mode & 0o002:
            os.close(fd)
            raise PermissionError('unsafe Mac admin directory')
        return fd

    def _read(self, dfd, name, limit):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
        with os.fdopen(fd, 'rb') as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != self.helper_uid or st.st_mode & 0o022 or st.st_size > limit:
                raise PermissionError('unsafe Mac admin result')
            return json.loads(f.read(limit + 1))

    def helper_alive(self):
        try:
            dfd = self._dir(self.results, self.helper_uid)
        except FileNotFoundError:
            raise RuntimeError('Mac admin helper not installed') from None
        try:
            beat = self._read(dfd, 'helper_status.json', 4096)
        except FileNotFoundError:
            raise RuntimeError('Mac admin helper not running') from None
        finally:
            os.close(dfd)
        if not isinstance(beat.get('time'), (int, float)):
            raise RuntimeError('Mac admin helper not running')
        busy = beat.get('busy_until') if isinstance(beat.get('busy_until'), (int, float)) else 0
        if self.now() - beat['time'] > HEARTBEAT_MAX_AGE and self.now() > busy:
            raise RuntimeError('Mac admin helper not running')
        return beat

    def request(self, caller, identity, args):
        if set(args) - {'command', 'reason', 'timeout'}:
            raise ValueError('unexpected admin arguments')
        if not isinstance(identity, str) or not identity.startswith('work:'):
            raise PermissionError('an open work session is required')
        command = args.get('command')
        argv = parse_command(command)
        timeout = parse_timeout(args.get('timeout'))
        reason = args.get('reason')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON:
            raise ValueError('reason required (max %d characters)' % MAX_REASON)
        self.helper_alive()
        dfd = self._dir(self.outbox, os.getuid())
        try:
            if os.fstat(dfd).st_mode & 0o077:
                raise PermissionError('unsafe Mac admin outbox')
            pending = [n for n in os.listdir(dfd) if RID.fullmatch(n[:-5] if n.endswith('.json') else '')]
            if len(pending) >= MAX_PENDING:
                raise PermissionError('too many pending Mac admin requests')
            rid, created = uuid.uuid4().hex, int(self.now())
            req = {'id': rid, 'command': command, 'argv': argv,
                   'sha256': hashlib.sha256(command.encode()).hexdigest(),
                   'reason': reason, 'timeout': timeout, 'caller': caller,
                   'work_session_id': identity[5:], 'created_at': created,
                   'expires_at': created + EXPIRE_S}
            temp = '.' + rid + '.tmp'
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(req, f, ensure_ascii=True)
                    f.flush()
                    os.fsync(f.fileno())
                os.rename(temp, rid + '.json', src_dir_fd=dfd, dst_dir_fd=dfd)
            except BaseException:
                try:
                    os.unlink(temp, dir_fd=dfd)
                except FileNotFoundError:
                    pass
                raise
            os.fsync(dfd)
        finally:
            os.close(dfd)
        return {'request_id': rid, 'sha256': req['sha256'], 'expires_at': req['expires_at'],
                'status': 'sent to Andrea on Telegram (Mac admin bot) for approval; poll mac_admin_result'}

    def result(self, caller, args):
        if set(args) != {'request_id'} or not isinstance(args['request_id'], str) or not RID.fullmatch(args['request_id']):
            raise ValueError('invalid request_id')
        rid = args['request_id']
        try:
            dfd = self._dir(self.results, self.helper_uid)
        except FileNotFoundError:
            raise RuntimeError('Mac admin helper not installed') from None
        try:
            data = self._read(dfd, rid + '.json', MAX_RESULT)
        except FileNotFoundError:
            data = None
        finally:
            os.close(dfd)
        if data is None:
            try:
                os.lstat(str(self.outbox / (rid + '.json')))
                return {'id': rid, 'status': 'queued'}
            except FileNotFoundError:
                return {'id': rid, 'status': 'unknown'}
        if data.get('id') != rid or data.get('caller') != caller:
            raise PermissionError('this admin request belongs to another authorization')
        return data
