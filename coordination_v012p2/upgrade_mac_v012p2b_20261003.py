#!/usr/bin/env python3
"""Hash-pinned local update of only the central personal-Mac agent: MCP Andrea v0.12 p2."""
import base64,contextlib,fcntl,hashlib,json,os,plistlib,re,stat,subprocess,sys,tempfile,time,zlib
from pathlib import Path
ROOT=Path('/Library/MCPAndreaMacMioV09')
BASE=ROOT/'code'
SELF=ROOT/'upgrade_v012p2b_20261003.py'
BACKUP=ROOT/'backup/v012p2b_20261003'
RECEIPT=ROOT/'v012p2b_20261003_receipt.json'
TEST_CODE=ROOT/'preflight-v012p2b_20261003'
TEST_DATA=Path('/Users/Shared/MCPAndreaMacMio/preflight-v012p2b_20261003')
GUARD=ROOT/'state/operations/guard'
LABEL='it.andreababini.mcp-mac-mio-v09'
PLIST=Path('/Library/LaunchDaemons')/(LABEL+'.plist')
PLIST_SHA='c355532f913809d9a183e0e4b4a55e226dfc850914dbe4992582d5d3bf7fd406'
PYTHON='/usr/bin/python3'
OLD_VERSION='0.12-personal-1'
NEW_VERSION='0.12-personal-2'
PAYLOAD={}
TESTS={}
SMOKE_INFO={}
SYSTEM_AGENTS=frozenset({'/usr/sbin/distnoted agent','/usr/sbin/cfprefsd agent','/usr/libexec/trustd --agent',
    '/usr/libexec/secinitd','/usr/libexec/lsd','/usr/libexec/containermanagerd'})
