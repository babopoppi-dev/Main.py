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
            spec = importlib.util.spec_from_file_location('agent_test_v08', Path(__file__).with_name('agent.py'))
            self.agent = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.agent)
        finally:
            if previous is None:
                os.environ.pop('CENTRAL_MCP_AGENT_CONFIG')
            else:
                os.environ['CENTRAL_MCP_AGENT_CONFIG'] = previous
        self.rid = 0

    async def asyncTearDown(self):
        if self.agent.WATCHDOG:
            self.agent.WATCHDOG.cancel()
        await self.agent.SEARCH.close()
        await self.agent.SHELL.disable()
        self.agent.FILE_ENGINE.close()
        self.tmp.cleanup()

    async def raw(self, op, args, caller='chatgpt:test-family'):
        self.rid += 1
        return await self.agent.dispatch(op, args, caller, format(self.rid, '032x'))

    async def session(self, lock=True, label='test'):
        s = await self.raw('work_session', {'action': 'open', 'label': label, 'minutes': 10})
        if lock:
            await self.raw('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10,
                                         'work_session_id': s['work_session_id'], 'work_session_token': s['work_session_token']})
        return s

    async def call(self, op, _s=None, **args):
        if op not in ('who_is_working', 'read_file', 'list_directory', 'get_file_info', 'read_multiple_files'):
            if _s is None:
                if getattr(self, 's', None) is None:
                    self.s = await self.session()
                _s = self.s
            args.update(work_session_id=_s['work_session_id'], work_session_token=_s['work_session_token'])
        return await self.raw(op, args)

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
            with self.assertRaises((ValueError, PermissionError)):
                await self.agent.dispatch('write_file', {'path': str(self.work/'a'), 'content': 'bad'}, caller, rid)
        self.assertFalse((self.work/'a').exists())

    async def test_full_shell_stays_disabled(self):
        with self.assertRaises(PermissionError):
            await self.call('shell_exec', command='id')
        with self.assertRaises(PermissionError):
            await self.raw('shell_exec', {'command': 'id'})
        self.assertFalse(self.agent.hello_meta()['full_shell_capable'])
        self.assertEqual((await self.raw('shell_exec', {'command': 'uname -a'}))['exit_code'], 0)

    async def test_writes_need_session_and_covering_lock(self):
        with self.assertRaises(PermissionError):
            await self.raw('write_file', {'path': str(self.work / 'a'), 'content': 'x'})
        b = await self.session(lock=False, label='other')
        with self.assertRaises(PermissionError):
            await self.call('write_file', b, path=str(self.work / 'a'), content='x')
        r = await self.call('write_file', path=str(self.work / 'a'), content='x')
        with self.assertRaises(PermissionError):
            await self.raw('work_lock', {'action': 'acquire', 'path': str(self.work / 'sub'), 'minutes': 5,
                                         'work_session_id': b['work_session_id'], 'work_session_token': b['work_session_token']})
        with self.assertRaises(PermissionError):
            await self.call('rollback_file', b, operation_id=r['operation_id'])
        with self.assertRaises(PermissionError):
            await self.raw('work_session', {'action': 'close', 'work_session_id': b['work_session_id'],
                                            'work_session_token': self.s['work_session_token']})
        await self.call('rollback_file', operation_id=r['operation_id'])
        self.assertFalse((self.work / 'a').exists())

    async def test_audit_names_session_and_close_releases(self):
        await self.call('write_file', path=str(self.work / 'a'), content='x')
        state = await self.call('who_is_working')
        sid = self.s['work_session_id']
        ops = {(x['operation'], x['work_session_id']) for x in state['recent_work_operations']}
        self.assertTrue({('work_session', sid), ('work_lock', sid), ('write_file', sid)} <= ops)
        self.assertNotIn(self.s['work_session_token'], str(state))
        self.assertEqual(len(state['work_locks']), 1)
        await self.call('work_session', action='close')
        state = await self.call('who_is_working')
        self.assertFalse(state['work_sessions'] or state['work_locks'])
        self.assertEqual(self.agent.hello_meta()['coordination_version'], '0.11.0')

    async def test_legacy_rollback_needs_lock(self):
        rid = 'b' * 32
        d = self.agent.OPS_ROOT / rid
        d.mkdir(parents=True)
        (d / 'meta.json').write_text(json.dumps({'target': str(self.work / 'legacy'), 'existed': False}))
        b = await self.session(lock=False, label='other')
        with self.assertRaises(PermissionError):
            await self.call('rollback_file', b, operation_id=rid)


    async def test_search_lifecycle_and_lock(self):
        (self.work/'a.txt').write_text('needle')
        r=await self.call('start_search',path=str(self.work),pattern='needle')
        self.assertEqual((await self.call('who_is_working'))['active_locks'][0]['kind'],'search')
        with self.assertRaises(PermissionError):await self.call('write_file',path=str(self.work/'b'),content='x')
        await self.agent.SEARCH.jobs[r['search_id']]['task']
        r=await self.call('get_more_search_results',search_id=r['search_id'])
        self.assertEqual(r['total_results'],1)
        self.assertFalse((await self.call('who_is_working'))['active_locks'])
    async def test_search_identity_is_not_supplied_by_arguments(self):
        with self.assertRaises(ValueError):await self.call('start_search',path=str(self.work),pattern='needle',caller='fake:caller')
    async def test_search_metadata(self):
        m=self.agent.hello_meta()
        self.assertEqual(m['search_version'],'0.10.1')
        self.assertTrue({'start_search','get_more_search_results','stop_search'}<=set(m['capabilities']))

if __name__ == '__main__':
    unittest.main()
