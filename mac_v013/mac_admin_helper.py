#!/usr/bin/env python3
"""MCP Andrea Mac admin helper (root LaunchDaemon), v0.12.

Reads requests queued by the non-admin agent (UID 5000), shows the exact
command to Andrea through a dedicated Telegram bot (not the VPS bot), and runs
it as root only after his approval. Every command is approved individually;
there is no allowlist. Sensitive commands need a second confirmation.
Self-contained on purpose: no imports from the agent tree.
"""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request

VERSION = '0.12-mac-admin-1'
ROOT = Path(os.environ.get('MCP_MAC_ADMIN_ROOT', '/Library/MCPAndreaMacAdmin'))
AGENT_UID = 5000
AGENT_GID = 5000
EXPIRE_S = 600
MAX_COMMAND = 3000
MAX_TIMEOUT = 900
MAX_PENDING = 3
MAX_REQUEST = 16384
MAX_OUT = 20000
CHARSET = re.compile(r'[A-Za-z0-9_./:=@%+, -]+')
HEX32 = re.compile(r'[0-9a-f]{32}')
CALLER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}')
SENSITIVE = re.compile(
    r'(^|/)(rm|rmdir|mv|dd|dscl|dseditgroup|sysadminctl|csrutil|nvram|diskutil|fdesetup|'
    r'security|chmod|chown|chflags|launchctl|kill|killall|pkill|shutdown|reboot|halt|'
    r'spctl|tccutil|pfctl|profiles|systemsetup|networksetup|softwareupdate|installer|'
    r'tmutil|pmset|scutil|visudo|sudo|su|bash|zsh|sh|python3?|perl|ruby|osascript|curl|git)( |$)'
    r'|/etc/|/System/|/Library/Launch|/Library/MCPAndrea|/Users/|\.ssh|keychain|bitcoin|marruca|lidar',
    re.I)
ENV = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_US.UTF-8', 'HOME': '/var/root'}


class ExpiredRequest(ValueError):
    pass


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def parse_argv(command):
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND or not CHARSET.fullmatch(command):
        raise ValueError('unsupported command')
    argv = shlex.split(command, posix=True)
    if not argv or not argv[0].startswith('/') or '/../' in argv[0] + '/' or argv[0].endswith('/'):
        raise ValueError('the program must be an absolute path')
    return argv


class Telegram:
    """Minimal Bot API client. Never log URLs or exception text: they carry the token."""
    def __init__(self, token):
        if not re.fullmatch(r'[0-9]{5,15}:[A-Za-z0-9_-]{30,64}', token or ''):
            raise ValueError('invalid bot token format')
        self.api = 'https://api.telegram.org/bot%s/' % token

    def __call__(self, method, **params):
        timeout = params.pop('_http_timeout', 40)
        data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                       for k, v in params.items()}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.api + method, data=data), timeout=timeout) as r:
                out = json.loads(r.read())
        except Exception as exc:
            raise RuntimeError('telegram %s failed (%s)' % (method, type(exc).__name__)) from None
        if not out.get('ok'):
            raise RuntimeError('telegram %s failed' % method)
        return out['result']


