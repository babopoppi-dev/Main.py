import types
import unittest
from unittest.mock import patch
import preflight_installer as p


class PreflightTests(unittest.TestCase):
    def test_active_account_cannot_be_used_for_preflight(self):
        with patch.object(p, 'identity'), patch.object(p, 'active', return_value=[42]):
            with self.assertRaisesRegex(RuntimeError, 'already running'):
                p.check()

    def test_previous_state_is_never_overwritten(self):
        with patch.object(p, 'identity'), patch.object(p, 'active', return_value=[]), patch.object(p.Path, 'exists', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'previous preflight'):
                p.check()

    def test_check_does_not_install(self):
        with patch.object(p, 'identity'), patch.object(p, 'active', return_value=[]), patch.object(p.Path, 'exists', return_value=False), patch.object(p.Path, 'is_symlink', return_value=False), patch.object(p.Path, 'mkdir') as mkdir:
            self.assertFalse(p.check()['live_agent_changed'])
            mkdir.assert_not_called()

    def test_child_uses_dedicated_uid_and_clean_environment(self):
        with patch.object(p.subprocess, 'run') as run:
            p.child(['worker.py'], 10)
            kwargs = run.call_args.kwargs
            self.assertEqual(kwargs['user'], 5000)
            self.assertEqual(kwargs['group'], 5000)
            self.assertEqual(kwargs['extra_groups'], [5000])
            self.assertTrue(kwargs['close_fds'])
            self.assertEqual(set(kwargs['env']), {'PATH', 'HOME', 'LANG'})

    def test_nonroot_apply_blocked(self):
        with patch.object(p.sys, 'argv', ['installer', '--apply']), patch.object(p.os, 'getuid', return_value=501), patch.object(p, 'apply') as apply:
            with self.assertRaises(SystemExit):
                p.main()
            apply.assert_not_called()

    def test_rollback_refuses_running_account(self):
        with patch.object(p, 'identity'), patch.object(p, 'active', return_value=[42]), patch.object(p.shutil, 'rmtree') as remove:
            with self.assertRaisesRegex(RuntimeError, 'active uid5000'):
                p.rollback()
            remove.assert_not_called()

    def test_cleanup_never_broadcasts_as_root(self):
        with patch.object(p, 'active', side_effect=[[42], []]), patch.object(p, 'child', return_value=types.SimpleNamespace(returncode=0)) as child, patch.object(p.os, 'kill') as kill:
            p.clear_test_processes()
            self.assertEqual(child.call_count, 1)
            kill.assert_not_called()

    def test_wrong_platform_refuses_before_directory_lookup(self):
        with patch.object(p.sys, 'platform', 'linux'), patch.object(p, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'macOS'):
                p.identity()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
