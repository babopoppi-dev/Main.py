import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import enroll_mac_mio as m

class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.config=self.root/'gateway.json'
        self.original=b'{"agents":{"vps":{"unchanged":true},"mac_noleggio":{"unchanged":true}},"other":"preserve"}\n'
        self.config.write_bytes(self.original)
        self.config.chmod(0o640)
        self.source=self.root/'source'
        self.source.mkdir()
        (self.source/'test.py').write_bytes(b'fixture')
        self.stack=contextlib.ExitStack()
        for key,value in {'CONFIG':self.config,'VERIFY':self.root/'mac.sha256','BACKUP':self.root/'backup',
              'RECEIPT':self.root/'backup/receipt.json','LOCK':self.root/'maintenance.lock',
              'SOURCE_ROOT':self.source,'EXPECTED':{'test.py':m.sha(b'fixture')}}.items():
            self.stack.enter_context(patch.object(m,key,value))
        self.stack.enter_context(patch.object(m.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=0)))
        self.stack.enter_context(patch.object(m.grp,'getgrnam',return_value=SimpleNamespace(gr_gid=0)))
        self.restart_impl=m.restart
        self.restart=self.stack.enter_context(patch.object(m,'restart'))
        self.reader=self.stack.enter_context(patch.object(m,'verify_reader'))
    def tearDown(self):
        self.stack.close();self.tmp.cleanup()
    def run_action(self,action):
        with patch.object(m.sys,'argv',['enroll.py',action]),contextlib.redirect_stdout(io.StringIO()):
            m.main()
    def test_apply_preserves_then_rolls_back_exact_bytes(self):
        self.run_action('--apply')
        cfg=json.loads(self.config.read_bytes())
        self.assertEqual(cfg['other'],'preserve')
        self.assertEqual(cfg['agents']['vps'],{'unchanged':True})
        self.assertEqual(set(cfg['agents']),{'vps','mac_noleggio','mac_mio'})
        self.assertEqual(m.VERIFY.read_text(),m.DIGEST)
        self.assertEqual(self.config.stat().st_mode & 0o777,0o640)
        self.run_action('--rollback')
        self.assertEqual(self.config.read_bytes(),self.original)
        self.assertEqual(self.config.stat().st_mode & 0o777,0o640)
        self.assertFalse(m.VERIFY.exists())
    def test_restart_failure_restores_original(self):
        self.restart.side_effect=[RuntimeError('fixture service failure'),None]
        with self.assertRaises(RuntimeError): self.run_action('--apply')
        self.assertEqual(self.config.read_bytes(),self.original)
        self.assertFalse(m.VERIFY.exists())
    def test_source_change_blocks_before_backup(self):
        (self.source/'test.py').write_bytes(b'changed')
        with self.assertRaises(RuntimeError): self.run_action('--apply')
        self.assertEqual(self.config.read_bytes(),self.original)
        self.assertFalse(m.BACKUP.exists())
    def test_existing_enrollment_not_overwritten(self):
        m.VERIFY.write_text('existing')
        with self.assertRaises(RuntimeError): self.run_action('--apply')
        self.assertEqual(m.VERIFY.read_text(),'existing')
    def test_concurrent_changes_block_rollback(self):
        self.run_action('--apply')
        self.config.write_bytes(b'{"changed":true}')
        with self.assertRaises(RuntimeError): self.run_action('--rollback')
        self.assertEqual(self.config.read_bytes(),b'{"changed":true}')

    def test_unreadable_new_config_restores_before_activation(self):
        self.reader.side_effect=PermissionError('service identity cannot read config')
        with self.assertRaises(PermissionError): self.run_action('--apply')
        self.assertEqual(self.config.read_bytes(),self.original)
        self.assertEqual(self.config.stat().st_mode & 0o777,0o640)
        self.restart.assert_called_once()

    def test_readiness_rejects_bad_health(self):
        from unittest.mock import MagicMock
        response=MagicMock()
        response.__enter__.return_value=io.StringIO('{"ok":false}')
        with patch.object(m.subprocess,'run'),patch.object(m.time,'sleep'),patch('urllib.request.urlopen',return_value=response):
            with self.assertRaises(RuntimeError): self.restart_impl()

    def test_readiness_rejects_service_that_dies_after_start(self):
        with patch.object(m.subprocess,'run',side_effect=[None,RuntimeError('service stopped')]),patch.object(m.time,'sleep'):
            with self.assertRaises(RuntimeError): self.restart_impl()

if __name__=='__main__': unittest.main()