class Helper:
    def __init__(self, root=ROOT, tg=None, chat_id=None, agent_uid=AGENT_UID, agent_gid=AGENT_GID,
                 owner_uid=0, now=time.time, cwd='/var/root'):
        self.root = Path(root)
        self.outbox, self.results = self.root / 'outbox', self.root / 'results'
        self.claims, self.audit_path = self.root / 'claims', self.root / 'audit.jsonl'
        self.tg, self.chat = tg, chat_id
        self.agent_uid, self.agent_gid, self.owner_uid = agent_uid, agent_gid, owner_uid
        self.now, self.cwd = now, cwd
        self.pending = {}

    # ---------- storage ----------
    def check_layout(self):
        def need(path, uid, gid, mode):
            st = os.lstat(str(path))
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != uid or (gid is not None and st.st_gid != gid) or stat.S_IMODE(st.st_mode) != mode:
                raise RuntimeError('unsafe layout: ' + str(path))
        need(self.root, self.owner_uid, None, 0o755)
        need(self.outbox, self.agent_uid, self.agent_gid, 0o700)
        need(self.results, self.owner_uid, self.agent_gid, 0o750)
        need(self.claims, self.owner_uid, None, 0o700)

    def audit(self, event, **kw):
        kw.update(event=event, ts=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self.now())))
        fd = os.open(str(self.audit_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as f:
            f.write(json.dumps(kw, ensure_ascii=False) + '\n')

    def write_result(self, rid, **kw):
        kw['id'] = rid
        kw['updated'] = int(self.now())
        self._publish(rid + '.json', kw)

    def _publish(self, name, value):
        dfd = os.open(str(self.results), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            temp = '.%s.%d.tmp' % (name, os.getpid())
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640, dir_fd=dfd)
            with os.fdopen(fd, 'w') as f:
                json.dump(value, f, ensure_ascii=False)
                f.flush()
                os.fchmod(f.fileno(), 0o640)
                if os.geteuid() == 0:
                    os.fchown(f.fileno(), self.owner_uid, self.agent_gid)
                os.fsync(f.fileno())
            os.rename(temp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        finally:
            os.close(dfd)

    def result_exists(self, rid):
        return os.path.lexists(str(self.results / (rid + '.json'))) or os.path.lexists(str(self.claims / (rid + '.json')))

    def heartbeat(self, busy_until=None):
        self._publish('helper_status.json', {'time': self.now(), 'version': VERSION, 'pid': os.getpid(),
                                             'pending': len(self.pending), 'busy_until': busy_until})

    # ---------- requests ----------
    def validate(self, raw):
        if not isinstance(raw, dict) or set(raw) != {'id', 'command', 'argv', 'sha256', 'reason', 'timeout', 'caller',
                                                     'work_session_id', 'created_at', 'expires_at'}:
            raise ValueError('unexpected request fields')
        rid, cmd = raw['id'], raw['command']
        if not isinstance(rid, str) or not HEX32.fullmatch(rid):
            raise ValueError('invalid request id')
        argv = parse_argv(cmd)
        if raw['argv'] != argv or raw['sha256'] != sha(cmd):
            raise ValueError('command hash or arguments mismatch')
        if not isinstance(raw['caller'], str) or not CALLER.fullmatch(raw['caller']):
            raise ValueError('invalid caller')
        if not isinstance(raw['work_session_id'], str) or not HEX32.fullmatch(raw['work_session_id']):
            raise ValueError('invalid work session')
        if type(raw['timeout']) is not int or not 1 <= raw['timeout'] <= MAX_TIMEOUT:
            raise ValueError('invalid timeout')
        reason = raw['reason']
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise ValueError('invalid reason')
        created, expires, now = raw['created_at'], raw['expires_at'], self.now()
        if type(created) is not int or type(expires) is not int or created > now + 5 or expires - created != EXPIRE_S or now >= expires:
            raise ValueError('request expired or invalid ttl')
        req = dict(raw)
        req['sensitive'] = bool(SENSITIVE.search(cmd))
        return req

    def take_outbox(self):
        """Read and remove queued files; the outbox is agent-owned and untrusted."""
        dfd = os.open(str(self.outbox), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        out = []
        try:
            st = os.fstat(dfd)
            if st.st_uid != self.agent_uid or stat.S_IMODE(st.st_mode) != 0o700:
                raise RuntimeError('unsafe outbox')
            for name in sorted(os.listdir(dfd)):
                rid = name[:-5] if name.endswith('.json') else None
                if rid is None or not HEX32.fullmatch(rid):
                    try:
                        if name.endswith('.tmp') and self.now() - os.lstat(name, dir_fd=dfd).st_mtime < 60:
                            continue
                        os.unlink(name, dir_fd=dfd)
                    except (FileNotFoundError, IsADirectoryError, PermissionError):
                        pass
                    continue
                data, error = None, None
                try:
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
                    with os.fdopen(fd, 'rb') as f:
                        fst = os.fstat(f.fileno())
                        if not stat.S_ISREG(fst.st_mode) or fst.st_uid != self.agent_uid or fst.st_nlink != 1 or fst.st_size > MAX_REQUEST:
                            raise ValueError('unsafe request file')
                        data = json.loads(f.read(MAX_REQUEST + 1))
                except Exception as exc:
                    error = str(exc)[:200]
                try:
                    os.unlink(name, dir_fd=dfd)
                except (FileNotFoundError, IsADirectoryError):
                    pass
                out.append((rid, data, error))
        finally:
            os.close(dfd)
        return out

    def text_for(self, req, header):
        warn = '\n\u26a0\ufe0f <b>COMANDO SENSIBILE: richiede doppia conferma</b>' if req.get('sensitive') else ''
        return ('%s\n<b>Mac:</b> mac_mio (root)\n<b>Da:</b> %s\n<b>Sessione:</b> %s\n<b>Motivo:</b> %s\n'
                '<b>Timeout:</b> %ss\n<b>ID:</b> <code>%s</code> \u00b7 sha <code>%s</code>%s\n\n<pre>%s</pre>'
                % (header, html.escape(req['caller']), req['work_session_id'][:8], html.escape(req['reason']),
                   req['timeout'], req['id'][:8], req['sha256'][:12], warn, html.escape(req['command'])))

    def buttons(self, req, stage):
        hh = req['sha256'][:16]
        ok = ('\u2705 Approva', 'a:%s:%s' % (req['id'], hh)) if stage == 1 else \
             ('\u26a0\ufe0f CONFERMA DEFINITIVA', 'c:%s:%s' % (req['id'], hh))
        return {'inline_keyboard': [[{'text': ok[0], 'callback_data': ok[1]},
                                     {'text': '\u274c Rifiuta', 'callback_data': 'r:%s' % req['id']}]]}

    def scan(self):
        for rid, data, error in self.take_outbox():
            caller = data.get('caller') if isinstance(data, dict) and isinstance(data.get('caller'), str) else '?'
            try:
                if error:
                    raise ValueError(error)
                if data.get('id') != rid:
                    raise ValueError('file name and request id differ')
                if rid in self.pending or self.result_exists(rid):
                    raise ValueError('duplicate request id')
                if len(self.pending) >= MAX_PENDING:
                    raise ValueError('too many pending requests')
                req = self.validate(data)
            except Exception as exc:
                self.audit('rejected_malformed', id=rid, error=str(exc)[:200])
                if not self.result_exists(rid) and rid not in self.pending:
                    self.write_result(rid, status='error', error='richiesta non valida: %s' % str(exc)[:200], caller=caller)
                continue
            self.audit('requested', id=rid, caller=req['caller'], sha256=req['sha256'], command=req['command'],
                       reason=req['reason'], work_session_id=req['work_session_id'])
            try:
                msg = self.tg('sendMessage', chat_id=self.chat, parse_mode='HTML',
                              text=self.text_for(req, '\U0001f510 <b>Richiesta amministratore Mac</b>'),
                              reply_markup=self.buttons(req, 1))
            except Exception as exc:
                self.audit('telegram_send_failed', id=rid, error_type=type(exc).__name__)
                self.write_result(rid, status='error', error='Telegram non raggiungibile; comando non eseguito',
                                  caller=req['caller'])
                continue
            self.pending[rid] = {'req': req, 'msg_id': msg['message_id'], 'stage': 1}
            self.write_result(rid, status='waiting', caller=req['caller'], sha256=req['sha256'])

    def finish(self, p, header, extra=''):
        try:
            self.tg('editMessageText', chat_id=self.chat, message_id=p['msg_id'], parse_mode='HTML',
                    text=self.text_for(p['req'], header) + extra)
        except Exception as exc:
            self.audit('edit_failed', error_type=type(exc).__name__)

    def on_callback(self, cq):
        try:
            self.tg('answerCallbackQuery', callback_query_id=cq['id'], _http_timeout=3)
        except Exception as exc:
            self.audit('callback_ack_failed', error_type=type(exc).__name__)
        if cq.get('from', {}).get('id') != self.chat or cq.get('message', {}).get('chat', {}).get('id') != self.chat:
            self.audit('callback_rejected_foreign_user', from_id=cq.get('from', {}).get('id'))
            return
        parts = (cq.get('data') or '').split(':')
        kind, rid = parts[0], parts[1] if len(parts) > 1 else ''
        p = self.pending.get(rid)
        if not p or cq.get('message', {}).get('message_id') != p['msg_id']:
            return
        req = p['req']
        if self.now() >= req['expires_at']:
            self.expire(force=rid)
            return
        if kind == 'r':
            self.pending.pop(rid)
            self.write_result(rid, status='rejected', caller=req['caller'])
            self.audit('rejected', id=rid, caller=req['caller'])
            self.finish(p, '\u274c <b>Rifiutato</b>')
            return
        if len(parts) != 3 or parts[2] != req['sha256'][:16]:
            return
        if kind == 'a' and req['sensitive']:
            p['stage'] = 2
            try:
                self.tg('editMessageText', chat_id=self.chat, message_id=p['msg_id'], parse_mode='HTML',
                        text=self.text_for(req, '\u26a0\ufe0f <b>Seconda conferma richiesta</b>'), reply_markup=self.buttons(req, 2))
            except Exception as exc:
                self.audit('second_confirmation_display_failed', id=rid, error_type=type(exc).__name__)
            return
        if (kind == 'a' and p['stage'] == 1) or (kind == 'c' and p['stage'] == 2):
            self.pending.pop(rid)
            self.audit('approved', id=rid, caller=req['caller'], stage=p['stage'])
            self.finish(p, '\u23f3 <b>Approvato, in esecuzione\u2026</b>')
            try:
                code, out = self.run(req)
                tail = html.escape(out[-1500:]) if out else '(nessun output)'
                self.finish(p, '\u2705 <b>Eseguito</b> (exit %s)' % code, '\n<b>Output:</b>\n<pre>%s</pre>' % tail)
            except ExpiredRequest as exc:
                self.write_result(rid, status='expired', error=str(exc), caller=req['caller'])
                self.finish(p, '\u231b <b>Scaduto</b> (comando non eseguito)')
            except Exception as exc:
                self.write_result(rid, status='error', error=str(exc)[:300], caller=req['caller'])
                self.finish(p, '\U0001f4a5 <b>Errore</b>: %s' % html.escape(str(exc)[:300]))

    def claim(self, req):
        dfd = os.open(str(self.claims), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(req['id'] + '.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
            with os.fdopen(fd, 'w') as f:
                json.dump({'id': req['id'], 'sha256': req['sha256'], 'claimed_at': self.now()}, f)
                f.flush()
                os.fsync(f.fileno())
            os.fsync(dfd)
        finally:
            os.close(dfd)

    def run(self, req):
        if self.now() >= req['expires_at']:
            raise ExpiredRequest('request expired; command was not executed')
        if parse_argv(req['command']) != req['argv'] or sha(req['command']) != req['sha256']:
            raise RuntimeError('command changed after display')
        self.claim(req)
        self.heartbeat(busy_until=self.now() + req['timeout'] + 30)
        started = time.monotonic()
        proc = subprocess.Popen(req['argv'], shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, cwd=self.cwd, env=dict(ENV), start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=req['timeout'])
            code = proc.returncode
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, _ = proc.communicate()
            code = 124
        text = out.decode('utf-8', errors='replace')
        truncated = len(text) > MAX_OUT
        text = text[-MAX_OUT:]
        self.write_result(req['id'], status='done', exit_code=code, output=text, truncated=truncated,
                          seconds=round(time.monotonic() - started, 1), caller=req['caller'], sha256=req['sha256'])
        self.audit('executed', id=req['id'], caller=req['caller'], sha256=req['sha256'], command=req['command'],
                   exit_code=code, output=text[-4000:])
        return code, text

    def expire(self, force=None):
        now = self.now()
        for rid in [r for r, p in self.pending.items() if r == force or p['req']['expires_at'] <= now]:
            p = self.pending.pop(rid)
            self.write_result(rid, status='expired', caller=p['req']['caller'])
            self.audit('expired', id=rid)
            self.finish(p, '\u231b <b>Scaduto</b> (comando non eseguito)')

    def startup_cleanup(self):
        dfd = os.open(str(self.results), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            names = os.listdir(dfd)
        finally:
            os.close(dfd)
        for name in names:
            if name.endswith('.json') and HEX32.fullmatch(name[:-5]):
                try:
                    with open(str(self.results / name)) as f:
                        r = json.load(f)
                    if r.get('status') == 'waiting':
                        self.write_result(name[:-5], status='expired', caller=r.get('caller', '?'), error='helper riavviato')
                except Exception:
                    pass


def load_config(root=ROOT):
    path = root / 'conf' / 'telegram.json'
    for p in (root / 'conf', path):
        st = os.lstat(str(p))
        if st.st_uid != 0 or stat.S_IMODE(st.st_mode) & 0o077:
            raise RuntimeError('unsafe Telegram configuration')
    with open(str(path)) as f:
        conf = json.load(f)
    if type(conf.get('chat_id')) is not int:
        raise RuntimeError('invalid chat id')
    return Telegram(conf['bot_token']), conf['chat_id']


def main():
    if os.geteuid() != 0 or sys.platform != 'darwin':
        raise SystemExit('root on macOS required')
    os.umask(0o077)
    tg, chat = load_config()
    helper = Helper(tg=tg, chat_id=chat)
    helper.check_layout()
    helper.startup_cleanup()
    offset = None
    for u in tg('getUpdates', timeout=0):
        offset = u['update_id'] + 1
    tg('sendMessage', chat_id=chat, text='\U0001f7e2 Helper amministrazione Mac (MCP Andrea) avviato.')
    helper.audit('started', version=VERSION, pid=os.getpid())
    while True:
        try:
            helper.heartbeat()
            helper.scan()
            params = {'timeout': 5, 'allowed_updates': ['callback_query']}
            if offset is not None:
                params['offset'] = offset
            for u in tg('getUpdates', **params):
                offset = u['update_id'] + 1
                if 'callback_query' in u:
                    helper.on_callback(u['callback_query'])
            helper.expire()
        except Exception as exc:
            helper.audit('loop_error', error_type=type(exc).__name__, error=str(exc)[:200])
            time.sleep(5)


if __name__ == '__main__':
    main()