ORIGINAL={'file_tools.py': 'c4e8af4bf9b6542e02c1c6c442160998125335010a2b1009becb220146a01e76', 'mac_agent.py': 'c3db14ba1fea17a0b6240d59ebac071750af4629bc1f6e5466bb94c4b66f594c', 'mac_child.py': 'f5b37188587c1459633d4eefb3ebc250798609272b83b4472247cca3b125b5bd', 'mac_shell.py': '5ebae9f1e668a6b7f9801d5014ff66deef308ceea4ec6acfa22b2c6839606534', 'net_proxy.py': 'a9ae31721b4eef732ce5cab4dfc15836224d5f7f5d33b3cd527ca3361ed8822e'}
DEPENDENCIES={'agent_shell.py': 'd62822814d97c52468ca8aad4a43fa1bf8e424b8cd8200ac88ea4e2c9c33e21c', 'file_schema.py': 'a981512019127689a443ca2717968d76e1509f4366075d5b39f6eee28218c1a4', 'mac_clock.py': '6553b061c51e2da286296231538796dd086404b1dbacca37bd9299e2628dae07', 'mac_guard.py': '8d3f7afe80daae81e8f3a3471229423d14777eb84358a3f57621e74149dc57bc', 'mac_policy.py': '70d03138610b2f7a92c0f5343c343abad2c1587479229670ed69f91205872246', 'mac_watchdog.py': '66dc9cbe74dd74931979200a9eda4032461a31c1687f5a2ca64a4441f21c4c99', 'search_schema.py': 'c6d111d440eec78bb08e27673fd832479f02446ac2abc25fb5237e12d47ee20d', 'search_tools.py': 'f5722cdf394ad1b98575e5f00d6af483a37c6c456adb7465e1213cdc002a625f', 'shell_common.py': '254dd32f26295b9376b1201cf7449832b8d9927018d0b9e208cc2a950b954f3f', 'upload_tools.py': 'fbea947e87afd04e7bbf54d1075c3c2852db3a415ac65e65e6fffde07834abc7', 'work_schema.py': '40eaf6a37998e42d9cdd6e3c28853e1f22cfeff1fc9b16bec8d391abc04817df', 'work_sessions.py': '4a7b736ef6d915c2439cd8aa63e09f0d40410325fa5e9387070f807d518b1861'}
TEST_NAMES=['file_tools.py', 'mac_agent.py', 'mac_child.py', 'mac_shell.py', 'net_proxy.py', 'agent_shell.py', 'file_schema.py', 'mac_clock.py', 'mac_guard.py', 'mac_policy.py', 'mac_watchdog.py', 'search_schema.py', 'search_tools.py', 'shell_common.py', 'upload_tools.py', 'work_schema.py', 'work_sessions.py', 'test_work_core.py', 'test_search.py', 'test_v012.py', 'test_files_v012.py', 'mac_v012_selftest.py', 'cg_tools.py']
SOURCE_SHA={'file_tools.py': '002d2382b7670e6a9a468facbb951c1f9a20431c70fbba2d8c370fffea5c24cc', 'mac_agent.py': '2063b597142d9a7bb6fe11aa1ccc36e8940601c9ff2d87286269a3b181040f85', 'mac_child.py': '24d7c1701eeab38885fbf51ea7b3bb0d368ebe102c1740c97c95efa6c6f8de1e', 'mac_shell.py': '79c8595ddf87e1076b64b782a0a366de5d7c30de89b1b697c99581e1e6de9c14', 'net_proxy.py': '550deb2441af4fbbd3b89ed7e8204339e439e1049c98ca2a01e6e73c50bfd48c', 'test_work_core.py': '08aa60ad5317db32fa515ba21a834b3ae22dbed014b8a240168deefa7ea15380', 'test_search.py': '907e711f24fdf773db95d5c36d73702db4331d3ced1375cc4bfe43ee5b88db5c', 'test_v012.py': 'cab24eee0012e8218188c133ebdfb44d7670263cbd70fc53e3392eeea4a9e8e5', 'test_files_v012.py': 'b23873ec8879851d36d6032a8fe025833934896582d66b0c45dee983ef951068', 'mac_v012_selftest.py': '0b10373a80a0b785d3f80a4b64e82e3d5f796c7ec043489d1a8fc0d247a62d66', 'cg_tools.py': '0df2f955e3de20a5fb13565fcb347c52c8c738963f8c418de0873dc0c123fbd1'}
SOURCES={
'file_tools.py': r'''"""Bounded POSIX file tools, Python 3.9, durable rollback, no shell execution.

Trusted configuration is supplied by the agent, never by tool arguments. All
descent uses directory descriptors and O_NOFOLLOW. User symlinks are rejected.
Callers must wire cross-client locks through lock_provider for a live deployment.
"""
import base64
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

    @contextlib.contextmanager
    def _journaled(self, r, undo=None):
        # A failure after _begin must close the record; a 'prepared' record left
        # behind blocks every later operation until reviewed recovery.
        try:
            yield
        except BaseException:
            if undo:
                undo()
            self._abort(r)
            raise

    def _require_parent(self, path):
        try:
            with self._parent(path):
                pass
        except FileNotFoundError:
            raise FileToolError('PARENT_MISSING', 'parent directory does not exist; create it first') from None

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
            self._require_parent(path)
            r = self._begin('write_file', [path], session_id)
            meta = before.get('metadata')
            if meta:
                meta = dict(meta, mtime_ns=time.time_ns())
            # _atomic_file publishes with one rename: on failure the target is unchanged.
            with self._journaled(r):
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
            with self._journaled(r):
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
            made = []
            with self._journaled(r, lambda: self._undo_created(made)):
                for p in missing:
                    with self._parent(p) as (fd, name):
                        os.mkdir(name, 0o750, dir_fd=fd)
                        made.append(p)
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
                stage = []

                def undo():
                    # Put the source back if it was already unlinked, then drop the new link.
                    if 'unlinked' in stage:
                        os.link(dn, sn, src_dir_fd=dfd, dst_dir_fd=sfd, follow_symlinks=False)
                    if 'linked' in stage:
                        with contextlib.suppress(FileNotFoundError):
                            os.unlink(dn, dir_fd=dfd)

                with self._journaled(r, undo):
                    # Exclusive hard-link publication prevents overwriting a destination
                    # created by a concurrent external process (rename would overwrite).
                    os.link(sn, dn, src_dir_fd=sfd, dst_dir_fd=dfd, follow_symlinks=False)
                    stage.append('linked')
                    if not stat.S_ISREG(os.stat(dn, dir_fd=dfd, follow_symlinks=False).st_mode):
                        raise FileToolError('SYMLINK', 'source changed during move')
                    os.fsync(dfd)
                    os.unlink(sn, dir_fd=sfd)
                    stage.append('unlinked')
                    os.fsync(sfd)
            return {'source': source, 'destination': destination, **self._finish(r)}

    MAX_TREE = 500
    MAX_COPY_BYTES = 64 * 1024 * 1024
    MAX_BINARY_CHUNK = 196608

    def _make_directory(self, path, mode):
        with self._parent(path) as (fd, name):
            os.mkdir(name, 0o700, dir_fd=fd)
            new = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                os.fchmod(new, mode)
            finally:
                os.close(new)
            os.fsync(fd)

    def _set_mode(self, path, mode):
        with self._parent(path) as (fd, name):
            new = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                if not stat.S_ISREG(os.fstat(new).st_mode):
                    raise FileToolError('NOT_REGULAR_FILE', 'regular file required')
                os.fchmod(new, mode)
                os.fsync(new)
            finally:
                os.close(new)

    def _tree(self, path):
        """Pre-order (path, kind, size) list of a bounded tree without links."""
        end = time.monotonic() + self.deadline
        items = []

        def visit(p):
            with self._parent(p) as (fd, name):
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(st.st_mode):
                raise FileToolError('SYMLINK', 'symlinks are rejected', path=p)
            if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                raise FileToolError('NOT_REGULAR_FILE', 'only regular files and directories are supported', path=p)
            if any(self._inside(p, d) for d in self.denied):
                raise FileToolError('ACCESS_DENIED', 'protected path', path=p)
            items.append((p, 'directory' if stat.S_ISDIR(st.st_mode) else 'file', st.st_size))
            if len(items) > self.MAX_TREE:
                raise FileToolError('LIMIT', 'tree exceeds entry limit; use the shell', max_entries=self.MAX_TREE)
            if time.monotonic() > end:
                raise FileToolError('LIMIT', 'tree scan exceeded time limit')
            if stat.S_ISDIR(st.st_mode):
                with self._directory(p) as dfd:
                    names = sorted(os.listdir(dfd))
                for child in names:
                    visit(p.rstrip('/') + '/' + child)

        visit(self._path(path, allow_root=False)[0])
        return items

    def _undo_created(self, paths):
        # Best-effort reversal of a failed copy/upload before it is committed.
        for p in reversed(paths):
            with contextlib.suppress(FileNotFoundError, FileToolError), self._parent(p) as (fd, name):
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(st.st_mode):
                    os.rmdir(name, dir_fd=fd)
                else:
                    os.unlink(name, dir_fd=fd)
                os.fsync(fd)

    def _abort(self, r):
        r['status'] = 'rolled_back'
        r['aborted'] = True
        r['after'] = {}
        r['rolled_back_at'] = time.time()
        self._record(r)

    def delete_path(self, path, session_id=None):
        with self._locked([path], session_id):
            items = self._tree(path)
            for p, kind, size in items:
                if kind == 'file' and size > self.max_file:
                    raise FileToolError('LIMIT', 'file too large for a reversible delete; use the shell',
                                        path=p, max_bytes=self.max_file)
            # Backups are read into memory by _begin: bound them before reading.
            if sum(size for _, kind, size in items if kind == 'file') > self.MAX_COPY_BYTES:
                raise FileToolError('LIMIT', 'tree too large for a reversible delete; use the shell',
                                    max_total_bytes=self.MAX_COPY_BYTES)
            r = self._begin('delete_path', [p for p, _, _ in items], session_id)
            try:
                for p, kind, _ in reversed(items):
                    with self._parent(p) as (fd, name):
                        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if stat.S_ISDIR(st.st_mode) != (kind == 'directory'):
                            raise FileToolError('CHANGED', 'tree changed during delete', path=p)
                        if kind == 'directory':
                            os.rmdir(name, dir_fd=fd)
                        else:
                            os.unlink(name, dir_fd=fd)
                        os.fsync(fd)
            except BaseException:
                # Put back what was already removed, then close the record.
                for e in r['before']:
                    if e['kind'] == 'directory' and self._snapshot(e['path'])['kind'] == 'missing':
                        self._make_directory(e['path'], e['metadata']['mode'])
                for e in r['before']:
                    if e['kind'] == 'file' and self._snapshot(e['path'])['kind'] == 'missing':
                        fd = os.open(e['backup'], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.state_fd)
                        with os.fdopen(fd, 'rb') as f:
                            self._atomic_file(e['path'], f.read(self.max_file + 1), e['metadata'])
                self._abort(r)
                raise
            files = sum(1 for _, kind, _ in items if kind == 'file')
            return {'path': path, 'deleted_files': files, 'deleted_directories': len(items) - files,
                    **self._finish(r)}

    def copy_file(self, source, destination, session_id=None):
        src = self._path(source)[0]
        dst = self._path(destination, allow_root=False)[0]
        if self._inside(dst, src) or self._inside(src, dst):
            raise FileToolError('INVALID_ARGUMENT', 'source and destination must not contain each other')
        with self._locked([destination], session_id):
            if self._snapshot(destination)['kind'] != 'missing':
                raise FileToolError('DESTINATION_EXISTS', 'destination exists; no overwrite')
            items = self._tree(source)
            total = sum(size for _, kind, size in items if kind == 'file')
            if total > self.MAX_COPY_BYTES or any(k == 'file' and s > self.max_file for _, k, s in items):
                raise FileToolError('LIMIT', 'copy exceeds size limits; use the shell',
                                    max_total_bytes=self.MAX_COPY_BYTES, max_file_bytes=self.max_file)
            targets = [dst + p[len(src):] for p, _, _ in items]
            r = self._begin('copy_file', targets, session_id)
            try:
                for (p, kind, _), target in zip(items, targets):
                    if kind == 'directory':
                        with self._directory(p) as dfd:
                            mode = stat.S_IMODE(os.fstat(dfd).st_mode)
                        self._make_directory(target, mode | 0o700)
                    else:
                        data, meta = self._read(p)
                        self._atomic_file(target, data)
                        self._set_mode(target, (meta['mode'] | 0o600) & 0o777)
            except BaseException:
                self._undo_created(targets)
                self._abort(r)
                raise
            return {'source': source, 'destination': destination, 'entries': len(items),
                    'bytes_copied': total, **self._finish(r)}

    def read_binary(self, path, offset=0, length=MAX_BINARY_CHUNK):
        if type(offset) is not int or type(length) is not int or offset < 0 or not 1 <= length <= self.MAX_BINARY_CHUNK:
            raise FileToolError('INVALID_ARGUMENT', 'offset >= 0 and length 1..%d required' % self.MAX_BINARY_CHUNK)
        data, _ = self._read(path)
        chunk = data[offset:offset + length]
        return {'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                'offset': min(offset, len(data)), 'length': len(chunk),
                'content_base64': base64.b64encode(chunk).decode('ascii'),
                'eof': offset + len(chunk) >= len(data)}

    def write_bytes(self, path, data, overwrite=False, session_id=None):
        """Journaled binary write used by verified uploads."""
        if not isinstance(data, bytes) or len(data) > self.max_file:
            raise FileToolError('LIMIT', 'binary content exceeds file size limit', max_bytes=self.max_file)
        with self._locked([path], session_id):
            before = self._snapshot(path)
            if before['kind'] == 'directory':
                raise FileToolError('NOT_REGULAR_FILE', 'cannot write a directory')
            if before['kind'] == 'file' and not overwrite:
                raise FileToolError('DESTINATION_EXISTS', 'destination exists; pass overwrite=true')
            self._require_parent(path)
            r = self._begin('upload_file', [path], session_id)
            meta = before.get('metadata')
            with self._journaled(r):
                self._atomic_file(path, data, dict(meta, mtime_ns=time.time_ns()) if meta else None)
            return {'path': path, 'bytes_written': len(data),
                    'sha256': hashlib.sha256(data).hexdigest(), **self._finish(r)}

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
            produced = {e['path'] for e in r['before'] if e['kind'] == 'missing'}
            created = {p for p in produced if r['after'][p]['kind'] == 'directory'}
            for p in created:
                with self._directory(p) as fd:
                    if any(p + '/' + name not in produced for name in os.listdir(fd)):
                        raise FileToolError('ROLLBACK_CONFLICT', 'created directory is no longer empty', path=p)
            r['status'] = 'rollback_prepared'
            self._record(r)
            # Directories removed by the operation come back first, parents
            # before children, so their files can be restored inside them.
            for e in r['before']:
                if e['kind'] == 'directory' and r['after'][e['path']]['kind'] == 'missing':
                    self._make_directory(e['path'], e['metadata']['mode'])
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
                   'list_directory', 'create_directory', 'move_file', 'get_file_info', 'rollback_file',
                   'delete_path', 'copy_file', 'read_binary'}
        if name not in methods:
            raise FileToolError('UNKNOWN_TOOL', 'unknown file tool')
        if name in {'write_file', 'edit_block', 'create_directory', 'move_file', 'rollback_file',
                    'delete_path', 'copy_file'}:
            a['session_id'] = session_id
        try:
            return getattr(self, name)(**a)
        except TypeError:
            raise FileToolError('INVALID_ARGUMENT', 'missing or unexpected parameters') from None
''',
'mac_agent.py': r'''#!/usr/bin/env python3
"""Dedicated non-admin agent; root-owned code, private state, offline shell."""
import asyncio
import contextlib
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import stat
import subprocess
import sys
import time

CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / 'vendor'))
from file_tools import FileTools
from file_schema import FILE_NAMES
from search_tools import SearchTools, SEARCH_NAMES
from agent_shell import AgentShell
from work_sessions import WorkSessions, MUTATIONS
from work_schema import WORK_NAMES
from upload_tools import Uploads
from net_proxy import ALLOWED_HOSTS, PROFILES
from mac_guard import require_identity, stop_dedicated_children
from mac_policy import profile

BASE = Path('/Library/MCPAndreaMacMioV09')
STATE = BASE / 'state'
WORK = Path('/Users/Shared/MCPAndreaMacMio/workspace')
URL = 'wss://mcp.andreababini.it/agent/ws/mac_mio'
VERSION = '0.12-personal-2'
LOG = logging.getLogger('mcp-andrea-mac-mio')
RID = re.compile(r'[a-f0-9]{32}')
CALLER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}')
COMMANDS = {'sw_vers': ('/usr/bin/sw_vers',)}


def baseline_argv(command, work):
    return ['/usr/bin/sandbox-exec','-p',profile(str(work))]+list(COMMANDS[command])


async def status_output(proc, timeout=15):
    task=asyncio.create_task(proc.communicate())
    timed_out=False
    try:
        output,_=await asyncio.wait_for(asyncio.shield(task),timeout)
    except asyncio.TimeoutError:
        timed_out=True
        with contextlib.suppress(ProcessLookupError):os.killpg(proc.pid,signal.SIGKILL)
        output,_=await asyncio.wait_for(task,3)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):os.killpg(proc.pid,signal.SIGKILL)
        with contextlib.suppress(Exception,asyncio.CancelledError):await asyncio.wait_for(task,3)
        raise
    return {'exit_code':proc.returncode,'output':output[-65536:].decode(errors='replace'),
            'truncated':len(output)>65536,'timed_out':timed_out}


def trusted_token():
    path = BASE / 'private/agent.token'
    for p in [path.parent] + list(path.parent.parents):
        s = p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise PermissionError('unsafe credential directory')
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r') as f:
        s = os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_gid != 5000 or s.st_mode & 0o137 or s.st_nlink != 1:
            raise PermissionError('unsafe credential file')
        token = f.read(257).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{43,256}', token):
        raise ValueError('invalid agent credential')
    return token


class Dispatcher:
    def __init__(self, work=WORK, state=STATE):
        self.work, self.state = Path(work), Path(state)
        self.files = FileTools([str(self.work)], str(self.state / 'operations'))
        self.shell = AgentShell(self.files, str(self.work), str(self.state / 'shell-logs'), capable=True)
        self.logs = FileTools([str(self.state / 'shell-logs')], str(self.state / 'log-reader'), max_file_bytes=16*1024*1024)
        self.search = SearchTools(self.files)
        self.recent = []
        self.work_sessions = WorkSessions(str(self.state / 'work-sessions'), self.files)
        self.files.lock_provider = self.work_sessions.lock_provider
        self.uploads = Uploads(self.files, str(self.state / 'uploads'))
        self.work_watchdog = None

    def file_call(self, op, args, identity):
        self.search.guard_mutation(op)
        path = args.get('path')
        log_root = str(self.state / 'shell-logs')
        is_log = isinstance(path, str) and (path == log_root or path.startswith(log_root + '/'))
        engine = self.logs if is_log else self.files
        if is_log and op not in ('read_file', 'get_file_info', 'list_directory', 'read_binary'):
            raise PermissionError('shell logs are read-only')
        if op == 'read_file' and not ({'offset', 'length'} & set(args)):
            if set(args) - {'path', 'max_bytes'}:
                raise ValueError('unexpected read arguments')
            limit = args.get('max_bytes', 262144)
            if type(limit) is not int or not 1 <= limit <= 1048576:
                raise ValueError('invalid read size')
            data, _ = engine._read(path); engine._text(data)
            return {'path': path, 'content': data[:limit].decode('utf-8', errors='replace'),
                    'bytes_returned': min(len(data), limit), 'truncated': len(data) > limit}
        return engine.dispatch(op, args, identity)

    async def baseline(self, args):
        if set(args) - {'command', 'cwd', 'timeout'} or args.get('command') not in COMMANDS:
            raise ValueError('invalid baseline arguments')
        if args.get('cwd') not in (None, str(self.work)):
            raise ValueError('invalid status cwd')
        if self.shell.working()['active_locks']:
            raise PermissionError('use the active shell session before running a separate status command')
        proc = await asyncio.create_subprocess_exec(*baseline_argv(args['command'],self.work),
            stdin=subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            cwd=str(self.work), start_new_session=True,
            env={'PATH': '/usr/bin:/bin', 'HOME': str(self.work), 'CFFIXED_USER_HOME':str(self.work),
                 'TMPDIR': str(self.work / '.tmp')})
        return await status_output(proc)

    async def reap_expired_work(self):
        # The request loop is serialized. Reap BEFORE accepting a new work lock,
        # so an expired shell cannot race a new owner of the same workspace.
        if self.shell.owner:
            try:
                remaining = self.work_sessions.remaining(self.shell.owner, str(self.work))
            except PermissionError:
                remaining = 0
            if remaining <= 0:
                await self.shell.disable()
        active = {x['work_session_id'] for x in self.work_sessions.snapshot()['work_sessions']}
        for job in list(self.search.jobs.values()):
            if job['status'] == 'running' and job['owner'].startswith('work:') and job['owner'][5:] not in active:
                await self.search.stop(job['owner'], job['id'])
        for uid, job in list(self.uploads.jobs.items()):
            if job['owner'][5:] not in active:
                self.uploads._drop(uid)

    async def watch_work(self):
        try:
            while True:
                await asyncio.sleep(.5)
                await self.reap_expired_work()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A corrupt/unavailable coordination store must not leave a shell
            # running under a lease that can no longer be verified.
            await self.shell.disable()
            await self.search.close()
            LOG.exception('work coordination watchdog failed')

    async def work_call(self, op, args, caller):
        a = dict(args)
        action = a.pop('action', None)
        sid = a.pop('work_session_id', None)
        token = a.pop('work_session_token', None)
        if op == 'work_session' and action == 'open':
            if sid is not None or token is not None or set(a) - {'label','minutes'}:
                raise ValueError('unexpected session open arguments')
            return self.work_sessions.open(caller, a.get('label'), a.get('minutes',30))
        identity = self.work_sessions.authenticate(caller, sid, token)
        if op == 'work_session' and action == 'renew':
            if set(a) - {'minutes'}:raise ValueError('unexpected session renew arguments')
            return self.work_sessions.renew(caller,sid,token,a.get('minutes',30))
        if op == 'work_session' and action == 'close' and not a:
            if self.shell.owner == identity:await self.shell.disable()
            for job in list(self.search.jobs.values()):
                if job['owner'] == identity and job['status'] == 'running':
                    await self.search.stop(identity,job['id'])
            for uid in self.uploads.owned_by(identity):self.uploads._drop(uid)
            return self.work_sessions.end(caller,sid,token)
        if op == 'work_lock' and action == 'acquire':
            if set(a)-{'path','minutes'}:raise ValueError('unexpected lock arguments')
            return self.work_sessions.acquire(caller,sid,token,a.get('path'),a.get('minutes',30))
        if op == 'work_lock' and action in ('renew','release'):
            if set(a)-{'lock_id','minutes'} or action=='release' and 'minutes' in a:
                raise ValueError('unexpected lock arguments')
            if action=='release' and self.shell.owner==identity:
                raise PermissionError('disable the session shell before releasing its work lock')
            return self.work_sessions.change_lock(caller,sid,token,a.get('lock_id'),
                                                 a.get('minutes',30) if action=='renew' else None)
        raise ValueError('unsupported work action')

    async def dispatch(self, message):
        if not isinstance(message, dict) or message.get('type') != 'request':
            raise ValueError('invalid request')
        caller, rid = message.get('caller'), message.get('id')
        if not isinstance(caller, str) or not CALLER.fullmatch(caller) or not isinstance(rid, str) or not RID.fullmatch(rid):
            raise PermissionError('authenticated caller and request id required')
        op, args = message.get('op'), message.get('args')
        if not isinstance(args, dict):raise ValueError('arguments must be an object')
        if self.work_watchdog is None or self.work_watchdog.done():
            self.work_watchdog = asyncio.create_task(self.watch_work())
        await self.reap_expired_work()
        args = dict(args)
        work_id = args.get('work_session_id')
        work_token = args.get('work_session_token')
        identity = caller
        ok = False
        try:
            if op not in WORK_NAMES:
                args.pop('work_session_id',None);args.pop('work_session_token',None)
                required = op in MUTATIONS | SEARCH_NAMES | {'enable_full_shell','disable_full_shell','shell_session'} or op=='shell_exec' and args.get('command') not in COMMANDS
                if required or work_id is not None or work_token is not None:
                    identity = self.work_sessions.authenticate(caller,work_id,work_token)
            if op in WORK_NAMES:
                result = await self.work_call(op,args,caller)
                # Successful session/lock calls are recorded under their session.
                sid = result.get('work_session_id') if op=='work_session' and isinstance(result,dict) else work_id
                if isinstance(sid,str):identity = 'work:'+sid
            elif op in SEARCH_NAMES:
                result = await self.search.dispatch(op, args, identity)
            elif op == 'upload_file':
                if args.get('action') == 'commit':self.search.guard_mutation(op)
                result = self.uploads.dispatch(identity, args)
            elif op in FILE_NAMES:
                result = self.file_call(op, args, identity)
            elif op == 'enable_full_shell':
                if 'minutes' not in args or set(args) - {'minutes','network'}:raise ValueError('unexpected enable arguments')
                if args['minutes']*60 > self.work_sessions.remaining(identity,str(self.work)):
                    raise PermissionError('work session and workspace lock must outlast the shell lease')
                result = await self.shell.enable(identity, args['minutes'], args.get('network','none'))
            elif op == 'disable_full_shell' and not args:
                if self.shell.owner is not None and self.shell.owner != identity:
                    raise PermissionError('shell lease belongs to another work session')
                result = await self.shell.disable()
            elif op == 'shell_exec':
                if set(args) - {'command','cwd','timeout'}:raise ValueError('unexpected shell arguments')
                if args.get('command') in COMMANDS:
                    result = await self.baseline(args)
                else:
                    self.work_sessions.remaining(identity,str(self.work))
                    result = await self.shell.execute(identity, args)
            elif op == 'shell_session':
                if set(args) - {'action','command','cwd','data','session_id'}:raise ValueError('unexpected session arguments')
                if args.get('action') == 'start':
                    self.work_sessions.remaining(identity,str(self.work))
                result = await self.shell.session(identity, args)
            elif op == 'who_is_working' and not args:
                result = {**self.shell.working(), 'recent_operations': self.recent[-20:], 'search_version': '0.10.1'}
                result['active_locks'] += self.search.active()
                result.update(self.work_sessions.snapshot())
            else:raise ValueError('unsupported operation')
            ok = True; return result
        finally:
            record = {'time': time.time(), 'caller': caller, 'work_session_id': work_id, 'request_id': rid, 'operation': op, 'ok': ok}
            if op in ('shell_exec', 'shell_session') and isinstance(args.get('command'), str):
                record['command'] = args['command'][:32768]
            LOG.info(json.dumps(record, ensure_ascii=True))
            self.recent.append({k:v for k,v in record.items() if k != 'command'})
            del self.recent[:-100]
            try:self.work_sessions.audit(identity,op,ok,rid)
            except Exception:LOG.exception('work audit failed request_id=%s',rid)

    async def close(self):
        if self.work_watchdog:
            self.work_watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):await self.work_watchdog
        await self.search.close(); await self.shell.disable()
        self.uploads.close(); self.work_sessions.close(); self.files.close(); self.logs.close()


def metadata():
    return {'hostname': socket.gethostname(), 'platform': 'darwin', 'python': sys.version.split()[0],
            'uid': os.getuid(), 'machine': 'mac_mio', 'agent_version': VERSION,
            'full_shell_capable': True, 'file_tools_version': '0.8', 'search_version': '0.10.1',
            'shell_backend': 'seatbelt-v09', 'shell_network': 'disabled; profiles on request',
            'shell_network_profiles': {k: sorted(v) for k, v in PROFILES.items()},
            'shell_network_hosts': sorted(ALLOWED_HOSTS), 'shell_scope': str(WORK),
            'allowed_roots': [str(WORK)], 'read_only_log_root': str(STATE / 'shell-logs'),
            'coordination_version':'0.11.0', 'work_session_required':True,
            'capabilities': sorted(FILE_NAMES | SEARCH_NAMES | WORK_NAMES | {'shell_exec','shell_session','enable_full_shell','disable_full_shell','who_is_working'}),
            'baseline_shell_commands': sorted(COMMANDS), 'reconnect': 'automatic; shell revoked on disconnect'}


def connected_receipt(connected=True):
    value = {'pid': os.getpid(), 'uid': os.getuid(), 'time': time.time(), 'version': VERSION, 'connected': connected}
    path = STATE / 'connected.json'
    temp = STATE / ('connected-' + str(os.getpid()) + '.tmp')
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:json.dump(value, f); f.flush(); os.fsync(f.fileno())
    os.replace(str(temp), str(path))


async def end_connection(heartbeat, dispatcher):
    heartbeat.cancel()
    try:
        with contextlib.suppress(asyncio.CancelledError, Exception):await heartbeat
    finally:
        try:
            await dispatcher.search.close()
            await dispatcher.shell.disable()
        finally:connected_receipt(False)


async def connection(dispatcher):
    from websockets.legacy.client import connect, WebSocketClientProtocol
    from websockets.exceptions import RedirectHandshake
    class NoRedirect(WebSocketClientProtocol):
        async def handshake(self, *args, **kwargs):
            try:return await super().handshake(*args, **kwargs)
            except RedirectHandshake:raise RuntimeError('redirect rejected') from None
    async with connect(URL, extra_headers={'Authorization': 'Bearer ' + trusted_token()},
                       ssl=ssl.create_default_context(), create_protocol=NoRedirect,
                       open_timeout=15, close_timeout=5, ping_interval=20, ping_timeout=20,
                       max_size=2*1024*1024, max_queue=8, compression=None) as ws:
        await ws.send(json.dumps({'type':'hello','meta':metadata()}))
        connected_receipt()
        async def beat():
            while True:
                await asyncio.sleep(15)
                await ws.send(json.dumps({'type':'hello','meta':metadata()}))
        heartbeat=asyncio.create_task(beat())
        try:
            async for raw in ws:
                rid=None
                try:
                    msg=json.loads(raw); rid=msg.get('id') if isinstance(msg,dict) else None
                    if not isinstance(rid,str) or not RID.fullmatch(rid):raise ValueError('request id required')
                    value=await dispatcher.dispatch(msg)
                    reply={'type':'result','id':rid,'ok':True,'result':value}
                except Exception as exc:
                    if not isinstance(rid,str) or not RID.fullmatch(rid):continue
                    reply={'type':'result','id':rid,'ok':False,'error':type(exc).__name__+': '+str(exc)[:300]}
                await ws.send(json.dumps(reply))
        finally:
            await end_connection(heartbeat, dispatcher)


async def run():
    dispatcher=Dispatcher()
    try:
        while True:
            try:await connection(dispatcher)
            except asyncio.CancelledError:raise
            except Exception as exc:LOG.warning('connection ended category=%s',type(exc).__name__)
            await asyncio.sleep(5)
    finally:await dispatcher.close()


def main():
    require_identity(); os.umask(0o077)
    fd=os.open(str(STATE/'agent.lock'),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    stop_dedicated_children()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s',handlers=[
        RotatingFileHandler(STATE/'audit.log',maxBytes=2*1024*1024,backupCount=4)])
    loop=asyncio.new_event_loop();asyncio.set_event_loop(loop)
    task=loop.create_task(run())
    for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,task.cancel)
    try:
        with contextlib.suppress(asyncio.CancelledError):loop.run_until_complete(task)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens());loop.close();os.close(fd)


if __name__=='__main__':main()
''',
'mac_child.py': r'''#!/usr/bin/env python3
"""Trusted resource-limit setup followed by exec into the seatbelt sandbox."""
import os
import re
from pathlib import Path
import resource
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mac_guard import require_identity
from mac_policy import profile


def main():
    require_identity()
    if len(sys.argv) != 5:
        raise SystemExit('workspace cwd command tty required')
    workspace, cwd, command, tty_path = sys.argv[1:]
    if os.path.commonpath([workspace, cwd]) != workspace:
        raise SystemExit('cwd outside workspace')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16777216, 16777216))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': workspace,
           'TMPDIR': workspace + '/.tmp', 'LANG': 'en_US.UTF-8', 'TERM': 'xterm'}
    # The agent passes the per-lease proxy credential in the environment,
    # never in argv (visible to every local user through ps).
    port, token = os.environ.get('MCP_NET_PORT'), os.environ.get('MCP_NET_TOKEN')
    net_port = None
    if port or token:
        if not (port and port.isdigit() and token and re.fullmatch(r'[A-Za-z0-9_-]{32}', token)):
            raise SystemExit('invalid network lease')
        net_port = int(port)
        proxy = 'http://mcp:%s@127.0.0.1:%d' % (token, net_port)
        env.update({'HTTPS_PROXY': proxy, 'https_proxy': proxy, 'NO_PROXY': '', 'no_proxy': '',
                    'GIT_SSL_CAINFO': '/etc/ssl/cert.pem', 'SSL_CERT_FILE': '/etc/ssl/cert.pem',
                    'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_COUNT': '1',
                    'GIT_CONFIG_KEY_0': 'http.proxyAuthMethod', 'GIT_CONFIG_VALUE_0': 'basic',
                    'PIP_PROXY': proxy, 'npm_config_https_proxy': proxy, 'npm_config_proxy': proxy})
    os.execve('/usr/bin/sandbox-exec', ['/usr/bin/sandbox-exec', '-p',
              profile(workspace, tty_path, net_port), '/bin/bash', '--noprofile', '--norc',
              '-c', command], env)


if __name__ == '__main__':
    main()
''',
'mac_shell.py': r'''"""macOS shell lease for one work session, uid5000 only.

Up to MAX_RUNNING concurrent processes share the lease, the workspace guard
and the watchdog. Stopping one process kills its process group; the full
uid5000 cleanup runs when the last one ends, on stop of the last one and
when the lease ends. Network is off unless the lease selects a profile.
"""
import asyncio
import contextlib
import errno
import fcntl
import os
from pathlib import Path
import pty
import stat
import subprocess
import sys
import time
import uuid

from shell_common import IsolatedShell
from mac_guard import require_identity, stop_dedicated_children
from mac_clock import lease_deadline
from net_proxy import GitHubProxy, PROFILES


class MacShell(IsolatedShell):
    LOG_LIMIT = 16 * 1024 * 1024
    MAX_RUNNING = 4

    def __init__(self, files, workspace, logs, capable=False):
        super().__init__(files, workspace, capable)
        self.code = Path(__file__).resolve().parent
        self.logs = Path(logs)
        self.logs.mkdir(mode=0o700, exist_ok=True)
        self.watchdog = None
        self.network = 'none'
        self.proxy = GitHubProxy(log=self.log_network)
        self.network_log = []
        self.guard_fd = None

    def log_network(self, event):
        self.network_log.append(dict(event, time=time.time()))
        del self.network_log[:-50]

    async def enable(self, caller, minutes, network='none'):
        require_identity()
        if network != 'none' and network not in PROFILES:
            raise ValueError('network must be none or one of: ' + ', '.join(sorted(PROFILES)))
        if self.owner == caller and time.monotonic() < self.until and network != self.network:
            if any(not j['done'].is_set() for j in self.jobs.values()):
                raise PermissionError('stop the running shell before changing network access')
        result = await super().enable(caller, minutes)
        await self.proxy.stop()
        if network != 'none':
            await self.proxy.start(PROFILES[network])
        self.network = network
        if self.watchdog and self.watchdog.poll() is None:
            self.refresh_watchdog()
        result['network'] = (network + ' via agent proxy: ' + ', '.join(sorted(PROFILES[network]))
                             if network != 'none' else 'disabled')
        result['maximum_active_sessions'] = self.MAX_RUNNING
        return result

    async def disable(self):
        try:
            return await super().disable()
        finally:
            self.network = 'none'
            await self.proxy.stop()

    def child_env(self):
        env = {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
        if self.network != 'none' and self.proxy.running:
            env.update(MCP_NET_PORT=str(self.proxy.address()), MCP_NET_TOKEN=self.proxy.token)
        return env

    def cwd(self, raw):
        path, root, _ = self.files._path(self.workspace if raw is None else raw)
        if root != self.workspace:
            raise PermissionError('cwd must be inside the shell workspace')
        with self.files._directory(path):
            pass
        return path

    def _trusted_code(self):
        for name in ('mac_guard.py', 'mac_child.py', 'mac_watchdog.py', 'mac_policy.py', 'mac_clock.py'):
            s = (self.code / name).lstat()
            if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
                raise PermissionError('root-owned shell helpers required')
        for p in [self.code] + list(self.code.parents):
            s = p.lstat()
            if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
                raise PermissionError('unsafe helper parent')

    def _start_watchdog(self):
        self.watchdog = subprocess.Popen(
            [sys.executable, '-I', '-B', str(self.code / 'mac_watchdog.py')],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, start_new_session=True, cwd='/',
            env={'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'})
        self.refresh_watchdog()

    def refresh_watchdog(self):
        self.watchdog.stdin.write((str(lease_deadline(self.until)) + '\n').encode())
        self.watchdog.stdin.flush()

    def _cleanup_uid(self):
        stop_dedicated_children()
        if self.watchdog:
            if self.watchdog.stdin:
                with contextlib.suppress(BrokenPipeError):
                    self.watchdog.stdin.close()
            self.watchdog.wait(timeout=3)
            self.watchdog = None

    def _drain(self, job):
        for _ in range(16):
            try:
                chunk = os.read(job['fd'], 8192)
            except BlockingIOError:
                return
            except OSError as exc:
                if exc.errno not in (errno.EIO, errno.EBADF):
                    raise
                return
            if not chunk:
                return
            remaining = self.LOG_LIMIT - job['log_bytes']
            if remaining > 0:
                job['log'].write(chunk[:remaining])
                job['log_bytes'] += min(len(chunk), remaining)
            job['output'].extend(chunk)
            excess = len(job['output']) - self.MAX_OUTPUT
            if excess > 0:
                del job['output'][:excess]; job['base'] += excess
            if len(chunk) > remaining:
                job['log_complete'] = False
                job['stop_reason'] = 'output limit reached'
                self._kill(job)
                return

    def running(self):
        return [j for j in self.jobs.values() if not j['done'].is_set()]

    def _acquire_guard(self):
        fd = os.open('guard', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.files.state_fd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.files._check_journal()
        except BaseException:
            os.close(fd)
            raise
        self.guard_fd = fd

    def _release_guard(self):
        if self.guard_fd is not None:
            os.close(self.guard_fd)
            self.guard_fd = None

    def _kill(self, job):
        """Stop one process group, or everything when it is the last one."""
        if any(j is not job for j in self.running()):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(job['proc'].pid, 9)
        else:
            self._cleanup_uid()

    async def start(self, caller, command, cwd=None):
        require_identity()
        self.allowed(caller)
        if not isinstance(command, str) or not command.strip() or '\0' in command or len(command.encode()) > 32768:
            raise ValueError('command required; maximum32768 bytes')
        running = self.running()
        if len(running) >= self.MAX_RUNNING:
            raise PermissionError('at most %d concurrent shell processes; stop one first' % self.MAX_RUNNING)
        if running and self.guard_fd is None:
            raise RuntimeError('shell guard lost; disable the shell')
        while len(self.jobs) >= 16 and len(self.jobs) > len(running):
            done = next(k for k, j in self.jobs.items() if j['done'].is_set())
            self.jobs.pop(done)
        cwd = self.cwd(cwd)
        self._trusted_code()
        first = not running
        master = slave = -1
        log = None
        started = False
        try:
            if first:
                self._acquire_guard()
            sid = uuid.uuid4().hex
            logpath = self.logs / (sid + '.log')
            fd = os.open(str(logpath), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            log = os.fdopen(fd, 'wb', buffering=0)
            master, slave = pty.openpty()
            os.set_blocking(master, False)
            started = True
            if first or not self.watchdog or self.watchdog.poll() is not None:
                self._start_watchdog()
            proc = subprocess.Popen(
                [sys.executable, '-I', '-B', str(self.code / 'mac_child.py'),
                 self.workspace, cwd, command, os.ttyname(slave)],
                stdin=slave, stdout=slave, stderr=slave, close_fds=True,
                start_new_session=True, cwd=cwd, env=self.child_env())
            os.close(slave); slave = -1
            job = {'id': sid, 'owner': caller, 'proc': proc, 'fd': master,
                   'output': bytearray(), 'base': 0, 'cursor': 0, 'command': command[:200],
                   'cwd': cwd, 'started_at': time.time(),
                   'done': asyncio.Event(), 'closed': False, 'log': log,
                   'log_path': str(logpath), 'log_bytes': 0, 'log_complete': True}
            self.jobs[sid] = job
            asyncio.get_running_loop().add_reader(master, self._drain, job)
            job['watcher'] = asyncio.create_task(self._watch_job(job))
            master = -1; log = None
            return {'session_id': sid, 'pid': proc.pid, 'running': proc.poll() is None,
                    'scope': self.workspace, 'uid': 5000, 'concurrent': len(self.running()),
                    'network': self.network if 'MCP_NET_PORT' in self.child_env() else 'disabled'}
        except BaseException:
            if first:
                if started:
                    self._cleanup_uid()
                self._release_guard()
            raise
        finally:
            for fd in (master, slave):
                if fd >= 0:
                    os.close(fd)
            if log:
                log.close()

    async def _watch_job(self, job):
        try:
            while job['proc'].poll() is None:
                if self.watchdog and self.watchdog.poll() is not None:
                    job['stop_reason'] = 'watchdog ended unexpectedly'
                    self._cleanup_uid()
                await asyncio.sleep(.05)
            # The last process also takes down daemons detached by any of them.
            if not any(j is not job for j in self.running()):
                self._cleanup_uid()
            self._drain(job)
        finally:
            if not job['closed']:
                job['closed'] = True
                asyncio.get_running_loop().remove_reader(job['fd'])
                os.close(job['fd']); job['log'].close()
            job['done'].set()
            if not self.running():
                self._release_guard()

    async def _terminate(self, job):
        if not job['done'].is_set():
            self._kill(job)
            await asyncio.wait_for(job['done'].wait(), 3)

    def processes(self):
        """Read-only inventory of uid5000 processes (the agent itself excluded)."""
        out = subprocess.run(['/bin/ps', '-axo', 'uid=,pid=,ppid=,etime=,args='], capture_output=True,
                             text=True, timeout=5, env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}).stdout
        rows = []
        for line in out.splitlines()[:5000]:
            p = line.split(None, 4)
            if len(p) >= 4 and p[0] == '5000' and int(p[1]) != os.getpid():
                rows.append({'pid': int(p[1]), 'ppid': int(p[2]), 'elapsed': p[3],
                             'command': (p[4] if len(p) == 5 else '')[:300]})
        return rows[:500]

    async def session(self, caller, args):
        action = args.get('action')
        if action == 'list':
            self.identity(caller)
            return {'sessions': [{'session_id': j['id'], 'command': j['command'], 'cwd': j['cwd'],
                                  'started_at': j['started_at'], 'running': not j['done'].is_set(),
                                  'exit_code': j['proc'].poll(), 'pid': j['proc'].pid}
                                 for j in self.jobs.values() if j['owner'] == caller],
                    'maximum_active_sessions': self.MAX_RUNNING}
        if action == 'processes':
            self.allowed(caller)
            return {'processes': self.processes()}
        return await super().session(caller, args)

    def read(self, caller, sid):
        result = super().read(caller, sid)
        job = self.lookup(caller, sid)
        result.update(log_path=job['log_path'], log_complete=job['log_complete'],
                      stop_reason=job.get('stop_reason'))
        return result

    def working(self):
        value = super().working()
        value['shell_network'] = 'github-only' if self.network == 'github' and self.proxy.running else 'disabled'
        value['network_events'] = list(self.network_log[-10:])
        return value
''',
'net_proxy.py': r'''"""Allow-listed HTTPS CONNECT proxy for the isolated shell (GitHub, packages).

Seatbelt cannot filter by host name, so the shell may reach only this proxy on
loopback. The proxy runs inside the agent (outside the sandbox), demands a
random per-lease credential, tunnels TLS on port 443 to an exact host list and
refuses addresses that are not public. It never sees decrypted traffic.
"""
import asyncio
import base64
import contextlib
import hmac
import ipaddress
import re
import secrets
import socket
import time

ALLOWED_HOSTS = frozenset({
    'github.com', 'api.github.com', 'codeload.github.com',
    'objects.githubusercontent.com', 'raw.githubusercontent.com',
})
PACKAGE_HOSTS = frozenset({'pypi.org', 'files.pythonhosted.org', 'registry.npmjs.org'})
# Lease profiles selectable with enable_full_shell(network=...).
PROFILES = {'github': ALLOWED_HOSTS, 'packages': ALLOWED_HOSTS | PACKAGE_HOSTS}
REQUEST = re.compile(rb'CONNECT ([a-z0-9.-]{1,253}):([0-9]{1,5}) HTTP/1\.[01]\r\n')


def public_address(address):
    ip = ipaddress.ip_address(address)
    if getattr(ip, 'ipv4_mapped', None):
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class GitHubProxy:
    MAX_CONNECTIONS = 16
    HEAD_LIMIT = 8192
    IDLE_SECONDS = 120
    MAX_TUNNEL_BYTES = 1024 * 1024 * 1024

    def __init__(self, log=None, resolver=None, hosts=ALLOWED_HOSTS, port=443):
        self.log = log or (lambda event: None)
        self.resolver = resolver
        self.hosts, self.port = frozenset(hosts), port
        self.server = None
        self.token = None
        self.tasks = set()
        self.stats = {'accepted': 0, 'refused': 0}

    @property
    def running(self):
        return self.server is not None

    def address(self):
        return self.server.sockets[0].getsockname()[1]

    def proxy_url(self):
        return 'http://mcp:%s@127.0.0.1:%d' % (self.token, self.address())

    async def start(self, hosts=None):
        if self.server is not None:
            return self.address()
        if hosts is not None:
            self.hosts = frozenset(hosts)
        self.token = secrets.token_urlsafe(24)
        self.stats = {'accepted': 0, 'refused': 0}
        self.server = await asyncio.start_server(self._client, '127.0.0.1', 0, limit=self.HEAD_LIMIT)
        return self.address()

    async def stop(self):
        server, self.server, self.token = self.server, None, None
        if server is not None:
            server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(server.wait_closed(), 3)
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    def _authorized(self, head):
        expected = 'Basic ' + base64.b64encode(('mcp:' + (self.token or '')).encode()).decode()
        for line in head.split(b'\r\n')[1:]:
            name, _, value = line.partition(b':')
            if name.strip().lower() == b'proxy-authorization':
                return self.token is not None and hmac.compare_digest(value.strip().decode('latin-1'), expected)
        return False

    async def _resolve(self, host):
        if self.resolver:
            return await self.resolver(host)
        infos = await asyncio.get_running_loop().getaddrinfo(host, self.port, type=socket.SOCK_STREAM)
        return [info[4][0] for info in infos]

    async def _client(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        host = None
        try:
            if len(self.tasks) > self.MAX_CONNECTIONS:
                return await self._refuse(writer, b'429 Too Many Connections', 'capacity', None)
            try:
                head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
                return await self._refuse(writer, b'400 Bad Request', 'malformed', None)
            match = REQUEST.match(head)
            if not match:
                return await self._refuse(writer, b'405 Method Not Allowed', 'method', None)
            if not self._authorized(head):
                return await self._refuse(writer, b'407 Proxy Authentication Required', 'auth', None)
            host, port = match.group(1).decode(), int(match.group(2))
            if host not in self.hosts or port != 443:
                return await self._refuse(writer, b'403 Forbidden', 'host', host)
            addresses = [a for a in await self._resolve(host) if public_address(a)]
            if not addresses:
                return await self._refuse(writer, b'502 Bad Gateway', 'address', host)
            up_reader, upstream = await asyncio.wait_for(
                asyncio.open_connection(addresses[0], self.port), 15)
            writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            await writer.drain()
            self.stats['accepted'] += 1
            started = time.monotonic()
            budget = [self.MAX_TUNNEL_BYTES]
            await asyncio.gather(self._pipe(reader, upstream, budget),
                                 self._pipe(up_reader, writer, budget))
            self.log({'event': 'tunnel', 'host': host, 'seconds': round(time.monotonic() - started, 1),
                      'bytes': self.MAX_TUNNEL_BYTES - budget[0]})
        except (OSError, asyncio.TimeoutError) as exc:
            self.log({'event': 'tunnel_error', 'host': host, 'error': type(exc).__name__})
        finally:
            self.tasks.discard(task)
            for w in (upstream, writer):
                if w is not None:
                    with contextlib.suppress(Exception):
                        w.close()

    async def _refuse(self, writer, status, reason, host):
        self.stats['refused'] += 1
        self.log({'event': 'refused', 'reason': reason, 'host': host})
        # curl (git) probes without credentials first and needs the scheme.
        extra = b'Proxy-Authenticate: Basic realm="mcp"\r\n' if status.startswith(b'407') else b''
        with contextlib.suppress(Exception):
            writer.write(b'HTTP/1.1 ' + status + b'\r\n' + extra + b'Connection: close\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()

    async def _pipe(self, reader, writer, budget):
        try:
            while True:
                data = await asyncio.wait_for(reader.read(65536), self.IDLE_SECONDS)
                if not data:
                    break
                budget[0] -= len(data)
                if budget[0] < 0:
                    break
                writer.write(data)
                await writer.drain()
        except (OSError, asyncio.TimeoutError):
            pass
        finally:
            with contextlib.suppress(Exception):
                if writer.can_write_eof():
                    writer.write_eof()
''',
'test_work_core.py': r'''"""Necessary isolation, persistence and dispatcher regression checks."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from file_tools import FileTools, FileToolError
from work_sessions import WorkSessions
from mac_agent import Dispatcher
from work_schema import install_schema, WORK_NAMES


class SessionCore(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.work=self.root/'work';self.work.mkdir(mode=0o700)
        self.f=FileTools([str(self.work)],str(self.root/'journal'))
        self.wall=1000.;self.tick=200.
        self.w=WorkSessions(str(self.root/'sessions'),self.f,wall=lambda:self.wall,clock=lambda:self.tick,boot='boot1')
        self.f.lock_provider=self.w.lock_provider
        self.a=self.w.open('test:client','chat A',10)
        self.b=self.w.open('test:client','chat B',10)
    def test_read_only_transaction_does_not_rewrite_state(self):
        st=self.root/'sessions'/'state.json';before=os.stat(st)
        self.w.snapshot();self.ident(self.a)
        after=os.stat(st)
        self.assertEqual((before.st_ino,before.st_mtime_ns),(after.st_ino,after.st_mtime_ns))
        self.tick+=601;self.w.snapshot()
        self.assertNotEqual(before.st_ino,os.stat(st).st_ino)
    def tearDown(self):
        self.w.close();self.f.close();self.tmp.cleanup()
    def auth(self,s):return ('test:client',s['work_session_id'],s['work_session_token'])
    def ident(self,s):return self.w.authenticate(*self.auth(s))
    def lock(self,s,path=None,minutes=5):return self.w.acquire(*self.auth(s),str(path or self.work),minutes)
    def test_same_oauth_distinct_sessions_cannot_impersonate(self):
        with self.assertRaises(PermissionError):
            self.w.authenticate('test:client',self.a['work_session_id'],self.b['work_session_token'])
        with self.assertRaises(PermissionError):
            self.w.authenticate('test:other',self.a['work_session_id'],self.a['work_session_token'])
    def test_prefix_overlap_and_component_boundary(self):
        self.lock(self.a,self.work/'app')
        for p in [self.work,self.work/'app',self.work/'app'/'file']:
            with self.assertRaises(PermissionError):self.lock(self.b,p)
        self.lock(self.b,self.work/'apple')
    def test_case_and_unicode_alias_overlap(self):
        self.lock(self.a,self.work/('Caf'+chr(0xe9)))
        with self.assertRaises(PermissionError):self.lock(self.b,self.work/('CAFE'+chr(0x301))/'x')
    def test_write_requires_lock_and_rollback_is_protected(self):
        p=str(self.work/'a')
        with self.assertRaises(PermissionError):self.f.write_file(p,'bad',session_id=self.ident(self.a))
        self.lock(self.a)
        r=self.f.write_file(p,'good',session_id=self.ident(self.a))
        with self.assertRaises(PermissionError):self.f.rollback_file(r['operation_id'],session_id=self.ident(self.b))
        self.f.rollback_file(r['operation_id'],session_id=self.ident(self.a))
        self.assertFalse(Path(p).exists())
    def test_move_checks_both_paths_and_reentrant_provider(self):
        (self.work/'a').write_text('content')
        self.lock(self.a,self.work/'a');self.lock(self.b,self.work/'b')
        with self.assertRaises(PermissionError):self.f.move_file(str(self.work/'a'),str(self.work/'b'),session_id=self.ident(self.a))
        self.w.end(*self.auth(self.b));self.lock(self.a,self.work/'b')
        self.f.move_file(str(self.work/'a'),str(self.work/'b'),session_id=self.ident(self.a))
        self.assertEqual((self.work/'b').read_text(),'content')
    def test_restart_preserves_lock_and_no_plain_tokens(self):
        self.lock(self.a);self.w.close()
        self.w=WorkSessions(str(self.root/'sessions'),self.f,wall=lambda:self.wall,clock=lambda:self.tick,boot='boot1')
        with self.assertRaises(PermissionError):self.lock(self.b)
        self.assertTrue(self.ident(self.a).startswith('work:'))
        state=(self.root/'sessions'/'state.json').read_text()
        for s in [self.a,self.b]:self.assertNotIn(s['work_session_token'],state+json.dumps(self.w.snapshot()))
    def test_lock_expiry_and_clock_rollback(self):
        self.lock(self.a,minutes=1)
        self.wall-=100;self.tick+=61
        self.lock(self.b)
        with self.assertRaises(PermissionError):self.w.remaining(self.ident(self.a),str(self.work))
    def test_session_expiry_and_reboot(self):
        self.lock(self.a);self.tick+=601
        with self.assertRaises(PermissionError):self.ident(self.a)
        self.assertFalse(self.w.snapshot()['work_locks'])
        c=self.w.open('test:client','new',10);self.lock(c)
        self.w.close();self.w=WorkSessions(str(self.root/'sessions'),self.f,wall=lambda:self.wall,clock=lambda:self.tick,boot='boot2')
        self.assertFalse(self.w.snapshot()['work_locks'])
        with self.assertRaises(PermissionError):self.ident(c)
    def test_outside_and_symlink_locks_refused(self):
        with self.assertRaises(FileToolError):self.lock(self.a,self.root/'outside')
        (self.work/'link').symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(PermissionError):self.lock(self.a,self.work/'link'/'a')
    def test_foreign_lock_release_refused_and_renew_bounded(self):
        l=self.lock(self.a,minutes=1)
        with self.assertRaises(PermissionError):self.w.change_lock(*self.auth(self.b),l['lock_id'])
        r=self.w.change_lock(*self.auth(self.a),l['lock_id'],240)
        self.assertEqual(r['expires_at'],self.a['expires_at'])
    def test_corrupt_store_and_symlink_fail_closed(self):
        p=self.root/'sessions'/'state.json';p.write_text('{}')
        with self.assertRaises(RuntimeError):self.w.snapshot()
        p.unlink();p.symlink_to(self.root/'outside')
        with self.assertRaises(OSError):self.w.snapshot()


class AgentCore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();r=Path(self.tmp.name)
        self.work=r/'work';self.state=r/'state'
        self.work.mkdir(mode=0o700);self.state.mkdir(mode=0o700)
        self.d=Dispatcher(self.work,self.state)
        self.a=await self.call('work_session',{'action':'open','label':'chat A','minutes':10})
        self.b=await self.call('work_session',{'action':'open','label':'chat B','minutes':10})
    async def asyncTearDown(self):
        await self.d.close();self.tmp.cleanup()
    async def call(self,op,args,s=None):
        if s:args={**args,**{k:s[k] for k in ['work_session_id','work_session_token']}}
        return await self.d.dispatch({'type':'request','id':uuid.uuid4().hex,'caller':'test:client','op':op,'args':args})
    async def lock(self,s):return await self.call('work_lock',{'action':'acquire','path':str(self.work),'minutes':10},s)
    async def test_authenticated_write_read_rollback_and_legacy_write_refused(self):
        p=str(self.work/'file')
        with self.assertRaises(PermissionError):await self.call('write_file',{'path':p,'content':'bad'})
        await self.lock(self.a)
        r=await self.call('write_file',{'path':p,'content':'good'},self.a)
        self.assertEqual((await self.call('read_file',{'path':p}))['content'],'good')
        with self.assertRaises(PermissionError):await self.call('write_file',{'path':p,'content':'other'},self.b)
        await self.call('rollback_file',{'operation_id':r['operation_id']},self.a)
        self.assertFalse(Path(p).exists())
    async def test_search_results_private_between_same_oauth_chats(self):
        (self.work/'f').write_text('needle')
        r=await self.call('start_search',{'path':str(self.work),'pattern':'needle'},self.a)
        await self.d.search.jobs[r['search_id']]['task']
        with self.assertRaises(PermissionError):await self.call('get_more_search_results',{'search_id':r['search_id']},self.b)
        self.assertEqual((await self.call('get_more_search_results',{'search_id':r['search_id']},self.a))['total_results'],1)
    async def test_shell_requires_whole_workspace_lock_and_separate_identity(self):
        with self.assertRaises(PermissionError):await self.call('enable_full_shell',{'minutes':1},self.a)
        await self.lock(self.a)
        with patch.object(self.d.shell,'enable',new=AsyncMock(return_value={'enabled':True})) as m:
            await self.call('enable_full_shell',{'minutes':1},self.a)
            m.assert_awaited_once_with('work:'+self.a['work_session_id'],1,'none')
        with self.assertRaises(PermissionError):await self.call('enable_full_shell',{'minutes':11},self.a)
    async def test_foreign_disable_refused_close_revokes_own_shell(self):
        await self.lock(self.a);identity='work:'+self.a['work_session_id']
        self.d.shell.owner=identity;self.d.shell.until=__import__('time').monotonic()+60
        with self.assertRaises(PermissionError):await self.call('disable_full_shell',{},self.b)
        with patch.object(self.d.shell,'disable',new=AsyncMock()) as m:
            await self.call('work_session',{'action':'close'},self.a)
            m.assert_awaited_once_with()
        self.d.shell.owner=None
        self.assertFalse((await self.call('who_is_working',{}))['work_locks'])
    async def test_expiry_reaps_before_accepting_new_lock(self):
        await self.lock(self.a);identity='work:'+self.a['work_session_id']
        self.d.shell.owner=identity;self.d.shell.until=__import__('time').monotonic()+60
        with self.d.work_sessions.transaction() as d:
            d['sessions'][self.a['work_session_id']]['deadline']=0
        async def disable():self.d.shell.owner=None
        with patch.object(self.d.shell,'disable',new=AsyncMock(side_effect=disable)) as m:
            await self.lock(self.b)
            m.assert_awaited_once_with()
    async def test_durable_audit_contains_session_id_not_secret(self):
        await self.lock(self.a)
        await self.call('write_file',{'path':str(self.work/'x'),'content':'x'},self.a)
        state=await self.call('who_is_working',{})
        self.assertTrue(any(x['work_session_id']==self.a['work_session_id'] and x['operation']=='write_file' for x in state['recent_work_operations']))
        self.assertNotIn(self.a['work_session_token'],json.dumps(state))
    async def test_audit_failure_does_not_mask_result(self):
        await self.lock(self.a)
        with patch.object(self.d.work_sessions,'audit',side_effect=BlockingIOError()):
            r=await self.call('write_file',{'path':str(self.work/'y'),'content':'y'},self.a)
        self.assertIn('operation_id',r)
    async def test_close_cancels_search_and_releases_locks(self):
        await self.lock(self.a)
        r=await self.call('start_search',{'path':str(self.work),'pattern':'x'},self.a)
        await self.call('work_session',{'action':'close'},self.a)
        self.assertFalse(self.d.search.jobs[r['search_id']]['status']=='running')
        await self.lock(self.b)


class Schema(unittest.TestCase):
    def test_schema_additive_and_idempotent(self):
        original=[{'name':'shell_session','description':'terminal','inputSchema':{'type':'object','properties':{'session_id':{'type':'string'}}}}]
        result=install_schema(original)
        self.assertEqual(len({x['name'] for x in result}),len(result))
        self.assertTrue(WORK_NAMES.issubset({x['name'] for x in result}))
        self.assertNotIn('work_session_id',original[0]['inputSchema']['properties'])
        self.assertIn('session_id',result[0]['inputSchema']['properties'])
        self.assertIn('work_session_id',result[0]['inputSchema']['properties'])

if __name__=='__main__':unittest.main()
''',
'test_search.py': r'''import asyncio
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from file_tools import FileTools, FileToolError
from search_tools import SearchTools, glob_match

OWNER='chatgpt:searchtest1'
OTHER='claude:searchtest2'


class Searches(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.root=self.base/'workspace';self.root.mkdir()
        self.secret=self.root/'protected';self.secret.mkdir()
        self.files=FileTools([str(self.root)],str(self.base/'journal'),denied_roots=[str(self.secret)])
        self.search=SearchTools(self.files)

    async def asyncTearDown(self):
        await self.search.close();self.files.close();self.tmp.cleanup()

    async def start(self, **kwargs):
        return await self.search.start(OWNER,{'path':str(self.root),'pattern':'needle',**kwargs})

    async def finish(self, initial):
        j=self.search.jobs[initial['search_id']]
        await asyncio.wait_for(j['task'],3)
        return await self.search.dispatch('get_more_search_results',{'search_id':j['id']},OWNER)

    async def test_text_casefold_and_context(self):
        (self.root/'code.py').write_text('prima\nNEEDLE utf8 '+chr(0xe8)+'\ndopo\n')
        r=await self.finish(await self.start())
        self.assertEqual(r['status'],'completed');self.assertEqual(r['results'][0]['line'],2)
        self.assertEqual(r['results'][0]['text'],'prima\nNEEDLE utf8 '+chr(0xe8)+'\ndopo')

    async def test_filename_glob_and_filter(self):
        for n in ('User.py','user.js','test.txt'):(self.root/n).write_text('')
        r=await self.finish(await self.start(search_type='files',match_mode='glob',pattern='*USER*',file_pattern='*.py'))
        self.assertEqual([Path(x['path']).name for x in r['results']],['User.py'])

    async def test_literal_punctuation(self):
        (self.root/'code.py').write_text('a.*(x)\nnot a match\n')
        r=await self.finish(await self.start(pattern='a.*(x)',context_lines=0))
        self.assertEqual(r['total_results'],1)

    async def test_no_outside_traversal(self):
        for path in (str(self.base),str(self.root/'..'),str(self.secret)):
            with self.assertRaises(FileToolError):await self.start(path=path)
        self.assertFalse(self.search.jobs)

    async def test_links_and_special_files_not_read(self):
        outside=self.base/'outside';outside.write_text('needle SECRET')
        os.symlink(outside,self.root/'link.txt');os.symlink(self.base,self.root/'dirlink')
        os.link(outside,self.root/'hard.txt');os.mkfifo(self.root/'pipe')
        r=await self.finish(await self.start())
        self.assertEqual(r['total_results'],0)
        self.assertEqual(r['skipped']['symlink'],2)
        self.assertEqual(r['skipped']['not_regular_or_hardlink'],2)

    async def test_symlink_requested_directory(self):
        os.symlink(self.base,self.root/'link')
        with self.assertRaises((FileToolError,OSError)):await self.start(path=str(self.root/'link'))

    async def test_hidden_and_protected(self):
        (self.root/'.hidden').write_text('needle');(self.secret/'secret').write_text('needle')
        r=await self.finish(await self.start())
        self.assertEqual(r['total_results'],0)
        r=await self.finish(await self.start(include_hidden=True))
        self.assertEqual(r['total_results'],1)
        self.assertEqual(r['skipped']['protected_or_changed_path'],1)

    async def test_binary_and_large_skip(self):
        (self.root/'null').write_bytes(b'needle\0');(self.root/'bad').write_bytes(b'needle'+bytes([255]))
        (self.root/'big').write_bytes(b'a'*(self.search.FILE_BYTES+1))
        r=await self.finish(await self.start())
        self.assertEqual(r['total_results'],0);self.assertEqual(r['skipped']['binary_file'],2)
        self.assertEqual(r['skipped']['large_file'],1)

    async def test_page_stability(self):
        (self.root/'many').write_text('needle\n'*120)
        r=await self.finish(await self.start(context_lines=0));sid=r['search_id']
        self.assertEqual(len(r['results']),100);self.assertTrue(r['has_more'])
        args={'search_id':sid,'offset':100,'length':100}
        tail=await self.search.dispatch('get_more_search_results',args,OWNER)
        self.assertEqual(len(tail['results']),20);self.assertFalse(tail['has_more'])
        self.assertEqual(tail,await self.search.dispatch('get_more_search_results',args,OWNER))

    async def test_limit_results(self):
        (self.root/'many').write_text('needle\n'*20)
        r=await self.finish(await self.start(max_results=3))
        self.assertEqual(r['total_results'],3);self.assertEqual(r['status'],'limited')
        self.assertIn('max_results',r['limits_reached'])

    async def test_depth_truncation_does_not_stop_siblings(self):
        (self.root/'d').mkdir();(self.root/'d'/'deep').write_text('needle')
        (self.root/'root').write_text('needle')
        r=await self.finish(await self.start(depth=1))
        self.assertEqual(r['total_results'],1);self.assertIn('depth',r['limits_reached'])

    async def test_read_budget(self):
        self.search.TOTAL_BYTES=10
        (self.root/'big').write_text('needle'*10)
        r=await self.finish(await self.start())
        self.assertLessEqual(r['bytes_read'],10);self.assertIn('total_bytes',r['limits_reached'])

    async def test_entry_budget(self):
        self.search.MAX_ENTRIES=2
        for i in range(10):(self.root/str(i)).write_text('needle')
        r=await self.finish(await self.start())
        self.assertIn('entries',r['limits_reached']);self.assertLessEqual(r['total_results'],2)

    async def test_response_budget_and_long_line(self):
        self.search.RESULT_BYTES=9000
        (self.root/'big').write_text(('needle'+chr(0xe8)*4000+'\n')*10)
        r=await self.finish(await self.start(context_lines=0))
        self.assertIn('result_bytes',r['limits_reached'])
        self.assertTrue(r['results'][0]['text_truncated'])
        self.assertLessEqual(len(r['results'][0]['text'].encode()),2048)

    async def test_owner_isolation(self):
        r=await self.start();sid=r['search_id']
        with self.assertRaises(PermissionError):self.search.owned(OTHER,sid)
        with self.assertRaises(PermissionError):await self.search.stop(OTHER,sid)
        await self.search.stop(OWNER,sid)

    async def test_cancel_before_worker_starts_releases_guard(self):
        r=await self.start();s=await self.search.stop(OWNER,r['search_id'])
        self.assertEqual(s['status'],'cancelled');self.assertFalse(self.search.active())
        with self.files._locked([str(self.root/'new')],OWNER):pass

    async def test_active_search_blocks_writes(self):
        r=await self.start()
        with self.assertRaises(PermissionError):self.search.guard_mutation('write_file')
        fd=os.open('guard',os.O_RDWR,dir_fd=self.files.state_fd)
        try:
            with self.assertRaises(BlockingIOError):fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        finally:os.close(fd)
        await self.search.stop(OWNER,r['search_id'])
        self.search.guard_mutation('write_file')

    async def test_existing_exclusive_lock_blocks_search(self):
        with self.files._locked([str(self.root/'new')],OWNER):
            with self.assertRaises(BlockingIOError):await self.start()
        self.assertFalse(self.search.jobs)

    async def test_disconnect_cancels_and_clears(self):
        await self.start();await self.start();await self.search.close()
        self.assertFalse(self.search.jobs)
        with self.files._locked([str(self.root/'new')],OWNER):pass

    async def test_capacity_and_expiration(self):
        self.search.MAX_JOBS=2
        for _ in range(2):await self.finish(await self.start())
        with self.assertRaises(PermissionError):await self.start()
        for j in self.search.jobs.values():j['finished']=time.monotonic()-301
        r=await self.start();self.assertEqual(len(self.search.jobs),1)
        await self.search.stop(OWNER,r['search_id'])

    async def test_timeout(self):
        r=await self.start();self.search.jobs[r['search_id']]['deadline']=time.monotonic()-1
        (self.root/'a').write_text('needle')
        r=await self.finish(r);self.assertIn('timeout',r['limits_reached'])

    async def test_root_replaced(self):
        old=self.base/'old';self.root.rename(old);self.root.mkdir()
        with self.assertRaises(FileToolError):await self.start()

    async def test_validation(self):
        bad=[{'pattern':''},{'pattern':'a\nb'},{'pattern':'x'*257},{'search_type':'oops'},
             {'match_mode':'regex'},{'match_mode':'glob'}, {'ignore_case':1}, {'depth':True},
             {'max_results':1001},{'timeout_seconds':0},{'extra':'bad'},{'include_hidden':'yes'}]
        for kw in bad:
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):await self.start(**kw)

    async def test_pagination_validation(self):
        r=await self.finish(await self.start());sid=r['search_id']
        for args in ({'offset':-1},{'length':0},{'length':101},{'length':True},{'extra':1}):
            with self.assertRaises(ValueError):await self.search.dispatch('get_more_search_results',{'search_id':sid,**args},OWNER)

    async def test_filename_replaced_with_link_before_read(self):
        target=self.root/'race';target.write_text('needle safe')
        outside=self.base/'outside';outside.write_text('needle SECRET')
        original=self.search.read_text
        async def swap(job,fd,name):
            target.unlink();target.symlink_to(outside)
            return await original(job,fd,name)
        with patch.object(self.search,'read_text',swap):r=await self.finish(await self.start())
        self.assertEqual(r['total_results'],0);self.assertNotIn('SECRET',json.dumps(r))

    async def test_regular_read_detects_change(self):
        target=self.root/'a';target.write_text('needle')
        original=os.read
        def changed(fd,count):
            value=original(fd,count)
            if value:target.write_text('changed size!')
            return value
        with patch('search_tools.os.read',changed):r=await self.finish(await self.start())
        self.assertEqual(r['total_results'],0);self.assertEqual(r['skipped']['changed_file'],1)


class Schema(unittest.TestCase):
    def test_glob(self):
        for text,pattern,expected in [('abc','a*',True),('abc','a?c',True),('abc','*d',False),
                                       ('a.py','*.py',True),('x[0]','x[0]',True),('','*',True)]:
            self.assertEqual(glob_match(text,pattern),expected)

    def test_tools_unique_and_machines(self):
        from cg_tools import TOOLS,NAMES
        self.assertEqual(len(TOOLS),len(NAMES));self.assertEqual(len(TOOLS),29)
        self.assertTrue({'work_session','work_lock'} <= NAMES)
        self.assertTrue({'start_search','get_more_search_results','stop_search'}<=NAMES)
        for t in TOOLS:
            m=t['inputSchema']['properties'].get('machine',{})
            if 'enum' in m:self.assertEqual(set(m['enum']),{'vps','mac_noleggio','mac_mio'})


if __name__=='__main__':unittest.main(verbosity=2)
''',
'test_v012.py': r'''"""v0.12 Mac side: GitHub-only proxy, seatbelt policy, child environment, dispatcher.

File tool tests live in test_files_v012.py.
"""
import asyncio
import contextlib
import subprocess
import types
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from file_tools import FileTools, FileToolError
import net_proxy
from net_proxy import GitHubProxy
import mac_policy
from mac_agent import Dispatcher


class Proxy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        async def echo(reader, writer):
            data = await reader.read(100)
            writer.write(b'echo:' + data); await writer.drain(); writer.close()
        self.upstream = await asyncio.start_server(echo, '127.0.0.1', 0)
        port = self.upstream.sockets[0].getsockname()[1]
        async def resolve(host): return ['127.0.0.1']
        self.p = GitHubProxy(log=self.events.append, resolver=resolve, port=port)
        await self.p.start()

    async def asyncTearDown(self):
        await self.p.stop(); self.upstream.close(); await self.upstream.wait_closed()

    async def request(self, head):
        r, w = await asyncio.open_connection('127.0.0.1', self.p.address())
        w.write(head); await w.drain()
        line = await r.readline()
        return r, w, line

    def auth(self, token=None):
        value = base64.b64encode(('mcp:' + (token or self.p.token)).encode())
        return b'Proxy-Authorization: Basic ' + value + b'\r\n'

    async def test_requires_credential(self):
        _, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n\r\n'); w.close()
        self.assertIn(b'407', line)
        _, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n' + self.auth('x' * 32) + b'\r\n'); w.close()
        self.assertIn(b'407', line)

    async def test_407_announces_basic_scheme_for_curl_anyauth(self):
        r, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n\r\n')
        head = await asyncio.wait_for(r.read(500), 5); w.close()
        self.assertIn(b'407', line)
        self.assertIn(b'Proxy-Authenticate: Basic', head)

    async def test_only_allowed_hosts_port_and_method(self):
        for head in [b'CONNECT example.com:443 HTTP/1.1\r\n', b'CONNECT github.com:22 HTTP/1.1\r\n',
                     b'CONNECT evilgithub.com:443 HTTP/1.1\r\n', b'CONNECT github.com.evil.com:443 HTTP/1.1\r\n']:
            _, w, line = await self.request(head + self.auth() + b'\r\n'); w.close()
            self.assertIn(b'403', line, head)
        _, w, line = await self.request(b'GET http://github.com/ HTTP/1.1\r\n' + self.auth() + b'\r\n'); w.close()
        self.assertIn(b'405', line)

    async def test_private_addresses_refused(self):
        _, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n' + self.auth() + b'\r\n'); w.close()
        self.assertIn(b'502', line)
        for a in ['127.0.0.1', '10.0.0.1', '192.168.1.1', '169.254.169.254', '::1', '::ffff:127.0.0.1']:
            self.assertFalse(net_proxy.public_address(a), a)
        self.assertTrue(net_proxy.public_address('140.82.121.4'))

    async def test_tunnel_to_allowed_host(self):
        with patch('net_proxy.public_address', return_value=True):
            r, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n' + self.auth() + b'\r\n')
            self.assertIn(b'200', line)
            await r.readline()
            w.write(b'hello'); await w.drain()
            self.assertEqual(await asyncio.wait_for(r.read(100), 5), b'echo:hello')
            w.close()

    async def test_stop_invalidates_token_and_port(self):
        port, token = self.p.address(), self.p.token
        await self.p.stop()
        self.assertIsNone(self.p.token)
        with self.assertRaises(OSError):
            await asyncio.open_connection('127.0.0.1', port)
        await self.p.start()
        self.assertNotEqual(self.p.token, token)


class Policy(unittest.TestCase):
    def setUp(self):
        self.patch = patch('mac_policy.safe_executables', return_value=['/bin/bash'])
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_offline_profile_has_no_network(self):
        text = mac_policy.profile('/Users/Shared/X/workspace')
        self.assertIn('(deny network*)', text)
        self.assertNotIn('network-outbound', text)
        self.assertNotIn('trustd', text)

    def test_network_profile_is_loopback_port_only(self):
        text = mac_policy.profile('/Users/Shared/X/workspace', net_port=50123)
        self.assertIn('(allow network-outbound (remote ip "localhost:50123"))', text)
        self.assertNotIn('(allow network*', text)
        self.assertIn('com.apple.trustd', text)
        self.assertLess(text.index('(deny network*)'), text.index('localhost:50123'))
        for bad in [80, 0, 70000, '50123']:
            with self.assertRaises(ValueError):
                mac_policy.profile('/Users/Shared/X/workspace', net_port=bad)


class TrustedTree(unittest.TestCase):
    def fake(self, modes):
        import stat as st
        def lstat(p):
            uid, mode, gid = modes.get(str(p), (0, 0o755, 0))
            return os.stat_result((st.S_IFDIR | mode, 0, 0, 0, uid, gid, 0, 0, 0, 0))
        return patch('mac_policy.Path.lstat', lambda self: lstat(self))

    def test_root_owned_tree_accepted_admin_group_write_tolerated(self):
        with self.fake({'/Applications': (0, 0o775, 80)}):
            self.assertEqual(mac_policy.trusted_tree('/Applications/Xcode.app/Contents/Developer/usr'),
                             '/Applications/Xcode.app/Contents/Developer/usr')

    def test_unsafe_trees_rejected(self):
        for bad in [(501, 0o755, 20), (0, 0o777, 0), (0, 0o775, 20)]:
            with self.fake({'/Applications/Xcode.app': bad}):
                self.assertIsNone(mac_policy.trusted_tree('/Applications/Xcode.app/Contents/Developer/usr'), bad)


class ChildEnvironment(unittest.TestCase):
    def test_git_uses_basic_proxy_auth_and_token_not_in_argv(self):
        import mac_child
        captured = {}
        def fake_exec(path, argv, env): captured.update(argv=argv, env=env)
        env = {'MCP_NET_PORT': '50123', 'MCP_NET_TOKEN': 'A' * 32}
        with patch.object(mac_child, 'require_identity'), patch.object(mac_child.resource, 'setrlimit'), \
                patch.object(mac_child.os, 'execve', side_effect=fake_exec), patch.dict(mac_child.os.environ, env, clear=True), \
                patch.object(mac_child, 'profile', return_value='(version 1)'), \
                patch.object(mac_child.sys, 'argv', ['c', '/Users/Shared/w', '/Users/Shared/w', 'git status', '/dev/ttys001']):
            mac_child.main()
        self.assertEqual(captured['env']['GIT_CONFIG_KEY_0'], 'http.proxyAuthMethod')
        self.assertEqual(captured['env']['GIT_CONFIG_VALUE_0'], 'basic')
        self.assertIn('A' * 32, captured['env']['HTTPS_PROXY'])
        self.assertNotIn('A' * 32, ' '.join(captured['argv']))

    def test_offline_child_has_no_proxy(self):
        import mac_child
        captured = {}
        with patch.object(mac_child, 'require_identity'), patch.object(mac_child.resource, 'setrlimit'), \
                patch.object(mac_child.os, 'execve', side_effect=lambda p, a, e: captured.update(env=e)), \
                patch.dict(mac_child.os.environ, {}, clear=True), patch.object(mac_child, 'profile', return_value='x') as prof, \
                patch.object(mac_child.sys, 'argv', ['c', '/Users/Shared/w', '/Users/Shared/w', 'ls', '/dev/ttys001']):
            mac_child.main()
        self.assertNotIn('HTTPS_PROXY', captured['env'])
        self.assertIsNone(prof.call_args.args[2])


class AgentV012(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); r = Path(self.tmp.name)
        self.work = r / 'work'; self.state = r / 'state'
        self.work.mkdir(mode=0o700); self.state.mkdir(mode=0o700)
        self.d = Dispatcher(self.work, self.state)
        self.a = await self.call('work_session', {'action': 'open', 'label': 'A', 'minutes': 10})
        self.b = await self.call('work_session', {'action': 'open', 'label': 'B', 'minutes': 10})

    async def asyncTearDown(self):
        await self.d.close(); self.tmp.cleanup()

    async def call(self, op, args, s=None):
        if s:
            args = {**args, **{k: s[k] for k in ['work_session_id', 'work_session_token']}}
        return await self.d.dispatch({'type': 'request', 'id': uuid.uuid4().hex, 'caller': 'test:client', 'op': op, 'args': args})

    async def test_new_mutations_require_session(self):
        (self.work / 'f').write_text('x')
        for op, args in [('delete_path', {'path': str(self.work / 'f')}),
                         ('copy_file', {'source': str(self.work / 'f'), 'destination': str(self.work / 'g')}),
                         ('upload_file', {'action': 'begin', 'path': str(self.work / 'h'), 'size': 1, 'sha256': '0' * 64})]:
            with self.assertRaises(PermissionError):
                await self.call(op, args)
        r = await self.call('read_binary', {'path': str(self.work / 'f')})
        self.assertEqual(base64.b64decode(r['content_base64']), b'x')

    async def test_upload_and_delete_through_dispatcher(self):
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10}, self.a)
        data = b'\x89PNG\r\n\x1a\n' + os.urandom(1000)
        b = await self.call('upload_file', {'action': 'begin', 'path': str(self.work / 'i.png'), 'size': len(data),
                                            'sha256': hashlib.sha256(data).hexdigest()}, self.a)
        with self.assertRaises(FileToolError):
            await self.call('upload_file', {'action': 'commit', 'upload_id': b['upload_id']}, self.b)
        await self.call('upload_file', {'action': 'chunk', 'upload_id': b['upload_id'], 'offset': 0,
                                        'data': base64.b64encode(data).decode()}, self.a)
        await self.call('upload_file', {'action': 'commit', 'upload_id': b['upload_id']}, self.a)
        self.assertEqual((self.work / 'i.png').read_bytes(), data)
        r = await self.call('delete_path', {'path': str(self.work / 'i.png')}, self.a)
        self.assertFalse((self.work / 'i.png').exists())
        await self.call('rollback_file', {'operation_id': r['operation_id']}, self.a)
        self.assertEqual((self.work / 'i.png').read_bytes(), data)

    async def test_close_drops_own_uploads(self):
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10}, self.a)
        await self.call('upload_file', {'action': 'begin', 'path': str(self.work / 'z'), 'size': 1, 'sha256': '0' * 64}, self.a)
        await self.call('work_session', {'action': 'close'}, self.a)
        self.assertEqual(self.d.uploads.jobs, {})

    async def test_enable_network_argument_validated_and_forwarded(self):
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10}, self.a)
        with patch.object(self.d.shell, 'enable', new=AsyncMock(return_value={'enabled': True})) as m:
            await self.call('enable_full_shell', {'minutes': 1, 'network': 'github'}, self.a)
            m.assert_awaited_once_with('work:' + self.a['work_session_id'], 1, 'github')
        with self.assertRaises(ValueError):
            await self.call('enable_full_shell', {'minutes': 1, 'proxy': 'x'}, self.a)

    async def test_shell_network_lease_starts_and_stops_proxy(self):
        shell = self.d.shell; identity = 'work:' + self.a['work_session_id']
        with patch('mac_shell.require_identity'):
            with self.assertRaises(ValueError):
                await shell.enable(identity, 1, 'internet')
            r = await shell.enable(identity, 1, 'github')
            self.assertTrue(shell.proxy.running)
            self.assertIn('github', r['network'])
            env = shell.child_env()
            self.assertEqual(env['MCP_NET_PORT'], str(shell.proxy.address()))
            await shell.enable(identity, 1, 'none')
            self.assertFalse(shell.proxy.running)
            self.assertNotIn('MCP_NET_PORT', shell.child_env())
            await shell.enable(identity, 1, 'github')
            await shell.disable()
            self.assertFalse(shell.proxy.running)
            self.assertEqual(shell.network, 'none')

    async def test_session_and_lock_operations_audited_with_session_id(self):
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10}, self.a)
        recent = (await self.call('who_is_working', {}))['recent_work_operations']
        sid = self.a['work_session_id']
        ops = [(x['operation'], x['work_session_id']) for x in recent if 'request_id' in x]
        self.assertIn(('work_session', sid), ops)
        self.assertIn(('work_lock', sid), ops)
        self.assertIn(('work_session', self.b['work_session_id']), ops)

    async def test_metadata_advertises_new_capabilities(self):
        import mac_agent
        meta = mac_agent.metadata()
        for name in ['delete_path', 'copy_file', 'read_binary', 'upload_file']:
            self.assertIn(name, meta['capabilities'])
        self.assertIn('github.com', meta['shell_network_hosts'])


class ConcurrentShell(unittest.IsolatedAsyncioTestCase):
    """Real processes through MacShell's job machinery (bash replaces the seatbelt child)."""

    async def asyncSetUp(self):
        import mac_shell
        self.ms = mac_shell
        self.tmp = tempfile.TemporaryDirectory(); r = Path(self.tmp.name)
        (r / 'work').mkdir(mode=0o700)
        self.f = FileTools([str(r / 'work')], str(r / 'journal'))
        self.work = str(r / 'work')
        self.cleanups = 0
        def cleanup():
            # Like stop_dedicated_children: every uid5000 process goes.
            self.cleanups += 1
            for j in self.shell.jobs.values():
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(j['proc'].pid, 9)
        real = subprocess.Popen
        def popen(argv, **kw):
            if len(argv) != 8 or not str(argv[3]).endswith('mac_child.py'):
                return real(argv, **kw)
            kw['env'] = {'PATH': '/usr/bin:/bin'}
            return real(['/bin/bash', '-c', argv[6]], **kw)
        self.patches = [patch.object(mac_shell, 'require_identity'), patch.object(mac_shell.subprocess, 'Popen', side_effect=popen)]
        for p in self.patches: p.start()
        self.shell = mac_shell.MacShell(self.f, self.work, str(r / 'logs'), capable=True)
        self.shell._trusted_code = lambda: None
        self.shell._start_watchdog = lambda: None
        self.shell._cleanup_uid = cleanup
        self.me = 'work:' + 'a' * 32
        await self.shell.enable(self.me, 1)

    async def asyncTearDown(self):
        for j in self.shell.running():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(j['proc'].pid, 9)
        for j in list(self.shell.jobs.values()):
            await asyncio.wait_for(j['done'].wait(), 5)
        self.shell.owner = None
        for p in self.patches: p.stop()
        self.f.close(); self.tmp.cleanup()

    async def wait_done(self, sid):
        await asyncio.wait_for(self.shell.jobs[sid]['done'].wait(), 5)

    async def test_four_concurrent_processes_with_separate_output(self):
        ids = [(await self.shell.start(self.me, 'echo out%d; sleep 3' % i))['session_id'] for i in range(4)]
        with self.assertRaises(PermissionError):
            await self.shell.start(self.me, 'true')
        await asyncio.sleep(.3)
        outs = [self.shell.read(self.me, i)['output'] for i in ids]
        for i, out in enumerate(outs):
            self.assertIn('out%d' % i, out)
        listed = await self.shell.session(self.me, {'action': 'list'})
        self.assertEqual(sum(x['running'] for x in listed['sessions']), 4)
        other = await self.shell.session('work:' + 'b' * 32, {'action': 'list'})
        self.assertEqual(other['sessions'], [])

    async def test_guard_held_while_any_runs_and_released_after_last(self):
        a = (await self.shell.start(self.me, 'sleep 3'))['session_id']
        b = (await self.shell.start(self.me, 'sleep 0.2'))['session_id']
        await self.wait_done(b)
        self.assertEqual(self.cleanups, 0, 'one process ending must not clean up the others')
        self.assertIsNotNone(self.shell.guard_fd)
        with self.assertRaises(FileToolError):
            self.f.write_file(self.work + '/x', 'x', session_id=self.me)
        await self.shell.session(self.me, {'action': 'stop', 'session_id': a})
        self.assertGreaterEqual(self.cleanups, 1)
        self.assertIsNone(self.shell.guard_fd)
        self.f.write_file(self.work + '/x', 'x', session_id=self.me)

    async def test_stop_one_keeps_others_running(self):
        a = (await self.shell.start(self.me, 'sleep 5'))['session_id']
        b = (await self.shell.start(self.me, 'sleep 5'))['session_id']
        r = await self.shell.session(self.me, {'action': 'stop', 'session_id': a})
        self.assertTrue(r['stopped'])
        self.assertTrue(self.shell.jobs[a]['done'].is_set())
        self.assertFalse(self.shell.jobs[b]['done'].is_set())
        self.assertEqual(self.cleanups, 0)

    async def test_disable_stops_everything(self):
        for _ in range(3):
            await self.shell.start(self.me, 'sleep 5')
        await self.shell.disable()
        self.assertEqual(self.shell.running(), [])
        self.assertIsNone(self.shell.guard_fd)

    async def test_processes_requires_lease(self):
        with patch.object(self.ms.subprocess, 'run', return_value=types.SimpleNamespace(
                stdout='5000 10 1 00:05 /bin/bash -c sleep\n501 11 1 00:01 other\n')):
            r = await self.shell.session(self.me, {'action': 'processes'})
        self.assertEqual([p['pid'] for p in r['processes']], [10])
        with self.assertRaises(PermissionError):
            await self.shell.session('work:' + 'b' * 32, {'action': 'processes'})

    async def test_network_profiles(self):
        with self.assertRaises(ValueError):
            await self.shell.enable(self.me, 1, 'internet')
        r = await self.shell.enable(self.me, 1, 'packages')
        self.assertIn('pypi.org', r['network'])
        self.assertIn('registry.npmjs.org', self.shell.proxy.hosts)
        await self.shell.enable(self.me, 1, 'github')
        self.assertNotIn('pypi.org', self.shell.proxy.hosts)
        await self.shell.enable(self.me, 1, 'none')
        self.assertFalse(self.shell.proxy.running)


class Catalog(unittest.TestCase):
    def test_gateway_catalog_has_new_tools_with_session_fields(self):
        import cg_tools
        tools = {t['name']: t for t in cg_tools.TOOLS}
        self.assertEqual(len(tools), len(cg_tools.TOOLS))
        for name in ['delete_path', 'copy_file', 'read_binary', 'upload_file']:
            self.assertIn('work_session_id', tools[name]['inputSchema']['properties'])
        self.assertEqual(tools['enable_full_shell']['inputSchema']['properties']['network']['enum'], ['none', 'github', 'packages'])
        self.assertIn('processes', tools['shell_session']['description'])
        json.dumps(cg_tools.TOOLS)


if __name__ == '__main__':
    unittest.main()
''',
'test_files_v012.py': r'''"""v0.12 reversible file tools: delete_path, copy_file, read_binary, upload_file.

Platform-neutral (runs in the Mac and VPS preflights).
"""
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from file_tools import FileTools, FileToolError
from work_sessions import WorkSessions
from upload_tools import Uploads


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.work = self.root / 'work'; self.work.mkdir(mode=0o700)
        self.f = FileTools([str(self.work)], str(self.root / 'journal'))
        self.w = WorkSessions(str(self.root / 'sessions'), self.f, boot='boot1')
        self.f.lock_provider = self.w.lock_provider
        self.a = self.w.open('test:client', 'chat A', 10)
        self.b = self.w.open('test:client', 'chat B', 10)

    def tearDown(self):
        self.w.close(); self.f.close(); self.tmp.cleanup()

    def auth(self, s): return ('test:client', s['work_session_id'], s['work_session_token'])
    def ident(self, s): return self.w.authenticate(*self.auth(s))
    def lock(self, s, path=None): return self.w.acquire(*self.auth(s), str(path or self.work), 5)

    def tree(self):
        base = self.work / 'proj'
        (base / 'src' / 'deep').mkdir(parents=True)
        (base / 'a.txt').write_text('alpha')
        (base / 'src' / 'b.bin').write_bytes(bytes(range(256)) * 4)
        (base / 'src' / 'deep' / 'c.txt').write_text('gamma')
        os.chmod(base / 'a.txt', 0o640)
        os.chmod(base / 'src', 0o711)
        return base

    def listing(self, base):
        out = {}
        for dirpath, dirs, files in os.walk(base):
            for name in dirs + files:
                p = Path(dirpath) / name
                st = p.lstat()
                out[str(p.relative_to(base))] = (oct(st.st_mode), p.read_bytes() if p.is_file() else None)
        return out


class Delete(Base):
    def test_requires_covering_lock(self):
        (self.work / 'x').write_text('x')
        with self.assertRaises(PermissionError):
            self.f.delete_path(str(self.work / 'x'), session_id=self.ident(self.a))
        self.lock(self.b, self.work / 'x')
        with self.assertRaises(PermissionError):
            self.f.delete_path(str(self.work / 'x'), session_id=self.ident(self.a))
        self.assertTrue((self.work / 'x').exists())

    def test_file_delete_and_rollback_restores_content_and_mode(self):
        p = self.work / 'x'; p.write_bytes(b'\x00\x01data'); os.chmod(p, 0o604)
        self.lock(self.a)
        r = self.f.delete_path(str(p), session_id=self.ident(self.a))
        self.assertEqual((r['deleted_files'], r['deleted_directories']), (1, 0))
        self.assertFalse(p.exists())
        self.f.rollback_file(r['operation_id'], session_id=self.ident(self.a))
        self.assertEqual(p.read_bytes(), b'\x00\x01data')
        self.assertEqual(p.stat().st_mode & 0o777, 0o604)

    def test_tree_delete_and_rollback_restores_everything(self):
        base = self.tree(); before = self.listing(base)
        self.lock(self.a)
        r = self.f.delete_path(str(base), session_id=self.ident(self.a))
        self.assertEqual((r['deleted_files'], r['deleted_directories']), (3, 3))
        self.assertFalse(base.exists())
        self.f.rollback_file(r['operation_id'], session_id=self.ident(self.a))
        self.assertEqual(self.listing(base), before)

    def test_rollback_refused_when_path_recreated(self):
        p = self.work / 'x'; p.write_text('old'); self.lock(self.a)
        r = self.f.delete_path(str(p), session_id=self.ident(self.a))
        p.write_text('new')
        with self.assertRaises(FileToolError) as e:
            self.f.rollback_file(r['operation_id'], session_id=self.ident(self.a))
        self.assertEqual(e.exception.code, 'ROLLBACK_CONFLICT')
        self.assertEqual(p.read_text(), 'new')

    def test_symlink_inside_tree_refuses_whole_delete(self):
        base = self.tree(); (base / 'src' / 'link').symlink_to(self.root)
        self.lock(self.a)
        with self.assertRaises(FileToolError):
            self.f.delete_path(str(base), session_id=self.ident(self.a))
        self.assertTrue((base / 'a.txt').exists())

    def test_root_and_missing_refused(self):
        self.lock(self.a)
        with self.assertRaises(FileToolError):
            self.f.delete_path(str(self.work), session_id=self.ident(self.a))
        with self.assertRaises(FileNotFoundError):
            self.f.delete_path(str(self.work / 'none'), session_id=self.ident(self.a))

    def test_total_size_bounded_before_reading(self):
        d = self.work / 'big'; d.mkdir()
        for i in range(3):
            (d / str(i)).write_bytes(b'x')
        self.lock(self.a)
        with patch.object(FileTools, 'MAX_COPY_BYTES', 2), patch.object(self.f, '_begin') as begin:
            with self.assertRaises(FileToolError):
                self.f.delete_path(str(d), session_id=self.ident(self.a))
            begin.assert_not_called()

    def test_entry_limit(self):
        d = self.work / 'many'; d.mkdir()
        for i in range(FileTools.MAX_TREE + 1):
            (d / str(i)).write_text('x')
        self.lock(self.a)
        with self.assertRaises(FileToolError) as e:
            self.f.delete_path(str(d), session_id=self.ident(self.a))
        self.assertEqual(e.exception.code, 'LIMIT')

    def test_failure_midway_restores_tree_and_journal_stays_usable(self):
        base = self.tree(); before = self.listing(base); self.lock(self.a)
        real = os.rmdir; calls = []
        def flaky(name, dir_fd=None):
            calls.append(name)
            if len(calls) == 2:
                raise OSError('simulated')
            return real(name, dir_fd=dir_fd)
        with patch('file_tools.os.rmdir', side_effect=flaky):
            with self.assertRaises(OSError):
                self.f.delete_path(str(base), session_id=self.ident(self.a))
        self.assertEqual(self.listing(base), before)
        self.f.write_file(str(self.work / 'after'), 'ok', session_id=self.ident(self.a))


class Copy(Base):
    def test_copy_tree_and_rollback(self):
        base = self.tree(); before = self.listing(base); self.lock(self.a, self.work / 'copy')
        r = self.f.copy_file(str(base), str(self.work / 'copy'), session_id=self.ident(self.a))
        self.assertEqual(r['entries'], 6)
        copied = self.listing(self.work / 'copy')
        self.assertEqual({k: v[1] for k, v in copied.items()}, {k: v[1] for k, v in before.items()})
        self.assertEqual(copied['a.txt'][0], before['a.txt'][0])
        self.f.rollback_file(r['operation_id'], session_id=self.ident(self.a))
        self.assertFalse((self.work / 'copy').exists())
        self.assertEqual(self.listing(base), before)

    def test_copy_rollback_refused_if_new_file_added(self):
        base = self.tree(); self.lock(self.a, self.work / 'copy')
        r = self.f.copy_file(str(base), str(self.work / 'copy'), session_id=self.ident(self.a))
        (self.work / 'copy' / 'src' / 'extra').write_text('mine')
        with self.assertRaises(FileToolError):
            self.f.rollback_file(r['operation_id'], session_id=self.ident(self.a))
        self.assertTrue((self.work / 'copy' / 'a.txt').exists())

    def test_no_overwrite_no_self_copy_and_lock_on_destination(self):
        base = self.tree(); (self.work / 'exists').write_text('x')
        with self.assertRaises(PermissionError):
            self.f.copy_file(str(base / 'a.txt'), str(self.work / 'n'), session_id=self.ident(self.a))
        self.lock(self.a)
        with self.assertRaises(FileToolError):
            self.f.copy_file(str(base / 'a.txt'), str(self.work / 'exists'), session_id=self.ident(self.a))
        with self.assertRaises(FileToolError):
            self.f.copy_file(str(base), str(base / 'src' / 'inner'), session_id=self.ident(self.a))
        r = self.f.copy_file(str(base / 'src' / 'b.bin'), str(self.work / 'b2'), session_id=self.ident(self.a))
        self.assertEqual((self.work / 'b2').read_bytes(), (base / 'src' / 'b.bin').read_bytes())
        self.assertEqual(r['bytes_copied'], 1024)

    def test_failed_copy_leaves_nothing(self):
        base = self.tree(); self.lock(self.a)
        real = self.f._atomic_file; calls = []
        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('disk full')
            return real(*a, **k)
        with patch.object(self.f, '_atomic_file', side_effect=flaky):
            with self.assertRaises(OSError):
                self.f.copy_file(str(base), str(self.work / 'copy'), session_id=self.ident(self.a))
        self.assertFalse((self.work / 'copy').exists())
        self.f.write_file(str(self.work / 'after'), 'ok', session_id=self.ident(self.a))


class Binary(Base):
    def test_read_binary_chunks_reassemble(self):
        data = os.urandom(500000); (self.work / 'blob').write_bytes(data)
        parts, offset = [], 0
        while True:
            r = self.f.read_binary(str(self.work / 'blob'), offset)
            parts.append(base64.b64decode(r['content_base64'])); offset += r['length']
            if r['eof']:
                break
        self.assertEqual(b''.join(parts), data)
        self.assertEqual(r['sha256'], hashlib.sha256(data).hexdigest())
        with self.assertRaises(FileToolError):
            self.f.read_binary(str(self.work / 'blob'), 0, 196609)

    def uploads(self):
        return Uploads(self.f, str(self.root / 'uploads'))

    def send(self, u, ident, path, data, overwrite=False, chunk=100000):
        b = u.begin(ident, path, len(data), hashlib.sha256(data).hexdigest(), overwrite)
        for i in range(0, len(data), chunk):
            u.chunk(ident, b['upload_id'], i, base64.b64encode(data[i:i + chunk]).decode())
        return u.commit(ident, b['upload_id'])

    def test_upload_commit_rollback_and_overwrite(self):
        u = self.uploads(); self.lock(self.a); ident = self.ident(self.a)
        p = str(self.work / 'img.png'); data = os.urandom(250000)
        r = self.send(u, ident, p, data)
        self.assertEqual(Path(p).read_bytes(), data)
        with self.assertRaises(FileToolError):
            u.begin(ident, p, 1, '0' * 64)
        r2 = self.send(u, ident, p, b'new', overwrite=True)
        self.assertEqual(Path(p).read_bytes(), b'new')
        self.f.rollback_file(r2['operation_id'], session_id=ident)
        self.assertEqual(Path(p).read_bytes(), data)
        self.f.rollback_file(r['operation_id'], session_id=ident)
        self.assertFalse(Path(p).exists())
        self.assertEqual(os.listdir(self.root / 'uploads'), [])
        u.close()

    def test_upload_rejects_bad_offset_checksum_owner_and_lock(self):
        u = self.uploads(); ia, ib = self.ident(self.a), self.ident(self.b)
        with self.assertRaises(PermissionError):
            u.begin(ia, str(self.work / 'x'), 3, hashlib.sha256(b'abc').hexdigest())
        self.lock(self.a)
        b = u.begin(ia, str(self.work / 'x'), 3, hashlib.sha256(b'abc').hexdigest())
        with self.assertRaises(FileToolError):
            u.chunk(ib, b['upload_id'], 0, base64.b64encode(b'abc').decode())
        with self.assertRaises(FileToolError):
            u.chunk(ia, b['upload_id'], 1, base64.b64encode(b'abc').decode())
        with self.assertRaises(FileToolError):
            u.chunk(ia, b['upload_id'], 0, 'not base64!')
        u.chunk(ia, b['upload_id'], 0, base64.b64encode(b'abd').decode())
        with self.assertRaises(FileToolError) as e:
            u.commit(ia, b['upload_id'])
        self.assertEqual(e.exception.code, 'CHECKSUM_MISMATCH')
        self.assertFalse((self.work / 'x').exists())
        u.close()

    def test_staging_bounded_and_cleared_on_restart(self):
        u = self.uploads(); self.lock(self.a); ia = self.ident(self.a)
        ids = [u.begin(ia, str(self.work / str(i)), 10, '0' * 64)['upload_id'] for i in range(4)]
        with self.assertRaises(FileToolError):
            u.begin(ia, str(self.work / 'five'), 10, '0' * 64)
        u.chunk(ia, ids[0], 0, base64.b64encode(b'12345').decode())
        u.close()
        (self.root / 'uploads' / (uuid.uuid4().hex + '.part')).write_bytes(b'left')
        u = self.uploads()
        self.assertEqual(os.listdir(self.root / 'uploads'), [])
        u.close()

    def test_expired_upload_is_dropped(self):
        now = [0.0]
        u = Uploads(self.f, str(self.root / 'uploads'), clock=lambda: now[0])
        self.lock(self.a); ia = self.ident(self.a)
        b = u.begin(ia, str(self.work / 'x'), 1, '0' * 64)
        now[0] += Uploads.TTL + 1
        with self.assertRaises(FileToolError):
            u.dispatch(ia, {'action': 'chunk', 'upload_id': b['upload_id'], 'offset': 0, 'data': 'YQ=='})
        u.close()


class JournalNeverLeftPrepared(Base):
    """A failed operation must close its record: 'prepared' blocks every later write."""

    def statuses(self):
        import json
        return sorted(json.loads((self.root / 'journal' / n).read_text())['status']
                      for n in os.listdir(self.root / 'journal') if n.endswith('.json'))

    def assert_usable(self, ident):
        self.assertNotIn('prepared', self.statuses())
        r = self.f.write_file(str(self.work / 'after.txt'), 'ok', session_id=ident)
        self.f.rollback_file(r['operation_id'], session_id=ident)

    def test_upload_commit_with_missing_parent(self):
        # Exact 2026-10-03 incident: commit into a directory that does not exist.
        u = Uploads(self.f, str(self.root / 'uploads')); self.lock(self.a); ia = self.ident(self.a)
        p = str(self.work / 'missing' / 'probe.bin'); data = os.urandom(1003)
        b = u.begin(ia, p, len(data), hashlib.sha256(data).hexdigest())
        u.chunk(ia, b['upload_id'], 0, base64.b64encode(data).decode())
        with self.assertRaises(FileToolError) as e:
            u.commit(ia, b['upload_id'])
        self.assertEqual(e.exception.code, 'PARENT_MISSING')
        self.assert_usable(ia)
        # The staged upload survives: create the directory and commit again.
        self.f.create_directory(str(self.work / 'missing'), session_id=ia)
        r = u.commit(ia, b['upload_id'])
        self.assertEqual(Path(p).read_bytes(), data)
        self.f.rollback_file(r['operation_id'], session_id=ia)
        self.assertFalse(Path(p).exists())
        u.close()

    def test_write_file_with_missing_parent(self):
        self.lock(self.a); ia = self.ident(self.a)
        with self.assertRaises(FileToolError) as e:
            self.f.write_file(str(self.work / 'nope' / 'x.txt'), 'x', session_id=ia)
        self.assertEqual(e.exception.code, 'PARENT_MISSING')
        self.assertEqual(self.statuses(), [])
        self.assert_usable(ia)

    def test_failed_publication_aborts_write_edit_and_upload(self):
        self.lock(self.a); ia = self.ident(self.a)
        target = self.work / 't.txt'; target.write_text('original')
        real = os.replace

        def failing(src, dst, **kw):
            if str(src).startswith('.mcp-write-'):
                raise OSError(28, 'No space left on device')
            return real(src, dst, **kw)

        with patch('file_tools.os.replace', failing):
            with self.assertRaises(OSError):
                self.f.write_file(str(target), 'new', session_id=ia)
            with self.assertRaises(OSError):
                self.f.edit_block(str(target), 'original', 'edited', session_id=ia)
            with self.assertRaises(OSError):
                self.f.write_bytes(str(target), b'bin', overwrite=True, session_id=ia)
        self.assertEqual(target.read_text(), 'original')
        self.assertEqual([n for n in os.listdir(self.work) if n.startswith('.mcp-write-')], [])
        self.assertEqual(self.statuses(), ['rolled_back'] * 3)
        self.assert_usable(ia)

    def test_failed_create_directory_removes_partial_tree(self):
        self.lock(self.a); ia = self.ident(self.a)
        real, calls = os.mkdir, []

        def failing(name, mode=0o777, **kw):
            calls.append(name)
            if len(calls) == 2:
                raise OSError(28, 'No space left on device')
            return real(name, mode, **kw)

        with patch('file_tools.os.mkdir', failing):
            with self.assertRaises(OSError):
                self.f.create_directory(str(self.work / 'a' / 'b' / 'c'), session_id=ia)
        self.assertFalse((self.work / 'a').exists())
        self.assertEqual(self.statuses(), ['rolled_back'])
        self.assert_usable(ia)

    def test_failed_move_keeps_source(self):
        self.lock(self.a); ia = self.ident(self.a)
        src = self.work / 's.txt'; src.write_text('keep'); dst = self.work / 'd.txt'
        real = os.fsync
        count = []

        def failing(fd):
            # Fail the fsync that follows unlinking the source (after the journal writes).
            if count == ['arm']:
                count.append('fired')
                raise OSError(5, 'I/O error')
            return real(fd)

        real_unlink = os.unlink

        def unlink(name, **kw):
            if name == 's.txt':
                count.append('arm')
            return real_unlink(name, **kw)

        with patch('file_tools.os.fsync', failing), patch('file_tools.os.unlink', unlink):
            with self.assertRaises(OSError):
                self.f.move_file(str(src), str(dst), session_id=ia)
        self.assertEqual(src.read_text(), 'keep')
        self.assertFalse(dst.exists())
        self.assertEqual(self.statuses(), ['rolled_back'])
        self.assert_usable(ia)

    def test_failed_move_before_unlink_drops_link(self):
        self.lock(self.a); ia = self.ident(self.a)
        src = self.work / 's.txt'; src.write_text('keep'); dst = self.work / 'd.txt'
        real_unlink = os.unlink

        def unlink(name, **kw):
            if name == 's.txt':
                raise OSError(1, 'Operation not permitted')
            return real_unlink(name, **kw)

        with patch('file_tools.os.unlink', unlink):
            with self.assertRaises(OSError):
                self.f.move_file(str(src), str(dst), session_id=ia)
        self.assertEqual(src.read_text(), 'keep')
        self.assertFalse(dst.exists())
        self.assertEqual(self.statuses(), ['rolled_back'])
        self.assert_usable(ia)


if __name__ == '__main__':
    unittest.main()
''',
'mac_v012_selftest.py': r'''"""UID5000 v0.12 smoke test, only while the central Mac daemon is stopped.

Covers the v0.11 coordination checks, the new reversible file tools, and the
real seatbelt behaviour of the shell child with and without the GitHub lease.
"""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import pty
import subprocess
import sys
import time
import uuid
sys.path.insert(0, '/Library/MCPAndreaMacMioV09/code')
from mac_agent import Dispatcher, WORK, CODE
from mac_guard import require_identity, stop_dedicated_children
from net_proxy import GitHubProxy

PROBE = r"""
import base64, os, socket, sys
port = int(sys.argv[1]); token = sys.argv[2]
def attempt(addr):
    try:
        s = socket.create_connection(addr, 3)
    except OSError as e:
        return 'blocked:' + type(e).__name__
    return s
s = attempt(('127.0.0.1', port))
if isinstance(s, str):
    print('PROXY', s)
else:
    auth = base64.b64encode(('mcp:' + token).encode())
    s.sendall(b'CONNECT example.com:443 HTTP/1.1\r\nProxy-Authorization: Basic ' + auth + b'\r\n\r\n')
    print('PROXY', s.recv(64).split(b'\r\n')[0].decode())
d = attempt(('1.1.1.1', 443))
print('DIRECT', d if isinstance(d, str) else 'open')
"""


def sandboxed(command, cwd, proxy=None, timeout=30):
    """Run through the real mac_child exactly as the shell does.

    Blocking: call it in a worker thread so the proxy keeps serving the loop.
    """
    master, slave = pty.openpty()
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
    if proxy:
        env.update(MCP_NET_PORT=str(proxy.address()), MCP_NET_TOKEN=proxy.token)
    proc = subprocess.Popen([sys.executable, '-I', '-B', str(CODE / 'mac_child.py'), str(WORK), cwd,
                             command, os.ttyname(slave)], stdin=slave, stdout=slave, stderr=slave,
                            close_fds=True, start_new_session=True, cwd=cwd, env=env)
    os.close(slave)
    os.set_blocking(master, False)
    output = bytearray(); end = time.monotonic() + timeout
    try:
        while time.monotonic() < end:
            try:
                chunk = os.read(master, 65536)
                if chunk:
                    output.extend(chunk)
            except BlockingIOError:
                pass
            except OSError:
                break
            if proc.poll() is not None:
                with __import__('contextlib').suppress(OSError):
                    output.extend(os.read(master, 65536))
                break
            time.sleep(.05)
        else:
            proc.kill()
    finally:
        os.close(master)
        if proc.poll() is None:
            proc.kill()
        proc.wait(5)
        stop_dedicated_children()
    return proc.returncode, output.decode(errors='replace')


def lines(text, key):
    return [l.split(None, 1)[1].strip() for l in text.splitlines() if l.startswith(key + ' ')]


async def main():
    require_identity(); d = Dispatcher(); operations = []; checks = []; sessions = []; info = {}
    caller = 'deployment:coordination-v012'
    async def call(op, s=None, **args):
        if s: args.update(work_session_id=s['work_session_id'], work_session_token=s['work_session_token'])
        return await d.dispatch({'type': 'request', 'id': uuid.uuid4().hex, 'caller': caller, 'op': op, 'args': args})
    async def refused(op, s=None, **args):
        try: await call(op, s, **args)
        except PermissionError: return
        raise AssertionError(op + ' was not refused')
    folder = str(WORK / ('v012_selftest_' + uuid.uuid4().hex))
    proxy = GitHubProxy()
    try:
        a = await call('work_session', action='open', label='selftest A', minutes=5); sessions.append(a)
        b = await call('work_session', action='open', label='selftest B', minutes=5); sessions.append(b)
        await refused('create_directory', a, path=folder)
        await refused('create_directory', path=folder)
        checks.append('writes need session and lock')
        lock = await call('work_lock', a, action='acquire', path=folder, minutes=5)
        await refused('work_lock', b, action='acquire', path=folder + '/x', minutes=5)
        checks.append('descendant conflict between sessions')
        operations.append((await call('create_directory', a, path=folder))['operation_id'])
        path = folder + '/prova.txt'
        operations.append((await call('write_file', a, path=path, content='MCP_V012_MAC_OK\n'))['operation_id'])
        await refused('write_file', b, path=path, content='other')
        await refused('rollback_file', b, operation_id=operations[-1])
        checks.append('foreign write and rollback refused')
        r = await call('start_search', a, path=folder, pattern='MCP_V012_MAC_OK')
        await asyncio.wait_for(d.search.jobs[r['search_id']]['task'], 5)
        await refused('get_more_search_results', b, search_id=r['search_id'])
        assert (await call('get_more_search_results', a, search_id=r['search_id']))['total_results'] == 1
        checks.append('search private to its session')

        data = bytes(range(256)) * 300
        up = await call('upload_file', a, action='begin', path=folder + '/blob.bin', size=len(data),
                        sha256=hashlib.sha256(data).hexdigest())
        await refused('upload_file', b, action='begin', path=folder + '/b.bin', size=1, sha256='0' * 64)
        await call('upload_file', a, action='chunk', upload_id=up['upload_id'], offset=0,
                   data=base64.b64encode(data).decode())
        operations.append((await call('upload_file', a, action='commit', upload_id=up['upload_id']))['operation_id'])
        got = await call('read_binary', path=folder + '/blob.bin')
        assert got['sha256'] == hashlib.sha256(data).hexdigest() and got['size'] == len(data), got
        checks.append('verified binary upload and read')
        await call('create_directory', a, path=folder + '/albero/sotto')
        await call('write_file', a, path=folder + '/albero/sotto/f.txt', content='albero')
        operations.append((await call('copy_file', a, source=folder + '/albero', destination=folder + '/copia'))['operation_id'])
        assert Path(folder + '/copia/sotto/f.txt').read_text() == 'albero'
        removed = await call('delete_path', a, path=folder + '/albero')
        assert not Path(folder + '/albero').exists()
        await refused('rollback_file', b, operation_id=removed['operation_id'])
        await call('rollback_file', a, operation_id=removed['operation_id'])
        assert Path(folder + '/albero/sotto/f.txt').read_text() == 'albero'
        removed = await call('delete_path', a, path=folder + '/albero')
        checks.append('copy and delete trees with rollback')

        state = await call('who_is_working')
        assert any(l['lock_id'] == lock['lock_id'] for l in state['work_locks']), state
        assert a['work_session_token'] not in json.dumps(state), 'token leaked'
        checks.append('who_is_working lists lock without tokens')
        r = await call('shell_exec', command='sw_vers')
        assert r['exit_code'] == 0 and not r['timed_out'], r
        checks.append('baseline sw_vers without session')

        code, out = await asyncio.to_thread(sandboxed, '/usr/bin/true', folder)
        assert code == 0, out
        checks.append('offline seatbelt profile with developer tools compiles')
        await proxy.start()
        script = folder + '/net_probe.py'
        Path(script).write_text(PROBE)
        probe = '%s -I -B %s %d %s' % (os.path.realpath(sys.executable), script, proxy.address(), proxy.token)
        code, out = await asyncio.to_thread(sandboxed, probe, folder, proxy)
        info['network_probe'] = out[-600:]
        assert lines(out, 'PROXY') == ['HTTP/1.1 403 Forbidden'], out
        assert lines(out, 'DIRECT') and lines(out, 'DIRECT')[0].startswith('blocked'), out
        checks.append('network lease: only the proxy port, non-GitHub host refused, direct internet blocked')
        code, out = await asyncio.to_thread(sandboxed, probe, folder, None)
        assert lines(out, 'PROXY') and lines(out, 'PROXY')[0].startswith('blocked'), out
        assert lines(out, 'DIRECT')[0].startswith('blocked'), out
        checks.append('offline shell cannot reach the proxy or internet')
        code, out = await asyncio.to_thread(sandboxed, '/usr/bin/git ls-remote https://github.com/git/git HEAD', folder, proxy, 25)
        info['github_git_ls_remote'] = 'ok' if code == 0 and 'HEAD' in out else 'failed: ' + out[-400:]
        os.unlink(script)

        whole = await call('work_lock', a, action='acquire', path=str(WORK), minutes=5)
        await call('enable_full_shell', a, minutes=2)
        s1 = await call('shell_session', a, action='start', command='sleep 20', cwd=folder)
        s2 = await call('shell_session', a, action='start', command='echo CONCURRENT_OK; sleep 20', cwd=folder)
        await refused('shell_session', b, action='start', command='true')
        listed = await call('shell_session', a, action='list')
        assert sum(x['running'] for x in listed['sessions']) == 2, listed
        await call('shell_session', a, action='stop', session_id=s1['session_id'])
        # A seatbelt shell needs ~1.5-2 s on the Mac before its first output: wait for it.
        seen, end = '', time.monotonic() + 15
        while time.monotonic() < end:
            r2 = await call('shell_session', a, action='read', session_id=s2['session_id'])
            seen += r2['output']
            assert r2['running'], r2
            if 'CONCURRENT_OK' in seen:
                break
            await asyncio.sleep(.25)
        assert 'CONCURRENT_OK' in seen, (seen, r2)
        procs = await call('shell_session', a, action='processes')
        assert procs['processes'], procs
        await call('disable_full_shell', a)
        await call('work_lock', a, action='release', lock_id=whole['lock_id'])
        checks.append('two concurrent shell processes, stop one keeps the other, disable stops all')
    finally:
        await d.shell.disable()
        await proxy.stop()
        await d.search.close()
        for operation in reversed(operations):
            await call('rollback_file', sessions[0], operation_id=operation)
        for s in sessions: await call('work_session', s, action='close')
        state = await call('who_is_working')
        await d.close()
    assert not state['work_sessions'] and not state['work_locks'] and not state['shell_enabled'], state
    assert not Path(folder).exists(), 'selftest folder left behind'
    checks.append('sessions closed, locks released, test files rolled back')
    print(json.dumps({'passed': True, 'uid': os.getuid(), 'checks': checks, 'info': info}))


if __name__ == '__main__': asyncio.run(main())
''',
'cg_tools.py': r'''TOOLS=[{'name': 'list_machines', 'description': 'List registered machines and online status.', 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}, {'name': 'shell_exec', 'description': 'Execute a command. VPS arbitrary commands need a temporary isolated-shell lease; network is disabled and access is limited to its workspace. Long commands return a session_id; poll shell_session read. Baseline status commands work without enabling.', 'inputSchema': {'type': 'object', 'required': ['machine', 'command'], 'properties': {'machine': {'type': 'string'}, 'command': {'type': 'string'}, 'cwd': {'type': 'string'}, 'timeout': {'type': 'number'}}}}, {'name': 'shell_session', 'description': 'Manage an isolated PTY: start/send/read/stop. Session belongs to its OAuth authorization. VPS allows one active workspace session; disable/expiry stops descendants. Read may return has_more.', 'inputSchema': {'type': 'object', 'required': ['machine', 'action'], 'properties': {'machine': {'type': 'string'}, 'action': {'type': 'string'}, 'session_id': {'type': 'string'}, 'command': {'type': 'string'}, 'data': {'type': 'string'}}}}, {'name': 'read_file', 'description': 'Read file through agent.', 'inputSchema': {'type': 'object', 'required': ['machine', 'path'], 'properties': {'machine': {'type': 'string'}, 'path': {'type': 'string'}, 'max_bytes': {'type': 'integer'}}}}, {'name': 'write_file', 'description': 'Write file with rollback operation id.', 'inputSchema': {'type': 'object', 'required': ['machine', 'path', 'content'], 'properties': {'machine': {'type': 'string'}, 'path': {'type': 'string'}, 'content': {'type': 'string'}}}}, {'name': 'rollback_file', 'description': 'Rollback write operation.', 'inputSchema': {'type': 'object', 'required': ['machine', 'operation_id'], 'properties': {'machine': {'type': 'string'}, 'operation_id': {'type': 'string'}}}}, {'name': 'enable_full_shell', 'description': 'Acquire a temporary shell lease for the authenticated authorization. Available only on machines with verified containment; VPS shell is workspace-only and offline. Multiple chats can share the same authorization.', 'inputSchema': {'type': 'object', 'required': ['machine', 'minutes'], 'properties': {'machine': {'type': 'string'}, 'minutes': {'type': 'integer', 'minimum': 1, 'maximum': 240}}}}, {'name': 'disable_full_shell', 'description': 'Disable temporary shell access and terminate its active sessions and descendants.', 'inputSchema': {'type': 'object', 'required': ['machine'], 'properties': {'machine': {'type': 'string'}}}}, {'name': 'who_is_working', 'description': 'Show active cross-session locks and recent operations on a Mac.', 'inputSchema': {'type': 'object', 'required': ['machine'], 'properties': {'machine': {'type': 'string'}}}}, {'name': 'xcode_list', 'description': 'List the Xcode container and simulators on a Mac.', 'inputSchema': {'type': 'object', 'required': ['machine'], 'properties': {'machine': {'type': 'string'}, 'project': {'type': 'string'}, 'workspace': {'type': 'string'}}}}, {'name': 'xcode_build', 'description': 'Build an Xcode project on a Mac (validated parameters; operation=test for the QA suite).', 'inputSchema': {'type': 'object', 'required': ['machine', 'scheme', 'configuration', 'destination'], 'properties': {'machine': {'type': 'string'}, 'project': {'type': 'string'}, 'workspace': {'type': 'string'}, 'scheme': {'type': 'string'}, 'configuration': {'type': 'string'}, 'destination': {'type': 'string'}, 'operation': {'type': 'string'}, 'action': {'type': 'string'}, 'job_id': {'type': 'string'}, 'result_name': {'type': 'string'}}}}, {'name': 'xcode_test', 'description': 'Run the fixed La Marruca QA tests on a Mac (start/status/artifacts).', 'inputSchema': {'type': 'object', 'required': ['machine', 'project', 'scheme', 'configuration', 'destination'], 'properties': {'machine': {'type': 'string'}, 'project': {'type': 'string'}, 'scheme': {'type': 'string'}, 'configuration': {'type': 'string'}, 'destination': {'type': 'string'}, 'action': {'type': 'string'}, 'job_id': {'type': 'string'}, 'result_name': {'type': 'string'}}}}, {'name': 'admin_request', 'description': 'Request execution of an administrator (root) command on the VPS. The exact command is sent to Andrea on Telegram; it runs only after he approves. Returns a request_id: poll admin_result.', 'inputSchema': {'type': 'object', 'required': ['command', 'reason'], 'properties': {'command': {'type': 'string'}, 'reason': {'type': 'string'}}}}, {'name': 'admin_result', 'description': 'Get status/output of an admin_request (waiting, done, rejected, expired, error).', 'inputSchema': {'type': 'object', 'required': ['request_id'], 'properties': {'request_id': {'type': 'string'}}}}]
NAMES={x["name"] for x in TOOLS}

from file_schema import install_schema
TOOLS=install_schema(TOOLS)
NAMES={x['name'] for x in TOOLS}

from search_schema import SEARCH_TOOLS, SEARCH_NAMES
TOOLS = [t for t in TOOLS if t['name'] not in SEARCH_NAMES] + SEARCH_TOOLS
NAMES = {t['name'] for t in TOOLS}

from work_schema import install_schema as install_work_schema
TOOLS = install_work_schema(TOOLS)
NAMES = {t["name"] for t in TOOLS}

# v0.12: optional GitHub-only network for the Mac shell lease.
for _t in TOOLS:
    if _t['name'] == 'enable_full_shell':
        _t['inputSchema']['properties']['network'] = {'type': 'string', 'enum': ['none', 'github', 'packages'], 'default': 'none'}
        _t['description'] += " On mac_mio, network='github' lets the shell reach only GitHub over HTTPS through the agent proxy; 'packages' adds pypi and the npm registry; default 'none'."
    if _t['name'] == 'shell_session':
        _t['description'] += " Actions: start, send, read, stop, list (this session's processes), processes (uid5000 inventory, mac_mio). On mac_mio up to 4 processes run concurrently in one lease."
''',
}


