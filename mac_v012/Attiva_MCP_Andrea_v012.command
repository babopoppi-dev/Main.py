#!/bin/zsh
print 'MCP Andrea v0.12 sul Mac personale: agent 0.12 e amministrazione via Telegram.'
print 'Crea un backup, collauda come utente non amministratore, abbina un bot Telegram nuovo'
print 'e riavvia il solo agent MCP. In caso di errore ripristina la versione 0.11.'
print 'Hash atteso installer: ''+digest+'
/usr/bin/shasum -a 256 ''+remote+''
print 'Quando richiesta, inserisci la password di accesso del tuo Mac personale.'
/usr/bin/python3 -I -B -c 'import os,stat,hashlib,sys
path='"'"'/Users/babo/MCPAndreaRepo/mac_v012/upgrade_mac_v012_20261003.py'"'"'
expected='"'"'f660f4ae451334ea7754903adae2d9d5111235a0450bb1d8be74654e3fcb38a1'"'"'
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
path='"'"'/Users/babo/MCPAndreaRepo/mac_v012/upgrade_mac_v012_20261003.py'"'"'
expected='"'"'f660f4ae451334ea7754903adae2d9d5111235a0450bb1d8be74654e3fcb38a1'"'"'
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
    print 'ATTIVAZIONE_MCP_V012_COMPLETATA. Torna nella chat e scrivi Fatto.'
  else
    print 'Attivazione non completata. Lascia questa finestra aperta e torna nella chat.'
  fi
else
  print 'Controllo preliminare non superato. Torna nella chat.'
fi
read -r '?Premi Invio per chiudere questa finestra...'
