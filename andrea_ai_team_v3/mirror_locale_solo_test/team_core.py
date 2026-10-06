from __future__ import annotations

# LOCAL MIRROR of /var/lib/central-mcp-vps-agent-test/workspace/andrea-ai-team/team_core.py
# (subset sufficient for offline tests; never deployed)

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


ONLINE = "ONLINE"
QUOTA = "QUOTA/COOLDOWN"
OFFLINE = "OFFLINE"
UNCONFIGURED = "UNCONFIGURED"
VALID_STATUSES = {ONLINE, QUOTA, OFFLINE, UNCONFIGURED}


@dataclass
class ProviderResult:
    ok: bool
    text: str
    provider: str
    cancelled: bool = False
    quota: bool = False
    unconfigured: bool = False
    error_code: str = ""


class AtomicState:
    DEFAULTS: Dict[str, Any] = {
        "last_update_id": -1,
        "paused": False,
        "read_only": True,
        "armed_mode": None,
        "armed_provider": None,
        "cooldowns": {},
        "provider_status": {},
        "provider_status_checked_at": {},
    }

    def __init__(self, path: str):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = dict(self.DEFAULTS)
        self._load()

    def _load(self) -> None:
        with self.lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data.update(raw)
            except FileNotFoundError:
                pass
            except Exception:
                self.data = dict(self.DEFAULTS)
            self.data["read_only"] = True
            self._save_locked()

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, sort_keys=True, indent=2)
        fd, tmp = tempfile.mkstemp(prefix=".state-", dir=str(self.path.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except Exception:
                pass

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.data))

    def update(self, **changes: Any) -> Dict[str, Any]:
        with self.lock:
            if "last_update_id" in changes:
                incoming = int(changes["last_update_id"])
                current = int(self.data.get("last_update_id", -1))
                changes["last_update_id"] = max(incoming, current)
            if "read_only" in changes:
                changes["read_only"] = True
            self.data.update(changes)
            self._save_locked()
            return self.snapshot()

    def set_offset(self, update_id: int) -> int:
        with self.lock:
            current = int(self.data.get("last_update_id", -1))
            if update_id > current:
                self.data["last_update_id"] = int(update_id)
                self._save_locked()
            return int(self.data["last_update_id"])

    def cooldown_until(self, provider: str) -> float:
        with self.lock:
            return float(self.data.get("cooldowns", {}).get(provider, 0.0) or 0.0)

    def set_cooldown(self, provider: str, seconds: int) -> None:
        with self.lock:
            c = dict(self.data.get("cooldowns", {}))
            c[provider] = max(float(c.get(provider, 0.0) or 0.0), time.time() + seconds)
            self.data["cooldowns"] = c
            self._save_locked()

    def set_provider_status(self, provider: str, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(status)
        with self.lock:
            s = dict(self.data.get("provider_status", {}))
            t = dict(self.data.get("provider_status_checked_at", {}))
            s[provider] = status
            t[provider] = time.time()
            self.data["provider_status"] = s
            self.data["provider_status_checked_at"] = t
            self._save_locked()

    def cached_provider_status(self, provider: str, ttl: int) -> Optional[str]:
        with self.lock:
            checked = float(self.data.get("provider_status_checked_at", {}).get(provider, 0.0) or 0.0)
            status = self.data.get("provider_status", {}).get(provider)
            if status in VALID_STATUSES and checked and (time.time() - checked) <= ttl:
                return str(status)
            return None


def _contains_quota(text: str) -> bool:
    low = text.lower()
    needles = (
        "quota", "rate limit", "rate-limit", "too many requests", "resource exhausted",
        "resource_exhausted", "429", "usage limit", "limit reached",
    )
    return any(x in low for x in needles)


def _contains_auth_problem(text: str) -> bool:
    low = text.lower()
    needles = (
        "not logged in", "sign in", "sign-in", "authenticate", "authentication",
        "credential", "unauthorized", "login required", "auth method",
        "no suitable authentication", "please login", "please log in",
        "unsupported_client", "unsupported client",
    )
    return any(x in low for x in needles)


def _health_failure_signature(code: int, text: str) -> str:
    return f"RC_{code}"


def _clean_text(text: str, limit: int = 24000) -> str:
    text = text.replace("\x00", "")
    if len(text) > limit:
        return text[-limit:]
    return text


def _extract_json_text(obj: Any) -> Optional[str]:
    if isinstance(obj, str):
        return obj.strip() or None
    if isinstance(obj, list):
        parts = []
        for item in obj:
            found = _extract_json_text(item)
            if found:
                parts.append(found)
        return "\n".join(parts).strip() or None
    if isinstance(obj, dict):
        for key in ("response", "output_text", "final_output", "final", "answer", "text"):
            if key in obj:
                found = _extract_json_text(obj[key])
                if found:
                    return found
        for key in ("content", "message", "result", "output"):
            if key in obj:
                found = _extract_json_text(obj[key])
                if found:
                    return found
    return None


class ProviderAdapter:
    name = "provider"

    def __init__(self, state, binary, team_home, gemini_home, codex_home, provider_path, workdir, status_ttl=600):
        self.state = state
        self.binary = binary
        self.team_home = team_home
        self.gemini_home = gemini_home
        self.codex_home = codex_home
        self.provider_path = provider_path
        self.workdir = workdir
        self.status_ttl = status_ttl
        self._status_lock = threading.Lock()

    def executable(self) -> Optional[str]:
        if os.path.isabs(self.binary):
            return self.binary if os.access(self.binary, os.X_OK) else None
        return shutil.which(self.binary, path=self.provider_path)

    def _run_process(self, argv, timeout, cancel_event=None):
        raise RuntimeError("provider sandbox unavailable in local mirror")

    def health(self, force: bool = False) -> str:
        if self.state.cooldown_until(self.name) > time.time():
            return QUOTA
        if not self.executable():
            self.state.set_provider_status(self.name, OFFLINE)
            return OFFLINE
        with self._status_lock:
            status = self._probe_health()
            self.state.set_provider_status(self.name, status)
            return status

    def _probe_health(self) -> str:
        raise NotImplementedError

    def run(self, prompt: str, cancel_event: threading.Event, timeout: int = 240) -> ProviderResult:
        raise NotImplementedError

    def mark_runtime_failure(self, combined: str) -> str:
        if _contains_quota(combined):
            self.state.set_cooldown(self.name, 15 * 60)
            self.state.set_provider_status(self.name, QUOTA)
            return QUOTA
        if _contains_auth_problem(combined):
            self.state.set_provider_status(self.name, UNCONFIGURED)
            return UNCONFIGURED
        self.state.set_provider_status(self.name, OFFLINE)
        return OFFLINE


class GeminiAdapter(ProviderAdapter):
    name = "gemini"


class CodexAdapter(ProviderAdapter):
    name = "codex"


class Coordinator:
    def __init__(self, state, providers):
        self.state = state
        self.providers = providers
