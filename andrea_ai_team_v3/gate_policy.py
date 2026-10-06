from __future__ import annotations

"""
Shared, side-effect-free policy for the ANDREA AI TEAM write gate.

Used by BOTH the orchestrator (early, friendly refusal) and the gate server
(authoritative enforcement). The gate server never trusts the orchestrator:
every path is rebuilt from (project name, relative path) here.
"""

import posixpath
import re
from typing import Optional


DEFAULT_PROJECTS_ROOT = "/var/lib/central-mcp-vps-agent-test/workspace/team-projects"
SNAPSHOT_DIR = ".snapshots"
TRASH_DIR = ".trash"

MAX_FILE_BYTES = 256 * 1024
MAX_FILES_PER_JOB = 80
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_REL_DEPTH = 6
MAX_REL_LEN = 200

_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,99}$")
_UID_RE = re.compile(r"^[a-f0-9]{32}$")

# Existing sensitive projects stay outside the TEAM sandbox. A TEAM project may
# not even borrow their names, so nobody can mistake a sandbox copy for the real one.
PROTECTED_KEYWORDS = (
    "bitcoin", "btc", "marruca", "lidar", "rentri", "mcp", "andrea-ai-team",
    "andrea_ai_team", "central-mcp", "gateway", "approver",
)
_RESERVED_NAMES = {"snapshots", "trash", "tmp", "root", "etc", "opt", "var", "home", "proc", "sys"}

# Files that must never be written by generated code.
_DENIED_BASENAMES = {
    ".env", ".envrc", ".netrc", ".pypirc", ".npmrc", ".git-credentials", "id_rsa", "id_ed25519",
    "id_ecdsa", "authorized_keys", "known_hosts", "credentials", "credentials.json", "secrets.json",
    "service-account.json", ".htpasswd",
}
_DENIED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".kdbx", ".so", ".dylib", ".exe")
_ALLOWED_HIDDEN = {".gitignore", ".editorconfig", ".flake8", ".coveragerc"}

# The ONLY commands the gate will ever run for a TEAM project. Never built from LLM text.
TEST_COMMANDS = {
    "unittest": "python3 -B -m unittest discover -v",
    "unittest_tests_dir": "python3 -B -m unittest discover -s tests -t . -v",
    "pytest": "python3 -B -m pytest -q -p no:cacheprovider",
}


class PolicyError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def is_protected_name(text: str) -> Optional[str]:
    low = (text or "").lower()
    for kw in PROTECTED_KEYWORDS:
        if kw in low:
            return kw
    return None


def validate_project_name(name: str) -> str:
    if not isinstance(name, str) or not _PROJECT_RE.match(name):
        raise PolicyError("INVALID_PROJECT", "nome progetto: 2-40 caratteri a-z 0-9 _ -")
    if name in _RESERVED_NAMES:
        raise PolicyError("INVALID_PROJECT", "nome riservato")
    kw = is_protected_name(name)
    if kw:
        raise PolicyError("PROTECTED_PROJECT", kw)
    return name


def validate_uid(uid: str) -> str:
    if not isinstance(uid, str) or not _UID_RE.match(uid):
        raise PolicyError("INVALID_JOB")
    return uid


def validate_relpath(rel: str, allow_root: bool = False) -> str:
    """Return a normalized relative path inside a project, or raise."""
    if not isinstance(rel, str):
        raise PolicyError("INVALID_PATH", "tipo")
    rel = rel.strip()
    if rel in ("", ".", "./"):
        if allow_root:
            return ""
        raise PolicyError("INVALID_PATH", "vuoto")
    if len(rel) > MAX_REL_LEN or "\x00" in rel or "\\" in rel or "\n" in rel:
        raise PolicyError("INVALID_PATH", "caratteri non ammessi")
    if rel.startswith("/") or rel.startswith("~"):
        raise PolicyError("PATH_OUTSIDE_PROJECT", "percorso assoluto")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise PolicyError("PATH_OUTSIDE_PROJECT", "componenti non ammessi")
    if len(parts) > MAX_REL_DEPTH:
        raise PolicyError("INVALID_PATH", "troppo profondo")
    for p in parts:
        if p.startswith(".") and p not in _ALLOWED_HIDDEN:
            raise PolicyError("INVALID_PATH", "file/directory nascosti non ammessi")
        if not (_COMPONENT_RE.match(p) or p in _ALLOWED_HIDDEN):
            raise PolicyError("INVALID_PATH", "nome non ammesso")
    base = parts[-1].lower()
    if base in _DENIED_BASENAMES or base.endswith(_DENIED_SUFFIXES) or base.startswith(".env"):
        raise PolicyError("DENIED_FILE", base)
    normalized = posixpath.normpath(rel)
    if normalized != rel:
        raise PolicyError("INVALID_PATH", "percorso non normalizzato")
    return rel


def project_path(root: str, project: str) -> str:
    validate_project_name(project)
    return posixpath.join(root, project)


def file_path(root: str, project: str, rel: str, allow_root: bool = False) -> str:
    base = project_path(root, project)
    rel = validate_relpath(rel, allow_root=allow_root)
    full = posixpath.join(base, rel) if rel else base
    # Belt and braces: the joined path must still be under the project directory.
    if not (full == base or full.startswith(base + "/")):
        raise PolicyError("PATH_OUTSIDE_PROJECT")
    return full


def snapshot_parent(root: str, project: str) -> str:
    validate_project_name(project)
    return posixpath.join(root, SNAPSHOT_DIR, project)


def snapshot_path(root: str, project: str, uid: str) -> str:
    return posixpath.join(snapshot_parent(root, project), validate_uid(uid))


def trash_path(root: str, project: str, uid: str) -> str:
    validate_project_name(project)
    return posixpath.join(root, TRASH_DIR, f"{project}-{validate_uid(uid)}")


def test_command(kind: str) -> str:
    cmd = TEST_COMMANDS.get(kind)
    if not cmd:
        raise PolicyError("TEST_KIND_NOT_ALLOWED", str(kind)[:40])
    return cmd


def check_content(content: str) -> str:
    if not isinstance(content, str):
        raise PolicyError("INVALID_CONTENT")
    if "\x00" in content:
        raise PolicyError("INVALID_CONTENT", "byte nullo")
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise PolicyError("FILE_TOO_LARGE")
    return content
