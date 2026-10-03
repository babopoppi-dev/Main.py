#!/bin/zsh
print 'MCP Andrea v0.12 p3: amministrazione del Mac via Telegram (0.12-personal-2 -> 0.12-personal-3).'
print 'Serve un bot Telegram NUOVO dedicato al Mac (@BotFather, /newbot): il token resta solo su questo Mac.'
print 'Abbina il bot, crea un backup, collauda come utente non amministratore, riavvia il solo agent MCP'
print 'e installa l helper root separato. In caso di errore sull agent ripristina la 0.12-personal-2.'
print 'Hash atteso installer: 34f2f867340af7dc0e6292f3285602789cbb6ec71c137b7388f9e1e23d643f7e'
/usr/bin/shasum -a 256 /Users/babo/MCPAndreaV012p3/upgrade_mac_v012p3_20261003.py
print 'Quando richiesta, inserisci la password di accesso del tuo Mac personale.'
/usr/bin/python3 -I -B -c 'import os,stat,hashlib,sys
path='"'"'/Users/babo/MCPAndreaV012p3/upgrade_mac_v012p3_20261003.py'"'"'
expected='"'"'34f2f867340af7dc0e6292f3285602789cbb6ec71c137b7388f9e1e23d643f7e'"'"'
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
path='"'"'/Users/babo/MCPAndreaV012p3/upgrade_mac_v012p3_20261003.py'"'"'
expected='"'"'34f2f867340af7dc0e6292f3285602789cbb6ec71c137b7388f9e1e23d643f7e'"'"'
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
    print 'ATTIVAZIONE_V012P3_MCP_COMPLETATA. Torna nella chat e scrivi Fatto.'
  else
    print 'Attivazione non completata. Lascia questa finestra aperta e torna nella chat.'
  fi
else
  print 'Controllo preliminare non superato. Torna nella chat.'
fi
read -r '?Premi Invio per chiudere questa finestra...'
