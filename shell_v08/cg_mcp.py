import hmac,json,re
from pathlib import Path
from aiohttp import web
from cg_tools import TOOLS,NAMES

LONG_TIMEOUTS={"xcode_build":1300,"xcode_test":300,"xcode_list":150}

def bearer(req):
    v=req.headers.get("Authorization","");return v[7:] if v.startswith("Bearer ") else ""

def local_static(req,cfg,raw):
    if req.remote not in ("127.0.0.1","::1"):return False
    if req.headers.get("X-Forwarded-For") or req.headers.get("Forwarded"):return False
    exp=Path(cfg["mcp_token_file"]).read_text().strip()
    return hmac.compare_digest(raw,exp)

def caller_of(app,principal):
    if not principal:return "local:static"
    try:
        c=app.oauth.db.client(principal["client_id"]);name=c["client_name"] if c else "oauth"
    except Exception:name="oauth"
    slug=re.sub(r"[^a-z0-9]+","-",str(name).lower()).strip("-")[:20] or "oauth"
    family = str(principal['family_id'])
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', family):
        raise PermissionError('invalid authorization identity')
    return f"{slug}:{family}"


APPROVER="/var/lib/central-mcp-approver"
def admin_request(args,app,principal):
    import hashlib,uuid,os,time
    if not principal: raise PermissionError("OAuth required for admin requests")
    cmd=args.get("command");reason=str(args.get("reason",""))[:500]
    if not isinstance(cmd,str) or not cmd.strip() or len(cmd)>3000:raise ValueError("command required (max 3000 chars)")
    client=app.oauth.db.client(principal["client_id"]) or {}
    client_name=str(client.get("client_name","oauth"))
    requester="claude" if "claude" in client_name.lower() else "chatgpt"
    session_id=str(principal.get("family_id",""))
    if not session_id: raise ValueError("OAuth session id missing")
    created=int(time.time());rid=uuid.uuid4().hex
    d={"id":rid,"command":cmd,"sha256":hashlib.sha256(cmd.encode()).hexdigest(),
       "reason":reason,"caller":requester+":"+session_id[:16],"machine":"vps",
       "requester":requester,"session_id":session_id,
       "oauth_client_id":str(principal["client_id"]),"oauth_client_name":client_name,
       "created_at":created,"expires_at":created+600}
    tmp=f"{APPROVER}/queue/.{rid}.tmp";open(tmp,"w").write(json.dumps(d,ensure_ascii=False));os.replace(tmp,f"{APPROVER}/queue/{rid}.json")
    return {"request_id":rid,"status":"sent to Andrea on Telegram for approval; poll admin_result (expires in 10 min)"}
def admin_result(args):
    rid=str(args.get("request_id",""))
    if not re.fullmatch(r"[0-9a-f]{32}",rid):raise ValueError("invalid request_id")
    p=Path(f"{APPROVER}/results/{rid}.json")
    return json.loads(p.read_text()) if p.exists() else {"id":rid,"status":"queued"}

async def handle(app,req):
    raw=bearer(req);principal=app.oauth.bearer(raw)
    if not principal and not local_static(req,app.cfg,raw):
        hdr={'WWW-Authenticate':f'Bearer resource_metadata="{app.oauth.issuer}/.well-known/oauth-protected-resource/mcp"'}
        return web.json_response({"error":"unauthorized"},status=401,headers=hdr)
    if req.method!="POST":raise web.HTTPMethodNotAllowed(req.method,["POST"])
    try:b=await req.json()
    except Exception:return web.json_response({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}})
    mid=b.get("id");method=b.get("method")
    if method=="initialize":
        return web.json_response({"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"central-mcp-gateway","version":"0.3.0"}}})
    if method=="ping":return web.json_response({"jsonrpc":"2.0","id":mid,"result":{}})
    if method in ("notifications/initialized","notifications/cancelled"):return web.Response(status=202)
    if method=="tools/list":return web.json_response({"jsonrpc":"2.0","id":mid,"result":{"tools":TOOLS}})
    if method!="tools/call":return web.json_response({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":"Method not found"}})
    p=b.get("params",{});name=p.get("name");args=p.get("arguments",{})
    if name not in NAMES:return web.json_response({"jsonrpc":"2.0","id":mid,"error":{"code":-32602,"message":"Unknown tool"}})
    try:
        if name=="list_machines":res={"machines":app.agents.listing()}
        elif name=="admin_request":res=admin_request(args,app,principal)
        elif name=="admin_result":res=admin_result(args)
        else:
            m=args.get("machine");opargs={k:v for k,v in args.items() if k!="machine"}
            t=LONG_TIMEOUTS.get(name,int(opargs.get("timeout",120))+10)
            res=await app.agents.call(m,name,opargs,t,caller_of(app,principal))
        return web.json_response({"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":json.dumps(res,ensure_ascii=False)}],"isError":False}})
    except Exception as e:
        return web.json_response({"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":str(e)}],"isError":True}})

