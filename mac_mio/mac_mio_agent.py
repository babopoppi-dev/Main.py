#!/usr/bin/env python3
"""Outbound MCP Andrea agent: bounded file workspace and fixed system status.

No arbitrary shell, sudo, credential transfer, or modification of older agents.
"""
import asyncio
import contextlib
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import stat
import subprocess
import sys
import time

from file_tools import FileTools

BASE = Path('/Users/babo/Library/Application Support/MCPAndrea')
WORK = Path('/Users/babo/MCPAndreaWorkspace')
URL = 'wss://mcp.andreababini.it/agent/ws/mac_mio'
LOG = logging.getLogger('mcp-andrea-mac-mio')
CALLER_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}')
FILE_OPS = {'read_file', 'read_multiple_files', 'write_file', 'edit_block',
            'create_directory', 'list_directory', 'move_file', 'get_file_info', 'rollback_file'}


def private_file(path):
    for p in [path] + list(path.parents):
        if p.is_symlink():
            raise ValueError('symlink in private path')
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError('private agent-owned file required')
    return path


class Dispatcher:
    def __init__(self, root, state):
        self.engine = FileTools([str(root)], str(state))
        self.recent = []

    async def dispatch(self, message):
        if not isinstance(message, dict) or message.get('type') != 'request':
            raise ValueError('invalid request')
        caller = message.get('caller')
        if not isinstance(caller, str) or not CALLER_RE.fullmatch(caller):
            raise ValueError('trusted gateway caller required')
        op, args = message.get('op'), message.get('args')
        if not isinstance(args, dict):
            raise ValueError('invalid arguments')
        try:
            if op in FILE_OPS:
                if op == 'read_file' and 'max_bytes' in args:
                    if set(args) - {'path', 'max_bytes'}:
                        raise ValueError('unexpected read arguments')
                    limit = args['max_bytes']
                    if type(limit) is not int or not 1 <= limit <= 1048576:
                        raise ValueError('invalid read size')
                    data, _ = self.engine._read(args['path'])
                    self.engine._text(data)
                    return {'path': args['path'], 'content': data[:limit].decode('utf-8', errors='replace'),
                            'bytes_returned': min(limit, len(data)), 'truncated': len(data) > limit}
                return self.engine.dispatch(op, args, caller)
            if op == 'shell_exec':
                if set(args) - {'command', 'cwd', 'timeout'} or args.get('command') not in ('sw_vers', '/usr/bin/sw_vers'):
                    raise PermissionError('full shell disabled; only sw_vers is enabled')
                if args.get('cwd') not in (None, str(WORK)):
                    raise ValueError('invalid cwd')
                proc = await asyncio.create_subprocess_exec('/usr/bin/sw_vers',
                    stdin=subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT, env={'PATH': '/usr/bin:/bin'},
                    start_new_session=True)
                try:
                    out, _ = await asyncio.wait_for(proc.communicate(), 10)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    await proc.wait()
                    raise RuntimeError('system status timed out')
                return {'exit_code': proc.returncode, 'output': out[:65536].decode(errors='replace'),
                        'timed_out': False, 'truncated': len(out) > 65536}
            if op == 'disable_full_shell' and not args:
                return {'enabled': False}
            if op in ('enable_full_shell', 'shell_session'):
                raise PermissionError('full shell is not installed on mac_mio')
            if op == 'who_is_working' and not args:
                return {'active_locks': [], 'recent_operations': self.recent[-20:],
                        'coordination': 'single agent process; serialized file journal; per-request locks',
                        'limitation': 'OAuth family identity does not distinguish separate chats'}
            raise ValueError('unsupported operation')
        finally:
            self.recent.append({'time': time.time(), 'caller': caller, 'operation': str(op)[:64]})
            del self.recent[:-100]


def metadata():
    return {'hostname': socket.gethostname(), 'platform': 'darwin', 'python': sys.version.split()[0],
            'uid': os.getuid(), 'full_shell_capable': False, 'machine': 'mac_mio',
            'mode': 'workspace_files_and_system_status', 'allowed_roots': [str(WORK)],
            'capabilities': sorted(FILE_OPS | {'shell_exec', 'who_is_working', 'disable_full_shell'}),
            'baseline_shell_commands': ['sw_vers']}


async def connection(dispatcher):
    from websockets.legacy.client import connect, WebSocketClientProtocol
    from websockets.exceptions import RedirectHandshake

    class NoRedirect(WebSocketClientProtocol):
        async def handshake(self, *args, **kwargs):
            try:
                return await super().handshake(*args, **kwargs)
            except RedirectHandshake:
                raise RuntimeError('redirect rejected') from None

    token = private_file(BASE / 'agent.token').read_text().strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise ValueError('invalid credential')
    async with connect(URL, extra_headers={'Authorization': 'Bearer ' + token},
                       ssl=ssl.create_default_context(), create_protocol=NoRedirect,
                       open_timeout=15, close_timeout=5, ping_interval=20, ping_timeout=20,
                       max_size=2*1024*1024, max_queue=8, compression=None) as ws:
        async def beat():
            while True:
                await ws.send(json.dumps({'type': 'hello', 'meta': metadata()}))
                await asyncio.sleep(15)
        heartbeat = asyncio.create_task(beat())
        try:
            LOG.info('connected')
            async for raw in ws:
                rid = None
                try:
                    msg = json.loads(raw)
                    rid = msg.get('id') if isinstance(msg, dict) else None
                    if not isinstance(rid, str) or not re.fullmatch(r'[a-f0-9]{32}', rid):
                        raise ValueError('invalid request id')
                    result = await dispatcher.dispatch(msg)
                    reply = {'type': 'result', 'id': rid, 'ok': True, 'result': result}
                    LOG.info('request id=%s caller=%s op=%s outcome=ok', rid, msg.get('caller'), msg.get('op'))
                except Exception as exc:
                    if not rid or not re.fullmatch(r'[a-f0-9]{32}', rid):
                        continue
                    reply = {'type': 'result', 'id': rid, 'ok': False,
                             'error': type(exc).__name__ + ': ' + str(exc)[:400]}
                    LOG.info('request id=%s outcome=rejected category=%s', rid, type(exc).__name__)
                await ws.send(json.dumps(reply))
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat


async def run():
    dispatcher = Dispatcher(WORK, BASE / 'operations')
    try:
        while True:
            try:
                await connection(dispatcher)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOG.warning('connection ended category=%s', type(exc).__name__)
            await asyncio.sleep(5)
    finally:
        dispatcher.engine.close()


def main():
    if sys.platform != 'darwin' or os.getuid() == 0:
        raise SystemExit('non-root macOS required')
    os.umask(0o077)
    fd = os.open(str(BASE / 'agent.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    log = RotatingFileHandler(BASE / 'agent.log', maxBytes=1048576, backupCount=3)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[log])
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = loop.create_task(run())
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        with contextlib.suppress(asyncio.CancelledError):
            loop.run_until_complete(task)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        os.close(fd)


if __name__ == '__main__':
    main()
