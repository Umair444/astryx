"""astryx · the cog's observatory FRONT (plan-11324 S3c 3/n, seed #60433 design B).

In a cog of several orgs the observatory is two things: each org runs today's observatory unchanged as its own
backend (astryx-observatory-org@<org>, on 127.0.0.1 at its registry port), and this front is the cog's one place on
:8090. It holds NO org's database, key or OBS_KEY: it reads the registry (names, homes, ports) and each HOME's
ASTRYX_ORG (a federation name, public by nature), and relays bytes.

  GET  /api/cog              the cog: {"cog": true, "home": null, "orgs": [{org, name, base}]}, sorted by org
  GET  /api/cog/stream       one SSE stream: every backend's /api/events, each event wrapped
                             {"org", "name", "event"}; a backend down is {"type": "cog_backend", "up": false}
  ANY  /o/<org>/<path>       a byte pipe to that org's backend at /<path>: method, query, body and the caller's
                             allowed headers (src/astryx/security/relay.py; x-obs-key passes, and each backend checks
                             its OWN key), plus the signed identity of a signed-in viewer. A name the registry doesn't
                             hold is a 404, and the path is never re-resolved across orgs
  POST /auth/login           {email, password} → 200 + the session cookie | 401 (one body) | 429 | 403 foreign Origin
  POST /auth/logout          the session revoked (a server row), the cookie cleared
  GET  /auth/me              {user, orgs: [{org, name, role}]}, each role as its org answers | 401 (plan-11859 U1+U2)
  ANY  /api/<path>           the root API, for the org the VIEWER chose: the `x-astryx-org` header, else the
                             `astryx_org` cookie (the app sets it when the owner picks a room; the front never
                             does). None named, or one not in this cog: 409, pointing at /api/cog. There is no
                             default org: a cog has no primary (ruling 3(b))
  /                          the web app (observatory/web/dist), as the one-org observatory serves it

The front adds ONE fact: who the viewer is (plan-11859 U1+U2). It is the authority for that, so it signs it, per
request and per org, and never says what the viewer may do: each backend decides that from its own members table.
Its one cookie is the session's (httpOnly, SameSite=Strict, Secure on an https origin); no backend can set it or
read it (relay.py, both directions). It has no PUBLIC_PATHS of its own to widen (every /o/ request is judged by the
backend's).

STATED LIMITS: websockets (hands' noVNC) are not piped through the front yet; reach a backend directly for those.
Run: uvicorn front:app --host 0.0.0.0 --port 8090   (from observatory/), registry: ASTRYX_COG_REGISTRY or the default.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import http.cookiejar
import json
import sys
import time
from collections import defaultdict, deque
from http import HTTPMethod
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent                 # observatory/
REPO = ROOT.parent
DIST = ROOT / "web" / "dist"
sys.path.insert(0, str(REPO / "src"))
from astryx import cogauth, config, orgs  # noqa: E402
from astryx.security import identity, relay  # noqa: E402   the ONE relay header policy (plan-11859 D3)

BACKEND = "astryx-observatory-org"     # the per-org backend's stem (data/org_units.json): its port is the registry's
CLIENT = "x-astryx-front-client"
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


# ---------------------------------------------------------------- sign-in (plan-11859 U1+U2, D1 D2 D7)
# The front is the authority for WHO you are: it checks the password, keeps the session (a server row in the COG's
# store, src/astryx/cogauth.py), and on every relayed request mints a 60 s Ed25519 token naming the account and the
# org it routed to (src/astryx/security/identity.py). It never decides what you may do: each org's backend reads
# its own `members` row for that (a2 I1). With no `cog` block in the registry there is no sign-in: /auth/* is a
# 404, which the app reads as "unavailable" (observatory/web/src/auth.ts), and the owner key works as before.
SESSION = "astryx_session"
FAILED = b'{"error":"sign-in failed"}'        # ONE body for every failed sign-in, whatever failed (F8, I9)
WINDOW, PER_CLIENT, PER_ACCOUNT = 300.0, 20, 5    # failed sign-ins in WINDOW s before a 429, by client AND account
_fails: dict[str, deque] = defaultdict(deque)
# THE COST OF A SIGN-IN, bounded (plan-11859 U1U2-F, seed #62578, a2's global form). One argon2id check is ~0.5 s of a
# core and 64 MiB. So at most CHECKS run at once, on an executor of their own (never asyncio's default pool, which
# every other to_thread shares), and at most INFLIGHT sign-ins wait for one: past that, a 503 at once, before any hash
CHECKS, INFLIGHT = 2, 8
_checks = concurrent.futures.ThreadPoolExecutor(max_workers=CHECKS, thread_name_prefix="astryx-pwcheck")
_inflight = 0


async def _check(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(_checks, fn, *args)


class _Auth:
    """The cog's sign-in state, read once: its id, signing key, configured public origins and store connection."""
    def __init__(self, c: dict):
        env = config.read_env(c["home"] / ".env")
        self.cog_id, self.home = c["id"], c["home"]
        self.key = identity.load_signer(c["home"])
        # the ORIGINS the cog is signed in on, CONFIGURED (a4 X1): never read from a forwarded header
        self.origins = {o.strip().rstrip("/") for o in env.get("ASTRYX_COG_ORIGINS", "").split(",") if o.strip()}
        try:     # the cog store's DSN, through the ONE resolver (file only; it refuses an org's database)
            self.dsn = config.dsn(c["home"] / ".env", env_first=False)
        except (LookupError, config.ForeignDSN):
            self.dsn = ""          # no store: every sign-in is a 503, and the owner key still works
        self.conn = None
        self.lock = asyncio.Lock()
        cogauth.dummy()          # made NOW, so the first unknown email doesn't pay for making it (its latency, F8)

    async def db(self, fn, *args):
        """fn(conn, *args) on the store's one connection, reconnecting once if it dropped."""
        import psycopg
        async with self.lock:
            for attempt in (0, 1):
                try:
                    if self.conn is None or self.conn.closed:
                        self.conn = await psycopg.AsyncConnection.connect(self.dsn, autocommit=True)
                    return await fn(self.conn, *args)
                except psycopg.OperationalError:
                    self.conn = None
                    if attempt:
                        raise


