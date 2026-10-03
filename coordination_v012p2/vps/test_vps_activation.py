"""VPS p2 activation: header, version-based reconnection check and journal smoke."""
import hashlib
from pathlib import Path
import types
import unittest
from unittest.mock import patch
import upgrade_vps_v012p2_20261003 as u

HERE = Path(__file__).resolve().parent


class VpsP2(unittest.TestCase):
    def test_header_pins_live_r1_and_new_names(self):
        self.assertEqual(sorted(u.ORIGINAL), ['agent.py', 'file_tools.py'])
        self.assertEqual(u.ORIGINAL['file_tools.py'], 'c4e8af4bf9b6542e02c1c6c442160998125335010a2b1009becb220146a01e76')
        self.assertEqual((u.OLD_VERSION, u.NEW_VERSION), ('0.12-vps-1', '0.12-vps-2'))
        self.assertEqual(u.SELF.name, 'upgrade_vps_v012p2_20261003.py')
        self.assertEqual(u.BACKUP.name, 'pre_vps_v012p2_20261003')
        cg = hashlib.sha256((HERE.parent / 'cg_tools.py').read_bytes()).hexdigest()
        self.assertIn(cg, u.DEPENDENCIES['cg_tools.py'])

    def test_payload_is_tested_source(self):
        with patch.object(u, 'BASE', HERE.parent), \
                patch.object(u, 'read', side_effect=lambda p, owner=0: (HERE.parent / ('shell_common.py' if Path(p).name == 'isolated_shell.py' else Path(p).name)).read_bytes()):
            u.load_package()
        self.assertEqual(u.PAYLOAD['file_tools.py'], (HERE.parent / 'file_tools.py').read_bytes())
        self.assertEqual(u.PAYLOAD['agent.py'], (HERE / 'agent.py').read_bytes())
        self.assertIn(b'_journaled', u.PAYLOAD['file_tools.py'])

    def machines(self, version):
        return {'machines': [{'machine': 'vps', 'online': True,
                              'meta': {'agent_version': version, 'coordination_version': '0.11.0'}}]}

    def test_reconnect_check_uses_agent_version_both_ways(self):
        for expect_new, version in ((True, '0.12-vps-2'), (False, '0.12-vps-1')):
            with patch.object(u, 'run'), patch.object(u, 'call', return_value=self.machines(version)):
                u.restart(expect_new)
        with patch.object(u, 'run'), patch.object(u, 'call', return_value=self.machines('0.12-vps-1')), \
                patch.object(u.time, 'monotonic', side_effect=[0, 0, 100]), patch.object(u.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'reconnection'):
                u.restart(True)

    def test_smoke_checks_missing_parent_and_unit_name(self):
        source = Path(u.__file__).read_text()
        self.assertIn("'missing parent not refused cleanly'", source)
        self.assertIn("'--unit=central-mcp-vps-v012p2-20261003'", source)


if __name__ == '__main__':
    unittest.main()
