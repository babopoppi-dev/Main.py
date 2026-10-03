import ast
import contextlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from file_tools import FileTools, FileToolError
from file_schema import FILE_TOOLS

SID = 'chatgpt-phase1-tests'


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / 'workspace'
        self.root.mkdir()
        self.state = self.base / 'state'
        self.engine = FileTools([str(self.root)], str(self.state))

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def p(self, name):
        return str(self.root / name)

    def write(self, name='a.txt', content='alpha\nbeta\n'):
        return self.engine.write_file(self.p(name), content, session_id=SID)

    def test_complete_chain_and_persisted_rollback(self):
        a, b = self.p('a.txt'), self.p('b.txt')
        original = b'original\r\nsecond\r\n'
        Path(a).write_bytes(original)
        os.chmod(a, 0o640)
        before = os.stat(a)
        w = self.engine.write_file(a, 'alpha\nbeta\n', session_id=SID)
        e = self.engine.edit_block(a, 'beta', 'gamma', session_id=SID)
        m = self.engine.move_file(a, b, session_id=SID)
        self.assertFalse(Path(a).exists())
        self.engine.close()
        self.engine = FileTools([str(self.root)], str(self.state))
        for operation in (m, e, w):
            self.engine.rollback_file(operation['operation_id'], session_id=SID)
        self.assertEqual(Path(a).read_bytes(), original)
        self.assertFalse(Path(b).exists())
        self.assertEqual(os.stat(a).st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(os.stat(a).st_mode & 0o777, 0o640)

    def test_create_file_then_restore_absence(self):
        r = self.write()
        self.engine.rollback_file(r['operation_id'], session_id=SID)
        self.assertFalse(Path(self.p('a.txt')).exists())

    def test_append_chunks(self):
        first = self.write(content='alpha\n')
        second = self.engine.write_file(self.p('a.txt'), 'beta\n', mode='append', session_id=SID)
        self.assertEqual(Path(self.p('a.txt')).read_text(), 'alpha\nbeta\n')
        self.engine.rollback_file(second['operation_id'], session_id=SID)
        self.assertEqual(Path(self.p('a.txt')).read_text(), 'alpha\n')
        self.engine.rollback_file(first['operation_id'], session_id=SID)

    def test_negative_offset(self):
        self.write(content='one\ntwo\nthree\n')
        r = self.engine.read_file(self.p('a.txt'), -2)
        self.assertEqual(r['content'], 'two\nthree\n')
        self.assertEqual(self.engine.read_file(self.p('a.txt'), 1, 1)['content'], 'two\n')

    def test_binary_rejected(self):
        Path(self.p('binary')).write_bytes(b'a\0b')
        with self.assertRaises(FileToolError) as e:
            self.engine.read_file(self.p('binary'))
        self.assertEqual(e.exception.code, 'BINARY_FILE')

    def test_batch_partial_error(self):
        self.write()
        r = self.engine.read_multiple_files([self.p('missing'), self.p('a.txt')])
        self.assertFalse(r['files'][0]['success'])
        self.assertTrue(r['files'][1]['success'])

    def test_edit_count_no_write(self):
        self.write(content='same same')
        count = len(list(self.state.glob('*.json')))
        with self.assertRaises(FileToolError) as e:
            self.engine.edit_block(self.p('a.txt'), 'same', 'other', session_id=SID)
        self.assertEqual(e.exception.details['occurrences_found'], 2)
        self.assertEqual(Path(self.p('a.txt')).read_text(), 'same same')
        self.assertEqual(len(list(self.state.glob('*.json'))), count)

    def test_missing_edit_hint(self):
        self.write(content='product olive oil\n')
        with self.assertRaises(FileToolError) as e:
            self.engine.edit_block(self.p('a.txt'), 'product oliv oil', 'new', session_id=SID)
        self.assertEqual(e.exception.details['closest_text'], 'product olive oil')

    def test_multiple_edits(self):
        self.write(content='same same')
        self.engine.edit_block(self.p('a.txt'), 'same', 'other', 2, SID)
        self.assertEqual(Path(self.p('a.txt')).read_text(), 'other other')

    def test_parent_and_sibling_escape(self):
        for path in (str(self.root) + '/../outside', str(self.root) + '-other/file'):
            with self.assertRaises(FileToolError):
                self.engine.write_file(path, 'x', session_id=SID)

    def test_symlink_escape_read_write_and_list(self):
        outside = self.base / 'bitcoin'
        outside.mkdir()
        secret = outside / 'probe'
        secret.write_text('fixture only')
        os.symlink(str(outside), self.p('escape'))
        for operation in (lambda: self.engine.read_file(self.p('escape/probe')),
                          lambda: self.engine.write_file(self.p('escape/probe'), 'changed', session_id=SID),
                          lambda: self.engine.list_directory(self.p('escape'))):
            with self.assertRaises((FileToolError, OSError)):
                operation()
        self.assertEqual(secret.read_text(), 'fixture only')
        self.assertIn('[SYMLINK BLOCKED] escape', self.engine.list_directory(str(self.root))['entries'])

    def test_final_symlink(self):
        self.write()
        os.symlink(self.p('a.txt'), self.p('link'))
        for name, a in [('read_file', {'path': self.p('link')}),
                        ('write_file', {'path': self.p('link'), 'content': 'x'}),
                        ('get_file_info', {'path': self.p('link')})]:
            with self.assertRaises((FileToolError, OSError)):
                self.engine.dispatch(name, a, SID)

    def test_nested_directory_rollback(self):
        r = self.engine.create_directory(self.p('a/b/c'), SID)
        self.engine.rollback_file(r['operation_id'], SID)
        self.assertFalse(Path(self.p('a')).exists())

    def test_directory_rollback_refuses_new_file(self):
        r = self.engine.create_directory(self.p('a/b'), SID)
        Path(self.p('a/b/external')).write_text('keep')
        with self.assertRaises(FileToolError):
            self.engine.rollback_file(r['operation_id'], SID)
        self.assertTrue(Path(self.p('a/b/external')).exists())

    def test_move_refuses_overwrite(self):
        self.write('a.txt', 'a')
        self.write('b.txt', 'b')
        with self.assertRaises(FileToolError):
            self.engine.move_file(self.p('a.txt'), self.p('b.txt'), SID)
        self.assertEqual(Path(self.p('b.txt')).read_text(), 'b')

    def test_rollback_conflict(self):
        r = self.write()
        Path(self.p('a.txt')).write_text('external edit')
        with self.assertRaises(FileToolError) as e:
            self.engine.rollback_file(r['operation_id'], SID)
        self.assertEqual(e.exception.code, 'ROLLBACK_CONFLICT')
        self.assertEqual(Path(self.p('a.txt')).read_text(), 'external edit')

    def test_state_is_not_accessible(self):
        nested = self.root / 'private-state'
        self.engine.close()
        self.engine = FileTools([str(self.root)], str(nested))
        with self.assertRaises(FileToolError):
            self.engine.read_file(str(nested / 'guard'))

    def test_limits(self):
        self.engine.max_chunk = 10
        with self.assertRaises(FileToolError):
            self.write(content='x' * 11)
        self.engine.max_chunk = 256 * 1024
        for i in range(5):
            Path(self.p(str(i))).write_text('x')
        self.engine.max_results = 2
        r = self.engine.list_directory(str(self.root))
        self.assertEqual(len(r['entries']), 2)
        self.assertTrue(r['truncated'])

    def test_nonregular_no_block(self):
        os.mkfifo(self.p('fifo'))
        with self.assertRaises(FileToolError):
            self.engine.read_file(self.p('fifo'))

    def test_identity_is_not_tool_argument(self):
        with self.assertRaises(FileToolError):
            self.engine.dispatch('write_file', {'path': self.p('a'), 'content': 'x', 'session_id': SID}, SID)
        with self.assertRaises(FileToolError):
            self.engine.write_file(self.p('a'), 'x', session_id='')

    def test_info(self):
        self.write()
        r = self.engine.get_file_info(self.p('a.txt'))
        self.assertEqual(r['line_count'], 2)
        self.assertIn('created', r)
        if not r['creation_time_available']:
            self.assertIsNone(r['created'])

    def test_schema_requires_machine(self):
        for t in FILE_TOOLS:
            self.assertIn('machine', t['inputSchema']['required'])
            self.assertFalse(t['inputSchema']['additionalProperties'])

    def test_python39_syntax(self):
        for filename in ('file_tools.py', 'file_schema.py'):
            ast.parse(Path(filename).read_text(), feature_version=(3, 9))


if __name__ == '__main__':
    unittest.main()
