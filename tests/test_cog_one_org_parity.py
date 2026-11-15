#!/usr/bin/env python3
"""Cog front parity (cog-rebuild Phase 1, owner 11-13: "the front IS the design"): a cog of ONE org behind the front
(observatory/front.py) loses nothing that today's bare main.py on :8090 serves, and a registry without a `cog` block,
or no registry, is today's behaviour exactly.

The REAL front (uvicorn front:app) before the REAL observatory (uvicorn main:app) and the REAL canvas
(bridges/canvas.py), each a child on a loopback socket it inherits (nothing binds 8090/8091/8092). The org's HOME is a
fake tree (<t>/home/observatory/api/main.py: paths.estate's "a copy in a tree with no package" rule), so the
backend's estate IS the registry's home, as the checkout's own is on a one-org host; canvas gets that estate the same way
(bridges.common.ESTATE, set before it is imported). The copy's only other changes are its two fixed upstreams
(CANVAS_UP, EAR_UP) pointed at this oracle's canvas and a stub, so no arm ever reaches a live canvas or ear. The cog
(its key, store schema, accounts and memberships) is made by the REAL host CLI (src/astryx/cogauth.py) on a fixture
store database. Two- org fronts use stub backends (registry names + a websocket echo). Dummy keys and passwords only.

  P1 ROUTING: one org, no cookie → its backend; two orgs with a door → the door, a cookie still picks the other;
     two orgs, no door → 409 (as before). /api/cog names the default as `door`
  P2 BARE PATHS: /canvas and /canvas/<p>?q → 308 to /o/<org>/canvas/<p>?q; /ear/<p> and /brain/<p> reach the
     backend (its ear proxy, its OpenAI surface); with no default, 409
  P3 CANVAS THROUGH THE FRONT: login at /o/<org>/canvas/api/login sets cv_session-<org> at Path=/o/<org>/canvas, it
     survives both relays, and /api/me with it is the owner
  P4 SIGN-IN, ONE ORG: password → owner reaches an owner route with no key and whoami says owner; a member does not;
     /auth/me names the org and role; logout revokes (whoami not owner, /auth/me 401)
  P5 THE KEY DOOR: x-obs-key through the front still opens an owner route; nothing opens nothing
  P6 THE FORWARDED VIEW: the ear (behind the backend's own pipe) sees the Host the viewer used at the front
  P7 WEBSOCKETS: /api/hands/<a>/vnc and /o/<org>/... pipe to a real ws echo (query, subprotocol, bytes both ways),
     by the same routing; no default → refused; the real backend refuses a keyless VNC through the front
  P8 TODAY, EXACTLY: no registry, and a one-entry registry without a `cog` block: orgs.here is None, canvas is
     cv_session at /canvas, the backend bounces /canvas to /canvas/ and a valid token is NOT the owner
Exit 0 · 1 · 77 (no database, uvicorn, httpx or websockets).
"""
import atexit
import base64
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_cog_one_org_parity', REPO, deps=('psycopg', 'asyncpg', 'fastapi', 'httpx', 'uvicorn', 'cryptography',
                                            'websockets'), env=False)
from astryx.security.sqlguard import propagate  # noqa: E402
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

PY = sys.executable
fails = []
ORIGIN = "http://fx-parity.invalid"
HOSTNAME = "fx-parity.invalid"
KEY = "fx-dummy-obskey-parity-0001"
PW = {"owner": "fx-dummy-pass-owner-0001", "member": "fx-dummy-pass-member-0002"}

STUB = r"""
from fastapi import FastAPI, Request, WebSocket
import os
app = FastAPI()
ME = os.environ["FX_ORG"]

@app.get("/api/whoami")
async def whoami():
    return {"stub": ME}

@app.get("/ear/{path:path}")
async def ear(path: str, request: Request):
    return {"stub": ME, "ear": path, "xfh": request.headers.get("x-forwarded-host")}

@app.websocket("/api/hands/{agent}/vnc")
async def vnc(ws: WebSocket, agent: str):
    proto = ws.headers.get("sec-websocket-protocol", "")
    await ws.accept(subprotocol="binary" if "binary" in proto else None)
    await ws.send_text(f"{ME}|{agent}|{ws.query_params.get('key', '')}")
    while True:
        m = await ws.receive()
        if m["type"] == "websocket.disconnect":
            return
        await ws.send_bytes(m.get("bytes") or (m.get("text") or "").encode())
"""

