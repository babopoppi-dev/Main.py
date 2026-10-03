#!/usr/bin/env python3
"""central-mcp-approver: esegue comandi admin sul VPS solo dopo approvazione Telegram.
Gira come root. Legge richieste da QUEUE (scritte dal gateway), chiede conferma
all'unico utente autorizzato, esegue esattamente il comando mostrato, scrive l'esito in RESULTS."""
import hashlib, html, json, os, re, shlex, stat, subprocess, sys, time, urllib.parse, urllib.request

BASE = os.environ.get("CMCP_APPROVER_BASE", "/var/lib/central-mcp-approver")
QUEUE, RESULTS, AUDIT = BASE + "/queue", BASE + "/results", BASE + "/audit.jsonl"
CLAIMS = BASE + "/execution-claims"
CONF = os.environ.get("CMCP_APPROVER_CONF", "/etc/central-mcp-approver")
with open(CONF + "/bot_token") as f:
    TOKEN = f.read().strip()
with open(CONF + "/chat_id") as f:
    CHAT = int(f.read().strip())
API = "https://api.telegram.org/bot%s/" % TOKEN
EXPIRE_S = 600
RUN_TIMEOUT = 300
MAX_CMD = 3000
MAX_OUT = 20000
SENSITIVE = re.compile(r"/home/ubuntu|btc_|crontab|\bubuntu\b|/etc/sudoers|userdel|chmod\s+-R\s+7|rm\s+-rf\s+/", re.I)
ALLOWLIST = {
    "systemctl restart central-mcp-gateway-test.service",
    "systemctl restart central-mcp-vps-agent-test.service",
    "systemctl status central-mcp-gateway-test.service --no-pager",
    "systemctl status central-mcp-vps-agent-test.service --no-pager",
    "journalctl -u central-mcp-gateway-test.service -n 100 --no-pager",
    "journalctl -u central-mcp-vps-agent-test.service -n 100 --no-pager",
    "systemctl reload caddy",
    "caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile",
}
pending = {}  # rid -> {"req":..., "msg_id":..., "stage":1|2, "expires":...}


def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), *a, flush=True)


def audit(event, **kw):
    kw.update(event=event, ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with open(AUDIT, "a") as f:
        f.write(json.dumps(kw, ensure_ascii=False) + "\n")


def tg(method, **params):
    http_timeout = params.pop('_http_timeout', 40)
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                   for k, v in params.items()}).encode()
    req = urllib.request.Request(API + method, data=data)
    with urllib.request.urlopen(req, timeout=http_timeout) as r:
        out = json.loads(r.read())
    if not out.get("ok"):
        raise RuntimeError("telegram %s failed" % method)
    return out["result"]


def write_result(rid, **kw):
    kw["id"] = rid
    kw["updated"] = int(time.time())
    tmp = os.path.join(RESULTS, ".%s.tmp" % rid)
    with open(tmp, "w") as f:
        json.dump(kw, f, ensure_ascii=False)
    os.chmod(tmp, 0o640)
    os.replace(tmp, os.path.join(RESULTS, rid + ".json"))


def h(cmd):
    return hashlib.sha256(cmd.encode()).hexdigest()


def parse_argv(cmd):
    if not re.fullmatch(r"[A-Za-z0-9_./:=@%+, -]+", cmd):
        raise ValueError("unsupported command character")
    argv = shlex.split(cmd, posix=True)
    if not argv:
        raise ValueError("empty command")
    return argv


class ExpiredRequest(ValueError):
    pass


def require_unexpired(req):
    if time.time() >= req["expires_at"]:
        raise ExpiredRequest("request expired; command was not executed")


def claim_execution(req):
    """Durable, root-owned one-shot claim, written before starting a process."""
    os.makedirs(CLAIMS, mode=0o700, exist_ok=True)
    st = os.lstat(CLAIMS)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise RuntimeError("unsafe execution claim directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    path = os.path.join(CLAIMS, req["id"] + ".json")
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"id": req["id"], "sha256": req["sha256"], "claimed_at": time.time()}, f)
        f.flush()
        os.fsync(f.fileno())
    dfd = os.open(CLAIMS, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def run(req):
    require_unexpired(req)
    cmd = req["command"]
    if h(cmd) != req["sha256"]:
        raise RuntimeError("hash mismatch")
    if req["argv"] != parse_argv(cmd):
        raise RuntimeError("command arguments mismatch")
    if not re.fullmatch(r"[0-9a-f]{32}", req["id"]):
        raise RuntimeError("invalid request ID")
    claim_execution(req)
    require_unexpired(req)
    t0 = time.time()
    try:
        argv = req["argv"]
        p = subprocess.run(argv, shell=False, capture_output=True, text=True,
                           timeout=RUN_TIMEOUT, cwd="/root",
                           env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                                "LANG": "C.UTF-8", "HOME": "/root"})
        out, code = (p.stdout + p.stderr), p.returncode
    except subprocess.TimeoutExpired as e:
        out, code = ((e.stdout or "") + (e.stderr or "")) if isinstance(e.stdout, str) else "", 124
    out = out[-MAX_OUT:]
    write_result(req["id"], status="done", exit_code=code, output=out,
                 seconds=round(time.time() - t0, 1), caller=req["caller"])
    audit("executed", id=req["id"], caller=req["caller"], sha256=req["sha256"],
          command=req["command"], reason=req["reason"], exit_code=code, output=out)
    return code, out


