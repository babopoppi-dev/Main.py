import asyncio
import tempfile
from pathlib import Path
import unittest
from file_tools import FileTools
from isolated_shell import IsolatedShell


class Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.work, self.other = base/'work', base/'other'
        self.work.mkdir(); self.other.mkdir()
        self.files = FileTools([str(self.work),str(self.other)], str(base/'state'))
        self.shell = IsolatedShell(self.files, str(self.work), capable=True)

    async def asyncTearDown(self):
        await self.shell.disable()
        self.files.close(); self.tmp.cleanup()

    async def test_default_closed_and_ownership(self):
        with self.assertRaises(PermissionError):
            await self.shell.start('client:first','id')
        await self.shell.enable('client:first',1)
        with self.assertRaises(PermissionError):
            await self.shell.enable('client:second',1)
        await self.shell.disable()
        with self.assertRaises(PermissionError):
            self.shell.allowed('client:first')

    async def test_expired_authorization_cannot_send(self):
        await self.shell.enable('client:first',1)
        self.shell.until = 0
        with self.assertRaises(PermissionError):
            self.shell.allowed('client:first')

    async def test_workspace_cannot_follow_symlink_or_other_root(self):
        (self.work/'escape').symlink_to(self.other)
        with self.assertRaises(OSError): self.shell.cwd(str(self.work/'escape'))
        with self.assertRaises(PermissionError): self.shell.cwd(str(self.other))

    async def test_invalid_durations_and_identity(self):
        for minutes in (True,0,241,1.2,'1'):
            with self.assertRaises(ValueError): await self.shell.enable('client:first',minutes)
        with self.assertRaises(PermissionError): await self.shell.enable('',1)

    async def test_result_not_readable_to_another_authorization(self):
        sid='a'*32
        self.shell.jobs[sid]={'owner':'client:first'}
        with self.assertRaises(PermissionError): self.shell.lookup('client:second',sid)
        self.shell.jobs.clear()


if __name__ == '__main__': unittest.main()
