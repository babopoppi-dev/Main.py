"""VPS agent v0.12: sessions, locks, new file tools, shell and search ownership."""
import asyncio
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch
import uuid

HERE = Path(__file__).resolve().parent
# The copy under test must win over a deployed sibling directory.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE.parent) not in sys.path:
    sys.path.append(str(HERE.parent))
try:
    import isolated_shell  # noqa: F401  (deployed name on the VPS)
except ImportError:
    import shell_common
    sys.modules['isolated_shell'] = shell_common
sys.modules.setdefault('aiohttp', types.ModuleType('aiohttp'))

TMP = tempfile.TemporaryDirectory()
ROOT = Path(TMP.name)
WORKDIR = ROOT / 'workspace'; SCRATCH = ROOT / 'tmp'; DATA = ROOT / 'data'
for d in (WORKDIR, SCRATCH, DATA):
    d.mkdir(mode=0o700)
(DATA / 'protected').mkdir(mode=0o700)
CONFIG = ROOT / 'agent.json'
CONFIG.write_text(json.dumps({'data_root': str(DATA), 'token_file': str(ROOT / 'token'),
                              'allowed_roots': [str(WORKDIR), str(SCRATCH)],
                              'protected_paths': [str(DATA / 'protected')],
                              'full_shell_capable': False, 'shell_backend': 'bwrap-v08',
                              'tls_sha256': '00', 'gateway_url': 'wss://example.invalid'}))
os.environ['CENTRAL_MCP_AGENT_CONFIG'] = str(CONFIG)
agent = importlib.import_module('agent')


def tearDownModule():
    agent.UPLOADS.close(); agent.WORK.close(); agent.FILE_ENGINE.close(); TMP.cleanup()


