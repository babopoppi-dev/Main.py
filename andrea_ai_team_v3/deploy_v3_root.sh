#!/usr/bin/env bash
# ANDREA AI TEAM v3 deploy (write gate + project builder + job history).
#
# Double confirmation, as for previous live replacements:
#   1) sudo bash deploy_v3_root.sh preflight        -> no live change; prints TOKEN=<t>
#   2) sudo bash deploy_v3_root.sh apply <t>         -> live replacement, automatic rollback on any error
#   (optional) sudo bash deploy_v3_root.sh rollback  -> restore the pre-v3 files and units
#
# Provider worker, provider units, Gemini (DORMANT), MCP helper and Telegram env are NOT modified.
set -euo pipefail
umask 077

MODE="${1:-}"
TOKEN_ARG="${2:-}"
SRC="/var/lib/central-mcp-vps-agent-test/workspace/andrea-ai-team"
APP="/opt/andrea-ai-team"
STATE="/var/lib/andrea-ai-team"
BACKUP="$STATE/deploy-backups/team-v3-pre"
TOKEN_FILE="$STATE/deploy-backups/team-v3-preflight.token"
IPC_GROUP="andrea-ai-team-ipc"
ORCH_USER="andrea-ai-team"
GATE_USER="mcp-gateway"
PROJECTS="/var/lib/central-mcp-vps-agent-test/workspace/team-projects"
UNIT_ORCH="/etc/systemd/system/andrea-ai-team.service"
UNIT_GATE="/etc/systemd/system/andrea-ai-team-write-gate.service"

PY_FILES=(redact.py job_store.py job_format.py gate_policy.py write_gate.py project_builder.py
          service_v3.py gate_server.py test_v3.py v3_testkit.py live_smoke_v3.py)
# Existing live modules the v3 code imports (never modified by this deploy).
BASE_FILES=(team_core.py team_core_v2.py service.py service_v2.py worker_client_v2.py mcp_helper.py)

log() { printf '[deploy-v3] %s\n' "$*"; }

verify_manifest() {
  ( cd "$SRC" && /usr/bin/sha256sum --quiet -c MANIFEST_V3.sha256 )
}

offline_tests() {
  local tmp
  tmp="$(/usr/bin/mktemp -d /tmp/aiteam-v3-test.XXXXXX)"
  for f in "${BASE_FILES[@]}"; do /bin/cp "$APP/$f" "$tmp/$f"; done
  for f in "${PY_FILES[@]}"; do /bin/cp "$SRC/$f" "$tmp/$f"; done
  local rc=0
  ( cd "$tmp" && PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B -W ignore test_v3.py ) || rc=$?
  /bin/rm -rf "$tmp"
  return $rc
}

preflight() {
  log "verifica integrita' sorgenti (MANIFEST_V3.sha256)"
  verify_manifest
  for f in "${PY_FILES[@]}" andrea-ai-team-v3.service andrea-ai-team-write-gate.service; do
    test -f "$SRC/$f"
  done
  for f in "${BASE_FILES[@]}"; do test -f "$APP/$f"; done
  getent group "$IPC_GROUP" >/dev/null
  id -u "$ORCH_USER" >/dev/null
  id -u "$GATE_USER" >/dev/null
  test -f /etc/central-mcp-gateway/gateway-test.json
  test -f /etc/andrea-ai-team/env
  test -d "$PROJECTS"
  log "test offline v3 (copia temporanea con i moduli live)"
  offline_tests
  log "test regressione v2 esistenti"
  ( cd "$SRC" && PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B test_v2.py >/dev/null 2>&1 ) \
    || { log "test_v2.py FALLITO"; exit 1; }
  ( cd "$SRC" && PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B test_worker_v2.py >/dev/null 2>&1 ) \
    || { log "test_worker_v2.py FALLITO"; exit 1; }
  /usr/bin/systemd-analyze verify "$SRC/andrea-ai-team-write-gate.service" "$SRC/andrea-ai-team-v3.service" || true
  /bin/mkdir -p "$(dirname "$TOKEN_FILE")"
  local token
  token="$( (cat "$SRC/MANIFEST_V3.sha256"; date +%s) | /usr/bin/sha256sum | cut -c1-12)"
  printf '%s %s\n' "$token" "$(date +%s)" > "$TOKEN_FILE"
  log "PREFLIGHT_OK - nessuna modifica live eseguita"
  echo "TOKEN=$token"
  echo "Per sostituire il live: sudo bash $SRC/deploy_v3_root.sh apply $token"
}

