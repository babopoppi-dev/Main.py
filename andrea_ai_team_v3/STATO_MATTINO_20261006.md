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
