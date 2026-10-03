import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import install_isolation as u


class Tests(unittest.TestCase):
    def test_binary_permissions_survive_umask(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(u.os,'fchown') as owner:
            path=Path(tmp)/'binary';old=os.umask(0o077)
            try:u.atomic(path,b'binary',0o550,987)
            finally:os.umask(old)
            self.assertEqual(path.stat().st_mode&0o777,0o550)
            self.assertEqual(owner.call_args.args[1:],(0,987))

    def test_probe_drops_privileges_and_mounts_no_host_state(self):
        responses=[types.SimpleNamespace(returncode=0,stdout='997\n',stderr=''),
                   types.SimpleNamespace(returncode=0,stdout='{"uid":997}',stderr='')]
        with patch.object(u,'command',side_effect=responses) as run:
            self.assertEqual(u.probe()['uid'],997)
        for args in run.call_args_list:
            argv=args.args[0]
            self.assertEqual(argv[:4],['runuser','-u','mcp-vps-agent','--'])
            self.assertIn('--no-new-privs',argv)
            self.assertIn('--unshare-all',argv)
            self.assertIn('--cap-drop',argv)
            self.assertNotIn('--bind',argv)
            self.assertEqual(argv[argv.index('--ro-bind')+1:argv.index('--ro-bind')+3],['/usr','/usr'])

    def test_wrong_uid_fails_before_further_checks(self):
        with patch.object(u,'command',return_value=types.SimpleNamespace(returncode=0,stdout='0\n',stderr='')) as run:
            with self.assertRaises(RuntimeError):u.probe()
            self.assertEqual(run.call_count,1)

    def test_rollback_refuses_modified_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile=Path(tmp)/'profile';profile.write_bytes(b'changed')
            with patch.object(u,'PROFILE',profile),patch.object(u,'profile_command') as unload:
                with self.assertRaises(RuntimeError):u.remove_installed()
                unload.assert_not_called()
            self.assertEqual(profile.read_bytes(),b'changed')


if __name__=='__main__':unittest.main()
