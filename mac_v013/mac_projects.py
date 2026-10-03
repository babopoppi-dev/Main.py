"""Point E: controlled access to real project folders (configuration only, empty by default).

The list lives in a root-owned JSON file next to the code. Read-write roots join
the main file engine (so writes need a work session AND a covering work lock);
read-only roots get a separate engine that refuses every mutation. The isolated
shell stays confined to the workspace.
"""
import json
import os
from pathlib import Path
import re
import stat

FORBIDDEN = re.compile(r'bitcoin|marruca|lidar|keychain|^\.ssh$|^\.gnupg$|^\.aws$|^\.config$|^library$|^\.trash$', re.I)
SCAN_DEPTH = 3
SCAN_LIMIT = 20000
EMPTY = {'rw': [], 'ro': [], 'exclude': []}


def forbidden_component(path, root):
    rel = os.path.relpath(path, root)
    parts = [] if rel == '.' else rel.split(os.sep)
    return any(FORBIDDEN.search(p) for p in parts)


def _overlap(a, b):
    a, b = a.casefold().rstrip('/'), b.casefold().rstrip('/')
    return a == b or a.startswith(b + '/') or b.startswith(a + '/')


def scan_forbidden(root, depth=SCAN_DEPTH, limit=SCAN_LIMIT):
    """Directories with forbidden names below a root become denied roots (no symlinks followed)."""
    found, seen, frontier = [], 0, [(root, 0)]
    while frontier:
        current, level = frontier.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for e in entries:
            seen += 1
            if seen > limit:
                raise ValueError('project root too large to pre-scan: ' + root)
            if not e.is_dir(follow_symlinks=False):
                continue
            if FORBIDDEN.search(e.name):
                found.append(e.path)
            elif level + 1 < depth:
                frontier.append((e.path, level + 1))
    return found


def load_projects(path, protected=(), owner=0, scan=scan_forbidden):
    """Return {'rw': [...], 'ro': [...], 'exclude': [...]}; a missing file means no projects."""
    path = Path(path)
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {k: list(v) for k, v in EMPTY.items()}
    with os.fdopen(fd, 'rb') as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != owner or st.st_mode & 0o022 or st.st_size > 65536:
            raise PermissionError('unsafe projects configuration')
        cfg = json.loads(f.read(65537))
    if not isinstance(cfg, dict) or set(cfg) - {'version', 'roots', 'exclude'} or cfg.get('version') != 1:
        raise ValueError('invalid projects configuration')
    out = {'rw': [], 'ro': [], 'exclude': []}
    roots = cfg.get('roots', [])
    if not isinstance(roots, list) or len(roots) > 16:
        raise ValueError('invalid project roots')
    chosen = []
    for item in roots:
        if not isinstance(item, dict) or set(item) != {'path', 'mode'} or item['mode'] not in ('ro', 'rw'):
            raise ValueError('each root needs path and mode ro/rw')
        p = item['path']
        if not isinstance(p, str) or not p.startswith('/Users/') or os.path.normpath(p) != p or p.startswith('/Users/Shared/'):
            raise ValueError('project roots must be normalized paths under /Users (not Shared): %r' % (p,))
        if os.path.realpath(p) != p or not os.path.isdir(p):
            raise ValueError('project root must be an existing directory without symlinks: ' + p)
        if any(FORBIDDEN.search(x) for x in p.split('/')):
            raise ValueError('project root names a forbidden area: ' + p)
        if any(_overlap(p, q) for q in chosen) or any(_overlap(p, q) for q in protected):
            raise ValueError('project roots must not overlap each other or protected paths: ' + p)
        chosen.append(p)
        out[item['mode']].append(p)
    for p in cfg.get('exclude', []):
        if not isinstance(p, str) or not os.path.isabs(p) or not any(_overlap(p, q) and len(p) > len(q) for q in chosen):
            raise ValueError('exclusions must lie strictly inside a project root')
        out['exclude'].append(os.path.normpath(p))
    for p in chosen:
        out['exclude'].extend(scan(p))
    return out
