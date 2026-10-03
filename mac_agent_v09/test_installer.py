import hashlib
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import install_mac_agent as i

class InstallerTests(unittest.TestCase):
    def test_running_dedicated_account_blocks_install(self):
        with patch.object(i,'identity'),patch.object(i,'active',return_value=[100]):
            with self.assertRaisesRegex(RuntimeError,'in use'):i.check()
    def test_existing_destination_blocks_install(self):
        with patch.object(i,'identity'),patch.object(i,'active',return_value=[]),patch.object(i.Path,'exists',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'destination exists'):i.check()
    def test_read_rejects_symlink_and_private_public_file(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t).resolve()/'real';p.write_text('test');p.chmod(0o644)
            q=Path(t).resolve()/'link';q.symlink_to(p)
            with self.assertRaises(OSError):i.read_regular(q,os.getuid())
            with self.assertRaises(RuntimeError):i.read_regular(p,os.getuid(),private=True)
    def test_root_guard_blocks_apply(self):
        with patch.object(i.sys,'argv',['installer','--apply']),patch.object(i.os,'getuid',return_value=501),patch.object(i,'apply') as apply:
            with self.assertRaises(SystemExit):i.main()
            apply.assert_not_called()
    def test_child_loses_all_root_groups(self):
        with patch.object(i.subprocess,'run') as run:
            i.child(['selftest.py'])
            kw=run.call_args.kwargs
            self.assertEqual((kw['user'],kw['group'],kw['extra_groups']),(5000,5000,[5000]))
    def test_workspace_with_new_file_is_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as t,patch.object(i,'OLDWORK',Path(t)):
            (Path(t)/'new.txt').write_text('must stay')
            with self.assertRaises(RuntimeError):i.empty_old_workspace()
            self.assertEqual((Path(t)/'new.txt').read_text(),'must stay')
    def test_rollback_wont_restore_old_while_new_daemon_still_loaded(self):
        with patch.object(i.Path,'exists',return_value=True),patch.object(i,'read_regular',return_value=b'plist'),patch.object(i,'run',return_value=types.SimpleNamespace(returncode=0)),patch.object(i.os,'replace') as move:
            with self.assertRaisesRegex(RuntimeError,'still loaded'):i.restore_old({'new_plist_sha256':hashlib.sha256(b'plist').hexdigest()})
            move.assert_not_called()

if __name__=='__main__':unittest.main()
