"""Gateway catalog entries for point G level 1 (process list/stop on the personal Mac)."""

PROCESS_NAMES = {'process_list', 'process_stop'}
SIGNAL_NAMES = ['INT', 'KILL', 'TERM']
AUTH = {'work_session_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'},
        'work_session_token': {'type': 'string', 'minLength': 43, 'maxLength': 43}}
PROCESS_TOOLS = [
    {'name': 'process_list',
     'description': 'List processes of the dedicated Mac account (pid, ppid, elapsed, state, command, role). '
                    'Read-only; no work session needed. Long jobs: run several commands in one shell_session '
                    'with output redirected to files in the workspace, then read them with read_file.',
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['machine'],
                     'properties': {'machine': {'type': 'string', 'enum': ['mac_mio']}}}},
    {'name': 'process_stop',
     'description': 'Send TERM, INT or KILL to one process started inside your running shell session '
                    '(descendants only; never the agent). Requires the work session that holds the shell.',
     'inputSchema': {'type': 'object', 'additionalProperties': False,
                     'required': ['machine', 'pid', 'work_session_id', 'work_session_token'],
                     'properties': {'machine': {'type': 'string', 'enum': ['mac_mio']},
                                    'pid': {'type': 'integer', 'minimum': 2},
                                    'signal': {'type': 'string', 'enum': SIGNAL_NAMES}, **AUTH}}},
]


def install_schema(tools):
    import copy
    return copy.deepcopy([t for t in tools if t['name'] not in PROCESS_NAMES]) + copy.deepcopy(PROCESS_TOOLS)
