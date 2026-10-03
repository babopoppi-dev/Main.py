"""v0.12 Mac side: GitHub-only proxy, seatbelt policy, child environment, dispatcher.

File tool tests live in test_files_v012.py.
"""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from file_tools import FileToolError
import net_proxy
from net_proxy import GitHubProxy
import mac_policy
from mac_agent import Dispatcher


class Proxy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        async def echo(reader, writer):
            data = await reader.read(100)
            writer.write(b'echo:' + data); await writer.drain(); writer.close()
        self.upstream = await asyncio.start_server(echo, '127.0.0.1', 0)
        port = self.upstream.sockets[0].getsockname()[1]
        async def resolve(host): return ['127.0.0.1']
        self.p = GitHubProxy(log=self.events.append, resolver=resolve, port=port)
        await self.p.start()

    async def asyncTearDown(self):
        await self.p.stop(); self.upstream.close(); await self.upstream.wait_closed()

    async def request(self, head):
        r, w = await asyncio.open_connection('127.0.0.1', self.p.address())
        w.write(head); await w.drain()
        line = await r.readline()
        return r, w, line

    def auth(self, token=None):
        value = base64.b64encode(('mcp:' + (token or self.p.token)).encode())
        return b'Proxy-Authorization: Basic ' + value + b'\r\n'

    async def test_requires_credential(self):
        _, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n\r\n'); w.close()
        self.assertIn(b'407', line)
        _, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n' + self.auth('x' * 32) + b'\r\n'); w.close()
        self.assertIn(b'407', line)

    async def test_407_announces_basic_scheme_for_curl_anyauth(self):
        r, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n\r\n')
        head = await asyncio.wait_for(r.read(500), 5); w.close()
        self.assertIn(b'407', line)
        self.assertIn(b'Proxy-Authenticate: Basic', head)

    async def test_only_allowed_hosts_port_and_method(self):
        for head in [b'CONNECT example.com:443 HTTP/1.1\r\n', b'CONNECT github.com:22 HTTP/1.1\r\n',
                     b'CONNECT evilgithub.com:443 HTTP/1.1\r\n', b'CONNECT github.com.evil.com:443 HTTP/1.1\r\n']:
            _, w, line = await self.request(head + self.auth() + b'\r\n'); w.close()
            self.assertIn(b'403', line, head)
        _, w, line = await self.request(b'GET http://github.com/ HTTP/1.1\r\n' + self.auth() + b'\r\n'); w.close()
        self.assertIn(b'405', line)

    async def test_private_addresses_refused(self):
        _, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n' + self.auth() + b'\r\n'); w.close()
        self.assertIn(b'502', line)
        for a in ['127.0.0.1', '10.0.0.1', '192.168.1.1', '169.254.169.254', '::1', '::ffff:127.0.0.1']:
            self.assertFalse(net_proxy.public_address(a), a)
        self.assertTrue(net_proxy.public_address('140.82.121.4'))

    async def test_tunnel_to_allowed_host(self):
        with patch('net_proxy.public_address', return_value=True):
            r, w, line = await self.request(b'CONNECT github.com:443 HTTP/1.1\r\n' + self.auth() + b'\r\n')
            self.assertIn(b'200', line)
            await r.readline()
            w.write(b'hello'); await w.drain()
            self.assertEqual(await asyncio.wait_for(r.read(100), 5), b'echo:hello')
            w.close()

    async def test_stop_invalidates_token_and_port(self):
        port, token = self.p.address(), self.p.token
        await self.p.stop()
        self.assertIsNone(self.p.token)
        with self.assertRaises(OSError):
            await asyncio.open_connection('127.0.0.1', port)
        await self.p.start()
        self.assertNotEqual(self.p.token, token)


class Policy(unittest.TestCase):
    def setUp(self):
        self.patch = patch('mac_policy.safe_executables', return_value=['/bin/bash'])
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_offline_profile_has_no_network(self):
        text = mac_policy.profile('/Users/Shared/X/workspace')
        self.assertIn('(deny network*)', text)
        self.assertNotIn('network-outbound', text)
        self.assertNotIn('trustd', text)

    def test_network_profile_is_loopback_port_only(self):
        text = mac_policy.profile('/Users/Shared/X/workspace', net_port=50123)
        self.assertIn('(allow network-outbound (remote ip "localhost:50123"))', text)
        self.assertNotIn('(allow network*', text)
        self.assertIn('com.apple.trustd', text)
        self.assertLess(text.index('(deny network*)'), text.index('localhost:50123'))
        for bad in [80, 0, 70000, '50123']:
            with self.assertRaises(ValueError):
                mac_policy.profile('/Users/Shared/X/workspace', net_port=bad)


