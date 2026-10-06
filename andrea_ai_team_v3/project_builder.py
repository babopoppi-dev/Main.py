from __future__ import annotations

"""
ANDREA AI TEAM - Project Builder.

Pipeline for one build job (all writes through the MCP write gate):

  request -> persistent job -> Codex + Claude + Grok analysis (parallel)
  -> consolidated plan -> work_session + work_lock (gate) -> snapshot
  -> executor writes files -> real tests (MCP isolated shell, no network)
  -> fix loop (bounded) -> Claude/Grok review -> optional fix -> final test
  -> release, or rollback -> Telegram report

Providers never touch the filesystem: they return text. The orchestrator parses
file blocks, validates every path with gate_policy and asks the gate to write.
"""

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import gate_policy as policy
from job_store import (
    ANALYZING, CANCELLED, COMPLETED, FAILED, QUEUED, REVIEWING, ROLLED_BACK, RUNNING, TESTING,
    Job, JobStore,
)
from redact import sanitize
from write_gate import GateError, WriteGateClient

try:  # the real ProviderResult when running on the VPS / with the mirror
    from team_core import ONLINE, ProviderResult
except Exception:  # pragma: no cover
    ONLINE = "ONLINE"

    @dataclass
    class ProviderResult:  # type: ignore[no-redef]
        ok: bool
        text: str
        provider: str
        cancelled: bool = False
        quota: bool = False
        unconfigured: bool = False
        error_code: str = ""


LOG = logging.getLogger("andrea-ai-team-builder")

EXECUTOR_PREFERENCE = ("codex", "claude", "grok")
AGENTS = ("codex", "claude", "grok")
TEXT_EXTENSIONS = (".py", ".md", ".txt", ".json", ".toml", ".cfg", ".ini", ".csv", ".sql", ".html", ".css",
                   ".js", ".yaml", ".yml", ".sh", ".rst")


@dataclass
class BuilderConfig:
    max_fix_attempts: int = 3
    max_review_fix_rounds: int = 1
    max_concurrent_jobs: int = 2
    job_timeout: int = 2400
    analysis_timeout: int = 300
    executor_timeout: int = 420
    review_timeout: int = 300
    test_timeout: int = 180
    lock_retry: int = 3
    lock_retry_wait: float = 20.0
    heartbeat_interval: float = 120.0
    max_context_chars: int = 45000
    max_auto_resume: int = 1
    review_enabled: bool = True


class JobAbort(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind  # CANCELLED | TIMEOUT | FAILED
        self.detail = detail


# --------------------------------------------------------------------------
# Provider pool: one call at a time per provider CLI, shared by all jobs
# --------------------------------------------------------------------------

class ProviderPool:
    def __init__(self, adapters: dict[str, Any]):
        self.adapters = dict(adapters)
        self._sems = {name: threading.Semaphore(1) for name in self.adapters}

    def health(self, name: str, force: bool = False) -> str:
        adapter = self.adapters.get(name)
        if adapter is None:
            return "UNCONFIGURED"
        try:
            return str(adapter.health(force=force))
        except Exception:
            return "OFFLINE"

    def run(self, name: str, prompt: str, cancel: threading.Event, timeout: int = 240) -> ProviderResult:
        adapter = self.adapters.get(name)
        if adapter is None:
            return ProviderResult(False, "", name, unconfigured=True, error_code="UNCONFIGURED")
        sem = self._sems[name]
        while not sem.acquire(timeout=0.5):
            if cancel.is_set():
                return ProviderResult(False, "", name, cancelled=True, error_code="CANCELLED")
        try:
            if cancel.is_set():
                return ProviderResult(False, "", name, cancelled=True, error_code="CANCELLED")
            try:
                return adapter.run(prompt, cancel, timeout=timeout)
            except Exception as exc:
                LOG.error("provider %s raised %s", name, type(exc).__name__)
                return ProviderResult(False, "", name, error_code="PROVIDER_EXCEPTION")
        finally:
            sem.release()

    def serialized(self, name: str) -> "SerializedAdapter":
        return SerializedAdapter(self, name)


class SerializedAdapter:
    """Drop-in adapter for CoordinatorV2 that waits for the provider instead of PROVIDER_BUSY."""

    def __init__(self, pool: ProviderPool, name: str, observer: Optional[Callable[[str, str], None]] = None):
        self.pool = pool
        self.name = name
        self.observer = observer

    def health(self, force: bool = False) -> str:
        return self.pool.health(self.name, force)

    def run(self, prompt: str, cancel_event: threading.Event, timeout: int = 240) -> ProviderResult:
        if self.observer:
            self.observer(self.name, "RUNNING")
        result = self.pool.run(self.name, prompt, cancel_event, timeout)
        if self.observer:
            if result.cancelled:
                state = "CANCELLED"
            elif result.ok:
                state = "DONE"
            elif result.error_code in {"OFFLINE", "UNCONFIGURED", "QUOTA/COOLDOWN", "DORMANT"}:
                state = "OFFLINE"
            else:
                state = "FAILED"
            self.observer(self.name, state)
        return result


# --------------------------------------------------------------------------
# Parsing helpers (pure functions, unit tested)
# --------------------------------------------------------------------------

_FILE_START = re.compile(r"^\s*={3,}\s*FILE\s*:\s*(.+?)\s*={3,}\s*$")
_FILE_END = re.compile(r"^\s*={3,}\s*END\s+FILE\s*={3,}\s*$")
_DELETE = re.compile(r"^\s*={3,}\s*DELETE\s*:\s*(.+?)\s*={3,}\s*$")
_SUMMARY_START = re.compile(r"^\s*={3,}\s*SUMMARY\s*={3,}\s*$")
_SUMMARY_END = re.compile(r"^\s*={3,}\s*END\s+SUMMARY\s*={3,}\s*$")
_PLAN_LINE = re.compile(r"^\s*[-*]?\s*`?([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`?\s*(?:\||:|—|-)\s*(.*)$")


@dataclass
class FileBlocks:
    files: dict[str, str] = field(default_factory=dict)
    deletes: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)
    summary: str = ""


def _strip_fences(content: str) -> str:
    lines = content.split("\n")
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        lines = lines[1:-1]
    return "\n".join(lines)


def parse_file_blocks(text: str) -> FileBlocks:
    out = FileBlocks()
    current: Optional[str] = None
    buf: list[str] = []
    in_summary = False
    summary: list[str] = []
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        if current is not None:
            if _FILE_END.match(line):
                content = _strip_fences("\n".join(buf))
                if not content.endswith("\n"):
                    content += "\n"
                out.files[current] = content
                current, buf = None, []
            else:
                buf.append(line)
            continue
        if in_summary:
            if _SUMMARY_END.match(line):
                in_summary = False
            else:
                summary.append(line)
            continue
        m = _FILE_START.match(line)
        if m:
            current = m.group(1).strip().strip("`").strip()
            buf = []
            continue
        m = _DELETE.match(line)
        if m:
            out.deletes.append(m.group(1).strip().strip("`").strip())
            continue
        if _SUMMARY_START.match(line):
            in_summary = True
    if current is not None:
        out.incomplete.append(current)
    out.summary = "\n".join(summary).strip()
    return out


