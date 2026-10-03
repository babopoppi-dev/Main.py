import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import cg_mcp
import upgrade_shell as u


class Tests(unittest.TestCase):
    def test_smoke_waits_for_async_command_and_accumulates_output(self):
        responses=[{'session_id':'a'*32,'running':True,'exit_code':None,'output':'9'},
                   {'session_id':'a'*32,'running':False,'exit_code':0,'output':'97\r\n'}]
        with patch.object(u,'call',side_effect=responses) as call,patch.object(u.time,'sleep'):
            result=u.completed_command('id -u')
        self.assertEqual(result['exit_code'],0)
        self.assertEqual(result['output'].strip(),'997')
        self.assertEqual(call.call_args.args[0],'shell_session')

    def test_authorizations_sharing_prefix_keep_distinct_owners(self):
        app=types.SimpleNamespace(oauth=types.SimpleNamespace(db=types.SimpleNamespace(
            client=lambda _: {'client_name':'ChatGPT'})))
        a=cg_mcp.caller_of(app,{'client_id':'client','family_id':'samepref_AAA111'})
        b=cg_mcp.caller_of(app,{'client_id':'client','family_id':'samepref_BBB222'})
        self.assertNotEqual(a,b)
        self.assertTrue(a.endswith('samepref_AAA111'))

    def test_unsafe_authorization_identity_is_refused(self):
        app=types.SimpleNamespace(oauth=types.SimpleNamespace(db=types.SimpleNamespace(client=lambda _: {})))
        with self.assertRaises(PermissionError):
            cg_mcp.caller_of(app,{'client_id':'x','family_id':'bad\nidentity'})

    def test_atomic_write_preserves_selected_permissions(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(u.os,'fchown') as owner:
            path=Path(tmp)/'config'
            u.atomic(path,b'config',0o640,0,987)
            self.assertEqual(path.stat().st_mode&0o777,0o640)
            self.assertEqual(owner.call_args.args[1:],(0,987))

    def test_explicit_rollback_checks_all_conflicts_before_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);backup=base/'backup';backup.mkdir()
            (backup/'manifest.json').write_text(json.dumps({'files':{},'installed_config_sha256':'unused'}))
            (base/'agent.py').write_bytes(b'external edit')
            with patch.object(u,'BASE',base),patch.object(u,'BACKUP',backup),patch.object(u,'PAYLOAD',{'agent.py':{'sha256':'different'}}),patch.object(u,'atomic') as write:
                with self.assertRaises(RuntimeError):u.restore()
                write.assert_not_called()
            self.assertEqual((base/'agent.py').read_bytes(),b'external edit')


if __name__=='__main__':unittest.main()
