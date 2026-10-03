"""Point F: allowlisted HTTPS egress for the isolated shell.

The seatbelt cannot filter by domain name. The shell therefore keeps
"(deny network*)" except one outbound TCP connection to this proxy on
127.0.0.1. The proxy, inside the agent (not sandboxed), accepts only
authenticated CONNECT requests to an exact allowlisted host on port 443,
resolves the name itself and refuses non-public addresses (no LAN, no
loopback, no metadata endpoints). Nothing else is relayed.
"""
import asyncio
import base64
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import time

HOST = re.compile(r'(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}')
MAX_CLIENTS = 16
IDLE = 300
HEADER_LIMIT = 8192


def load_domains(path, owner=0):
    """Root-owned {"version":1,"domains":[...]}; a missing file means no network."""
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return []
    with os.fdopen(fd, 'rb') as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != owner or st.st_mode & 0o022 or st.st_size > 16384:
            raise PermissionError('unsafe network configuration')
        cfg = json.loads(f.read(16385))
    if not isinstance(cfg, dict) or set(cfg) != {'version', 'domains'} or cfg['version'] != 1:
        raise ValueError('invalid network configuration')
    domains = cfg['domains']
    if not isinstance(domains, list) or len(domains) > 32:
        raise ValueError('invalid domain list')
    out = []
    for d in domains:
        if not isinstance(d, str) or d != d.lower() or not HOST.fullmatch(d):
            raise ValueError('domains must be exact lowercase host names: %r' % (d,))
        out.append(d)
    return sorted(set(out))


def public_address(ip):
    a = ipaddress.ip_address(ip)
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_global and not a.is_multicast


async def default_resolve(host):
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return [i[4][0] for i in infos]


class NetProxy:
    def __init__(self, domains, resolve=default_resolve, is_public=public_address, port=0):
        self.domains = frozenset(domains)
        self.resolve, self.is_public = resolve, is_public
        self.port, self.server, self.token = port, None, None
        self.upstream_port = 443  # tests only override this
        self.clients = set()
        self.log = []

    def record(self, host, ok, reason=''):
        self.log.append({'time': time.time(), 'host': host[:255], 'ok': ok, 'reason': reason})
        del self.log[:-200]

    async def start(self):
        if not self.domains:
            raise PermissionError('no network domains configured')
        self.token = secrets.token_urlsafe(24)
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', self.port)
        self.port = self.server.sockets[0].getsockname()[1]
        return {'port': self.port, 'url': 'http://mcp:%s@127.0.0.1:%d' % (self.token, self.port),
                'domains': sorted(self.domains)}

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        for task in list(self.clients):
            task.cancel()
        for task in list(self.clients):
            try:
                await task
            except BaseException:
                pass
        self.token = None

    def authorized(self, headers):
        value = headers.get('proxy-authorization', '')
        if not value.lower().startswith('basic ') or not self.token:
            return False
        try:
            user, _, password = base64.b64decode(value[6:].strip(), validate=True).decode().partition(':')
        except Exception:
            return False
        return user == 'mcp' and hmac.compare_digest(password, self.token)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        if len(self.clients) >= MAX_CLIENTS:
            writer.close()
            return
        self.clients.add(task)
        host = '?'
        try:
            head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 15)
            if len(head) > HEADER_LIMIT:
                raise ValueError('header too large')
            lines = head.decode('latin-1').split('\r\n')
            parts = lines[0].split(' ')
            headers = {}
            for line in lines[1:]:
                if ':' in line:
                    k, v = line.split(':', 1)
                    headers[k.strip().lower()] = v.strip()
            if len(parts) != 3 or parts[0] != 'CONNECT':
                return await self.refuse(writer, host, 405, 'only CONNECT')
            host, _, port = parts[1].rpartition(':')
            host = host.lower()
            if not self.authorized(headers):
                return await self.refuse(writer, host, 407, 'proxy authentication')
            if port != '443' or host not in self.domains:
                return await self.refuse(writer, host, 403, 'not allowlisted')
            addresses = [a for a in await self.resolve(host)]
            if not addresses or not all(self.is_public(a) for a in addresses):
                return await self.refuse(writer, host, 403, 'non-public address')
            upstream_r, upstream_w = await asyncio.wait_for(asyncio.open_connection(addresses[0], self.upstream_port), 15)
            writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
            await writer.drain()
            self.record(host, True)
            await asyncio.gather(self.pipe(reader, upstream_w), self.pipe(upstream_r, writer))
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ValueError, OSError) as exc:
            self.record(host, False, type(exc).__name__)
        finally:
            self.clients.discard(task)
            writer.close()

    async def refuse(self, writer, host, code, reason):
        self.record(host, False, reason)
        writer.write(b'HTTP/1.1 %d %s\r\nContent-Length: 0\r\nConnection: close\r\n\r\n' % (code, reason.encode()))
        await writer.drain()

    @staticmethod
    async def pipe(src, dst):
        try:
            while True:
                data = await asyncio.wait_for(src.read(65536), IDLE)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except (asyncio.TimeoutError, OSError):
            pass
        finally:
            try:
                dst.close()
            except Exception:
                pass
