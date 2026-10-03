"""Bounded logs; optional allowlist network proxy bound to the shell lease (point F)."""
import os
import re
import stat
from mac_shell import MacShell
from mac_netproxy import NetProxy


class AgentShell(MacShell):
    domains = ()
    proxy = None

    def child_env(self):
        env = super().child_env()
        if self.proxy is not None and self.proxy.token:
            env['MCP_PROXY'] = '%d:%s' % (self.proxy.port, self.proxy.token)
        return env

    async def enable(self, caller, minutes, network=False):
        if type(network) is not bool:
            raise ValueError('network must be boolean')
        if network and not self.domains:
            raise PermissionError('no network domains configured for the shell')
        if network and self.proxy is not None and self.owner not in (None, caller):
            raise PermissionError('another client holds the workspace shell lease')
        result = await super().enable(caller, minutes)
        if network and self.proxy is None:
            proxy = NetProxy(self.domains)
            await proxy.start()
            self.proxy = proxy
        if self.proxy is not None and not network:
            await self.stop_proxy()
        result['network'] = 'allowlist proxy' if self.proxy is not None else 'disabled'
        if self.proxy is not None:
            result['network_domains'] = sorted(self.proxy.domains)
        return result

    async def stop_proxy(self):
        proxy, self.proxy = self.proxy, None
        if proxy is not None:
            await proxy.stop()

    async def disable(self):
        try:
            return await super().disable()
        finally:
            await self.stop_proxy()

    def network_log(self):
        return list(self.proxy.log[-20:]) if self.proxy is not None else []

    def check_log_storage(self):
        count = total = 0
        with os.scandir(self.logs) as entries:
            for entry in entries:
                s = entry.stat(follow_symlinks=False)
                if not re.fullmatch(r'[0-9a-f]{32}\.log', entry.name) or not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_nlink != 1:
                    raise PermissionError('unexpected shell log entry')
                count += 1; total += s.st_size
                if count >= 128 or total + self.LOG_LIMIT > 256 * 1024 * 1024:
                    raise PermissionError('shell log quota reached; archive logs before new sessions')

    async def start(self, caller, command, cwd=None):
        self.check_log_storage()
        return await super().start(caller, command, cwd)
