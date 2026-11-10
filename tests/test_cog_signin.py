#!/usr/bin/env python3
"""plan-11859 U1+U2 end to end: the cog's sign-in, the signed identity, and each org deciding for itself.

The REAL front (uvicorn front:app) before two REAL org observatories (uvicorn main:app, each its own fixture database
and HOME) and one stub backend, on loopback sockets the children inherit (nothing binds 8090). The cog's HOME, its
key, its store's schema, its accounts and every membership row are made by the REAL host CLI (src/astryx/cogauth.py),
the store living in org B's fixture database (cog_schema.sql is applied there as the fixture's extra DDL). Dummy
passwords and keys only; every assertion is on a status, a name or whose value appeared, never a printed secret.

  S1 SIGN-IN: a good password → 200 and ONE cookie astryx_session (HttpOnly, SameSite=Strict, Path=/; Secure only when
     the request comes from the configured https origin). A wrong password and an unknown email → the SAME status and
     bytes, and an unknown email pays the password check too (its latency within 3x of a known one's: F8, I9)
  S2 ORIGIN (D7): no Origin, or one the cog isn't configured on → 403 and no session row; a caller's forged
     x-forwarded-host moves nothing
  S3 RATE (D4, J4): 5 failures on one account → the 6th is 429 even with the right password; the same for an email
     with no account, in the same bytes; 20 failures from one client → 429 for any account from it
  S4 THE OWNER ARM (owner ruling 10-21, seed #61925): signed in, with NO x-obs-key, the owner reaches org A's
     owner-only /api/presence (200) and /api/whoami says owner, through /o/A/ and through the root with x-astryx-org;
     the same requests with ONLY x-obs-key, no cookie, still work (the fallback intact); with neither, 403
  S5 EACH ORG DECIDES (I1): the same account is only a MEMBER of B: B's owner-only route is 403 and whoami not owner;
     /auth/me lists {A owner, B member} as each org answered; an account with no membership anywhere lists none, and
     once its session row expires, /auth/me is 401
  S6 THE STRIP (D3): a caller's own x-astryx-identity (a VALID token for A's owner, minted with the cog's real key)
     sent with no session never reaches A: whoami not owner. A state-changing request with the session but a foreign
     Origin carries no identity (403)
  S7 SIGN-OUT: the session row is revoked: the old cookie gets no identity (whoami not owner) and /auth/me is 401
  S8 D2 AT THE BACKEND, direct on its loopback port: a token minted for B, an expired one and one signed by a key the
     cog never published are each the public face; A's own valid token is the owner
  S9 A BACKEND'S SET-COOKIE (a3 N1, a4 #62231): the stub answers Set-Cookie for the front's session, for other
     orgs' canvas sessions and for its own; the browser gets only its own. The same stub as A's canvas, asked through
     A's own observatory pipe directly: only A's canvas cookie
  S10 NO SIGN-IN: a front whose registry has no `cog` block answers /auth/* with 404 (the app's "unavailable")
  S11 THE COG STREAM: signed in, each backend's /api/events connect carries a token for THAT org naming the account;
     after sign-out, the stream's next connect (the front's retry) carries none; without a session, none ever
  S14 A SAME-SITE PAGE (a2 #62390 R-1): SameSite=Strict lets a sibling host of the same site send the cookie, and
     /api/memory/late WRITES on GET (it claims the owner's waiting replies). With the session and Sec-Fetch-Site
     same-site, cross-site or absent: 403 and the reply stays pending; same-origin: 200 and it is claimed
  S13 an org whose database lacks the members table (schema.sql not re-applied yet): a valid identity is the public
     face, never a 500
  S15 a front whose cog store DSN names a database like its role (seed's turn-on, 10-23): sign-in is 503, and its
     stderr (the journal) names why
  S12 AN ORG'S OWN STREAM: signed in, no key, A's /api/events (an EventSource: no header) streams an agent's step,
     the owner-only content
Seams: OBS_FRONT_SRC (a mutant front.py), OBS_MAIN_SRC (a mutant main.py), COGAUTH_SRC (a mutant cogauth.py).
Exit 0 · 1 · 77 (no database, uvicorn or httpx).
"""
import atexit
import base64
import http.client
import hashlib
import json
import os
import shutil
import signal
import socket
import statistics
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
gate('test_cog_signin', REPO, deps=('psycopg', 'asyncpg', 'fastapi', 'httpx', 'uvicorn', 'cryptography'), env=False)
from astryx.security.sqlguard import propagate  # noqa: E402
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