class VpsAgent(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.a = await self.call('work_session', {'action': 'open', 'label': 'A', 'minutes': 10})
        self.b = await self.call('work_session', {'action': 'open', 'label': 'B', 'minutes': 10})

    async def asyncTearDown(self):
        await agent.SHELL.disable()
        for s in (self.a, self.b):
            try:
                await self.call('work_session', {'action': 'close'}, s)
            except PermissionError:
                pass
        if agent.WATCHDOG:
            agent.WATCHDOG.cancel()
            with __import__('contextlib').suppress(asyncio.CancelledError):
                await agent.WATCHDOG
            agent.WATCHDOG = None
        await agent.SEARCH.close()

    async def call(self, op, args, s=None, caller='claude:testclient'):
        if s:
            args = {**args, 'work_session_id': s['work_session_id'], 'work_session_token': s['work_session_token']}
        return await agent.dispatch(op, args, caller, uuid.uuid4().hex)

    async def lock(self, s, path=WORKDIR):
        return await self.call('work_lock', {'action': 'acquire', 'path': str(path), 'minutes': 10}, s)

    def folder(self):
        return WORKDIR / ('t' + uuid.uuid4().hex)

    async def test_writes_require_session_and_lock(self):
        f = self.folder()
        with self.assertRaises(PermissionError):
            await self.call('create_directory', {'path': str(f)})
        with self.assertRaises(PermissionError):
            await self.call('create_directory', {'path': str(f)}, self.a)
        await self.lock(self.a, f)
        r = await self.call('create_directory', {'path': str(f)}, self.a)
        with self.assertRaises(PermissionError):
            await self.call('write_file', {'path': str(f / 'x'), 'content': 'x'}, self.b)
        with self.assertRaises(PermissionError):
            await self.lock(self.b, f / 'x')
        await self.call('rollback_file', {'operation_id': r['operation_id']}, self.a)
        self.assertFalse(f.exists())

    async def test_reads_and_baseline_without_session(self):
        (WORKDIR / 'plain.txt').write_text('ciao')
        self.assertEqual((await self.call('read_file', {'path': str(WORKDIR / 'plain.txt')}))['content'], 'ciao')
        r = await self.call('read_binary', {'path': str(WORKDIR / 'plain.txt')})
        self.assertEqual(base64.b64decode(r['content_base64']), b'ciao')
        with patch.object(agent, 'run_baseline', new=AsyncMock(return_value={'exit_code': 0})):
            self.assertEqual((await self.call('shell_exec', {'command': 'uname -a'}))['exit_code'], 0)
        (WORKDIR / 'plain.txt').unlink()

    async def test_new_tools_delete_copy_upload_with_rollback(self):
        f = self.folder(); await self.lock(self.a, f)
        await self.call('create_directory', {'path': str(f / 'src')}, self.a)
        await self.call('write_file', {'path': str(f / 'src' / 'a.txt'), 'content': 'alpha'}, self.a)
        c = await self.call('copy_file', {'source': str(f / 'src'), 'destination': str(f / 'dst')}, self.a)
        self.assertEqual((f / 'dst' / 'a.txt').read_text(), 'alpha')
        d = await self.call('delete_path', {'path': str(f / 'src')}, self.a)
        self.assertFalse((f / 'src').exists())
        with self.assertRaises(PermissionError):
            await self.call('rollback_file', {'operation_id': d['operation_id']}, self.b)
        await self.call('rollback_file', {'operation_id': d['operation_id']}, self.a)
        self.assertEqual((f / 'src' / 'a.txt').read_text(), 'alpha')
        await self.call('rollback_file', {'operation_id': c['operation_id']}, self.a)
        data = os.urandom(5000)
        b = await self.call('upload_file', {'action': 'begin', 'path': str(f / 'bin'), 'size': len(data),
                                            'sha256': hashlib.sha256(data).hexdigest()}, self.a)
        with self.assertRaises(Exception):
            await self.call('upload_file', {'action': 'commit', 'upload_id': b['upload_id']}, self.b)
        await self.call('upload_file', {'action': 'chunk', 'upload_id': b['upload_id'], 'offset': 0,
                                        'data': base64.b64encode(data).decode()}, self.a)
        await self.call('upload_file', {'action': 'commit', 'upload_id': b['upload_id']}, self.a)
        self.assertEqual((f / 'bin').read_bytes(), data)

    async def test_scratch_root_also_locked(self):
        p = SCRATCH / ('s' + uuid.uuid4().hex)
        with self.assertRaises(PermissionError):
            await self.call('write_file', {'path': str(p), 'content': 'x'}, self.a)
        await self.lock(self.a, p)
        await self.call('write_file', {'path': str(p), 'content': 'x'}, self.a)
        p.unlink()

    async def test_protected_path_still_refused(self):
        with self.assertRaises(Exception):
            await self.call('work_lock', {'action': 'acquire', 'path': str(DATA / 'protected'), 'minutes': 5}, self.a)

    async def test_shell_needs_whole_workspace_lock_and_is_offline(self):
        with self.assertRaises(PermissionError):
            await self.call('enable_full_shell', {'minutes': 1}, self.a)
        await self.lock(self.a)
        with self.assertRaises(ValueError):
            await self.call('enable_full_shell', {'minutes': 1, 'network': 'github'}, self.a)
        with self.assertRaises(PermissionError):
            await self.call('enable_full_shell', {'minutes': 11}, self.a)
        with patch.object(agent.SHELL, 'enable', new=AsyncMock(return_value={'enabled': True})) as m:
            await self.call('enable_full_shell', {'minutes': 1}, self.a)
            m.assert_awaited_once_with('work:' + self.a['work_session_id'], 1)
        with self.assertRaises(PermissionError):
            await self.call('shell_exec', {'command': 'ls'}, self.b)

    async def test_foreign_disable_refused_and_close_revokes_shell(self):
        await self.lock(self.a); identity = 'work:' + self.a['work_session_id']
        agent.SHELL.owner = identity; agent.SHELL.until = __import__('time').monotonic() + 60
        with self.assertRaises(PermissionError):
            await self.call('disable_full_shell', {}, self.b)
        with self.assertRaises(PermissionError):
            lock_id = (await self.call('who_is_working', {}))['work_locks'][0]['lock_id']
            await self.call('work_lock', {'action': 'release', 'lock_id': lock_id}, self.a)
        await self.call('work_session', {'action': 'close'}, self.a)
        self.assertIsNone(agent.SHELL.owner)
        await self.lock(self.b)

    async def test_expired_session_reaps_shell_before_new_lock(self):
        await self.lock(self.a); identity = 'work:' + self.a['work_session_id']
        agent.SHELL.owner = identity; agent.SHELL.until = __import__('time').monotonic() + 60
        with agent.WORK.transaction() as d:
            d['sessions'][self.a['work_session_id']]['deadline'] = 0
        await self.lock(self.b)
        self.assertIsNone(agent.SHELL.owner)

    async def test_search_private_to_session(self):
        f = self.folder(); await self.lock(self.a, f)
        await self.call('create_directory', {'path': str(f)}, self.a)
        await self.call('write_file', {'path': str(f / 'n.txt'), 'content': 'needle_vps'}, self.a)
        r = await self.call('start_search', {'path': str(f), 'pattern': 'needle_vps'}, self.a)
        await agent.SEARCH.jobs[r['search_id']]['task']
        with self.assertRaises(PermissionError):
            await self.call('get_more_search_results', {'search_id': r['search_id']}, self.b)
        self.assertEqual((await self.call('get_more_search_results', {'search_id': r['search_id']}, self.a))['total_results'], 1)
        with self.assertRaises(PermissionError):
            await self.call('start_search', {'path': str(f), 'pattern': 'x'})

    async def test_who_is_working_and_meta_without_tokens(self):
        await self.lock(self.a)
        state = await self.call('who_is_working', {})
        self.assertEqual(len(state['work_locks']), 1)
        self.assertNotIn(self.a['work_session_token'], json.dumps(state))
        meta = agent.hello_meta()
        self.assertEqual(meta['coordination_version'], '0.11.0')
        for n in ('work_session', 'work_lock', 'delete_path', 'copy_file', 'read_binary', 'upload_file'):
            self.assertIn(n, meta['capabilities'])

    async def test_session_and_lock_operations_audited_with_session_id(self):
        await self.lock(self.a)
        recent = (await self.call('who_is_working', {}))['recent_work_operations']
        ops = [(x['operation'], x['work_session_id']) for x in recent if 'request_id' in x]
        self.assertIn(('work_lock', self.a['work_session_id']), ops)
        self.assertIn(('work_session', self.b['work_session_id']), ops)

    async def test_legacy_rollback_requires_lock(self):
        op = uuid.uuid4().hex; target = WORKDIR / ('legacy' + op)
        (agent.OPS_ROOT / op).mkdir(mode=0o700)
        (agent.OPS_ROOT / op / 'meta.json').write_text(json.dumps({'operation_id': op, 'target': str(target),
                                                                   'existed': False, 'mode': None, 'rolled_back': False}))
        target.write_text('created by old agent')
        with self.assertRaises(PermissionError):
            await self.call('rollback_file', {'operation_id': op}, self.a)
        await self.lock(self.a, target)
        await self.call('rollback_file', {'operation_id': op}, self.a)
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
