"""Read-only progressive searches inside pinned FileTools roots; Python 3.9+."""
import asyncio
import contextlib
import fcntl
import json
import os
import re
import stat
import time
import uuid

from file_tools import FileToolError

SEARCH_NAMES = {'start_search', 'get_more_search_results', 'stop_search'}
MUTATIONS = {'write_file', 'edit_block', 'create_directory', 'move_file', 'rollback_file',
             'delete_path', 'copy_file', 'upload_file'}


def glob_match(text, pattern):
    """Only * and ? wildcards, without user-supplied regular expressions."""
    i = j = 0
    star = -1
    mark = 0
    while i < len(text):
        if j < len(pattern) and (pattern[j] == '?' or pattern[j] == text[i]):
            i += 1; j += 1
        elif j < len(pattern) and pattern[j] == '*':
            star = j; j += 1; mark = i
        elif star >= 0:
            j = star + 1; mark += 1; i = mark
        else:
            return False
    return all(c == '*' for c in pattern[j:])


class SearchTools:
    MAX_JOBS = 8
    MAX_ACTIVE = 2
    FILE_BYTES = 1024 * 1024
    TOTAL_BYTES = 32 * 1024 * 1024
    RESULT_BYTES = 512 * 1024
    MAX_ENTRIES = 20000
    TTL = 300

    def __init__(self, files):
        self.files = files
        self.jobs = {}

    @staticmethod
    def identity(caller):
        if not isinstance(caller, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{5,95}', caller):
            raise PermissionError('authenticated search owner required')

    @staticmethod
    def integer(value, low, high, name):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(name + ' outside permitted range')
        return value

    def purge(self):
        now = time.monotonic()
        for sid, job in list(self.jobs.items()):
            if job['finished'] is not None and now - job['finished'] >= self.TTL:
                del self.jobs[sid]

    def active(self):
        return [{'search_id': j['id'], 'owner': j['owner'], 'path': j['path'], 'mode': 'read',
                 'kind': 'search'} for j in self.jobs.values() if j['status'] == 'running']

    def guard_mutation(self, operation):
        if operation in MUTATIONS and self.active():
            raise PermissionError('search holds a read lock; stop it before modifying files')

    def owned(self, caller, sid):
        self.identity(caller); self.purge()
        if not isinstance(sid, str) or not re.fullmatch(r'[a-f0-9]{32}', sid):
            raise ValueError('invalid search_id')
        job = self.jobs.get(sid)
        if job is None or job['owner'] != caller:
            raise PermissionError('search unavailable for this authorization')
        return job

    def release(self, job):
        if job['guard'] is not None:
            os.close(job['guard']); job['guard'] = None

    async def start(self, caller, args):
        self.identity(caller); self.purge()
        allowed = {'path', 'pattern', 'search_type', 'match_mode', 'file_pattern', 'ignore_case',
                   'include_hidden', 'max_results', 'context_lines', 'depth', 'timeout_seconds'}
        if set(args) - allowed or not {'path', 'pattern'} <= set(args):
            raise ValueError('missing or unexpected search arguments')
        options = dict(search_type='content', match_mode='literal', file_pattern='*',
                       ignore_case=True, include_hidden=False, max_results=1000,
                       context_lines=1, depth=8, timeout_seconds=30)
        options.update(args)
        for key in ('pattern', 'file_pattern'):
            p = options[key]
            if not isinstance(p, str) or not p or len(p.encode('utf-8')) > 256 or any(c in p for c in '\0\r\n'):
                raise ValueError(key + ' requires 1..256 UTF-8 bytes on one line')
        if options['search_type'] not in ('files', 'content') or options['match_mode'] not in ('literal', 'glob'):
            raise ValueError('invalid search_type or match_mode')
        if options['search_type'] == 'content' and options['match_mode'] != 'literal':
            raise ValueError('content searches accept literal text only')
        for key in ('ignore_case', 'include_hidden'):
            if type(options[key]) is not bool:raise ValueError(key + ' must be boolean')
        for key, lo, hi in [('max_results',1,1000), ('context_lines',0,3), ('depth',1,16), ('timeout_seconds',1,60)]:
            self.integer(options[key], lo, hi, key)
        canonical, root, _ = self.files._path(options['path'])
        with self.files._directory(canonical):pass
        if len(self.jobs) >= self.MAX_JOBS or len(self.active()) >= self.MAX_ACTIVE:
            raise PermissionError('search capacity reached; completed searches expire after five minutes')
        guard = os.open('guard', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.files.state_fd)
        try:
            st = os.fstat(guard)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_mode & 0o077:
                raise PermissionError('unsafe file journal guard')
            fcntl.flock(guard, fcntl.LOCK_SH | fcntl.LOCK_NB)
            self.files._check_journal()
        except BaseException:
            os.close(guard); raise
        now = time.monotonic(); sid = uuid.uuid4().hex
        job = dict(id=sid, owner=caller, path=canonical, root=root, options=options, guard=guard,
                   status='running', results=[], result_bytes=0, entries=0, bytes_read=0,
                   skipped={}, limits=[], finished=None, deadline=now+options['timeout_seconds'])
        self.jobs[sid] = job
        job['task'] = asyncio.create_task(self.scan(job))
        job['task'].add_done_callback(lambda task:self.release(job))
        return self.page(job, 0, 100)

    def page(self, job, offset, length):
        self.integer(offset, 0, 1000, 'offset'); self.integer(length, 1, 100, 'length')
        rows = job['results'][offset:offset+length]
        return {'search_id':job['id'], 'status':job['status'], 'path':job['path'], 'results':rows,
                'offset':offset, 'next_offset':offset+len(rows), 'total_results':len(job['results']),
                'has_more':offset+len(rows)<len(job['results']), 'running':job['status']=='running',
                'truncated':bool(job['limits']), 'limits_reached':list(job['limits']),
                'entries_scanned':job['entries'], 'bytes_read':job['bytes_read'],
                'skipped':dict(job['skipped']), 'retention_seconds_after_finish':self.TTL,
                'identity_scope':'OAuth authorization; chats may share an authorization',
                **({'error':job['error']} if 'error' in job else {})}

    def skip(self, job, reason):
        job['skipped'][reason] = job['skipped'].get(reason, 0) + 1

    def limited(self, job, reason):
        if reason not in job['limits']:job['limits'].append(reason)

    def budget(self, job):
        if time.monotonic() >= job['deadline']:self.limited(job, 'timeout')
        return not job['limits']

    def add(self, job, row):
        size = len(json.dumps(row, ensure_ascii=True).encode('utf-8'))
        if job['result_bytes'] + size > self.RESULT_BYTES:
            self.limited(job, 'result_bytes'); return
        job['results'].append(row); job['result_bytes'] += size
        if len(job['results']) >= job['options']['max_results']:self.limited(job, 'max_results')

    def folded(self, job, text):
        return text.casefold() if job['options']['ignore_case'] else text

    async def read_text(self, job, directory_fd, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                self.skip(job, 'not_regular_or_hardlink'); return None
            if st.st_size > self.FILE_BYTES:
                self.skip(job, 'large_file'); return None
            chunks=[]; count=0
            while self.budget(job):
                await asyncio.sleep(0)
                remaining = self.TOTAL_BYTES-job['bytes_read']
                if remaining <= 0:self.limited(job,'total_bytes'); return None
                chunk=os.read(fd,min(65536,self.FILE_BYTES+1-count,remaining))
                if not chunk:break
                count+=len(chunk);job['bytes_read']+=len(chunk);chunks.append(chunk)
                if count>self.FILE_BYTES:
                    self.skip(job,'large_file');return None
            if not self.budget(job):return None
            after=os.fstat(fd)
            if (st.st_size,st.st_mtime_ns,st.st_ctime_ns,st.st_nlink)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns,after.st_nlink):
                self.skip(job,'changed_file');return None
            data=b''.join(chunks)
            try:return self.files._text(data)
            except FileToolError:self.skip(job,'binary_file');return None
        finally:os.close(fd)

    async def visit(self, job, path, level):
        options=job['options']
        with self.files._directory(path) as fd:
            with os.scandir(fd) as entries:
                for item in entries:
                    await asyncio.sleep(0)
                    if not self.budget(job):return
                    job['entries']+=1
                    if job['entries']>self.MAX_ENTRIES:self.limited(job,'entries');return
                    if not options['include_hidden'] and item.name.startswith('.'):
                        self.skip(job,'hidden');continue
                    child=path.rstrip('/')+'/'+item.name
                    try:
                        self.files._path(child)
                        st=os.stat(item.name,dir_fd=fd,follow_symlinks=False)
                        if stat.S_ISLNK(st.st_mode):self.skip(job,'symlink');continue
                        if st.st_dev!=os.fstat(self.files.root_fds[job['root']]).st_dev:
                            self.skip(job,'different_device');continue
                        if stat.S_ISDIR(st.st_mode):
                            if level>=options['depth']:
                                job['depth_skipped']=True
                            else:await self.visit(job,child,level+1)
                            continue
                        if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:
                            self.skip(job,'not_regular_or_hardlink');continue
                        name=self.folded(job,item.name)
                        if not glob_match(name,self.folded(job,options['file_pattern'])):continue
                        pattern=self.folded(job,options['pattern'])
                        if options['search_type']=='files':
                            matches=glob_match(name,pattern) if options['match_mode']=='glob' else pattern in name
                            if matches:self.add(job,{'path':child,'type':'file'})
                        else:
                            text=await self.read_text(job,fd,item.name)
                            if text is None:continue
                            lines=text.splitlines()
                            for index,line in enumerate(lines):
                                if index%64==0:
                                    await asyncio.sleep(0)
                                    if not self.budget(job):return
                                if pattern in self.folded(job,line):
                                    lo=max(0,index-options['context_lines']);hi=min(len(lines),index+options['context_lines']+1)
                                    snippet='\n'.join(lines[lo:hi])
                                    encoded=snippet.encode('utf-8')
                                    self.add(job,{'path':child,'line':index+1,'context_start_line':lo+1,
                                        'text':encoded[:2048].decode('utf-8','ignore'),'text_truncated':len(encoded)>2048})
                                    if not self.budget(job):return
                    except FileToolError:self.skip(job,'protected_or_changed_path')
                    except OSError:self.skip(job,'unreadable_or_changed')

    async def scan(self, job):
        try:
            await self.visit(job,job['path'],1)
            if job.get('depth_skipped'):self.limited(job,'depth')
            job['status']='limited' if job['limits'] else 'completed'
        except asyncio.CancelledError:
            job['status']='cancelled'
        except Exception as exc:
            job['status']='error';job['error']=type(exc).__name__
        finally:
            job['finished']=time.monotonic();self.release(job)

    async def stop(self, caller, sid):
        job=self.owned(caller,sid)
        if job['status']=='running':
            job['status']='cancelled';job['task'].cancel()
            with contextlib.suppress(asyncio.CancelledError):await job['task']
            job['finished']=time.monotonic();self.release(job)
        return self.page(job,0,100)

    async def close(self):
        for job in list(self.jobs.values()):
            if job['status']=='running':await self.stop(job['owner'],job['id'])
        self.jobs.clear()

    async def dispatch(self, op, args, caller):
        if not isinstance(args,dict):raise ValueError('arguments must be an object')
        if op=='start_search':return await self.start(caller,args)
        if op=='get_more_search_results':
            if set(args)-{'search_id','offset','length'}:raise ValueError('unexpected search arguments')
            return self.page(self.owned(caller,args.get('search_id')),args.get('offset',0),args.get('length',100))
        if op=='stop_search' and set(args)=={'search_id'}:return await self.stop(caller,args['search_id'])
        raise ValueError('invalid search operation')
