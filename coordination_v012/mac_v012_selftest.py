"""UID5000 v0.12 smoke test, only while the central Mac daemon is stopped.

Covers the v0.11 coordination checks, the new reversible file tools, and the
real seatbelt behaviour of the shell child with and without the GitHub lease.
"""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import pty
import subprocess
import sys
import time
import uuid
sys.path.insert(0, '/Library/MCPAndreaMacMioV09/code')
from mac_agent import Dispatcher, WORK, CODE
from mac_guard import require_identity, stop_dedicated_children
from net_proxy import GitHubProxy

PROBE = r"""
import base64, os, socket, sys
port = int(sys.argv[1]); token = sys.argv[2]
def attempt(addr):
    try:
        s = socket.create_connection(addr, 3)
    except OSError as e:
        return 'blocked:' + type(e).__name__
    return s
s = attempt(('127.0.0.1', port))
if isinstance(s, str):
    print('PROXY', s)
else:
    auth = base64.b64encode(('mcp:' + token).encode())
    s.sendall(b'CONNECT example.com:443 HTTP/1.1\r\nProxy-Authorization: Basic ' + auth + b'\r\n\r\n')
    print('PROXY', s.recv(64).split(b'\r\n')[0].decode())
d = attempt(('1.1.1.1', 443))
print('DIRECT', d if isinstance(d, str) else 'open')
"""


def sandboxed(command, cwd, proxy=None, timeout=30):
    """Run through the real mac_child exactly as the shell does.

    Blocking: call it in a worker thread so the proxy keeps serving the loop.
    """
    master, slave = pty.openpty()
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
    if proxy:
        env.update(MCP_NET_PORT=str(proxy.address()), MCP_NET_TOKEN=proxy.token)
    proc = subprocess.Popen([sys.executable, '-I', '-B', str(CODE / 'mac_child.py'), str(WORK), cwd,
                             command, os.ttyname(slave)], stdin=slave, stdout=slave, stderr=slave,
                            close_fds=True, start_new_session=True, cwd=cwd, env=env)
    os.close(slave)
    os.set_blocking(master, False)
    output = bytearray(); end = time.monotonic() + timeout
    try:
        while time.monotonic() < end:
            try:
                chunk = os.read(master, 65536)
                if chunk:
                    output.extend(chunk)
            except BlockingIOError:
                pass
            except OSError:
                break
            if proc.poll() is not None:
                with __import__('contextlib').suppress(OSError):
                    output.extend(os.read(master, 65536))
                break
            time.sleep(.05)
        else:
            proc.kill()
    finally:
        os.close(master)
        if proc.poll() is None:
            proc.kill()
        proc.wait(5)
        stop_dedicated_children()
    return proc.returncode, output.decode(errors='replace')


def lines(text, key):
    return [l.split(None, 1)[1].strip() for l in text.splitlines() if l.startswith(key + ' ')]


