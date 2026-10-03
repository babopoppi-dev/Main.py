#!/bin/zsh
printf 'MCP Andrea: account dedicato, collaudo e servizio sul Mac personale.\n'
printf 'Richiede autorizzazione locale amministratore per questa installazione.\n'
printf 'Il collegamento attuale cambia solo dopo il superamento dei controlli.\n\n'
/usr/bin/sudo /usr/bin/python3 -I -B - --apply <<'MCPPY'
from pathlib import Path
import hashlib
p=Path('/Users/babo/MCPAndreaMacMioSetupV09_20261002/setup_personal.py')
data=p.open('rb').read(131073)
if len(data)>131072 or hashlib.sha256(data).hexdigest()!='193ea13da717b7ee1aba5ed6165bd03eae46906b6a9393191c5d10d0fb33ae17':
    raise SystemExit('Verifica fallita: esecuzione bloccata')
exec(compile(data,str(p),'exec'),{'__name__':'__main__','__file__':str(p),'APPROVED_SOURCE':data})
MCPPY
mcp_setup_exit=$?
if (( mcp_setup_exit == 0 )); then
    printf '\nInstallazione completata. Torna in chat e scrivi Fatto.\n'
else
    printf '\nInstallazione fermata. Invia alla chat il messaggio mostrato sopra.\n'
fi
read -r '?Premi Invio per chiudere questa finestra... '
exit "$mcp_setup_exit"