class TrustedTree(unittest.TestCase):
    def fake(self, modes):
        import stat as st
        def lstat(p):
            uid, mode, gid = modes.get(str(p), (0, 0o755, 0))
            return os.stat_result((st.S_IFDIR | mode, 0, 0, 0, uid, gid, 0, 0, 0, 0))
        return patch('mac_policy.Path.lstat', lambda self: lstat(self))

    def test_root_owned_tree_accepted_admin_group_write_tolerated(self):
        with self.fake({'/Applications': (0, 0o775, 80)}):
            self.assertEqual(mac_policy.trusted_tree('/Applications/Xcode.app/Contents/Developer/usr'),
                             '/Applications/Xcode.app/Contents/Developer/usr')

    def test_unsafe_trees_rejected(self):
        for bad in [(501, 0o755, 20), (0, 0o777, 0), (0, 0o775, 20)]:
            with self.fake({'/Applications/Xcode.app': bad}):
                self.assertIsNone(mac_policy.trusted_tree('/Applications/Xcode.app/Contents/Developer/usr'), bad)


class ChildEnvironment(unittest.TestCase):
    def test_git_uses_basic_proxy_auth_and_token_not_in_argv(self):
        import mac_child
        captured = {}
        def fake_exec(path, argv, env): captured.update(argv=argv, env=env)
        env = {'MCP_NET_PORT': '50123', 'MCP_NET_TOKEN': 'A' * 32}
        with patch.object(mac_child, 'require_identity'), patch.object(mac_child.resource, 'setrlimit'), \
                patch.object(mac_child.os, 'execve', side_effect=fake_exec), patch.dict(mac_child.os.environ, env, clear=True), \
                patch.object(mac_child, 'profile', return_value='(version 1)'), \
                patch.object(mac_child.sys, 'argv', ['c', '/Users/Shared/w', '/Users/Shared/w', 'git status', '/dev/ttys001']):
            mac_child.main()
        self.assertEqual(captured['env']['GIT_CONFIG_KEY_0'], 'http.proxyAuthMethod')
        self.assertEqual(captured['env']['GIT_CONFIG_VALUE_0'], 'basic')
        self.assertIn('A' * 32, captured['env']['HTTPS_PROXY'])
        self.assertNotIn('A' * 32, ' '.join(captured['argv']))

    def test_offline_child_has_no_proxy(self):
        import mac_child
        captured = {}
        with patch.object(mac_child, 'require_identity'), patch.object(mac_child.resource, 'setrlimit'), \
                patch.object(mac_child.os, 'execve', side_effect=lambda p, a, e: captured.update(env=e)), \
                patch.dict(mac_child.os.environ, {}, clear=True), patch.object(mac_child, 'profile', return_value='x') as prof, \
                patch.object(mac_child.sys, 'argv', ['c', '/Users/Shared/w', '/Users/Shared/w', 'ls', '/dev/ttys001']):
            mac_child.main()
        self.assertNotIn('HTTPS_PROXY', captured['env'])
        self.assertIsNone(prof.call_args.args[2])


