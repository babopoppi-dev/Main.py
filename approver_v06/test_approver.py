import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        for name in ['queue','results','conf']:(self.base/name).mkdir()
        (self.base/'conf/bot_token').write_text('test-token')
        (self.base/'conf/chat_id').write_text('12345')
        with patch.dict(os.environ,{'CMCP_APPROVER_BASE':str(self.base),'CMCP_APPROVER_CONF':str(self.base/'conf')}):
            spec=importlib.util.spec_from_file_location('under_test',Path(__file__).with_name('approver.py'))
            self.a=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.a)
        self.clock=patch.object(self.a.time,'time',return_value=1000);self.clock.start()
        self.tg=patch.object(self.a,'tg',return_value={'message_id':42});self.tgmock=self.tg.start()
        self.runner=patch.object(self.a.subprocess,'run',return_value=types.SimpleNamespace(stdout='OK',stderr='',returncode=0))
        self.runmock=self.runner.start()
    def tearDown(self):
        self.runner.stop();self.tg.stop();self.clock.stop();self.tmp.cleanup()
    def req(self,command='true',rid='a'*32,created=900):
        return {'id':rid,'command':command,'sha256':hashlib.sha256(command.encode()).hexdigest(),
                'argv':command.split(),'reason':'test','caller':'chatgpt:test-session',
                'machine':'vps','requester':'chatgpt','session_id':'test-session',
                'created_at':created,'expires_at':created+600,
                'sensitive':bool(self.a.SENSITIVE.search(command))}
    def callback(self,req,kind='a',uid=12345):
        return {'id':'callback1','from':{'id':uid},'message':{'chat':{'id':12345}},
                'data':kind+':'+req['id']+':'+req['sha256'][:16]}
    def pending(self,req):
        self.a.pending[req['id']]={'req':req,'msg_id':42,'stage':1,'expires':req['expires_at']}
    def result(self,rid='a'*32):return json.loads((self.base/'results'/str(rid+'.json')).read_text())
    def test_late_callback_never_executes(self):
        r=self.req(created=400);self.pending(r)
        self.a.on_callback(self.callback(r))
        self.runmock.assert_not_called();self.assertEqual(self.result()['status'],'expired')
    def test_expiry_checked_again_after_telegram_edit(self):
        r=self.req();self.pending(r)
        def finish(*args,**kw):self.a.time.time.return_value=1500
        with patch.object(self.a,'finish',side_effect=finish):self.a.on_callback(self.callback(r))
        self.runmock.assert_not_called();self.assertEqual(self.result()['status'],'expired')
    def test_expired_direct_run_denied(self):
        with self.assertRaises(self.a.ExpiredRequest):self.a.run(self.req(created=399))
        self.runmock.assert_not_called()
    def test_exactly_once_persistent_claim(self):
        r=self.req();self.a.run(r)
        self.a.pending.clear()
        with self.assertRaises(FileExistsError):self.a.run(r)
        self.assertEqual(self.runmock.call_count,1)
        self.assertTrue((self.base/'execution-claims'/str(r['id']+'.json')).exists())
    def test_two_confirmations_for_sensitive_command(self):
        r=self.req('stat /home/ubuntu');self.pending(r)
        self.a.on_callback(self.callback(r));self.runmock.assert_not_called()
        self.assertEqual(self.a.pending[r['id']]['stage'],2)
        self.a.on_callback(self.callback(r,'c'));self.assertEqual(self.runmock.call_count,1)
    def test_double_confirmation_expired_between_taps(self):
        r=self.req('stat /home/ubuntu');self.pending(r)
        self.a.on_callback(self.callback(r));self.a.time.time.return_value=1501
        self.a.on_callback(self.callback(r,'c'));self.runmock.assert_not_called()
    def test_hash_or_argv_mismatch_denied(self):
        for key,value in [('sha256','0'*64),('argv',['id'])]:
            r=self.req();r[key]=value
            with self.assertRaises(RuntimeError):self.a.run(r)
        self.runmock.assert_not_called()
    def test_wrong_user_and_wrong_hash_denied(self):
        r=self.req();self.pending(r);self.a.on_callback(self.callback(r,uid=67890))
        cb=self.callback(r);cb['data']=cb['data'][:-16]+'0'*16;self.a.on_callback(cb)
        self.runmock.assert_not_called()
    def test_queue_keeps_original_expiry(self):
        r=self.req(created=500)
        (self.base/'queue'/str(r['id']+'.json')).write_text(json.dumps(r))
        self.a.scan_queue();self.assertEqual(self.a.pending[r['id']]['expires'],1100)
    def test_future_created_time_denied(self):
        r=self.req(created=1001);p=self.base/'queue'/str(r['id']+'.json');p.write_text(json.dumps(r))
        with self.assertRaises(ValueError):self.a.load_request(str(p))
        self.runmock.assert_not_called()
    def test_duplicate_request_preserves_previous_result(self):
        r=self.req();self.a.run(r);original=self.result()
        (self.base/'queue'/str(r['id']+'.json')).write_text(json.dumps(r))
        self.a.scan_queue();self.assertEqual(self.result(),original);self.assertEqual(self.runmock.call_count,1)
    def test_symlink_claim_directory_denied(self):
        target=self.base/'elsewhere';target.mkdir()
        (self.base/'execution-claims').symlink_to(target,target_is_directory=True)
        with self.assertRaises(RuntimeError):self.a.run(self.req())
        self.runmock.assert_not_called()
    def test_rejection_never_executes(self):
        r=self.req();self.pending(r);self.a.on_callback(self.callback(r,'r'))
        self.runmock.assert_not_called();self.assertEqual(self.result()['status'],'rejected')

if __name__=='__main__':unittest.main()
