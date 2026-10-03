"""Point E (project roots ro/rw) and point G level 1 (process list/stop)."""
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest
import uuid

from mac_agent import Dispatcher
from mac_projects import load_projects, forbidden_component
from mac_processes import ProcessTools, install_schema, PROCESS_NAMES


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.cfg = self.base / 'projects.json'

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, data, **kw):
        self.cfg.write_text(json.dumps(data))
        os.chmod(self.cfg, 0o644)
        return load_projects(self.cfg, owner=os.getuid(), **kw)

    def test_missing_file_means_no_projects(self):
        self.assertEqual(load_projects(self.base / 'none.json'), {'rw': [], 'ro': [], 'exclude': []})

    def test_rejections(self):
        bad = [{'version': 1, 'roots': [{'path': '/etc', 'mode': 'ro'}]},
               {'version': 1, 'roots': [{'path': '/Users/Shared/x', 'mode': 'ro'}]},
               {'version': 1, 'roots': [{'path': '/Users/babo/Bitcoin', 'mode': 'ro'}]},
               {'version': 1, 'roots': [{'path': '/Users/babo/x/../y', 'mode': 'ro'}]},
               {'version': 1, 'roots': [{'path': '/Users/nobody-xyz', 'mode': 'rw'}]},
               {'version': 1, 'roots': [{'path': '/Users/x', 'mode': 'admin'}]},
               {'version': 2, 'roots': []}]
        for data in bad:
            with self.assertRaises((ValueError, PermissionError), msg=data):
                self.load(data)
        os.chmod(self.cfg, 0o666)
        with self.assertRaises(PermissionError):
            load_projects(self.cfg, owner=os.getuid())

    def test_forbidden_component(self):
        self.assertTrue(forbidden_component('/r/a/La Marruca/x', '/r'))
        self.assertTrue(forbidden_component('/r/.ssh/id', '/r'))
        self.assertFalse(forbidden_component('/r/app/src', '/r'))


class Projects(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        b = Path(self.tmp.name)
        for d in ('work', 'state', 'rw', 'ro', 'ro/LiDAR', 'rw/bitcoin'):
            (b / d).mkdir(mode=0o700)
        (b / 'ro' / 'readme.txt').write_text('ciao\n')
        (b / 'ro' / 'LiDAR' / 'scan.txt').write_text('segreto\n')
        (b / 'rw' / 'bitcoin' / 'w.txt').write_text('no\n')
        self.b = b
        projects = {'rw': [str(b / 'rw')], 'ro': [str(b / 'ro')],
                    'exclude': [str(b / 'ro' / 'LiDAR'), str(b / 'rw' / 'bitcoin')]}
        self.d = Dispatcher(b / 'work', b / 'state', projects=projects)
        self.s = await self.call('work_session', {'action': 'open', 'label': 'p', 'minutes': 5})

    async def asyncTearDown(self):
        await self.d.close()
        self.tmp.cleanup()

    async def call(self, op, args, auth=False):
        args = dict(args)
        if auth:
            args.update(work_session_id=self.s['work_session_id'], work_session_token=self.s['work_session_token'])
        return await self.d.dispatch({'type': 'request', 'id': uuid.uuid4().hex, 'caller': 'claude:abcdef12',
                                      'op': op, 'args': args})

    async def test_read_only_root(self):
        p = str(self.b / 'ro' / 'readme.txt')
        self.assertEqual((await self.call('read_file', {'path': p}))['content'], 'ciao\n')
        listing = await self.call('list_directory', {'path': str(self.b / 'ro'), 'depth': 2})
        self.assertNotIn('LiDAR', json.dumps(listing))
        with self.assertRaises(Exception):
            await self.call('read_file', {'path': str(self.b / 'ro' / 'LiDAR' / 'scan.txt')})
        with self.assertRaises(PermissionError):
            await self.call('write_file', {'path': p, 'content': 'x'}, auth=True)
        with self.assertRaises(PermissionError):
            await self.call('move_file', {'source': p, 'destination': str(self.b / 'work' / 'r.txt')}, auth=True)
        self.assertEqual(Path(p).read_text(), 'ciao\n')

    async def test_read_write_root_needs_lock(self):
        p = str(self.b / 'rw' / 'nuovo.txt')
        with self.assertRaises(PermissionError):
            await self.call('write_file', {'path': p, 'content': 'x'}, auth=True)
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.b / 'rw'), 'minutes': 5}, auth=True)
        r = await self.call('write_file', {'path': p, 'content': 'x'}, auth=True)
        with self.assertRaises(Exception):
            await self.call('write_file', {'path': str(self.b / 'rw' / 'bitcoin' / 'w.txt'), 'content': 'x'}, auth=True)
        await self.call('rollback_file', {'operation_id': r['operation_id']}, auth=True)
        self.assertFalse(Path(p).exists())
        self.assertEqual((self.b / 'rw' / 'bitcoin' / 'w.txt').read_text(), 'no\n')

    async def test_search_in_read_only_root(self):
        r = await self.call('start_search', {'path': str(self.b / 'ro'), 'pattern': 'ciao'}, auth=True)
        await self.d.ro_search.jobs[r['search_id']]['task']
        r = await self.call('get_more_search_results', {'search_id': r['search_id']}, auth=True)
        self.assertEqual(r['total_results'], 1)
        r = await self.call('start_search', {'path': str(self.b / 'ro'), 'pattern': 'segreto'}, auth=True)
        await self.d.ro_search.jobs[r['search_id']]['task']
        self.assertEqual((await self.call('get_more_search_results', {'search_id': r['search_id']}, auth=True))['total_results'], 0)

    async def test_metadata_lists_roots(self):
        from mac_agent import metadata
        m = metadata(self.d)
        self.assertEqual(m['project_roots'], {'rw': [str(self.b / 'rw')], 'ro': [str(self.b / 'ro')]})
        self.assertTrue(PROCESS_NAMES <= set(m['capabilities']))


