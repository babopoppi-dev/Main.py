from __future__ import annotations

"""
ANDREA AI TEAM v3 - Telegram orchestrator with controlled write gate.

Extends TeamServiceV2 (the live v2 behaviour is preserved unchanged for normal
analysis messages) with:
- persistent job history for every request (SQLite/WAL);
- Project Builder jobs: /crea, /modifica and natural-language build requests;
- /incorso /ultimo /lavori /storico /lavoro /annulla /progetti /aiuto.

Owner authorization is checked before any job, provider or MCP activity.
"""

import logging
import os
import re
import threading
import time
from typing import Any, Optional

import gate_policy as policy
from job_format import format_active, format_detail, format_final, format_list
from job_store import (
    ANALYZING, CANCELLED, COMPLETED, FAILED, QUEUED, InvalidTransition, JobStore,
)
from mcp_helper import RestrictedMCPHelper
from project_builder import AGENTS, BuilderConfig, JobManager, ProviderPool, SerializedAdapter
from redact import sanitize
from service import _int_env
from service_v2 import (
    EXPECTED_BOT_USERNAME, EXPECTED_OWNER_ID, TeamServiceV2, TelegramClientV2, _validate_bot_identity,
)
from team_core import AtomicState
from team_core_v2 import CoordinatorV2, DORMANT
from write_gate import GateError, WriteGateClient


LOG = logging.getLogger("andrea-ai-team-v3")

V3_COMMANDS = {
    "/incorso", "/ultimo", "/lavori", "/storico", "/lavoro", "/annulla", "/crea", "/modifica",
    "/progetti", "/aiuto", "/help",
}

_CREATE_RE = re.compile(
    r"^\s*(?:@team\s+)?(crea|creami|genera|sviluppa|scrivi|realizza|costruisci|programma)\b"
    r".{0,200}?\b(programma|programmino|app|applicazione|script|progetto|tool|software|gestionale|cli|bot|"
    r"libreria|modulo|servizio|task\s*manager)\b",
    re.I | re.S,
)
_MODIFY_RE = re.compile(
    r"\b(?:nel|al|del|sul)\s+progetto\s+`?([A-Za-z0-9_-]{2,40})`?",
    re.I,
)
_MODIFY_VERBS = re.compile(
    r"\b(aggiungi|modifica|correggi|aggiorna|estendi|implementa|rifattorizza|sistema|migliora|rimuovi|elimina)\b",
    re.I,
)


def detect_build_intent(text: str) -> Optional[tuple[str, Optional[str], str]]:
    """Return (operation, project, request) for natural-language build requests."""
    body = (text or "").strip()
    if not body or body.startswith("/"):
        return None
    if body.lower().startswith("@team "):
        body = body[6:].strip()
    m = _MODIFY_RE.search(body)
    if m and _MODIFY_VERBS.search(body):
        return "modifica", m.group(1).lower(), body
    if _CREATE_RE.search(body):
        return "crea", None, body
    return None


HELP_TEXT = (
    "ANDREA AI TEAM v3 - comandi\n"
    "Sviluppo (via MCP Andrea, solo area progetti TEAM):\n"
    "/crea <richiesta>  oppure  /crea nome_progetto: <richiesta>\n"
    "/modifica <nome_progetto> <richiesta>\n"
    "oppure in linguaggio naturale: \"Crea un programma Python per...\", "
    "\"Nel progetto clienti_app aggiungi...\"\n"
    "Lavori:\n"
    "/incorso - lavori in corso\n"
    "/ultimo - ultimo lavoro\n"
    "/lavori - elenco recente\n"
    "/storico [pN | <id> | <progetto>] - storico\n"
    "/lavoro <id> - dettaglio\n"
    "/annulla <id> - annulla un lavoro\n"
    "/progetti - progetti del TEAM\n"
    "Analisi: un normale messaggio va a Codex + Claude + Grok.\n"
    "/stato /stop /riprendi /team /veloce /chatgpt /claude /grok"
)