_auth_state: list = []


def auth() -> _Auth | None:
    """The sign-in state, read once. A cog block whose key can't be read means NO sign-in (named on stderr), never a
    front that fails every request: the owner key and every public face keep working."""
    if not _auth_state:
        c = orgs.cog()
        try:
            _auth_state.append(_Auth(c) if c else None)
        except (OSError, ValueError) as e:
            print(f"front: the cog's sign-in is OFF: its key in {c['home']} is unreadable ({type(e).__name__})",
                  file=sys.stderr)
            _auth_state.append(None)
    return _auth_state[0]


def _origin(request: Request, a: _Auth) -> str | None:
    """The request's Origin when it is one the cog is configured on, else None (absent counts as foreign)."""
    o = (request.headers.get("origin") or "").rstrip("/")
    return o if o and o in a.origins else None


def _limited(*keys: str) -> bool:
    now = time.monotonic()
    for k in list(_fails):                       # every key, so the table holds only the last WINDOW's failures
        q = _fails[k]
        while q and now - q[0] > WINDOW:
            q.popleft()
        if not q:
            del _fails[k]
    return len(_fails.get(keys[0], ())) >= PER_CLIENT or len(_fails.get(keys[1], ())) >= PER_ACCOUNT


def _nope(status: int = 401, body: bytes = FAILED) -> Response:
    return Response(body, status_code=status, media_type="application/json", headers={"cache-control": "no-store"})


