import os
import base64
import contextlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import zlib
import upgrade_vps_template as u


class Deployment(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.back=self.base/'backup';self.back.mkdir()
        self.old=b'old code';self.new=b'new code'
        self.original={'one.py':u.sha(self.old),'new.py':None}
        self.payload={'one.py':self.new,'new.py':b'added code'}
        self.manifest={'one.py':{'sha256':u.sha(self.old),'mode':0o644,'uid':0,'gid':0},'new.py':None}
        (self.base/'one.py').write_bytes(self.new);(self.base/'new.py').write_bytes(b'added code')
        (self.back/'one.py').write_bytes(self.old);(self.back/'manifest.json').write_text(json.dumps(self.manifest))
        self.stack=contextlib.ExitStack()
        for name,value in [('BASE',self.base),('BACKUP',self.back),('ORIGINAL',self.original),('PAYLOAD',self.payload)]:
            self.stack.enter_context(patch.object(u,name,value))
        self.stack.enter_context(patch.object(u,'read',side_effect=lambda p:Path(p).read_bytes()))
        self.stack.enter_context(patch.object(u,'trusted_directory'))
        self.stack.enter_context(patch.object(u.os,'fchown'))

    def tearDown(self):self.stack.close();self.tmp.cleanup()

    def test_rollback_restores_bytes_and_removes_only_added_modules(self):
        u.restore()
        self.assertEqual((self.base/'one.py').read_bytes(),self.old)
        self.assertFalse((self.base/'new.py').exists())
        self.assertTrue((self.back/'one.py').exists())

    def test_rollback_conflict_checks_all_files_before_any_write(self):
        (self.base/'new.py').write_bytes(b'someone else edited')
        with patch.object(u,'atomic') as write:
            with self.assertRaises(RuntimeError):u.restore()
            write.assert_not_called()
        self.assertEqual((self.base/'one.py').read_bytes(),self.new)

    def test_corrupted_backup_does_not_restore_any_file(self):
        (self.back/'one.py').write_bytes(b'corrupt')
        with patch.object(u,'atomic') as write:
            with self.assertRaises(RuntimeError):u.restore()
            write.assert_not_called()

    def test_automatic_rollback_accepts_partial_install(self):
        (self.base/'new.py').unlink()
        u.restore(strict=False)
        self.assertEqual((self.base/'one.py').read_bytes(),self.old)

    def test_symlink_destination_refused(self):
        (self.base/'new.py').unlink();(self.base/'new.py').symlink_to(self.back/'one.py')
        with self.assertRaises(RuntimeError):u.restore(strict=False)
        self.assertEqual((self.back/'one.py').read_bytes(),self.old)

    def test_busy_shell_prevents_install(self):
        for state in ({'active_locks':[{'owner':'other'}]}, {'shell_enabled':True}):
            with patch.object(u,'call',return_value=state):
                with self.assertRaises(RuntimeError):u.idle()

    def test_atomic_preserves_permissions(self):
        path=self.base/'output';u.atomic(path,b'test',0o640,0,987)
        self.assertEqual(path.read_bytes(),b'test');self.assertEqual(path.stat().st_mode&0o777,0o640)

    def test_restart_touches_only_the_vps_agent(self):
        with patch.object(u,'run') as run,patch.object(u,'call',return_value={'machines':[
            {'machine':'vps','online':True,'meta':{'agent_version':'0.12-vps-work-1'}},
            {'machine':'mac_noleggio','online':False}]}):
            u.restart(True)
        self.assertEqual([c.args[0] for c in run.call_args_list],[['systemctl','restart',u.AGENT]])
        with patch.object(u,'run'),patch.object(u,'call',return_value={'machines':[{'machine':'vps','online':True,'meta':{}}]}),\
             patch.object(u.time,'monotonic',side_effect=[0,0,100]),patch.object(u.time,'sleep'):
            with self.assertRaises(RuntimeError):u.restart(True)

    def test_open_session_blocks_install(self):
        with patch.object(u,'call',return_value={'work_sessions':[{'work_session_id':'a'*32}]}):
            with self.assertRaises(RuntimeError):u.idle()

    def test_pinned_dependencies_match_tested_sources(self):
        here=Path(__file__).parent
        for n,h in u.DEPENDENCIES.items():
            if n!='cg_mcp.py':self.assertEqual(u.sha((here/n).read_bytes()),h,n)
        import upgrade_vps_v012_20261003 as generated
        self.assertEqual(generated.ORIGINAL,{'agent.py':u.sha((here.parent/'search_v010'/'agent.py').read_bytes()),'work_sessions.py':None})
        self.assertEqual(u.sha((here.parent/'shell_v08'/'cg_mcp.py').read_bytes()),u.DEPENDENCIES['cg_mcp.py'])

    def test_generated_package_uses_exact_tested_sources(self):
        import upgrade_vps_v012_20261003 as generated
        generated.load_package()
        for n,b in generated.PAYLOAD.items():
            self.assertEqual(b,(Path(__file__).parent/n).read_bytes())
            self.assertEqual(b,generated.TESTS[n])


class MaintenanceLock(unittest.TestCase):
    def test_activation_waits_interactive_fails(self):
        import fcntl,tempfile
        with tempfile.NamedTemporaryFile() as f:
            holder=os.open(f.name,os.O_RDWR);fcntl.flock(holder,fcntl.LOCK_EX)
            fd=os.open(f.name,os.O_RDWR)
            try:
                with self.assertRaisesRegex(RuntimeError,'another maintenance'):u.maintenance_lock(fd,'--check')
                ticks=iter([0,10,20,30])
                def sleep(_):
                    if next(ticks)==20:fcntl.flock(holder,fcntl.LOCK_UN)
                with patch.object(u.time,'sleep',side_effect=sleep):u.maintenance_lock(fd,'--activate')
            finally:os.close(fd);os.close(holder)

if __name__=='__main__':unittest.main(verbosity=2)