def parse_plan(text: str) -> list[tuple[str, str]]:
    """Extract (path, description) from a PLAN block, falling back to the whole text."""
    body = text or ""
    m = re.search(r"={3,}\s*PLAN\s*={3,}(.*?)={3,}\s*END\s+PLAN\s*={3,}", body, re.S | re.I)
    if m:
        body = m.group(1)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in body.splitlines():
        pm = _PLAN_LINE.match(line)
        if not pm:
            continue
        path = pm.group(1).strip()
        if path.startswith("./"):
            path = path[2:]
        if path in seen:
            continue
        try:
            policy.validate_relpath(path)
        except policy.PolicyError:
            continue
        seen.add(path)
        out.append((path, pm.group(2).strip()[:200]))
    return out[: policy.MAX_FILES_PER_JOB]


_RAN = re.compile(r"^Ran (\d+) tests? in", re.M)
_FAILED = re.compile(r"^FAILED \(([^)]*)\)", re.M)
_PYTEST = re.compile(r"(\d+) (passed|failed|error|errors)")


@dataclass
class TestOutcome:
    passed: bool
    ran: int
    failed: int
    errors: int
    output_tail: str
    timed_out: bool = False
    note: str = ""

    @property
    def ok_count(self) -> int:
        return max(0, self.ran - self.failed - self.errors)


def parse_test_output(result: dict[str, Any]) -> TestOutcome:
    out = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
    exit_code = result.get("exit_code")
    timed_out = bool(result.get("timed_out"))
    ran = failed = errors = 0
    m = None
    for m in _RAN.finditer(out):
        pass
    if m is not None:
        ran = int(m.group(1))
        fm = None
        for fm in _FAILED.finditer(out):
            pass
        if fm is not None:
            for part in fm.group(1).split(","):
                k, _, v = part.strip().partition("=")
                if v.isdigit():
                    if k == "failures":
                        failed = int(v)
                    elif k == "errors":
                        errors = int(v)
    else:
        for n, kind in _PYTEST.findall(out):
            if kind == "passed":
                ran += int(n)
            elif kind == "failed":
                failed += int(n)
                ran += int(n)
            else:
                errors += int(n)
                ran += int(n)
    note = ""
    passed = (exit_code == 0) and ran > 0 and failed == 0 and errors == 0 and not timed_out
    if exit_code == 0 and ran == 0:
        note = "nessun test trovato"
    if timed_out:
        note = "timeout dei test"
    if exit_code not in (0, None) and ran > 0 and failed == 0 and errors == 0:
        errors = 1  # crashed after tests (e.g. import error at teardown)
    tail = out.strip()[-6000:]
    return TestOutcome(passed, ran, failed, errors, sanitize(tail, 6000), timed_out, note)


def parse_verdict(text: str) -> tuple[Optional[str], str]:
    m = re.search(r"VERDICT\s*:\s*(APPROVE|CHANGES)", text or "", re.I)
    verdict = m.group(1).upper() if m else None
    issues = (text or "").strip()
    if m:
        issues = (text[m.end():] or "").strip()
    return verdict, issues[:3000]


_SLUG_STOP = {
    "crea", "creami", "genera", "sviluppa", "scrivi", "realizza", "costruisci", "un", "una", "uno", "il", "lo",
    "la", "per", "con", "di", "del", "della", "in", "e", "programma", "python", "python3", "app", "applicazione",
    "script", "progetto", "locale", "che", "gestire", "gestisce", "semplice", "mini", "nuovo", "nuova", "testalo",
    "correggilo", "finche", "funziona", "sqlite", "tool", "software", "cli", "a", "da", "the", "and",
}


def derive_project_name(request: str, analysis_texts: list[str], job_id: int) -> str:
    for text in analysis_texts:
        m = re.search(r"PROJECT_NAME\s*:\s*`?([A-Za-z0-9_-]{2,40})`?", text or "")
        if m:
            cand = m.group(1).lower().replace("-", "_")
            try:
                return policy.validate_project_name(cand)
            except policy.PolicyError:
                continue
    words = re.findall(r"[a-zà-ù0-9]+", (request or "").lower())
    picked = [w for w in words if w not in _SLUG_STOP and len(w) > 2][:3]
    cand = "_".join(picked) or "progetto"
    cand = re.sub(r"[^a-z0-9_]", "", cand)[:30] or "progetto"
    if not cand[0].isalnum():
        cand = "p" + cand
    try:
        return policy.validate_project_name(cand)
    except policy.PolicyError:
        return f"progetto_{job_id}"


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------

_RULES = (
    "REGOLE TECNICHE:\n"
    "- Python 3.12, SOLO libreria standard (niente pip, niente rete).\n"
    "- I test reali saranno eseguiti dall'orchestratore con: python3 -B -m unittest discover -v "
    "dalla root del progetto, in una sandbox senza rete.\n"
    "- I file di test si chiamano test_*.py e stanno nella ROOT del progetto.\n"
    "- I test non devono usare la rete ne' scrivere fuori dal progetto: usa tempfile o SQLite ':memory:'.\n"
    "- Nessun segreto, token, password o file .env. Nessun percorso assoluto, nessun '..'.\n"
    "- Ogni file al massimo ~350 righe: se serve di piu', dividi in moduli.\n"
)

_FORMAT = (
    "FORMATO DI USCITA OBBLIGATORIO (l'orchestratore salva SOLO cio' che e' in questi blocchi):\n"
    "=== FILE: percorso/relativo.ext ===\n"
    "<contenuto COMPLETO del file, senza recinti ```>\n"
    "=== END FILE ===\n"
    "Per eliminare un file: === DELETE: percorso/relativo.ext ===\n"
    "Chiudi con:\n=== SUMMARY ===\n<2-5 righe su cosa hai fatto>\n=== END SUMMARY ===\n"
)


def analysis_prompt(request: str, operation: str, project: Optional[str], context: str) -> str:
    target = f"Progetto esistente: {project}\n" if operation == "modifica" else ""
    ctx = f"\nCONTENUTO ATTUALE DEL PROGETTO (estratto):\n{context}\n" if context else ""
    return (
        "ANDREA AI TEAM - FASE DI ANALISI (sei uno dei tre analisti indipendenti).\n"
        "Non scrivere ancora il codice completo. Proponi in modo conciso: architettura, elenco file, "
        "casi di test importanti, rischi/bug probabili.\n"
        + ("Prima riga OBBLIGATORIA: PROJECT_NAME: <nome_breve_snake_case>\n" if operation == "crea" else "")
        + _RULES + target + "\nRICHIESTA DELL'UTENTE:\n" + request + ctx
    )


