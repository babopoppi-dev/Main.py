"""configura_mac.py: plan only without --applica, validation through the agent loaders, symmetric ACLs."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import configura_mac as c


class Configure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.code = Path(self.tmp.name) / 'code'
        self.code.mkdir()
        here = Path(__file__).parent
        for n in ('mac_netproxy.py', 'mac_projects.py'):
            shutil.copy(here / n, self.code / n)
        self.p = patch.object(c, 'CODE', self.code)
        self.p.start()

    def tearDown(self):
        self.p.stop(); self.tmp.cleanup()

    def out(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            c.main(list(argv))
        return buf.getvalue()

    def test_network_plan_does_not_write(self):
        text = self.out('rete', 'github.com', 'pypi.org')
        self.assertIn('PIANO', text); self.assertIn('kickstart', text)
        self.assertFalse((self.code / 'network.json').exists())
        with self.assertRaises(ValueError):
            self.out('rete', '*.github.com')

    def test_network_apply_writes_valid_root_file(self):
        with patch.object(c.os, 'geteuid', return_value=0), patch.object(c.os, 'chown'), patch.object(c, 'run') as run:
            self.out('rete', 'github.com', '--applica')
        data = json.loads((self.code / 'network.json').read_text())
        self.assertEqual(data, {'version': 1, 'domains': ['github.com']})
        self.assertEqual(run.call_args.args[0][:3], ['/bin/launchctl', 'kickstart', '-k'])

    def test_projects_rejected_before_any_acl(self):
        with patch.object(c, 'run') as run:
            with self.assertRaises(ValueError):
                self.out('progetti', '/Users/babo/Bitcoin:ro')
            run.assert_not_called()

    def test_acl_commands_symmetric_and_keep_shared_ancestors(self):
        a, b = ('/Users/babo/Dev/A', 'rw'), ('/Users/babo/Dev/B', 'ro')
        grant = c.acl_commands([a, b], True)
        self.assertEqual(grant[0], ['/bin/chmod', '+a', 'mcp_andrea allow search', '/Users/babo'])
        self.assertIn(['/bin/chmod', '-R', '+a', 'mcp_andrea allow ' + c.ACE['rw'], a[0]], grant)
        self.assertEqual(sum(1 for x in grant if x[-1] == '/Users/babo/Dev'), 1)
        revoke = c.acl_commands([a], False, keep=[b])
        self.assertEqual(revoke, [['/bin/chmod', '-R', '-a', 'mcp_andrea allow ' + c.ACE['rw'], a[0]]])
        revoke_all = c.acl_commands([a], False)
        self.assertEqual(revoke_all[-1], ['/bin/chmod', '-a', 'mcp_andrea allow search', '/Users/babo'])


if __name__ == '__main__':
    unittest.main()
