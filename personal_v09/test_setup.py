import types,unittest
from unittest.mock import Mock,patch
import setup_personal as s

class SetupTests(unittest.TestCase):
    def parts(self):return [Mock(),Mock(),Mock()]
    def test_nonroot_apply_rejected_before_loading_components(self):
        with patch.object(s.sys,'argv',['setup','--apply']),patch.object(s.os,'getuid',return_value=501),patch.object(s,'components') as load:
            with self.assertRaises(SystemExit):s.main()
            load.assert_not_called()
    def test_failed_account_stops_preflight_and_migration(self):
        a,p,m=self.parts();a.apply.side_effect=RuntimeError('creation failed');a.STATE.exists.return_value=False
        with patch.object(s,'check'),patch.dict(s.__dict__,{'APPROVED_SOURCE':b'approved'}),patch('builtins.print'):
            with self.assertRaises(RuntimeError):s.apply(a,p,m)
        p.apply.assert_not_called();m.apply.assert_not_called()
    def test_failed_preflight_never_migrates(self):
        a,p,m=self.parts();p.apply.side_effect=SystemExit(1);a.STATE.exists.return_value=False;a.STATE.__truediv__=Mock()
        with patch.object(s,'check'),patch.dict(s.__dict__,{'APPROVED_SOURCE':b'approved'}),patch('builtins.print'):
            with self.assertRaises(SystemExit):s.apply(a,p,m)
        m.apply.assert_not_called()
    def test_success_stages_are_ordered(self):
        from pathlib import Path
        a,p,m=self.parts();a.STATE=Path('/nonexistent-personal-test-root');events=[]
        a.apply.side_effect=lambda:events.append('account');p.apply.side_effect=lambda:events.append('preflight');m.apply.side_effect=lambda:events.append('migration')
        with patch.object(s,'check'),patch.dict(s.__dict__,{'APPROVED_SOURCE':b'approved'}),patch('builtins.print'):
            s.apply(a,p,m)
        self.assertEqual(events,['account','preflight','migration'])

if __name__=='__main__':unittest.main()
