# ANDREA AI TEAM v3 — stato al 2026-10-06 (lavoro notturno autonomo)

## Fatto
- Ispezione live via MCP Andrea: nessun lock/sessione attivi; health gateway e VPS HEALTHY
  (mac_mio DEGRADED solo per disco quasi pieno).
- Root progetti creata via MCP: `/var/lib/central-mcp-vps-agent-test/workspace/team-projects/`
  con `.snapshots/` e `.trash/` (README incluso).
- Semantica MCP verificata dal vivo su un progetto di prova (poi rimosso): create_directory,
  write_file, rollback_file, copy_file di alberi (snapshot), delete_path di alberi, ripristino da
  snapshot, formato list_directory. `move_file` NON sposta directory → cestino = copia + delete.
- Sorgente v3 completo in staging: `/var/lib/central-mcp-vps-agent-test/workspace/andrea-ai-team/`
  (14 file, SHA-256 verificati uno per uno contro `MANIFEST_V3.sha256`).
- 52 test offline verdi (Python 3.12 e 3.13, 6 run consecutivi senza instabilità).
- Deploy simulato in locale: preflight, token errato rifiutato, apply OK, smoke fallito → rollback
  automatico a v2 verificato.
- Lock rilasciato e work_session chiusa.

## NON fatto (richiede te)
- Deploy live: serve root (sudo / admin_request approvata su Telegram) e la tua doppia conferma.
- Smoke live dello shell MCP: il classificatore di sicurezza di questa sessione ha negato a me
  `enable_full_shell`; il comportamento reale dei lock richiesti dallo shell va verificato dallo
  smoke del deploy (`live_smoke_v3.py`). Se risponde LOCK_REQUIRED: impostare
  `GATE_SHELL_LOCK_PATH` nella unit del gate.

## Alle 9:30
1. `sudo bash /var/lib/central-mcp-vps-agent-test/workspace/andrea-ai-team/deploy_v3_root.sh preflight`
2. leggere l'output; se `PREFLIGHT_OK`, eseguire `... apply <TOKEN>` (doppia conferma)
3. Telegram: `/stato` → deve mostrare `Write Gate MCP: ON`; poi `/aiuto`
4. Collaudo: inviare il testo del Mini Task Manager; seguire con `/incorso`, poi `/ultimo`
5. In caso di problemi: `... deploy_v3_root.sh rollback`

## Aggiornamento 09:30 — deploy eseguito
- Primo apply: smoke FAIL su `enable_full_shell` → rollback automatico a v2 riuscito.
- Causa (dal sorgente dell'agente VPS): la shell MCP richiede un lock che copra l'INTERO workspace;
  il gateway nasconde il messaggio d'errore (sempre `RuntimeError`).
- Correzioni: gate prende il lock sul workspace solo per la durata dei test (attesa max 5 min,
  mai furto); conflitti riconosciuti tramite `who_is_working`; polling dell'output della shell
  (risposta dopo 3 s + `has_more`); fase di scrittura/test serializzata tra lavori.
- Secondo apply: SMOKE_V3=OK, DEPLOY_V3=OK. Bot in v3 (`service_v3.py`), gate attivo.
- Collaudo Mini Task Manager avviato (lavoro #1, progetto `mini_task_manager`).

## Collaudo e prove live (2026-10-06)
| # | Prova | Esito | Verifica |
|---|---|---|---|
| 1 | Mini Task Manager (benchmark) | COMPLETATO, 36/36 PASS, 1 fix, 7m54s | riletto via MCP e rieseguito: 36/36 OK |
| 2 | Messaggio duplicato | rifiutato: "Richiesta identica gia' in corso: lavoro #2" | un solo job |
| 3 | `/annulla` durante lo sviluppo | ANNULLATO, rollback eseguito (3 rollback_file) | progetto rimosso, nessun lock/sessione residui |
| 4 | Lock occupato da altra chat | FALLITO dopo 3 tentativi a 20 s, "nessun lock rubato" | lock esterno intatto, 0 file toccati |
| 5 | Riavvio `andrea-ai-team.service` in RUNNING | rollback nativo in <1 s (sessione del gate sopravvissuta), lock rilasciati, job rimesso in coda e ripreso | audit MCP |

Correzioni emerse dalle prove (deploy successivo):
- dopo un riavvio il nome progetto viene mantenuto (prima un `crea` ripreso ricalcolava il nome:
  `prova_riavvio` → `temp_converter`);
- messaggio finale: errore non piu' ripetuto; esecutore mai partito = "non avviato";
- riepilogo: rimosse le note dell'LLM tipo "test non eseguiti / spetta all'orchestratore".
