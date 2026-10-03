#!/bin/zsh
printf 'MCP Andrea: secondo tentativo, attivazione agent non amministratore sul Mac a noleggio.\n'
printf 'Crea backup, prova il nuovo agent e attiva l’avvio automatico.\n'
printf 'Se l’avvio fallisce, ripristina il collegamento precedente.\n'
printf 'Installazione locale gia autorizzata. Corregge la verifica Xcode del primo tentativo.\n\n'
/usr/bin/sudo /usr/bin/python3 -I -B - --apply <<'MCPPY'
from pathlib import Path
import hashlib
p=Path('/Users/vagrant/MCPAndreaMacAgentSetupV09R2_20261002/install_mac_agent.py')
data=p.open('rb').read(65537)
if len(data)>65536 or hashlib.sha256(data).hexdigest() != '47bbf8e89ab9e5d6085c1b9e97152029af26bdb28104ee18d7ae13b8d3d97b40':
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
