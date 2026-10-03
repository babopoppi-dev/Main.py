"""UID5000 coordination smoke test, only while the central Mac daemon is stopped."""
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
    require_identity();d=Dispatcher();operations=[];checks=[];sessions=[]
    caller='deployment:coordination-v011'
    async def call(op,s=None,**args):
        if s:args.update(work_session_id=s['work_session_id'],work_session_token=s['work_session_token'])
        return await d.dispatch({'type':'request','id':uuid.uuid4().hex,'caller':caller,'op':op,'args':args})
    async def refused(op,s=None,**args):
        try:await call(op,s,**args)
        except PermissionError:return
        raise AssertionError(op+' was not refused')
    folder=str(WORK/('coordination_selftest_'+uuid.uuid4().hex))
    try:
        a=await call('work_session',action='open',label='selftest A',minutes=5);sessions.append(a)
        b=await call('work_session',action='open',label='selftest B',minutes=5);sessions.append(b)
        await refused('create_directory',a,path=folder)
        await refused('create_directory',path=folder)
        checks.append('writes need session and lock')
        lock=await call('work_lock',a,action='acquire',path=folder,minutes=5)
        await refused('work_lock',b,action='acquire',path=folder+'/x',minutes=5)
        checks.append('descendant conflict between sessions')
        operations.append((await call('create_directory',a,path=folder))['operation_id'])
        path=folder+'/prova.txt'
        operations.append((await call('write_file',a,path=path,content='MCP_COORD_MAC_OK\n'))['operation_id'])
        await refused('write_file',b,path=path,content='other')
        await refused('rollback_file',b,operation_id=operations[-1])
        checks.append('foreign write and rollback refused')
        r=await call('start_search',a,path=folder,pattern='MCP_COORD_MAC_OK')
        await asyncio.wait_for(d.search.jobs[r['search_id']]['task'],5)
        await refused('get_more_search_results',b,search_id=r['search_id'])
        assert (await call('get_more_search_results',a,search_id=r['search_id']))['total_results']==1
        checks.append('search private to its session')
        state=await call('who_is_working')
        assert any(l['lock_id']==lock['lock_id'] for l in state['work_locks']),state
        assert a['work_session_token'] not in json.dumps(state),'token leaked'
        checks.append('who_is_working lists lock without tokens')
        r=await call('shell_exec',command='sw_vers')
        assert r['exit_code']==0 and not r['timed_out'],r
        checks.append('baseline sw_vers without session')
    finally:
        await d.search.close()
        for operation in reversed(operations):await call('rollback_file',sessions[0],operation_id=operation)
        for s in sessions:await call('work_session',s,action='close')
        state=await call('who_is_working')
        await d.close()
    assert not state['work_sessions'] and not state['work_locks'] and not state['shell_enabled'],state
    assert not Path(folder).exists()
    checks.append('sessions closed, locks released, test files rolled back')
    print(json.dumps({'passed':True,'uid':os.getuid(),'checks':checks}))


if __name__=='__main__':asyncio.run(main())
