from __future__ import annotations

"""Telegram rendering of job records (Italian, iPhone-friendly, no secrets)."""

import time
from datetime import datetime
from typing import Iterable, Optional

from job_store import (
    ANALYZING, CANCELLED, COMPLETED, FAILED, QUEUED, REVIEWING, ROLLED_BACK, RUNNING, TESTING, Job,
)

try:
    from zoneinfo import ZoneInfo

    _TZ = ZoneInfo("Europe/Rome")
except Exception:  # tzdata missing: fall back to host local time
    _TZ = None

STATE_ICON = {
    QUEUED: "⏳",
    ANALYZING: "🔎",
    RUNNING: "🟢",
    TESTING: "🧪",
    REVIEWING: "🧐",
    COMPLETED: "✅",
    FAILED: "❌",
    CANCELLED: "⛔",
    ROLLED_BACK: "↩️",
}
STATE_IT = {
    QUEUED: "IN CODA",
    ANALYZING: "ANALISI",
    RUNNING: "RUNNING",
    TESTING: "TESTING",
    REVIEWING: "REVIEW",
    COMPLETED: "COMPLETATO",
    FAILED: "FALLITO",
    CANCELLED: "ANNULLATO",
    ROLLED_BACK: "ROLLBACK ESEGUITO",
}
AGENT_LABEL = {"codex": "Codex", "claude": "Claude", "grok": "Grok"}


def _dt(ts: Optional[float]) -> Optional[datetime]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, _TZ) if _TZ else datetime.fromtimestamp(ts)


def hhmmss(ts: Optional[float]) -> str:
    d = _dt(ts)
    return d.strftime("%H:%M:%S") if d else "-"


def day_time(ts: Optional[float]) -> str:
    d = _dt(ts)
    return d.strftime("%d/%m %H:%M") if d else "-"


def duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def job_duration(job: Job, now: Optional[float] = None) -> str:
    start = job.started_at or job.created_at
    end = job.completed_at or (now or time.time())
    return duration(end - start)


def test_line(job: Job) -> str:
    if not job.tests_run and not job.test_result:
        return "non ancora eseguiti"
    if job.tests_run:
        verdict = "PASS" if job.tests_failed == 0 and job.test_result == "PASS" else "FAIL"
        return f"{job.tests_passed}/{job.tests_run} {verdict}"
    return job.test_result


def _agent_role_text(job: Job, agent: str) -> str:
    state = job.agent_state(agent)
    is_exec = job.executor == agent
    if job.kind != "build":
        return {"DONE": "analisi completata", "FAILED": "errore", "OFFLINE": "offline",
                "SKIPPED": "non usato", "RUNNING": "in corso", "WAITING": "in attesa",
                "CANCELLED": "annullato"}.get(state, state)
    if is_exec:
        return {"DONE": "sviluppo completato", "FAILED": "sviluppo fallito", "RUNNING": "sviluppo in corso",
                "OFFLINE": "offline", "CANCELLED": "annullato", "WAITING": "in attesa",
                "SKIPPED": "non avviato"}.get(state, state)
    return {"DONE": "review completata", "FAILED": "review non riuscita", "RUNNING": "review in corso",
            "OFFLINE": "review non disponibile (offline)", "SKIPPED": "review saltata",
            "CANCELLED": "annullato", "WAITING": "in attesa"}.get(state, state)


def format_active(job: Job) -> str:
    icon = STATE_ICON.get(job.state, "•")
    lines = [f"{icon} LAVORO #{job.job_id} — {job.state}"]
    lines.append(f"Progetto: {job.project or '(da definire)'}" if job.kind == "build" else "Tipo: analisi team")
    lines.append(f"Inizio: {hhmmss(job.started_at or job.created_at)}")
    for agent in ("codex", "claude", "grok"):
        suffix = " (esecutore)" if job.executor == agent else ""
        lines.append(f"{AGENT_LABEL[agent]}: {job.agent_state(agent)}{suffix}")
    lines.append(f"Fase: {job.phase or '-'}")
    if job.kind == "build":
        lines.append(f"Test: {test_line(job)}")
        if job.attempts:
            lines.append(f"Tentativi fix: {job.attempts}")
        lines.append(f"Work lock: {job.lock_state}")
    lines.append(f"Durata: {job_duration(job)}")
    return "\n".join(lines)