class TeamServiceV3(TeamServiceV2):
    def __init__(self, *args: Any, jobs: JobStore, manager: Optional[JobManager],
                 gate: Optional[WriteGateClient], write_gate_enabled: bool, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.jobs = jobs
        self.manager = manager
        self.gate = gate
        self.write_gate_enabled = bool(write_gate_enabled and manager is not None and gate is not None)
        self._current_message: Optional[dict[str, Any]] = None
        self._analysis_job_id: Optional[int] = None
        self._analysis_lock = threading.Lock()

    # -- provider observation for analysis jobs ----------------------------------

    def observe_agent(self, agent: str, state: str) -> None:
        with self._analysis_lock:
            job_id = self._analysis_job_id
        if job_id is not None and agent in AGENTS:
            try:
                self.jobs.set_agent(job_id, agent, state)
            except Exception:
                pass

    # -- status ----------------------------------------------------------------------

    def _gate_status(self) -> str:
        if not self.write_gate_enabled:
            return "OFF"
        try:
            self.gate.status()  # type: ignore[union-attr]
            return "ON (solo area progetti TEAM, via MCP Andrea)"
        except GateError as exc:
            return f"DEGRADED ({exc.code})"

    def _status_text(self) -> str:
        text = super()._status_text()
        text = text.replace("Write gate MCP: OFF", f"Write Gate MCP: {self._gate_status()}")
        text = text.replace("READ ONLY: ON", "READ ONLY: ON (fuori dall'area progetti TEAM)")
        active = self.jobs.active()
        builds = [j for j in active if j.kind == "build"]
        return text + f"\nLavori di sviluppo attivi: {len(builds)}"

    # -- analysis jobs are recorded too ------------------------------------------------

    def _start_job(self, chat_id: int, prompt: str, mode: str, direct_provider: Optional[str] = None) -> bool:
        with self._job_lock:
            if self._job_thread is not None and self._job_thread.is_alive():
                return False
            msg = self._current_message or {}
            mid = msg.get("message_id")
            idem = f"tg:{chat_id}:{mid}" if mid is not None else None
            if direct_provider:
                operation = f"analisi diretta {direct_provider}"
            else:
                operation = "analisi veloce" if mode == "fast" else "analisi team"
            job, created = self.jobs.create(user_id=self.allowed_user_id, chat_id=chat_id, request=prompt,
                                            kind="analysis", operation=operation, idem_key=idem)
            if not created:
                self._send(chat_id, f"Messaggio gia' elaborato come lavoro #{job.job_id}.")
                return True
            cancel = threading.Event()
            self._job_cancel = cancel
            self._job_chat = chat_id
            self._job_seq += 1
            seq = self._job_seq
            job_id = job.job_id

            def target() -> None:
                with self._analysis_lock:
                    self._analysis_job_id = job_id
                try:
                    self.jobs.transition(job_id, ANALYZING, "analisi in corso")
                    result = self.coordinator.execute(prompt, mode=mode, cancel_event=cancel,
                                                      direct_provider=direct_provider)
                    if cancel.is_set() or result.cancelled:
                        self.jobs.transition(job_id, CANCELLED, "interrotto")
                        self._send(chat_id, "Lavoro interrotto.")
                        return
                    self.jobs.update(job_id, result_summary=sanitize(result.text or result.error_code, 1500))
                    if result.ok:
                        self.jobs.transition(job_id, COMPLETED, "completato")
                        self._send(chat_id, result.text)
                    else:
                        self.jobs.add_error(job_id, result.error_code or "ERROR")
                        self.jobs.transition(job_id, FAILED, "nessuna risposta utile")
                        self._send(chat_id, result.text or f"Operazione non disponibile ({result.error_code}).")
                except Exception as exc:
                    LOG.error("analysis job failed: %s", type(exc).__name__)
                    try:
                        self.jobs.add_error(job_id, f"errore interno {type(exc).__name__}")
                        self.jobs.transition(job_id, FAILED, "errore interno")
                    except InvalidTransition:
                        pass
                    if not cancel.is_set():
                        self._send(chat_id, "Errore interno del team. Nessuna modifica operativa e stata eseguita.")
                finally:
                    with self._analysis_lock:
                        self._analysis_job_id = None
                    try:
                        final = self.jobs.get(job_id)
                        if final is not None:
                            for agent in AGENTS:
                                if final.agent_state(agent) == "WAITING":
                                    self.jobs.set_agent(job_id, agent, "SKIPPED")
                    except Exception:
                        pass
                    with self._job_lock:
                        if seq == self._job_seq:
                            self._job_cancel = None
                            self._job_chat = None
                            self._job_thread = None

            thread = threading.Thread(target=target, name=f"ai-job-{seq}", daemon=True)
            self._job_thread = thread
            thread.start()
            return True

    # -- update handling ------------------------------------------------------------------

    def handle_update(self, update: dict[str, Any]) -> None:
        try:
            update_id = int(update.get("update_id", -1))
        except Exception:
            return
        if update_id <= int(self.state.snapshot().get("last_update_id", -1)):
            return
        message = update.get("message")
        # Owner check FIRST. Anything not from the owner goes to the v2 path, which
        # only advances the offset and ignores it.
        if not isinstance(message, dict) or not self._authorized(message):
            super().handle_update(update)
            return
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            super().handle_update(update)
            return
        command, arg = self._parse_command(text)
        intent = None if command else detect_build_intent(text)
        if command in V3_COMMANDS or intent is not None:
            self.state.set_offset(update_id)
            chat_id = int((message.get("chat") or {}).get("id"))
            try:
                self._handle_v3(chat_id, message, command, arg, intent)
            except Exception as exc:
                LOG.error("v3 command failed: %s", type(exc).__name__)
                self._send(chat_id, "Errore interno nel comando. Nessuna modifica eseguita.")
            return
        if command == "/stop" and self.manager is not None:
            n = self.manager.cancel_all()
            if n:
                chat_id = int((message.get("chat") or {}).get("id"))
                self._send(chat_id, f"Annullamento richiesto per {n} lavori di sviluppo (rollback automatico).")
        self._current_message = message
        try:
            super().handle_update(update)
        finally:
            self._current_message = None

    def _handle_v3(self, chat_id: int, message: dict[str, Any], command: Optional[str], arg: str,
                   intent: Optional[tuple[str, Optional[str], str]]) -> None:
        if command in {"/aiuto", "/help"}:
            self._send(chat_id, HELP_TEXT)
            return
        if command == "/incorso":
            active = self.jobs.active()
            if not active:
                self._send(chat_id, "Nessun lavoro in corso.")
                return
            self._send(chat_id, "\n\n".join(format_active(j) for j in active[:10]))
            return
        if command == "/ultimo":
            job = self.jobs.last()
            self._send(chat_id, format_detail(job) if job else "Nessun lavoro registrato.")
            return
        if command == "/lavori":
            self._send(chat_id, format_list(self.jobs.recent(limit=10), "LAVORI RECENTI"))
            return
        if command == "/storico":
            self._storico(chat_id, arg)
            return
        if command == "/lavoro":
            job_id = self._parse_id(arg)
            job = self.jobs.get(job_id) if job_id else None
            self._send(chat_id, format_detail(job) if job else "Uso: /lavoro <id>")
            return
        if command == "/annulla":
            self._annulla(chat_id, arg)
            return
        if command == "/progetti":
            self._progetti(chat_id)
            return
        # Build requests ------------------------------------------------------------------
        if command == "/crea":
            if not arg:
                self._send(chat_id, "Uso: /crea <richiesta>  oppure  /crea nome_progetto: <richiesta>")
                return
            project = None
            request = arg
            m = re.match(r"^([A-Za-z0-9_-]{2,40}):\s+(.+)$", arg, re.S)
            if m:
                project, request = m.group(1).lower(), m.group(2).strip()
            self._submit_build(chat_id, message, "crea", project, request)
            return
        if command == "/modifica":
            parts = arg.split(maxsplit=1)
            if len(parts) < 2:
                self._send(chat_id, "Uso: /modifica <nome_progetto> <richiesta>")
                return
            self._submit_build(chat_id, message, "modifica", parts[0].lower().strip("`:"), parts[1].strip())
            return
        if intent is not None:
            operation, project, request = intent
            self._submit_build(chat_id, message, operation, project, request)

    @staticmethod
    def _parse_id(arg: str) -> Optional[int]:
        m = re.match(r"^#?(\d{1,9})$", (arg or "").strip())
        return int(m.group(1)) if m else None

    def _storico(self, chat_id: int, arg: str) -> None:
        arg = (arg or "").strip()
        job_id = self._parse_id(arg)
        if job_id is not None:
            job = self.jobs.get(job_id)
            self._send(chat_id, format_detail(job) if job else f"Lavoro #{job_id} non trovato.")
            return
        page = 1
        project = None
        m = re.match(r"^p(\d{1,4})$", arg, re.I)
        if m:
            page = max(1, int(m.group(1)))
        elif arg:
            project = arg.lower()
        size = 15
        jobs = self.jobs.recent(limit=size, offset=(page - 1) * size, project=project)
        total = self.jobs.count()
        title = f"STORICO pagina {page}" + (f" - progetto {project}" if project else "") + f" (totale {total})"
        text = format_list(jobs, title)
        if len(jobs) == size:
            text += f"\nAltri: /storico p{page + 1}"
        self._send(chat_id, text)

    def _annulla(self, chat_id: int, arg: str) -> None:
        job_id = self._parse_id(arg)
        if job_id is None:
            self._send(chat_id, "Uso: /annulla <id>")
            return
        job = self.jobs.get(job_id)
        if job is None:
            self._send(chat_id, f"Lavoro #{job_id} non trovato.")
            return
        if job.kind == "analysis":
            stopped = self._stop_job() if job.state not in {COMPLETED, FAILED, CANCELLED} else False
            self._send(chat_id, f"Analisi #{job_id}: " + ("interruzione richiesta." if stopped else "non attiva."))
            return
        if self.manager is None or not self.manager.cancel(job_id):
            self._send(chat_id, f"Lavoro #{job_id} non e' attivo ({job.state}).")
            return
        self._send(chat_id, f"Annullamento richiesto per il lavoro #{job_id}: rollback automatico in corso.")

    def _progetti(self, chat_id: int) -> None:
        seen: dict[str, Any] = {}
        for job in self.jobs.recent(limit=50):
            if job.kind == "build" and job.project and job.project not in seen:
                seen[job.project] = job
        if not seen:
            self._send(chat_id, "Nessun progetto TEAM registrato.")
            return
        lines = ["PROGETTI TEAM (ultimo lavoro)"]
        for name, job in seen.items():
            lines.append(f"• {name}: #{job.job_id} {job.state}")
        root = self.gate.projects_root if self.gate is not None else policy.DEFAULT_PROJECTS_ROOT
        lines.append(f"Root: {root}")
        self._send(chat_id, "\n".join(lines))

    def _submit_build(self, chat_id: int, message: dict[str, Any], operation: str, project: Optional[str],
                      request: str) -> None:
        if self.state.snapshot().get("paused"):
            self._send(chat_id, "Team in pausa. Usa /riprendi.")
            return
        if not self.write_gate_enabled:
            self._send(chat_id, "Write Gate MCP disattivato: posso solo analizzare. "
                                "Invio la richiesta in analisi al team.")
            self._current_message = message
            try:
                if not self._start_job(chat_id, request, self.default_mode):
                    self._send(chat_id, "Un lavoro AI e gia in corso.")
            finally:
                self._current_message = None
            return
        protected = policy.is_protected_name(project or "") or (
            policy.is_protected_name(request) if operation == "modifica" else None)
        if protected:
            self._send(chat_id, f"Progetto protetto ({protected}): il TEAM non lo modifica automaticamente. "
                                "Serve l'autorizzazione prevista dalle regole esistenti.")
            return
        if project:
            try:
                policy.validate_project_name(project)
            except policy.PolicyError as exc:
                self._send(chat_id, f"Nome progetto non valido ({exc.code}). Usa 2-40 caratteri a-z 0-9 _ -")
                return
        mid = message.get("message_id")
        idem = f"tg:{chat_id}:{mid}" if mid is not None else None
        if idem:
            seen = self.jobs.get_by_idem(idem)
            if seen is not None:
                self._send(chat_id, f"Messaggio gia' elaborato come lavoro #{seen.job_id} ({seen.state}).")
                return
        dup = self.jobs.find_active_duplicate(chat_id, request)
        if dup is not None:
            self._send(chat_id, f"Richiesta identica gia' in corso: lavoro #{dup.job_id} ({dup.state}).")
            return
        job, created = self.manager.submit(user_id=self.allowed_user_id, chat_id=chat_id,  # type: ignore[union-attr]
                                           request=request, operation=operation, project=project,
                                           idem_key=idem)
        if not created:
            self._send(chat_id, f"Messaggio gia' elaborato come lavoro #{job.job_id} ({job.state}).")
            return
        target = project or "(nome deciso dal team)"
        self._send(chat_id, f"🟡 LAVORO #{job.job_id} accettato - {operation} progetto {target}.\n"
                            "Codex + Claude + Grok analizzano; Codex sviluppa; test reali via MCP Andrea.\n"
                            "Segui con /incorso.")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_config_from_env() -> BuilderConfig:
    cfg = BuilderConfig()
    for field_name, env in (
        ("max_fix_attempts", "TEAM_MAX_FIX_ATTEMPTS"),
        ("max_concurrent_jobs", "TEAM_MAX_CONCURRENT_JOBS"),
        ("job_timeout", "TEAM_JOB_TIMEOUT"),
        ("executor_timeout", "TEAM_EXECUTOR_TIMEOUT"),
        ("test_timeout", "TEAM_TEST_TIMEOUT"),
    ):
        val = _int_env(env)
        if val is not None:
            setattr(cfg, field_name, max(1, val))
    cfg.max_fix_attempts = min(cfg.max_fix_attempts, 6)
    cfg.max_concurrent_jobs = min(cfg.max_concurrent_jobs, 3)
    cfg.review_enabled = _env_flag("TEAM_REVIEW_ENABLED", True)
    return cfg


def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from worker_client_v2 import RemoteProviderAdapterV2

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    allowed_user_id = _int_env("TELEGRAM_ALLOWED_USER_ID", required=True)
    allowed_chat_id = _int_env("TELEGRAM_ALLOWED_CHAT_ID", required=False)
    expected_owner_id = _int_env("TEAM_OWNER_TELEGRAM_ID", required=False) or EXPECTED_OWNER_ID
    if int(allowed_user_id) != int(expected_owner_id):
        raise RuntimeError("TELEGRAM_ALLOWED_USER_ID does not match the configured owner")

    state = AtomicState(os.environ.get("STATE_FILE", "/var/lib/andrea-ai-team/state/state.json"))
    state.update(read_only=True)
    jobs = JobStore(os.environ.get("JOBS_DB", "/var/lib/andrea-ai-team/state/jobs.sqlite3"))

    provider_socket = os.environ.get("PROVIDER_SOCKET", "/run/andrea-ai-team/provider.sock")
    raw = {name: RemoteProviderAdapterV2(name, provider_socket) for name in ("gemini", "codex", "claude", "grok")}
    pool = ProviderPool({name: raw[name] for name in AGENTS})

    telegram = TelegramClientV2(token)
    expected_bot = os.environ.get("TELEGRAM_BOT_USERNAME", EXPECTED_BOT_USERNAME)
    _validate_bot_identity(telegram, expected_bot)

    write_gate_enabled = _env_flag("WRITE_GATE_ENABLED", False)
    gate = WriteGateClient() if write_gate_enabled else None

    holder: dict[str, TeamServiceV3] = {}

    def observer(agent: str, st: str) -> None:
        svc = holder.get("svc")
        if svc is not None:
            svc.observe_agent(agent, st)

    adapters: dict[str, Any] = {"gemini": raw["gemini"]}
    adapters.update({name: SerializedAdapter(pool, name, observer) for name in AGENTS})
    synthesize = os.environ.get("TEAM_SYNTHESIS", "1").strip().lower() not in {"0", "false", "no", "off"}
    coordinator = CoordinatorV2(state, adapters, synthesize=synthesize)

    def notify(chat_id: int, text: str) -> None:
        svc = holder.get("svc")
        if svc is not None:
            svc._send(chat_id, text)

    manager = JobManager(jobs, gate, pool, notify, build_config_from_env()) if gate is not None else None

    service = TeamServiceV3(
        telegram=telegram,
        allowed_user_id=int(allowed_user_id),
        allowed_chat_id=allowed_chat_id,
        state=state,
        coordinator=coordinator,
        mcp=RestrictedMCPHelper(),
        default_mode=os.environ.get("DEFAULT_MODE", "team"),
        jobs=jobs,
        manager=manager,
        gate=gate,
        write_gate_enabled=write_gate_enabled,
    )
    holder["svc"] = service

    if manager is not None:
        for _ in range(15):
            try:
                gate.status()  # type: ignore[union-attr]
                break
            except GateError:
                time.sleep(2)
        for job_id, what in manager.recover_on_start():
            LOG.info("recovered job %s: %s", job_id, what)
        manager.start()
    else:
        # Analysis-only mode: still never leave stale active rows after a restart.
        for job in jobs.active():
            try:
                jobs.transition(job.job_id, FAILED if job.state != QUEUED else CANCELLED,
                                "interrotto da riavvio")
            except InvalidTransition:
                pass

    LOG.info("ANDREA AI TEAM v3 starting bot=@%s owner_id=%s gemini=%s write_gate=%s",
             expected_bot.lstrip("@"), int(allowed_user_id), DORMANT, "ON" if manager else "OFF")
    service.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
