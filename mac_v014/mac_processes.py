"""Point G, level 1: list and stop processes of the dedicated account.

Does not change the containment guarantee: the shell still stops every process
of the dedicated account when its session ends. process_stop only signals
descendants of a running shell session owned by the caller's work session.
"""
import os
import re
import signal
import subprocess

from process_schema import PROCESS_NAMES, PROCESS_TOOLS, install_schema

SIGNALS = {'TERM': signal.SIGTERM, 'KILL': signal.SIGKILL, 'INT': signal.SIGINT}


def run_ps():
    return subprocess.run(['/bin/ps', '-axww', '-o', 'uid=,pid=,ppid=,etime=,stat=,command='],
                          capture_output=True, text=True, timeout=10, check=True,
                          env={'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}).stdout


class ProcessTools:
    MAX_LIST = 200

    def __init__(self, uid=None, agent_pid=None, ps=run_ps, kill=os.kill):
        self.uid = os.getuid() if uid is None else uid
        self.agent_pid = os.getpid() if agent_pid is None else agent_pid
        self.ps, self.kill = ps, kill

    def snapshot(self):
        procs = {}
        for row in self.ps().splitlines():
            p = row.split(None, 5)
            if len(p) < 5 or not p[0].isdigit() or int(p[0]) != self.uid:
                continue
            procs[int(p[1])] = {'pid': int(p[1]), 'ppid': int(p[2]), 'elapsed': p[3], 'state': p[4],
                                'command': (p[5] if len(p) > 5 else '')[:300]}
        return procs

    @staticmethod
    def descends(procs, pid, roots):
        seen = set()
        while pid in procs and pid not in seen:
            seen.add(pid)
            pid = procs[pid]['ppid']
            if pid in roots:
                return True
        return False

    def roles(self, procs, job_pids):
        for p in procs.values():
            if p['pid'] == self.agent_pid:
                p['role'] = 'agent'
            elif p['pid'] in job_pids:
                p['role'] = 'shell_session'
            elif self.descends(procs, p['pid'], job_pids):
                p['role'] = 'shell_process'
            elif p['ppid'] == self.agent_pid:
                p['role'] = 'agent_helper'
            else:
                p['role'] = 'other'
        return procs

    def list(self, job_pids):
        procs = self.roles(self.snapshot(), set(job_pids))
        items = sorted(procs.values(), key=lambda x: x['pid'])
        return {'uid': self.uid, 'processes': items[:self.MAX_LIST], 'truncated': len(items) > self.MAX_LIST}

    def stop(self, args, job_pids):
        if set(args) - {'pid', 'signal'} or type(args.get('pid')) is not int or args['pid'] < 2:
            raise ValueError('pid required')
        name = args.get('signal', 'TERM')
        if name not in SIGNALS:
            raise ValueError('signal must be TERM, INT or KILL')
        pid, roots = args['pid'], set(job_pids)
        procs = self.snapshot()
        if pid not in procs:
            raise PermissionError('process not found for the dedicated account')
        if pid == self.agent_pid or pid in roots or not self.descends(procs, pid, roots):
            raise PermissionError('only processes started inside your running shell session can be stopped')
        self.kill(pid, SIGNALS[name])
        return {'pid': pid, 'signal': name, 'sent': True, 'command': procs[pid]['command']}
