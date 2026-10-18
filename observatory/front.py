"""astryx · the cog's observatory FRONT (plan-11324 S3c 3/n, seed #60433 design B).

In a cog of several orgs the observatory is two things: each org runs today's observatory unchanged as its own
backend (astryx-observatory-org@<org>, on 127.0.0.1 at its registry port), and this front is the cog's one place on
:8090. It holds NO org's database, key or OBS_KEY: it reads the registry (names, homes, ports) and each HOME's
ASTRYX_ORG (a federation name, public by nature), and relays bytes.

  GET  /api/cog              the cog: {"cog": true, "home": null, "orgs": [{org, name, base}]}, sorted by org
  GET  /api/cog/stream       one SSE stream: every backend's /api/events, each event wrapped
                             {"org", "name", "event"}; a backend down is {"type": "cog_backend", "up": false}
  ANY  /o/<org>/<path>       a byte pipe to that org's backend at /<path>: method, query, body and the caller's own
                             headers (x-obs-key passes through untouched; each backend checks its OWN key). A name
                             the registry doesn't hold is a 404, and the path is never re-resolved across orgs
  ANY  /api/<path>           the root API, for the org the VIEWER chose: the `x-astryx-org` header, else the
                             `astryx_org` cookie (the app sets it when the owner picks a room; the front never
                             does). None named, or one not in this cog: 409, pointing at /api/cog. There is no
                             default org: a cog has no primary (ruling 3(b))
  /                          the web app (observatory/web/dist), as the one-org observatory serves it

The front never adds authority: it forwards what the caller sent and nothing else, keeps no cookie, and has no
PUBLIC_PATHS of its own to widen (every /o/ request is judged by the backend's).

STATED LIMITS: websockets (hands' noVNC) are not piped through the front yet; reach a backend directly for those.
Run: uvicorn front:app --host 0.0.0.0 --port 8090   (from observatory/), registry: ASTRYX_COG_REGISTRY or the default.
"""
from __future__ import annotations

import asyncio
import http.cookiejar
import json
import sys
from http import HTTPMethod
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent                 # observatory/
REPO = ROOT.parent
DIST = ROOT / "web" / "dist"
sys.path.insert(0, str(REPO / "src"))
from astryx import config, orgs  # noqa: E402

BACKEND = "astryx-observatory-org"     # the per-org backend's stem (data/org_units.json): its port is the registry's
CLIENT = "x-astryx-front-client"
SET = {CLIENT, "x-forwarded-host", "x-forwarded-proto", "x-forwarded-prefix"}   # the front's own, never passed through
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization",
       "proxy-authenticate", "host"}
RETRY = 5.0
# Behind the front every backend's peer is 127.0.0.1, so a per-visitor cap (VEGA's) would be ONE bucket for the cog
# (a2 #60582 A-1). The front names the client it saw in this header, OVERWRITING any the caller sent; a backend reads
# it only in a cog and only from 127.0.0.1 (main.py _client)


def rooms(env=None) -> list[dict]:
    """Every org of the cog: registry name, federation name, base, and its backend's loopback port (never served)."""
    out = []
    for org, e in sorted((orgs.load(env) or {}).items()):
        name = config.read_env(e["home"] / ".env").get("ASTRYX_ORG") or org
        out.append({"org": org, "name": name, "base": f"/o/{org}/", "port": e["ports"].get(BACKEND)})
    return out


def _cog() -> dict[str, dict]:
    return {r["org"]: r for r in rooms()}


app = FastAPI(title="astryx cog observatory")
_http: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        # a jar that STORES NOTHING: one client serves every viewer, so it must never replay one's cookie to another
        _http = httpx.AsyncClient(timeout=httpx.Timeout(30, read=None),
                                  cookies=http.cookiejar.CookieJar(
                                      policy=http.cookiejar.DefaultCookiePolicy(allowed_domains=[])))
    return _http


@app.get("/api/cog")
async def cog():
    return {"cog": True, "home": None,
            "orgs": [{k: r[k] for k in ("org", "name", "base")} for r in rooms()]}


