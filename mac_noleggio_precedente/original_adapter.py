#!/usr/bin/env python3
"""Read-only pilot: outbound WSS -> the existing mac_control MCP stdio server.

No local implementation of filesystem commands, shell, locks, or rollback.
Mutating operations deliberately require a later, reviewed gateway/session phase.
"""
import asyncio
import contextlib
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import random
import re
import signal
import ssl
import stat
import sys
import time
from pathlib import Path

URL = "wss://mcp.andreababini.it/agent/ws/mac_noleggio"
BASE = Path("/Users/vagrant/.mac-control-gateway/central-adapter")
SOURCE = Path("/Users/vagrant/mac_control_mcp/mac_control.py")
COORDINATION = SOURCE.with_name("mac_control_coordination.py")
MAX_REQUEST = 65536
MAX_RESPONSE = 2 * 1024 * 1024
LOG = logging.getLogger("central-adapter")


def safe_regular(path, private=False):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("absolute path required")
    for item in [path] + list(path.parents):
        if item.is_symlink():
            raise ValueError("symlink rejected")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        raise ValueError("file must belong to service user")
    if st.st_mode & (0o077 if private else 0o022):
        raise ValueError("unsafe file permissions")
    return path


def load_config(path):
    path = safe_regular(path, private=True)
    if path.parent != BASE:
        raise ValueError("configuration must be in protected adapter directory")
    cfg = json.loads(path.read_text())
    if set(cfg) != {"gateway_url", "machine", "mode", "token_file", "source_sha256", "coordination_sha256"}:
        raise ValueError("unexpected configuration keys")
    if cfg["gateway_url"] != URL or cfg["machine"] != "mac_noleggio" or cfg["mode"] != "read_only":
        raise ValueError("only the reviewed read-only endpoint is supported")
    token_path = Path(cfg["token_file"])
    if token_path != BASE / "agent.token":
        raise ValueError("unexpected token location")
    for source, key in [(SOURCE, "source_sha256"), (COORDINATION, "coordination_sha256")]:
        safe_regular(source)
        if hashlib.sha256(source.read_bytes()).hexdigest() != cfg[key]:
            raise ValueError("mac_control source changed; review required")
    return cfg


def load_token(cfg):
    token = safe_regular(cfg["token_file"], private=True).read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,256}", token):
        raise ValueError("invalid dedicated agent token")
    return token