PY = sys.executable
fails = []
ORIGIN, SECURE = "http://fx-front.invalid", "https://fx-secure.invalid"
PW = {"owner": "fx-dummy-pass-owner-0001", "lone": "fx-dummy-pass-lone-0002", "slow": "fx-dummy-pass-slow-0003",
      "lock": "fx-dummy-pass-lock-0004"}
KEY = {"a": "fx-dummy-obskey-a-0001", "b": "fx-dummy-obskey-b-0002"}

STUB = r"""
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import os
app = FastAPI()
ORGS = os.environ["FX_ORGS"].split(",")

@app.get("/api/cookies")
@app.get("/canvas/api/cookies")              # as an org's canvas, behind that org's own observatory pipe
async def cookies():
    r = Response("{}", media_type="application/json")
    r.raw_headers.append((b"set-cookie", b"astryx_session=fx-fixed-session; Path=/; HttpOnly"))
    r.raw_headers.append((b"set-cookie", b"cv_session-fxsi-other=fx-other; Path=/o/fxsi-other/canvas"))
    for o in ORGS:
        r.raw_headers.append((b"set-cookie", f"cv_session-{o}=fx-own; Path=/o/{o}/canvas; HttpOnly".encode()))
    return r

@app.get("/api/events")
async def events(request: Request):
    # one event saying what THIS connect carried (the token's claims, decoded, unverified: S8 verifies), then the end:
    # the front reconnects after its RETRY and mints again
    import base64, json
    tok = request.headers.get("x-astryx-identity")
    claims = None
    if tok:
        b = tok.split(".")[0]
        claims = json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
    async def gen():
        yield "data: " + json.dumps({"type": "fx_connect", "aud": (claims or {}).get("aud"),
                                     "sub": (claims or {}).get("sub")}) + "\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/api/auth/role")
async def role():
    return Response('{"error":"no role here"}', status_code=401, media_type="application/json")
"""


PRELOAD = ("import sys, types; src, mut = sys.argv[1], sys.argv[2]; del sys.argv[1:3]; sys.path.insert(0, src); "
           "import astryx; m = types.ModuleType('astryx.cogauth'); m.__file__ = src + '/astryx/cogauth.py'; "
           "m.__package__ = 'astryx'; sys.modules['astryx.cogauth'] = m; astryx.cogauth = m; "
           "exec(compile(open(mut).read(), m.__file__, 'exec'), m.__dict__); import uvicorn; sys.exit(uvicorn.main())")


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {scrub(str(detail))}")


def scrub(s: str) -> str:
    """Every dummy secret replaced by its label before a failure detail is printed."""
    for label, v in [*PW.items(), *KEY.items()]:
        s = s.replace(v, f"<{label}'s value>")
    return s


def listener() -> socket.socket:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(64)
    return s


def call(port, path, method="GET", body=None, headers=None, timeout=20):
    """(status, headers as a list of pairs, body text, seconds)."""
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    h = {"content-type": "application/json"} if isinstance(body, dict) else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=data, headers={**h, **(headers or {})})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.items(), r.read().decode(), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.headers.items(), e.read().decode(), time.monotonic() - t0


def cookies_of(hs, name=None):
    return [v for k, v in hs if k.lower() == "set-cookie" and (name is None or v.startswith(name + "="))]


def attrs(line):
    parts = [x.strip() for x in line.split(";")]
    return {k.lower(): v for k, _, v in (x.partition("=") for x in parts[1:])}


def wait(port, path, proc, t=60):
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


def token(key, sub, aud, iat=None, ttl=60):
    """THIS oracle's token (its own encoding), for the backend arms: never identity.mint."""
    from cryptography.hazmat.primitives import serialization
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    now = int(time.time()) if iat is None else iat
    body = json.dumps({"sub": sub, "aud": aud, "iat": now, "exp": now + ttl,
                       "kid": hashlib.sha256(raw).hexdigest()[:16]}, separators=(",", ":")).encode()
    return f"{b64(body)}.{b64(key.sign(body))}"


