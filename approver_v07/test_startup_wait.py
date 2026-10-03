import types
import unittest
from unittest.mock import patch
import upgrade_approver as u


class StartupWaitTests(unittest.TestCase):
    def test_telegram_startup_slower_than_twenty_seconds_can_complete(self):
        attempts=0
        def command(args):
            nonlocal attempts
            output=''
            if args[0]=='journalctl':
                attempts+=1
                if attempts>=45:output='approver pronto v0.7'
            return types.SimpleNamespace(returncode=0,stdout=output)
        with patch.object(u,'command',side_effect=command),patch.object(u.time,'sleep'):
            u.restart_and_check('approver pronto v0.7')
        self.assertEqual(attempts,45)

    def test_started_marker_alone_is_not_ready(self):
        with patch.object(u,'command',return_value=types.SimpleNamespace(
                returncode=0,stdout='approver avviato v0.7')),patch.object(u.time,'sleep'):
            with self.assertRaises(RuntimeError):
                u.restart_and_check('approver pronto v0.7')
