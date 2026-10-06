# ANDREA AI TEAM v3 — Write Gate MCP + Project Builder + Storico lavori

Stato: **in staging** nel workspace, **non ancora in produzione**. Il live resta v2 finché non si esegue
il deploy con doppia conferma (vedi sotto).

## Architettura

```
iPhone / Telegram (@teamandreabot, owner 1090463042)
  └─ andrea-ai-team.service (orchestratore v3, utente andrea-ai-team)
       ├─ storico lavori SQLite/WAL  /var/lib/andrea-ai-team/state/jobs.sqlite3
       ├─ provider worker v2 (INVARIATO) → Codex + Claude + Grok (Gemini DORMANT)
       └─ write gate (socket Unix, peer uid verificato)
            └─ andrea-ai-team-write-gate.service (utente mcp-gateway, come l'helper di stato)
                 └─ MCP Andrea (gateway locale) → work_session → work_lock → tool → VPS
```

- I provider producono **solo testo**. Nessun LLM ha shell, filesystem, SSH, Mac, servizi o root.
- L'orchestratore **non** ha credenziali MCP e non vede il workspace (`InaccessiblePaths`).
- Il gate è l'unico componente con la credenziale MCP (la stessa già usata dall'helper di stato) e
  accetta solo `(job, progetto, percorso relativo)`: i percorsi assoluti sono ricostruiti dal gate,
  validati (`gate_policy.py`) e devono restare dentro la root progetti.
- Il token della work_session MCP resta nella memoria del gate: non arriva mai all'orchestratore,
  ai provider, ai log o al database.

## Funzioni MCP Andrea riusate (non reimplementate)

| Esigenza | Funzione MCP Andrea |
|---|---|
| sessione/ownership/lease | `work_session` open/renew/close (lease 20 min, heartbeat ogni 2 min) |
| esclusività progetto | `work_lock` acquire/renew/release, conflitto padre/figlio, **hard-fail, nessun furto** |
| scrittura/backup | `write_file`, `create_directory`, `copy_file` (snapshot ad albero), `delete_path` |
| rollback | `rollback_file` per operation_id (rollback durevole nativo) |
| test reali | `enable_full_shell` (network `none`) + `shell_exec` + heartbeat `shell_session` + `disable_full_shell` |
| audit / task state / health | audit e task-state SQLite/WAL di MCP Andrea; `system_health`; circuit breaker dell'agente |

Verificato dal vivo il 2026-10-06: `create_directory`, `write_file`, `copy_file` di un albero
(snapshot), `delete_path` di un albero, ripristino da snapshot, `rollback_file`, formato di
`list_directory` (`[FILE] pkg/m.py`). `move_file` **non** sposta directory: il cestino usa
copia + `delete_path`.

## Root progetti

`/var/lib/central-mcp-vps-agent-test/workspace/team-projects/`

Scelta dopo verifica permessi: `/var/lib/andrea-ai-team/projects` è **fuori** dalle allowed roots
MCP della VPS (allowed: `workspace`, `tmp`, `btc-readonly-export` in sola lettura) e lo shell MCP
isolato vede solo `workspace`. Struttura: `<progetto>/`, `.snapshots/<progetto>/<job>/`,
`.trash/<progetto>-<job>/`.

Progetti protetti (Bitcoin, La Marruca, LiDAR, RENTRI, MCP Andrea, andrea-ai-team, gateway):
stanno fuori dalla root progetti, quindi non raggiungibili dal gate; in più i loro nomi sono vietati
come nomi di progetto TEAM e le richieste di modifica che li citano vengono rifiutate.

## Flusso di un lavoro di sviluppo

richiesta Telegram → job persistente (QUEUED) → analisi parallela Codex+Claude+Grok (ANALYZING)
→ scelta esecutore (Codex; se offline Claude, poi Grok; uno solo alla volta) → work_session + work_lock
(retry su conflitto, mai furto) → snapshot (progetti esistenti) → piano file → un file per chiamata
(RUNNING) → test reali (TESTING) → se FAIL: errore all'esecutore → correzione (max 3) → test →
review Claude + Grok (REVIEWING) → eventuale correzione (max 1 giro) → test finale → COMPLETED,
oppure rollback (ROLLED_BACK) → messaggio finale su Telegram.

