from __future__ import annotations

# LOCAL MIRROR of team_core_v2.py (CoordinatorV2 copied verbatim; adapters stubbed).

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional

from team_core import (
    OFFLINE,
    ONLINE,
    QUOTA,
    UNCONFIGURED,
    AtomicState,
    ProviderAdapter,
    ProviderResult,
)

DORMANT = "DORMANT"
ACTIVE_TEAM_PROVIDERS = ("codex", "claude", "grok")
ALL_PROVIDER_NAMES = ("gemini", "codex", "claude", "grok")
LOG = logging.getLogger("andrea-ai-team-v2")


class ClaudeAdapter(ProviderAdapter):
    name = "claude"


class GrokAdapter(ProviderAdapter):
    name = "grok"


class CoordinatorV2:
    def __init__(self, state: AtomicState, providers: Dict[str, ProviderAdapter], synthesize: bool = True):
        self.state = state
        self.providers = providers
        self.synthesize = bool(synthesize)

    def statuses(self, force: bool = False) -> Dict[str, str]:
        result: Dict[str, str] = {"gemini": DORMANT}
        active = [name for name in ACTIVE_TEAM_PROVIDERS if name in self.providers]
        if not active:
            return result
        with ThreadPoolExecutor(max_workers=len(active), thread_name_prefix="health") as pool:
            futures = {pool.submit(self.providers[name].health, force): name for name in active}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result[name] = future.result()
                except Exception:
                    result[name] = OFFLINE
        return result

    def _run_parallel(self, user_prompt: str, cancel_event: threading.Event) -> Dict[str, ProviderResult]:
        results: Dict[str, ProviderResult] = {}
        with ThreadPoolExecutor(max_workers=len(ACTIVE_TEAM_PROVIDERS), thread_name_prefix="team-provider") as pool:
            futures = {
                pool.submit(self.providers[name].run, user_prompt, cancel_event): name
                for name in ACTIVE_TEAM_PROVIDERS
                if name in self.providers
            }
            for future in as_completed(futures):
                name = futures[future]
                if cancel_event.is_set():
                    continue
                try:
                    results[name] = future.result()
                except Exception:
                    LOG.exception("provider %s failed in team fan-out", name)
                    results[name] = ProviderResult(False, "", name, error_code="PROVIDER_EXCEPTION")
        return results

    @staticmethod
    def _fallback_team_text(results: Dict[str, ProviderResult]) -> str:
        labels = {"codex": "ChatGPT/Codex", "claude": "Claude", "grok": "Grok"}
        sections: list[str] = []
        for name in ACTIVE_TEAM_PROVIDERS:
            result = results.get(name)
            if result is None:
                continue
            label = labels[name]
            if result.ok:
                sections.append(f"{label}:\n{result.text.strip()}")
            else:
                sections.append(f"{label}: {result.error_code or 'ERROR'}")
        return "\n\n".join(sections).strip()

    def _synthesize(self, user_prompt, successful, cancel_event) -> Optional[ProviderResult]:
        if not self.synthesize or len(successful) < 2 or cancel_event.is_set():
            return None
        synthesizer_name = next((n for n in ("codex", "claude", "grok") if n in successful), None)
        if synthesizer_name is None:
            return None
        labels = {"codex": "CHATGPT/CODEX", "claude": "CLAUDE", "grok": "GROK"}
        reviews = [f"{labels[n]} OUTPUT:\n{successful[n].text}" for n in ACTIVE_TEAM_PROVIDERS if n in successful]
        synthesis_prompt = (
            "Produce the single final answer to the user's original request using the "
            "independent outputs below.\n\nORIGINAL USER REQUEST:\n" + user_prompt + "\n\n" + "\n\n".join(reviews)
        )
        result = self.providers[synthesizer_name].run(synthesis_prompt, cancel_event)
        if result.ok:
            result.provider = "team"
            return result
        return None

    def execute(self, user_prompt, mode, cancel_event, direct_provider=None) -> ProviderResult:
        if cancel_event.is_set():
            return ProviderResult(False, "", "team", cancelled=True, error_code="CANCELLED")
        if direct_provider:
            if direct_provider == "gemini":
                return ProviderResult(False, "Gemini is DORMANT.", "gemini", unconfigured=True, error_code=DORMANT)
            provider = self.providers.get(direct_provider)
            if provider is None:
                return ProviderResult(False, f"{direct_provider} UNCONFIGURED", direct_provider,
                                      unconfigured=True, error_code=UNCONFIGURED)
            return provider.run(user_prompt, cancel_event)
        if mode == "fast":
            statuses = self.statuses(force=False)
            for name in ACTIVE_TEAM_PROVIDERS:
                if statuses.get(name) == ONLINE:
                    return self.providers[name].run(user_prompt, cancel_event)
            return ProviderResult(False, "Nessun provider attivo disponibile.", "team", error_code="NO_PROVIDER")
        results = self._run_parallel(user_prompt, cancel_event)
        if cancel_event.is_set():
            return ProviderResult(False, "", "team", cancelled=True, error_code="CANCELLED")
        successful = {n: r for n, r in results.items() if r.ok}
        if not successful:
            text = self._fallback_team_text(results)
            return ProviderResult(False, text or "Nessun provider del team disponibile.", "team", error_code="NO_PROVIDER")
        synthesized = self._synthesize(user_prompt, successful, cancel_event)
        if synthesized is not None:
            return synthesized
        if len(successful) == 1:
            return next(iter(successful.values()))
        return ProviderResult(True, self._fallback_team_text(results), "team")
