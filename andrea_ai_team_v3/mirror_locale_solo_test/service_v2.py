from __future__ import annotations

# LOCAL MIRROR of service_v2.py (logic copied from the workspace; formatting compacted).

import logging
import os
from typing import Any, Optional

from mcp_helper import RestrictedMCPHelper
from service import TelegramClient, TeamService, _int_env
from team_core import AtomicState, UNCONFIGURED
from team_core_v2 import CoordinatorV2, DORMANT


LOG = logging.getLogger("andrea-ai-team-v2")
EXPECTED_OWNER_ID = 1090463042
EXPECTED_BOT_USERNAME = "teamandreabot"


class TelegramClientV2(TelegramClient):
    def get_me(self) -> dict[str, Any]:
        result = self._call("getMe", {}, timeout=20)
        return result if isinstance(result, dict) else {}


class TeamServiceV2(TeamService):
    def _status_text(self) -> str:
        statuses = self.coordinator.statuses(force=False)
        mcp = self.mcp.status()
        snap = self.state.snapshot()
        paused = "SI" if snap.get("paused") else "NO"
        busy = "SI" if self._is_busy() else "NO"
        return (
            "ANDREA AI TEAM\n"
            f"Gemini: {DORMANT}\n"
            f"ChatGPT/Codex: {statuses.get('codex', UNCONFIGURED)}\n"
            f"Claude: {statuses.get('claude', UNCONFIGURED)}\n"
            f"Grok: {statuses.get('grok', UNCONFIGURED)}\n"
            f"MCP Andrea: {mcp.status}"
            + (f" ({mcp.detail})" if mcp.detail else "")
            + "\n"
            "READ ONLY: ON\n"
            "Write gate MCP: OFF\n"
            f"Team in pausa: {paused}\n"
            f"Lavoro AI in corso: {busy}"
        )

    @staticmethod
    def _mention_target(text: str) -> tuple[Optional[str], str]:
        stripped = text.strip()
        if not stripped.startswith("@"):
            return None, stripped
        first, *rest = stripped.split(maxsplit=1)
        mapping = {"@chatgpt": "codex", "@codex": "codex", "@claude": "claude",
                   "@grok": "grok", "@gemini": "gemini", "@team": "team"}
        target = mapping.get(first.lower())
        if target is None:
            return None, stripped
        return target, (rest[0].strip() if rest else "")

    def handle_update(self, update: dict[str, Any]) -> None:
        try:
            update_id = int(update.get("update_id", -1))
        except Exception:
            return
        snap = self.state.snapshot()
        if update_id <= int(snap.get("last_update_id", -1)):
            return
        self.state.set_offset(update_id)

        message = update.get("message")
        if not isinstance(message, dict):
            return
        if not self._authorized(message):
            return
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            return
        chat_id = int((message.get("chat") or {}).get("id"))
        command, arg = self._parse_command(text)

        if command in {"/stato", "/status"}:
            self._send(chat_id, self._status_text())
            return
        if command == "/team" and not arg:
            self.state.update(armed_mode="team", armed_provider=None)
            self._send(chat_id, "Modalita TEAM armata: prossimo messaggio a Codex + Claude + Grok.")
            return
        if command == "/veloce" and not arg:
            self.state.update(armed_mode="fast", armed_provider=None)
            self._send(chat_id, "Modalita VELOCE armata per il prossimo messaggio.")
            return
        if command == "/solalettura":
            self.state.update(read_only=True)
            self._send(chat_id, "READ ONLY attivo. Il write gate MCP resta OFF.")
            return
        if command == "/stop":
            active = self._stop_job()
            self.state.update(paused=True)
            self._send(chat_id, "Stop richiesto. Team in pausa." if active else "Team in pausa.")
            return
        if command == "/riprendi":
            self.state.update(paused=False)
            self._send(chat_id, "Team riattivato in READ ONLY.")
            return
        if command == "/gemini":
            self.state.update(armed_provider=None, armed_mode=None)
            self._send(chat_id, "Gemini e DORMANT: resta installata ma non viene invocata.")
            return
        if command in {"/chatgpt", "/claude", "/grok"} and not arg:
            provider = {"/chatgpt": "codex", "/claude": "claude", "/grok": "grok"}[command]
            self.state.update(armed_provider=provider, armed_mode=None)
            self._send(chat_id, f"Agente {provider} armato per il prossimo messaggio.")
            return

        snap = self.state.snapshot()
        if snap.get("paused"):
            self._send(chat_id, "Team in pausa. Usa /riprendi.")
            return
        if self._is_busy():
            self._send(chat_id, "Un lavoro AI e gia in corso. Usa /stop per interromperlo.")
            return

        direct_provider: Optional[str] = None
        mode = self.default_mode
        prompt = arg if command else text.strip()
        if command == "/team":
            mode = "team"
        elif command == "/veloce":
            mode = "fast"
        elif command in {"/chatgpt", "/claude", "/grok"}:
            direct_provider = {"/chatgpt": "codex", "/claude": "claude", "/grok": "grok"}[command]
        elif command:
            self._send(chat_id, "Comando non riconosciuto.")
            return
        else:
            mention_target, mention_prompt = self._mention_target(prompt)
            if mention_target == "gemini":
                self._send(chat_id, "Gemini e DORMANT: resta installata ma non viene invocata.")
                return
            if mention_target == "team":
                mode = "team"
                prompt = mention_prompt
            elif mention_target in {"codex", "claude", "grok"}:
                direct_provider = mention_target
                prompt = mention_prompt
            else:
                armed_provider = snap.get("armed_provider")
                armed_mode = snap.get("armed_mode")
                if armed_provider:
                    direct_provider = str(armed_provider)
                elif armed_mode in {"team", "fast"}:
                    mode = str(armed_mode)
            self.state.update(armed_provider=None, armed_mode=None)

        if not prompt:
            self._send(chat_id, "Messaggio vuoto.")
            return
        if not self._start_job(chat_id, prompt, mode, direct_provider=direct_provider):
            self._send(chat_id, "Un lavoro AI e gia in corso.")


def _validate_bot_identity(telegram: TelegramClientV2, expected_username: str) -> None:
    info = telegram.get_me()
    username = str(info.get("username", "")).strip().lstrip("@").lower()
    expected = expected_username.strip().lstrip("@").lower()
    if not username or username != expected:
        raise RuntimeError("Telegram token does not belong to the expected bot username")