def sha(data):return hashlib.sha256(data).hexdigest()

def trusted_directory(path):
    for p in [path]+list(path.parents):
        st=p.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
            raise RuntimeError('untrusted directory: '+str(p))

def read(path, owner=0):
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=owner or st.st_mode&0o022 or st.st_nlink!=1:
            raise RuntimeError('unsafe file: '+str(path))
        data=f.read(2*1024*1024+1)
    if len(data)>2*1024*1024:raise RuntimeError('file exceeds limit')
    return data

def digest(path):
    if path.is_symlink():raise RuntimeError('symlink destination rejected')
    return sha(read(path)) if path.exists() else None

def atomic(path,data,mode=0o644,uid=0,gid=0):
    trusted_directory(path.parent)
    if path.is_symlink():raise RuntimeError('symlink destination rejected')
    fd,name=tempfile.mkstemp(prefix='.search-v010-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchown(f.fileno(),uid,gid);os.fchmod(f.fileno(),mode)
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,str(path))
        dfd=os.open(str(path.parent),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:
        if os.path.exists(name):os.unlink(name)

def record(status,**fields):
    atomic(RECEIPT,json.dumps(dict(status=status,time=time.time(),**fields),indent=2).encode())

def run(argv,timeout=30):
    return subprocess.run(argv,check=True,capture_output=True,text=True,timeout=timeout,
                          env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C.UTF-8'})

def backup():
    trusted_directory(BACKUP.parent)
    BACKUP.mkdir(mode=0o700)
    manifest={}
    for name in ORIGINAL:
        path=BASE/name
        if ORIGINAL[name] is None:manifest[name]=None;continue
        data=read(path);st=path.lstat()
        manifest[name]={'sha256':sha(data),'mode':stat.S_IMODE(st.st_mode),'uid':st.st_uid,'gid':st.st_gid}
        atomic(BACKUP/name,data,0o600)
    atomic(BACKUP/'manifest.json',json.dumps(manifest,indent=2).encode(),0o600)
    return manifest

def verify_restore(strict=True):
    manifest=json.loads(read(BACKUP/'manifest.json'))
    if set(manifest)!=set(ORIGINAL):raise RuntimeError('unexpected backup manifest')
    # Check every destination and every backup before restoring any file.
    for name,old in ORIGINAL.items():
        current=digest(BASE/name)
        accepted={sha(PAYLOAD[name])} if strict else {old,sha(PAYLOAD[name])}
        if current not in accepted:raise RuntimeError('rollback conflict: '+name)
        if old is not None:
            if not manifest[name] or sha(read(BACKUP/name))!=old or manifest[name]['sha256']!=old:
                raise RuntimeError('backup mismatch: '+name)
    return manifest


def restore(strict=True):
    manifest=verify_restore(strict)
    for name,meta in manifest.items():
        if meta is None:
            if (BASE/name).exists():(BASE/name).unlink()
        else:atomic(BASE/name,read(BACKUP/name),meta['mode'],meta['uid'],meta['gid'])

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
    text=run(['/bin/ps','-axo','uid=,pid=,ppid=,stat=,args=']).stdout
    pids=set()
    for row in text.splitlines():
        p=row.split(None,4)
        if len(p)<4 or p[0]!='5000' or p[3].startswith('Z'):continue
        # macOS starts these per-user agents on demand from launchd (exact path and arguments).
        if p[2]=='1' and len(p)==5 and p[4].strip() in SYSTEM_AGENTS:continue
        pids.add(int(p[1]))
    if pids!=(set() if daemon_pid is None else {daemon_pid}):raise RuntimeError('dedicated account busy')


def service_state():
    result=subprocess.run(['/bin/launchctl','print','system/'+LABEL],
        capture_output=True,text=True,timeout=10,
        env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C.UTF-8'})
    if result.returncode==0:
        match=re.search(r'\bpid = (\d+)\b',result.stdout)
        return {'loaded':True,'pid':int(match.group(1)) if match else None}
    if result.returncode==113 and 'Could not find service' in result.stderr:
        return {'loaded':False,'pid':None}
    raise RuntimeError('cannot inspect daemon: '+result.stderr[-400:])


def check_sources():
    identity();trusted_directory(BASE)
    for name,expected in {**ORIGINAL,**DEPENDENCIES}.items():
        if digest(BASE/name)!=expected:raise RuntimeError('live source changed: '+name)
    state=service_state()
    if state['pid'] is not None:
        if active_pid()!=state['pid']:raise RuntimeError('daemon changed during preflight')
    no_other_processes(state['pid'])
    return {'source_check_passed':True,'target':'mac_mio','new_version':NEW_VERSION,
            'daemon_loaded':state['loaded'],'administrative_preflight_pending':True,'rental_touched':False}


def load_package():
    global PAYLOAD,TESTS
    carried={n:src.encode() for n,src in SOURCES.items()}
    if {n:sha(b) for n,b in carried.items()}!=SOURCE_SHA:raise RuntimeError('unexpected embedded sources')
    PAYLOAD={n:carried[n] for n in ORIGINAL}
    # Unchanged dependencies come from the live, hash-pinned installation.
    TESTS={n:carried[n] if n in carried else read(BASE/n) for n in TEST_NAMES}
    for n,h in DEPENDENCIES.items():
        if sha(TESTS[n])!=h:raise RuntimeError('live dependency changed: '+n)
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
    code="import sys,unittest;sys.path.insert(0,"+repr(str(TEST_CODE))+");s=unittest.defaultTestLoader.loadTestsFromNames(['test_work_core','test_search','test_v012','test_files_v012']);r=unittest.TextTestRunner(verbosity=2).run(s);sys.exit(0 if r.wasSuccessful() else 1)"
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
    state=service_state()
    if state['pid'] is not None:
        if active_pid()!=state['pid']:raise RuntimeError('daemon changed before stop')
    no_other_processes(state['pid'])
    if state['loaded']:run(['/bin/launchctl','bootout','system/'+LABEL],30)
    # launchd removes the job asynchronously; wait for BOTH the job and its
    # processes. Never treat a failed status probe as proof of absence.
    end=time.monotonic()+20
    while time.monotonic()<end:
        state=service_state()
        if not state['loaded']:
            try:no_other_processes();return
            except RuntimeError:pass
        time.sleep(.2)
    raise RuntimeError('daemon or dedicated processes did not exit within 20 seconds')


def prepare_backup():
    if BACKUP.exists() or BACKUP.is_symlink():raise RuntimeError('backup exists; inspect before retry')
    return backup()


def start_daemon(expected_version):
    if service_state()['loaded']:raise RuntimeError('refusing to bootstrap an already loaded daemon')
    no_other_processes()
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
    code="import runpy;runpy.run_path("+repr(str(TEST_CODE/'mac_v012_selftest.py'))+",run_name='__main__')"
    r=child(code,timeout=120)
    atomic(TEST_CODE/'selftest.log',(r.stdout+r.stderr).encode()[-65536:])
    if r.returncode:raise RuntimeError('v0.12 p2 smoke failed: '+r.stderr[-1000:])
    result=json.loads(r.stdout.strip().splitlines()[-1])
    if result.get('passed') is not True or result.get('uid')!=5000:raise RuntimeError('invalid smoke receipt')
    SMOKE_INFO.update(result.get('info',{}))
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
            check_sources()
            try:preflight()
            except Exception as e:
                record('preflight_failed',reason=str(e)[:1200],live_modules_modified=False);raise
            check_sources()
            stopped=False;installed=False
            try:
                with workspace_guard():
                    check_sources();manifest=prepare_backup();stopped=True;stop_daemon()
                    for name,data in PAYLOAD.items():
                        meta=manifest[name] or {'mode':0o444,'uid':0,'gid':0}
                        atomic(BASE/name,data,meta['mode'],meta['uid'],meta['gid'])
                    installed=True
                checks=selftest();ready=start_daemon(NEW_VERSION);stopped=False
                record('active',version=NEW_VERSION,uid=5000,agent_pid=ready['pid'],checks=checks,info=SMOKE_INFO,
                       backup=str(BACKUP),hashes={n:sha(b) for n,b in PAYLOAD.items()},rental_touched=False)
                print(json.dumps({'status':'active','checks':checks,'info':SMOKE_INFO,'uid':5000},indent=2))
            except Exception as error:
                try:
                    if installed and not stopped:
                        with workspace_guard():stop_daemon();stopped=True
                    if stopped:
                        # A failed bootstrap can leave a loaded daemon: stop only this label.
                        with workspace_guard():
                            stop_daemon()
                            restore(strict=False)
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
