import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mac_mio_agent import Dispatcher


class AgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'work'
        self.root.mkdir()
        self.d = Dispatcher(self.root, Path(self.tmp.name) / 'state')

    def tearDown(self):
        self.d.engine.close()
        self.tmp.cleanup()

    async def call(self, op, **args):
        return await self.d.dispatch({'type':'request', 'caller':'chatgpt:session123', 'op':op, 'args':args})

    async def test_roundtrip_and_rollback(self):
        path = str(self.root / 'probe.txt')
        a = await self.call('write_file', path=path, content='prima\n')
        b = await self.call('write_file', path=path, content='dopo\n')
        self.assertEqual((await self.call('read_file', path=path, max_bytes=2))['content'], 'do')
        await self.call('rollback_file', operation_id=b['operation_id'])
        self.assertEqual((await self.call('read_file', path=path))['content'], 'prima\n')
        await self.call('rollback_file', operation_id=a['operation_id'])
        self.assertFalse(Path(path).exists())

    async def test_missing_identity_fails(self):
        with self.assertRaises(ValueError):
            await self.d.dispatch({'type':'request','op':'write_file','args':{'path':str(self.root/'x'),'content':'x'}})

    async def test_outside_and_symlink_denied(self):
        outside=Path(self.tmp.name)/'secret'
        outside.write_text('fixture')
        (self.root/'link').symlink_to(outside)
        for path in (outside, self.root/'link'):
            with self.assertRaises(Exception):
                await self.call('read_file',path=str(path),max_bytes=32)

    async def test_no_arbitrary_shell_or_sessions(self):
        with patch('mac_mio_agent.asyncio.create_subprocess_exec') as runner:
            for command in ('sudo id','sw_vers; id','/usr/bin/sw_vers\nid','uname -a'):
                with self.assertRaises(PermissionError):
                    await self.call('shell_exec',command=command)
            runner.assert_not_called()
        for op in ('shell_session','enable_full_shell'):
            with self.assertRaises(PermissionError):
                await self.call(op)
        self.assertEqual(await self.call('disable_full_shell'),{'enabled':False})

    async def test_rollback_conflict_preserves_external_edit(self):
        path=str(self.root/'probe.txt')
        op=await self.call('write_file',path=path,content='agent')
        Path(path).write_text('external')
        with self.assertRaises(Exception):
            await self.call('rollback_file',operation_id=op['operation_id'])
        self.assertEqual(Path(path).read_text(),'external')

    async def test_only_fixed_status_program(self):
        class Proc:
            returncode=0
            async def communicate(self): return b'ProductVersion: 12.7.6\n', None
        async def fake(*args,**kwargs):
            self.assertEqual(args,('/usr/bin/sw_vers',))
            self.assertNotIn('shell',kwargs)
            return Proc()
        with patch('mac_mio_agent.asyncio.create_subprocess_exec',fake):
            self.assertEqual((await self.call('shell_exec',command='sw_vers'))['exit_code'],0)


if __name__=='__main__': unittest.main()
