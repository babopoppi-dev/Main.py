"""Gateway v0.12 p2 activation (from the live r1 catalog): real catalog preflight, backup/install/rollback with mocked services."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch
import upgrade_gateway_v012p2_20261003 as g

HERE = Path(__file__).resolve().parent
R1 = (HERE / 'live_r1' / 'upgrade_gateway_v012_20261003.py').read_text()
LIVE = {}
exec(R1[:R1.index('def sha(data):')], LIVE)


class GatewayActivation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name) / 'gw'; self.base.mkdir()
        (self.base / 'backups').mkdir()
        for n, text in LIVE['SOURCES'].items():
            (self.base / n).write_text(text)
        shutil.copy(HERE / 'search_schema.py', self.base / 'search_schema.py')
        # cg_mcp.py is only hash-pinned (never imported or replaced): a stand-in suffices.
        (self.base / 'cg_mcp.py').write_text('# live gateway server stand-in\n')
        stub = hashlib.sha256((self.base / 'cg_mcp.py').read_bytes()).hexdigest()
        for p in self.base.iterdir():
            if p.is_file(): os.chmod(p, 0o644)
        self.patches = [patch.object(g, 'BASE', self.base), patch.object(g, 'BACKUP', self.base / 'backups' / 'pre'),
                        patch.object(g, 'RECEIPT', self.base / 'receipt.json'), patch.object(g, 'trusted_directory'),
                        patch.object(g, 'idle'), patch.object(g, 'PYTHON', shutil.which('python3')),
                        patch.dict(g.DEPENDENCIES, {'cg_mcp.py': stub})]
        for p in self.patches: p.start()
        g.load_package()

    def tearDown(self):
        for p in self.patches: p.stop()
        self.tmp.cleanup()

    def test_check_pins_live_sources_and_imports_new_catalog(self):
        with patch.object(g, 'run', side_effect=lambda a, t=30: types.SimpleNamespace(stdout='mcp-gateway' if 'show' in a else 'active')):
            self.assertTrue(g.validate()['check_passed'])
        self.assertEqual(g.preflight(), 29)
        (self.base / 'cg_mcp.py').write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'live source changed'): g.validate()

    def test_live_payload_hashes_match_r1_install(self):
        self.assertEqual(g.ORIGINAL, {'cg_tools.py': '515b27df01b2195027d3de283f0a619cd568641a100158b7d310fdb80703a567'})
        self.assertEqual(g.DEPENDENCIES['work_schema.py'], LIVE['PAYLOAD_SHA']['work_schema.py'])
        self.assertEqual(g.DEPENDENCIES['file_schema.py'], LIVE['PAYLOAD_SHA']['file_schema.py'])
        for n, b in g.PAYLOAD.items(): self.assertEqual(b, (HERE / n).read_bytes())

    def test_install_then_rollback_restores_exact_bytes_and_modes(self):
        before = {n: (self.base / n).read_bytes() for n in g.ORIGINAL}
        manifest = g.backup(); g.install(manifest)
        for n in g.ORIGINAL:
            self.assertEqual((self.base / n).read_bytes(), g.PAYLOAD[n])
            self.assertEqual(os.stat(self.base / n).st_mode & 0o777, 0o644)
        g.restore()
        for n in g.ORIGINAL: self.assertEqual((self.base / n).read_bytes(), before[n])

    def test_apply_failure_rolls_back(self):
        with patch.object(g, 'validate'), patch.object(g, 'restart'), patch.object(g, 'smoke', side_effect=RuntimeError('boom')), \
                patch.object(g.os, 'getuid', return_value=0), patch.object(g.os, 'geteuid', return_value=0), \
                patch.object(g, 'SELF', Path(g.__file__).resolve()):
            with self.assertRaisesRegex(RuntimeError, 'boom'): g.main('--activate')
        for n in g.ORIGINAL:
            self.assertEqual(hashlib.sha256((self.base / n).read_bytes()).hexdigest(), g.ORIGINAL[n])
        self.assertIn('rolled_back', (self.base / 'receipt.json').read_text())

    def test_apply_only_schedules_detached_activation(self):
        with patch.object(g, 'validate'), patch.object(g, 'preflight', return_value=29), \
                patch.object(g.os, 'getuid', return_value=0), patch.object(g.os, 'geteuid', return_value=0), \
                patch.object(g, 'SELF', Path(g.__file__).resolve()), patch.object(g, 'run') as run, patch.object(g, 'install') as install:
            g.main('--apply')
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], 'systemd-run'); self.assertEqual(argv[-1], '--activate'); install.assert_not_called()
        self.assertIn('--unit=central-mcp-v012p2-20261003', argv)

    def test_existing_backup_blocks_apply(self):
        (self.base / 'backups' / 'pre').mkdir()
        with self.assertRaisesRegex(RuntimeError, 'backup already exists'): g.validate()

    def tools(self, p2):
        out = []
        for n in ['work_session', 'work_lock', 'write_file', 'enable_full_shell', 'shell_session'] + sorted(g.NEW_TOOLS):
            props = {'machine': {}}
            if n in ('write_file', 'delete_path'): props['work_session_id'] = {}
            if n == 'enable_full_shell': props['network'] = {'enum': ['none', 'github'] + (['packages'] if p2 else [])}
            desc = 'Manage an isolated PTY.' + (' Actions: list, processes.' if p2 and n == 'shell_session' else '')
            out.append({'name': n, 'description': desc, 'inputSchema': {'properties': props}})
        return {'tools': out}

    def test_smoke_expectations_before_and_after(self):
        with patch.object(g, 'call', return_value={'exit_code': 0}):
            with patch.object(g, 'rpc', return_value=self.tools(True)):
                self.assertTrue(g.smoke(True))
                with self.assertRaises(RuntimeError): g.smoke(False)
            with patch.object(g, 'rpc', return_value=self.tools(False)):
                self.assertTrue(g.smoke(False))
                with self.assertRaises(RuntimeError): g.smoke(True)

if __name__ == '__main__': unittest.main()
