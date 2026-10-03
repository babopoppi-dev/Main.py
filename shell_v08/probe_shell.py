"""Real containment/lifecycle tests, run as UID997 in a hardened transient unit."""
import asyncio
import json
import os
from pathlib import Path
import shlex
import sys
import time

from file_tools import FileTools
from isolated_shell import IsolatedShell

BASE = Path('/var/lib/central-mcp-vps-agent-test/tmp/collaudo_shell_v08r3_20261002')
WORK = BASE / 'workspace'
STATE = BASE / 'journal'
OWNER, OTHER = 'test:owner-a', 'test:owner-b'


def python(code):
    return '/usr/bin/python3 -I -c ' + shlex.quote(code)


def daemon(marker):
    return python("import os,time\nif os.fork()==0:\n os.setsid()\n while True:\n  open('/workspace/" + marker + "','w').write(str(time.monotonic()))\n  time.sleep(.05)\ntime.sleep(60)\n")


async def expect_denied(operation):
    try:
        await operation
    except (PermissionError, ValueError):
        return
    raise AssertionError('operation unexpectedly accepted')


async def completed(shell, command):
    start = await shell.start(OWNER, command)
    job = shell.jobs[start['session_id']]
    await asyncio.wait_for(job['done'].wait(), 8)
    result = shell.read(OWNER, start['session_id'])
    assert result['exit_code'] == 0, result
    return result


async def wait_marker(path):
    for _ in range(100):
        if path.exists() and path.read_text():
            return
        await asyncio.sleep(.02)
    raise AssertionError('child heartbeat did not start')


async def stable(path):
    await asyncio.sleep(.25)
    before = path.read_text()
    await asyncio.sleep(.35)
    assert path.read_text() == before, 'daemon survived shell revocation'


async def main():
    assert os.getuid() == 997
    files = FileTools([str(WORK)], str(STATE))
    shell = IsolatedShell(files, str(WORK), capable=True)
    checks = []
    try:
        if len(sys.argv) == 2 and sys.argv[1] == '--parent-death':
            await shell.enable(OWNER, 1)
            await shell.start(OWNER, daemon('parent-death'))
            await wait_marker(WORK / 'parent-death')
            os._exit(0)
        await expect_denied(shell.start(OWNER, 'id'))
        await shell.enable(OWNER, 1)
        await expect_denied(shell.enable(OTHER, 1))
        checks.append('disabled and competing authorization refused')
        result = await shell.execute(OWNER, {'command': 'id -u'})
        output = result['output']
        deadline = time.monotonic() + 8
        while result.get('running') or result.get('has_more'):
            assert time.monotonic() < deadline, result
            await asyncio.sleep(.05)
            result = shell.read(OWNER, result['session_id'])
            output += result['output']
        assert result['exit_code'] == 0 and output.strip() == '997', (result, output)
        checks.append('shell_exec id with asynchronous completion')
        result = await completed(shell, python("""import os,json,socket,subprocess,resource
s=dict(l.split(':',1) for l in open('/proc/self/status') if ':' in l)
assert os.getuid()==997 and os.geteuid()==997
assert s['NoNewPrivs'].strip()=='1'
assert int(s['CapEff'].strip(),16)==0
assert not os.path.exists('/home')
assert not os.path.exists('/etc/central-mcp-gateway')
assert not os.path.exists('/etc/central-mcp-vps-agent')
assert not os.path.exists('/opt/central-mcp-gateway')
assert not os.path.exists('/var/lib/central-mcp-gateway')
assert resource.getrlimit(resource.RLIMIT_NPROC)[1]==64
assert resource.getrlimit(resource.RLIMIT_FSIZE)[1]==16777216
assert subprocess.run(['unshare','--user','true'],capture_output=True).returncode!=0
try:
 socket.create_connection(('1.1.1.1',443),.2)
except OSError: pass
else: raise AssertionError('network unexpectedly reachable')
open('/workspace/written.txt','w').write('isolated write\\n')
print(json.dumps({'uid':os.getuid(),'no_new_privileges':True,'capabilities':0,'network':'isolated'}))
"""))
        assert (WORK / 'written.txt').read_text() == 'isolated write\n'
        checks.append('filesystem credentials capabilities network and resource limits')
        sid = (await shell.start(OWNER, 'cat'))['session_id']
        try:
            shell.read(OTHER, sid)
        except PermissionError:
            pass
        else:
            raise AssertionError('output crossed authorization boundary')
        await expect_denied(shell.session(OTHER, {'action':'send','session_id':sid,'data':'bad\n'}))
        await expect_denied(shell.start(OWNER, 'id'))
        sent = await shell.session(OWNER, {'action':'send','session_id':sid,'data':'MCP_PTY_OK\n'})
        assert sent['bytes_sent'] == 11
        await asyncio.sleep(.1)
        assert 'MCP_PTY_OK' in shell.read(OWNER, sid)['output']
        try:
            files.write_file(str(WORK / 'conflict.txt'), 'bad', session_id=OWNER)
        except Exception as exc:
            assert getattr(exc, 'code', None) == 'LOCK_BUSY', str(exc)
        else:
            raise AssertionError('file write ignored active shell lock')
        assert not (WORK / 'conflict.txt').exists()
        await shell.session(OWNER, {'action':'stop','session_id':sid})
        files.write_file(str(WORK / 'after-stop.txt'), 'ok', session_id=OWNER)
        checks.append('PTY input output ownership and shared file lock')
        sid = (await shell.start(OWNER, python("import sys;sys.stdout.write('x'*1048576)")))['session_id']
        await asyncio.wait_for(shell.jobs[sid]['done'].wait(), 8)
        assert len(shell.jobs[sid]['output']) <= shell.MAX_OUTPUT
        assert shell.read(OWNER, sid)['truncated']
        checks.append('bounded output')
        await shell.start(OWNER, daemon('disabled'))
        await wait_marker(WORK / 'disabled')
        await shell.disable()
        await stable(WORK / 'disabled')
        await expect_denied(shell.start(OWNER, 'id'))
        checks.append('disable kills detached descendants')
        await shell.enable(OWNER, 1)
        await shell.start(OWNER, daemon('expired'))
        await wait_marker(WORK / 'expired')
        shell.until = time.monotonic() + .1  # Test-only clock deadline.
        await asyncio.sleep(.4)
        await stable(WORK / 'expired')
        assert shell.owner is None
        checks.append('expiry kills detached descendants')
        child = await asyncio.create_subprocess_exec(sys.executable, '-B', __file__, '--parent-death',
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(child.communicate(), 8)
        assert child.returncode == 0, stderr.decode()
        await stable(WORK / 'parent-death')
        files.write_file(str(WORK / 'after-parent-death.txt'), 'ok', session_id=OWNER)
        checks.append('agent death kills descendants and releases lock')
        print(json.dumps({'status':'SHELL_PROBE_OK','checks':checks,'live_agent_modified':False}))
    finally:
        await shell.disable()
        files.close()


if __name__ == '__main__':
    asyncio.run(main())