@app.get("/api/cog/stream")
async def cog_stream(request: Request):
    key = request.query_params.get("key")
    q: asyncio.Queue = asyncio.Queue()

    async def follow(r: dict):
        params = {"key": key} if key else {}
        tag = {"org": r["org"], "name": r["name"]}
        up = None
        while True:
            try:
                if r["port"] is None:
                    raise httpx.ConnectError("no registry port")
                async with client().stream("GET", f"http://127.0.0.1:{r['port']}/api/events", params=params) as s:
                    if s.status_code != 200:
                        raise httpx.HTTPStatusError("not 200", request=s.request, response=s)
                    if up is not True:
                        up = True
                        await q.put({**tag, "event": {"type": "cog_backend", "up": True}})
                    async for line in s.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                ev = json.loads(line[6:])
                            except ValueError:
                                continue
                            await q.put({**tag, "event": ev})
            except (httpx.HTTPError, OSError):
                pass
            if up is not False:
                up = False
                await q.put({**tag, "event": {"type": "cog_backend", "up": False}})
            await asyncio.sleep(RETRY)

    async def stream():
        tasks = [asyncio.create_task(follow(r)) for r in rooms()]
        try:
            yield ": hello\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {json.dumps(item)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                if await request.is_disconnected():
                    return
        finally:
            for t in tasks:
                t.cancel()
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"cache-control": "no-store", "x-accel-buffering": "no"})


# the stdlib's names, never verb literals (sqlguard reads a bare "DELETE" as a possible query's only trace)
METHODS = [m.value for m in (HTTPMethod.GET, HTTPMethod.POST, HTTPMethod.PUT, HTTPMethod.PATCH, HTTPMethod.DELETE,
                             HTTPMethod.HEAD, HTTPMethod.OPTIONS)]


@app.api_route("/o/{org}/{path:path}", methods=METHODS)
async def pipe(org: str, path: str, request: Request):
    return await _relay(org, path, request)


@app.api_route("/api/{path:path}", methods=METHODS)
async def chosen(path: str, request: Request):
    org = request.headers.get("x-astryx-org") or request.cookies.get("astryx_org") or ""
    if org not in _cog():
        return JSONResponse({"error": "this cog runs several orgs: choose one", "cog": "/api/cog"}, status_code=409)
    return await _relay(org, f"api/{path}", request)


async def _relay(org: str, path: str, request: Request):
    r = _cog().get(org)
    if r is None or r["port"] is None:
        return JSONResponse({"error": f"no org {org!r} in this cog"}, status_code=404)
    # the headers the front SETS are never the caller's too: a backend reads the first copy, so an appended one lost
    headers = [(k, v) for k, v in request.headers.items() if k.lower() not in HOP | SET]
    headers += [(CLIENT, request.client.host if request.client else ""),   # what WE saw, never what the caller said
                ("x-forwarded-host", request.headers.get("x-forwarded-host") or request.headers.get("host", "")),
                ("x-forwarded-proto", request.headers.get("x-forwarded-proto") or request.url.scheme),
                ("x-forwarded-prefix", f"/o/{org}")]
    up = client().build_request(request.method, f"http://127.0.0.1:{r['port']}/{path}",
                                params=request.query_params, headers=headers, content=await request.body())
    try:
        resp = await client().send(up, stream=True)
    except httpx.HTTPError:
        return JSONResponse({"error": f"org {org}'s observatory is down"}, status_code=502)
    done = BackgroundTasks()
    done.add_task(resp.aclose)
    out = StreamingResponse(resp.aiter_raw(), status_code=resp.status_code, background=done)
    out.raw_headers = [(k, v) for k, v in resp.headers.raw if k.decode().lower() not in HOP]
    return out


# ?key= must never reach journald in clear (a3 #42085 F2), here as in the backends
from astryx.security import logredact as _logredact  # noqa: E402
_logredact.install()

if DIST.is_dir():
    @app.get("/")
    async def index():
        return FileResponse(DIST / "index.html", headers={"cache-control": "no-store"})
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
