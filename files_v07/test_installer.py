import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import upgrade_files as u


class InstallerTests(unittest.TestCase):
    def test_activation_runs_independently_of_approver(self):
        with patch.object(u.subprocess,'run') as run, patch.object(u,'record') as record:
            u.schedule_activation()
        argv=run.call_args.args[0]
        self.assertEqual(argv[0],'systemd-run')
        self.assertIn('--on-active=5s',argv)
        self.assertEqual(argv[-1],'--activate')
        record.assert_called_once_with('activation_scheduled',installer=str(u.SELF))

    def test_restart_waits_for_systemd_grace_period(self):
        with patch.object(u.subprocess,'run') as run, patch.object(u,'call',return_value={'machines':[{'machine':'vps','online':True}]}):
            u.restart()
        self.assertEqual(run.call_count,2)
        self.assertTrue(all(c.kwargs['timeout']>=100 for c in run.call_args_list))

    def test_source_permissions_survive_private_umask(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(u.os, 'fchown'):
            p = Path(tmp) / 'code.py'
            previous = os.umask(0o077)
            try:
                u.atomic(p, b'pass\n')
            finally:
                os.umask(previous)
            self.assertEqual(p.stat().st_mode & 0o777, 0o644)

    def test_restore_refuses_corrupt_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / 'backup'
            backup.mkdir()
            (backup / 'manifest.json').write_text(json.dumps({'agent.py': {'mode': 420, 'uid': 0, 'gid': 0}}))
            (backup / 'agent.py').write_bytes(b'corrupt')
            with patch.object(u, 'BASE', root), patch.object(u, 'BACKUP', backup), patch.object(u, 'atomic') as write:
                with self.assertRaises(RuntimeError):
                    u.restore()
                write.assert_not_called()

    def test_restore_preserves_old_metadata_and_removes_only_pinned_new_file(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(u.os, 'fchown') as chown:
            root = Path(tmp)
            backup = root / 'backup'
            backup.mkdir()
            old, new = b'old source\n', b'new module\n'
            (backup / 'agent.py').write_bytes(old)
            (root / 'file_tools.py').write_bytes(new)
            manifest = {'agent.py': {'mode': 0o640, 'uid': 12, 'gid': 34}, 'file_tools.py': None}
            (backup / 'manifest.json').write_text(json.dumps(manifest))
            with patch.object(u, 'BASE', root), patch.object(u, 'BACKUP', backup), \
                 patch.object(u, 'ORIGINAL', {'agent.py': u.sha(old)}), \
                 patch.object(u, 'PAYLOAD', {'file_tools.py': {'sha256': u.sha(new)}}), \
                 patch.object(u, 'restart'):
                u.restore()
            self.assertEqual((root / 'agent.py').read_bytes(), old)
            self.assertEqual((root / 'agent.py').stat().st_mode & 0o777, 0o640)
            self.assertFalse((root / 'file_tools.py').exists())
            self.assertEqual(chown.call_args.args[1:], (12, 34))


if __name__ == '__main__':
    unittest.main()
