"""Bounded POSIX file tools, Python 3.9, durable rollback, no shell execution.

Trusted configuration is supplied by the agent, never by tool arguments. All
descent uses directory descriptors and O_NOFOLLOW. User symlinks are rejected.
Callers must wire cross-client locks through lock_provider for a live deployment.
"""
import contextlib
import difflib
import fcntl
import hashlib
import json
import os
import re
import stat
import time
import uuid


class FileToolError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details

    def result(self):
        return {"error": {"code": self.code, "message": str(self), **self.details}}


class FileTools:
    def __init__(self, allowed_roots, state_root, denied_roots=(), lock_provider=None,
                 max_file_bytes=8 * 1024 * 1024, max_chunk_bytes=256 * 1024,
                 max_results=1000, deadline_seconds=15):
        if any(not isinstance(r, str) or not os.path.isabs(r) for r in allowed_roots):
            raise ValueError('absolute roots required')
        self.aliases = sorted([(os.path.normpath(r), os.path.realpath(r)) for r in allowed_roots],
                              key=lambda item: len(item[0]), reverse=True)
        self.roots = sorted({r[1] for r in self.aliases}, key=len, reverse=True)
        if not self.roots or any(not os.path.isabs(r) or r == '/' for r in self.roots):
            raise ValueError('explicit narrow absolute roots required')
        self.state = os.path.realpath(state_root)
        self.denied = tuple(os.path.realpath(r) for r in denied_roots) + (self.state,)
        self.lock_provider = lock_provider
        self.max_file = max_file_bytes
        self.max_chunk = max_chunk_bytes
        self.max_results = max_results
        self.deadline = deadline_seconds
        for r in self.roots:
            if not os.path.isdir(r):
                raise ValueError('allowed root must already exist: ' + r)
            if any(self._inside(r, d) for d in self.denied):
                raise ValueError('allowed root overlaps a denied directory')
        os.makedirs(self.state, mode=0o700, exist_ok=True)
        st = os.stat(self.state)
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise ValueError('rollback state must be private and owned by agent')
        self.state_fd = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.root_fds = {r: os.open(r, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) for r in self.roots}

    def close(self):
        for fd in list(self.root_fds.values()) + [self.state_fd]:
            os.close(fd)
        self.root_fds.clear()

    @staticmethod
    def _inside(path, root):
        return path == root or path.startswith(root.rstrip('/') + '/')

    def _path(self, path, allow_root=True):
        if not isinstance(path, str) or not os.path.isabs(path) or '\0' in path or len(path.encode('utf-8')) > 4096:
            raise FileToolError('INVALID_PATH', 'absolute path required')
        if '..' in path.split('/'):
            raise FileToolError('INVALID_PATH', 'parent traversal is rejected')
        path = os.path.normpath(path)
        # Canonicalize only administrator-approved root aliases (e.g. /tmp or
        # /var on macOS); never resolve untrusted descendant symlinks.
        for alias, real in self.aliases:
            if self._inside(path, alias):
                path = real + path[len(alias):]
                break
        if any(self._inside(path, d) for d in self.denied):
            raise FileToolError('ACCESS_DENIED', 'protected path')
        for root in self.roots:
            if self._inside(path, root):
                now = os.stat(root, follow_symlinks=False)
                pinned = os.fstat(self.root_fds[root])
                if (now.st_dev, now.st_ino) != (pinned.st_dev, pinned.st_ino):
                    raise FileToolError('ROOT_CHANGED', 'allowed root changed; restart after review')
                if path == root and not allow_root:
                    raise FileToolError('ACCESS_DENIED', 'cannot mutate an allowed root')
                parts = path[len(root):].strip('/').split('/') if path != root else []
                if len(parts) > 64:
                    raise FileToolError('LIMIT', 'path nesting exceeds 64 components')
                return path, root, parts
        raise FileToolError('ACCESS_DENIED', 'path outside allowed roots')

    @contextlib.contextmanager
    def _parent(self, path):
        path, root, parts = self._path(path, allow_root=False)
        fd = os.dup(self.root_fds[root])
        try:
            for part in parts[:-1]:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
            yield fd, parts[-1]
        except OSError as exc:
            if exc.errno in (20, 40):
                raise FileToolError('SYMLINK_OR_NOT_DIRECTORY', 'symlink or non-directory in path') from None
            raise
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def _directory(self, path):
        path, root, parts = self._path(path)
        fd = os.dup(self.root_fds[root])
        try:
            for part in parts:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
            yield fd
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def _locked(self, paths, session_id):
        if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}', session_id):
            raise FileToolError('INVALID_SESSION', 'trusted session identity required')
        for path in paths:
            self._path(path, allow_root=False)
        # Serializes durable journal changes across agent processes. The optional
        # provider additionally participates in the existing mac_control lock tree.
        fd = os.open('guard', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.state_fd)
        try:
            end = time.monotonic() + 3
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= end:
                        raise FileToolError('LOCK_BUSY', 'file operation already in progress')
                    time.sleep(0.02)
            with contextlib.ExitStack() as stack:
                self._check_journal()
                if self.lock_provider:
                    for p in sorted(set(paths)):
                        stack.enter_context(self.lock_provider(session_id, p))
                yield
        finally:
            os.close(fd)

    def _check_journal(self):
        count, total = 0, 0
        with os.scandir(self.state_fd) as iterator:
            for item in iterator:
                count += 1
                if count > 2048:
                    raise FileToolError('JOURNAL_LIMIT', 'rollback storage requires reviewed archival')
                st = item.stat(follow_symlinks=False)
                if not stat.S_ISREG(st.st_mode):
                    raise FileToolError('JOURNAL_CORRUPT', 'unexpected rollback state entry')
                total += st.st_size
                if total > 128 * 1024 * 1024:
                    raise FileToolError('JOURNAL_LIMIT', 'rollback storage exceeds 128 MiB')
                if re.fullmatch(r'[a-f0-9]{32}\.json', item.name):
                    fd = os.open(item.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.state_fd)
                    with os.fdopen(fd, 'r') as handle:
                        record = json.loads(handle.read(1024 * 1024))
                    if record.get('status') not in ('committed', 'rolled_back'):
                        raise FileToolError('RECOVERY_REQUIRED', 'interrupted operation requires reviewed recovery',
                                            operation_id=record.get('operation_id'))
        return count, total

    @staticmethod
    def _metadata(st):
        return {'mode': stat.S_IMODE(st.st_mode), 'uid': st.st_uid, 'gid': st.st_gid,
                'atime_ns': st.st_atime_ns, 'mtime_ns': st.st_mtime_ns}

    def _read(self, path):
        with self._parent(path) as (parent, name):
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except OSError as exc:
                if exc.errno == 40:
                    raise FileToolError('SYMLINK', 'symlinks are rejected') from None
                raise
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode):
                    raise FileToolError('NOT_REGULAR_FILE', 'regular file required')
                if st.st_size > self.max_file:
                    raise FileToolError('LIMIT', 'file exceeds bounded size', max_bytes=self.max_file)
                chunks, count = [], 0
                while True:
                    chunk = os.read(fd, min(65536, self.max_file + 1 - count))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    count += len(chunk)
                    if count > self.max_file:
                        raise FileToolError('LIMIT', 'file grew beyond size limit')
                return b''.join(chunks), self._metadata(st)
            finally:
                os.close(fd)

    @staticmethod
    def _text(data):
        if b'\0' in data:
            raise FileToolError('BINARY_FILE', 'binary file: text tool cannot decode it')
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            raise FileToolError('BINARY_FILE', 'file is not UTF-8 text') from None

    def read_file(self, path, offset=0, length=1000):
        if type(offset) is not int or type(length) is not int or not 0 <= length <= 10000:
            raise FileToolError('INVALID_ARGUMENT', 'offset/length must be integers; length 0..10000')
        data, _ = self._read(path)
        lines = self._text(data).splitlines(keepends=True)
        start = max(0, len(lines) + offset) if offset < 0 else min(offset, len(lines))
        returned, count = [], 0
        for line in lines[start:start + length]:
            size = len(line.encode('utf-8'))
            if count + size > self.max_chunk:
                if not returned:
                    raise FileToolError('LIMIT', 'single line exceeds response limit')
                break
            returned.append(line)
            count += size
        return {'path': path, 'content': ''.join(returned), 'offset': start,
                'lines_returned': len(returned), 'total_lines': len(lines),
                'next_offset': start + len(returned), 'truncated': start + len(returned) < len(lines)}

    def read_multiple_files(self, paths):
        if not isinstance(paths, list) or not 1 <= len(paths) <= 20:
            raise FileToolError('INVALID_ARGUMENT', 'paths requires 1..20 files')
        results, remaining = [], self.max_chunk
        for path in paths:
            try:
                value = self.read_file(path)
                size = len(value['content'].encode('utf-8'))
                if size > remaining:
                    raise FileToolError('LIMIT', 'batch response budget exhausted')
                remaining -= size
                results.append({'path': path, 'success': True, **value})
            except (FileToolError, OSError) as exc:
                error = exc.result()['error'] if isinstance(exc, FileToolError) else {'code': 'IO_ERROR', 'message': type(exc).__name__}
                results.append({'path': path, 'success': False, 'error': error})
        return {'files': results}

    def _snapshot(self, path):
        try:
            with self._parent(path) as (fd, name):
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(st.st_mode):
                    raise FileToolError('SYMLINK', 'symlinks are rejected')
                if stat.S_ISDIR(st.st_mode):
                    return {'kind': 'directory', 'metadata': self._metadata(st)}
            data, meta = self._read(path)
            return {'kind': 'file', 'data': data, 'metadata': meta}
        except FileNotFoundError:
            return {'kind': 'missing'}

    def _signature(self, path):
        s = self._snapshot(path)
        if s['kind'] == 'file':
            return {'kind': 'file', 'sha256': hashlib.sha256(s['data']).hexdigest(),
                    'mode': s['metadata']['mode'], 'uid': s['metadata']['uid'], 'gid': s['metadata']['gid']}
        if s['kind'] == 'directory':
            with self._directory(path) as fd:
                st = os.fstat(fd)
                return {'kind': 'directory', 'inode': st.st_ino, 'device': st.st_dev,
                        'mode': stat.S_IMODE(st.st_mode)}
        return {'kind': 'missing'}

    def _state_write(self, name, data):
        temp = uuid.uuid4().hex + '.tmp'
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.state_fd)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, name, src_dir_fd=self.state_fd, dst_dir_fd=self.state_fd)
            os.fsync(self.state_fd)
        finally:
            try:
                os.unlink(temp, dir_fd=self.state_fd)
            except FileNotFoundError:
                pass

    def _record(self, record):
        data = json.dumps(record, sort_keys=True).encode()
        if len(data) > 1024 * 1024:
            raise FileToolError('JOURNAL_LIMIT', 'operation record exceeds limit')
        self._state_write(record['operation_id'] + '.json', data)

    def _begin(self, action, paths, session_id):
        rid = uuid.uuid4().hex
        entries = []
        snapshots = [(path, self._snapshot(path)) for path in paths]
        count, total = self._check_journal()
        reserve = sum(len(snap.get('data', b'')) for _, snap in snapshots) + 1024 * 1024
        if total + reserve > 128 * 1024 * 1024 or count + len(paths) + 2 > 2048:
            raise FileToolError('JOURNAL_LIMIT', 'not enough rollback budget; reviewed archival required')
        for i, (path, snap) in enumerate(snapshots):
            if 'data' in snap:
                backup = rid + '.' + str(i) + '.bin'
                self._state_write(backup, snap.pop('data'))
                snap['backup'] = backup
            entries.append({'path': path, **snap})
        r = {'operation_id': rid, 'action': action, 'session_id': session_id,
             'created_at': time.time(), 'status': 'prepared', 'before': entries}
        self._record(r)
        return r

    def _finish(self, r):
        r['after'] = {e['path']: self._signature(e['path']) for e in r['before']}
        r['status'] = 'committed'
        self._record(r)
        return {'operation_id': r['operation_id'], 'rollback_persistent': True}

    def _atomic_file(self, path, data, metadata=None):
        with self._parent(path) as (fd, name):
            temp = '.mcp-write-' + uuid.uuid4().hex
            output = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                with os.fdopen(output, 'wb') as f:
                    f.write(data)
                    f.flush()
                    if metadata:
                        st = os.fstat(f.fileno())
                        if (st.st_uid, st.st_gid) != (metadata['uid'], metadata['gid']):
                            os.fchown(f.fileno(), metadata['uid'], metadata['gid'])
                        os.fchmod(f.fileno(), metadata['mode'])
                        os.utime(f.fileno(), ns=(metadata['atime_ns'], metadata['mtime_ns']))
                    os.fsync(f.fileno())
                os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
            finally:
                try:
                    os.unlink(temp, dir_fd=fd)
                except FileNotFoundError:
                    pass

    def write_file(self, path, content, mode='rewrite', session_id=None):
        if mode not in ('rewrite', 'append') or not isinstance(content, str):
            raise FileToolError('INVALID_ARGUMENT', 'mode rewrite|append and string content required')
        data = content.encode('utf-8')
        if len(data) > self.max_chunk:
            raise FileToolError('LIMIT', 'chunk too large; append smaller chunks')
        with self._locked([path], session_id):
            before = self._snapshot(path)
            if before['kind'] == 'directory':
                raise FileToolError('NOT_REGULAR_FILE', 'cannot write a directory')
            if mode == 'append' and before['kind'] == 'file':
                self._text(before['data'])
                data = before['data'] + data
            if len(data) > self.max_file:
                raise FileToolError('LIMIT', 'result exceeds file size limit')
            r = self._begin('write_file', [path], session_id)
            meta = before.get('metadata')
            if meta:
                meta = dict(meta, mtime_ns=time.time_ns())
            self._atomic_file(path, data, meta)
            return {'path': path, 'bytes_written': len(data), **self._finish(r)}

    def edit_block(self, file_path, old_string, new_string, expected_replacements=1, session_id=None):
        if not isinstance(old_string, str) or not old_string or not isinstance(new_string, str):
            raise FileToolError('INVALID_ARGUMENT', 'non-empty old_string and string new_string required')
        if type(expected_replacements) is not int or not 1 <= expected_replacements <= 1000:
            raise FileToolError('INVALID_ARGUMENT', 'expected_replacements must be 1..1000')
        if len((old_string + new_string).encode()) > self.max_chunk:
            raise FileToolError('LIMIT', 'edit text exceeds request limit')
        with self._locked([file_path], session_id):
            data, meta = self._read(file_path)
            text = self._text(data)
            found = text.count(old_string)
            if found != expected_replacements:
                details = {'occurrences_found': found, 'expected_replacements': expected_replacements}
                if found == 0:
                    # Bounded line-level hint; never a quadratic full-file diff.
                    lines = text.splitlines()[:1000]
                    hint = difflib.get_close_matches(old_string[:512], [s[:512] for s in lines], n=1, cutoff=0.1)
                    details['closest_text'] = hint[0] if hint else ''
                raise FileToolError('REPLACEMENT_COUNT', 'occurrence count differs; file unchanged', **details)
            out = text.replace(old_string, new_string).encode('utf-8')
            if len(out) > self.max_file:
                raise FileToolError('LIMIT', 'edited file exceeds size limit')
            r = self._begin('edit_block', [file_path], session_id)
            self._atomic_file(file_path, out, dict(meta, mtime_ns=time.time_ns()))
            return {'path': file_path, 'replacements': found, **self._finish(r)}

    def create_directory(self, path, session_id=None):
        with self._locked([path], session_id):
            path, root, parts = self._path(path, allow_root=False)
            fd = os.dup(self.root_fds[root])
            missing, current = [], root
            try:
                for i, part in enumerate(parts):
                    current += '/' + part
                    try:
                        new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    except FileNotFoundError:
                        missing = [root + '/' + '/'.join(parts[:j + 1]) for j in range(i, len(parts))]
                        break
                    os.close(fd)
                    fd = new
            finally:
                os.close(fd)
            # Always provide a persistent operation, including an idempotent call.
            r = self._begin('create_directory', missing, session_id)
            for p in missing:
                with self._parent(p) as (fd, name):
                    os.mkdir(name, 0o750, dir_fd=fd)
                    os.fsync(fd)
            return {'path': path, 'created': bool(missing), **self._finish(r)}

    def move_file(self, source, destination, session_id=None):
        if os.path.normpath(source) == os.path.normpath(destination):
            raise FileToolError('INVALID_ARGUMENT', 'source and destination must differ')
        with self._locked([source, destination], session_id):
            src = self._snapshot(source)
            if src['kind'] != 'file':
                raise FileToolError('NOT_REGULAR_FILE', 'phase 1 move supports regular files only')
            if self._snapshot(destination)['kind'] != 'missing':
                raise FileToolError('DESTINATION_EXISTS', 'destination exists; no overwrite')
            with self._parent(source) as (sfd, sn), self._parent(destination) as (dfd, dn):
                if os.fstat(sfd).st_dev != os.fstat(dfd).st_dev:
                    raise FileToolError('CROSS_DEVICE', 'cross-device move is not supported')
                r = self._begin('move_file', [source, destination], session_id)
                # Exclusive hard-link publication prevents overwriting a destination
                # created by a concurrent external process (rename would overwrite).
                os.link(sn, dn, src_dir_fd=sfd, dst_dir_fd=dfd, follow_symlinks=False)
                if not stat.S_ISREG(os.stat(dn, dir_fd=dfd, follow_symlinks=False).st_mode):
                    os.unlink(dn, dir_fd=dfd)
                    raise FileToolError('SYMLINK', 'source changed during move')
                os.fsync(dfd)
                os.unlink(sn, dir_fd=sfd)
                os.fsync(sfd)
            return {'source': source, 'destination': destination, **self._finish(r)}

    def rollback_file(self, operation_id, session_id=None):
        if not isinstance(operation_id, str) or not re.fullmatch(r'[a-f0-9]{32}', operation_id):
            raise FileToolError('INVALID_ARGUMENT', 'invalid operation_id')
        fd = os.open(operation_id + '.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.state_fd)
        with os.fdopen(fd, 'r') as f:
            r = json.load(f)
        paths = [e['path'] for e in r['before']]
        with self._locked(paths, session_id):
            if r['status'] != 'committed':
                raise FileToolError('ROLLBACK_STATE', 'operation is not committed or was already rolled back')
            for p, signature in r['after'].items():
                if self._signature(p) != signature:
                    raise FileToolError('ROLLBACK_CONFLICT', 'file changed since operation; rollback refused', path=p)
            # Check every created directory before removing any. Descendants created
            # by this operation are expected; anything else blocks the whole rollback.
            created = {e['path'] for e in r['before'] if e['kind'] == 'missing' and r['after'][e['path']]['kind'] == 'directory'}
            for p in created:
                with self._directory(p) as fd:
                    if any(p + '/' + name not in created for name in os.listdir(fd)):
                        raise FileToolError('ROLLBACK_CONFLICT', 'created directory is no longer empty', path=p)
            r['status'] = 'rollback_prepared'
            self._record(r)
            for e in reversed(r['before']):
                p = e['path']
                if e['kind'] == 'missing':
                    with self._parent(p) as (fd, name):
                        try:
                            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                            if stat.S_ISDIR(st.st_mode):
                                os.rmdir(name, dir_fd=fd)
                            else:
                                os.unlink(name, dir_fd=fd)
                            os.fsync(fd)
                        except FileNotFoundError:
                            pass
                elif e['kind'] == 'file':
                    fd = os.open(e['backup'], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.state_fd)
                    with os.fdopen(fd, 'rb') as f:
                        data = f.read(self.max_file + 1)
                    self._atomic_file(p, data, e['metadata'])
            r['status'] = 'rolled_back'
            r['rolled_back_at'] = time.time()
            self._record(r)
            return {'operation_id': operation_id, 'rolled_back': True, 'persistent': True}

    def list_directory(self, path, depth=2):
        if type(depth) is not int or not 0 <= depth <= 8:
            raise FileToolError('INVALID_ARGUMENT', 'depth must be 0..8')
        entries, truncated = [], False
        end = time.monotonic() + self.deadline

        def visit(p, level, prefix=''):
            nonlocal truncated
            if level >= depth:
                return
            with self._directory(p) as fd:
                # Do not allocate an unbounded list for very large directories.
                with os.scandir(fd) as iterator:
                    for item in iterator:
                        if len(entries) >= self.max_results or time.monotonic() > end:
                            truncated = True
                            return
                        name = prefix + item.name
                        if item.is_symlink():
                            entries.append('[SYMLINK BLOCKED] ' + name)
                            continue
                        child = p.rstrip('/') + '/' + item.name
                        if any(self._inside(child, d) for d in self.denied):
                            continue
                        directory = item.is_dir(follow_symlinks=False)
                        entries.append(('[DIR] ' if directory else '[FILE] ') + name)
                        if directory:
                            visit(child, level + 1, name + '/')
                            if truncated:
                                return
        self._path(path)
        visit(path, 0)
        return {'path': path, 'entries': entries, 'truncated': truncated}

    def get_file_info(self, path):
        normalized, root, parts = self._path(path)
        if not parts:
            st = os.fstat(self.root_fds[root])
        else:
            with self._parent(path) as (fd, name):
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISLNK(st.st_mode):
            raise FileToolError('SYMLINK', 'symlinks are rejected')
        value = {'path': path, 'size': st.st_size, 'permissions': oct(stat.S_IMODE(st.st_mode)),
                 'uid': st.st_uid, 'gid': st.st_gid, 'modified': st.st_mtime,
                 'metadata_changed': st.st_ctime, 'created': getattr(st, 'st_birthtime', None),
                 'creation_time_available': hasattr(st, 'st_birthtime'),
                 'is_directory': stat.S_ISDIR(st.st_mode), 'line_count': None}
        if stat.S_ISREG(st.st_mode) and st.st_size <= self.max_file:
            data, _ = self._read(path)
            try:
                value['line_count'] = len(self._text(data).splitlines())
                value['is_text'] = True
            except FileToolError:
                value['is_text'] = False
        return value

    def dispatch(self, name, arguments, session_id):
        a = dict(arguments)
        if 'machine' in a or 'session_id' in a:
            raise FileToolError('INVALID_ARGUMENT', 'routing and identity are supplied by gateway')
        methods = {'read_file', 'read_multiple_files', 'write_file', 'edit_block',
                   'list_directory', 'create_directory', 'move_file', 'get_file_info', 'rollback_file'}
        if name not in methods:
            raise FileToolError('UNKNOWN_TOOL', 'unknown file tool')
        if name in {'write_file', 'edit_block', 'create_directory', 'move_file', 'rollback_file'}:
            a['session_id'] = session_id
        try:
            return getattr(self, name)(**a)
        except TypeError:
            raise FileToolError('INVALID_ARGUMENT', 'missing or unexpected parameters') from None
