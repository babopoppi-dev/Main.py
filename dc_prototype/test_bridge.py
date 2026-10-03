import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest
from dc_bridge import Backend

SERVER = r'''
import json,sys,time
for line in sys.stdin:
    request=json.loads(line)
    if 'id' not in request:continue
    method=request['method']
    if method=='stall':time.sleep(30)
    if method=='invalid':
        print('not json',flush=True);continue
    if method=='large':
        print('x'*10000,flush=True);continue
    if method=='exit':sys.exit(0)
    print(json.dumps({'jsonrpc':'2.0','method':'notifications/message',
                      'params':{'data':'private payload not to retain'}}),flush=True)
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'echo':method}}),flush=True)
'''


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.backend=Backend([sys.executable,'-u','-c',SERVER],self.tmp.name,
                             {'PATH':os.environ.get('PATH','/usr/bin:/bin')},max_message=4096)
        await self.backend.start()

    async def asyncTearDown(self):
        await self.backend.close()
        self.tmp.cleanup()

    async def test_concurrent_calls_are_correlated_and_notifications_redacted(self):
        results=await asyncio.gather(*(self.backend.rpc('call'+str(i),{}) for i in range(12)))
        self.assertEqual([r['echo'] for r in results],['call'+str(i) for i in range(12)])
        self.assertEqual(set(self.backend.notifications),{'notifications/message'})
        self.assertFalse(self.backend.pending)

    async def test_timeout_stops_backend_and_does_not_retry(self):
        with self.assertRaisesRegex(RuntimeError,'outcome unknown'):
            await self.backend.rpc('stall',{},0.03)
        self.assertIsNotNone(self.backend.proc.returncode)
        self.assertEqual(self.backend.next_id,2)

    async def test_cancel_stops_backend(self):
        task=asyncio.create_task(self.backend.rpc('stall',{}))
        await asyncio.sleep(0.03)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertIsNotNone(self.backend.proc.returncode)

    async def test_invalid_frame_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError,'protocol failure'):
            await self.backend.rpc('invalid',{})
        with self.assertRaises(RuntimeError):await self.backend.rpc('later',{})

    async def test_oversized_response_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError,'protocol failure'):
            await self.backend.rpc('large',{})

    async def test_disconnect_does_not_hang_followup(self):
        with self.assertRaisesRegex(RuntimeError,'disconnected'):
            await self.backend.rpc('exit',{})
        with self.assertRaises(RuntimeError):await self.backend.rpc('later',{},0.1)


if __name__=='__main__':unittest.main()
