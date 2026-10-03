#!/bin/zsh
print 'MCP Andrea: aggiorna soltanto la ricerca sul Mac personale.'
print 'Crea un backup, collauda come utente non amministratore e riavvia il solo agent MCP.'
print 'Quando richiesta, inserisci la password di accesso del tuo Mac personale.'
/usr/bin/python3 -I -B -c 'import os,stat,hashlib,sys
path='"'"'/Users/babo/MCPAndreaSearchV010_20261002/upgrade_mac_search_v010_20261002.py'"'"'
expected='"'"'fddd5279a3070a717275a82766bcdcc55522ea5a4bc67cdb67845863905cc4ce'"'"'
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
path='"'"'/Users/babo/MCPAndreaSearchV010_20261002/upgrade_mac_search_v010_20261002.py'"'"'
expected='"'"'fddd5279a3070a717275a82766bcdcc55522ea5a4bc67cdb67845863905cc4ce'"'"'
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
