#!/bin/zsh
printf 'MCP Andrea: attivazione agent non amministratore sul Mac a noleggio.\n'
printf 'Crea backup, prova il nuovo agent e attiva l’avvio automatico.\n'
printf 'Se l’avvio fallisce, ripristina il collegamento precedente.\n'
printf 'Richiede autorizzazione locale amministratore per questa installazione.\n\n'
/usr/bin/sudo /usr/bin/python3 -I -B - --apply <<'MCPPY'
from pathlib import Path
import hashlib
p=Path('/Users/vagrant/MCPAndreaMacAgentSetupV09_20261002/install_mac_agent.py')
data=p.open('rb').read(65537)
if len(data)>65536 or hashlib.sha256(data).hexdigest() != '322c27c45652760b97326d53be33814f83f1d94de0c325de6652fcd98e38abcd':
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