def format_final(job: Job, max_summary: int = 1500) -> str:
    icon = STATE_ICON.get(job.state, "•")
    lines = [f"{icon} LAVORO #{job.job_id} {STATE_IT.get(job.state, job.state)}"]
    if job.kind == "build":
        lines.append(f"Progetto: {job.project or '-'}")
        for agent in ("codex", "claude", "grok"):
            lines.append(f"{AGENT_LABEL[agent]}: {_agent_role_text(job, agent)}")
        lines.append(f"File creati/modificati: {len(job.files)}")
        lines.append(f"Test: {test_line(job)}")
        lines.append(f"Errori: {job.tests_failed if job.state == COMPLETED else max(job.tests_failed, len(job.errors))}")
        lines.append(f"Tentativi fix: {job.attempts}")
        rollback = {
            "none": "non necessario", "not_needed": "non necessario", "done": "eseguito",
            "partial": "PARZIALE - verificare", "failed": "NON RIUSCITO - verificare",
        }.get(job.rollback, job.rollback)
        lines.append(f"Rollback: {rollback}")
        if job.project_path and job.state == COMPLETED:
            lines.append("Percorso:")
            lines.append(job.project_path)
    else:
        for agent in ("codex", "claude", "grok"):
            lines.append(f"{AGENT_LABEL[agent]}: {_agent_role_text(job, agent)}")
    lines.append(f"Durata: {job_duration(job)}")
    last_error = ""
    if job.state != COMPLETED and job.errors:
        last_error = job.errors[-1][:400]
        lines.append("Ultimo errore: " + last_error)
    if job.result_summary:
        summary = job.result_summary.strip()
        if last_error:  # the abort summary starts with the same error line: don't repeat it
            first, _, rest = summary.partition("\n")
            if first.strip() == last_error.strip() or last_error.strip().startswith(first.strip()):
                summary = rest.strip()
    if job.result_summary and summary:
        if len(summary) > max_summary:
            summary = summary[: max_summary - 1] + "…"
        lines.append("")
        lines.append(summary)
    return "\n".join(lines)


def format_detail(job: Job) -> str:
    if job.state in (COMPLETED, FAILED, CANCELLED, ROLLED_BACK):
        head = format_final(job, max_summary=2500)
    else:
        head = format_active(job)
    extra = [
        "",
        f"Creato: {day_time(job.created_at)}",
        f"Operazione: {job.operation}",
        "Richiesta: " + (job.request[:600] + ("…" if len(job.request) > 600 else "")),
    ]
    if job.executor:
        extra.append(f"Esecutore: {AGENT_LABEL.get(job.executor, job.executor)}")
    if job.work_session_id:
        extra.append(f"Work session: {job.work_session_id[:8]}…")
    if job.files:
        shown = ", ".join(job.files[:15]) + (" …" if len(job.files) > 15 else "")
        extra.append(f"File: {shown}")
    if job.restarts:
        extra.append(f"Riprese dopo riavvio: {job.restarts}")
    return head + "\n".join(extra)


def format_line(job: Job) -> str:
    icon = STATE_ICON.get(job.state, "•")
    what = job.project if job.kind == "build" else "analisi"
    req = job.request.replace("\n", " ")
    if len(req) > 48:
        req = req[:47] + "…"
    tests = f" · test {test_line(job)}" if job.kind == "build" and (job.tests_run or job.test_result) else ""
    return f"{icon} #{job.job_id} {day_time(job.created_at)} {job.state} · {what or '-'}{tests}\n   {req}"


def format_list(jobs: Iterable[Job], title: str) -> str:
    jobs = list(jobs)
    if not jobs:
        return f"{title}\nNessun lavoro registrato."
    return title + "\n" + "\n".join(format_line(j) for j in jobs)