PS = """  501   10     1   1:00 S /Applications/Other.app
 5000  100     1   2:00 S /usr/bin/python3 mac_agent.py
 5000  101   100   0:30 S /usr/bin/python3 mac_watchdog.py
 5000  200   100   0:10 S /usr/bin/python3 mac_child.py
 5000  201   200   0:10 S /usr/bin/sandbox-exec -p x /bin/zsh -c make
 5000  202   201   0:05 R /usr/bin/make all
 5000  300     1   9:00 S /usr/sbin/distnoted agent
"""


class Processes(unittest.TestCase):
    def setUp(self):
        self.killed = []
        self.p = ProcessTools(uid=5000, agent_pid=100, ps=lambda: PS, kill=lambda pid, sig: self.killed.append((pid, sig)))

    def test_list_roles(self):
        roles = {x['pid']: x['role'] for x in self.p.list({200})['processes']}
        self.assertEqual(roles, {100: 'agent', 101: 'agent_helper', 200: 'shell_session',
                                 201: 'shell_process', 202: 'shell_process', 300: 'other'})

    def test_stop_only_descendants(self):
        self.assertEqual(self.p.stop({'pid': 202}, {200})['signal'], 'TERM')
        self.assertEqual(self.killed, [(202, signal.SIGTERM)])
        for pid in (100, 101, 200, 300, 10, 999):
            with self.assertRaises(PermissionError, msg=pid):
                self.p.stop({'pid': pid, 'signal': 'KILL'}, {200})
        with self.assertRaises(PermissionError):
            self.p.stop({'pid': 202}, set())
        with self.assertRaises(ValueError):
            self.p.stop({'pid': 202, 'signal': 'HUP'}, {200})
        self.assertEqual(len(self.killed), 1)

    def test_catalog(self):
        tools = install_schema(install_schema([{'name': 'x'}]))
        self.assertEqual([t['name'] for t in tools].count('process_stop'), 1)


class BadConfig(unittest.IsolatedAsyncioTestCase):
    async def test_bad_projects_file_does_not_stop_agent(self):
        import mac_agent
        with tempfile.TemporaryDirectory() as tmp:
            b = Path(tmp); (b / 'work').mkdir(mode=0o700); (b / 'state').mkdir(mode=0o700)
            cfg = b / 'projects.json'; cfg.write_text('{"version": 1, "roots": [{"path": "/etc", "mode": "rw"}]}')
            old = mac_agent.PROJECTS; mac_agent.PROJECTS = cfg
            try:
                d = mac_agent.Dispatcher(b / 'work', b / 'state')
            finally:
                mac_agent.PROJECTS = old
            self.assertEqual(d.projects['rw'], [])
            self.assertTrue(mac_agent.metadata(d)['projects_error'])
            await d.close()


class ProcessDispatch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        b = Path(self.tmp.name)
        (b / 'work').mkdir(mode=0o700); (b / 'state').mkdir(mode=0o700)
        self.d = Dispatcher(b / 'work', b / 'state', projects={'rw': [], 'ro': [], 'exclude': []})

    async def asyncTearDown(self):
        await self.d.close(); self.tmp.cleanup()

    async def test_list_without_session_stop_needs_shell_owner(self):
        call = lambda op, args: self.d.dispatch({'type': 'request', 'id': uuid.uuid4().hex,
                                                 'caller': 'claude:abcdef12', 'op': op, 'args': args})
        r = await call('process_list', {})
        self.assertTrue(any(p['role'] == 'agent' for p in r['processes']))
        with self.assertRaises(PermissionError):
            await call('process_stop', {'pid': 2})
        s = await call('work_session', {'action': 'open', 'label': 'x', 'minutes': 5})
        with self.assertRaises(PermissionError):
            await call('process_stop', {'pid': 2, 'work_session_id': s['work_session_id'],
                                        'work_session_token': s['work_session_token']})


if __name__ == '__main__':
    unittest.main()
