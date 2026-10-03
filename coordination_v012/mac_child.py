#!/usr/bin/env python3
"""Trusted resource-limit setup followed by exec into the seatbelt sandbox."""
import os
import re
from pathlib import Path
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
    # The agent passes the per-lease proxy credential in the environment,
    # never in argv (visible to every local user through ps).
    port, token = os.environ.get('MCP_NET_PORT'), os.environ.get('MCP_NET_TOKEN')
    net_port = None
    if port or token:
        if not (port and port.isdigit() and token and re.fullmatch(r'[A-Za-z0-9_-]{32}', token)):
            raise SystemExit('invalid network lease')
        net_port = int(port)
        proxy = 'http://mcp:%s@127.0.0.1:%d' % (token, net_port)
        env.update({'HTTPS_PROXY': proxy, 'https_proxy': proxy, 'NO_PROXY': '', 'no_proxy': '',
                    'GIT_SSL_CAINFO': '/etc/ssl/cert.pem', 'SSL_CERT_FILE': '/etc/ssl/cert.pem',
                    'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_COUNT': '1',
                    'GIT_CONFIG_KEY_0': 'http.proxyAuthMethod', 'GIT_CONFIG_VALUE_0': 'basic'})
    os.execve('/usr/bin/sandbox-exec', ['/usr/bin/sandbox-exec', '-p',
              profile(workspace, tty_path, net_port), '/bin/bash', '--noprofile', '--norc',
              '-c', command], env)


if __name__ == '__main__':
    main()
