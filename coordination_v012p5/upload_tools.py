"""Chunked binary uploads, staged privately and committed as one journaled write.

Chunks never touch the project tree. Only commit, after size and SHA-256 match,
writes the destination through FileTools, so rollback keeps one backup per file
instead of one per chunk. Staging is bounded, owner-bound and expires.
"""
import base64
import binascii
import hashlib
import os
import re
import stat
import time
import uuid

from file_tools import FileToolError

ID = re.compile(r'[a-f0-9]{32}')
SHA = re.compile(r'[a-f0-9]{64}')


class Uploads:
    MAX_ACTIVE = 4
    MAX_STAGED = 32 * 1024 * 1024
    TTL = 30 * 60
    MAX_CHUNK_BASE64 = 262144

    def __init__(self, files, directory, clock=time.monotonic):
        self.files, self.clock = files, clock
        self.path = os.path.abspath(directory)
        os.makedirs(self.path, mode=0o700, exist_ok=True)
        s = os.lstat(self.path)
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
            raise PermissionError('private upload directory required')
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        # Staged data does not survive an agent restart: clients start again.
        for name in os.listdir(self.fd):
            if re.fullmatch(r'[a-f0-9]{32}\.part', name):
                os.unlink(name, dir_fd=self.fd)
            else:
                raise PermissionError('unexpected upload staging entry')
        self.jobs = {}

    def close(self):
        for uid in list(self.jobs):
            self._drop(uid)
        os.close(self.fd)

    def _drop(self, uid):
        self.jobs.pop(uid, None)
        try:
            os.unlink(uid + '.part', dir_fd=self.fd)
        except FileNotFoundError:
            pass

    def purge(self):
        now = self.clock()
        for uid, job in list(self.jobs.items()):
            if now >= job['deadline']:
                self._drop(uid)

    def _job(self, identity, upload_id):
        if not isinstance(upload_id, str) or not ID.fullmatch(upload_id):
            raise FileToolError('INVALID_ARGUMENT', 'invalid upload_id')
        job = self.jobs.get(upload_id)
        if job is None or job['owner'] != identity:
            raise FileToolError('UPLOAD_UNKNOWN', 'upload missing, expired, or owned by another session')
        return job

    def begin(self, identity, path, size, sha256, overwrite=False):
        if type(size) is not int or not 0 <= size <= self.files.max_file:
            raise FileToolError('LIMIT', 'size must be 0..%d bytes' % self.files.max_file)
        if not isinstance(sha256, str) or not SHA.fullmatch(sha256):
            raise FileToolError('INVALID_ARGUMENT', 'lowercase hex sha256 required')
        if type(overwrite) is not bool:
            raise FileToolError('INVALID_ARGUMENT', 'overwrite must be boolean')
        if len(self.jobs) >= self.MAX_ACTIVE:
            raise FileToolError('LIMIT', 'too many active uploads; commit or abort one')
        if sum(j['size'] for j in self.jobs.values()) + size > self.MAX_STAGED:
            raise FileToolError('LIMIT', 'upload staging quota reached')
        # Fail early when the destination is not covered by this session's lock.
        with self.files._locked([path], identity):
            kind = self.files._snapshot(path)['kind']
        if kind == 'directory' or kind == 'file' and not overwrite:
            raise FileToolError('DESTINATION_EXISTS', 'destination exists; pass overwrite=true for a file')
        uid = uuid.uuid4().hex
        fd = os.open(uid + '.part', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        os.close(fd)
        self.jobs[uid] = {'owner': identity, 'path': path, 'size': size, 'sha256': sha256,
                          'overwrite': overwrite, 'received': 0, 'deadline': self.clock() + self.TTL}
        return {'upload_id': uid, 'path': path, 'size': size, 'received': 0,
                'max_chunk_base64': self.MAX_CHUNK_BASE64, 'expires_in_seconds': self.TTL}

    def chunk(self, identity, upload_id, offset, data):
        job = self._job(identity, upload_id)
        if type(offset) is not int or offset != job['received']:
            raise FileToolError('OFFSET_MISMATCH', 'offset must equal bytes received', received=job['received'])
        if not isinstance(data, str) or not data or len(data) > self.MAX_CHUNK_BASE64:
            raise FileToolError('INVALID_ARGUMENT', 'data must be 1..%d base64 characters' % self.MAX_CHUNK_BASE64)
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise FileToolError('INVALID_ARGUMENT', 'data is not valid base64') from None
        if job['received'] + len(raw) > job['size']:
            raise FileToolError('LIMIT', 'chunk exceeds declared size')
        fd = os.open(upload_id + '.part', os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            if os.fstat(fd).st_size != job['received']:
                raise FileToolError('UPLOAD_CORRUPT', 'staged data changed; abort and restart')
            os.write(fd, raw)
        finally:
            os.close(fd)
        job['received'] += len(raw)
        return {'upload_id': upload_id, 'received': job['received'], 'size': job['size'],
                'complete': job['received'] == job['size']}

    def commit(self, identity, upload_id):
        job = self._job(identity, upload_id)
        if job['received'] != job['size']:
            raise FileToolError('INCOMPLETE', 'upload incomplete', received=job['received'], size=job['size'])
        fd = os.open(upload_id + '.part', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        with os.fdopen(fd, 'rb') as f:
            data = f.read(job['size'] + 1)
        if len(data) != job['size'] or hashlib.sha256(data).hexdigest() != job['sha256']:
            self._drop(upload_id)
            raise FileToolError('CHECKSUM_MISMATCH', 'size or sha256 differs; upload discarded')
        result = self.files.write_bytes(job['path'], data, job['overwrite'], identity)
        self._drop(upload_id)
        return {'upload_id': upload_id, **result}

    def abort(self, identity, upload_id):
        self._job(identity, upload_id)
        self._drop(upload_id)
        return {'upload_id': upload_id, 'aborted': True}

    def dispatch(self, identity, args):
        self.purge()
        a = dict(args)
        action = a.pop('action', None)
        allowed = {'begin': {'path', 'size', 'sha256', 'overwrite'}, 'chunk': {'upload_id', 'offset', 'data'},
                   'commit': {'upload_id'}, 'abort': {'upload_id'}}
        if action not in allowed or set(a) - allowed[action]:
            raise FileToolError('INVALID_ARGUMENT', 'action begin|chunk|commit|abort with its own fields')
        try:
            return getattr(self, action)(identity, **a)
        except TypeError:
            raise FileToolError('INVALID_ARGUMENT', 'missing or unexpected parameters') from None

    def owned_by(self, identity):
        return [uid for uid, j in self.jobs.items() if j['owner'] == identity]
