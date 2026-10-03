"""Point F wiring: seatbelt rules, child environment, proxy bound to the shell lease."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import uuid

import mac_policy
import mac_child
from mac_shell import MacShell
from agent_shell import AgentShell


class Policy(unittest.TestCase):
    def rules(self, port=None):
        with patch.object(mac_policy, 'safe_executables', return_value=['/bin/bash']):
            return mac_policy.profile('/Users/Shared/MCPAndreaMacMio/workspace', None, port)

    def test_offline_by_default(self):
        r = self.rules()
        self.assertIn('(deny network*)', r)
        self.assertNotIn('network-outbound', r)
        self.assertIn('(deny mach-lookup)', r)

    def test_proxy_only(self):
        r = self.rules(18443)
        self.assertIn('(allow network-outbound (remote tcp "localhost:18443"))', r)
        self.assertEqual(r.count('network-outbound'), 1)
        self.assertNotIn('network-inbound', r)
        self.assertIn('(global-name "com.apple.trustd")', r)
        for bad in (80, 70000, '18443', True):
            with self.assertRaises(ValueError):
                self.rules(bad)


class Child(unittest.TestCase):
    def run_child(self, spec):
        calls = []
        env = {'MCP_PROXY': spec} if spec is not None else {}
        argv = ['mac_child.py', '/Users/x/w', '/Users/x/w', 'git pull', '/dev/ttys001']
        with patch.object(mac_child, 'require_identity'), patch.object(mac_child.resource, 'setrlimit'), \
             patch.object(mac_child, 'profile', side_effect=lambda w, t, p: 'PROFILE:%s' % p), \
             patch.object(mac_child.os, 'execve', side_effect=lambda *a: calls.append(a)), \
             patch.dict(os.environ, env, clear=True), patch.object(sys, 'argv', argv):
            mac_child.main()
        return calls[0]

    def test_no_proxy(self):
        path, argv, env = self.run_child(None)
        self.assertIn('PROFILE:None', argv)
        self.assertNotIn('HTTPS_PROXY', env)

    def test_proxy_env(self):
        token = 'a' * 32
        path, argv, env = self.run_child('18443:' + token)
        self.assertIn('PROFILE:18443', argv)
        self.assertEqual(env['HTTPS_PROXY'], 'http://mcp:%s@127.0.0.1:18443' % token)
        self.assertNotIn(token, ' '.join(argv))

    def test_bad_spec(self):
        with self.assertRaises(SystemExit):
            self.run_child('80:x')


class Lease(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from file_tools import FileTools
        self.tmp = tempfile.TemporaryDirectory()
        b = Path(self.tmp.name)
        (b / 'w').mkdir(); (b / 'logs').mkdir()
        self.files = FileTools([str(b / 'w')], str(b / 'state'))
        self.shell = AgentShell(self.files, str(b / 'w'), str(b / 'logs'), capable=True)
        self.p = patch.object(MacShell, 'enable', new=AsyncMock(return_value={'enabled': True}))
        self.p.start()

    async def asyncTearDown(self):
        await self.shell.stop_proxy(); self.p.stop(); self.files.close(); self.tmp.cleanup()

    async def test_network_needs_domains(self):
        with self.assertRaises(PermissionError):
            await self.shell.enable('work:' + 'a' * 32, 5, True)
        r = await self.shell.enable('work:' + 'a' * 32, 5)
        self.assertEqual(r['network'], 'disabled')
        self.assertNotIn('MCP_PROXY', self.shell.child_env())

    async def test_proxy_follows_lease(self):
        self.shell.domains = ('github.com',)
        r = await self.shell.enable('work:' + 'a' * 32, 5, True)
        self.assertEqual((r['network'], r['network_domains']), ('allowlist proxy', ['github.com']))
        spec = self.shell.child_env()['MCP_PROXY']
        port, token = spec.split(':')
        self.assertEqual(int(port), self.shell.proxy.port)
        await self.shell.enable('work:' + 'a' * 32, 5, False)
        self.assertIsNone(self.shell.proxy)
        await self.shell.enable('work:' + 'a' * 32, 5, True)
        with patch.object(MacShell, 'disable', new=AsyncMock(return_value={})):
            await self.shell.disable()
        self.assertIsNone(self.shell.proxy)
        self.assertNotIn('MCP_PROXY', self.shell.child_env())


if __name__ == '__main__':
    unittest.main()
