"""Offline engine probe in a fresh sandbox. Never connects to the gateway."""
import asyncio
import json
import os
from pathlib import Path
import re
import sys

from dc_bridge import Backend

ROOT = Path(__file__).resolve().parent
PACKAGE = Path('/Users/vagrant/.npm/_npx/c329005a7fd3ed13/node_modules/@wonderwhy-er/desktop-commander')


async def main():
    if sys.platform != 'darwin' or os.getuid() == 0:
        raise RuntimeError('non-root macOS test required')
    home = ROOT / 'test-home'
    work = ROOT / 'test-workspace'
    home.mkdir(mode=0o700)
    work.mkdir(mode=0o700)
    cfg = home / '.claude-server-commander'
    cfg.mkdir(mode=0o700)
    (cfg / 'config.json').write_text(json.dumps({
        'telemetryEnabled': False, 'allowedDirectories': [str(work)],
        'defaultShell': '/bin/sh', 'blockedCommands': ['sudo', 'su'],
        'fileWriteLineLimit': 50, 'fileReadLineLimit': 1000,
        'welcomeOnboardingEligible': False, 'pendingWelcomeOnboarding': False,
    }))
    profile = ROOT / 'probe.sb'
    lines = ['(version 1)', '(allow default)', '(deny network*)',
             '(deny file-read* (subpath "/Users"))',
             '(deny file-read* (subpath "/Volumes"))', '(deny file-write*)',
             '(allow file-read-metadata)']
    for p in ['/System', '/usr', '/bin', '/sbin', '/Library/Apple',
              '/opt/homebrew', str(PACKAGE.parents[2]), str(ROOT)]:
        lines.append('(allow file-read* (subpath ' + json.dumps(p) + '))')
    for p in ['/dev/null', '/dev/urandom', '/dev/random', '/private/etc/localtime']:
        lines.append('(allow file-read* (literal ' + json.dumps(p) + '))')
    for p in [str(home), str(work)]:
        lines.append('(allow file-write* (subpath ' + json.dumps(p) + '))')
    lines.append('(allow file-write* (literal "/dev/null"))')
    profile.write_text('\n'.join(lines) + '\n')
    env = {'HOME': str(home), 'PATH': '/opt/homebrew/bin:/usr/bin:/bin',
           'SHELL': '/bin/sh', 'LANG': 'en_US.UTF-8',
           'TMPDIR': str(home), 'DESKTOP_COMMANDER_DISABLE_TELEMETRY': '1',
           'UV_THREADPOOL_SIZE': '16'}
    backend = Backend(['/usr/bin/sandbox-exec', '-f', str(profile),
                       '/opt/homebrew/bin/node', str(ROOT / 'dc_stdio.mjs'), str(PACKAGE)],
                      str(work), env)
    async def call(name, args):
        value = await backend.call(name, args, 30)
        if value.get('isError'):
            raise RuntimeError(name + ' rejected: ' + json.dumps(value)[:1500])
        text = '\n'.join(c.get('text', '') for c in value.get('content', []))
        print(json.dumps({'tool': name, 'result': text[:3000]}), flush=True)
        return text
    try:
        init = await backend.start()
        catalog = await backend.tools()
        print(json.dumps({'server': init.get('serverInfo'),
                          'tools': [t['name'] for t in catalog]}), flush=True)
        (ROOT / 'catalog.json').write_text(json.dumps(catalog, indent=2))
        await call('write_file', {'path': str(work / 'probe.txt'), 'content': 'MCP Andrea prova\nseconda riga\n'})
        text = await call('read_file', {'path': str(work / 'probe.txt')})
        assert 'MCP Andrea prova' in text
        await call('list_directory', {'path': str(work)})
        search = await call('start_search', {'path': str(work), 'pattern': 'MCP Andrea',
                                           'searchType': 'content', 'literalSearch': True})
        match = re.search(r'(?:session|Session)\s*(?:ID|id)?\s*:\s*(\S+)', search)
        if match:
            await call('get_more_search_results', {'sessionId': match.group(1)})
        proc = await call('start_process', {'command': '/usr/bin/sw_vers', 'timeout_ms': 1000})
        pid = re.search(r'PID\s*:?\s*(\d+)', proc)
        if pid:
            await call('read_process_output', {'pid': int(pid.group(1)), 'timeout_ms': 1000})
        # The denied target is a fresh test sentinel, not a personal file.
        denied = await backend.call('read_file', {'path': str(ROOT.parent / 'mcp-parity-denied-sentinel')})
        assert denied.get('isError'), 'outside read unexpectedly allowed'
        print('PROBE_OK', flush=True)
    finally:
        await backend.close()


if __name__ == '__main__':
    asyncio.run(main())
