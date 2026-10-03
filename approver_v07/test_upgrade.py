import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import upgrade_approver as u

class Tests(unittest.TestCase):
    def test_explicit_permissions_survive_umask(self):
        import os
        with tempfile.TemporaryDirectory() as tmp, patch.object(u.os,'fchown') as owner:
            p=Path(tmp)/'code.py';old=os.umask(0o077)
            try:u.atomic(p,b'pass\n',0o500)
            finally:os.umask(old)
            self.assertEqual(p.stat().st_mode&0o777,0o500);owner.assert_called_once()
    def test_active_without_ready_marker_is_failure(self):
        with patch.object(u,'command',return_value=types.SimpleNamespace(returncode=0,stdout='')),patch.object(u.time,'sleep'):
            with self.assertRaises(RuntimeError):u.restart_and_check('v0.7')
    def test_ready_marker_and_running_service_pass(self):
        with patch.object(u,'command',return_value=types.SimpleNamespace(returncode=0,stdout='approver avviato v0.7')),patch.object(u.time,'sleep'):
            u.restart_and_check('approver avviato v0.7')
    def test_bad_backup_never_overwrites_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Path(tmp)/'backup';b.mkdir();(b/'approver.py').write_bytes(b'wrong')
            with patch.object(u,'BACKUP',b),patch.object(u,'atomic') as write:
                with self.assertRaises(RuntimeError):u.restore()
                write.assert_not_called()

if __name__=='__main__':unittest.main()
