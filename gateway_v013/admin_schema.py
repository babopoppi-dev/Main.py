"""Mac administration through Telegram: shared validation and gateway catalog entries.

The agent (UID 5000) only queues requests. A separate root helper with its own
Telegram bot shows the exact command to Andrea and runs it only after approval.
Nothing is pre-authorized.
"""
import re
import shlex

ADMIN_NAMES = {'mac_admin_request', 'mac_admin_result'}
CHARSET = re.compile(r'[A-Za-z0-9_./:=@%+, -]+')
MAX_COMMAND = 3000
MAX_REASON = 500
DEFAULT_TIMEOUT = 300
MAX_TIMEOUT = 900
EXPIRE_S = 600
AUTH = {'work_session_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'},
        'work_session_token': {'type': 'string', 'minLength': 43, 'maxLength': 43}}

ADMIN_TOOLS = [
    {'name': 'mac_admin_request',
     'description': 'Ask Andrea to run ONE administrator (root) command on his personal Mac. '
                    'The exact command is shown on Telegram by a separate Mac bot and runs only after '
                    'his approval (sensitive commands need a second confirmation); nothing is pre-authorized. '
                    'No shell: absolute program path, characters [A-Za-z0-9_./:=@%+, -] only, max 3000. '
                    'Requires an open work session. Returns request_id; poll mac_admin_result (expires in 10 min).',
     'inputSchema': {'type': 'object', 'additionalProperties': False,
                     'required': ['machine', 'command', 'reason', 'work_session_id', 'work_session_token'],
                     'properties': {'machine': {'type': 'string', 'enum': ['mac_mio']},
                                    'command': {'type': 'string', 'minLength': 1, 'maxLength': MAX_COMMAND},
                                    'reason': {'type': 'string', 'minLength': 1, 'maxLength': MAX_REASON},
                                    'timeout': {'type': 'integer', 'minimum': 1, 'maximum': MAX_TIMEOUT},
                                    **AUTH}}},
    {'name': 'mac_admin_result',
     'description': 'Status and output of a mac_admin_request (queued, waiting, done, rejected, expired, error). '
                    'Only the requesting authorization can read it.',
     'inputSchema': {'type': 'object', 'additionalProperties': False,
                     'required': ['machine', 'request_id'],
                     'properties': {'machine': {'type': 'string', 'enum': ['mac_mio']},
                                    'request_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'}}}},
]


def parse_command(command):
    """Return argv for an admin command, or raise ValueError. No shell is ever used."""
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND:
        raise ValueError('command required (max %d characters)' % MAX_COMMAND)
    if not CHARSET.fullmatch(command):
        raise ValueError('unsupported command character')
    argv = shlex.split(command, posix=True)
    if not argv or not argv[0].startswith('/') or '/../' in argv[0] + '/' or argv[0].endswith('/'):
        raise ValueError('the program must be an absolute path')
    return argv


def parse_timeout(value):
    if value is None:
        return DEFAULT_TIMEOUT
    if type(value) is not int or not 1 <= value <= MAX_TIMEOUT:
        raise ValueError('timeout must be 1..%d seconds' % MAX_TIMEOUT)
    return value


def install_schema(tools):
    """Additive and idempotent catalog update for the gateway."""
    import copy
    return copy.deepcopy([t for t in tools if t['name'] not in ADMIN_NAMES]) + copy.deepcopy(ADMIN_TOOLS)
