import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
import uuid
from mac_agent import Dispatcher, end_connection, status_output, baseline_argv
from file_tools import FileToolError

class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.work=self.root/'work';self.state=self.root/'state'
        self.work.mkdir(mode=0o700);self.state.mkdir(mode=0o700)
        self.d=Dispatcher(self.work,self.state)
    async def asyncTearDown(self):
        await self.d.close();self.tmp.cleanup()
    async def call(self,op,args,caller='test:client'):
        return await self.d.dispatch({'type':'request','id':uuid.uuid4().hex,'caller':caller,'op':op,'args':args})
    async def test_file_write_read_and_rollback(self):
        p=str(self.work/'hello.txt')
        r=await self.call('write_file',{'path':p,'content':'test'})
        self.assertEqual((await self.call('read_file',{'path':p}))['content'],'test')
        self.assertTrue((await self.call('rollback_file',{'operation_id':r['operation_id']}))['rolled_back'])
        self.assertFalse(Path(p).exists())
    async def test_log_reader_cannot_write_or_move(self):
        p=self.state/'shell-logs'/('a'*32+'.log');p.write_text('shell output');p.chmod(0o600)
        self.assertEqual((await self.call('read_file',{'path':str(p)}))['content'],'shell output')
        with self.assertRaises(PermissionError):await self.call('write_file',{'path':str(p),'content':'bad'})
        with self.assertRaises(FileToolError):await self.call('move_file',{'source':str(p),'destination':str(self.work/'log.txt')})
    async def test_private_state_cannot_be_read(self):
        p=self.state/'agent.token';p.write_text('TEST_SENTINEL_ONLY')
        with self.assertRaises(FileToolError):await self.call('read_file',{'path':str(p)})
    async def test_default_shell_is_disabled(self):
        self.assertFalse((await self.call('who_is_working',{}))['shell_enabled'])
        with self.assertRaises(PermissionError):self.d.shell.allowed('test:client')
    async def test_untrusted_identity_rejected(self):
        with self.assertRaises(PermissionError):await self.call('who_is_working',{},caller='x')
    async def test_extra_shell_arguments_rejected(self):
        with self.assertRaises(ValueError):await self.call('shell_exec',{'command':'id -u','user':'root'})
    async def test_caller_passed_to_shell(self):
        with patch.object(self.d.shell,'enable',new=AsyncMock(return_value={'enabled':True})) as enable:
            await self.call('enable_full_shell',{'minutes':3})
            enable.assert_awaited_once_with('test:client',3)
    async def test_audit_records_request_but_not_command_in_recent_view(self):
        with patch.object(self.d.shell,'execute',new=AsyncMock(return_value={})):
            await self.call('shell_exec',{'command':'echo test'})
        row=self.d.recent[-1]
        self.assertEqual(row['caller'],'test:client');self.assertNotIn('command',row)
    async def test_log_quota_does_not_delete_existing_logs(self):
        p=self.state/'shell-logs'
        for n in range(128):(p/(format(n,'032x')+'.log')).write_text('saved')
        with self.assertRaises(PermissionError):self.d.shell.check_log_storage()
        self.assertEqual(len(list(p.iterdir())),128)
    async def test_log_symlink_blocks_new_shell(self):
        p=self.state/'shell-logs'/('a'*32+'.log');p.symlink_to(self.work/'absent')
        with self.assertRaises(PermissionError):self.d.shell.check_log_storage()
    async def test_failed_heartbeat_still_revokes_shell(self):
        async def failed():raise ConnectionError('connection closed')
        task=asyncio.create_task(failed())
        await asyncio.sleep(0)
        with patch.object(self.d.shell,'disable',new=AsyncMock()) as disable,patch('mac_agent.connected_receipt') as receipt:
            await end_connection(task,self.d)
            disable.assert_awaited_once_with()
            receipt.assert_called_once_with(False)
    async def test_timeout_preserves_diagnostic_output_and_reaps_process(self):
        import types,signal
        done=asyncio.Event()
        async def communicate():
            await done.wait();return b'partial diagnostic',None
        proc=types.SimpleNamespace(pid=200,returncode=-9,communicate=communicate)
        with patch('mac_agent.os.killpg',side_effect=lambda pid,sig:done.set()) as kill:
            result=await status_output(proc,timeout=.01)
            self.assertTrue(result['timed_out']);self.assertEqual(result['output'],'partial diagnostic')
            kill.assert_called_once_with(200,signal.SIGKILL)
    async def test_baseline_status_uses_sandbox_and_fixed_argv(self):
        with patch('mac_agent.profile',return_value='(deny default)\n'):
            argv=baseline_argv('sw_vers',self.work)
            self.assertEqual(argv,['/usr/bin/sandbox-exec','-p','(deny default)\n','/usr/bin/sw_vers'])

    async def test_search_lifecycle_and_audit(self):
        (self.work/'a.txt').write_text('needle')
        r=await self.call('start_search',{'path':str(self.work),'pattern':'needle'})
        self.assertEqual((await self.call('who_is_working',{}))['active_locks'][0]['kind'],'search')
        with self.assertRaises(PermissionError):await self.call('write_file',{'path':str(self.work/'b'),'content':'x'})
        await self.d.search.jobs[r['search_id']]['task']
        r=await self.call('get_more_search_results',{'search_id':r['search_id']})
        self.assertEqual(r['total_results'],1)
        self.assertEqual(self.d.recent[-1]['operation'],'get_more_search_results')
        self.assertFalse((await self.call('who_is_working',{}))['active_locks'])
    async def test_search_does_not_access_shell_logs(self):
        with self.assertRaises(FileToolError):await self.call('start_search',{'path':str(self.state/'shell-logs'),'pattern':'test'})
    async def test_disconnect_revokes_search(self):
        r=await self.call('start_search',{'path':str(self.work),'pattern':'test'})
        async def beat():await asyncio.sleep(100)
        task=asyncio.create_task(beat())
        with patch('mac_agent.connected_receipt'):
            await end_connection(task,self.d)
        self.assertFalse(self.d.search.jobs)

if __name__=='__main__':unittest.main()
