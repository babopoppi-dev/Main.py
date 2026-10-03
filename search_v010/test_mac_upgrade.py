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
import upgrade_mac_search_v010_20261002 as u


class MacUpgrade(unittest.TestCase):
    def test_launcher_passes_exact_source_to_root_bootstrap(self):
        tokens=shlex.split((Path(__file__).parent/'Aggiorna_Ricerca_MCP_Andrea.command').read_text())
        loaders=[tokens[i+1] for i,t in enumerate(tokens) if t=='-c']
        self.assertEqual(len(loaders),2)
        self.assertEqual(loaders[0],loaders[1])
        source=(Path(__file__).parent/'upgrade_mac_search_v010_20261002.py').read_bytes()
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
        u.load_package()
        for n,b in u.PAYLOAD.items():
            self.assertEqual(b,(Path(__file__).parent/n).read_bytes())
            self.assertEqual(b,u.TESTS[n])
        for n,h in u.DEPENDENCIES.items():self.assertEqual(u.sha(u.TESTS[n]),h)

    def test_plist_change_refused_before_any_stop(self):
        with patch.object(u.sys,'platform','darwin'),patch.object(u,'run',side_effect=[
            types.SimpleNamespace(stdout='5000'),types.SimpleNamespace(stdout='5000'),types.SimpleNamespace(stdout='5000')]),patch.object(u,'read',return_value=b'changed'):
            with self.assertRaises(RuntimeError):u.identity()

    def test_wrong_uid_refused(self):
        with patch.object(u.sys,'platform','darwin'),patch.object(u,'run',return_value=types.SimpleNamespace(stdout='501')):
            with self.assertRaises(RuntimeError):u.identity()

    def test_other_dedicated_process_blocks_stop(self):
        with patch.object(u,'active_pid',return_value=1),patch.object(u,'run',return_value=types.SimpleNamespace(stdout='5000 1 S\n5000 2 S\n')) as run:
            with self.assertRaises(RuntimeError):u.stop_daemon()
            self.assertFalse(any(c.args[0][0]=='/bin/launchctl' for c in run.call_args_list))

    def test_zombies_are_not_live_workers(self):
        with patch.object(u,'run',return_value=types.SimpleNamespace(stdout='5000 1 S\n5000 2 Z\n501 3 S\n')):
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


if __name__=='__main__':unittest.main(verbosity=2)
