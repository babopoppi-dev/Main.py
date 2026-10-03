"""Point E: controlled access to real project folders (from the reviewed mac_v013 reserve work).

The list lives in a root-owned JSON file in the agent code directory. Read-write
roots join the main file engine (writes need a work session AND a covering work
lock); read-only roots get a separate engine that refuses every mutation. A
read-write root may sit inside a read-only root: the read-only engine then
excludes it, so every path belongs to exactly one engine. The isolated shell may
read the project roots and write only the read-write ones (seatbelt profile).
"""
import json
import os
from pathlib import Path
import re
import stat

FORBIDDEN = re.compile(r'bitcoin|marruca|lidar|keychain|^\.ssh$|^\.gnupg$|^\.aws$|^\.config$|^library$|^\.trash$', re.I)
# Pre-scan only: forbidden names are also checked on every requested path and by the seatbelt.
SKIP_SCAN = frozenset({'.git', 'node_modules', 'Pods', 'DerivedData', '.build', 'build', '.venv', 'venv'})
SCAN_DEPTH = 3
SCAN_LIMIT = 200000
EMPTY = {'rw': [], 'ro': [], 'exclude': [], 'ro_exclude': []}


def forbidden_component(path, root):
    rel = os.path.relpath(path, root)
    parts = [] if rel == '.' else rel.split(os.sep)
    return any(FORBIDDEN.search(p) for p in parts)


def _inside(a, b):
    """True when a is b or lies below it (case-insensitive, like APFS)."""
    a, b = a.casefold().rstrip('/'), b.casefold().rstrip('/')
    return a == b or a.startswith(b + '/')


def _overlap(a, b):
    return _inside(a, b) or _inside(b, a)


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
            elif level + 1 < depth and e.name not in SKIP_SCAN:
                frontier.append((e.path, level + 1))
    return found


def validate(cfg, protected=(), scan=scan_forbidden, check_fs=True):
    """Return {'rw', 'ro', 'exclude', 'ro_exclude'} from a parsed configuration."""
    if not isinstance(cfg, dict) or set(cfg) - {'version', 'roots', 'exclude'} or cfg.get('version') != 1:
        raise ValueError('invalid projects configuration')
    out = {k: [] for k in EMPTY}
    roots = cfg.get('roots', [])
    if not isinstance(roots, list) or len(roots) > 16:
        raise ValueError('invalid project roots')
    chosen = []
    for item in roots:
        if not isinstance(item, dict) or set(item) != {'path', 'mode'} or item['mode'] not in ('ro', 'rw'):
            raise ValueError('each root needs path and mode ro/rw')
        p = item['path']
        if not isinstance(p, str) or not re.fullmatch(r'/Users/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+', p) \
                or os.path.normpath(p) != p or p.startswith('/Users/Shared/') or '/..' in p or '/./' in p:
            raise ValueError('project roots must be plain normalized paths under /Users (not Shared): %r' % (p,))
        if check_fs and (os.path.realpath(p) != p or not os.path.isdir(p)):
            raise ValueError('project root must be an existing directory without symlinks: ' + p)
        if any(FORBIDDEN.search(x) for x in p.split('/')):
            raise ValueError('project root names a forbidden area: ' + p)
        if any(_overlap(p, q) for q in protected):
            raise ValueError('project roots must not overlap protected paths: ' + p)
        chosen.append((p, item['mode']))
    for i, (p, mode) in enumerate(chosen):
        for j, (q, other) in enumerate(chosen):
            if i == j or not _overlap(p, q):
                continue
            # Only a read-write root strictly inside a read-only root is allowed.
            if not (mode == 'rw' and other == 'ro' and _inside(p, q) and p.casefold() != q.casefold()) and \
               not (other == 'rw' and mode == 'ro' and _inside(q, p) and p.casefold() != q.casefold()):
                raise ValueError('project roots overlap: %s and %s' % (p, q))
        out[mode].append(p)
    for p in cfg.get('exclude', []):
        if not isinstance(p, str) or not os.path.isabs(p) or os.path.normpath(p) != p \
                or not any(_inside(p, q) and p.casefold() != q.casefold() for q, _ in chosen):
            raise ValueError('exclusions must lie strictly inside a project root')
        out['exclude'].append(p)
    for p, _ in chosen:
        out['exclude'].extend(scan(p))
    out['ro_exclude'] = out['exclude'] + [p for p in out['rw'] if any(_inside(p, q) for q in out['ro'])]
    return out


def load_projects(path, protected=(), owner=0, scan=scan_forbidden):
    """Read the root-owned configuration; a missing file means no projects."""
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
    return validate(cfg, protected, scan)


def shell_view(projects):
    """The subset handed to the sandboxed shell launcher (already validated by the agent)."""
    return {'rw': list(projects['rw']), 'ro': list(projects['ro']), 'exclude': list(projects['exclude'])}