def plan_prompt(request: str, project: str, analyses: str, context: str, operation: str) -> str:
    ctx = f"\nFILE ATTUALI DEL PROGETTO:\n{context}\n" if context else ""
    return (
        "ANDREA AI TEAM - RUOLO: ESECUTORE. Stai per sviluppare il progetto '" + project + "'.\n"
        "Non esegui comandi: l'orchestratore salvera' i file tramite MCP Andrea ed eseguira' i test reali.\n"
        + _RULES
        + "Ora restituisci SOLO il piano dei file da " + ("creare" if operation == "crea" else "creare o modificare")
        + ", in quest'ordine: moduli applicativi, poi test, poi README.md.\n"
        "Formato:\n=== PLAN ===\npercorso/file.py | descrizione breve\n=== END PLAN ===\n"
        "\nRICHIESTA:\n" + request + "\n\nANALISI DEL TEAM:\n" + analyses + ctx
    )


def file_prompt(request: str, project: str, analyses: str, plan: list[tuple[str, str]], target: str,
                written: str, operation: str, current: str = "") -> str:
    plan_txt = "\n".join(f"- {p} | {d}" for p, d in plan)
    cur = f"\nCONTENUTO ATTUALE DI {target}:\n{current}\n" if current else ""
    return (
        "ANDREA AI TEAM - RUOLO: ESECUTORE. Progetto '" + project + "'.\n"
        "Non esegui comandi: l'orchestratore salva i file via MCP Andrea ed esegue i test reali.\n"
        + _RULES + _FORMAT
        + "Scrivi ORA il contenuto COMPLETO del solo file: " + target + "\n"
        "Deve essere coerente con il piano e con i file gia' scritti (stesse API, nomi, firme).\n"
        "\nRICHIESTA:\n" + request + "\n\nPIANO:\n" + plan_txt
        + "\n\nANALISI DEL TEAM (estratto):\n" + analyses[:8000]
        + ("\n\nFILE GIA' SCRITTI:\n" + written if written else "") + cur
    )


def fix_prompt(request: str, project: str, files_ctx: str, problem: str, origin: str) -> str:
    return (
        "ANDREA AI TEAM - RUOLO: ESECUTORE, FASE DI CORREZIONE. Progetto '" + project + "'.\n"
        + _RULES + _FORMAT
        + "Correggi il progetto. Restituisci SOLO i file da modificare/creare, ciascuno COMPLETO.\n"
        "Non indebolire ne' cancellare i test per farli passare: correggi il codice (o un test davvero errato).\n"
        "\nRICHIESTA ORIGINALE:\n" + request
        + "\n\nPROBLEMA (" + origin + "):\n" + problem
        + "\n\nFILE ATTUALI DEL PROGETTO:\n" + files_ctx
    )


def review_prompt(request: str, project: str, files_ctx: str, tests: str, role: str) -> str:
    return (
        "ANDREA AI TEAM - RUOLO: " + role + " del progetto '" + project + "'.\n"
        "Non eseguire nulla. Valuta correttezza, bug, sicurezza e aderenza alla richiesta.\n"
        "Prima riga OBBLIGATORIA: VERDICT: APPROVE oppure VERDICT: CHANGES\n"
        "Usa CHANGES solo per difetti BLOCCANTI (bug reali, requisiti mancanti, rischi di sicurezza), "
        "non per stile. Poi elenca al massimo 5 problemi bloccanti, ciascuno con file e correzione proposta.\n"
        "\nRICHIESTA:\n" + request + "\n\nRISULTATO TEST REALI:\n" + tests + "\n\nFILE:\n" + files_ctx
    )


# --------------------------------------------------------------------------
# Job runner
# --------------------------------------------------------------------------

Notify = Callable[[int, str], None]