async def viewer(request: Request, a: _Auth | None) -> str | None:
    """The signed-in account behind this request, as identity's sub (uid@cog id), or None. The browser must say the
    request started on this origin (Sec-Fetch-Site), and a state-changing method must also come FROM a configured
    origin (D7's Origin check, on top of SameSite=Strict)."""
    tok = request.cookies.get(SESSION)
    if a is None or not tok:
        return None
    # SameSite=Strict is a SITE rule: a page on a sibling host of the same registrable domain (the tunnel serves
    # VEGA's observer beside the front) still sends the cookie, and some owner GETs WRITE (/api/memory/late claims
    # replies). So the browser's own word on who started the request decides: only this origin, or the viewer
    # typing/bookmarking it ("none"). Same-site, cross-site or no header at all mints nothing (a2 #62390 R-1)
    if request.headers.get("sec-fetch-site") not in ("same-origin", "none"):
        return None
    if request.method not in ("GET", "HEAD", "OPTIONS") and _origin(request, a) is None:
        return None
    try:
        s = await a.db(cogauth.session_of, tok)
    except Exception:  # noqa: BLE001 — a store that can't answer signs nobody in (fail closed), the key still works
        return None
    return cogauth.sub(s[0], a.cog_id) if s else None


@app.post("/auth/login")
async def login(request: Request):
    a = auth()
    if a is None:
        return _nope(404, b'{"error":"this cog has no sign-in"}')
    o = _origin(request, a)
    if o is None:
        return _nope(403, b'{"error":"sign in from this cog\'s own page"}')
    try:
        j = await request.json()
        email, pw = j["email"], j["password"]
        assert isinstance(email, str) and isinstance(pw, str)
    except Exception:  # noqa: BLE001 — any malformed body is the same refusal
        return _nope(400, b'{"error":"send {email, password}"}')
    global _inflight
    ck, ak = "c:" + (request.client.host if request.client else "?"), "a:" + cogauth.norm_email(email)
    if _limited(ck, ak):
        return _nope(429, b'{"error":"too many tries"}')
    if _inflight >= INFLIGHT:            # the host is busy checking passwords: say so now, never queue a hash
        return _nope(503, b'{"error":"sign-in is busy, try again in a moment"}')
    # the attempt counts from its START: a concurrent burst on one client or account stops at its limit, never
    # after every request of it has passed the check above; a success takes its own count back
    now = time.monotonic()
    _fails[ck].append(now)
    _fails[ak].append(now)
    _inflight += 1
    try:
        got = await cogauth.sign_in(a.db, email, pw, check=_check)
    except Exception:  # noqa: BLE001 — the store is down: no session, and no word on the account
        return _nope(503, b'{"error":"sign-in is unavailable"}')
    finally:
        _inflight -= 1
    if got is None:
        return _nope()
    for k in (ck, ak):
        try:
            _fails[k].remove(now)
        except (KeyError, ValueError):
            pass
    r = Response(b'{"ok":true}', media_type="application/json", headers={"cache-control": "no-store"})
    r.set_cookie(SESSION, got[1], max_age=cogauth.SESSION_DAYS * 86400, path="/", httponly=True,
                 samesite="strict", secure=o.startswith("https://"))
    return r


@app.post("/auth/logout")
async def logout(request: Request):
    a = auth()
    if a is None:
        return _nope(404, b'{"error":"this cog has no sign-in"}')
    if _origin(request, a) is None:
        return _nope(403, b'{"error":"sign out from this cog\'s own page"}')
    tok = request.cookies.get(SESSION)
    if tok:
        try:
            await a.db(cogauth.sign_out, tok)
        except Exception:  # noqa: BLE001
            return _nope(503, b'{"error":"sign-out is unavailable"}')
    r = Response(b'{"ok":true}', media_type="application/json", headers={"cache-control": "no-store"})
    r.delete_cookie(SESSION, path="/", httponly=True, samesite="strict")
    return r


