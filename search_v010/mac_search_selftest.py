"""UID5000 search smoke test, only while the central Mac daemon is stopped."""
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid
sys.path.insert(0,'/Library/MCPAndreaMacMioV09/code')
from mac_agent import Dispatcher, WORK
from mac_guard import require_identity


async def main():
    require_identity();d=Dispatcher();operations=[];checks=[]
    caller='deployment:search-v010'
    async def call(op,**args):
        return await d.dispatch({'type':'request','id':uuid.uuid4().hex,'caller':caller,'op':op,'args':args})
    folder=str(WORK/('search_selftest_'+uuid.uuid4().hex))
    try:
        operations.append((await call('create_directory',path=folder))['operation_id'])
        path=folder+'/prova.txt'
        operations.append((await call('write_file',path=path,content='MCP_SEARCH_MAC_OK\n'))['operation_id'])
        for args in [dict(pattern='MCP_SEARCH_MAC_OK'),dict(pattern='*.txt',search_type='files',match_mode='glob')]:
            r=await call('start_search',path=folder,**args)
            await asyncio.wait_for(d.search.jobs[r['search_id']]['task'],5)
            r=await call('get_more_search_results',search_id=r['search_id'])
            assert r['status']=='completed' and r['total_results']==1 and r['results'][0]['path']==path,r
            checks.append('content' if args.get('search_type') is None else 'filename')
        r=await call('start_search',path=folder,pattern='test')
        r=await call('stop_search',search_id=r['search_id'])
        assert r['status']=='cancelled';checks.append('cancel and read-lock release')
        r=await call('shell_exec',command='sw_vers')
        assert r['exit_code']==0 and not r['timed_out'],r
        checks.append('sandboxed sw_vers')
        state=await call('who_is_working')
        assert not state['shell_enabled'] and not state['active_locks'],state
    finally:
        await d.search.close()
        for operation in reversed(operations):await call('rollback_file',operation_id=operation)
        await d.close()
    assert not Path(folder).exists()
    checks.append('all test files rolled back')
    print(json.dumps({'passed':True,'uid':os.getuid(),'checks':checks}))


if __name__=='__main__':asyncio.run(main())
