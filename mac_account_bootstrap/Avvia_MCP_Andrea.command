#!/bin/zsh
printf 'MCP Andrea: creazione account dedicato sul Mac a noleggio.\n'
printf 'Se viene richiesta, inserisci qui la password del Mac.\n\n'
/usr/bin/sudo /usr/bin/python3 -I -B - --apply <<'PY'
from pathlib import Path
import hashlib
p = Path('/Users/vagrant/MCPAndreaAccountSetup20261002/bootstrap_account.py')
data = p.open('rb').read(65537)
expected = '673a989f829b2e67d3f320baa15c373f44e8af8cf1d75e42c046ee331a0eac1f'
if len(data) > 65536 or hashlib.sha256(data).hexdigest() != expected:
    raise SystemExit('Verifica fallita: esecuzione bloccata')
exec(compile(data, str(p), 'exec'), {
    '__name__': '__main__', '__file__': str(p), 'APPROVED_SOURCE': data
})
PY
mcp_exit=$?
if (( mcp_exit == 0 )); then
    printf '\nOperazione completata. Torna nella chat e scrivi Fatto.\n'
else
    printf '\nOperazione non completata. Comunica alla chat il messaggio qui sopra.\n'
fi
read -r '?Premi Invio per chiudere questa finestra... '
exit "$mcp_exit"
