import contextlib
import builtins
import importlib
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import upgrade_mac_v012_20261003 as u


class MacUpgrade(unittest.TestCase):
    def test_launcher_passes_exact_source_to_root_bootstrap(self):
        tokens=shlex.split((Path(__file__).parent/'Attiva_MCP_Andrea_v012.command').read_text())
        loaders=[tokens[i+1] for i,t in enumerate(tokens) if t=='-c']
        self.assertEqual(len(loaders),2)
        self.assertEqual(loaders[0],loaders[1])
        source=(Path(__file__).parent/'upgrade_mac_v012_20261003.py').read_bytes()
        execute=builtins.exec
        for action in ('--check','--apply'):
            with self.subTest(action=action),tempfile.TemporaryFile() as f:
                f.write(source);f.seek(0)
                fd=os.dup(f.fileno())
                fake_stat=types.SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=501,st_nlink=1)
                with patch.object(os,'open',return_value=fd),patch.object(os,'fstat',return_value=fake_stat),patch.object(sys,'argv',['launcher',action]),patch.object(builtins,'exec') as root_exec:
                    execute(compile(loaders[0],'launcher','exec'),{})
                    root_exec.assert_called_once()
                    context=root_exec.call_args.args[1]
                    self.assertEqual(context.get('APPROVED_SOURCE'),source if action=='--apply' else None)

    def test_package_matches_tested_agent_and_dependencies(self):
        here=Path(__file__).parent
        with patch.object(u,'BASE',here),patch.object(u,'read',side_effect=lambda p,owner=0:Path(p).read_bytes()):
            u.load_package()
        for n,b in u.PAYLOAD.items():
            self.assertEqual(b,(here/n).read_bytes())
            self.assertEqual(b,u.TESTS[n])
        for n,h in u.DEPENDENCIES.items():self.assertEqual(u.sha(u.TESTS[n]),h)
        with patch.object(u,'BASE',here),patch.object(u,'read',side_effect=lambda p,owner=0:b'changed' if Path(p).name=='shell_common.py' else Path(p).read_bytes()):
            with self.assertRaisesRegex(RuntimeError,'live dependency changed'):u.load_package()

    def test_plist_change_refused_before_any_stop(self):
        with patch.object(u.sys,'platform','darwin'),patch.object(u,'run',side_effect=[
            types.SimpleNamespace(stdout='5000'),types.SimpleNamespace(stdout='5000'),types.SimpleNamespace(stdout='5000')]),patch.object(u,'read',return_value=b'changed'):
            with self.assertRaises(RuntimeError):u.identity()

    def test_wrong_uid_refused(self):
        with patch.object(u.sys,'platform','darwin'),patch.object(u,'run',return_value=types.SimpleNamespace(stdout='501')):
            with self.assertRaises(RuntimeError):u.identity()

    def test_other_dedicated_process_blocks_stop(self):
        with patch.object(u,'service_state',return_value={'loaded':True,'pid':1}),patch.object(u,'active_pid',return_value=1),patch.object(u,'run',return_value=types.SimpleNamespace(stdout='5000 1 1 S /usr/bin/python3 agent\n5000 2 1 S /bin/sh\n')) as run:
            with self.assertRaises(RuntimeError):u.stop_daemon()
            self.assertFalse(any(c.args[0][0]=='/bin/launchctl' for c in run.call_args_list))

    def test_only_launchd_distnoted_is_tolerated(self):
        with patch.object(u,'run',return_value=types.SimpleNamespace(stdout='5000 7 1 S /usr/sbin/distnoted agent\n')):
            u.no_other_processes()
        for row in ('5000 7 9 S /usr/sbin/distnoted agent\n','5000 7 1 S /tmp/distnoted agent\n','5000 7 1 S /usr/sbin/distnoted agent extra\n'):
            with patch.object(u,'run',return_value=types.SimpleNamespace(stdout=row)):
                with self.assertRaises(RuntimeError):u.no_other_processes()

    def test_zombies_are_not_live_workers(self):
        with patch.object(u,'run',return_value=types.SimpleNamespace(stdout='5000 1 1 S python agent\n5000 2 1 Z (sh)\n501 3 1 S other\n5000 4 1 S /usr/sbin/distnoted agent\n')):
            u.no_other_processes(1)

    def test_root_bootstrap_does_not_overwrite_different_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'installer';p.write_bytes(b'other')
            with patch.object(u,'SELF',p),patch.object(u,'trusted_directory'),patch.object(u,'read',return_value=b'other'),patch.object(u.os,'execv') as execute:
                with self.assertRaises(RuntimeError):u.bootstrap(b'approved')
                execute.assert_not_called();self.assertEqual(p.read_bytes(),b'other')

    def test_restore_prevalidation_does_not_modify_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);backup=p/'backup';backup.mkdir()
            old=b'old';new=b'new'
            (p/'mac_agent.py').write_bytes(new);(backup/'mac_agent.py').write_bytes(old)
            (backup/'manifest.json').write_text(json.dumps({'mac_agent.py':{'sha256':u.sha(old),'uid':0,'gid':0,'mode':0o444}}))
            with patch.object(u,'BASE',p),patch.object(u,'BACKUP',backup),patch.object(u,'ORIGINAL',{'mac_agent.py':u.sha(old)}),patch.object(u,'PAYLOAD',{'mac_agent.py':new}),patch.object(u,'read',side_effect=lambda p:Path(p).read_bytes()),patch.object(u,'atomic') as write:
                u.verify_restore();write.assert_not_called()
                (backup/'mac_agent.py').write_bytes(b'corrupt')
                with self.assertRaises(RuntimeError):u.verify_restore()
                write.assert_not_called()


