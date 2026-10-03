#!/bin/zsh
print 'MCP Andrea: riprende la ricerca sul Mac personale dopo il riavvio interrotto.'
print 'Verifica e conserva il backup originale, collauda e riavvia il solo agent MCP.'
print 'Quando richiesta, inserisci la password di accesso del tuo Mac personale.'
/usr/bin/python3 -I -B -c 'import os,stat,hashlib,sys
path='"'"'/Users/babo/MCPAndreaSearchV010_20261002/upgrade_mac_search_v010r2_20261002.py'"'"'
expected='"'"'4bb2fcf8abe3536f34b6e0e15d3e8e84c92e72781b3c12799ba04ccdefb5216d'"'"'
fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
with os.fdopen(fd,'"'"'rb'"'"') as f:
 st=os.fstat(f.fileno())
 if not stat.S_ISREG(st.st_mode) or st.st_uid!=501 or st.st_nlink!=1 or st.st_mode&0o022:raise SystemExit('"'"'File installer non sicuro'"'"')
 raw=f.read(2097153)
if hashlib.sha256(raw).hexdigest()!=expected:raise SystemExit('"'"'Hash installer diverso: operazione fermata'"'"')
if len(sys.argv)!=2 or sys.argv[1] not in ('"'"'--check'"'"','"'"'--apply'"'"'):raise SystemExit('"'"'Azione non valida'"'"')
action=sys.argv[1]
sys.argv=[path,action]
context={'"'"'__name__'"'"':'"'"'__main__'"'"','"'"'__file__'"'"':path}
if action=='"'"'--apply'"'"':context['"'"'APPROVED_SOURCE'"'"']=raw
exec(compile(raw,path,'"'"'exec'"'"'),context)
' --check
if [[ $? == 0 ]]; then
  /usr/bin/sudo /usr/bin/python3 -I -B -c 'import os,stat,hashlib,sys
path='"'"'/Users/babo/MCPAndreaSearchV010_20261002/upgrade_mac_search_v010r2_20261002.py'"'"'
expected='"'"'4bb2fcf8abe3536f34b6e0e15d3e8e84c92e72781b3c12799ba04ccdefb5216d'"'"'
fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
with os.fdopen(fd,'"'"'rb'"'"') as f:
 st=os.fstat(f.fileno())
 if not stat.S_ISREG(st.st_mode) or st.st_uid!=501 or st.st_nlink!=1 or st.st_mode&0o022:raise SystemExit('"'"'File installer non sicuro'"'"')
 raw=f.read(2097153)
if hashlib.sha256(raw).hexdigest()!=expected:raise SystemExit('"'"'Hash installer diverso: operazione fermata'"'"')
if len(sys.argv)!=2 or sys.argv[1] not in ('"'"'--check'"'"','"'"'--apply'"'"'):raise SystemExit('"'"'Azione non valida'"'"')
action=sys.argv[1]
sys.argv=[path,action]
context={'"'"'__name__'"'"':'"'"'__main__'"'"','"'"'__file__'"'"':path}
if action=='"'"'--apply'"'"':context['"'"'APPROVED_SOURCE'"'"']=raw
exec(compile(raw,path,'"'"'exec'"'"'),context)
' --apply
  if [[ $? == 0 ]]; then
    print 'AGGIORNAMENTO_RICERCA_MCP_COMPLETATO. Torna nella chat e scrivi Fatto.'
  else
    print 'Aggiornamento non completato. Lascia questa finestra aperta e torna nella chat.'
  fi
else
  print 'Controllo preliminare non superato. Torna nella chat.'
fi
read -r '?Premi Invio per chiudere questa finestra...'
