import signal
import types
import unittest
from unittest.mock import patch
import mac_guard as g
from mac_policy import profile


class Tests(unittest.TestCase):
    def identity(self, uid=5000, groups=()):
        from contextlib import ExitStack
        s=ExitStack()
        s.enter_context(patch.object(g.sys,'platform','darwin'))
        for name in ('getuid','geteuid','getgid','getegid'):
            s.enter_context(patch.object(g.os,name,return_value=uid))
        s.enter_context(patch.object(g.os,'getgroups',return_value=list(groups)))
        s.enter_context(patch.object(g.pwd,'getpwuid',return_value=types.SimpleNamespace(pw_name='mcp_andrea')))
        return s
    def test_root_can_never_trigger_broadcast_cleanup(self):
        with self.identity(0),patch.object(g.os,'kill') as kill:
            with self.assertRaises(PermissionError):g.stop_dedicated_children()
            kill.assert_not_called()
    def test_personal_account_can_never_trigger_broadcast_cleanup(self):
        with self.identity(501),patch.object(g.os,'kill') as kill:
            with self.assertRaises(PermissionError):g.stop_dedicated_children()
            kill.assert_not_called()
    def test_admin_group_refused(self):
        with self.identity(groups=[5000,80]),patch.object(g.os,'kill') as kill:
            with self.assertRaises(PermissionError):g.stop_dedicated_children()
            kill.assert_not_called()
    def test_only_dedicated_identity_may_signal(self):
        with self.identity(groups=[5000]),patch.object(g.os,'getpid',return_value=100),patch.object(g,'targets',side_effect=[{200},set()]),patch.object(g.os,'kill') as kill:
            g.stop_dedicated_children()
            self.assertEqual(kill.call_args_list, [unittest.mock.call(200,signal.SIGSTOP),unittest.mock.call(200,signal.SIGKILL)])
    def test_negative_or_self_pid_always_refused(self):
        with self.identity(groups=[5000]),patch.object(g.os,'getpid',return_value=100),patch.object(g.os,'kill') as kill:
            for pid in (-1,0,1,100):
                with self.assertRaises(PermissionError):g.signal_target(pid,signal.SIGKILL)
            kill.assert_not_called()
    def test_inventory_excludes_other_users_self_scanner_and_zombies(self):
        raw='0 1 Ss\n501 200 S\n5000 100 S\n5000 300 R\n5000 400 Z\n5000 500 Ss+\n'
        self.assertEqual(g.parse_processes(raw,300,100),{500})
    def test_cleanup_rescans_descendant_born_during_stop(self):
        with self.identity(groups=[5000]),patch.object(g.os,'getpid',return_value=100),patch.object(g,'targets',side_effect=[{200},{201},set()]),patch.object(g.os,'kill') as kill:
            g.stop_dedicated_children()
            self.assertEqual([c.args[0] for c in kill.call_args_list],[200,200,201,201])
    def test_inventory_failure_cannot_trigger_signal(self):
        with self.identity(groups=[5000]),patch.object(g,'targets',side_effect=RuntimeError('inventory')),patch.object(g.os,'kill') as kill:
            with self.assertRaises(RuntimeError):g.stop_dedicated_children()
            kill.assert_not_called()
    def test_reused_identity_refused(self):
        with self.identity(),patch.object(g.pwd,'getpwuid',return_value=types.SimpleNamespace(pw_name='other')),patch.object(g.os,'kill') as kill:
            with self.assertRaises(PermissionError):g.stop_dedicated_children()
            kill.assert_not_called()
    def test_wrong_platform_refused(self):
        with self.identity(),patch.object(g.sys,'platform','linux'),patch.object(g.os,'kill') as kill:
            with self.assertRaises(PermissionError):g.stop_dedicated_children()
            kill.assert_not_called()
    def test_policy_rejects_broad_scope_or_bad_device(self):
        for path in ['/', '/Users', '/Users/Shared', '/etc']:
            with self.assertRaises(ValueError):profile(path)
        with self.assertRaises(ValueError):profile('/Users/Shared/MCPAndrea/workspace','/dev/null')