def main():
    t = Path(tempfile.mkdtemp(prefix="astryx-signin-")).resolve()
    atexit.register(shutil.rmtree, t, True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    procs = []
    atexit.register(lambda: [p.kill() for p in procs if p.poll() is None])
    cog_sql = (REPO / "src" / "astryx" / "sql" / "cog_schema.sql").read_text()
    with fixture_db() as da, fixture_db(extra=(cog_sql,)) as dbb:
        run(t, da, dbb, procs)
    for p in procs:
        if p.poll() is None:
            p.terminate()
    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: one sign-in for the cog, a signed identity per "
          "request, and each org deciding from its own members")
    return 1 if fails else 0


def run(t, da, dbb, procs):
    pid = os.getpid()
    oa, ob, oc = f"fxsi-a-{pid}", f"fxsi-b-{pid}", f"fxsi-c-{pid}"
    cid = f"fxcog-{pid:08d}"
    socks = {k: listener() for k in ("a", "b", "c", "c2", "front", "bare", "badstore")}
    port = {k: s.getsockname()[1] for k, s in socks.items()}
    reg = {"orgs": {}}
    for o, d, k in ((oa, da, "a"), (ob, dbb, "b"), (oc, None, "c")):
        h = t / o
        h.mkdir()
        (h / ".env").write_text(f"ASTRYX_ORG=fed-{o}\n" + (f"ASTRYX_DSN={d['url']}\n" if d else "")
                                + (f"OBS_KEY={KEY[k]}\n" if k in KEY else ""))
        reg["orgs"][o] = {"home": str(h), "db": f"fxsidb_{k}_{pid}", "ports": {"astryx-observatory-org": port[k]}}
    reg["orgs"][oa]["ports"]["astryx-canvas"] = port["c2"]     # A's canvas: the stub again, behind A's own pipe
    (t / "bare.json").write_text(json.dumps(reg))          # S10: the same cog with no sign-in
    home = t / "cog"
    home.mkdir()
    (home / ".env").write_text(f"ASTRYX_DSN={dbb['url']}\nASTRYX_COG_ORIGINS={ORIGIN}, {SECURE}\n")
    regf = t / "cog.json"
    regf.write_text(json.dumps(reg))
    base = {k: os.environ[k] for k in ("PATH", "HOME", "ASTRYX_FIXTURE_ADMIN_DSN") if k in os.environ}
    # the cog-scoped children (the CLI, the fronts) have no org HOME, so sqlguard's shim in them finds the admin DSN
    # through the tree named here (else every cog-store site is capped at FIXTURE-DDL: its stamps go unread)
    cogbase = {**base, "ASTRYX_SQLGUARD_ROOT": str(REPO)}

    # the host CLI makes the cog (the owner's sudo step, the registry line, is this oracle's)
    cli_src = os.environ.get("COGAUTH_SRC")
    cli = [PY, cli_src or str(REPO / "src" / "astryx" / "cogauth.py")]
    if cli_src:
        cli = [PY, "-c", "import sys; real, mut = sys.argv[1], sys.argv[2]; del sys.argv[1:3]; "
               "exec(compile(open(mut).read(), real, 'exec'), {'__name__': '__main__', '__file__': real})",
               str(REPO / "src/astryx/cogauth.py"), cli_src]

    def cog(*args, stdin=None):
        return subprocess.run([*cli, *args], input=stdin, capture_output=True, text=True, timeout=120,
                              env=propagate.env_for_child({**cogbase, "ASTRYX_COG_REGISTRY": str(regf)}))
    r = cog("init", "--home", str(home), "--id", cid)
    check("cogauth init: a signing key and the store's schema (rc 0)", r.returncode == 0, r.stderr[-300:])
    reg["cog"] = {"id": cid, "home": str(home)}
    regf.write_text(json.dumps(reg))
    # S15's cog: the same key, a store DSN whose database is named like its role (libpq's default: config refuses it)
    bad = t / "cog-badstore"
    shutil.copytree(home / "keys", bad / "keys")
    shutil.copy2(home / "identity.key", bad / "identity.key")
    (bad / ".env").write_text(f"ASTRYX_DSN=postgresql://fxsirole@127.0.0.1:5432/fxsirole\nASTRYX_COG_ORIGINS={ORIGIN}\n")
    (t / "badstore.json").write_text(json.dumps({**reg, "cog": {"id": cid, "home": str(bad)}}))
    users = {"owner": "Owner@FX-Signin.invalid", "lone": "lone@fx-signin.invalid", "slow": "slow@fx-signin.invalid",
             "lock": "lock@fx-signin.invalid"}
    for who, email in users.items():
        r = cog("user", "add", email, stdin=PW[who] + "\n")
        check(f"cogauth user add ({who}): the password from stdin (rc 0)", r.returncode == 0, r.stderr[-300:])
    for args in (("grant", oa, users["owner"], "owner"), ("grant", ob, users["owner"], "member")):
        r = cog(*args)
        check(f"cogauth {' '.join(args[:2])} … {args[3]} (rc 0)", r.returncode == 0, r.stderr[-300:])

    # the backends, the stub and the fronts
    (t / "stub.py").write_text(STUB)
    main_src = os.environ.get("OBS_MAIN_SRC")
    mdir = REPO / "observatory" / "api"
    if main_src:
        mdir = t / "obsapi"
        mdir.mkdir()
        (mdir / "main.py").write_text(Path(main_src).read_text().replace(
            "ROOT = Path(__file__).resolve().parent.parent", f"ROOT = Path({str(REPO / 'observatory')!r})"))
    for o, k, d in ((oa, "a", da), (ob, "b", dbb)):
        s = socks[k]
        procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "main:app", "--fd", str(s.fileno())], pass_fds=(s.fileno(),), cwd=mdir,
            env=propagate.env_for_child({**base, "ASTRYX_COG_REGISTRY": str(regf), "ASTRYX_HOME": str(t / o),
                                         "ASTRYX_DSN": d["url"], "OBS_KEY": KEY[k]}),
            stdout=subprocess.DEVNULL, stderr=(t / f"{k}.err").open("w")))
    for k in ("c", "c2"):
        s = socks[k]
        # own-env: the oracle's stub app (t/stub.py), not repo code
        procs.append(subprocess.Popen([PY, "-m", "uvicorn", "stub:app", "--fd", str(s.fileno())], pass_fds=(s.fileno(),),
                                      cwd=t, env={**base, "PYTHONPATH": str(t), "FX_ORGS": f"{oc},{oa}",
                                                  "ASTRYX_COG_REGISTRY": str(regf)},
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    front_src = os.environ.get("OBS_FRONT_SRC")
    fdir = REPO / "observatory"
    if front_src:
        fdir = t / "observatory"
        fdir.mkdir()
        (fdir / "front.py").write_text(Path(front_src).read_text().replace(
            'ROOT = Path(__file__).resolve().parent', f'ROOT = Path({str(REPO / "observatory")!r})'))
    # COGAUTH_SRC reaches the front too: its cogauth is the mutant, loaded before uvicorn imports front.py
    launch = [PY, "-m", "uvicorn"] if not cli_src else [PY, "-c", PRELOAD, str(REPO / "src"), cli_src]
    for k, rf in (("front", regf), ("bare", t / "bare.json"), ("badstore", t / "badstore.json")):
        s = socks[k]
        procs.append(subprocess.Popen(
            [*launch, "front:app", "--fd", str(s.fileno())], pass_fds=(s.fileno(),), cwd=fdir,
            env=propagate.env_for_child({**cogbase, "ASTRYX_COG_REGISTRY": str(rf)}),
            stdout=subprocess.DEVNULL, stderr=(t / f"{k}.err").open("w")))
    for s in socks.values():
        s.close()
    F = port["front"]
    up = all(wait(port[k], "/api/whoami" if k in "ab" else "/api/cog" if k in ("front", "bare") else "/api/auth/role",
                  procs[i]) for i, k in enumerate(("a", "b", "c", "c2", "front", "bare", "badstore")))
    check("every server starts", up, " | ".join((t / f"{k}.err").read_text()[-300:] for k in ("a", "b", "front")
                                                 if (t / f"{k}.err").exists()))
    if not up:
        return
    O = {"origin": ORIGIN}

    def login(who, pw=None, email=None, headers=None):
        return call(F, "/auth/login", "POST", {"email": email or users[who], "password": PW[who] if pw is None else pw},
                    headers={**O, **(headers or {})})

    def session_rows():
        import psycopg
        with psycopg.connect(dbb["url"]) as c:
            return c.execute("SELECT count(*) FROM sessions").fetchone()[0]

    print("\nS1 SIGN-IN")
    st, hs, body, _ = login("owner", headers={"x-forwarded-for": "198.51.100.1"})
    sc = cookies_of(hs, "astryx_session")
    a = attrs(sc[0]) if len(sc) == 1 else {}
    check("a good password: 200 and one astryx_session cookie", st == 200 and len(sc) == 1, f"{st} {len(sc)}")
    check("...HttpOnly, SameSite=Strict, Path=/, and not Secure on the http origin",
          "httponly" in a and a.get("samesite", "").lower() == "strict" and a.get("path") == "/" and "secure" not in a,
          str(sorted(a)))
    sess = sc[0].split(";")[0] if sc else ""
    st2, hs2, _, _ = login("owner", headers={"origin": SECURE, "x-forwarded-for": "198.51.100.1"})
    a2 = attrs(cookies_of(hs2, "astryx_session")[0]) if cookies_of(hs2, "astryx_session") else {}
    check("from the configured https origin the cookie is Secure", st2 == 200 and "secure" in a2, str(sorted(a2)))
    wrong, none = [], []
    for i in range(5):            # INTERLEAVED, so a load spike (the backends warming up) lands on both sides alike
        wrong.append(login("slow", pw="fx-dummy-wrong-0009", headers={"x-forwarded-for": "198.51.100.2"}))
        none.append(login("slow", email=f"nobody{i}@fx-signin.invalid", pw="fx-dummy-wrong-0009",
                          headers={"x-forwarded-for": "198.51.100.2"}))
    check("a wrong password and an unknown email: the same status and the same bytes",
          len({(w[0], w[2]) for w in wrong + none}) == 1 and wrong[0][0] == 401, str({(w[0], w[2]) for w in wrong + none}))
    mw, mn = statistics.median(w[3] for w in wrong), statistics.median(n[3] for n in none)
    # 3x: a loaded host moves one median, never by the ~15x an unknown email that skips the check shows
    check("an unknown email pays the password check: its latency within 3x of a known account's",
          mn >= mw / 3 and mw >= mn / 3, f"known {[round(w[3], 3) for w in wrong]}, unknown {[round(n[3], 3) for n in none]}")

    print("\nS2 ORIGIN")
    before = session_rows()
    st_no, _, _, _ = call(F, "/auth/login", "POST", {"email": users["lone"], "password": PW["lone"]},
                          headers={"x-forwarded-for": "198.51.100.3"})
    st_far, _, _, _ = login("lone", headers={"origin": "https://fx-elsewhere.invalid", "x-forwarded-host":
                                             "fx-front.invalid", "x-forwarded-for": "198.51.100.3"})
    check("no Origin, or a foreign one (a forged x-forwarded-host beside it): 403, and no session row",
          st_no == 403 and st_far == 403 and session_rows() == before, f"{st_no} {st_far}")

    print("\nS3 RATE")
    lock = [login("lock", pw="fx-dummy-wrong-0009", headers={"x-forwarded-for": f"198.51.100.{10 + i}"})[0]
            for i in range(5)]
    right = login("lock", headers={"x-forwarded-for": "198.51.100.20"})
    ghost = [login("lock", email="ghost@fx-signin.invalid", pw="fx-dummy-wrong-0009",
                   headers={"x-forwarded-for": f"198.51.100.{30 + i}"}) for i in range(6)]
    check("5 failures on one account: the 6th is 429, even with the right password",
          lock == [401] * 5 and right[0] == 429, f"{lock} {right[0]}")
    check("an email with no account: the same 429, in the same bytes", ghost[-1][0] == 429 and ghost[-1][2] == right[2],
          f"{ghost[-1][0]}")
    flood = [login("slow", email=f"flood{i}@fx-signin.invalid", pw="fx-dummy-wrong-0009",
                   headers={"x-forwarded-for": "198.51.100.40"})[0] for i in range(20)]
    after = login("lone", headers={"x-forwarded-for": "198.51.100.40"})
    check("20 failures from one client: 429 for any account from it", after[0] == 429 and flood[-1] == 401,
          f"{flood[-1]} {after[0]}")

    print("\nS4 THE OWNER ARM: SIGNED IN, NO KEY")
    SO = {"sec-fetch-site": "same-origin"}       # what a browser says of a request this page itself started
    C = {"cookie": sess, **SO}
    via = {"/o/A/": lambda p, h: call(F, f"/o/{oa}{p}", headers=h),
           "the root with x-astryx-org": lambda p, h: call(F, p, headers={**h, "x-astryx-org": oa})}
    for name, go in via.items():
        st_p, _, _, _ = go("/api/presence", C)
        _, _, w, _ = go("/api/whoami", C)
        check(f"signed in, no x-obs-key, through {name}: the owner-only /api/presence is 200, whoami says owner",
              st_p == 200 and json.loads(w).get("owner") is True, f"{st_p} {w[:80]}")
    st_k, _, _, _ = call(F, f"/o/{oa}/api/presence", headers={"x-obs-key": KEY["a"]})
    _, _, wk, _ = call(F, f"/o/{oa}/api/whoami", headers={"x-obs-key": KEY["a"]})
    check("ONLY x-obs-key, no cookie: still 200 and owner (the fallback intact)",
          st_k == 200 and json.loads(wk).get("owner") is True, f"{st_k}")
    st_0, _, _, _ = call(F, f"/o/{oa}/api/presence")
    check("neither: 403", st_0 == 403, f"{st_0}")

    print("\nS5 EACH ORG DECIDES")
    st_b, _, _, _ = call(F, f"/o/{ob}/api/presence", headers=C)
    _, _, wb, _ = call(F, f"/o/{ob}/api/whoami", headers=C)
    check("a MEMBER of B: B's owner-only route is 403, whoami not owner", st_b == 403
          and json.loads(wb).get("owner") is False, f"{st_b} {wb[:80]}")
    st_m, _, mb, _ = call(F, "/auth/me", headers=C)
    me = json.loads(mb) if st_m == 200 else {}
    got = sorted((x.get("org"), x.get("name"), x.get("role")) for x in me.get("orgs", []))
    check("/auth/me: the account, and {A owner, B member} as each org answered (the stub, no role, absent)",
          me.get("user") == users["owner"].lower() and got == [(oa, f"fed-{oa}", "owner"), (ob, f"fed-{ob}", "member")],
          f"{st_m} {got}")
    sl = cookies_of(login("lone", headers={"x-forwarded-for": "198.51.100.50"})[1], "astryx_session")
    lone = sl[0].split(";")[0] if sl else ""
    st_l, _, ml, _ = call(F, "/auth/me", headers={"cookie": lone})
    check("an account with no membership anywhere: /auth/me lists no org", st_l == 200 and json.loads(ml).get("orgs") == [],
          f"{st_l} {ml[:80]}")
    st_la, _, _, _ = call(F, f"/o/{oa}/api/presence", headers={"cookie": lone, **SO})
    check("...and A's owner-only route is 403 for it", st_la == 403, f"{st_la}")
    import psycopg
    with psycopg.connect(dbb["url"], autocommit=True) as c:      # its sessions run out (D7: a server row's expiry)
        c.execute("UPDATE sessions SET expires = now() - interval '1 second' WHERE uid = %s", (_uid(dbb, users["lone"]),))
    st_e, _, _, _ = call(F, "/auth/me", headers={"cookie": lone})
    check("an EXPIRED session: /auth/me is 401", st_e == 401, f"{st_e}")

    print("\nS6 THE STRIP")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey as _K
    real = _K.from_private_bytes(bytes.fromhex((home / "identity.key").read_text().strip()))   # the spec: a hex seed
    owner_sub = f"{_uid(dbb, users['owner'])}@{cid}"
    forged = token(real, owner_sub, oa)
    _, _, wf, _ = call(F, f"/o/{oa}/api/whoami", headers={"x-astryx-identity": forged})
    check("a caller's own x-astryx-identity (a VALID token for A's owner), no session: whoami not owner",
          json.loads(wf).get("owner") is False, wf[:80])
    st_x, _, _, _ = call(F, f"/o/{oa}/api/messages", "POST", {"to": "fxnobody", "body": "fx"},
                         headers={**C, "origin": "https://fx-elsewhere.invalid"})
    st_y, _, _, _ = call(F, f"/o/{oa}/api/messages", "POST", {"to": "", "body": ""}, headers={**C, **O})
    check("a POST with the session from a foreign Origin carries no identity: 403 (control: from the cog's own "
          "origin it reaches the handler, 400 on an empty message)", st_x == 403 and st_y == 400, f"{st_x} {st_y}")

    print("\nS12 AN ORG'S OWN EVENT STREAM")
    conn = http.client.HTTPConnection("127.0.0.1", F, timeout=30)
    conn.request("GET", f"/o/{oa}/api/events", headers=C)       # an EventSource: the cookie, never a key
    resp = conn.getresponse()
    time.sleep(1.5)                                             # its LISTEN is up before the step lands
    import psycopg
    with psycopg.connect(da["url"], autocommit=True) as c:
        c.execute("INSERT INTO steps (agent, kind, content) VALUES ('fxsi-agent', 'tool', 'fx-step-for-the-owner')")
    seen, end = None, time.time() + 20
    while seen is None and time.time() < end:
        ln = resp.fp.readline().decode()
        if ln.startswith("data: ") and '"fxsi-agent"' in ln:        # the doorbell carries {id, agent, kind}
            seen = json.loads(ln[6:])
    conn.close()
    check("signed in, no key: A's /api/events streams an agent's step (owner-only content) through the front",
          seen is not None and seen.get("type") == "step" and seen.get("agent") == "fxsi-agent", str(seen)[:200])

    print("\nS14 A SAME-SITE PAGE (a2 #62390 R-1)")
    import psycopg
    with psycopg.connect(da["url"], autocommit=True) as c:      # a reply waiting for the owner's desk
        late = c.execute("INSERT INTO messages (from_agent, to_agent, to_org, thread, intent, body, status) VALUES "
                         "('fxsi-agent', 'owner', 'local', 'obs:estate-fx', 'chat', 'fx-late-reply', 'pending') "
                         "RETURNING id").fetchone()[0]

    def pending():
        with psycopg.connect(da["url"]) as c:
            return c.execute("SELECT status FROM messages WHERE id = %s", (late,)).fetchone()[0] == "pending"
    path = f"/o/{oa}/api/memory/late?prefix=obs:estate"
    for site in ("same-site", "cross-site", None):
        h = {"cookie": sess, **({"sec-fetch-site": site} if site else {})}
        st_s, _, _, _ = call(F, path, headers=h)
        check(f"a GET that WRITES, with the session, Sec-Fetch-Site {site or 'absent'}: no identity (403), the reply "
              "still pending", st_s == 403 and pending(), f"{st_s} pending={pending()}")
    st_s, _, body_s, _ = call(F, path, headers=C)
    check("...the same GET from this origin (same-origin): 200, and the reply is claimed (the control)",
          st_s == 200 and not pending() and "fx-late-reply" in body_s, f"{st_s} pending={pending()}")
    _, _, wn, _ = call(F, f"/o/{oa}/api/whoami", headers={"cookie": sess, "sec-fetch-site": "none"})
    check("a request the viewer typed or bookmarked (Sec-Fetch-Site none) is signed in: whoami says owner",
          json.loads(wn).get("owner") is True, wn[:80])

    print("\nS11 THE COG STREAM")
    s2 = cookies_of(login("owner", headers={"x-forwarded-for": "198.51.100.60"})[1], "astryx_session")
    sess2 = s2[0].split(";")[0] if s2 else ""
    conn = http.client.HTTPConnection("127.0.0.1", F, timeout=30)
    conn.request("GET", "/api/cog/stream", headers={"cookie": sess2, **SO})
    resp = conn.getresponse()

    def next_c(deadline):
        while time.time() < deadline:
            ln = resp.fp.readline().decode()
            if ln.startswith("data: "):
                ev = json.loads(ln[6:])
                if ev.get("org") == oc and ev.get("event", {}).get("type") == "fx_connect":
                    return ev["event"]
        return None
    first = next_c(time.time() + 20)
    check("signed in: the stream's connect to an org carries a token for THAT org, naming the account",
          first is not None and first.get("aud") == oc and first.get("sub") == owner_sub, str(first))
    call(F, "/auth/logout", "POST", b"", headers={"cookie": sess2, **O})
    later = next_c(time.time() + 20)
    if later is not None and later.get("sub"):          # one connect may have raced the sign-out; the next decides
        later = next_c(time.time() + 20)
    check("after sign-out, the stream's next connect carries no identity", later is not None and later.get("sub") is None,
          str(later))
    conn.close()
    conn = http.client.HTTPConnection("127.0.0.1", F, timeout=30)
    conn.request("GET", "/api/cog/stream")
    resp = conn.getresponse()
    anon = next_c(time.time() + 20)
    check("without a session: no identity", anon is not None and anon.get("sub") is None, str(anon))
    conn.close()

    print("\nS7 SIGN-OUT")
    st_o, hso, _, _ = call(F, "/auth/logout", "POST", b"", headers={**C, **O})
    cleared = cookies_of(hso, "astryx_session")
    _, _, wo, _ = call(F, f"/o/{oa}/api/whoami", headers=C)
    st_me, _, _, _ = call(F, "/auth/me", headers=C)
    check("sign-out: 200, the cookie cleared; the old cookie gets no identity and /auth/me is 401",
          st_o == 200 and cleared and json.loads(wo).get("owner") is False and st_me == 401, f"{st_o} {st_me}")
    st_o2, _, _, _ = call(F, "/auth/logout", "POST", b"", headers={**C, **O})
    check("signing out an already-revoked session again: 200 (nothing left to revoke)", st_o2 == 200, f"{st_o2}")

    print("\nS8 D2 AT THE BACKEND")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    A = port["a"]

    def owner_with(tok):
        _, _, w, _ = call(A, "/api/whoami", headers={"x-astryx-identity": tok})
        return json.loads(w).get("owner")
    check("A's own valid token: the owner (the positive control)", owner_with(token(real, owner_sub, oa)) is True)
    check("a token minted for B: the public face", owner_with(token(real, owner_sub, ob)) is False)
    check("an expired token: the public face", owner_with(token(real, owner_sub, oa, iat=int(time.time()) - 300)) is False)
    check("signed by a key the cog never published: the public face",
          owner_with(token(Ed25519PrivateKey.generate(), owner_sub, oa)) is False)

    print("\nS9 A BACKEND'S SET-COOKIE")
    _, hc, _, _ = call(F, f"/o/{oc}/api/cookies")
    got = [c.split("=")[0] for c in cookies_of(hc)]
    check("of the front's session, other orgs' canvas sessions and its own, the browser gets only its own",
          got == [f"cv_session-{oc}"], str(got))
    _, hd, _, _ = call(port["a"], "/canvas/api/cookies")        # A's OWN pipe to its canvas, the front not in between
    got = [c.split("=")[0] for c in cookies_of(hd)]
    check("A's own observatory, piping its canvas: only A's canvas cookie comes back", got == [f"cv_session-{oa}"],
          str(got))

    print("\nS13 AN ORG WITHOUT ITS MEMBERS TABLE")
    with psycopg.connect(da["url"], autocommit=True) as c:     # schema.sql not yet re-applied to this org's database
        c.execute("DROP TABLE members")
    st_w, _, w13, _ = call(A, "/api/whoami", headers={"x-astryx-identity": token(real, owner_sub, oa)})
    st_p, _, _, _ = call(A, "/api/presence", headers={"x-astryx-identity": token(real, owner_sub, oa)})
    check("a valid identity reads as the public face (whoami 200, not owner; an owner route 403), never a 500",
          st_w == 200 and json.loads(w13).get("owner") is False and st_p == 403, f"{st_w} {st_p}")

    print("\nS15 A STORE THE FRONT CAN'T USE")
    st_b, _, _, _ = call(port["badstore"], "/auth/login", "POST", {"email": users["owner"], "password": PW["owner"]},
                         headers=O)
    err = (t / "badstore.err").read_text() if (t / "badstore.err").exists() else ""
    check("a store database named like its role: the sign-in is 503, AND the front's stderr says why",
          st_b == 503 and "sign-in store is unusable" in err, f"{st_b} {err[-200:]}")

    print("\nS10 NO SIGN-IN")
    st_n = [call(port["bare"], p, m, b, headers=O)[0] for p, m, b in
            (("/auth/me", "GET", None), ("/auth/login", "POST", {"email": users["owner"], "password": PW["owner"]}),
             ("/auth/logout", "POST", b""))]
    check("a front whose registry has no cog block: /auth/* is 404", st_n == [404, 404, 404], str(st_n))


def _uid(dbb, email):
    import psycopg
    with psycopg.connect(dbb["url"]) as c:
        return c.execute("SELECT id FROM users WHERE email = %s", (email.lower(),)).fetchone()[0]


if __name__ == "__main__":
    from astryx.security.sqlguard.estate import unavailable
    from astryx.security.sqlguard.fixture import FixtureUnavailable
    try:
        sys.exit(main())
    except FixtureUnavailable as e:          # no admin DSN reachable: NOT SEARCHED (77), never a crash read as a red
        unavailable("test_cog_signin", REPO, e)
