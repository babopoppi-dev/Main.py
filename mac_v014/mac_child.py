#!/usr/bin/env python3
"""Trusted resource-limit setup followed by exec into the seatbelt sandbox."""
import os
from pathlib import Path
import re
import resource
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mac_guard import require_identity
from mac_policy import profile


def main():
    require_identity()
    if len(sys.argv) != 5:
        raise SystemExit('workspace cwd command tty required')
    workspace, cwd, command, tty_path = sys.argv[1:]
    if os.path.commonpath([workspace, cwd]) != workspace:
        raise SystemExit('cwd outside workspace')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16777216, 16777216))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': workspace,
           'TMPDIR': workspace + '/.tmp', 'LANG': 'en_US.UTF-8', 'TERM': 'xterm'}
    port = None
    spec = os.environ.get('MCP_PROXY', '')
    if spec:
        m = re.fullmatch(r'([0-9]{4,5}):([A-Za-z0-9_-]{32})', spec)
        if not m:
            raise SystemExit('invalid proxy specification')
        port = int(m.group(1))
        url = 'http://mcp:%s@127.0.0.1:%d' % (m.group(2), port)
        for name in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'ALL_PROXY', 'all_proxy'):
            env[name] = url
    os.execve('/usr/bin/sandbox-exec', ['/usr/bin/sandbox-exec', '-p',
              profile(workspace, tty_path, port), '/bin/bash', '--noprofile', '--norc',
              '-c', command], env)


if __name__ == '__main__':
    main()