do_rollback() {
  log "ROLLBACK verso pre-v3"
  if [ -f "$BACKUP/andrea-ai-team.service" ]; then
    /bin/cp -a "$BACKUP/andrea-ai-team.service" "$UNIT_ORCH"
  fi
  if [ -f "$BACKUP/andrea-ai-team-write-gate.service" ]; then
    /bin/cp -a "$BACKUP/andrea-ai-team-write-gate.service" "$UNIT_GATE"
  else
    /usr/bin/systemctl disable --now andrea-ai-team-write-gate.service 2>/dev/null || true
    /bin/rm -f "$UNIT_GATE"
  fi
  for f in "${PY_FILES[@]}"; do
    if [ -f "$BACKUP/opt/$f" ]; then
      /bin/cp -a "$BACKUP/opt/$f" "$APP/$f"
    else
      /bin/rm -f "$APP/$f"
    fi
  done
  /usr/bin/systemctl daemon-reload || true
  /usr/bin/systemctl restart andrea-ai-team.service || true
  log "rollback completato: servizio v2 ripristinato"
}

apply() {
  test -n "$TOKEN_ARG" || { log "manca il token del preflight"; exit 2; }
  test -f "$TOKEN_FILE" || { log "eseguire prima il preflight"; exit 2; }
  read -r expected created < "$TOKEN_FILE"
  if [ "$TOKEN_ARG" != "$expected" ]; then log "token non valido"; exit 2; fi
  if [ $(( $(date +%s) - created )) -gt 7200 ]; then log "token scaduto (2h): rifare il preflight"; exit 2; fi
  verify_manifest

  /bin/mkdir -p "$BACKUP/opt"
  /bin/cp -a "$UNIT_ORCH" "$BACKUP/andrea-ai-team.service"
  if [ -f "$UNIT_GATE" ]; then /bin/cp -a "$UNIT_GATE" "$BACKUP/andrea-ai-team-write-gate.service"; fi
  for f in "${PY_FILES[@]}"; do
    if [ -f "$APP/$f" ]; then /bin/cp -a "$APP/$f" "$BACKUP/opt/$f"; fi
  done
  if [ -f "$STATE/state/jobs.sqlite3" ]; then /bin/cp -a "$STATE/state/jobs.sqlite3" "$BACKUP/jobs.sqlite3.bak"; fi

  trap 'rc=$?; log "ERRORE rc=$rc"; do_rollback; exit $rc' ERR

  for f in "${PY_FILES[@]}"; do
    /usr/bin/install -o root -g "$IPC_GROUP" -m 0640 "$SRC/$f" "$APP/$f"
  done
  ( cd "$SRC" && for f in "${PY_FILES[@]}"; do
      a="$(/usr/bin/sha256sum "$APP/$f" | cut -d' ' -f1)"; b="$(grep "  $f\$" MANIFEST_V3.sha256 | cut -d' ' -f1)"
      [ "$a" = "$b" ]
    done )

  /usr/bin/install -o root -g root -m 0644 "$SRC/andrea-ai-team-write-gate.service" "$UNIT_GATE"
  /usr/bin/systemctl daemon-reload
  /usr/bin/systemctl enable andrea-ai-team-write-gate.service
  /usr/bin/systemctl restart andrea-ai-team-write-gate.service
  for _ in $(seq 1 20); do [ -S /run/andrea-ai-team-gate/gate.sock ] && break; sleep 0.5; done
  /usr/bin/systemctl is-active --quiet andrea-ai-team-write-gate.service

  log "smoke live del write gate (MCP reale, progetto usa-e-getta, rollback finale)"
  ( cd "$APP" && /usr/sbin/runuser -u "$ORCH_USER" -g "$IPC_GROUP" -- \
      /usr/bin/python3 -B "$APP/live_smoke_v3.py" )

  /usr/bin/install -o root -g root -m 0644 "$SRC/andrea-ai-team-v3.service" "$UNIT_ORCH"
  /usr/bin/systemctl daemon-reload
  /usr/bin/systemctl restart andrea-ai-team.service
  started=0
  for _ in $(seq 1 30); do
    if /usr/bin/journalctl -u andrea-ai-team.service --since "-2min" --no-pager 2>/dev/null \
        | grep -q "ANDREA AI TEAM v3 starting"; then started=1; break; fi
    sleep 1
  done
  [ "$started" = 1 ]
  /usr/bin/systemctl is-active --quiet andrea-ai-team.service

  trap - ERR
  /bin/rm -f "$TOKEN_FILE"
  log "DEPLOY_V3=OK"
  log "Verifica da Telegram: /stato, /aiuto, poi il collaudo Mini Task Manager."
}

case "$MODE" in
  preflight) preflight ;;
  apply) apply ;;
  rollback) do_rollback ;;
  *) echo "uso: $0 preflight | apply <TOKEN> | rollback"; exit 2 ;;
esac
