"""Native coordination probe for mac_mio (UID5000, temporary workspace area)."""
import json, os, platform, stat, sys, tempfile, time, unicodedata
from pathlib import Path
from file_tools import FileTools
import work_sessions as ws

out = {'python': sys.version.split()[0], 'platform': platform.platform(), 'uid': os.getuid()}
try: out['boot_identity'] = ws.boot_identity()[:12]; out['boot_identity_stable'] = ws.boot_identity() == ws.boot_identity()
except Exception as e: out['boot_identity'] = 'ERROR ' + repr(e)
a = ws.shared_clock(); time.sleep(0.2); b = ws.shared_clock()
out['clock_raw_delta'] = round(b - a, 3)
base = Path(tempfile.mkdtemp(prefix='coordprobe-'))
work = base / 'work'; work.mkdir(mode=0o700)
f = FileTools([str(work)], str(base / 'journal'))
w = ws.WorkSessions(str(base / 'sessions'), f)
f.lock_provider = w.lock_provider
A = w.open('native:probe1', 'probe A', 5); B = w.open('native:probe1', 'probe B', 5)
cred = lambda s: ('native:probe1', s['work_session_id'], s['work_session_token'])
checks = {}
def expect_fail(name, fn, exc=PermissionError):
    try: fn(); checks[name] = 'FAIL (no error)'
    except exc: checks[name] = 'ok'
    except Exception as e: checks[name] = 'FAIL ' + repr(e)
nfc = 'Caf\u00e9'; w.acquire(*cred(A), str(work / nfc), 5)
expect_fail('nfd_case_alias_conflict', lambda: w.acquire(*cred(B), str(work / 'CAFE\u0301' / 'x'), 5))
(work / nfc).mkdir()
out['volume_case_insensitive'] = (work / 'CAFE\u0301').exists()
ida = w.authenticate(*cred(A)); idb = w.authenticate(*cred(B))
r = f.write_file(str(work / nfc / 'f.txt'), 'native', session_id=ida); checks['locked_write'] = 'ok'
expect_fail('foreign_write_refused', lambda: f.write_file(str(work / nfc / 'g.txt'), 'x', session_id=idb))
expect_fail('foreign_rollback_refused', lambda: f.rollback_file(r['operation_id'], session_id=idb))
st = base / 'sessions' / 'state.json'; s0 = os.stat(st)
w.snapshot(); w.authenticate(*cred(A)); s1 = os.stat(st)
checks['no_rewrite_on_read'] = 'ok' if (s0.st_ino, s0.st_mtime_ns) == (s1.st_ino, s1.st_mtime_ns) else 'FAIL'
checks['state_mode_0600'] = 'ok' if stat.S_IMODE(s1.st_mode) == 0o600 else oct(s1.st_mode)
raw = st.read_text()
checks['no_token_in_state'] = 'ok' if A['work_session_token'] not in raw and B['work_session_token'] not in raw else 'FAIL'
w.close(); w = ws.WorkSessions(str(base / 'sessions'), f); f.lock_provider = w.lock_provider
checks['restart_keeps_session'] = 'ok' if w.authenticate(*cred(A)) == ida else 'FAIL'
expect_fail('restart_keeps_lock', lambda: w.acquire(*cred(B), str(work), 5))
f.rollback_file(r['operation_id'], session_id=ida)
checks['rollback_own'] = 'ok' if not (work / nfc / 'f.txt').exists() else 'FAIL'
w.end(*cred(A)); w.acquire(*cred(B), str(work), 5); checks['close_releases_lock'] = 'ok'
expect_fail('closed_session_refused', lambda: w.authenticate(*cred(A)))
w.end(*cred(B)); w.close(); f.close()
out['checks'] = checks
out['all_ok'] = all(v == 'ok' for v in checks.values()) and not str(out['boot_identity']).startswith('ERROR')
print(json.dumps(out, indent=1, ensure_ascii=True))