class RestartRecovery(unittest.TestCase):
    def transaction(self, *, start_failure=False, write_failure=False):
        with tempfile.TemporaryFile() as lock:
            lock_fd=os.dup(lock.fileno())
            fake_stat=types.SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=0,st_nlink=1)
            with contextlib.ExitStack() as stack:
                def mock(name,**kw):return stack.enter_context(patch.object(u,name,**kw))
                for name in ['load_package','trusted_directory','read','identity','check_sources','preflight']:
                    mock(name)
                mock('__file__',new=str(u.SELF))
                stack.enter_context(patch.object(u.os,'getuid',return_value=0))
                stack.enter_context(patch.object(u.os,'geteuid',return_value=0))
                stack.enter_context(patch.object(u.os,'umask'))
                stack.enter_context(patch.object(u.os,'open',return_value=lock_fd))
                stack.enter_context(patch.object(u.os,'fstat',return_value=fake_stat))
                mock('workspace_guard',side_effect=contextlib.nullcontext)
                mock('prepare_backup',return_value={name:None for name in u.ORIGINAL})
                stopped=mock('stop_daemon')
                writer=mock('atomic',side_effect=[None,RuntimeError('disk error')] if write_failure else None)
                smoke=mock('selftest',return_value=['passed'])
                start=mock('start_daemon',side_effect=[RuntimeError('gateway reconnect not verified'),{'pid':14}] if start_failure else None,return_value={'pid':12})
                restore=mock('restore')
                record=mock('record')
                if start_failure or write_failure:
                    with self.assertRaises(RuntimeError):u.main('--apply')
                    restore.assert_called_once_with(strict=False)
                    self.assertEqual(start.call_args.args,(u.OLD_VERSION,))
                    self.assertEqual(record.call_args.args,('rolled_back',))
                    self.assertEqual(stopped.call_count,2)
                    if write_failure:smoke.assert_not_called()
                else:
                    u.main('--apply')
                    self.assertEqual(writer.call_count,len(u.PAYLOAD))
                    smoke.assert_called_once();restore.assert_not_called()
                    start.assert_called_once_with(u.NEW_VERSION)
                    self.assertEqual(record.call_args.args,('active',))

    def test_successful_recovery_installs_and_verifies_connection(self):
        self.transaction()

    def test_reconnect_failure_restores_original_and_restarts_old_version(self):
        self.transaction(start_failure=True)

    def test_partial_write_failure_restores_original_before_starting(self):
        self.transaction(write_failure=True)

    def test_delayed_bootout_waits_for_job_and_processes(self):
        states=[{'loaded':True,'pid':12},{'loaded':True,'pid':12},
                {'loaded':True,'pid':None},{'loaded':False,'pid':None}]
        with patch.object(u,'service_state',side_effect=states),patch.object(u,'active_pid',return_value=12),patch.object(u,'no_other_processes') as processes,patch.object(u,'run') as run,patch.object(u.time,'sleep') as sleep:
            u.stop_daemon()
        self.assertEqual(sleep.call_count,2)
        self.assertEqual(processes.call_args_list,[unittest.mock.call(12),unittest.mock.call()])
        run.assert_called_once_with(['/bin/launchctl','bootout','system/'+u.LABEL],30)

    def test_already_unloaded_daemon_needs_no_bootout(self):
        with patch.object(u,'service_state',return_value={'loaded':False,'pid':None}),patch.object(u,'no_other_processes'),patch.object(u,'run') as run:
            u.stop_daemon()
        run.assert_not_called()

    def test_unloaded_job_with_lingering_process_waits(self):
        states=[{'loaded':True,'pid':12},{'loaded':False,'pid':None},{'loaded':False,'pid':None}]
        with patch.object(u,'service_state',side_effect=states),patch.object(u,'active_pid',return_value=12),patch.object(u,'no_other_processes',side_effect=[None,RuntimeError('busy'),None]),patch.object(u,'run'),patch.object(u.time,'sleep') as sleep:
            u.stop_daemon()
        sleep.assert_called_once_with(.2)

    def test_stop_timeout_does_not_claim_success(self):
        with patch.object(u,'service_state',return_value={'loaded':True,'pid':12}),patch.object(u,'active_pid',return_value=12),patch.object(u,'no_other_processes'),patch.object(u,'run'),patch.object(u.time,'monotonic',side_effect=[0,21]):
            with self.assertRaisesRegex(RuntimeError,'within 20 seconds'):u.stop_daemon()

    def test_only_explicit_missing_service_counts_as_unloaded(self):
        result=types.SimpleNamespace(returncode=113,stdout='',stderr='Could not find service "agent" in domain for system')
        with patch.object(u.subprocess,'run',return_value=result):
            self.assertEqual(u.service_state(),{'loaded':False,'pid':None})
        for code,error in [(1,'Operation not permitted'),(113,'Other failure')]:
            with self.subTest(code=code),patch.object(u.subprocess,'run',return_value=types.SimpleNamespace(returncode=code,stdout='',stderr=error)):
                with self.assertRaisesRegex(RuntimeError,'cannot inspect daemon'):u.service_state()

    def test_service_pid_is_parsed(self):
        with patch.object(u.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout='state = running\n\tpid = 123\n',stderr='')):
            self.assertEqual(u.service_state(),{'loaded':True,'pid':123})

    def test_probe_failure_prevents_bootout(self):
        with patch.object(u,'service_state',side_effect=RuntimeError('cannot inspect daemon')),patch.object(u,'run') as run:
            with self.assertRaises(RuntimeError):u.stop_daemon()
        run.assert_not_called()

    def test_loaded_without_pid_is_stopped_when_account_idle(self):
        with patch.object(u,'service_state',side_effect=[{'loaded':True,'pid':None},{'loaded':False,'pid':None}]),patch.object(u,'no_other_processes'),patch.object(u,'run') as run:
            u.stop_daemon()
        run.assert_called_once()

    def test_start_refuses_loaded_service(self):
        with patch.object(u,'service_state',return_value={'loaded':True,'pid':12}),patch.object(u,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'already loaded'):u.start_daemon(u.NEW_VERSION)
        run.assert_not_called()

    def test_reconnect_requires_fresh_correct_uid_version_and_pid(self):
        correct={'connected':True,'version':u.NEW_VERSION,'time':101,'uid':5000,'pid':12}
        readings=[dict(correct,time=99),dict(correct,version=u.OLD_VERSION),dict(correct,uid=501),dict(correct,pid=13),correct]
        with patch.object(u,'service_state',return_value={'loaded':False,'pid':None}),patch.object(u,'no_other_processes'),patch.object(u,'run'),patch.object(u.time,'time',return_value=100),patch.object(u.time,'sleep'),patch.object(u,'active_pid',return_value=12),patch.object(u,'read',side_effect=[json.dumps(r).encode() for r in readings]):
            self.assertEqual(u.start_daemon(u.NEW_VERSION),correct)

    def test_intact_original_sources_can_pass_with_service_offline(self):
        with patch.object(u,'identity'),patch.object(u,'trusted_directory'),patch.object(u,'digest',side_effect=lambda p:{**u.ORIGINAL,**u.DEPENDENCIES}[p.name]),patch.object(u,'service_state',return_value={'loaded':False,'pid':None}),patch.object(u,'no_other_processes'):
            self.assertFalse(u.check_sources()['daemon_loaded'])

    def test_existing_backup_is_never_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(u,'BACKUP',Path(tmp)),patch.object(u,'backup') as fresh:
                with self.assertRaisesRegex(RuntimeError,'backup exists'):u.prepare_backup()
                fresh.assert_not_called()
            with patch.object(u,'BACKUP',Path(tmp)/'new'),patch.object(u,'backup',return_value={'m':None}) as fresh:
                self.assertEqual(u.prepare_backup(),{'m':None})

    def test_new_modules_absent_before_and_removed_on_rollback(self):
        self.assertIsNone(u.ORIGINAL['net_proxy.py']);self.assertIsNone(u.ORIGINAL['upload_tools.py'])
        self.assertEqual(u.ORIGINAL['mac_agent.py'],'f099f621d41b17f834105393c3161cc5428681f8ddf22b07dcdafb542e6d0104')
        self.assertEqual(u.ORIGINAL['file_tools.py'],'8a830b3e4ed62fec5b28c5c600a616899c5b706547155d5ed3684a1d8309d54e')
        self.assertEqual((u.OLD_VERSION,u.NEW_VERSION),('0.11-personal-work-2','0.12-personal-1'))

    def test_v012_preflight_and_selftest_wiring(self):
        source=Path(u.__file__).read_text()
        self.assertIn("loadTestsFromNames(['test_work_core','test_search','test_v012'])",source)
        self.assertIn("TEST_CODE/'mac_v012_selftest.py'",source)
        self.assertIn('child(code,timeout=120)',source)
        for name in ('test_v012.py','mac_v012_selftest.py'):self.assertIn(name,u.TEST_NAMES)
        for name in ('net_proxy.py','upload_tools.py','mac_policy.py','mac_child.py','mac_shell.py'):self.assertIn(name,u.PAYLOAD if u.PAYLOAD else u.ORIGINAL)

    def test_smoke_receipt_takes_last_json_line(self):
        r=types.SimpleNamespace(returncode=0,stdout='noise\n{"passed": true, "uid": 5000, "checks": ["a"], "info": {"github_git_ls_remote": "ok"}}\n',stderr='')
        with patch.object(u,'child',return_value=r),patch.object(u,'atomic'),patch.object(u,'no_other_processes'):
            self.assertEqual(u.selftest(),['a'])
        self.assertEqual(u.SMOKE_INFO['github_git_ls_remote'],'ok')

if __name__=='__main__':unittest.main()
