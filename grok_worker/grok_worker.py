#!/usr/bin/env python3
"""Grok worker: affida un lavoro a Grok (API xAI) e salva il risultato in un file unico.

Solo libreria standard, eseguibile con /usr/bin/python3 -I -B.
Chiave: variabile d'ambiente XAI_API_KEY (mai su riga di comando, mai nei file).

Esempi:
  python3 -I -B grok_worker.py modelli
  python3 -I -B grok_worker.py lavoro --tipo revisione --file ../la-marruca-ios/README.md \
      "Controlla coerenza e errori"
  python3 -I -B grok_worker.py lavoro --compito compito.txt --file a.py --file b.py --prova
"""
import argparse
import datetime
import fnmatch
import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")
DEFAULT_MODEL = os.environ.get("XAI_MODEL", "grok-4")
OUT_DIR = os.environ.get("GROK_OUT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "risultati"))
MAX_FILE_BYTES = 200_000
MAX_TOTAL_BYTES = 600_000
TIMEOUT = 300

# Dati che non devono uscire verso un fornitore esterno (PEC, posta, chiavi, pagamenti).
BLOCKED_PATTERNS = [
    "*.env", ".env*", "*.pem", "*.key", "*.p12", "*.p8", "*.mobileprovision", "*.keychain*",
    "*secret*", "*token*", "*password*", "*credential*", "id_rsa*", "id_ed25519*",
    "pec*", "*_pec*", "*-pec*", "*.eml", "*.mbox", "*GoogleService-Info*", "*.sqlite*", "*.db",
]

ROLES = {
    "generale": "Sei un collaboratore tecnico del team. Rispondi in italiano, in modo concreto.",
    "revisione": (
        "Sei un revisore indipendente. Cerca errori, rischi e incoerenze nei file forniti. "
        "Per ogni problema: file, riga o sezione, gravita (alta/media/bassa), motivo, correzione proposta. "
        "Non inventare problemi: se non ne trovi, dillo. Rispondi in italiano."
    ),
    "codice": (
        "Sei uno sviluppatore. Proponi le modifiche come diff unificato applicabile con 'git apply', "
        "seguito da una breve spiegazione. Mantieni lo stile del codice esistente. Rispondi in italiano."
    ),
    "testi": (
        "Sei un copywriter per un piccolo marchio italiano. Scrivi testi chiari e naturali, "
        "senza esagerazioni. Rispondi in italiano."
    ),
    "ricerca": (
        "Sei un analista. Riassumi lo stato delle informazioni che conosci, distinguendo fatti e ipotesi, "
        "e indica le date dei dati quando le conosci. Rispondi in italiano."
    ),
}


class WorkerError(Exception):
    pass


def is_blocked(path):
    name = os.path.basename(path).lower()
    full = path.lower()
    return any(fnmatch.fnmatch(name, p.lower()) or fnmatch.fnmatch(full, "*/" + p.lower()) for p in BLOCKED_PATTERNS)


def read_context(paths):
    parts, total = [], 0
    for p in paths:
        if is_blocked(p):
            raise WorkerError(f"file escluso per riservatezza: {p}")
        if not os.path.isfile(p):
            raise WorkerError(f"file non trovato: {p}")
        size = os.path.getsize(p)
        if size > MAX_FILE_BYTES:
            raise WorkerError(f"file troppo grande ({size} byte, max {MAX_FILE_BYTES}): {p}")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise WorkerError(f"contesto totale oltre {MAX_TOTAL_BYTES} byte")
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            parts.append(f"=== FILE: {p} ===\n{f.read()}\n=== FINE FILE ===")
    return "\n\n".join(parts)


def build_messages(role, task, context):
    user = task if not context else f"{task}\n\nFILE DI CONTESTO:\n\n{context}"
    return [{"role": "system", "content": ROLES[role]}, {"role": "user", "content": user}]


def api_request(method, path, key, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE_URL + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise WorkerError(f"API xAI HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise WorkerError(f"API xAI non raggiungibile: {e.reason}") from None


def get_key():
    key = os.environ.get("XAI_API_KEY", "").strip()
    if not key:
        raise WorkerError("XAI_API_KEY non impostata")
    return key


def unique_out_path(role):
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(OUT_DIR, f"grok_{role}_{stamp}_{os.getpid()}")
    path, n = base + ".md", 1
    while os.path.exists(path):
        path, n = f"{base}_{n}.md", n + 1
    return path


def cmd_models(_args):
    res = api_request("GET", "/models", get_key())
    for m in res.get("data", []):
        print(m.get("id"))
    return 0


def cmd_job(args):
    if args.compito:
        with open(args.compito, "r", encoding="utf-8") as f:
            task = f.read().strip()
    else:
        task = " ".join(args.testo).strip()
    if not task:
        raise WorkerError("compito vuoto: passa un testo o --compito FILE")
    context = read_context(args.file)
    messages = build_messages(args.tipo, task, context)

    if args.prova:
        print(f"[prova] modello={args.modello} tipo={args.tipo} file={len(args.file)} "
              f"caratteri={sum(len(m['content']) for m in messages)}")
        print("[prova] nessuna chiamata inviata")
        return 0

    body = {"model": args.modello, "messages": messages, "temperature": args.temperatura}
    res = api_request("POST", "/chat/completions", get_key(), body)
    try:
        answer = res["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise WorkerError(f"risposta inattesa: {json.dumps(res)[:500]}") from None
    usage = res.get("usage", {})

    out = unique_out_path(args.tipo)
    header = (
        f"# Grok — {args.tipo}\n\n"
        f"- data: {datetime.datetime.now().isoformat(timespec='seconds')}\n"
        f"- modello: {res.get('model', args.modello)}\n"
        f"- file: {', '.join(args.file) or 'nessuno'}\n"
        f"- token: {usage.get('prompt_tokens', '?')} in / {usage.get('completion_tokens', '?')} out\n\n"
        f"## Compito\n\n{task}\n\n## Risposta\n\n"
    )
    with open(out, "x", encoding="utf-8") as f:
        f.write(header + answer.rstrip() + "\n")
    print(out)
    if args.stampa:
        print()
        print(answer)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Affida un lavoro a Grok (xAI) e salva il risultato.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("modelli", help="elenca i modelli disponibili per la chiave").set_defaults(func=cmd_models)

    j = sub.add_parser("lavoro", help="esegue un compito")
    j.add_argument("testo", nargs="*", help="compito (oppure --compito FILE)")
    j.add_argument("--compito", help="file di testo con il compito")
    j.add_argument("--tipo", choices=sorted(ROLES), default="generale")
    j.add_argument("--file", action="append", default=[], help="file di contesto (ripetibile)")
    j.add_argument("--modello", default=DEFAULT_MODEL)
    j.add_argument("--temperatura", type=float, default=0.2)
    j.add_argument("--prova", action="store_true", help="mostra cosa verrebbe inviato, senza chiamare l'API")
    j.add_argument("--stampa", action="store_true", help="stampa anche la risposta")
    j.set_defaults(func=cmd_job)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except WorkerError as e:
        print(f"errore: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
