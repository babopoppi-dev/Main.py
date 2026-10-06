from __future__ import annotations

# LOCAL MIRROR of service.py (base TelegramClient/TeamService), copied from the workspace.

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from mcp_helper import RestrictedMCPHelper
from team_core import AtomicState, Coordinator, UNCONFIGURED


LOG = logging.getLogger("andrea-ai-team")


def _int_env(name: str, required: bool = False) -> Optional[int]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        if required:
            raise RuntimeError(f"{name} is required")
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


class TelegramClient:
    def __init__(self, token: str, timeout: int = 60):
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        self._token = token
        self._base = "https://api.telegram.org/bot" + token + "/"
        self.timeout = timeout

    def _call(self, method: str, payload: dict[str, Any], timeout: Optional[int] = None) -> Any:
        raise RuntimeError("network disabled in local mirror")

    def get_updates(self, offset: int, timeout: int = 50) -> list[dict[str, Any]]:
        result = self._call("getUpdates", {"offset": offset, "timeout": timeout,
                                           "allowed_updates": json.dumps(["message"])}, timeout=timeout + 10)
        return result if isinstance(result, list) else []

    def send_message(self, chat_id: int, text: str) -> None:
        self._call("sendMessage", {"chat_id": str(chat_id), "text": text}, timeout=20)


class TeamService:
    def __init__(
        self,
        telegram: TelegramClient,
        allowed_user_id: int,
        state: AtomicState,
        coordinator: Coordinator,
        mcp: RestrictedMCPHelper,
        allowed_chat_id: Optional[int] = None,
        default_mode: str = "team",
    ):
        self.telegram = telegram
        self.allowed_user_id = allowed_user_id
        self.allowed_chat_id = allowed_chat_id
        self.state = state
        self.coordinator = coordinator
        self.mcp = mcp
        self.default_mode = "fast" if default_mode == "fast" else "team"
        self._job_lock = threading.Lock()
        self._job_thread: Optional[threading.Thread] = None
        self._job_cancel: Optional[threading.Event] = None
        self._job_chat: Optional[int] = None
        self._job_seq = 0

    def _authorized(self, message: dict[str, Any]) -> bool:
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        if int(sender.get("id", -1)) != self.allowed_user_id:
            return False
        if chat.get("type") != "private":
            return False
        chat_id = int(chat.get("id", -1))
        if self.allowed_chat_id is not None and chat_id != self.allowed_chat_id:
            return False
        return True

    def _send(self, chat_id: int, text: str) -> None:
        try:
            self.telegram.send_message(chat_id, text)
        except Exception as exc:
            LOG.warning("send_message failed: %s", type(exc).__name__)

    def _is_busy(self) -> bool:
        with self._job_lock:
            return self._job_thread is not None and self._job_thread.is_alive()

    def _parse_command(self, text: str) -> tuple[Optional[str], str]:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return None, stripped
        first, *rest = stripped.split(maxsplit=1)
        command = first.split("@", 1)[0].lower()
        arg = rest[0].strip() if rest else ""
        return command, arg

    def _start_job(self, chat_id: int, prompt: str, mode: str, direct_provider: Optional[str] = None) -> bool:
        with self._job_lock:
            if self._job_thread is not None and self._job_thread.is_alive():
                return False
            cancel = threading.Event()
            self._job_cancel = cancel
            self._job_chat = chat_id
            self._job_seq += 1
            seq = self._job_seq

            def target() -> None:
                try:
                    result = self.coordinator.execute(prompt, mode=mode, cancel_event=cancel,
                                                      direct_provider=direct_provider)
                    if cancel.is_set() or result.cancelled:
                        self._send(chat_id, "Lavoro interrotto.")
                        return
                    if result.ok:
                        self._send(chat_id, result.text)
                    else:
                        self._send(chat_id, result.text or f"Operazione non disponibile ({result.error_code}).")
                except Exception as exc:
                    LOG.error("job failed: %s", type(exc).__name__)
                    if not cancel.is_set():
                        self._send(chat_id, "Errore interno del team. Nessuna modifica operativa e stata eseguita.")
                finally:
                    with self._job_lock:
                        if seq == self._job_seq:
                            self._job_cancel = None
                            self._job_chat = None
                            self._job_thread = None

            thread = threading.Thread(target=target, name=f"ai-job-{seq}", daemon=True)
            self._job_thread = thread
            thread.start()
            return True

    def _stop_job(self) -> bool:
        with self._job_lock:
            active = self._job_thread is not None and self._job_thread.is_alive()
            if self._job_cancel is not None:
                self._job_cancel.set()
            return active

    def handle_update(self, update: dict[str, Any]) -> None:
        raise NotImplementedError("mirror: overridden by TeamServiceV2")

    def run_forever(self) -> None:
        LOG.info("ANDREA AI TEAM starting; read-only=on write-gate=off")
        backoff = 2
        while True:
            try:
                offset = int(self.state.snapshot().get("last_update_id", -1)) + 1
                updates = self.telegram.get_updates(offset=offset, timeout=50)
                for update in updates:
                    self.handle_update(update)
                backoff = 2
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                LOG.warning("polling error: %s", type(exc).__name__)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
