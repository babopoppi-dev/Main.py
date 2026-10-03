"""Mac admin via Telegram: agent client, root helper (simulated) and dispatcher."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from admin_schema import ADMIN_TOOLS, ADMIN_NAMES, install_schema, parse_command
from mac_admin_client import AdminClient
import mac_admin_helper as H

CHAT = 4242


class FakeTelegram:
    def __init__(self):
        self.calls = []
        self.next_id = 100
        self.fail = set()

    def __call__(self, method, **params):
        params.pop('_http_timeout', None)
        self.calls.append((method, params))
        if method in self.fail:
            raise RuntimeError('telegram %s failed' % method)
        if method == 'sendMessage':
            self.next_id += 1
            return {'message_id': self.next_id}
        return True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'admin'
        self.root.mkdir(mode=0o755)
        os.chmod(self.root, 0o755)
        for name, mode in (('outbox', 0o700), ('results', 0o750), ('claims', 0o700)):
            (self.root / name).mkdir(mode=mode)
            os.chmod(self.root / name, mode)
        self.clock = [1_000_000.0]
        now = lambda: self.clock[0]
        uid, gid = os.getuid(), os.getgid()
        self.tg = FakeTelegram()
        self.helper = H.Helper(self.root, tg=self.tg, chat_id=CHAT, agent_uid=uid, agent_gid=gid,
                               owner_uid=uid, now=now, cwd=self.tmp.name)
        self.client = AdminClient(self.root, helper_uid=uid, now=now)
        self.helper.check_layout()
        self.helper.heartbeat()

    def tearDown(self):
        self.tmp.cleanup()

    def ask(self, command='/bin/echo ciao', caller='claude:abcdef12', reason='prova', **extra):
        args = {'command': command, 'reason': reason, **extra}
        return self.client.request(caller, 'work:' + 'a' * 32, args)

    def tap(self, kind, rid, user=CHAT, msg=None, short=None):
        p = self.helper.pending.get(rid)
        data = kind + ':' + rid + ('' if kind == 'r' else ':' + (short or p['req']['sha256'][:16]))
        self.helper.on_callback({'id': 'x', 'data': data, 'from': {'id': user},
                                 'message': {'chat': {'id': user}, 'message_id': msg or (p['msg_id'] if p else 0)}})

    def result(self, rid, caller='claude:abcdef12'):
        return self.client.result(caller, {'request_id': rid})


class Validation(unittest.TestCase):
    def test_parse_command(self):
        self.assertEqual(parse_command('/bin/launchctl print system'), ['/bin/launchctl', 'print', 'system'])
        for bad in ('ls -la', '/bin/ls; rm', '/bin/echo $(id)', '/bin/ls | cat', '/bin/../bin/sh', '', 'x' * 3001, '/bin/a"b'):
            with self.assertRaises(ValueError):
                parse_command(bad)

    def test_catalog_additive(self):
        tools = install_schema(install_schema([{'name': 'list_machines', 'inputSchema': {}}]))
        self.assertEqual([t['name'] for t in tools].count('mac_admin_request'), 1)
        self.assertEqual({t['name'] for t in ADMIN_TOOLS}, ADMIN_NAMES)
        req = [t for t in tools if t['name'] == 'mac_admin_request'][0]['inputSchema']
        self.assertEqual(req['properties']['machine']['enum'], ['mac_mio'])
        self.assertIn('work_session_token', req['required'])

    def test_sensitive_patterns(self):
        for cmd in ('/bin/rm -f /tmp/x', '/usr/bin/dscl . -list /Users', '/bin/launchctl bootout system/x',
                    '/usr/bin/python3 /tmp/x.py', '/bin/ls /Users/babo/Bitcoin', '/usr/bin/git pull'):
            self.assertTrue(H.SENSITIVE.search(cmd), cmd)
        for cmd in ('/usr/bin/sw_vers', '/bin/launchd_x', '/usr/bin/uptime', '/bin/df -h'):
            self.assertFalse(H.SENSITIVE.search(cmd), cmd)


class Flow(Base):
    def test_approve_runs_exact_command_once(self):
        r = self.ask()
        self.assertEqual(self.result(r['request_id'])['status'], 'queued')
        self.helper.scan()
        self.assertEqual(self.result(r['request_id'])['status'], 'waiting')
        method, params = self.tg.calls[-1]
        self.assertEqual(method, 'sendMessage')
        self.assertIn('/bin/echo ciao', params['text'])
        self.tap('a', r['request_id'])
        res = self.result(r['request_id'])
        self.assertEqual((res['status'], res['exit_code'], res['output']), ('done', 0, 'ciao\n'))
        self.assertTrue((self.root / 'claims' / (r['request_id'] + '.json')).exists())
        self.tap('a', r['request_id'], msg=101, short=res['sha256'][:16])  # stale repeated tap
        executed = [l for l in (self.root / 'audit.jsonl').read_text().splitlines() if '"executed"' in l]
        self.assertEqual(len(executed), 1)

    def test_foreign_user_wrong_hash_and_wrong_message_ignored(self):
        r = self.ask()
        self.helper.scan()
        rid = r['request_id']
        self.tap('a', rid, user=999)
        self.tap('a', rid, short='0' * 16)
        self.tap('a', rid, msg=1)
        self.assertEqual(self.result(rid)['status'], 'waiting')

    def test_sensitive_needs_second_confirmation(self):
        target = Path(self.tmp.name) / 'victim'
        target.write_text('x')
        r = self.ask('/bin/rm ' + str(target))
        self.helper.scan()
        rid = r['request_id']
        self.tap('a', rid)
        self.tap('a', rid)
        self.assertTrue(target.exists())
        self.tap('c', rid)
        self.assertFalse(target.exists())
        self.assertEqual(self.result(rid)['status'], 'done')

    def test_reject_and_expiry(self):
        a, b = self.ask(), self.ask()
        self.helper.scan()
        self.tap('r', a['request_id'])
        self.assertEqual(self.result(a['request_id'])['status'], 'rejected')
        self.clock[0] += 601
        self.helper.expire()
        self.assertEqual(self.result(b['request_id'])['status'], 'expired')

    def test_late_tap_after_expiry_does_not_run(self):
        target = Path(self.tmp.name) / 'late'
        r = self.ask('/usr/bin/touch ' + str(target))
        self.helper.scan()
        self.clock[0] += 600
        self.tap('a', r['request_id'])
        self.assertFalse(target.exists())
        self.assertEqual(self.result(r['request_id'])['status'], 'expired')

    def test_timeout_kills_command(self):
        r = self.ask('/bin/sleep 5', timeout=1)
        self.helper.scan()
        self.tap('a', r['request_id'])
        self.assertEqual(self.result(r['request_id'])['exit_code'], 124)

    def test_other_caller_cannot_read_result(self):
        r = self.ask()
        self.helper.scan()
        with self.assertRaises(PermissionError):
            self.result(r['request_id'], caller='chatgpt:zzzzzzzz')

    def test_pending_limit_and_session_required(self):
        for _ in range(3):
            self.ask()
        with self.assertRaises(PermissionError):
            self.ask()
        with self.assertRaises(PermissionError):
            self.client.request('claude:abcdef12', 'claude:abcdef12', {'command': '/bin/echo', 'reason': 'x'})

    def test_helper_down_refuses_queue(self):
        self.clock[0] += 121
        with self.assertRaises(RuntimeError):
            self.ask()
        self.helper.heartbeat(busy_until=self.clock[0] + 300)
        self.clock[0] += 200
        self.ask()

    def test_telegram_failure_reports_error(self):
        self.tg.fail.add('sendMessage')
        r = self.ask()
        self.helper.scan()
        self.assertEqual(self.result(r['request_id'])['status'], 'error')


class Hostile(Base):
    """The outbox is written by the agent account: treat every file as hostile."""
    def put(self, name, data):
        path = self.root / 'outbox' / name
        path.write_text(json.dumps(data) if not isinstance(data, str) else data)
        return path

    def good(self, **change):
        r = self.ask()
        path = self.root / 'outbox' / (r['request_id'] + '.json')
        data = json.loads(path.read_text())
        data.update(change)
        path.write_text(json.dumps(data))
        return r['request_id']

    def test_tampered_fields_rejected(self):
        cases = [dict(command='/bin/echo altro'), dict(argv=['/bin/sh', '-c', 'id']), dict(timeout=10000),
                 dict(expires_at=2_000_000), dict(created_at=2_000_000), dict(caller='bad caller'),
                 dict(extra=1)]
        for change in cases:
            rid = self.good(**change)
            self.helper.scan()
            self.assertEqual(self.result(rid, caller=change.get('caller', 'claude:abcdef12'))['status'], 'error', change)
            self.assertNotIn(rid, self.helper.pending)
        self.assertFalse([c for c in self.tg.calls if c[0] == 'sendMessage'])

    def test_symlink_and_junk_removed(self):
        secret = Path(self.tmp.name) / 'secret.json'
        secret.write_text('{}')
        rid = uuid.uuid4().hex
        os.symlink(str(secret), str(self.root / 'outbox' / (rid + '.json')))
        self.put('junk.txt', 'x')
        self.helper.scan()
        self.assertEqual(os.listdir(self.root / 'outbox'), [])
        self.assertTrue(secret.exists())
        with self.assertRaises(PermissionError):  # error result recorded, caller unknown
            self.result(rid)
        self.assertEqual(json.loads((self.root / 'results' / (rid + '.json')).read_text())['status'], 'error')

    def test_replay_of_executed_id_rejected(self):
        r = self.ask()
        raw = (self.root / 'outbox' / (r['request_id'] + '.json')).read_text()
        self.helper.scan()
        self.tap('a', r['request_id'])
        self.put(r['request_id'] + '.json', raw)
        self.helper.scan()
        self.assertEqual(self.result(r['request_id'])['status'], 'done')
        self.assertNotIn(r['request_id'], self.helper.pending)

    def test_flood_is_bounded(self):
        for i in range(25):
            self.put(uuid.uuid4().hex + '.json', '{bad')
        self.helper.scan()
        self.assertEqual(len(os.listdir(self.root / 'outbox')), 15)
        old = H.KEEP_RESULTS
        H.KEEP_RESULTS = 4
        try:
            self.helper.prune()
        finally:
            H.KEEP_RESULTS = old
        names = [n for n in os.listdir(self.root / 'results') if n != 'helper_status.json']
        self.assertEqual(len(names), 4)

    def test_prune_keeps_pending(self):
        r = self.ask()
        self.helper.scan()
        self.clock[0] += H.RESULT_TTL + 10
        os.utime(self.root / 'results' / (r['request_id'] + '.json'), (0, 0))
        self.helper.prune()
        self.assertTrue((self.root / 'results' / (r['request_id'] + '.json')).exists())

    def test_layout_check_rejects_open_outbox(self):
        os.chmod(self.root / 'outbox', 0o777)
        with self.assertRaises(RuntimeError):
            self.helper.check_layout()


class Dispatch(unittest.IsolatedAsyncioTestCase):
    """mac_admin_request needs a work session and is audited with its id (point B too)."""
    async def asyncSetUp(self):
        from mac_agent import Dispatcher
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        (base / 'work').mkdir(mode=0o700)
        (base / 'state').mkdir(mode=0o700)
        self.d = Dispatcher(base / 'work', base / 'state')
        root = base / 'admin'
        root.mkdir(mode=0o755)
        for name, mode in (('outbox', 0o700), ('results', 0o750), ('claims', 0o700)):
            (root / name).mkdir(mode=mode)
            os.chmod(root / name, mode)
        self.helper = H.Helper(root, tg=FakeTelegram(), chat_id=CHAT, agent_uid=os.getuid(), agent_gid=os.getgid(),
                               owner_uid=os.getuid(), cwd=self.tmp.name)
        self.helper.heartbeat()
        self.d.admin = AdminClient(root, helper_uid=os.getuid())

    async def asyncTearDown(self):
        await self.d.close()
        self.tmp.cleanup()

    async def call(self, op, args, s=None, caller='claude:abcdef12'):
        args = dict(args)
        if s:
            args.update(work_session_id=s['work_session_id'], work_session_token=s['work_session_token'])
        return await self.d.dispatch({'type': 'request', 'id': uuid.uuid4().hex, 'caller': caller, 'op': op, 'args': args})

    async def test_admin_request_requires_session_and_is_audited(self):
        with self.assertRaises(PermissionError):
            await self.call('mac_admin_request', {'command': '/bin/echo x', 'reason': 'r'})
        s = await self.call('work_session', {'action': 'open', 'label': 'admin', 'minutes': 5})
        r = await self.call('mac_admin_request', {'command': '/bin/echo x', 'reason': 'r'}, s)
        self.assertEqual((await self.call('mac_admin_result', {'request_id': r['request_id']}))['status'], 'queued')
        state = await self.call('who_is_working', {})
        ops = {(x['operation'], x['work_session_id']) for x in state['recent_work_operations']}
        sid = s['work_session_id']
        self.assertIn(('mac_admin_request', sid), ops)
        self.assertIn(('work_session', sid), ops)  # B: open is audited with its new id
        await self.call('work_session', {'action': 'close'}, s)
        state = await self.call('who_is_working', {})
        self.assertEqual(sum(1 for x in state['recent_work_operations'] if x == {**x, 'operation': 'work_session', 'work_session_id': sid}), 2)


if __name__ == '__main__':
    unittest.main()