class AgentV012(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); r = Path(self.tmp.name)
        self.work = r / 'work'; self.state = r / 'state'
        self.work.mkdir(mode=0o700); self.state.mkdir(mode=0o700)
        self.d = Dispatcher(self.work, self.state)
        self.a = await self.call('work_session', {'action': 'open', 'label': 'A', 'minutes': 10})
        self.b = await self.call('work_session', {'action': 'open', 'label': 'B', 'minutes': 10})

    async def asyncTearDown(self):
        await self.d.close(); self.tmp.cleanup()

    async def call(self, op, args, s=None):
        if s:
            args = {**args, **{k: s[k] for k in ['work_session_id', 'work_session_token']}}
        return await self.d.dispatch({'type': 'request', 'id': uuid.uuid4().hex, 'caller': 'test:client', 'op': op, 'args': args})

    async def test_new_mutations_require_session(self):
        (self.work / 'f').write_text('x')
        for op, args in [('delete_path', {'path': str(self.work / 'f')}),
                         ('copy_file', {'source': str(self.work / 'f'), 'destination': str(self.work / 'g')}),
                         ('upload_file', {'action': 'begin', 'path': str(self.work / 'h'), 'size': 1, 'sha256': '0' * 64})]:
            with self.assertRaises(PermissionError):
                await self.call(op, args)
        r = await self.call('read_binary', {'path': str(self.work / 'f')})
        self.assertEqual(base64.b64decode(r['content_base64']), b'x')

    async def test_upload_and_delete_through_dispatcher(self):
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10}, self.a)
        data = b'\x89PNG\r\n\x1a\n' + os.urandom(1000)
        b = await self.call('upload_file', {'action': 'begin', 'path': str(self.work / 'i.png'), 'size': len(data),
                                            'sha256': hashlib.sha256(data).hexdigest()}, self.a)
        with self.assertRaises(FileToolError):
            await self.call('upload_file', {'action': 'commit', 'upload_id': b['upload_id']}, self.b)
        await self.call('upload_file', {'action': 'chunk', 'upload_id': b['upload_id'], 'offset': 0,
                                        'data': base64.b64encode(data).decode()}, self.a)
        await self.call('upload_file', {'action': 'commit', 'upload_id': b['upload_id']}, self.a)
        self.assertEqual((self.work / 'i.png').read_bytes(), data)
        r = await self.call('delete_path', {'path': str(self.work / 'i.png')}, self.a)
        self.assertFalse((self.work / 'i.png').exists())
        await self.call('rollback_file', {'operation_id': r['operation_id']}, self.a)
        self.assertEqual((self.work / 'i.png').read_bytes(), data)

    async def test_close_drops_own_uploads(self):
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10}, self.a)
        await self.call('upload_file', {'action': 'begin', 'path': str(self.work / 'z'), 'size': 1, 'sha256': '0' * 64}, self.a)
        await self.call('work_session', {'action': 'close'}, self.a)
        self.assertEqual(self.d.uploads.jobs, {})

    async def test_enable_network_argument_validated_and_forwarded(self):
        await self.call('work_lock', {'action': 'acquire', 'path': str(self.work), 'minutes': 10}, self.a)
        with patch.object(self.d.shell, 'enable', new=AsyncMock(return_value={'enabled': True})) as m:
            await self.call('enable_full_shell', {'minutes': 1, 'network': 'github'}, self.a)
            m.assert_awaited_once_with('work:' + self.a['work_session_id'], 1, 'github')
        with self.assertRaises(ValueError):
            await self.call('enable_full_shell', {'minutes': 1, 'proxy': 'x'}, self.a)

    async def test_shell_network_lease_starts_and_stops_proxy(self):
        shell = self.d.shell; identity = 'work:' + self.a['work_session_id']
        with patch('mac_shell.require_identity'):
            with self.assertRaises(ValueError):
                await shell.enable(identity, 1, 'internet')
            r = await shell.enable(identity, 1, 'github')
            self.assertTrue(shell.proxy.running)
            self.assertIn('github', r['network'])
            env = shell.child_env()
            self.assertEqual(env['MCP_NET_PORT'], str(shell.proxy.address()))
            await shell.enable(identity, 1, 'none')
            self.assertFalse(shell.proxy.running)
            self.assertNotIn('MCP_NET_PORT', shell.child_env())
            await shell.enable(identity, 1, 'github')
            await shell.disable()
            self.assertFalse(shell.proxy.running)
            self.assertEqual(shell.network, 'none')

    async def test_metadata_advertises_new_capabilities(self):
        import mac_agent
        meta = mac_agent.metadata()
        for name in ['delete_path', 'copy_file', 'read_binary', 'upload_file']:
            self.assertIn(name, meta['capabilities'])
        self.assertIn('github.com', meta['shell_network_hosts'])


class Catalog(unittest.TestCase):
    def test_gateway_catalog_has_new_tools_with_session_fields(self):
        import cg_tools
        tools = {t['name']: t for t in cg_tools.TOOLS}
        self.assertEqual(len(tools), len(cg_tools.TOOLS))
        for name in ['delete_path', 'copy_file', 'read_binary', 'upload_file']:
            self.assertIn('work_session_id', tools[name]['inputSchema']['properties'])
        self.assertEqual(tools['enable_full_shell']['inputSchema']['properties']['network']['enum'], ['none', 'github'])
        json.dumps(cg_tools.TOOLS)


if __name__ == '__main__':
    unittest.main()
