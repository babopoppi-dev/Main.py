"""Progressive read-only search tools, version 0.10.1."""
MACHINE={'type':'string','enum':['vps','mac_noleggio','mac_mio']}
def tool(name,description,properties,required):
    return {'name':name,'description':description,'inputSchema':{'type':'object',
        'additionalProperties':False,'properties':{'machine':MACHINE,**properties},
        'required':['machine']+required}}

SEARCH_TOOLS=[
    tool('start_search','Start a bounded background search inside allowed roots. Files: literal substring or * ? glob; content: literal UTF-8 text only. No symlinks or hardlinks. A read lock blocks MCP writes/shells until finished or stopped. Poll get_more_search_results. Inspect truncated/skipped for completeness. Requires search_version in machine metadata.',{
        'path':{'type':'string','description':'Absolute authorized directory'},
        'pattern':{'type':'string','minLength':1,'maxLength':256},
        'search_type':{'type':'string','enum':['files','content'],'default':'content'},
        'match_mode':{'type':'string','enum':['literal','glob'],'default':'literal'},
        'file_pattern':{'type':'string','default':'*','description':'Filename filter with * and ? wildcards'},
        'ignore_case':{'type':'boolean','default':True},
        'include_hidden':{'type':'boolean','default':False},
        'context_lines':{'type':'integer','minimum':0,'maximum':3,'default':1},
        'max_results':{'type':'integer','minimum':1,'maximum':1000,'default':1000},
        'depth':{'type':'integer','minimum':1,'maximum':16,'default':8},
        'timeout_seconds':{'type':'integer','minimum':1,'maximum':60,'default':30}},['path','pattern']),
    tool('get_more_search_results','Read a stable page of search results. Poll while running=true even if has_more=false. Results are private to the initiating OAuth authorization and expire five minutes after completion.',{
        'search_id':{'type':'string','pattern':'^[a-f0-9]{32}$'},
        'offset':{'type':'integer','minimum':0,'maximum':1000,'default':0},
        'length':{'type':'integer','minimum':1,'maximum':100,'default':100}},['search_id']),
    tool('stop_search','Cancel a search, release its read lock, and keep collected results for five minutes.',{
        'search_id':{'type':'string','pattern':'^[a-f0-9]{32}$'}},['search_id'])]
SEARCH_NAMES={t['name'] for t in SEARCH_TOOLS}