async def main():
    require_identity(); d = Dispatcher(); operations = []; checks = []; sessions = []; info = {}
    caller = 'deployment:coordination-v012'
    async def call(op, s=None, **args):
        if s: args.update(work_session_id=s['work_session_id'], work_session_token=s['work_session_token'])
        return await d.dispatch({'type': 'request', 'id': uuid.uuid4().hex, 'caller': caller, 'op': op, 'args': args})
    async def refused(op, s=None, **args):
        try: await call(op, s, **args)
        except PermissionError: return
        raise AssertionError(op + ' was not refused')
    folder = str(WORK / ('v012_selftest_' + uuid.uuid4().hex))
    proxy = GitHubProxy()
    try:
        a = await call('work_session', action='open', label='selftest A', minutes=5); sessions.append(a)
        b = await call('work_session', action='open', label='selftest B', minutes=5); sessions.append(b)
        await refused('create_directory', a, path=folder)
        await refused('create_directory', path=folder)
        checks.append('writes need session and lock')
        lock = await call('work_lock', a, action='acquire', path=folder, minutes=5)
        await refused('work_lock', b, action='acquire', path=folder + '/x', minutes=5)
        checks.append('descendant conflict between sessions')
        operations.append((await call('create_directory', a, path=folder))['operation_id'])
        path = folder + '/prova.txt'
        operations.append((await call('write_file', a, path=path, content='MCP_V012_MAC_OK\n'))['operation_id'])
        await refused('write_file', b, path=path, content='other')
        await refused('rollback_file', b, operation_id=operations[-1])
        checks.append('foreign write and rollback refused')
        r = await call('start_search', a, path=folder, pattern='MCP_V012_MAC_OK')
        await asyncio.wait_for(d.search.jobs[r['search_id']]['task'], 5)
        await refused('get_more_search_results', b, search_id=r['search_id'])
        assert (await call('get_more_search_results', a, search_id=r['search_id']))['total_results'] == 1
        checks.append('search private to its session')

        data = bytes(range(256)) * 300
        up = await call('upload_file', a, action='begin', path=folder + '/blob.bin', size=len(data),
                        sha256=hashlib.sha256(data).hexdigest())
        await refused('upload_file', b, action='begin', path=folder + '/b.bin', size=1, sha256='0' * 64)
        await call('upload_file', a, action='chunk', upload_id=up['upload_id'], offset=0,
                   data=base64.b64encode(data).decode())
        operations.append((await call('upload_file', a, action='commit', upload_id=up['upload_id']))['operation_id'])
        got = await call('read_binary', path=folder + '/blob.bin')
        assert got['sha256'] == hashlib.sha256(data).hexdigest() and got['size'] == len(data), got
        checks.append('verified binary upload and read')
        await call('create_directory', a, path=folder + '/albero/sotto')
        await call('write_file', a, path=folder + '/albero/sotto/f.txt', content='albero')
        operations.append((await call('copy_file', a, source=folder + '/albero', destination=folder + '/copia'))['operation_id'])
        assert Path(folder + '/copia/sotto/f.txt').read_text() == 'albero'
        removed = await call('delete_path', a, path=folder + '/albero')
        assert not Path(folder + '/albero').exists()
        await refused('rollback_file', b, operation_id=removed['operation_id'])
        await call('rollback_file', a, operation_id=removed['operation_id'])
        assert Path(folder + '/albero/sotto/f.txt').read_text() == 'albero'
        removed = await call('delete_path', a, path=folder + '/albero')
        checks.append('copy and delete trees with rollback')

        state = await call('who_is_working')
        assert any(l['lock_id'] == lock['lock_id'] for l in state['work_locks']), state
        assert a['work_session_token'] not in json.dumps(state), 'token leaked'
        checks.append('who_is_working lists lock without tokens')
        r = await call('shell_exec', command='sw_vers')
        assert r['exit_code'] == 0 and not r['timed_out'], r
        checks.append('baseline sw_vers without session')

        code, out = await asyncio.to_thread(sandboxed, '/usr/bin/true', folder)
        assert code == 0, out
        checks.append('offline seatbelt profile with developer tools compiles')
        await proxy.start()
        script = folder + '/net_probe.py'
        Path(script).write_text(PROBE)
        probe = '%s -I -B %s %d %s' % (os.path.realpath(sys.executable), script, proxy.address(), proxy.token)
        code, out = await asyncio.to_thread(sandboxed, probe, folder, proxy)
        info['network_probe'] = out[-600:]
        assert lines(out, 'PROXY') == ['HTTP/1.1 403 Forbidden'], out
        assert lines(out, 'DIRECT') and lines(out, 'DIRECT')[0].startswith('blocked'), out
        checks.append('network lease: only the proxy port, non-GitHub host refused, direct internet blocked')
        code, out = await asyncio.to_thread(sandboxed, probe, folder, None)
        assert lines(out, 'PROXY') and lines(out, 'PROXY')[0].startswith('blocked'), out
        assert lines(out, 'DIRECT')[0].startswith('blocked'), out
        checks.append('offline shell cannot reach the proxy or internet')
        code, out = await asyncio.to_thread(sandboxed, '/usr/bin/git ls-remote https://github.com/git/git HEAD', folder, proxy, 25)
        info['github_git_ls_remote'] = 'ok' if code == 0 and 'HEAD' in out else 'failed: ' + out[-400:]
        os.unlink(script)
    finally:
        await proxy.stop()
        await d.search.close()
        for operation in reversed(operations):
            await call('rollback_file', sessions[0], operation_id=operation)
        for s in sessions: await call('work_session', s, action='close')
        state = await call('who_is_working')
        await d.close()
    assert not state['work_sessions'] and not state['work_locks'] and not state['shell_enabled'], state
    assert not Path(folder).exists(), 'selftest folder left behind'
    checks.append('sessions closed, locks released, test files rolled back')
    print(json.dumps({'passed': True, 'uid': os.getuid(), 'checks': checks, 'info': info}))


if __name__ == '__main__': asyncio.run(main())