Limiti: 3 cicli di fix, 1 giro di fix da review, 40 min per job, 2 job concorrenti, 180 s per run di test,
80 file / 256 KB per file / 4 MB per job.

## Storico persistente

Tabella `jobs` con tutti i campi richiesti (id, tempi, utente/chat, richiesta, progetto, operazione,
stato generale + Codex/Claude/Grok, esecutore, work_session_id, work_lock_id, file, test, tentativi,
errori sanitizzati, rollback, esito) + `job_ops` (operation_id MCP per il rollback) + `job_events`
(audit). Transizioni validate; tutte le stringhe passano dal redattore di segreti (`redact.py`).
Idempotenza: un messaggio Telegram (chat + message_id) = un solo lavoro; testo identico mentre un
lavoro uguale è attivo → rifiutato.

Recupero dopo riavvio: analisi interrotte → FAILED; build interrotte → rollback (nativo se il gate
ha ancora la sessione, altrimenti cestino/snapshot con nuova sessione; se il lease MCP della
sessione morta è ancora attivo il rollback viene **rinviato** e ritentato ogni 60 s) → ripresa
automatica una volta, poi abbandono.

## Comandi Telegram

`/crea <richiesta>` · `/crea nome: <richiesta>` · `/modifica <progetto> <richiesta>` · linguaggio
naturale ("Crea un programma…", "Nel progetto X aggiungi…") · `/incorso` · `/ultimo` · `/lavori` ·
`/storico [pN|id|progetto]` · `/lavoro <id>` · `/annulla <id>` · `/progetti` · `/aiuto` ·
più tutti i comandi v2 (`/stato`, `/stop` ora annulla anche i build, `/riprendi`, …).

## File

| File | Ruolo |
|---|---|
| `service_v3.py` | orchestratore Telegram v3 (estende `TeamServiceV2`, non lo sostituisce) |
| `project_builder.py` | pipeline, pool provider serializzato, JobManager, recupero |
| `job_store.py` / `job_format.py` | storico SQLite/WAL e messaggi Telegram |
| `gate_server.py` / `write_gate.py` / `gate_policy.py` | write gate (server, client, policy) |
| `redact.py` | redazione segreti |
| `test_v3.py` / `v3_testkit.py` | 52 test offline (MCP finto su directory reale, test eseguiti davvero) |
| `live_smoke_v3.py` | smoke sul gate e MCP reali (progetto usa-e-getta, rollback finale) |
| `andrea-ai-team-write-gate.service` / `andrea-ai-team-v3.service` | unit systemd |
| `deploy_v3_root.sh` | deploy con preflight/token/apply e rollback automatico |
| `MANIFEST_V3.sha256` | integrità dei sorgenti verificata dal deploy |

## Deploy (doppia conferma)

```
sudo bash /var/lib/central-mcp-vps-agent-test/workspace/andrea-ai-team/deploy_v3_root.sh preflight
# nessuna modifica live; stampa TOKEN=xxxxxxxxxxxx
sudo bash /var/lib/central-mcp-vps-agent-test/workspace/andrea-ai-team/deploy_v3_root.sh apply xxxxxxxxxxxx
# rollback manuale in qualsiasi momento:
sudo bash /var/lib/central-mcp-vps-agent-test/workspace/andrea-ai-team/deploy_v3_root.sh rollback
```

`apply` fa: verifica manifest → backup in `/var/lib/andrea-ai-team/deploy-backups/team-v3-pre` →
installa i moduli → avvia il gate → **smoke live** (test reali PASS/FAIL via MCP + rollback) →
installa la unit v3 → riavvia l'orchestratore → verifica. Qualsiasi errore → rollback automatico a v2.
Provider worker, Gemini, helper MCP e `/etc/andrea-ai-team/env` non vengono toccati.
