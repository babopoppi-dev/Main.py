"""Point E (p5): real project roots, ro with a nested rw root, for file tools and the shell."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from mac_agent import Dispatcher, metadata
from mac_projects import load_projects, validate, forbidden_component, EMPTY
import mac_policy

DEV, MCP = '/Users/babo/Developer', '/Users/babo/Developer/MCPAndrea'


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.cfg = self.base / 'projects.json'

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, roots, exclude=()):
        return validate({'version': 1, 'roots': roots, 'exclude': list(exclude)}, scan=lambda p: [], check_fs=False)

    def test_missing_file_means_no_projects(self):
        self.assertEqual(load_projects(self.base / 'none.json'), EMPTY)

    def test_andrea_layout_rw_nested_in_ro(self):
        out = self.check([{'path': DEV, 'mode': 'ro'}, {'path': MCP, 'mode': 'rw'}])
        self.assertEqual((out['ro'], out['rw']), ([DEV], [MCP]))
        self.assertEqual(out['ro_exclude'], [MCP])
        self.assertEqual(out['exclude'], [])

    def test_other_overlaps_rejected(self):
        for roots in ([{'path': DEV, 'mode': 'rw'}, {'path': MCP, 'mode': 'ro'}],
                      [{'path': DEV, 'mode': 'ro'}, {'path': MCP, 'mode': 'ro'}],
                      [{'path': DEV, 'mode': 'rw'}, {'path': MCP, 'mode': 'rw'}],
                      [{'path': DEV, 'mode': 'ro'}, {'path': DEV, 'mode': 'rw'}],
                      [{'path': DEV, 'mode': 'ro'}, {'path': '/Users/babo/developer', 'mode': 'rw'}]):
            with self.assertRaises(ValueError, msg=roots):
                self.check(roots)

    def test_rejections(self):
        bad = [[{'path': '/etc', 'mode': 'ro'}],
               [{'path': '/Users/Shared/x', 'mode': 'ro'}],
               [{'path': '/Users/babo', 'mode': 'ro'}],
               [{'path': '/Users/babo/Bitcoin', 'mode': 'ro'}],
               [{'path': '/Users/babo/Dev/LaMarrucaApp', 'mode': 'rw'}],
               [{'path': '/Users/babo/x/../y', 'mode': 'ro'}],
               [{'path': '/Users/babo/a b', 'mode': 'ro'}],
               [{'path': '/Users/babo/Library', 'mode': 'ro'}],
               [{'path': DEV, 'mode': 'admin'}]]
        for roots in bad:
            with self.assertRaises((ValueError, PermissionError), msg=roots):
                self.check(roots)
        with self.assertRaises(ValueError):
            validate({'version': 2, 'roots': []}, check_fs=False)
        with self.assertRaises(ValueError):
            self.check([{'path': DEV, 'mode': 'ro'}], exclude=['/Users/babo/elsewhere'])

    def test_unsafe_file_refused(self):
        self.cfg.write_text(json.dumps({'version': 1, 'roots': []}))
        os.chmod(self.cfg, 0o666)
        with self.assertRaises(PermissionError):
            load_projects(self.cfg, owner=os.getuid())
        os.chmod(self.cfg, 0o644)
        with self.assertRaises(PermissionError):
            load_projects(self.cfg, owner=os.getuid() + 1)

    def test_forbidden_component(self):
        self.assertTrue(forbidden_component('/r/a/La Marruca/x', '/r'))
        self.assertTrue(forbidden_component('/r/.ssh/id', '/r'))
        self.assertTrue(forbidden_component('/r/MyBitcoinWallet', '/r'))
        self.assertFalse(forbidden_component('/r/app/src', '/r'))


class Projects(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        b = Path(self.tmp.name)
        for d in ('work', 'state', 'dev', 'dev/mcp', 'dev/LiDAR', 'dev/mcp/bitcoin', 'dev/app'):
            (b / d).mkdir(mode=0o700)
        (b / 'dev' / 'app' / 'readme.txt').write_text('ciao\n')
        (b / 'dev' / 'LiDAR' / 'scan.txt').write_text('segreto\n')
        (b / 'dev' / 'mcp' / 'bitcoin' / 'w.txt').write_text('no\n')
        self.b = b
        ex = [str(b / 'dev' / 'LiDAR'), str(b / 'dev' / 'mcp' / 'bitcoin')]
        self.projects = {'rw': [str(b / 'dev' / 'mcp')], 'ro': [str(b / 'dev')], 'exclude': ex,
                         'ro_exclude': ex + [str(b / 'dev' / 'mcp')]}
        self.d = Dispatcher(b / 'work', b / 'state', projects=self.projects)
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

    async def lock(self, path):
        return await self.call('work_lock', {'action': 'acquire', 'path': str(path), 'minutes': 5}, auth=True)

    async def test_read_only_root(self):
        p = str(self.b / 'dev' / 'app' / 'readme.txt')
        self.assertEqual((await self.call('read_file', {'path': p}))['content'], 'ciao\n')
        self.assertEqual((await self.call('read_binary', {'path': p}))['size'], 5)
        listing = await self.call('list_directory', {'path': str(self.b / 'dev'), 'depth': 2})
        self.assertNotIn('LiDAR', json.dumps(listing))
        with self.assertRaises(Exception):
            await self.call('read_file', {'path': str(self.b / 'dev' / 'LiDAR' / 'scan.txt')})
        with self.assertRaises(Exception):
            await self.lock(self.b / 'dev' / 'app')
        with self.assertRaises(PermissionError):
            await self.call('write_file', {'path': p, 'content': 'x'}, auth=True)
        with self.assertRaises(PermissionError):
            await self.call('move_file', {'source': p, 'destination': str(self.b / 'work' / 'r.txt')}, auth=True)
        self.assertEqual(Path(p).read_text(), 'ciao\n')

    async def test_nested_read_write_root_needs_lock_and_has_rollback(self):
        p = str(self.b / 'dev' / 'mcp' / 'nuovo.txt')
        with self.assertRaises(PermissionError):
            await self.call('write_file', {'path': p, 'content': 'x'}, auth=True)
        await self.lock(self.b / 'dev' / 'mcp')
        r = await self.call('write_file', {'path': p, 'content': 'x'}, auth=True)
        self.assertEqual((await self.call('read_file', {'path': p}))['content'], 'x')
        with self.assertRaises(Exception):
            await self.call('write_file', {'path': str(self.b / 'dev' / 'mcp' / 'bitcoin' / 'w.txt'), 'content': 'x'}, auth=True)
        with self.assertRaises(PermissionError):
            await self.call('copy_file', {'source': str(self.b / 'dev' / 'app' / 'readme.txt'), 'destination': p + '2'}, auth=True)
        await self.call('rollback_file', {'operation_id': r['operation_id']}, auth=True)
        self.assertFalse(Path(p).exists())
        self.assertEqual((self.b / 'dev' / 'mcp' / 'bitcoin' / 'w.txt').read_text(), 'no\n')

    async def test_search_in_read_only_root(self):
        r = await self.call('start_search', {'path': str(self.b / 'dev'), 'pattern': 'ciao'}, auth=True)
        await self.d.ro_search.jobs[r['search_id']]['task']
        self.assertEqual((await self.call('get_more_search_results', {'search_id': r['search_id']}, auth=True))['total_results'], 1)
        r = await self.call('start_search', {'path': str(self.b / 'dev'), 'pattern': 'segreto'}, auth=True)
        await self.d.ro_search.jobs[r['search_id']]['task']
        self.assertEqual((await self.call('get_more_search_results', {'search_id': r['search_id']}, auth=True))['total_results'], 0)
        state = await self.call('who_is_working', {})
        self.assertIsInstance(state['active_locks'], list)

    async def test_metadata_lists_roots(self):
        m = metadata(self.d)
        self.assertEqual(m['project_roots'], {'rw': [str(self.b / 'dev' / 'mcp')], 'ro': [str(self.b / 'dev')]})
        self.assertIn(str(self.b / 'dev'), m['allowed_roots'])
        self.assertIsNone(m['projects_error'])

    async def test_shell_cwd_and_environment(self):
        sh = self.d.shell
        self.assertEqual(sh.cwd(str(self.b / 'dev' / 'app')), str(self.b / 'dev' / 'app'))
        self.assertEqual(sh.cwd(str(self.b / 'dev' / 'mcp')), str(self.b / 'dev' / 'mcp'))
        for bad in (self.b / 'dev' / 'LiDAR', self.b / 'dev' / 'mcp' / 'bitcoin', self.b / 'state', Path('/etc')):
            with self.assertRaises(Exception, msg=bad):
                sh.cwd(str(bad))
        env = json.loads(sh.child_env()['MCP_PROJECTS'])
        self.assertEqual(env, {'rw': self.projects['rw'], 'ro': self.projects['ro'], 'exclude': self.projects['exclude']})

    async def test_shell_needs_locks_on_workspace_and_read_write_roots(self):
        ident = 'work:' + self.s['work_session_id']
        await self.lock(self.b / 'work')
        with self.assertRaises(PermissionError):
            self.d.shell_remaining(ident)
        await self.lock(self.b / 'dev' / 'mcp')
        self.assertGreater(self.d.shell_remaining(ident), 0)

    async def test_bad_configuration_fails_closed(self):
        with patch('mac_agent.load_projects', side_effect=ValueError('boom')), patch('mac_agent.WORK', self.b / 'work'):
            d = Dispatcher(self.b / 'work', self.b / 'state2')
        try:
            self.assertEqual(d.projects['rw'] + d.projects['ro'], [])
            self.assertIn('boom', d.projects_error)
            self.assertNotIn('MCP_PROJECTS', d.shell.child_env())
        finally:
            await d.close()


class ShellProfile(unittest.TestCase):
    def setUp(self):
        self.patch = patch('mac_policy.safe_executables', return_value=['/bin/bash'])
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_project_rules(self):
        text = mac_policy.profile('/Users/Shared/X/workspace', '/dev/ttys003', None,
                                  {'rw': [MCP], 'ro': [DEV], 'exclude': [DEV + '/old']})
        lines = text.splitlines()
        self.assertIn('(allow file-read* (subpath "%s"))' % DEV, lines)
        self.assertIn('(allow file-write* (subpath "%s"))' % MCP, lines)
        self.assertIn('(allow process-exec* (subpath "%s"))' % MCP, lines)
        self.assertNotIn('(allow file-write* (subpath "%s"))' % DEV, lines)
        deny = [l for l in lines if l.startswith('(deny file-read* file-write* process-exec*')]
        self.assertEqual(len(deny), 1)
        self.assertIn('(subpath "%s/old")' % DEV, deny[0])
        self.assertIn('[Mm][Aa][Rr][Rr][Uu][Cc][Aa]', deny[0])
        self.assertIn('\\.[Ss][Ss][Hh]', deny[0])
        self.assertNotIn('#"^' + MCP, deny[0])  # nested root covered by the outer one
        self.assertGreater(lines.index(deny[0]), lines.index('(allow file-write* (subpath "%s"))' % MCP))

    def test_regexes_catch_forbidden_names(self):
        import re
        rules = mac_policy.project_rules({'rw': [MCP], 'ro': [DEV], 'exclude': []})
        regexes = re.findall(r'#"([^"]+)"', rules[-1])
        def denied(path):
            return any(re.search(r, path) for r in regexes)
        for p in (DEV + '/LaMarrucaApp', DEV + '/x/my_BITCOIN/a', MCP + '/.ssh/id', DEV + '/a/Library',
                  DEV + '/.config', DEV + '/LiDAR'):
            self.assertTrue(denied(p), p)
        for p in (DEV + '/app/src/main.py', MCP + '/repo/.git/HEAD', DEV + '/libraryx', DEV + '/my.sshkeys'):
            self.assertFalse(denied(p), p)

    def test_invalid_project_paths_refused(self):
        for bad in ({'rw': ['/etc'], 'ro': [], 'exclude': []}, {'rw': [], 'ro': ['/Users/b/a"b'], 'exclude': []},
                    {'rw': [], 'ro': ['/Users/b/x/../y'], 'exclude': []}):
            with self.assertRaises(ValueError):
                mac_policy.project_rules(bad)


class ChildProjects(unittest.TestCase):
    def run_child(self, cwd, projects):
        import mac_child
        captured = {}
        env = {'MCP_PROJECTS': json.dumps(projects)} if projects is not None else {}
        with patch.object(mac_child, 'require_identity'), patch.object(mac_child.resource, 'setrlimit'), \
                patch.object(mac_child.os, 'execve', side_effect=lambda p, a, e: captured.update(env=e)), \
                patch.dict(mac_child.os.environ, env, clear=True), patch.object(mac_child, 'profile', return_value='x') as prof, \
                patch.object(mac_child.sys, 'argv', ['c', '/Users/Shared/w', cwd, 'git status', '/dev/ttys001']):
            mac_child.main()
        return captured['env'], prof.call_args.args

    def test_project_cwd_and_git_trust(self):
        projects = {'rw': [MCP], 'ro': [DEV], 'exclude': []}
        env, args = self.run_child(MCP + '/repo', projects)
        self.assertEqual(args[3], projects)
        self.assertEqual((env['GIT_CONFIG_KEY_0'], env['GIT_CONFIG_VALUE_0']), ('safe.directory', '*'))
        self.assertNotIn('HTTPS_PROXY', env)

    def test_cwd_outside_roots_refused(self):
        with self.assertRaises(SystemExit):
            self.run_child('/Users/babo/Documents', {'rw': [MCP], 'ro': [DEV], 'exclude': []})
        with self.assertRaises(SystemExit):
            self.run_child(DEV, None)
        with self.assertRaises(SystemExit):
            self.run_child(DEV, {'rw': [MCP]})


if __name__ == '__main__':
    unittest.main()
