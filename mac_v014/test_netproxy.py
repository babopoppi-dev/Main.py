"""Point F proxy: only authenticated CONNECT to exact allowlisted hosts with public addresses."""
import asyncio
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest

from mac_netproxy import NetProxy, load_domains, public_address


class Domains(unittest.TestCase):
    def test_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'network.json'
            self.assertEqual(load_domains(p), [])
            p.write_text(json.dumps({'version': 1, 'domains': ['github.com', 'pypi.org']}))
            self.assertEqual(load_domains(p, owner=os.getuid()), ['github.com', 'pypi.org'])
            for bad in (['*.github.com'], ['GitHub.com'], ['github.com:443'], ['localhost'], ['10.0.0.1']):
                p.write_text(json.dumps({'version': 1, 'domains': bad}))
                with self.assertRaises(ValueError, msg=bad):
                    load_domains(p, owner=os.getuid())
            os.chmod(p, 0o666)
            with self.assertRaises(PermissionError):
                load_domains(p, owner=os.getuid())

    def test_public_address(self):
        for ip in ('127.0.0.1', '10.1.2.3', '192.168.1.1', '169.254.169.254', '::1', '::ffff:10.0.0.1', 'fd00::1', '224.0.0.1'):
            self.assertFalse(public_address(ip), ip)
        for ip in ('140.82.121.4', '2606:50c0:8000::153'):
            self.assertTrue(public_address(ip), ip)


class Proxy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def echo(r, w):
            data = await r.read(100)
            w.write(b'UP:' + data); await w.drain(); w.close()
        self.up = await asyncio.start_server(echo, '127.0.0.1', 0)
        self.addresses = {'github.com': ['127.0.0.1'], 'evil.example': ['127.0.0.1'], 'lan.github.com': ['10.0.0.5']}
        async def resolve(host):
            return self.addresses.get(host, [])
        self.p = NetProxy(['github.com', 'lan.github.com'], resolve=resolve,
                          is_public=lambda ip: ip == '127.0.0.1')
        info = await self.p.start()
        self.p.upstream_port = self.up.sockets[0].getsockname()[1]
        self.port, self.token = info['port'], self.p.token

    async def asyncTearDown(self):
        await self.p.stop(); self.up.close(); await self.up.wait_closed()

    async def request(self, line, token=True):
        r, w = await asyncio.open_connection('127.0.0.1', self.port)
        auth = 'Proxy-Authorization: Basic %s\r\n' % base64.b64encode(('mcp:' + (self.token if token is True else token)).encode()).decode() if token else ''
        w.write((line + '\r\n' + auth + '\r\n').encode()); await w.drain()
        status = (await r.readline()).decode()
        if ' 200 ' in status:
            await r.readline()
            w.write(b'hello'); await w.drain()
            body = await r.read(100)
        else:
            body = b''
        w.close()
        return status, body

    async def test_allowed_connect_relays(self):
        status, body = await self.request('CONNECT github.com:443 HTTP/1.1')
        self.assertIn(' 200 ', status); self.assertEqual(body, b'UP:hello')

    async def test_refusals(self):
        cases = [('CONNECT evil.example:443 HTTP/1.1', True, ' 403 '),
                 ('CONNECT github.com:22 HTTP/1.1', True, ' 403 '),
                 ('CONNECT lan.github.com:443 HTTP/1.1', True, ' 403 '),
                 ('GET http://github.com/ HTTP/1.1', True, ' 405 '),
                 ('CONNECT github.com:443 HTTP/1.1', None, ' 407 '),
                 ('CONNECT github.com:443 HTTP/1.1', 'wrong', ' 407 ')]
        for line, token, code in cases:
            status, body = await self.request(line, token)
            self.assertIn(code, status, line)
            self.assertEqual(body, b'')
        self.assertEqual(sum(1 for x in self.p.log if x['ok']), 0)

    async def test_no_domains_no_proxy(self):
        with self.assertRaises(PermissionError):
            await NetProxy([]).start()

    async def test_stop_revokes_token(self):
        await self.p.stop()
        with self.assertRaises(OSError):
            await asyncio.open_connection('127.0.0.1', self.port)


if __name__ == '__main__':
    unittest.main()