# the REAL canvas, with this oracle's estate (the HOME) set where canvas reads it, before canvas is imported
CANVAS = r"""
import sys
from pathlib import Path
repo, home, fd = sys.argv[1], sys.argv[2], int(sys.argv[3])
sys.path[:0] = [repo, repo + "/src"]
import bridges.common as common
common.ESTATE = Path(home)
import bridges.canvas as cv
if fd < 0:
    print("RESULT", cv.COOKIE, cv.PUBLIC)
    sys.exit(0)
import uvicorn
uvicorn.run(cv.root, fd=fd, log_level="warning")
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {scrub(str(detail))}")


def scrub(s: str) -> str:
    for label, v in [*PW.items(), ("key", KEY)]:
        s = s.replace(v, f"<{label}'s value>")
    return s


def listener() -> socket.socket:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(64)
    return s


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def call(port, path, method="GET", body=None, headers=None, timeout=20):
    """(status, headers as a list of pairs, body text). Redirects are answers here, never followed."""
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    h = {"content-type": "application/json"} if isinstance(body, dict) else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=data,
                                 headers={**h, **(headers or {})})
    try:
        with _opener.open(req, timeout=timeout) as r:
            return r.status, r.headers.items(), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.items(), e.read().decode()


def hdr(hs, name):
    return next((v for k, v in hs if k.lower() == name), None)


def cookies_of(hs, name):
    return [v for k, v in hs if k.lower() == "set-cookie" and v.startswith(name + "=")]


def attrs(line):
    parts = [x.strip() for x in line.split(";")]
    return {k.lower(): v for k, _, v in (x.partition("=") for x in parts[1:])}


def jget(body, k, default=None):
    try:
        return json.loads(body).get(k, default)
    except (ValueError, AttributeError):
        return default


def wait(port, path, proc, t=90):
    end = time.time() + t
    while time.time() < end and proc.poll() is None:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2)
            return True
        except urllib.error.HTTPError:
            return True
        except OSError:
            time.sleep(0.3)
    return False


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def token(key, sub, aud):
    """THIS oracle's token (its own encoding of identity's spec), never identity.mint."""
    from cryptography.hazmat.primitives import serialization
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    now = int(time.time())
    body = json.dumps({"sub": sub, "aud": aud, "iat": now, "exp": now + 60,
                       "kid": hashlib.sha256(raw).hexdigest()[:16]}, separators=(",", ":")).encode()
    return f"{b64(body)}.{b64(key.sign(body))}"


def ws_talk(port, path, headers=None, protos=("binary",)):
    """(first text, echoed bytes, subprotocol) through a real websocket, or ("refused", <why>, None)."""
    from websockets.sync.client import connect
    try:
        with connect(f"ws://127.0.0.1:{port}{path}", additional_headers=headers or {},
                     subprotocols=list(protos) or None, open_timeout=15) as c:
            first = c.recv(timeout=15)
            c.send(b"\x01\x02fx")
            echo = c.recv(timeout=15)
            return first, echo, c.subprotocol
    except Exception as e:  # noqa: BLE001 — a refusal in any form (handshake status, close code) is the answer
        return "refused", f"{type(e).__name__}: {e}", None


def main():
    t = Path(tempfile.mkdtemp(prefix="astryx-parity-")).resolve()
    atexit.register(shutil.rmtree, t, True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    procs = []
    atexit.register(lambda: [p.kill() for p in procs if p.poll() is None])
    cog_sql = (REPO / "src" / "astryx" / "sql" / "cog_schema.sql").read_text()
    with fixture_db() as da, fixture_db(extra=(cog_sql,)) as ds:
        run(t, da, ds, procs)
    for p in procs:
        if p.poll() is None:
            p.terminate()
    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: a one-org cog behind the front loses nothing; "
          "no cog block, or no registry, is today")
    return 1 if fails else 0


def run(t, da, ds, procs):
    pid = os.getpid()
    O, P, Q = f"fxpar-o-{pid}", f"fxpar-p-{pid}", f"fxpar-q-{pid}"
    cid = f"fxparcog-{pid:08d}"
    names = ("back", "back0", "back1", "canvas", "ear", "sp", "sq", "f1", "f2", "f3")
    socks = {k: listener() for k in names}
    port = {k: s.getsockname()[1] for k, s in socks.items()}
    base = {k: os.environ[k] for k in ("PATH", "HOME", "ASTRYX_FIXTURE_ADMIN_DSN") if k in os.environ}
    cogbase = {**base, "ASTRYX_SQLGUARD_ROOT": str(REPO)}

    # the org's HOME: a fake tree whose observatory/api/main.py is main.py (paths.estate places it at <t>/home)
    home = t / "home"
    api = home / "observatory" / "api"
    api.mkdir(parents=True)
    (home / ".env").write_text(f"ASTRYX_ORG=fed-{O}\nASTRYX_DSN={da['url']}\nOBS_KEY={KEY}\n")
    src = (REPO / "observatory" / "api" / "main.py").read_text()
    for a, b in (("ROOT = Path(__file__).resolve().parent.parent", f"ROOT = Path({str(REPO / 'observatory')!r})"),
                 ('CANVAS_UP = _upstream("astryx-canvas", 8091)', f'CANVAS_UP = "http://127.0.0.1:{port["canvas"]}"'),
                 ('EAR_UP = _upstream("astryx-ear", 8092)', f'EAR_UP = "http://127.0.0.1:{port["ear"]}"')):
        check(f"the fixture's main.py copy finds its line {a.split(' =')[0]}", src.count(a) == 1)
        src = src.replace(a, b)
    (api / "main.py").write_text(src)
    for h, o in ((t / "hp", P), (t / "hq", Q)):
        h.mkdir()
        (h / ".env").write_text(f"ASTRYX_ORG=fed-{o}\n")
    cog_home = t / "cog"
    cog_home.mkdir()
    (cog_home / ".env").write_text(f"ASTRYX_DSN={ds['url']}\nASTRYX_COG_ORIGINS={ORIGIN}\n")

    one = {"orgs": {O: {"home": str(home), "db": f"fxparorg_{pid}", "primary": True,
                        "ports": {"astryx-observatory-org": port["back"]}}}}
    two = {"orgs": {P: {"home": str(t / "hp"), "db": f"fxparp_{pid}", "primary": True,
                        "ports": {"astryx-observatory-org": port["sp"]}},
                    Q: {"home": str(t / "hq"), "db": f"fxparq_{pid}", "ports": {"astryx-observatory-org": port["sq"]}}}}
    reg = {k: t / f"{k}.json" for k in ("one", "nocog", "door", "nodoor", "none")}
    reg["nocog"].write_text(json.dumps(one))           # P8: the same one org, no cog block
    reg["nodoor"].write_text(json.dumps(two))
    two["orgs"][P]["door"] = True
    reg["door"].write_text(json.dumps(two))
    reg["one"].write_text(json.dumps(one))             # the cog block is added once cogauth init has made the key

    # the host CLI makes the cog, its accounts and both memberships (the org's own .env DSN: the fixture's)
    def cog(*args, stdin=None):
        return subprocess.run([PY, str(REPO / "src" / "astryx" / "cogauth.py"), *args], input=stdin,
                              capture_output=True, text=True, timeout=120,
                              env=propagate.env_for_child({**cogbase, "ASTRYX_COG_REGISTRY": str(reg["one"])}))
    r = cog("init", "--home", str(cog_home), "--id", cid)
    check("cogauth init on a fixture store (rc 0)", r.returncode == 0, r.stderr[-300:])
    reg["one"].write_text(json.dumps({**one, "cog": {"id": cid, "home": str(cog_home)}}))
    users = {"owner": "owner@fx-parity.invalid", "member": "member@fx-parity.invalid"}
    for who, email in users.items():
        r = cog("user", "add", email, stdin=PW[who] + "\n")
        check(f"cogauth user add {who} (rc 0)", r.returncode == 0, r.stderr[-300:])
        r = cog("grant", O, email, who)
        check(f"cogauth grant {who} in the one org (rc 0)", r.returncode == 0, r.stderr[-300:])

    # P8's pure half: the predicate, and canvas's name and path, under each registry
    def here(rf):
        p = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, sys.argv[1]); from astryx import orgs; "
                            "print('HERE', orgs.here(sys.argv[2]))", str(REPO / "src"), str(home)],
                           env={**base, "ASTRYX_COG_REGISTRY": str(rf)}, capture_output=True, text=True, timeout=60)
        return next((ln[5:] for ln in p.stdout.splitlines() if ln.startswith("HERE ")), p.stderr[-200:])

    def canvas_names(rf):
        p = subprocess.run([PY, "-c", CANVAS, str(REPO), str(home), "-1"], capture_output=True, text=True, timeout=60,
                           env=propagate.env_for_child({**base, "ASTRYX_COG_REGISTRY": str(rf),
                                                        "ASTRYX_DSN": da["url"], "OBS_KEY": KEY}))
        return next((ln.split()[1:] for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), p.stderr[-300:])

    # the servers: three backends (cog, no cog block, no registry), canvas, the stubs, three fronts
    def backend(k, rf):
        s = socks[k]
        procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "main:app", "--fd", str(s.fileno())], pass_fds=(s.fileno(),), cwd=api,
            env=propagate.env_for_child({**base, "ASTRYX_COG_REGISTRY": str(rf), "ASTRYX_DSN": da["url"],
                                         "OBS_KEY": KEY}),
            stdout=subprocess.DEVNULL, stderr=(t / f"{k}.err").open("w")))
    backend("back", reg["one"])
    backend("back0", reg["none"])
    backend("back1", reg["nocog"])
    s = socks["canvas"]
    procs.append(subprocess.Popen([PY, "-c", CANVAS, str(REPO), str(home), str(s.fileno())], pass_fds=(s.fileno(),),
                                  env=propagate.env_for_child({**base, "ASTRYX_COG_REGISTRY": str(reg["one"]),
                                                               "ASTRYX_DSN": da["url"], "OBS_KEY": KEY}),
                                  stdout=subprocess.DEVNULL, stderr=(t / "canvas.err").open("w")))
    (t / "stub.py").write_text(STUB)
    for k, o in (("ear", O), ("sp", P), ("sq", Q)):
        s = socks[k]
        procs.append(subprocess.Popen([PY, "-m", "uvicorn", "stub:app", "--fd", str(s.fileno())],
                                      pass_fds=(s.fileno(),), cwd=t, env={**base, "PYTHONPATH": str(t), "FX_ORG": o},
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    for k, rf in (("f1", reg["one"]), ("f2", reg["door"]), ("f3", reg["nodoor"])):
        s = socks[k]
        procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "front:app", "--fd", str(s.fileno())], pass_fds=(s.fileno(),),
            cwd=REPO / "observatory", env=propagate.env_for_child({**cogbase, "ASTRYX_COG_REGISTRY": str(rf)}),
            stdout=subprocess.DEVNULL, stderr=(t / f"{k}.err").open("w")))
    for s in socks.values():
        s.close()
    probe = {"back": "/api/whoami", "back0": "/api/whoami", "back1": "/api/whoami", "canvas": "/canvas/api/me",
             "ear": "/api/whoami", "sp": "/api/whoami", "sq": "/api/whoami", "f1": "/api/cog", "f2": "/api/cog",
             "f3": "/api/cog"}
    up = all(wait(port[k], probe[k], procs[i]) for i, k in enumerate(("back", "back0", "back1", "canvas", "ear", "sp",
                                                                       "sq", "f1", "f2", "f3")))
    check("every server starts", up, " | ".join(f"{k}: {(t / f'{k}.err').read_text()[-300:]}"
                                                for k in ("back", "back0", "back1", "canvas", "f1")
                                                if (t / f"{k}.err").exists()))
    if not up:
        return
    F1, F2, F3 = port["f1"], port["f2"], port["f3"]
    SO = {"origin": ORIGIN, "sec-fetch-site": "same-origin"}

    print("\nP1 ROUTING")
    st, _, body = call(F1, "/api/whoami")
    check("one org, nothing chosen: the backend answers (no 409)", st == 200 and jget(body, "owner") is False, f"{st} {body[:200]}")
    st, _, body = call(F2, "/api/whoami")
    check("two orgs with a door, nothing chosen: the door answers", st == 200 and jget(body, "stub") == P, f"{st} {body[:200]}")
    st, _, body = call(F2, "/api/whoami", headers={"cookie": f"astryx_org={Q}"})
    check("two orgs with a door: the viewer's cookie still picks the other", jget(body, "stub") == Q, f"{st} {body[:200]}")
    st, _, body = call(F3, "/api/whoami")
    check("two orgs, no door, nothing chosen: 409 naming /api/cog (as before)", st == 409 and '"/api/cog"' in body, f"{st}")
    st, _, body = call(F2, "/api/whoami", headers={"cookie": "astryx_org=fx-nowhere"})
    check("a cookie naming no org of the cog: 409, never the default", st == 409, f"{st}")
    doors = [jget(call(f, "/api/cog")[2], "door") for f in (F1, F2, F3)]
    check("/api/cog names the default as door: the only org, the door, none", doors == [O, P, None], str(doors))

    print("\nP2 BARE ROOT PATHS")
    st, hs, _ = call(F1, "/canvas")
    check("/canvas → 308 /o/<org>/canvas/", st == 308 and hdr(hs, "location") == f"/o/{O}/canvas/", f"{st} {hdr(hs, 'location')}")
    st, hs, _ = call(F1, "/canvas/api/me?fx=1")
    check("/canvas/api/me?fx=1 → 308 /o/<org>/canvas/api/me?fx=1",
          st == 308 and hdr(hs, "location") == f"/o/{O}/canvas/api/me?fx=1", f"{st} {hdr(hs, 'location')}")
    st, hs, _ = call(F2, "/canvas/")
    check("two orgs with a door: /canvas/ → the door's canvas", st == 308 and hdr(hs, "location") == f"/o/{P}/canvas/",
          f"{st} {hdr(hs, 'location')}")
    st, hs, _ = call(F1, f"/o/{O}/canvas")
    check("the backend's own bounce through /o/<org>/canvas is /o/<org>/canvas/ (its CANVAS_PRE)",
          st == 308 and hdr(hs, "location") == f"/o/{O}/canvas/", f"{st} {hdr(hs, 'location')}")
    st, _, body = call(F1, "/ear/api/fx-probe", headers={"x-obs-key": KEY})
    check("/ear/<p> reaches the backend's ear proxy (the ear stub answers)",
          st == 200 and jget(body, "stub") == O and jget(body, "ear") == "api/fx-probe", f"{st} {body[:200]}")
    st, _, body = call(F1, "/brain/v1/models", headers={"authorization": f"Bearer {KEY}"})
    check("/brain/v1/models reaches the backend's OpenAI surface (with its key)",
          st == 200 and "astryx-growbot" in body, f"{st} {body[:200]}")
    st, _, _ = call(F1, "/brain/v1/models")
    check("/brain without the key: the backend's own 403", st == 403, f"{st}")
    codes = [call(F3, p)[0] for p in ("/canvas/", "/ear/api/x", "/brain/v1/models")]
    check("no default (two orgs, no door): /canvas, /ear, /brain are 409", codes == [409, 409, 409], str(codes))

    print("\nP3 CANVAS THROUGH THE FRONT")
    st, hs, body = call(F1, f"/o/{O}/canvas/api/login", "POST", {"key": KEY}, headers={"x-astryx": "1", **SO})
    sc = cookies_of(hs, f"cv_session-{O}")
    a = attrs(sc[0]) if len(sc) == 1 else {}
    check("the canvas login through the front: 200, ONE cv_session-<org> cookie at Path=/o/<org>/canvas",
          st == 200 and len(sc) == 1 and a.get("path") == f"/o/{O}/canvas" and not cookies_of(hs, "cv_session"),
          f"{st} {[k for k, _ in hs]} {a}")
    tok = sc[0].split(";")[0].split("=", 1)[1] if sc else ""
    st, _, body = call(F1, f"/o/{O}/canvas/api/me", headers={"cookie": f"cv_session-{O}={tok}"})
    check("with that cookie, canvas's /api/me through the front is the owner", st == 200, f"{st} {body[:200]}")
    st, _, _ = call(F1, f"/o/{O}/canvas/api/me", headers={"cookie": f"cv_session={tok}"})
    check("under the plain one-org name it is nobody (the name follows the registry)", st == 401, f"{st}")

    print("\nP4 SIGN-IN IN A ONE-ORG COG")
    sess = {}
    for who in ("owner", "member"):
        st, hs, _ = call(F1, "/auth/login", "POST", {"email": users[who], "password": PW[who]}, headers={"origin": ORIGIN})
        c = cookies_of(hs, "astryx_session")
        sess[who] = c[0].split(";")[0] if len(c) == 1 else ""
        check(f"{who}: a good password → 200 and one session cookie", st == 200 and bool(sess[who]), f"{st}")
    for who, owner in (("owner", True), ("member", False)):
        h = {**SO, "cookie": sess[who]}
        st, _, body = call(F1, "/api/whoami", headers=h)
        check(f"{who}: whoami through the root, no cookie naming an org, says owner={owner}",
              st == 200 and jget(body, "owner") is owner, f"{st} {body[:200]}")
        st, _, _ = call(F1, "/api/goals", headers=h)       # /api/presence is a member's read since 11-15 (member-live)
        check(f"{who}: the owner-only /api/goals with no key is {200 if owner else 403}",
              st == (200 if owner else 403), f"{st}")
        st, _, body = call(F1, "/auth/me", headers=h)
        mine = jget(body, "orgs", [])
        check(f"{who}: /auth/me lists the one org with the role it gave ({who})",
              st == 200 and mine == [{"org": O, "name": f"fed-{O}", "role": who}], f"{st} {body[:300]}")
    st, _, _ = call(F1, "/auth/logout", "POST", headers={"origin": ORIGIN, "cookie": sess["owner"]})
    check("logout: 200", st == 200, f"{st}")
    h = {**SO, "cookie": sess["owner"]}
    st, _, body = call(F1, "/api/whoami", headers=h)
    check("after logout the old cookie is not the owner", jget(body, "owner") is False, f"{st} {body[:200]}")
    st, _, _ = call(F1, "/auth/me", headers=h)
    check("after logout /auth/me is 401", st == 401, f"{st}")

    print("\nP5 THE KEY DOOR")
    st, _, _ = call(F1, "/api/presence", headers={"x-obs-key": KEY})
    check("x-obs-key through the front, no session: the owner route is 200", st == 200, f"{st}")
    st, _, _ = call(F1, "/api/presence")
    check("no key, no session: 403", st == 403, f"{st}")

    print("\nP6 THE FORWARDED VIEW")
    st, _, body = call(F1, "/ear/api/view", headers={"x-obs-key": KEY, "host": HOSTNAME,
                                                     "x-forwarded-host": "evil.invalid"})
    check("the ear behind the backend's pipe sees the Host the viewer used at the front (not the backend's "
          "127.0.0.1, never the caller's forged one)", jget(body, "xfh") == HOSTNAME, f"{st} {body[:200]}")

    print("\nP7 WEBSOCKETS")
    first, echo, proto = ws_talk(F2, "/api/hands/fxa/vnc?key=fx-k")
    check("root /api/hands/<a>/vnc, nothing chosen: the door's ws, the query carried, bytes echoed, binary agreed",
          first == f"{P}|fxa|fx-k" and echo == b"\x01\x02fx" and proto == "binary", f"{first} {echo} {proto}")
    first, echo, _ = ws_talk(F2, "/api/hands/fxa/vnc", headers={"cookie": f"astryx_org={Q}"})
    check("the root ws follows the viewer's chosen org", first == f"{Q}|fxa|", f"{first} {echo}")
    first, echo, _ = ws_talk(F2, f"/o/{Q}/api/hands/fxb/vnc?key=k2")
    check("/o/<org>/... ws reaches that org", first == f"{Q}|fxb|k2" and echo == b"\x01\x02fx", f"{first} {echo}")
    first, why, _ = ws_talk(F3, "/api/hands/fxa/vnc")
    check("no default (two orgs, no door): the root ws is refused", first == "refused", f"{first} {why}")
    first, why, _ = ws_talk(F2, "/o/fx-nowhere/api/hands/fxa/vnc")
    check("an org not in the cog: refused", first == "refused", f"{first} {why}")
    first, why, _ = ws_talk(F1, "/api/hands/fxa/vnc")
    check("the real backend, through the front, refuses a keyless VNC", first == "refused", f"{first} {why}")

    print("\nP8 TODAY, EXACTLY: NO REGISTRY, NO COG BLOCK")
    hs_ = {k: here(reg[k]) for k in ("none", "nocog", "one")}
    check("orgs.here: None with no registry and with no cog block; the org with one",
          hs_ == {"none": "None", "nocog": "None", "one": O}, str(hs_))
    cn = {k: canvas_names(reg[k]) for k in ("none", "nocog", "one")}
    check("canvas: cv_session at /canvas with no registry and with no cog block; cv_session-<org> at /o/<org>/canvas "
          "in the one-org cog", cn == {"none": ["cv_session", "/canvas"], "nocog": ["cv_session", "/canvas"],
                                       "one": [f"cv_session-{O}", f"/o/{O}/canvas"]}, str(cn))
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    signer = Ed25519PrivateKey.from_private_bytes(bytes.fromhex((cog_home / "identity.key").read_text().strip()))
    import psycopg
    with psycopg.connect(ds["url"]) as c:
        uid = c.execute("SELECT id FROM users WHERE email = %s", (users["owner"],)).fetchone()[0]
    sub = f"{uid}@{cid}"
    for k, label in (("back0", "no registry"), ("back1", "no cog block")):
        st, hs, _ = call(port[k], "/canvas")
        check(f"{label}: the backend bounces /canvas to /canvas/", st == 308 and hdr(hs, "location") == "/canvas/",
              f"{st} {hdr(hs, 'location')}")
        st, _, body = call(port[k], "/api/whoami", headers={"x-astryx-identity": token(signer, sub, O)})
        check(f"{label}: a valid token for the org is NOT the owner (no sign-in, as before)",
              jget(body, "owner") is False, f"{st} {body[:200]}")
    st, _, body = call(port["back"], "/api/whoami", headers={"x-astryx-identity": token(signer, sub, O)})
    check("control: the one-org cog's backend takes that same token as its owner", jget(body, "owner") is True,
          f"{st} {body[:200]}")


if __name__ == "__main__":
    from astryx.security.sqlguard.estate import unavailable
    from astryx.security.sqlguard.fixture import FixtureUnavailable
    try:
        rc = main()
    except FixtureUnavailable as e:
        unavailable("test_cog_one_org_parity", REPO, e)
    sys.exit(rc)