def text_for(req, header):
    cmd = html.escape(req["command"])
    warn = "\n⚠️ <b>COMANDO SENSIBILE: richiede doppia conferma</b>" if req.get("sensitive") else ""
    return ("%s\n<b>Da:</b> %s\n<b>Motivo:</b> %s\n<b>ID:</b> <code>%s</code>%s\n\n<pre>%s</pre>"
            % (header, html.escape(req["caller"]), html.escape(req["reason"] or "-"),
               req["id"][:8], warn, cmd))


def buttons(req, stage):
    hh = req["sha256"][:16]
    ok = ("✅ Approva", "a:%s:%s" % (req["id"], hh)) if stage == 1 else \
         ("⚠️ CONFERMA DEFINITIVA", "c:%s:%s" % (req["id"], hh))
    return {"inline_keyboard": [[{"text": ok[0], "callback_data": ok[1]},
                                 {"text": "❌ Rifiuta", "callback_data": "r:%s" % req["id"]}]]}


def load_request(path):
    with open(path) as f:
        r = json.load(f)
    os.remove(path)
    rid, cmd = r.get("id", ""), r.get("command", "")
    if not re.fullmatch(r"[0-9a-f]{32}", rid) or not isinstance(cmd, str) or not cmd.strip():
        raise ValueError("invalid request")
    if rid in pending or os.path.exists(os.path.join(RESULTS, rid + ".json")) or os.path.exists(os.path.join(CLAIMS, rid + ".json")):
        raise ValueError("duplicate request ID")
    if len(cmd) > MAX_CMD or "\x00" in cmd:
        raise ValueError("command too long or invalid")
    if r.get("sha256") != h(cmd):
        raise ValueError("hash mismatch")
    argv = parse_argv(cmd)
    machine = str(r.get("machine", ""))
    requester = str(r.get("requester", "")).lower()
    session_id = str(r.get("session_id", ""))
    created_at = int(r.get("created_at", 0))
    expires_at = int(r.get("expires_at", 0))
    if machine != "vps" or requester not in ("chatgpt", "claude"):
        raise ValueError("invalid machine/requester")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{3,160}", session_id):
        raise ValueError("invalid session_id")
    if not created_at or created_at > time.time() or expires_at - created_at != EXPIRE_S or time.time() >= expires_at:
        raise ValueError("request expired or invalid ttl")
    caller = requester + ":" + session_id
    return {"id": rid, "command": cmd, "argv": argv, "sha256": r["sha256"],
            "reason": str(r.get("reason", ""))[:500], "caller": caller,
            "machine": machine, "requester": requester, "session_id": session_id,
            "oauth_client_id": str(r.get("oauth_client_id", ""))[:160],
            "oauth_client_name": str(r.get("oauth_client_name", ""))[:160],
            "created_at": created_at, "expires_at": expires_at,
            "sensitive": bool(SENSITIVE.search(cmd))}


