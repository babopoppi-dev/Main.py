"""Preserve complete bounded logs; require reviewed archival once storage fills."""
import os
import re
import stat
from mac_shell import MacShell


class AgentShell(MacShell):
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
