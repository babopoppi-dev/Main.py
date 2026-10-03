"""VPS v0.12 installer: package pinning, preflight from embedded sources, real smoke."""
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
P = HERE.parent
sys.path.insert(0, str(HERE))
import upgrade_vps_v012_20261003 as u  # noqa: E402


def live_base(tmp):
    """A fake /opt holding the live (post-gateway-v0.12) dependencies."""
    base = Path(tmp)
    for n in ('file_schema.py', 'search_schema.py', 'work_schema.py', 'cg_tools.py'):
        shutil.copy(P / n, base / n)
    shutil.copy(P / 'shell_common.py', base / 'isolated_shell.py')
    return base


def plain_read(p, owner=0):
    return Path(p).read_bytes()


class Package(unittest.TestCase):
    def test_sources_pinned_and_dependencies_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = live_base(tmp)
            with patch.object(u, 'BASE', base), patch.object(u, 'read', side_effect=plain_read):
                u.load_package()
                self.assertEqual(set(u.PAYLOAD), {'agent.py', 'file_tools.py', 'search_tools.py', 'work_sessions.py', 'upload_tools.py'})
                self.assertEqual(u.PAYLOAD['agent.py'], (HERE / 'agent.py').read_bytes())
                (base / 'isolated_shell.py').write_text('# changed\n')
                with self.assertRaisesRegex(RuntimeError, 'live dependency changed'):
                    u.load_package()

    def test_live_hashes_match_transcription_and_both_catalogs(self):
        self.assertEqual(u.ORIGINAL['agent.py'], hashlib.sha256((HERE / 'agent_live.py').read_bytes()).hexdigest())
        live11 = P.parent / 'coordination_v011r1'
        for n in ('file_schema.py', 'work_schema.py', 'cg_tools.py'):
            self.assertEqual(u.DEPENDENCIES[n], [hashlib.sha256((live11 / n).read_bytes()).hexdigest(),
                                                 hashlib.sha256((P / n).read_bytes()).hexdigest()])

    def test_validate_accepts_either_catalog_but_nothing_else(self):
        hashes = {**u.ORIGINAL, **{n: (h[0] if isinstance(h, list) else h) for n, h in u.DEPENDENCIES.items()}}
        ok = types.SimpleNamespace(stdout='active')
        def run(argv, timeout=30):
            return types.SimpleNamespace(stdout='mcp-vps-agent' if 'show' in argv and u.AGENT in argv else
                                         'mcp-gateway' if 'show' in argv else 'active')
        with tempfile.TemporaryDirectory() as tmp:
            for variant in (0, 1):
                live = {n: (h[variant] if isinstance(h, list) else h) for n, h in u.DEPENDENCIES.items()}
                with patch.object(u, 'BACKUP', Path(tmp) / 'none'), patch.object(u, 'idle'), patch.object(u, 'run', side_effect=run), \
                        patch.object(u, 'digest', side_effect=lambda p: {**u.ORIGINAL, **live}[p.name]):
                    u.validate()
            with patch.object(u, 'BACKUP', Path(tmp) / 'none'), patch.object(u, 'idle'), patch.object(u, 'run', side_effect=run), \
                    patch.object(u, 'digest', side_effect=lambda p: 'f' * 64 if p.name == 'file_schema.py' else hashes[p.name]):
                with self.assertRaisesRegex(RuntimeError, 'live source changed: file_schema.py'):
                    u.validate()
        del ok

    def test_preflight_suite_passes_from_embedded_sources(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as code:
            base = live_base(tmp)
            with patch.object(u, 'BASE', base), patch.object(u, 'read', side_effect=plain_read):
                u.load_package()
            for n, b in u.TESTS.items():
                Path(code, n).write_bytes(b)
            run = "import sys,unittest;sys.path.insert(0,%r);s=unittest.defaultTestLoader.loadTestsFromNames(['test_search','test_files_v012','test_vps_agent']);r=unittest.TextTestRunner().run(s);sys.exit(0 if r.wasSuccessful() else 1)" % code
            r = subprocess.run([sys.executable, '-I', '-B', '-c', run], capture_output=True, text=True, timeout=120, cwd='/')
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])

    def test_apply_schedules_unit_and_rollback_validates_first(self):
        source = Path(u.__file__).read_text()
        self.assertIn("'--unit=central-mcp-vps-v012-20261003'", source)
        self.assertIn("loadTestsFromNames(['test_search','test_files_v012','test_vps_agent'])", source)
        self.assertIn("state.get('work_sessions')", source)


def live_smoke(catalog):
    """Run the installer smoke against the real v0.12 agent dispatcher in-process.

    catalog 'v011' hides the new file tools, as the gateway does before its v0.12 activation.
    """
    import uuid
    import test_vps_agent  # configures and imports the agent with temp roots
    agent = test_vps_agent.agent
    import cg_tools
    loop = asyncio.new_event_loop()

    def rpc(method, params):
        if method == 'tools/list':
            hidden = {'delete_path', 'copy_file', 'read_binary', 'upload_file'} if catalog == 'v011' else set()
            return {'tools': [t for t in cg_tools.TOOLS if t['name'] not in hidden]}
        args = dict(params['arguments']); args.pop('machine', None)
        try:
            value = loop.run_until_complete(agent.dispatch(params['name'], args, 'claude:installer', uuid.uuid4().hex))
            return {'content': [{'text': json.dumps(value)}]}
        except Exception as exc:
            return {'isError': True, 'content': [{'text': type(exc).__name__ + ': ' + str(exc)}]}

    def call(name, **args):
        if name == 'list_machines':
            return {'machines': [{'machine': 'vps', 'online': True, 'meta': agent.hello_meta()}]}
        value = rpc('tools/call', {'name': name, 'arguments': args})
        if value.get('isError'):
            raise RuntimeError(name + ': ' + value['content'][0]['text'][:300])
        return json.loads(value['content'][0]['text'])

    async def fake_baseline(args):
        return {'exit_code': 0}
    with patch.object(u, 'rpc', side_effect=rpc), patch.object(u, 'call', side_effect=call), \
            patch.object(u, 'WORK', test_vps_agent.WORKDIR), patch.object(agent, 'run_baseline', fake_baseline):
        checks = u.smoke()
    state = call('who_is_working')
    assert not (state['work_sessions'] or state['work_locks']), state
    assert len(checks) == (5 if catalog == 'v011' else 6), checks
    print(json.dumps(checks))


class LiveSmoke(unittest.TestCase):
    def test_smoke_against_real_agent_with_both_catalogs(self):
        for catalog in ('v011', 'v012'):
            with self.subTest(catalog=catalog):
                r = subprocess.run([sys.executable, '-B', __file__, '--live-smoke', catalog], capture_output=True,
                                   text=True, timeout=120, cwd=str(HERE))
                self.assertEqual(r.returncode, 0, r.stdout[-1000:] + r.stderr[-2000:])
                self.assertIn('rolled back', r.stdout)
                self.assertEqual('upload, read_binary' in r.stdout, catalog == 'v012')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--live-smoke']:
        live_smoke(sys.argv[2])
    else:
        unittest.main()
