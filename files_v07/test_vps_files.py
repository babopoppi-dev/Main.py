import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


class VpsFiles(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.work = base / 'workspace'
        self.work.mkdir()
        cfg = base / 'config.json'
        cfg.write_text(json.dumps({'data_root': str(base), 'allowed_roots': [str(self.work)],
                                   'protected_paths': [], 'full_shell_capable': False}))
        previous = os.environ.get('CENTRAL_MCP_AGENT_CONFIG')
        os.environ['CENTRAL_MCP_AGENT_CONFIG'] = str(cfg)
        try:
            spec = importlib.util.spec_from_file_location('agent_test_v07', Path(__file__).with_name('agent.py'))
            self.agent = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.agent)
        finally:
            if previous is None:
                os.environ.pop('CENTRAL_MCP_AGENT_CONFIG')
            else:
                os.environ['CENTRAL_MCP_AGENT_CONFIG'] = previous
        self.rid = 0

    def tearDown(self):
        self.agent.FILE_ENGINE.close()
        self.tmp.cleanup()

    async def call(self, op, **args):
        self.rid += 1
        return await self.agent.dispatch(op, args, 'chatgpt:test-family', format(self.rid, '032x'))

    async def test_directory_edit_move_and_reverse_rollback(self):
        sub = str(self.work / 'new')
        ops = [await self.call('create_directory', path=sub)]
        src, dst = sub + '/a.txt', sub + '/b.txt'
        ops.append(await self.call('write_file', path=src, content='uno\ndue\n'))
        ops.append(await self.call('edit_block', file_path=src, old_string='due', new_string='tre'))
        ops.append(await self.call('move_file', source=src, destination=dst))
        self.assertEqual((await self.call('read_file', path=dst, offset=-1, length=1))['content'], 'tre\n')
        self.assertEqual((await self.call('read_file', path=dst, max_bytes=3))['content'], 'uno')
        for op in reversed(ops):
            await self.call('rollback_file', operation_id=op['operation_id'])
        self.assertFalse(Path(sub).exists())

    async def test_new_rollback_conflict_never_falls_back(self):
        p = self.work / 'a.txt'
        r = await self.call('write_file', path=str(p), content='created')
        p.write_text('changed externally')
        with self.assertRaises(Exception):
            await self.call('rollback_file', operation_id=r['operation_id'])
        self.assertEqual(p.read_text(), 'changed externally')

    async def test_requires_authenticated_caller_and_request(self):
        for caller, rid in [(None, 'a'*32), ('chatgpt:test-family', None)]:
            with self.assertRaises(ValueError):
                await self.agent.dispatch('write_file', {'path': str(self.work/'a'), 'content': 'bad'}, caller, rid)
        self.assertFalse((self.work/'a').exists())

    async def test_full_shell_stays_disabled(self):
        with self.assertRaises(PermissionError):
            await self.call('shell_exec', command='id')
        self.assertFalse(self.agent.hello_meta()['full_shell_capable'])


if __name__ == '__main__':
    unittest.main()
