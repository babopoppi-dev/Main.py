"""Run as5000 before switching the gateway connection; no credential use."""
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mac_agent import Dispatcher, WORK
from mac_guard import require_identity

async def main():
    require_identity(); d=Dispatcher()
    caller='migration:selftest'
    async def call(op,args):
        return await d.dispatch({'type':'request','id':uuid.uuid4().hex,'caller':caller,'op':op,'args':args})
    try:
        for command in ('sw_vers','xcodebuild -version'):
            print(json.dumps({'starting':command,'uid':os.getuid(),'sandbox':True}),flush=True)
            result=await call('shell_exec',{'command':command})
            assert result['exit_code']==0 and not result['timed_out'],(command,result)
            print(json.dumps({'check':command,'passed':True,'output':result['output']}),flush=True)
        path=str(WORK/'migration-selftest.txt')
        op=await call('write_file',{'path':path,'content':'MCP_MIGRATION_OK'})
        assert (await call('read_file',{'path':path}))['content']=='MCP_MIGRATION_OK'
        await call('rollback_file',{'operation_id':op['operation_id']})
        assert not Path(path).exists()
        await call('enable_full_shell',{'minutes':1})
        result=await call('shell_exec',{'command':'id -u'})
        assert result['exit_code']==0 and result['output'].strip()=='5000',result
        log=await call('read_file',{'path':result['log_path']})
        assert log['content'].strip()=='5000'
        try:
            await call('write_file',{'path':result['log_path'],'content':'forbidden'})
            raise AssertionError('log write permitted')
        except PermissionError:pass
        await call('disable_full_shell',{})
        assert not (await call('who_is_working',{}))['shell_enabled']
        print(json.dumps({'check':'dispatcher_files_shell_logs_rollback','passed':True}),flush=True)
    finally:await d.close()

if __name__=='__main__':asyncio.run(main())
