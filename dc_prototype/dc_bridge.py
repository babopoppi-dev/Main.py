"""Bounded JSON-RPC subprocess transport for an isolated local MCP backend."""
import asyncio
import contextlib
import json
import os
import signal
from collections import deque


class Backend:
    def __init__(self, argv, cwd, env, max_message=2*1024*1024):
        self.argv=list(argv);self.cwd=cwd;self.env=dict(env);self.max_message=max_message
        self.proc=None;self.reader=None;self.pending={};self.next_id=0;self.failure=None
        self.notifications=deque(maxlen=20);self.write_lock=asyncio.Lock()

    async def start(self):
        if self.proc is not None:raise RuntimeError('backend already started')
        self.proc=await asyncio.create_subprocess_exec(*self.argv,cwd=self.cwd,env=self.env,
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,limit=self.max_message+1,start_new_session=True)
        self.reader=asyncio.create_task(self._read_loop())
        try:
            result=await self.rpc('initialize',{'protocolVersion':'2025-06-18',
                'capabilities':{},'clientInfo':{'name':'MCP-Andrea','version':'0.7-prototype'}},30)
            await self.send({'jsonrpc':'2.0','method':'notifications/initialized'})
            return result
        except BaseException:
            await self.close()
            raise

    async def send(self,message):
        data=(json.dumps(message,separators=(',',':'))+'\n').encode()
        if len(data)>self.max_message:raise ValueError('backend request too large')
        async with self.write_lock:
            if self.failure:raise RuntimeError(self.failure)
            if not self.proc or self.proc.returncode is not None:raise RuntimeError('backend offline')
            self.proc.stdin.write(data);await self.proc.stdin.drain()

    async def _read_loop(self):
        error=RuntimeError('backend disconnected')
        try:
            while True:
                line=await self.proc.stdout.readline()
                if not line:break
                if len(line)>self.max_message:raise ValueError('backend response too large')
                msg=json.loads(line)
                if not isinstance(msg,dict) or msg.get('jsonrpc')!='2.0':raise ValueError('invalid backend frame')
                rid=msg.get('id')
                if rid in self.pending:
                    future=self.pending[rid]
                    if not future.done():future.set_result(msg)
                elif 'method' in msg:
                    # Metadata only: do not copy arbitrary notification contents
                    # or tool arguments into transport logs.
                    self.notifications.append(str(msg['method'])[:100])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error=RuntimeError('backend protocol failure: '+type(exc).__name__)
        finally:
            self.failure=str(error)
            for future in self.pending.values():
                if not future.done():future.set_exception(error)

    async def rpc(self,method,params,timeout=30):
        self.next_id+=1;rid=self.next_id
        future=asyncio.get_running_loop().create_future();self.pending[rid]=future
        try:
            await self.send({'jsonrpc':'2.0','id':rid,'method':method,'params':params})
            msg=await asyncio.wait_for(future,timeout)
            if 'error' in msg:raise RuntimeError('backend RPC rejected request')
            if 'result' not in msg:raise RuntimeError('backend result missing')
            return msg['result']
        except asyncio.TimeoutError:
            # Never repeat a timed-out mutation automatically.
            await self.close()
            raise RuntimeError('backend request timed out; execution outcome unknown') from None
        except asyncio.CancelledError:
            # Cancellation is also an unknown execution outcome: terminate this
            # backend instance; never silently replay its request.
            await self.close()
            raise
        finally:
            self.pending.pop(rid,None)
            if not future.done():future.cancel()
            elif not future.cancelled():future.exception()

    async def tools(self):return (await self.rpc('tools/list',{}))['tools']
    async def call(self,name,args,timeout=30):
        return await self.rpc('tools/call',{'name':name,'arguments':args},timeout)

    async def close(self):
        if self.proc and self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):os.killpg(self.proc.pid,signal.SIGTERM)
            try:await asyncio.wait_for(self.proc.wait(),3)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):os.killpg(self.proc.pid,signal.SIGKILL)
                await self.proc.wait()
        if self.reader:
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):await self.reader