class JobRunner:
    def __init__(self, job_id: int, store: JobStore, gate: WriteGateClient, pool: ProviderPool,
                 notify: Notify, config: BuilderConfig, cancel: threading.Event,
                 claim_project: Callable[[str, threading.Event], bool],
                 release_project: Callable[[str], None]):
        self.job_id = job_id
        self.store = store
        self.gate = gate
        self.pool = pool
        self.notify = notify
        self.cfg = config
        self.cancel = cancel
        self._claim = claim_project
        self._release = release_project
        self.deadline = time.monotonic() + config.job_timeout
        self.job: Job = store.get(job_id)  # type: ignore[assignment]
        self.uid = self.job.uid
        self.project: Optional[str] = self.job.project
        self.claimed = False
        self.session_open = False
        self.snapshot_uid: Optional[str] = None
        self.project_existed = False
        self.executor: Optional[str] = None
        self.analyses_text = ""
        self.summary = ""
        self._hb_stop = threading.Event()
        self._hb: Optional[threading.Thread] = None
        self._known_dirs: set[str] = set()

    # -- helpers -------------------------------------------------------------

    def _refresh(self) -> Job:
        self.job = self.store.get(self.job_id)  # type: ignore[assignment]
        return self.job

    def _check(self) -> None:
        if self.cancel.is_set() or self._refresh().cancel_requested:
            self.cancel.set()
            raise JobAbort("CANCELLED", "annullato dall'utente")
        if time.monotonic() > self.deadline:
            raise JobAbort("TIMEOUT", f"superato il tempo massimo di {self.cfg.job_timeout}s")

    def _to(self, state: str, phase: str) -> None:
        if self._refresh().state != state:
            self.store.transition(self.job_id, state, phase)
        else:
            self.store.update(self.job_id, phase=phase)

    def _agent(self, agent: str, state: str) -> None:
        self.store.set_agent(self.job_id, agent, state)

    def _call(self, agent: str, prompt: str, timeout: int) -> ProviderResult:
        self._check()
        if len(prompt) > 70000:  # provider worker hard limit is 80k chars / 128 KB JSON
            prompt = prompt[:70000] + "\n[contesto troncato]"
        self._agent(agent, "RUNNING")
        result = self.pool.run(agent, prompt, self.cancel, timeout=timeout)
        if result.cancelled or self.cancel.is_set():
            self._agent(agent, "CANCELLED")
            raise JobAbort("CANCELLED", "annullato dall'utente")
        if result.ok:
            # The executor stays RUNNING for the whole development phase.
            self._agent(agent, "RUNNING" if agent == self.executor else "DONE")
        else:
            code = result.error_code or "ERROR"
            self._agent(agent, "OFFLINE" if code in {"OFFLINE", "UNCONFIGURED", "QUOTA/COOLDOWN", "DORMANT"}
                        else "FAILED")
            self.store.add_error(self.job_id, f"{agent}: {code}")
        return result

    def _record(self, op: str, path: str, res: dict[str, Any]) -> None:
        self.store.record_op(self.job_id, op, path, res.get("operation_id"))

    # -- heartbeat -----------------------------------------------------------

    def _start_heartbeat(self) -> None:
        def beat() -> None:
            while not self._hb_stop.wait(self.cfg.heartbeat_interval):
                try:
                    self.gate.heartbeat(self.uid, self.project or "")
                except GateError as exc:
                    LOG.warning("job %s heartbeat failed %s", self.job_id, exc.code)
                    self.store.event(self.job_id, "heartbeat_failed", exc.code)

        self._hb = threading.Thread(target=beat, name=f"job-hb-{self.job_id}", daemon=True)
        self._hb.start()

    def _stop_heartbeat(self) -> None:
        self._hb_stop.set()
        if self._hb is not None:
            self._hb.join(timeout=2)

    # -- project context -------------------------------------------------------

    def _list_entries(self) -> list[str]:
        assert self.project
        try:
            return [str(e) for e in self.gate.list(self.uid, self.project, "", depth=5).get("entries", [])]
        except GateError:
            pass
        # Fallback: walk level by level, skipping unreadable directories (e.g. foreign __pycache__).
        out: list[str] = []
        pending = [""]
        while pending and len(out) < 2000:
            base = pending.pop(0)
            try:
                entries = self.gate.list(self.uid, self.project, base, depth=1).get("entries", [])
            except GateError:
                continue
            for e in entries:
                e = str(e)
                kind, _, name = e.partition("] ")
                rel = f"{base}/{name}" if base else name
                if kind == "[DIR":
                    out.append(f"[DIR] {rel}")
                    if "__pycache__" not in rel and rel.count("/") < 5:
                        pending.append(rel)
                else:
                    out.append(f"[FILE] {rel}")
        return out

    def _project_files(self) -> list[str]:
        assert self.project
        files = []
        for entry in self._list_entries():
            entry = str(entry)
            if not entry.startswith("[FILE]"):
                continue
            rel = entry[len("[FILE]"):].strip()
            if "__pycache__" in rel or rel.endswith(".pyc"):
                continue
            try:
                policy.validate_relpath(rel)
            except policy.PolicyError:
                continue
            files.append(rel)
        return sorted(files)

    def _context(self, files: Optional[list[str]] = None, limit: Optional[int] = None) -> str:
        assert self.project
        limit = limit or self.cfg.max_context_chars
        files = files if files is not None else self._project_files()
        parts: list[str] = []
        used = 0
        for rel in files:
            if not rel.endswith(TEXT_EXTENSIONS):
                parts.append(f"(file non testuale: {rel})")
                continue
            try:
                content = self.gate.read(self.uid, self.project, rel)
            except GateError:
                continue
            block = f"=== FILE: {rel} ===\n{content}\n=== END FILE ===\n"
            if used + len(block) > limit:
                parts.append(f"(omesso per spazio: {rel})")
                continue
            parts.append(block)
            used += len(block)
        return "\n".join(parts)

    # -- writes ----------------------------------------------------------------

    def _ensure_dirs(self, rel: str) -> None:
        assert self.project
        parts = rel.split("/")[:-1]
        cur = ""
        for p in parts:
            cur = f"{cur}/{p}" if cur else p
            if cur in self._known_dirs:
                continue
            info = self.gate.exists(self.uid, self.project, cur)
            if not info.get("exists"):
                res = self.gate.mkdir(self.uid, self.project, cur)
                self._record("mkdir", cur, res)
            self._known_dirs.add(cur)

    def _apply(self, blocks: FileBlocks) -> list[str]:
        assert self.project
        written: list[str] = []
        total = 0
        if len(blocks.files) + len(self.job.files) > policy.MAX_FILES_PER_JOB:
            raise JobAbort("FAILED", "troppi file nel progetto")
        for rel, content in blocks.files.items():
            self._check()
            try:
                policy.validate_relpath(rel)
                policy.check_content(content)
            except policy.PolicyError as exc:
                self.store.add_error(self.job_id, f"file rifiutato {rel[:80]}: {exc.code}")
                continue
            total += len(content.encode("utf-8"))
            if total > policy.MAX_TOTAL_BYTES:
                raise JobAbort("FAILED", "dimensione totale dei file oltre il limite")
            self._ensure_dirs(rel)
            res = self.gate.write(self.uid, self.project, rel, content)
            self._record("write", rel, res)
            written.append(rel)
        for rel in blocks.deletes:
            try:
                policy.validate_relpath(rel)
            except policy.PolicyError as exc:
                self.store.add_error(self.job_id, f"delete rifiutato {rel[:80]}: {exc.code}")
                continue
            if self.gate.exists(self.uid, self.project, rel).get("exists"):
                res = self.gate.delete(self.uid, self.project, rel)
                self._record("delete", rel, res)
                written.append(rel)
        if written:
            self.store.add_files(self.job_id, written)
            self._refresh()
        return written

    # -- phases ----------------------------------------------------------------

    def _analysis(self) -> None:
        job = self._refresh()
        self._to(ANALYZING, "analisi del team")
        context = ""
        if job.operation == "modifica" and self.project:
            # Read-only peek inside the gate session is not available before begin();
            # the executor reads the real files after the lock is acquired.
            context = "(i file attuali verranno letti dopo l'acquisizione del lock)"
        prompt = analysis_prompt(job.request, job.operation, self.project, context)
        results: dict[str, ProviderResult] = {}

        def one(agent: str) -> ProviderResult:
            try:
                return self._call(agent, prompt, self.cfg.analysis_timeout)
            except JobAbort as exc:
                return ProviderResult(False, "", agent, cancelled=exc.kind == "CANCELLED",
                                      error_code=exc.kind)

        with ThreadPoolExecutor(max_workers=3, thread_name_prefix=f"job{self.job_id}-an") as ex:
            futs = {agent: ex.submit(one, agent) for agent in AGENTS}
            for agent, fut in futs.items():
                results[agent] = fut.result()
        self._check()
        for agent, res in results.items():
            if res.ok:
                self._agent(agent, "DONE")
        ok = {a: r for a, r in results.items() if r.ok}
        if not ok:
            raise JobAbort("FAILED", "nessun agente disponibile per l'analisi")
        labels = {"codex": "CODEX", "claude": "CLAUDE", "grok": "GROK"}
        self.analyses_text = "\n\n".join(
            f"[{labels[a]}]\n{sanitize(ok[a].text, 7000)}" for a in AGENTS if a in ok
        )
        if job.operation == "crea" and not self.project:
            name = derive_project_name(job.request, [ok[a].text for a in AGENTS if a in ok], job.job_id)
            self.project = name
            self.store.update(self.job_id, project=name)
        self.store.event(self.job_id, "analysis_done", f"agents={','.join(sorted(ok))}")

    def _choose_executor(self, exclude: set[str] = frozenset()) -> str:
        for agent in EXECUTOR_PREFERENCE:
            if agent in exclude:
                continue
            if self.pool.health(agent) == ONLINE:
                return agent
        raise JobAbort("FAILED", "nessun esecutore disponibile (Codex/Claude/Grok offline)")

    def _set_executor(self, agent: str) -> None:
        previous = self.executor
        self.executor = agent
        self.store.update(self.job_id, executor=agent)
        self.store.event(self.job_id, "executor", agent)
        for other in AGENTS:
            if other == agent:
                self._agent(other, "RUNNING")
            elif other == previous:
                self._agent(other, "FAILED")
            elif self._refresh().agent_state(other) in {"DONE", "RUNNING"}:
                self._agent(other, "WAITING")

    def _executor_call(self, prompt: str) -> ProviderResult:
        """Call the executor; on provider failure switch once to the next available agent."""
        assert self.executor
        res = self._call(self.executor, prompt, self.cfg.executor_timeout)
        if res.ok:
            return res
        if res.error_code == "EMPTY_OUTPUT":
            return res
        failed = {self.executor}
        try:
            nxt = self._choose_executor(exclude=failed)
        except JobAbort:
            raise JobAbort("FAILED", f"esecutore {self.executor} non disponibile ({res.error_code})")
        self.store.event(self.job_id, "executor_switch", f"{self.executor}->{nxt} ({res.error_code})")
        self._set_executor(nxt)
        res2 = self._call(nxt, prompt, self.cfg.executor_timeout)
        if not res2.ok:
            raise JobAbort("FAILED", f"esecutori non disponibili ({res.error_code}, {res2.error_code})")
        return res2

    def _acquire(self) -> None:
        assert self.project
        if not self._claim(self.project, self.cancel):
            raise JobAbort("CANCELLED", "annullato in attesa del progetto")
        self.claimed = True
        self.store.update(self.job_id, lock_state="WAITING", phase="acquisizione work_session/work_lock")
        last: Optional[GateError] = None
        for attempt in range(self.cfg.lock_retry):
            self._check()
            try:
                info = self.gate.begin(self.uid, self.project)
                self.session_open = True
                self.store.update(self.job_id, work_session_id=info.get("work_session_id"),
                                  work_lock_id=info.get("work_lock_id"), lock_state="ACQUIRED")
                self._start_heartbeat()
                return
            except GateError as exc:
                last = exc
                if exc.code != "LOCK_CONFLICT":
                    break
                self.store.update(self.job_id, lock_state="CONFLICT")
                self.store.event(self.job_id, "lock_conflict", f"tentativo {attempt + 1}")
                if attempt + 1 < self.cfg.lock_retry:
                    if self.cancel.wait(self.cfg.lock_retry_wait):
                        raise JobAbort("CANCELLED", "annullato in attesa del lock")
        code = last.code if last else "LOCK_FAILED"
        self.store.update(self.job_id, lock_state="FAILED")
        raise JobAbort("FAILED", f"work_lock non ottenuto ({code}): progetto in uso, nessun lock rubato")

    def _prepare_project(self) -> None:
        assert self.project
        job = self._refresh()
        info = self.gate.exists(self.uid, self.project, "")
        self.project_existed = bool(info.get("exists"))
        if job.operation == "modifica" and not self.project_existed:
            raise JobAbort("FAILED", f"il progetto {self.project} non esiste")
        if job.operation == "crea" and self.project_existed:
            raise JobAbort("FAILED", f"il progetto {self.project} esiste gia': usa /modifica {self.project} ...")
        if self.project_existed:
            self.store.update(self.job_id, phase="backup/snapshot")
            res = self.gate.snapshot(self.uid, self.project)
            self.snapshot_uid = self.uid
            self._record("snapshot", f".snapshots/{self.project}/{self.uid}", res)
        else:
            res = self.gate.mkdir(self.uid, self.project, "")
            self._record("mkdir", "", res)

    def _develop(self) -> None:
        assert self.project and self.executor
        job = self._refresh()
        self._to(RUNNING, "sviluppo: piano file")
        context = self._context() if self.project_existed else ""
        res = self._executor_call(plan_prompt(job.request, self.project, self.analyses_text, context,
                                              job.operation))
        plan = parse_plan(res.text)
        if not plan:
            raise JobAbort("FAILED", "l'esecutore non ha prodotto un piano file valido")
        self.store.event(self.job_id, "plan", ", ".join(p for p, _ in plan)[:1500])
        written_ctx: list[str] = []
        summaries: list[str] = []
        for idx, (rel, _desc) in enumerate(plan, 1):
            self._check()
            self.store.update(self.job_id, phase=f"sviluppo: {rel} ({idx}/{len(plan)})")
            current = ""
            if self.project_existed:
                info = self.gate.exists(self.uid, self.project, rel)
                if info.get("exists") and rel.endswith(TEXT_EXTENSIONS):
                    current = self.gate.read(self.uid, self.project, rel)
            written = "\n".join(written_ctx)[-self.cfg.max_context_chars:]
            prompt = file_prompt(job.request, self.project, self.analyses_text, plan, rel, written,
                                 job.operation, current)
            blocks = FileBlocks()
            for _try in range(2):
                out = self._executor_call(prompt)
                blocks = parse_file_blocks(out.text if out.ok else "")
                if rel in blocks.files:
                    break
                prompt = prompt + (
                    "\n\nATTENZIONE: la risposta precedente non conteneva un blocco completo per "
                    f"{rel}. Restituisci SOLO quel file, piu' compatto, tra === FILE: {rel} === e === END FILE ===."
                )
            if rel not in blocks.files:
                raise JobAbort("FAILED", f"l'esecutore non ha prodotto il file {rel}")
            only = FileBlocks(files={rel: blocks.files[rel]})
            self._apply(only)
            written_ctx.append(f"=== FILE: {rel} ===\n{blocks.files[rel]}=== END FILE ===")
            if blocks.summary:
                summaries.append(blocks.summary)
        self.summary = "\n".join(summaries[-2:])[:1200]

    def _detect_test_kind(self, files: list[str]) -> str:
        root_tests = [f for f in files if "/" not in f and f.startswith("test") and f.endswith(".py")]
        dir_tests = [f for f in files if f.startswith("tests/") and f.endswith(".py")]
        if not root_tests and dir_tests:
            return "unittest_tests_dir"
        return "unittest"

    def _test(self, label: str) -> TestOutcome:
        assert self.project
        self._check()
        self._to(TESTING, f"test reali ({label})")
        kind = self._detect_test_kind(self._project_files())
        try:
            raw = self.gate.run_tests(self.uid, self.project, kind=kind, timeout=self.cfg.test_timeout)
        except GateError as exc:
            self.store.add_error(self.job_id, f"test gate: {exc.code} {exc.detail}")
            outcome = TestOutcome(False, 0, 0, 1, f"Esecuzione test non disponibile: {exc.code}", note=exc.code)
            self.store.update(self.job_id, test_result=f"ERRORE GATE {exc.code}", test_command=kind)
            if exc.code in {"GATE_OFFLINE", "MCP_UNREACHABLE", "MCP_DENIED", "LOCK_REQUIRED", "LOCK_CONFLICT",
                            "GATE_CONFIG", "TEST_KIND_NOT_ALLOWED"}:
                raise JobAbort("FAILED", f"impossibile eseguire i test reali via MCP ({exc.code})")
            return outcome
        outcome = parse_test_output(raw)
        self.store.update(
            self.job_id,
            tests_run=outcome.ran,
            tests_passed=outcome.ok_count,
            tests_failed=outcome.failed + outcome.errors,
            test_result="PASS" if outcome.passed else ("FAIL" + (f" ({outcome.note})" if outcome.note else "")),
            test_command=kind,
        )
        self.store.event(self.job_id, "tests",
                         f"{label}: ran={outcome.ran} failed={outcome.failed} errors={outcome.errors} "
                         f"passed={outcome.passed} {outcome.note}")
        return outcome

    def _fix(self, problem: str, origin: str) -> None:
        assert self.project and self.executor
        job = self._refresh()
        attempts = job.attempts + 1
        self.store.update(self.job_id, attempts=attempts)
        self._to(RUNNING, f"correzione {attempts} ({origin})")
        self._agent(self.executor, "RUNNING")
        ctx = self._context()
        res = self._executor_call(fix_prompt(job.request, self.project, ctx, problem[-8000:], origin))
        blocks = parse_file_blocks(res.text if res.ok else "")
        for rel in blocks.incomplete:
            self.store.add_error(self.job_id, f"blocco incompleto ignorato: {rel[:80]}")
        if not blocks.files and not blocks.deletes:
            self.store.add_error(self.job_id, f"correzione {attempts}: nessun file restituito")
            return
        self._apply(blocks)
        if blocks.summary:
            self.summary = (self.summary + "\n" + blocks.summary).strip()[-1500:]

    def _test_and_fix(self, label: str) -> TestOutcome:
        outcome = self._test(label)
        while not outcome.passed:
            if self._refresh().attempts >= self.cfg.max_fix_attempts:
                return outcome
            problem = outcome.output_tail or outcome.note or "test falliti"
            if outcome.note == "nessun test trovato":
                problem = ("Nessun test e' stato eseguito: crea test unittest reali (file test_*.py nella root) "
                           "che verifichino tutte le funzionalita' richieste.\n" + problem)
            self._fix(problem, "test falliti")
            outcome = self._test(f"dopo correzione {self._refresh().attempts}")
        return outcome

    def _review(self, outcome: TestOutcome) -> list[str]:
        assert self.project
        job = self._refresh()
        reviewers = [a for a in ("claude", "grok", "codex") if a != self.executor][:2]
        for agent in AGENTS:
            if agent != self.executor and agent not in reviewers:
                self._agent(agent, "SKIPPED")
        if not self.cfg.review_enabled:
            for a in reviewers:
                self._agent(a, "SKIPPED")
            return []
        self._to(REVIEWING, "review indipendente")
        if self.executor:
            self._agent(self.executor, "WAITING")
        ctx = self._context()
        tests = f"{outcome.ok_count}/{outcome.ran} PASS"
        roles = {reviewers[0]: "CODE REVIEW"}
        if len(reviewers) > 1:
            roles[reviewers[1]] = "REVISIONE INDIPENDENTE / RICERCA BUG"
        issues: list[str] = []

        def one(agent: str) -> tuple[str, ProviderResult]:
            if self.pool.health(agent) != ONLINE:
                return agent, ProviderResult(False, "", agent, error_code="OFFLINE")
            try:
                return agent, self._call(agent, review_prompt(job.request, self.project or "", ctx, tests,
                                                              roles[agent]), self.cfg.review_timeout)
            except JobAbort as exc:
                return agent, ProviderResult(False, "", agent, cancelled=exc.kind == "CANCELLED",
                                             error_code=exc.kind)

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"job{self.job_id}-rv") as ex:
            results = list(ex.map(one, reviewers))
        self._check()
        for agent, res in results:
            if not res.ok:
                self._agent(agent, "OFFLINE" if res.error_code == "OFFLINE" else "FAILED")
                continue
            self._agent(agent, "DONE")
            verdict, text = parse_verdict(res.text)
            self.store.event(self.job_id, "review", f"{agent}: {verdict or 'N/D'}")
            if verdict == "CHANGES":
                issues.append(f"[{agent.upper()}]\n{sanitize(text, 2500)}")
        return issues

    # -- rollback ----------------------------------------------------------------

    def rollback(self) -> str:
        """Undo this job's operations. Returns none|done|partial|failed."""
        ops = [o for o in self.store.ops(self.job_id) if o["op"] != "snapshot"]
        if not ops:
            return "not_needed"
        if not self.project:
            return "failed"
        status = "done"
        try:
            if not self.session_open:
                self.gate.begin(self.uid, self.project)
                self.session_open = True
        except GateError as exc:
            if exc.code == "LOCK_CONFLICT":
                # The dead process' MCP lease still holds the lock: never steal it, retry later.
                self.store.event(self.job_id, "rollback_deferred", exc.code)
                return "deferred"
            self.store.add_error(self.job_id, f"rollback: sessione non disponibile {exc.code}")
            return "failed"
        native_failed = False
        for op in reversed(ops):
            if not op.get("operation_id"):
                continue
            try:
                self.gate.rollback(self.uid, self.project, op["operation_id"])
                self.store.mark_op_rolled_back(op["id"])
            except GateError as exc:
                native_failed = True
                self.store.event(self.job_id, "rollback_op_failed", f"{op['op']} {op['path']} {exc.code}")
                break
        if native_failed:
            try:
                if self.snapshot_uid or any(o["op"] == "snapshot" for o in self.store.ops(self.job_id)):
                    self.gate.restore_snapshot(self.uid, self.project, self.snapshot_uid or self.uid)
                    self.store.event(self.job_id, "rollback", "ripristino da snapshot")
                else:
                    self.gate.trash_project(self.uid, self.project)
                    self.store.event(self.job_id, "rollback", "progetto nuovo spostato in .trash")
                for op in self.store.ops(self.job_id):
                    if op["op"] != "snapshot":
                        self.store.mark_op_rolled_back(op["id"])
            except GateError as exc:
                self.store.add_error(self.job_id, f"rollback fallito: {exc.code}")
                status = "failed"
        return status

    def _close(self) -> None:
        self._stop_heartbeat()
        if self.session_open and self.project:
            try:
                self.gate.end(self.uid, self.project)
                self.store.update(self.job_id, lock_state="RELEASED")
            except GateError as exc:
                self.store.event(self.job_id, "release_failed", exc.code)
            self.session_open = False
        if self.claimed and self.project:
            self._release(self.project)
            self.claimed = False

    # -- main --------------------------------------------------------------------

    def run(self) -> Job:
        job = self._refresh()
        if job.state != QUEUED:
            # Cancelled/finished between dispatch and start: nothing to do, nothing to report.
            return job
        try:
            self._check()
            if job.operation == "modifica" and self.project:
                policy.validate_project_name(self.project)
            self._analysis()
            assert self.project
            policy.validate_project_name(self.project)
            self.store.update(self.job_id, project_path=policy.project_path(
                getattr(self.gate, "projects_root", policy.DEFAULT_PROJECTS_ROOT), self.project))
            self._set_executor(self._choose_executor())
            self._to(RUNNING, "preparazione")
            self.notify(job.telegram_chat_id,
                        f"🟢 LAVORO #{self.job_id}: piano pronto. Progetto: {self.project}. "
                        f"Esecutore: {self.executor}. Inizio sviluppo.")
            self._acquire()
            self._prepare_project()
            self._develop()
            outcome = self._test_and_fix("prima esecuzione")
            if outcome.passed:
                for rnd in range(self.cfg.max_review_fix_rounds + 1):
                    issues = self._review(outcome)
                    if not issues or rnd >= self.cfg.max_review_fix_rounds:
                        if issues:
                            self.store.event(self.job_id, "review_unresolved", "osservazioni residue")
                            self.summary = (self.summary + "\nNote review non bloccanti/residue:\n"
                                            + "\n".join(i[:400] for i in issues)).strip()
                        break
                    if self._refresh().attempts >= self.cfg.max_fix_attempts + self.cfg.max_review_fix_rounds:
                        break
                    self._fix("\n\n".join(issues), "review")
                    outcome = self._test_and_fix("dopo review")
                    if not outcome.passed:
                        break
            if outcome.passed:
                final = self._test("finale")
                outcome = final
            if not outcome.passed:
                raise JobAbort("FAILED", f"test non superati dopo {self._refresh().attempts} tentativi di fix")
            if self.executor:
                self._agent(self.executor, "DONE")
            self.store.update(self.job_id, rollback="not_needed",
                              result_summary=self.summary or "Lavoro completato.")
            self._close()
            self.store.transition(self.job_id, COMPLETED, "completato")
        except JobAbort as exc:
            self._finish_abort(exc)
        except GateError as exc:
            self._finish_abort(JobAbort("FAILED", f"write gate: {exc.code} {exc.detail}"))
        except policy.PolicyError as exc:
            self._finish_abort(JobAbort("FAILED", f"policy: {exc.code} {exc.detail}"))
        except Exception as exc:  # never crash the manager
            LOG.exception("job %s crashed", self.job_id)
            self._finish_abort(JobAbort("FAILED", f"errore interno {type(exc).__name__}"))
        finally:
            self._stop_heartbeat()
            if self.claimed and self.project:
                self._release(self.project)
                self.claimed = False
        job = self._refresh()
        from job_format import format_final  # local import: avoid cycle at module load
        self.notify(job.telegram_chat_id, format_final(job))
        return job

    def _finish_abort(self, exc: JobAbort) -> None:
        self.store.add_error(self.job_id, f"{exc.kind}: {exc.detail}")
        if self.executor and self._refresh().agent_state(self.executor) in {"RUNNING", "WAITING"}:
            self._agent(self.executor, "CANCELLED" if exc.kind == "CANCELLED" else "FAILED")
        for agent in AGENTS:
            if self._refresh().agent_state(agent) in {"WAITING", "RUNNING"}:
                self._agent(agent, "CANCELLED" if exc.kind == "CANCELLED" else "SKIPPED")
        rb = "not_needed"
        try:
            rb = self.rollback()
        except Exception as rexc:  # pragma: no cover - defensive
            LOG.error("rollback crashed %s", type(rexc).__name__)
            rb = "failed"
        self.store.update(self.job_id, rollback=rb,
                          result_summary=f"{exc.kind}: {exc.detail}" + (f"\n{self.summary}" if self.summary else ""))
        self._close()
        state = self._refresh().state
        if state in (COMPLETED, FAILED, CANCELLED, ROLLED_BACK):
            return
        if exc.kind == "CANCELLED":
            target = CANCELLED
        elif rb in ("done",):
            target = ROLLED_BACK
        else:
            target = FAILED
        if state == QUEUED and target == ROLLED_BACK:
            target = FAILED
        if state == ANALYZING and target == ROLLED_BACK:
            target = FAILED
        self.store.transition(self.job_id, target, exc.detail[:150])


