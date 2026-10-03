"""GitHub-only HTTPS CONNECT proxy for the isolated shell.

Seatbelt cannot filter by host name, so the shell may reach only this proxy on
loopback. The proxy runs inside the agent (outside the sandbox), demands a
random per-lease credential, tunnels TLS on port 443 to an exact host list and
refuses addresses that are not public. It never sees decrypted traffic.
"""
import asyncio
import base64
import contextlib
import hmac
import ipaddress
import re
import secrets
import socket
import time

ALLOWED_HOSTS = frozenset({
    'github.com', 'api.github.com', 'codeload.github.com',
    'objects.githubusercontent.com', 'raw.githubusercontent.com',
})
REQUEST = re.compile(rb'CONNECT ([a-z0-9.-]{1,253}):([0-9]{1,5}) HTTP/1\.[01]\r\n')


def public_address(address):
    ip = ipaddress.ip_address(address)
    if getattr(ip, 'ipv4_mapped', None):
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class GitHubProxy:
    MAX_CONNECTIONS = 16
    HEAD_LIMIT = 8192
    IDLE_SECONDS = 120
    MAX_TUNNEL_BYTES = 1024 * 1024 * 1024

    def __init__(self, log=None, resolver=None, hosts=ALLOWED_HOSTS, port=443):
        self.log = log or (lambda event: None)
        self.resolver = resolver
        self.hosts, self.port = frozenset(hosts), port
        self.server = None
        self.token = None
        self.tasks = set()
        self.stats = {'accepted': 0, 'refused': 0}

    @property
    def running(self):
        return self.server is not None

    def address(self):
        return self.server.sockets[0].getsockname()[1]

    def proxy_url(self):
        return 'http://mcp:%s@127.0.0.1:%d' % (self.token, self.address())

    async def start(self):
        if self.server is not None:
            return self.address()
        self.token = secrets.token_urlsafe(24)
        self.stats = {'accepted': 0, 'refused': 0}
        self.server = await asyncio.start_server(self._client, '127.0.0.1', 0, limit=self.HEAD_LIMIT)
        return self.address()

    async def stop(self):
        server, self.server, self.token = self.server, None, None
        if server is not None:
            server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(server.wait_closed(), 3)
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    def _authorized(self, head):
        expected = 'Basic ' + base64.b64encode(('mcp:' + (self.token or '')).encode()).decode()
        for line in head.split(b'\r\n')[1:]:
            name, _, value = line.partition(b':')
            if name.strip().lower() == b'proxy-authorization':
                return self.token is not None and hmac.compare_digest(value.strip().decode('latin-1'), expected)
        return False

    async def _resolve(self, host):
        if self.resolver:
            return await self.resolver(host)
        infos = await asyncio.get_running_loop().getaddrinfo(host, self.port, type=socket.SOCK_STREAM)
        return [info[4][0] for info in infos]

    async def _client(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        host = None
        try:
            if len(self.tasks) > self.MAX_CONNECTIONS:
                return await self._refuse(writer, b'429 Too Many Connections', 'capacity', None)
            try:
                head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
                return await self._refuse(writer, b'400 Bad Request', 'malformed', None)
            match = REQUEST.match(head)
            if not match:
                return await self._refuse(writer, b'405 Method Not Allowed', 'method', None)
            if not self._authorized(head):
                return await self._refuse(writer, b'407 Proxy Authentication Required', 'auth', None)
            host, port = match.group(1).decode(), int(match.group(2))
            if host not in self.hosts or port != 443:
                return await self._refuse(writer, b'403 Forbidden', 'host', host)
            addresses = [a for a in await self._resolve(host) if public_address(a)]
            if not addresses:
                return await self._refuse(writer, b'502 Bad Gateway', 'address', host)
            up_reader, upstream = await asyncio.wait_for(
                asyncio.open_connection(addresses[0], self.port), 15)
            writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            await writer.drain()
            self.stats['accepted'] += 1
            started = time.monotonic()
            budget = [self.MAX_TUNNEL_BYTES]
            await asyncio.gather(self._pipe(reader, upstream, budget),
                                 self._pipe(up_reader, writer, budget))
            self.log({'event': 'tunnel', 'host': host, 'seconds': round(time.monotonic() - started, 1),
                      'bytes': self.MAX_TUNNEL_BYTES - budget[0]})
        except (OSError, asyncio.TimeoutError) as exc:
            self.log({'event': 'tunnel_error', 'host': host, 'error': type(exc).__name__})
        finally:
            self.tasks.discard(task)
            for w in (upstream, writer):
                if w is not None:
                    with contextlib.suppress(Exception):
                        w.close()

    async def _refuse(self, writer, status, reason, host):
        self.stats['refused'] += 1
        self.log({'event': 'refused', 'reason': reason, 'host': host})
        # curl (git) probes without credentials first and needs the scheme.
        extra = b'Proxy-Authenticate: Basic realm="mcp"\r\n' if status.startswith(b'407') else b''
        with contextlib.suppress(Exception):
            writer.write(b'HTTP/1.1 ' + status + b'\r\n' + extra + b'Connection: close\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()

    async def _pipe(self, reader, writer, budget):
        try:
            while True:
                data = await asyncio.wait_for(reader.read(65536), self.IDLE_SECONDS)
                if not data:
                    break
                budget[0] -= len(data)
                if budget[0] < 0:
                    break
                writer.write(data)
                await writer.drain()
        except (OSError, asyncio.TimeoutError):
            pass
        finally:
            with contextlib.suppress(Exception):
                if writer.can_write_eof():
                    writer.write_eof()