class Backend:
    def __init__(self, argv=None, cwd=None):
        self.argv = argv or ["/usr/bin/python3", "-B", str(SOURCE)]
        self.cwd = cwd or str(SOURCE.parent)
        self.process = None
        self.counter = 0
        self.lock = asyncio.Lock()

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            *self.argv, cwd=self.cwd, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=MAX_RESPONSE, start_new_session=True,
            env={"HOME": "/Users/vagrant", "PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        await self.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                     "clientInfo": {"name": "central-adapter-readonly", "version": "0.1.0"}})
        await self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        result = await self.rpc("tools/list", {})
        names = {x["name"] for x in result.get("tools", [])}
        if not {"mac_control", "who_is_working"}.issubset(names):
            raise RuntimeError("required mac_control tools missing")

    async def send(self, obj):
        raw = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
        if len(raw) > MAX_REQUEST:
            raise ValueError("MCP request too large")
        self.process.stdin.write(raw)
        await self.process.stdin.drain()

    async def rpc(self, method, params):
        async with self.lock:
            self.counter += 1
            rid = self.counter
            await self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            try:
                line = await asyncio.wait_for(self.process.stdout.readline(), 25)
            except (asyncio.TimeoutError, ValueError):
                await self.close()
                raise RuntimeError("backend timeout or oversized response") from None
            if not line or len(line) > MAX_RESPONSE:
                raise RuntimeError("backend disconnected or oversized response")
            result = json.loads(line)
            if result.get("id") != rid or result.get("jsonrpc") != "2.0":
                raise RuntimeError("backend response mismatch")
            if "error" in result:
                raise RuntimeError("mac_control rejected request")
            return result["result"]

    async def call(self, name, args):
        data = await self.rpc("tools/call", {"name": name, "arguments": args})
        if data.get("isError"):
            raise RuntimeError("mac_control rejected request")
        text = [x["text"] for x in data.get("content", []) if x.get("type") == "text"]
        if len(text) != 1:
            raise RuntimeError("unexpected mac_control result")
        return json.loads(text[0])

    async def close(self):
        if self.process and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                await self.process.wait()


async def dispatch(backend, message):
    if not isinstance(message, dict) or message.get("type") != "request":
        raise ValueError("invalid request")
    rid = message.get("id")
    if not isinstance(rid, str) or not re.fullmatch(r"[0-9a-f]{32}", rid):
        raise ValueError("invalid request id")
    op, args = message.get("op"), message.get("args")
    if not isinstance(args, dict):
        raise ValueError("invalid arguments")
    # This ID labels an individual read request, not an authenticated human session.
    # Do not enable writes until the gateway forwards a trusted stable session ID.
    sid = "gateway-readonly:" + rid
    if op == "read_file":
        if set(args) - {"path", "max_bytes"} or not isinstance(args.get("path"), str):
            raise ValueError("invalid read arguments")
        limit = args.get("max_bytes", 512 * 1024)
        if type(limit) is not int or not 1 <= limit <= 512 * 1024:
            raise ValueError("invalid max_bytes")
        result = await backend.call("mac_control", {"action": "read", "path": args["path"], "session_id": sid})
        content = result["content"].encode("utf-8")
        result["content"] = content[:limit].decode("utf-8", errors="ignore")
        result["truncated"] = len(content) > limit
        result["bytes_returned"] = len(result["content"].encode("utf-8"))
        return result
    if op == "who_is_working" and not args:
        return await backend.call("who_is_working", {"session_id": sid})
    raise ValueError("read-only pilot: operation not enabled")


async def connection(cfg, token, backend):
    from websockets.legacy.client import connect
    # Disallow redirects: credentials must be sent only to the reviewed origin.
    from websockets.legacy.client import WebSocketClientProtocol

    class NoRedirect(WebSocketClientProtocol):
        async def handshake(self, *args, **kwargs):
            from websockets.exceptions import RedirectHandshake
            try:
                return await super().handshake(*args, **kwargs)
            except RedirectHandshake:
                raise RuntimeError("WebSocket redirect rejected") from None

    async with connect(cfg["gateway_url"], extra_headers={"Authorization": "Bearer " + token},
                       ssl=ssl.create_default_context(), create_protocol=NoRedirect,
                       open_timeout=15, close_timeout=5, ping_interval=20, ping_timeout=20,
                       max_size=MAX_RESPONSE, max_queue=8, compression=None) as ws:
        async def heartbeat():
            while True:
                await ws.send(json.dumps({"type": "hello", "meta": {
                    "platform": "darwin", "adapter": "mac_control-stdio", "mode": "read_only",
                    "full_shell_capable": False, "capabilities": ["read_file", "who_is_working"],
                    "python": sys.version.split()[0], "uid": os.getuid()}}))
                await asyncio.sleep(15)
        beat = asyncio.create_task(heartbeat())
        LOG.info("connected read_only")
        try:
            async for raw in ws:
                rid = None
                try:
                    msg = json.loads(raw)
                    rid = msg.get("id") if isinstance(msg, dict) else None
                    if not isinstance(rid, str) or not re.fullmatch(r"[0-9a-f]{32}", rid):
                        raise ValueError("invalid request id")
                    result = await dispatch(backend, msg)
                    await ws.send(json.dumps({"type": "result", "id": rid, "ok": True, "result": result}))
                    LOG.info("request_ok id=%s", rid)
                except (ValueError, RuntimeError, KeyError, TypeError):
                    if isinstance(rid, str) and re.fullmatch(r"[0-9a-f]{32}", rid):
                        await ws.send(json.dumps({"type": "result", "id": rid, "ok": False,
                                                 "error": "READ_ONLY_OR_BACKEND_REJECTED"}))
                    LOG.warning("request_rejected")
                    if backend.process.returncode is not None:
                        raise RuntimeError("backend exited")
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat


async def run(config_path):
    delay = 1
    while True:
        backend = Backend()
        started = time.monotonic()
        try:
            cfg = load_config(config_path)
            token = load_token(cfg)
            await backend.start()
            await connection(cfg, token, backend)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never log exception text, URLs, request contents or token values.
            LOG.warning("connection_ended category=%s", type(exc).__name__)
        finally:
            await backend.close()
        delay = 1 if time.monotonic() - started > 60 else min(delay * 2, 60)
        await asyncio.sleep(delay + random.uniform(0, 1))


def main():
    if sys.platform != "darwin" or os.getuid() == 0:
        raise SystemExit("requires non-root macOS user")
    if len(sys.argv) != 2:
        raise SystemExit("usage: adapter.py /absolute/config.json")
    log = RotatingFileHandler(BASE / 'logs/adapter.log', maxBytes=1024 * 1024, backupCount=3)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[log])
    lock_path = BASE / "adapter.lock"
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = loop.create_task(run(sys.argv[1]))
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        with contextlib.suppress(asyncio.CancelledError):
            loop.run_until_complete(task)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        os.close(fd)


if __name__ == "__main__":
    main()

