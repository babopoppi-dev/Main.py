#!/usr/bin/env python3
"""Root-only configuration of points E (projects) and F (network) on the personal Mac.

Run through mac_admin_request (Telegram). Without --applica it only prints the plan.
  configura_mac.py rete github.com pypi.org [--applica]
  configura_mac.py rete --nessuna [--applica]
  configura_mac.py progetti /Users/babo/Developer/App:rw /Users/babo/Developer:ro [--applica]
  configura_mac.py progetti --nessuno [--applica]
The configuration is validated with the agent's own loaders before it is written;
ACLs are granted to the dedicated account mcp_andrea only and revoked symmetrically;
then only the agent daemon is restarted.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BASE = Path('/Library/MCPAndreaMacMioV09')
CODE = BASE / 'code'
LABEL = 'it.andreababini.mcp-mac-mio-v09'
USER = 'mcp_andrea'
ACE = {'traverse': 'search',
       'ro': 'list,search,read,readattr,readextattr,readsecurity,file_inherit,directory_inherit',
       'rw': 'list,search,read,readattr,readextattr,readsecurity,add_file,add_subdirectory,write,append,'
             'writeattr,writeextattr,delete,delete_child,file_inherit,directory_inherit'}


def run(argv, apply):
    print(('ESEGUO ' if apply else 'PIANO  ') + ' '.join(argv))
    if apply:
        subprocess.run(argv, check=True, timeout=600, env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'})


def loaders():
    sys.path.insert(0, str(CODE))
    from mac_netproxy import load_domains
    from mac_projects import load_projects
    return load_domains, load_projects


def write_config(name, data, check, apply):
    target = CODE / name
    raw = json.dumps(data, indent=2).encode()
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / name
        probe.write_bytes(raw)
        check(probe, owner=os.getuid())
    print(('SCRIVO ' if apply else 'PIANO  ') + str(target) + ' ' + json.dumps(data))
    if apply:
        temp = CODE / ('.' + name + '.tmp')
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
        with os.fdopen(fd, 'wb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        os.chown(str(temp), 0, 0)
        os.replace(str(temp), str(target))


def remove_config(name, apply):
    target = CODE / name
    print(('RIMUOVO ' if apply else 'PIANO  rimozione ') + str(target))
    if apply and target.exists():
        target.unlink()


def ancestors(path):
    out, p = [], Path(path).parent
    while str(p) not in ('/', '/Users'):
        out.append(str(p)); p = p.parent
    return list(reversed(out))


def acl_commands(projects, grant, keep=()):
    """chmod ACL commands; on revoke, ancestors still needed by kept projects stay traversable."""
    sign = '+a' if grant else '-a'
    cmds, seen = [], {a for path, _ in keep for a in ancestors(path)} if not grant else set()
    for path, mode in projects:
        for a in ancestors(path):
            if a not in seen:
                seen.add(a)
                cmds.append(['/bin/chmod', sign, '%s allow %s' % (USER, ACE['traverse']), a])
        cmds.append(['/bin/chmod', '-R', sign, '%s allow %s' % (USER, ACE[mode]), path])
    if not grant:
        cmds.reverse()
    return cmds


def restart(apply):
    run(['/bin/launchctl', 'kickstart', '-k', 'system/' + LABEL], apply)


def main(argv):
    apply = '--applica' in argv
    args = [a for a in argv if a != '--applica']
    if apply and os.geteuid() != 0:
        raise SystemExit('serve root (mac_admin_request)')
    load_domains, load_projects = loaders()
    if args[:1] == ['rete']:
        if args[1:] == ['--nessuna']:
            remove_config('network.json', apply)
        else:
            write_config('network.json', {'version': 1, 'domains': args[1:]}, load_domains, apply)
    elif args[:1] == ['progetti']:
        previous = []
        if (CODE / 'projects.json').exists():
            old = json.loads((CODE / 'projects.json').read_text())
            previous = [(r['path'], r['mode']) for r in old.get('roots', [])]
        if args[1:] == ['--nessuno']:
            wanted = []
        else:
            wanted = []
            for item in args[1:]:
                path, _, mode = item.rpartition(':')
                if mode not in ('ro', 'rw'):
                    raise SystemExit('formato: /percorso:ro oppure /percorso:rw')
                wanted.append((path, mode))
        protected = (str(BASE), '/Users/Shared/MCPAndreaMacMio', '/Library', '/System')
        if wanted:
            write_config('projects.json', {'version': 1, 'roots': [{'path': p, 'mode': m} for p, m in wanted]},
                         lambda f, owner: load_projects(f, protected, owner=owner), apply)
        kept = [x for x in previous if x in wanted]
        for cmd in acl_commands([x for x in previous if x not in wanted], False, keep=kept):
            run(cmd, apply)
        for cmd in acl_commands([x for x in wanted if x not in previous], True):
            run(cmd, apply)
        if not wanted:
            remove_config('projects.json', apply)
    else:
        raise SystemExit(__doc__)
    restart(apply)
    if not apply:
        print('Nessuna modifica: aggiungi --applica per eseguire.')


if __name__ == '__main__':
    main(sys.argv[1:])
