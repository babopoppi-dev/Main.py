import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import bootstrap_account as b


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.state=Path(self.tmp.name)/'state'
        self.p=patch.object(b,'STATE',self.state);self.p.start()
        self.machine=patch.object(b,'machine_check');self.machine.start()
    def tearDown(self):
        self.machine.stop();self.p.stop();self.tmp.cleanup()
    def test_existing_account_is_not_modified(self):
        with patch.object(b,'record',return_value={'UniqueID':['501']}),patch.object(b,'set_attribute') as mutate:
            with self.assertRaises(RuntimeError):b.apply()
            mutate.assert_not_called()
    def test_numeric_collision_is_rejected(self):
        with patch.object(b,'record',return_value=None),patch.object(b,'identifiers',return_value={5000}):
            with self.assertRaises(RuntimeError):b.preflight()
    def test_read_only_check_does_not_create_anything(self):
        with patch.object(b,'record',return_value=None),patch.object(b,'identifiers',return_value={501}):
            self.assertTrue(b.preflight()['ready'])
        self.assertFalse(self.state.exists())
    def test_wrong_machine_rejected(self):
        self.machine.stop()
        try:
            with patch.object(b.sys,'platform','darwin'),patch.object(b,'run',return_value=types.SimpleNamespace(stdout='"IOPlatformUUID" = "wrong"')):
                with self.assertRaises(RuntimeError):b.machine_check()
        finally:self.machine.start()
    def test_directory_service_error_is_not_absence(self):
        r=types.SimpleNamespace(returncode=1,stdout='',stderr='permission denied')
        with patch.object(b,'run',return_value=r):
            with self.assertRaises(RuntimeError):b.record('/Users/mcp_andrea')
    def test_rollback_refuses_foreign_identity(self):
        with patch.object(b,'active_processes',return_value=[]),patch.object(b,'record',return_value={'GeneratedUID':['other']}),patch.object(b,'run') as run:
            with self.assertRaises(RuntimeError):b.rollback({'user_uuid':'ours','group_uuid':'group'})
            run.assert_not_called()
    def test_rollback_refuses_running_account(self):
        with patch.object(b,'active_processes',return_value=[345]),patch.object(b,'run') as run:
            with self.assertRaises(RuntimeError):b.rollback({})
            run.assert_not_called()
    def test_rollback_refuses_repurposed_account(self):
        current={'GeneratedUID':['ours'],'UniqueID':['5000'],'UserShell':['/bin/zsh']}
        with patch.object(b,'active_processes',return_value=[]),patch.object(b,'record',return_value=current),patch.object(b,'run') as run:
            with self.assertRaises(RuntimeError):b.rollback({'user_uuid':'ours','group_uuid':'group'})
            run.assert_not_called()
    def test_partial_failure_restores_only_created_records(self):
        records={};deletions=[]
        def set_attr(path,key,val):
            if key=='UserShell':raise RuntimeError('simulated directory service failure')
            records.setdefault(path,{})[key]=[str(val)]
        def run(argv,**kwargs):
            if '-delete' in argv:deletions.append(argv[-1]);records.pop(argv[-1],None)
            return types.SimpleNamespace(returncode=0,stdout='5000',stderr='')
        with patch.object(b,'record',side_effect=lambda p:records.get(p)),patch.object(b,'identifiers',return_value=set()),patch.object(b,'trusted_directory'),patch.object(b,'active_processes',return_value=[]),patch.object(b,'set_attribute',side_effect=set_attr),patch.object(b,'run',side_effect=run),patch.dict(b.__dict__,{'APPROVED_SOURCE':b'approved-code'}):
            with self.assertRaises(RuntimeError):b.apply()
        self.assertEqual(set(deletions),set(b.RECORDS.values()))
        self.assertTrue((self.state/'before.json').exists())
        self.assertIn('rolled_back',(self.state/'receipt.json').read_text())
    def test_success_is_disabled_login_without_admin_or_agent_change(self):
        records={}
        def set_attr(path,key,val):records.setdefault(path,{})[key]=[str(val)]
        with patch.object(b,'record',side_effect=lambda p:records.get(p)),patch.object(b,'identifiers',return_value=set()),patch.object(b,'trusted_directory'),patch.object(b,'set_attribute',side_effect=set_attr),patch.object(b,'run',return_value=types.SimpleNamespace(stdout='5000')),patch.dict(b.__dict__,{'APPROVED_SOURCE':b'approved-code'}),patch('builtins.print'):
            b.apply()
        u=records[b.RECORDS['user']]
        self.assertEqual(u['AuthenticationAuthority'],[';DisabledUser;'])
        self.assertEqual(u['UserShell'],['/usr/bin/false'])
        self.assertIn('"agent_migrated": false',(self.state/'receipt.json').read_text())


if __name__=='__main__':unittest.main()
