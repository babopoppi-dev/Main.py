"""Runs only inside a root-prepared disposable area as dedicated uid5000."""
import asyncio
import json
import os
from pathlib import Path
import shlex
import signal
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from file_tools import FileTools, FileToolError
from mac_shell import MacShell
from mac_guard import require_identity

CALLER = 'preflight:mac-shell-v09'
BASE = Path('/Library/MCPAndreaMacMioPreflightV09')
WORK = Path('/Users/Shared/MCPAndreaMacMioPreflightV09/workspace')


def check(value, label):
    if not value:
        raise AssertionError(label)
    print(json.dumps({'check': label, 'passed': True}), flush=True)


async def gone(pid):
    for _ in range(60):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        await asyncio.sleep(.05)
    return False


def detached(name, stay):
    code = '''import os,time,pathlib
p=pathlib.Path(%r)
pid=os.fork()
if pid == 0:
 os.setsid()
 p.write_text(str(os.getpid()))
 time.sleep(90)
 os._exit(0)
for _ in range(200):
 if p.exists():break
 time.sleep(.01)
print('DETACHED_READY',flush=True)
time.sleep(%d)
''' % (str(WORK / name), 90 if stay else 0)
    return shlex.quote(os.path.realpath(sys.executable)) + ' -I -B -c ' + shlex.quote(code)


async def wait_file(name):
    path = WORK / name
    for _ in range(100):
        if path.exists():
            return int(path.read_text())
        await asyncio.sleep(.05)
    raise AssertionError('detached process did not start')


async def main(mode):
    require_identity()
    files = FileTools([str(WORK)], str(BASE / 'run/operations'))
    shell = MacShell(files, str(WORK), str(BASE / 'run/logs'), capable=True)
    try:
        try:
            await shell.start(CALLER, 'id -u')
            raise AssertionError('disabled shell accepted command')
        except PermissionError:
            check(True, 'disabled_by_default')
        if mode == 'agent-death':
            await shell.enable(CALLER, 1)
            await shell.start(CALLER, detached('death.pid', True))
            await wait_file('death.pid')
            print(json.dumps({'check': 'agent_death_injected', 'passed': True}), flush=True)
            os._exit(23)
        target = str(WORK / 'rollback.txt')
        op = files.write_file(target, 'MCP_ROLLBACK_TEST', session_id=CALLER)
        check(files.read_file(target)['content'] == 'MCP_ROLLBACK_TEST', 'read_write')
        files.rollback_file(op['operation_id'], session_id=CALLER)
        check(not Path(target).exists(), 'rollback')
        await shell.enable(CALLER, 1)
        out = await shell.execute(CALLER, {'command': 'id -u'})
        check(out['exit_code'] == 0 and out['output'].strip() == '5000', 'shell_uid5000')
        session = await shell.start(CALLER, 'cat')
        sid = session['session_id']
        await shell.session(CALLER, {'action': 'send', 'session_id': sid, 'data': 'MCP_PTY_OK\n'})
        observed = ''
        for _ in range(40):
            observed += shell.read(CALLER, sid)['output']
            if 'MCP_PTY_OK' in observed:
                break
            await asyncio.sleep(.05)
        check('MCP_PTY_OK' in observed, 'pty_send_read')
        try:
            await shell.enable('preflight:other-client', 1)
            raise AssertionError('lease stolen')
        except PermissionError:
            check(True, 'other_client_lease_rejected')
        try:
            files.write_file(str(WORK / 'busy.txt'), 'blocked', session_id=CALLER)
            raise AssertionError('file lock ignored')
        except FileToolError as exc:
            check(exc.code == 'LOCK_BUSY', 'file_shell_lock')
        await shell.disable()
        check(shell.read(CALLER, sid)['exit_code'] == -9, 'disable_stops_session')
        await shell.enable(CALLER, 1)
        out = await shell.execute(CALLER, {'command': detached('foreground.pid', False)})
        pid = await wait_file('foreground.pid')
        check(not out['running'] and await gone(pid), 'foreground_end_stops_detached')
        session = await shell.start(CALLER, detached('revoke.pid', True))
        pid = await wait_file('revoke.pid')
        await shell.disable()
        check(await gone(pid), 'disable_stops_detached')
        await shell.enable(CALLER, 1)
        session = await shell.start(CALLER, detached('expiry.pid', True))
        pid = await wait_file('expiry.pid')
        shell.until = time.monotonic() + .4
        shell.refresh_watchdog()
        await asyncio.wait_for(shell.jobs[session['session_id']]['done'].wait(), 4)
        check(shell.owner is None and await gone(pid), 'expiry_stops_detached')
        await shell.enable(CALLER, 1)
        session = await shell.start(CALLER, 'sleep 90')
        os.kill(shell.watchdog.pid, signal.SIGKILL)
        await asyncio.wait_for(shell.jobs[session['session_id']]['done'].wait(), 4)
        check(shell.read(CALLER, session['session_id'])['exit_code'] == -9, 'watchdog_failure_stops_session')
        shell.LOG_LIMIT = 16384
        out = await shell.execute(CALLER, {'command': "yes MCP_OUTPUT_LIMIT"})
        job = shell.jobs[out['session_id']]
        check(not out['log_complete'] and job['log_bytes'] <= 16384, 'output_limit')
        await shell.disable()
        check(not shell.working()['active_locks'], 'no_remaining_locks')
    finally:
        await shell.disable()
        files.close()


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else 'normal'))