def scan_queue():
    for name in sorted(os.listdir(QUEUE)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(QUEUE, name)
        try:
            req = load_request(path)
        except Exception as e:
            log("rejected malformed request", name, e)
            rid = name[:-5]
            if re.fullmatch(r"[0-9a-f]{32}", rid) and not os.path.exists(os.path.join(RESULTS, rid + ".json")):
                write_result(rid, status="error", error="richiesta non valida: %s" % e)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            continue
        audit("requested", id=req["id"], caller=req["caller"], sha256=req["sha256"],
              command=req["command"], reason=req["reason"])
        if req["command"].strip() in ALLOWLIST and not req["sensitive"]:
            code, out = run(req)
            tg("sendMessage", chat_id=CHAT, parse_mode="HTML",
               text=text_for(req, "ℹ️ <b>Eseguito senza approvazione (lista fissa)</b>")
               + "\n<b>Esito:</b> exit %s" % code)
            continue
        msg = tg("sendMessage", chat_id=CHAT, parse_mode="HTML",
                 text=text_for(req, "🔐 <b>Richiesta comando amministratore</b>"),
                 reply_markup=buttons(req, 1))
        pending[req["id"]] = {"req": req, "msg_id": msg["message_id"], "stage": 1,
                              "expires": req["expires_at"]}
        write_result(req["id"], status="waiting", caller=req["caller"])


def finish(p, header, extra=""):
    try:
        tg("editMessageText", chat_id=CHAT, message_id=p["msg_id"], parse_mode="HTML",
           text=text_for(p["req"], header) + extra)
    except Exception as e:
        log("edit failed", e)


def on_callback(cq):
    # A UI acknowledgement is not the authorization itself. A timeout or a
    # stale callback acknowledgement must not discard a valid signed-button tap.
    # Never log API URLs or exception text here: they can contain bot credentials.
    try:
        tg("answerCallbackQuery", callback_query_id=cq["id"], _http_timeout=3)
    except Exception as exc:
        audit("callback_ack_failed", error_type=type(exc).__name__)
    if cq.get("from", {}).get("id") != CHAT or cq.get("message", {}).get("chat", {}).get("id") != CHAT:
        audit("callback_rejected_foreign_user", from_id=cq.get("from", {}).get("id"))
        return
    parts = (cq.get("data") or "").split(":")
    kind, rid = parts[0], parts[1] if len(parts) > 1 else ""
    p = pending.get(rid)
    if not p:
        return
    req = p["req"]
    if time.time() >= req["expires_at"]:
        pending.pop(rid)
        write_result(rid, status="expired", caller=req["caller"])
        audit("expired", id=rid)
        finish(p, "⌛ <b>Scaduto</b> (comando non eseguito)")
        return
    if kind == "r":
        pending.pop(rid)
        write_result(rid, status="rejected", caller=req["caller"])
        audit("rejected", id=rid, caller=req["caller"])
        finish(p, "❌ <b>Rifiutato</b>")
        return
    if len(parts) != 3 or parts[2] != req["sha256"][:16]:
        return
    if kind == "a" and p["stage"] in (1, 2) and req["sensitive"]:
        p["stage"] = 2
        try:
            tg("editMessageText", chat_id=CHAT, message_id=p["msg_id"], parse_mode="HTML",
               text=text_for(req, "⚠️ <b>Seconda conferma richiesta</b>"), reply_markup=buttons(req, 2))
        except Exception as exc:
            audit("second_confirmation_display_failed", id=rid, error_type=type(exc).__name__)
        # Retrying the first button only redisplays the second confirmation.
        # Only its distinct 'c' callback can authorize execution at stage 2.
        return
    if (kind == "a" and p["stage"] == 1) or (kind == "c" and p["stage"] == 2):
        pending.pop(rid)
        audit("approved", id=rid, caller=req["caller"], stage=p["stage"])
        finish(p, "⏳ <b>Approvato, in esecuzione…</b>")
        try:
            code, out = run(req)
            tail = html.escape(out[-1500:]) if out else "(nessun output)"
            finish(p, "✅ <b>Eseguito</b> (exit %s)" % code, "\n<b>Output:</b>\n<pre>%s</pre>" % tail)
        except ExpiredRequest as e:
            write_result(rid, status="expired", error=str(e), caller=req["caller"])
            finish(p, "⌛ <b>Scaduto</b> (comando non eseguito)")
        except Exception as e:
            write_result(rid, status="error", error=str(e), caller=req["caller"])
            finish(p, "💥 <b>Errore</b>: %s" % html.escape(str(e)))


def expire():
    now = time.time()
    for rid in [r for r, p in pending.items() if p["expires"] <= now]:
        p = pending.pop(rid)
        write_result(rid, status="expired", caller=p["req"]["caller"])
        audit("expired", id=rid)
        finish(p, "⌛ <b>Scaduto</b> (nessuna risposta in 10 minuti)")


def startup_cleanup():
    for name in os.listdir(RESULTS):
        if name.endswith(".json"):
            path = os.path.join(RESULTS, name)
            try:
                with open(path) as f:
                    r = json.load(f)
                if r.get("status") == "waiting":
                    write_result(r["id"], status="expired", caller=r.get("caller", "?"),
                                 error="approver riavviato")
            except Exception:
                pass


def main():
    os.umask(0o027)
    startup_cleanup()
    offset = None
    # scarta eventuali vecchi tap rimasti in coda su Telegram
    for u in tg("getUpdates", timeout=0):
        offset = u["update_id"] + 1
    log("approver avviato v0.7")
    tg("sendMessage", chat_id=CHAT, text="🟢 Approver del gateway MCP avviato.")
    log("approver pronto v0.7")
    while True:
        try:
            for name in os.listdir(QUEUE):
                p = os.path.join(QUEUE, name)
                if os.path.islink(p) or not os.path.isfile(p):
                    os.remove(p) if os.path.islink(p) else None
            scan_queue()
            params = {"timeout": 5, "allowed_updates": ["callback_query"]}
            if offset is not None:
                params["offset"] = offset
            for u in tg("getUpdates", **params):
                offset = u["update_id"] + 1
                if "callback_query" in u:
                    on_callback(u["callback_query"])
            expire()
        except Exception as e:
            log("loop error:", type(e).__name__, str(e)[:200])
            time.sleep(5)


if __name__ == "__main__":
    main()
