"""Gateway catalog change for point F: optional network flag on enable_full_shell (personal Mac only)."""
import copy

NETWORK_PROPERTY = {'type': 'boolean',
                    'description': 'Personal Mac only: also allow HTTPS through the allowlist proxy '
                                   '(domains listed by list_machines network_domains). Default false.'}


def install_schema(tools):
    out = copy.deepcopy(tools)
    for t in out:
        if t['name'] == 'enable_full_shell':
            t['inputSchema'].setdefault('properties', {})['network'] = copy.deepcopy(NETWORK_PROPERTY)
    return out