@app.get("/auth/me")
async def me(request: Request):
    """{user, orgs: [{org, name, role}]}: the account, and each org of the cog where it holds a role, as THAT org's
    backend answers (its own members row, asked with a token for it): the front holds no role (a2 I1)."""
    a = auth()
    if a is None:
        return _nope(404, b'{"error":"this cog has no sign-in"}')
    tok = request.cookies.get(SESSION)
    try:
        s = await a.db(cogauth.session_of, tok) if tok else None
    except Exception:  # noqa: BLE001
        return _nope(503, b'{"error":"sign-in is unavailable"}')
    if not s:
        return _nope(401, b'{"error":"signed out"}')
    who = cogauth.sub(s[0], a.cog_id)

    async def role(r: dict):
        if r["port"] is None:
            return None
        try:
            resp = await client().get(f"http://127.0.0.1:{r['port']}/api/auth/role", timeout=3,
                                      headers={identity.HEADER: identity.mint(a.key, who, r["org"])})
            got = resp.json().get("role") if resp.status_code == 200 else None
        except (httpx.HTTPError, ValueError, AttributeError):
            return None
        return {"org": r["org"], "name": r["name"], "role": got} if got in cogauth.ROLES else None
    mine = [x for x in await asyncio.gather(*(role(r) for r in rooms())) if x]
    return JSONResponse({"user": s[1], "orgs": mine}, headers={"cache-control": "no-store"})


@app.get("/api/cog")
async def cog():
    return {"cog": True, "home": None,
            "orgs": [{k: r[k] for k in ("org", "name", "base")} for r in rooms()]}


@app.get("/api/cog/stream")
async def cog_stream(request: Request):
    key = request.query_params.get("key")
    a = auth()
    q: asyncio.Queue = asyncio.Queue()

    async def follow(r: dict):
        params = {"key": key} if key else {}
        tag = {"org": r["org"], "name": r["name"]}
        up = None
        while True:
            try:
                if r["port"] is None:
                    raise httpx.ConnectError("no registry port")
                who = await viewer(request, a)    # asked again at EVERY connect: a signed-out session stops here
                signed = {identity.HEADER: identity.mint(a.key, who, r["org"])} if who else {}
                async with client().stream("GET", f"http://127.0.0.1:{r['port']}/api/events", params=params,
                                           headers=signed) as s:
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
    a = auth()
    who = await viewer(request, a)
    # the signed identity for THIS org (D1), minted from the session the front verified; a caller's own copy was
    # never on the allowlist. No session: no identity, and the backend answers as it does to anyone (D2)
    signed = [(identity.HEADER, identity.mint(a.key, who, org))] if who else []
    # ONE allowlist (src/astryx/security/relay.py): the caller's allowed headers, only this org's own canvas cookie,
    # and the view the front OBSERVED: the Host it was reached at, the scheme its uvicorn resolved from its pinned
    # trusted peer, the client it saw. Never the caller's x-forwarded-* or X-Forwarded-For (plan-11859 X1/X2).
    headers = relay.headers(request.headers.items(), host=request.headers.get("host", ""), proto=request.url.scheme,
                            cookies={relay.canvas_cookie(org)},
                            extra=[(CLIENT, request.client.host if request.client else ""),
                                   ("x-forwarded-prefix", f"/o/{org}"), *signed])
    up = client().build_request(request.method, f"http://127.0.0.1:{r['port']}/{path}",
                                params=request.query_params, headers=headers, content=await request.body())
    try:
        resp = await client().send(up, stream=True)
    except httpx.HTTPError:
        return JSONResponse({"error": f"org {org}'s observatory is down"}, status_code=502)
    done = BackgroundTasks()
    done.add_task(resp.aclose)
    out = StreamingResponse(resp.aiter_raw(), status_code=resp.status_code, background=done)
    out.raw_headers = relay.response_headers(resp.headers.raw, org)    # its own canvas cookie, or no Set-Cookie (N1)
    return out


# ?key= must never reach journald in clear (a3 #42085 F2), here as in the backends
from astryx.security import logredact as _logredact  # noqa: E402
_logredact.install()

if DIST.is_dir():
    @app.get("/")
    async def index():
        return FileResponse(DIST / "index.html", headers={"cache-control": "no-store"})
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