# --------------------------------------------------------------------------
# Job manager: queue, concurrency, per-project serialization, restart recovery
# --------------------------------------------------------------------------

class JobManager:
    def __init__(self, store: JobStore, gate: WriteGateClient, pool: ProviderPool, notify: Notify,
                 config: Optional[BuilderConfig] = None):
        self.store = store
        self.gate = gate
        self.pool = pool
        self.notify = notify
        self.cfg = config or BuilderConfig()
        self._lock = threading.Condition()
        self._busy_projects: set[str] = set()
        self._running: dict[int, threading.Thread] = {}
        self._cancels: dict[int, threading.Event] = {}
        self._stop = threading.Event()
        self._dispatcher: Optional[threading.Thread] = None
        self._wake = threading.Event()
        self._pending_recovery: set[int] = set()
        self.recovery_retry_interval = 60.0

    # -- project claims ----------------------------------------------------------

    def claim_project(self, name: str, cancel: threading.Event) -> bool:
        with self._lock:
            while name in self._busy_projects:
                if cancel.is_set() or self._stop.is_set():
                    return False
                self._lock.wait(timeout=0.5)
            self._busy_projects.add(name)
            return True

    def release_project(self, name: str) -> None:
        with self._lock:
            self._busy_projects.discard(name)
            self._lock.notify_all()
        self._wake.set()

    # -- submission ----------------------------------------------------------------

    def submit(self, *, user_id: int, chat_id: int, request: str, operation: str,
               project: Optional[str], idem_key: Optional[str]) -> tuple[Job, bool]:
        if project:
            policy.validate_project_name(project)
        job, created = self.store.create(user_id=user_id, chat_id=chat_id, request=request, kind="build",
                                         operation=operation, project=project, idem_key=idem_key)
        if created:
            self._wake.set()
        return job, created

    def cancel(self, job_id: int) -> bool:
        ok = self.store.request_cancel(job_id)
        with self._lock:
            ev = self._cancels.get(job_id)
        if ev is not None:
            ev.set()
        job = self.store.get(job_id)
        if ok and job is not None and job.state == QUEUED and job_id not in self._running:
            self.store.transition(job_id, CANCELLED, "annullato in coda")
        return ok

    def cancel_all(self) -> int:
        n = 0
        for job in self.store.active():
            if job.kind == "build" and self.cancel(job.job_id):
                n += 1
        return n

    def running_ids(self) -> list[int]:
        with self._lock:
            return sorted(i for i, t in self._running.items() if t.is_alive())

    # -- execution -----------------------------------------------------------------

    def _launch(self, job: Job) -> None:
        cancel = threading.Event()

        def target() -> None:
            try:
                JobRunner(job.job_id, self.store, self.gate, self.pool, self.notify, self.cfg, cancel,
                          self.claim_project, self.release_project).run()
            finally:
                with self._lock:
                    self._running.pop(job.job_id, None)
                    self._cancels.pop(job.job_id, None)
                self._wake.set()

        t = threading.Thread(target=target, name=f"build-job-{job.job_id}", daemon=True)
        with self._lock:
            self._running[job.job_id] = t
            self._cancels[job.job_id] = cancel
        t.start()

    def dispatch_once(self) -> int:
        started = 0
        queued = [j for j in self.store.active() if j.kind == "build" and j.state == QUEUED]
        for job in queued:
            with self._lock:
                alive = sum(1 for t in self._running.values() if t.is_alive())
                if alive >= self.cfg.max_concurrent_jobs:
                    break
                if job.job_id in self._running:
                    continue
            if job.cancel_requested:
                self.store.transition(job.job_id, CANCELLED, "annullato in coda")
                continue
            self._launch(job)
            started += 1
        return started

    def start(self) -> None:
        def loop() -> None:
            last_retry = time.monotonic()
            while not self._stop.is_set():
                try:
                    if self._pending_recovery and time.monotonic() - last_retry >= self.recovery_retry_interval:
                        last_retry = time.monotonic()
                        self.retry_deferred_recovery()
                    self.dispatch_once()
                except Exception as exc:
                    LOG.error("dispatcher error %s", type(exc).__name__)
                self._wake.wait(2.0)
                self._wake.clear()

        self._dispatcher = threading.Thread(target=loop, name="build-dispatcher", daemon=True)
        self._dispatcher.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                alive = [t for t in self._running.values() if t.is_alive()]
            queued = [j for j in self.store.active() if j.kind == "build" and j.state == QUEUED]
            if not alive and not queued and not self._pending_recovery:
                return True
            time.sleep(0.05)
        return False

    # -- restart recovery ------------------------------------------------------------

    def recover_on_start(self) -> list[tuple[int, str]]:
        """Called once at service start, before dispatching. Never leaves a job half-applied."""
        report: list[tuple[int, str]] = []
        for job in self.store.active():
            if job.kind != "build":
                self.store.transition(job.job_id, FAILED, "interrotto da riavvio del servizio")
                report.append((job.job_id, "analisi interrotta dal riavvio"))
                continue
            if job.state == QUEUED and not self.store.ops(job.job_id):
                report.append((job.job_id, "in coda: riprende"))
                continue
            self.store.bump_restarts(job.job_id)
            report.append((job.job_id, self._recover_job(job.job_id)))
        return report

    def retry_deferred_recovery(self) -> list[tuple[int, str]]:
        with self._lock:
            pending = sorted(self._pending_recovery)
        out = []
        for job_id in pending:
            out.append((job_id, self._recover_job(job_id)))
        return out

    def _recover_job(self, job_id: int) -> str:
        job = self.store.get(job_id)
        if job is None or job.terminal:
            with self._lock:
                self._pending_recovery.discard(job_id)
            return "gia' concluso"
        rb = "not_needed"
        if [o for o in self.store.ops(job_id) if o["op"] != "snapshot"]:
            runner = JobRunner(job_id, self.store, self.gate, self.pool, self.notify, self.cfg,
                               threading.Event(), lambda n, c: True, lambda n: None)
            snaps = [o for o in self.store.ops(job_id) if o["op"] == "snapshot"]
            runner.snapshot_uid = job.uid if snaps else None
            try:
                runner.session_open = self.gate.has_session(job.uid)
            except GateError:
                runner.session_open = False
            rb = runner.rollback()
            if rb == "deferred":
                with self._lock:
                    first = job_id not in self._pending_recovery
                    self._pending_recovery.add(job_id)
                if first:
                    self.notify(job.telegram_chat_id,
                                f"♻️ LAVORO #{job_id}: servizio riavviato durante il lavoro. Il lock MCP della "
                                "sessione precedente e' ancora attivo: rollback rinviato alla sua scadenza "
                                "(nessun lock rubato).")
                return "rollback rinviato (lease MCP ancora attivo)"
            runner._close()
            self.store.update(job_id, rollback=rb)
        with self._lock:
            self._pending_recovery.discard(job_id)
        job = self.store.get(job_id)
        assert job is not None
        if rb == "failed":
            self.store.add_error(job_id, "riavvio: rollback non riuscito, intervento manuale")
            self.store.transition(job_id, FAILED, "riavvio: rollback non riuscito")
            what = "rollback NON riuscito: verificare"
        elif job.restarts <= self.cfg.max_auto_resume:
            for agent in AGENTS:
                self.store.set_agent(job_id, agent, "WAITING")
            self.store.update(job_id, attempts=0, tests_run=0, tests_passed=0, tests_failed=0,
                              test_result="", lock_state="NONE", executor=None,
                              project=job.project if job.operation == "modifica" else None)
            self.store.requeue_after_restart(job_id, "ripreso dopo riavvio")
            self._wake.set()
            what = f"rollback {rb}; ripreso dall'inizio"
        else:
            if job.state in (RUNNING, TESTING, REVIEWING) and rb == "done":
                self.store.transition(job_id, ROLLED_BACK, "riavvio ripetuto: rollback eseguito")
            else:
                self.store.transition(job_id, FAILED, "riavvio ripetuto: lavoro abbandonato")
            what = "abbandonato dopo riavvii ripetuti"
        final = self.store.get(job_id)
        if final is not None:
            self.notify(final.telegram_chat_id,
                        f"♻️ LAVORO #{job_id}: servizio riavviato durante il lavoro. "
                        f"Rollback: {rb}. Stato: {final.state}.")
        return what
