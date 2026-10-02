"""Gateway activation: real catalog preflight, backup/install/rollback with mocked services."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch
import upgrade_gateway_coordination_v011r1_20261002 as g

HERE=Path(__file__).resolve().parent
PREV=HERE.parent/'search_v010'


class GatewayActivation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)/'gw';self.base.mkdir()
        (self.base/'backups').mkdir()
        for n in ('cg_tools.py','file_schema.py','search_schema.py'):shutil.copy(PREV/n,self.base/n)
        shutil.copy(HERE.parent/'shell_v08'/'cg_mcp.py',self.base/'cg_mcp.py')
        for p in self.base.iterdir():
            if p.is_file():os.chmod(p,0o644)
        self.patches=[patch.object(g,'BASE',self.base),patch.object(g,'BACKUP',self.base/'backups'/'pre'),
                      patch.object(g,'RECEIPT',self.base/'receipt.json'),patch.object(g,'trusted_directory'),
                      patch.object(g,'idle'),patch.object(g,'PYTHON',shutil.which('python3'))]
        for p in self.patches:p.start()
        g.load_package()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.tmp.cleanup()
    def services(self):
        return patch.object(g,'run',return_value=types.SimpleNamespace(stdout='mcp-gateway' ))
    def test_check_pins_live_sources_and_imports_new_catalog(self):
        with patch.object(g,'run',side_effect=lambda a,t=30:types.SimpleNamespace(stdout='mcp-gateway' if 'show' in a else 'active')):
            self.assertTrue(g.validate()['check_passed'])
        self.assertGreater(g.preflight(),15)
        (self.base/'cg_mcp.py').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'live source changed'):g.validate()
    def test_install_then_rollback_restores_exact_bytes_and_removes_new_module(self):
        before=(self.base/'cg_tools.py').read_bytes()
        manifest=g.backup();g.install(manifest)
        self.assertEqual((self.base/'cg_tools.py').read_bytes(),g.PAYLOAD['cg_tools.py'])
        self.assertEqual(os.stat(self.base/'work_schema.py').st_mode&0o777,0o644)
        g.restore()
        self.assertEqual((self.base/'cg_tools.py').read_bytes(),before)
        self.assertFalse((self.base/'work_schema.py').exists())
    def test_apply_failure_rolls_back(self):
        with patch.object(g,'validate'),patch.object(g,'restart'),patch.object(g,'smoke',side_effect=RuntimeError('boom')),patch.object(g.os,'getuid',return_value=0):
            with self.assertRaisesRegex(RuntimeError,'boom'):g.main('--apply')
        self.assertEqual(hashlib.sha256((self.base/'cg_tools.py').read_bytes()).hexdigest(),g.ORIGINAL['cg_tools.py'])
        self.assertFalse((self.base/'work_schema.py').exists())
        self.assertIn('rolled_back',(self.base/'receipt.json').read_text())
    def test_existing_backup_blocks_apply(self):
        (self.base/'backups'/'pre').mkdir()
        with self.assertRaisesRegex(RuntimeError,'backup already exists'):g.validate()

if __name__=='__main__':unittest.main()
