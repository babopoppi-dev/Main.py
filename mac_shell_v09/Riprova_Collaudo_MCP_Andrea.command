#!/bin/zsh
printf 'MCP Andrea: ripetizione collaudo isolato, revisione2 del nuovo account sul Mac a noleggio.\n'
printf 'Collaudo gia autorizzato nella chat.\n'
printf 'Questo collaudo non migra l’agent attivo.\n\n'
/usr/bin/sudo /usr/bin/python3 -I -B - --apply <<'MCPPY'
from pathlib import Path
import hashlib
p=Path('/Users/vagrant/MCPAndreaShellPreflightSetupR2_20261002/preflight_installer.py')
data=p.open('rb').read(65537)
if len(data)>65536 or hashlib.sha256(data).hexdigest() != '506636dda780016d3f5c3e81084062a12ebdb1e802aee339c82d8fef395a4b8e':
    raise SystemExit('Verifica fallita: esecuzione bloccata')
exec(compile(data,str(p),'exec'),{'__name__':'__main__','__file__':str(p),'APPROVED_SOURCE':data})
MCPPY
mcp_test_exit=$?
if (( mcp_test_exit == 0 )); then
    printf '\nCollaudo completato. Torna in chat e scrivi Fatto.\n'
else
    printf '\nCollaudo fermato. Invia alla chat il messaggio mostrato sopra.\n'
fi
read -r '?Premi Invio per chiudere questa finestra... '
exit "$mcp_test_exit"
