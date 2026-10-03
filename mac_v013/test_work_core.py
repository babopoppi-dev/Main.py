"""Necessary isolation, persistence and dispatcher regression checks."""
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
            m.assert_awaited_once_with('work:'+self.a['work_session_id'],1)
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
    async def test_work_operations_audited_with_session_id(self):
        await self.lock(self.a)
        with self.assertRaises(PermissionError):await self.lock(self.b)
        state=await self.call('who_is_working',{})
        ops=[(x['operation'],x['work_session_id'],x.get('ok')) for x in state['recent_work_operations'] if x['operation']=='work_lock']
        self.assertIn(('work_lock',self.a['work_session_id'],True),ops)
        self.assertIn(('work_lock',self.b['work_session_id'],False),ops)
        self.assertFalse([x for x in state['recent_work_operations'] if x['operation'] in ('work_lock','work_session') and x['work_session_id'] is None])
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
