"""v0.12 reversible file tools: delete_path, copy_file, read_binary, upload_file.

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


if __name__ == '__main__':
    unittest.main()
