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
  /auth/admin/*, /auth/link, /auth/accept   the admin panel's account half: users, one-time invite and reset links,
                             sign out everywhere (the block "the admin panel's ACCOUNT half" below)
  ANY  /api/<path>           the root API, for the org the VIEWER chose: the `x-astryx-org` header, else the
                             `astryx_org` cookie (the app sets it when the owner picks a room; the front never
                             does). None named: the DEFAULT org (cog front parity, owner 11-13): the cog's only org,
                             else the registry's `door`; with neither, 409 pointing at /api/cog (ruling 3(b): a
                             cog of several has no primary unless its registry names a door). One named that is not
                             in this cog: 409
  ANY  /canvas[/<path>]      308 to /o/<default>/canvas/<path>: canvas's session lives at that path (its cookie's
                             Path), so a bare-path relay would set a cookie the browser never sends back
  ANY  /ear/<path>, /brain/<path>   relayed to the default org, as every root path today's one-org :8090 served
  WS   /o/<org>/<path>, /api/<path>  a websocket pipe to that org's backend (hands' noVNC), the same default rule
  /                          the web app (observatory/web/dist), as the one-org observatory serves it

The front adds ONE fact: who the viewer is (plan-11859 U1+U2). It is the authority for that, so it signs it, per
request and per org, and never says what the viewer may do: each backend decides that from its own members table.
Its one cookie is the session's (httpOnly, SameSite=Strict, Secure on an https origin); no backend can set it or
read it (relay.py, both directions). It has no PUBLIC_PATHS of its own to widen (every /o/ request is judged by the
backend's).

STATED LIMITS: a websocket carries no signed identity (the backend's VNC gate is the owner key in its query, as before).
Run: uvicorn front:app --host 0.0.0.0 --port 8090   (from observatory/), registry: ASTRYX_COG_REGISTRY or the default.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import http.cookiejar
import json
import re
import secrets
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
        except (LookupError, config.ForeignDSN) as e:
            self.dsn = ""          # no store: every sign-in is a 503, and the owner key still works
            # ...and the journal says why, at the first sign-in (a2 #62616: at turn-on a store named like its role
            # read as a bare 503, its reason nowhere)
            print(f"front: the cog's sign-in store is unusable: {e}", file=sys.stderr)
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
    """viewer_id's sub alone (uid@cog id), or None."""
    v = await viewer_id(request, a)
    return v[0] if v else None


def _mint(a: "_Auth", v: tuple[str, str], org: str) -> str:
    """The signed identity for `org`: the account's sub and its own label (cog-who: the email's local part, so the
    org can say WHICH human asked; never the whole email)."""
    return identity.mint(a.key, v[0], org, name=v[1])


async def viewer_id(request: Request, a: _Auth | None) -> tuple[str, str] | None:
    """(sub, label) of the signed-in account behind this request, or None. sub is identity's (uid@cog id), the label
    its email's local part. The browser must say the
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
    return (cogauth.sub(s[0], a.cog_id), str(s[1]).partition("@")[0]) if s else None


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
    return _signed_in(got[1], o)


def _signed_in(token: str, origin: str, body: bytes = b'{"ok":true}') -> Response:
    """The reply that carries a new session: its one cookie (httpOnly, SameSite=Strict, Secure on an https origin)."""
    r = Response(body, media_type="application/json", headers={"cache-control": "no-store"})
    r.set_cookie(SESSION, token, max_age=cogauth.SESSION_DAYS * 86400, path="/", httponly=True,
                 samesite="strict", secure=origin.startswith("https://"))
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
        got = await _role_in(a, who, r)
        return {"org": r["org"], "name": r["name"], "role": got} if got else None
    mine = [x for x in await asyncio.gather(*(role(r) for r in rooms())) if x]
    return JSONResponse({"user": s[1], "orgs": mine}, headers={"cache-control": "no-store"})


async def _role_in(a: "_Auth", who: str, r: dict) -> str | None:
    """The role `who` holds in org r, as THAT org's backend answers (its members table, asked with a token for it)."""
    if r["port"] is None:
        return None
    try:
        resp = await client().get(f"http://127.0.0.1:{r['port']}/api/auth/role", timeout=3,
                                  headers={identity.HEADER: identity.mint(a.key, who, r["org"])})
        got = resp.json().get("role") if resp.status_code == 200 else None
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    return got if got in cogauth.ROLES else None



# ---------------------------------------------------------------- the admin panel's ACCOUNT half (cog-rebuild, owner 11-13)
# "an option to create new user … whoever is the owner of org can decide the roles of other users … managed by an
# admin". Accounts are the cog's (this store); roles are each org's (its backend, observatory/api/admin.py). There is
# no mail on this host, so a new user and a forgotten password are both a ONE-TIME LINK the owner or an admin copies
# to the person: a random token, only its sha256 stored (cog_schema.sql `links`), one use, an expiry.
#
#   GET  /auth/admin/users?org=          the accounts with a role in org: uid, email, created, last sign-in, live
#                                        sessions, their rows [{node, role}]; and the org's open invites
#   POST /auth/admin/invite              {org, role, node?} → {link, expires}: shown once
#   POST /auth/admin/invite/cancel       {org, id}
#   POST /auth/admin/reset               {org, uid} → {link, expires}: a reset LINK, never a password
#   POST /auth/admin/revoke-sessions     {org, uid} → {revoked}: sign out everywhere
#   GET  /auth/link?t=                   what a link is (kind, org, role, node; a reset's email) | 410
#   POST /auth/accept                    {token, email?, password}: an invite creates the account when the email is
#                                        new (an existing one proves its password), then the role is granted; a reset
#                                        sets the password and revokes every session. Either way, signed in after
#
# WHO MAY: the owner or an admin OF THAT ORG, as its backend answers (/api/auth/role, as /auth/me asks), through a
# session viewer() accepts (this origin; a state change from a configured Origin). An admin never makes an owner.
# THE GRANT AT ACCEPT is made AS THE INVITER: the front mints the inviter's identity for that org and PUTs the row to
# the org's /api/admin/members, so the backend judges it with the guards it applies to everyone, and an inviter who
# has since lost the role can no longer bring anyone in. Sessions are cog-wide, so a reset or a sign-out-everywhere
# is refused unless the caller manages EVERY org where the target holds a role (an owner target: owners only).
INVITE_HOURS, RESET_HOURS = 72, 24
_NODE = re.compile(r"^[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*)*$")   # schema.sql members_node_check
MANAGERS = ("owner", "admin")
GONE = b'{"error":"this link is no longer valid"}'


def _json(obj, status: int = 200) -> JSONResponse:
    return JSONResponse(obj, status_code=status, headers={"cache-control": "no-store"})


def _account_n(a: _Auth, who) -> int | None:
    """The account id in a uid of THIS cog (<n>@<cog id>), else None."""
    if not isinstance(who, str):
        return None
    n, _, cid = who.partition("@")
    return int(n) if n.isdigit() and len(n) <= 18 and cid == a.cog_id else None


async def _manager(request: Request, org) -> tuple | Response:
    """(auth, the caller's uid, its role in org, org's room), or the refusal."""
    a = auth()
    if a is None:
        return _nope(404, b'{"error":"this cog has no sign-in"}')
    r = _cog().get(org) if isinstance(org, str) else None
    if r is None:
        return _nope(404, b'{"error":"no such org in this cog"}')
    who = await viewer(request, a)
    if who is None:
        return _nope(401, b'{"error":"signed out"}')
    role = await _role_in(a, who, r)
    if role not in MANAGERS:
        return _nope(403, b'{"error":"owners and admins only"}')
    return a, who, role, r


async def _backend(a: _Auth, who: str, r: dict, method: str, path: str, body=None) -> tuple[int, dict]:
    """A call to org r's backend AS `who` (a token minted for that org): (status, its JSON or {})."""
    if r["port"] is None:
        return 502, {}
    try:
        resp = await client().request(method, f"http://127.0.0.1:{r['port']}{path}", json=body, timeout=10,
                                      headers={identity.HEADER: identity.mint(a.key, who, r["org"])})
    except httpx.HTTPError:
        return 502, {}
    try:
        j = resp.json()
    except ValueError:
        j = {}
    return resp.status_code, j if isinstance(j, dict) else {}


async def _body(request: Request) -> dict | None:
    try:
        j = await request.json()
    except Exception:  # noqa: BLE001 — any malformed body is the same refusal
        return None
    return j if isinstance(j, dict) else None


async def _accounts(conn, ids: list[int]):
    cur = await conn.execute(
        "SELECT u.id, u.email, u.created, max(s.created), "
        "count(s.digest) FILTER (WHERE s.revoked IS NULL AND s.expires > now()) "
        "FROM users u LEFT JOIN sessions s ON s.uid = u.id WHERE u.id = ANY(%s) GROUP BY u.id", (ids,))
    return await cur.fetchall()


async def _open_invites(conn, org: str):
    cur = await conn.execute(
        "SELECT l.id, l.role, l.node, l.created, l.expires, u.email FROM links l LEFT JOIN users u ON u.id = l.by_uid "
        "WHERE l.kind = 'invite' AND l.org = %s AND l.used IS NULL AND l.expires > now() ORDER BY l.created", (org,))
    return await cur.fetchall()


def _iso(t):
    return t.isoformat() if t else None


@app.get("/auth/admin/users")
async def admin_users(request: Request, org: str = ""):
    got = await _manager(request, org)
    if isinstance(got, Response):
        return got
    a, who, you, r = got
    st, j = await _backend(a, who, r, "GET", "/api/admin/members")
    if st != 200 or not isinstance(j.get("members"), list):
        return _nope(502, b'{"error":"the org could not list its members"}')
    rows: dict[str, list] = {}
    for m in j["members"]:
        rows.setdefault(m.get("uid"), []).append({"node": m.get("node") or "", "role": m.get("role")})
    ids = [n for n in (_account_n(a, u) for u in rows) if n is not None]
    try:
        acc = {x[0]: x for x in await a.db(_accounts, ids)}
        inv = await a.db(_open_invites, r["org"])
    except Exception:  # noqa: BLE001
        return _nope(503, b'{"error":"the account store is unavailable"}')
    users = []
    for uid, held in rows.items():
        x = acc.get(_account_n(a, uid))
        root = next((h["role"] for h in held if h["node"] == ""), None)
        users.append({"uid": uid, "email": x[1] if x else None, "created": _iso(x[2]) if x else None,
                      "last_session": _iso(x[3]) if x else None, "live_sessions": x[4] if x else 0,
                      "role": root, "roles": sorted(held, key=lambda h: h["node"]), "you": uid == who})
    users.sort(key=lambda u: (-{"owner": 3, "admin": 2, "member": 1, "viewer": 0}.get(u["role"] or "", -1),
                              u["email"] or "~"))
    return _json({"org": r["org"], "name": r["name"], "you": you, "uid": who, "roles": j.get("roles") or [],
                  "tree": bool(j.get("tree")), "users": users,
                  "invites": [{"id": i[0], "role": i[1], "node": i[2], "created": _iso(i[3]), "expires": _iso(i[4]),
                               "by": i[5]} for i in inv]})


async def _new_link(conn, dig: bytes, kind: str, org: str, role, node: str, uid, by: int, hours: int):
    cur = await conn.execute(
        "INSERT INTO links (digest, kind, org, role, node, uid, by_uid, expires) VALUES (%s, %s, %s, %s, %s, %s, %s, "
        "now() + make_interval(hours => %s)) RETURNING expires", (dig, kind, org, role, node, uid, by, hours))
    return (await cur.fetchone())[0]


def _link_url(request: Request, a: _Auth, token: str) -> str:
    return f"{_origin(request, a)}/#/accept?t={token}"     # a POST here passed viewer(): its Origin is configured


@app.post("/auth/admin/invite")
async def admin_invite(request: Request):
    j = await _body(request) or {}
    got = await _manager(request, j.get("org"))
    if isinstance(got, Response):
        return got
    a, who, you, r = got
    role, node = j.get("role"), j.get("node") or ""
    st, mj = await _backend(a, who, r, "GET", "/api/admin/members")
    if st != 200:
        return _nope(502, b'{"error":"the org could not be asked"}')
    if role not in (mj.get("roles") or []):
        return _json({"error": f"role is one of {', '.join(mj.get('roles') or [])}"}, 400)
    if you != "owner" and role == "owner":
        return _nope(403, b'{"error":"only an owner can invite an owner"}')
    if not isinstance(node, str) or (node and not (mj.get("tree") and _NODE.fullmatch(node))):
        return _nope(400, b'{"error":"node is a path in the agents/ tree"}')
    token = secrets.token_urlsafe(32)
    try:
        exp = await a.db(_new_link, cogauth.digest(token), "invite", r["org"], role, node, None, _account_n(a, who),
                         INVITE_HOURS)
    except Exception:  # noqa: BLE001
        return _nope(503, b'{"error":"the account store is unavailable"}')
    return _json({"link": _link_url(request, a, token), "expires": _iso(exp), "role": role, "node": node})


async def _cancel_invite(conn, org: str, iid: int, owner_too: bool) -> int:
    cur = await conn.execute("UPDATE links SET used = now() WHERE id = %s AND org = %s AND kind = 'invite' AND "
                             "used IS NULL AND (%s OR role <> 'owner')", (iid, org, owner_too))
    return cur.rowcount


@app.post("/auth/admin/invite/cancel")
async def admin_invite_cancel(request: Request):
    j = await _body(request) or {}
    got = await _manager(request, j.get("org"))
    if isinstance(got, Response):
        return got
    a, _, you, r = got
    if not isinstance(j.get("id"), int):
        return _nope(400, b'{"error":"send {org, id}"}')
    n = await a.db(_cancel_invite, r["org"], j["id"], you == "owner")
    return _json({"ok": n > 0})


async def _may_manage(a: _Auth, who: str, you: str, r: dict, target: str) -> Response | None:
    """None when the caller may act on the target's ACCOUNT (cog-wide), else the refusal."""
    if _account_n(a, target) is None:
        return _nope(400, b'{"error":"uid is an account of this cog"}')
    every = rooms()
    theirs = await asyncio.gather(*(_role_in(a, target, x) for x in every))
    if theirs[[x["org"] for x in every].index(r["org"])] is None:
        return _nope(404, b'{"error":"no such member of this org"}')
    if target == who:
        return None
    mine = await asyncio.gather(*(_role_in(a, who, x) if x["org"] != r["org"] else _same(you) for x in every))
    for t, m in zip(theirs, mine):
        if t is None:
            continue
        if m not in MANAGERS:
            return _nope(403, b'{"error":"that account is also in an org you do not manage"}')
        if t == "owner" and m != "owner":
            return _nope(403, b'{"error":"only an owner can do that to an owner"}')
    return None


async def _same(v):
    return v


@app.post("/auth/admin/reset")
async def admin_reset(request: Request):
    j = await _body(request) or {}
    got = await _manager(request, j.get("org"))
    if isinstance(got, Response):
        return got
    a, who, you, r = got
    bad = await _may_manage(a, who, you, r, j.get("uid"))
    if bad:
        return bad
    token = secrets.token_urlsafe(32)
    try:
        exp = await a.db(_new_link, cogauth.digest(token), "reset", r["org"], None, "", _account_n(a, j["uid"]),
                         _account_n(a, who), RESET_HOURS)
    except Exception:  # noqa: BLE001
        return _nope(503, b'{"error":"the account store is unavailable"}')
    return _json({"link": _link_url(request, a, token), "expires": _iso(exp)})


async def _revoke_all(conn, uid: int) -> int:
    cur = await conn.execute("UPDATE sessions SET revoked = now() WHERE uid = %s AND revoked IS NULL", (uid,))
    return cur.rowcount


@app.post("/auth/admin/revoke-sessions")
async def admin_revoke_sessions(request: Request):
    j = await _body(request) or {}
    got = await _manager(request, j.get("org"))
    if isinstance(got, Response):
        return got
    a, who, you, r = got
    bad = await _may_manage(a, who, you, r, j.get("uid"))
    if bad:
        return bad
    n = await a.db(_revoke_all, _account_n(a, j["uid"]))
    return _json({"revoked": n})


async def _peek(conn, dig: bytes):
    cur = await conn.execute(
        "SELECT l.kind, l.org, l.role, l.node, l.uid, l.by_uid, l.expires, u.email FROM links l "
        "LEFT JOIN users u ON u.id = l.uid WHERE l.digest = %s AND l.used IS NULL AND l.expires > now()", (dig,))
    return await cur.fetchone()


async def _claim(conn, dig: bytes) -> bool:
    cur = await conn.execute("UPDATE links SET used = now() WHERE digest = %s AND used IS NULL AND expires > now()",
                             (dig,))
    return cur.rowcount == 1


async def _unclaim(conn, dig: bytes) -> None:
    await conn.execute("UPDATE links SET used = NULL WHERE digest = %s", (dig,))


async def _create(conn, email: str, phc: str) -> int | None:
    cur = await conn.execute("INSERT INTO users (email, pw) VALUES (%s, %s) ON CONFLICT (email) DO NOTHING RETURNING id",
                             (email, phc))
    row = await cur.fetchone()
    return row[0] if row else None


async def _drop_account(conn, uid: int) -> None:
    await conn.execute("DELETE FROM users WHERE id = %s", (uid,))


async def _set_password(conn, uid: int, phc: str) -> None:
    await conn.execute("UPDATE users SET pw = %s WHERE id = %s", (phc, uid))
    await conn.execute("UPDATE sessions SET revoked = now() WHERE uid = %s AND revoked IS NULL", (uid,))


@app.get("/auth/link")
async def link_info(t: str = ""):
    a = auth()
    if a is None:
        return _nope(404, b'{"error":"this cog has no sign-in"}')
    try:
        row = await a.db(_peek, cogauth.digest(t)) if t else None
    except Exception:  # noqa: BLE001
        return _nope(503, b'{"error":"the account store is unavailable"}')
    r = _cog().get(row[1]) if row else None
    if row is None or r is None:
        return _nope(410, GONE)
    return _json({"kind": row[0], "org": row[1], "name": r["name"], "role": row[2], "node": row[3],
                  "expires": _iso(row[6]), "email": row[7] if row[0] == "reset" else None})


@app.post("/auth/accept")
async def accept(request: Request):
    global _inflight
    a = auth()
    if a is None:
        return _nope(404, b'{"error":"this cog has no sign-in"}')
    o = _origin(request, a)
    if o is None:
        return _nope(403, b'{"error":"open the link on this cog\'s own page"}')
    j = await _body(request) or {}
    token, pw, email = j.get("token"), j.get("password"), j.get("email")
    if not (isinstance(token, str) and token and isinstance(pw, str)):
        return _nope(400, b'{"error":"send {token, password}"}')
    ck = "c:" + (request.client.host if request.client else "?")
    if _limited(ck, "l:" + cogauth.digest(token).hex()):
        return _nope(429, b'{"error":"too many tries"}')
    dig = cogauth.digest(token)
    link = await a.db(_peek, dig)
    room = _cog().get(link[1]) if link else None
    if link is None or room is None:
        _fails[ck].append(time.monotonic())
        return _nope(410, GONE)
    kind, org, role, node, target, by = link[:6]
    if len(pw) < 12:
        return _nope(400, b'{"error":"a password has at least 12 characters"}')
    if _inflight >= INFLIGHT:
        return _nope(503, b'{"error":"sign-in is busy, try again in a moment"}')
    acct = None
    if kind == "invite":
        if not (isinstance(email, str) and 3 <= len(email) <= 254 and "@" in email and not any(c.isspace() for c in
                                                                                                 email.strip())):
            return _nope(400, b'{"error":"enter your email"}')
        email = cogauth.norm_email(email)
        if _limited(ck, "a:" + email):     # login's per-account limit holds here too: a link is no side door
            return _nope(429, b'{"error":"too many tries"}')
        acct = await a.db(cogauth._account, email)
    _inflight += 1
    try:
        if acct:      # an existing account joins: it proves its own password (a link is no way into someone's account)
            ok = await _check(cogauth.check_password, pw, acct[1])
            if not ok:
                now = time.monotonic()
                _fails[ck].append(now)
                _fails["a:" + email].append(now)
                return _nope()
        phc = None if acct else await _check(cogauth.hash_password, pw)
    finally:
        _inflight -= 1
    if not await a.db(_claim, dig):         # one use: the claim is the conditional UPDATE, whoever raced us
        return _nope(410, GONE)
    if kind == "reset":
        await a.db(_set_password, target, phc)
        uid = target
    else:
        uid = acct[0] if acct else await a.db(_create, email, phc)
        if uid is None:                      # the email was taken between the read and the write
            await a.db(_unclaim, dig)
            return _nope(409, b'{"error":"that email was just registered: open the link again"}')
        st, bj = await _backend(a, cogauth.sub(by, a.cog_id), room, "PUT", "/api/admin/members",
                                {"uid": cogauth.sub(uid, a.cog_id), "role": role, "node": node})
        if st != 200:                        # the inviter may no longer grant this: nothing is left half-made
            await a.db(_unclaim, dig)
            if not acct:
                await a.db(_drop_account, uid)
            return _json({"error": "the invite could not be honoured: " + str(bj.get("error") or f"status {st}")},
                         409 if st in (401, 403, 409) else 502)     # 409: the link's promise no longer holds
    tok = secrets.token_urlsafe(32)
    await a.db(cogauth._open_session, uid, cogauth.digest(tok))
    return _signed_in(tok, o, json.dumps({"ok": True, "org": org, "kind": kind}).encode())


@app.get("/api/cog")
async def cog():
    # `door`: the org a viewer with no choice lands in (default()), so the app can preselect it (sign-in's dropdown)
    return {"cog": True, "home": None, "door": default(),
            "orgs": [{k: r[k] for k in ("org", "name", "base")} for r in rooms()]}


def default() -> str | None:
    """The org a request that names none goes to (cog front parity, owner 11-13): the cog's ONLY org, else the
    registry's `door` (the primary's: the bare root was its own before the cog, orgs.load), else None (409). A
    property of the registry, never of the request: nothing a caller sends picks it."""
    c = _cog()
    if len(c) == 1:
        return next(iter(c))
    d = orgs.door()
    return d if d in c else None


def _pick(request) -> tuple[str | None, bool]:
    """(the org this root request is for, whether the viewer named it): the header, else the cookie, else default()."""
    named = request.headers.get("x-astryx-org") or request.cookies.get("astryx_org") or ""
    return (named, True) if named else (default(), False)


NO_ORG = {"error": "this cog runs several orgs: choose one", "cog": "/api/cog"}


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
                who = await viewer_id(request, a)    # asked again at EVERY connect: a signed-out session stops here
                signed = {identity.HEADER: _mint(a, who, r["org"])} if who else {}
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
    org, _ = _pick(request)
    if org not in _cog():
        return JSONResponse(NO_ORG, status_code=409)
    return await _relay(org, f"api/{path}", request)


# THE BARE ROOT PATHS today's one-org :8090 serves beside /api (main.py's /canvas, /ear, /brain; the SPA is ours), for
# the default org (cog front parity, owner 11-13: links, bookmarks, the growbot's brain URL keep working). Canvas is a
# redirect, not a relay: its session cookie is Path=/o/<org>/canvas (canvas.py PUBLIC), so a page served at /canvas/
# would set a cookie its own next request never carries (a login loop). The location is computed from the registry
# and the request's own path, never from a header.
@app.api_route("/canvas", methods=METHODS)
@app.api_route("/canvas/{path:path}", methods=METHODS)
async def bare_canvas(request: Request, path: str = ""):
    org = default()
    if org is None:
        return JSONResponse(NO_ORG, status_code=409)
    q = request.url.query
    return Response(status_code=308, headers={"location": f"/o/{org}/canvas/{path}" + (f"?{q}" if q else "")})


@app.api_route("/ear/{path:path}", methods=METHODS)
@app.api_route("/brain/{path:path}", methods=METHODS)
async def bare(path: str, request: Request):
    org = default()
    if org is None:
        return JSONResponse(NO_ORG, status_code=409)
    return await _relay(org, request.url.path.lstrip("/"), request)


# WEBSOCKETS (hands' noVNC, ui/hands.tsx dials the ROOT /api/hands/<agent>/vnc): a byte pipe to the org's backend,
# with the same routing as HTTP (/o/<org>/…, or the root's choice/default). Upstream is dialled FIRST, so the viewer
# is accepted only with the subprotocol the backend chose, and a backend's refusal (its key check) is a refusal here.
# The connect carries only the relay allowlist's headers (src/astryx/security/relay.py) and the query (the key rides
# there: a browser websocket can't send headers); no identity is minted (STATED LIMITS).
from fastapi import WebSocket  # noqa: E402


@app.websocket("/o/{org}/{path:path}")
async def pipe_ws(ws: WebSocket, org: str, path: str):
    await _relay_ws(org, path, ws)


@app.websocket("/api/{path:path}")
async def chosen_ws(ws: WebSocket, path: str):
    org, _ = _pick(ws)
    await _relay_ws(org or "", f"api/{path}", ws)


async def _relay_ws(org: str, path: str, ws: WebSocket):
    import websockets
    r = _cog().get(org)
    if r is None or r["port"] is None:
        await ws.close(code=4404)
        return
    q = ws.url.query
    headers = [(k, v) for k, v in relay.headers(
        ws.headers.items(), host=ws.headers.get("host", ""), proto="https" if ws.url.scheme == "wss" else "http",
        cookies={relay.canvas_cookie(org)},
        extra=[(CLIENT, ws.client.host if ws.client else ""), ("x-forwarded-prefix", f"/o/{org}")])
        if k.lower() not in ("origin", "content-length")]     # websockets sends its own Origin-less handshake
    protos = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    try:
        up = await websockets.connect(f"ws://127.0.0.1:{r['port']}/{path}" + (f"?{q}" if q else ""),
                                      additional_headers=headers, subprotocols=protos or None,
                                      max_size=None, open_timeout=10)
    except websockets.InvalidStatus as e:          # the backend refused the handshake (a 403 is its key check)
        await ws.close(code=4403 if e.response.status_code == 403 else 4502)
        return
    except (OSError, websockets.WebSocketException, asyncio.TimeoutError):
        await ws.close(code=4502)
        return
    await ws.accept(subprotocol=up.subprotocol)

    async def to_up():
        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    return
                if m.get("bytes") is not None:
                    await up.send(m["bytes"])
                elif m.get("text") is not None:
                    await up.send(m["text"])
        except (websockets.ConnectionClosed, RuntimeError):
            return

    async def to_viewer():
        try:
            async for m in up:
                if isinstance(m, bytes):
                    await ws.send_bytes(m)
                else:
                    await ws.send_text(m)
        except (websockets.ConnectionClosed, RuntimeError):
            return

    tasks = [asyncio.create_task(to_up()), asyncio.create_task(to_viewer())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await up.close()
        try:
            await ws.close()
        except RuntimeError:
            pass


async def _relay(org: str, path: str, request: Request):
    r = _cog().get(org)
    if r is None or r["port"] is None:
        return JSONResponse({"error": f"no org {org!r} in this cog"}, status_code=404)
    a = auth()
    who = await viewer_id(request, a)
    # the signed identity for THIS org (D1), minted from the session the front verified; a caller's own copy was
    # never on the allowlist. No session: no identity, and the backend answers as it does to anyone (D2)
    signed = [(identity.HEADER, _mint(a, who, org))] if who else []
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
