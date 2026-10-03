import asyncio
import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from workspace_runtime import WorkspaceRuntime
from adapter import dispatch

class Coordination:
    def __init__(self): self.active={}; self.history=[]
    def acquire_lock(self, caller, path, ttl, kind):
        if path in self.active: raise CoordinationConflict('lock held by another client')
        self.active[path]=caller; self.history.append(caller)
        return {'lock_id':path}
    def release_lock(self, key, caller):
        assert self.active[key]==caller
        del self.active[key]

class Backend:
    async def call(self, name, args):
        if name=='who_is_working': return {'active_locks':[]}
        return {'content':'legacy read'}

class CoordinationConflict(Exception):pass

class Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/'work';self.root.mkdir()
        self.coord=Coordination()
        self.r=WorkspaceRuntime(self.root,Path(self.tmp.name)/'state',self.coord)
        self.count=0
    def tearDown(self):
        self.r.close();self.tmp.cleanup()
    async def call(self, op, **args):
        self.count+=1
        return await dispatch(Backend(),{'type':'request','id':format(self.count,'032x'),
            'caller':'chatgpt:family123','op':op,'args':args},self.r)
    async def test_write_overwrite_read_two_rollbacks(self):
        p=str(self.root/'a')
        a=await self.call('write_file',path=p,content='A')
        b=await self.call('write_file',path=p,content='B')
        self.assertEqual((await self.call('read_file',path=p))['content'],'B')
        await self.call('rollback_file',operation_id=b['operation_id'])
        self.assertEqual((await self.call('read_file',path=p))['content'],'A')
        await self.call('rollback_file',operation_id=a['operation_id'])
        self.assertFalse(Path(p).exists());self.assertFalse(self.coord.active)
    async def test_conflict_preserves_external_edit(self):
        p=str(self.root/'a'); a=await self.call('write_file',path=p,content='A')
        Path(p).write_text('external')
        with self.assertRaises(Exception): await self.call('rollback_file',operation_id=a['operation_id'])
        self.assertEqual(Path(p).read_text(),'external')
    async def test_external_lock_blocks_write(self):
        p=str(self.root/'a');self.coord.active[p]='claude:another'
        with self.assertRaises(PermissionError): await self.call('write_file',path=p,content='A')
        self.assertFalse(Path(p).exists())
    async def test_distinct_request_locks_same_oauth_family(self):
        await self.call('write_file',path=str(self.root/'a'),content='A')
        await self.call('write_file',path=str(self.root/'b'),content='B')
        self.assertNotEqual(*self.coord.history)
    async def test_write_outside_and_symlink_denied(self):
        p=Path(self.tmp.name)/'outside';p.write_text('safe');(self.root/'link').symlink_to(p)
        for target in [p,self.root/'link']:
            with self.assertRaises(Exception):await self.call('write_file',path=str(target),content='unsafe')
        self.assertEqual(p.read_text(),'safe')
    async def test_identity_required(self):
        for caller in [None,'bad\ncaller']:
            with self.assertRaises(ValueError):
                await dispatch(Backend(),{'type':'request','id':'a'*32,'caller':caller,'op':'who_is_working','args':{}},self.r)
    async def test_arbitrary_shell_and_full_shell_rejected(self):
        with patch('workspace_runtime.asyncio.create_subprocess_exec') as run:
            for command in ['sw_vers; id','sudo id','xcodebuild -version\nid']:
                with self.assertRaises(PermissionError):await self.call('shell_exec',command=command)
            run.assert_not_called()
        for op in ['enable_full_shell','shell_session']:
            with self.assertRaises(PermissionError):await self.call(op)
        self.assertFalse((await self.call('disable_full_shell'))['enabled'])
    async def test_fixed_argv(self):
        class Proc:
            returncode=0
            async def communicate(self):return b'Xcode test',None
        async def run(*args,**kw):
            self.assertEqual(args,('/usr/bin/xcodebuild','-version'));return Proc()
        with patch('workspace_runtime.asyncio.create_subprocess_exec',run):
            self.assertEqual((await self.call('shell_exec',command='xcodebuild -version'))['exit_code'],0)
    async def test_legacy_reads_retained(self):
        self.assertEqual((await self.call('read_file',path='/legacy/file',max_bytes=6))['content'],'legacy')

if __name__=='__main__':unittest.main()
