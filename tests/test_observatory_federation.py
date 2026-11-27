#!/usr/bin/env python3
"""Oracle: cog-rebuild Phase 4, the observatory's FEDERATION routes (observatory/api/federation.py).
In-process: the app's lifespan runs on a throwaway fixture database (fixture_db); the home is a temp dir whose .env holds
a fresh test key and the fixture DSN; the gateway port is 9 (nothing answers); the peer introduced is a FAKE gateway on
loopback (a thread in this process), so nothing leaves the host and the live org is never read or written.
  - G  GATE: every (method, path) the module serves is 403 to a visitor (HEAD and OPTIONS too); none is a PUBLIC pair;
       the public GET /api/peers keeps its three columns.
  - ID identity: name, mode 'none' with no ASTRYX_URL/RELAY, the down gateway reported as unreachable, peer counts.
  - P  peers: empty, then the seeded set with the wire's counts per peer (in, out, pending, dead), last contact, and
       NO message body anywhere in the listing.
  - M  a peer's messages: both directions with bodies for the owner; none for a stranger name; a bad name 400.
  - T  trust transitions: trust/untrust/block/unblock each move one row and write one audit row to seed; a repeat is a
       409 that writes nothing; a keyless stranger can't be trusted; an absent peer 404; an unknown action 400.
  - I  introduce: malformed targets are 400 BEFORE any network call; a good url runs introduce.introduce in a CHILD
       process (introduce_run.py: the signed reply verified, the row stored as `introduced`, an audit row written); a
       forged signature is 502 and stores nothing; a relay name with no ASTRYX_RELAY is 502 with introduce.py's words.
  - K  the secret key: federation.py imports nothing that loads it (no introduce module, no load_env, no
       ASTRYX_SECRET_KEY, no nacl), and after every route ran, astryx.federation.introduce was never imported here.
  - W  the peers counts cover the last 30 days: an older cross-org message counts for nobody.
  - D  ASTRYX_DEV_NO_WIRE: every POST here is refused (503) and writes nothing."""
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_observatory_federation", REPO, deps=("fastapi", "httpx", "asyncpg", "psycopg", "nacl"), env=False)
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402

SUBJECT = Path(os.environ.get("FED_OBS_SRC") or REPO / "observatory" / "api" / "federation.py")
O = {"x-obs-key": "test-owner-key"}
ME = "fixture.example"
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def seed(url: str):
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        for org, st, pub in (("alpha.example", "introduced", "a1" * 32), ("beta.example", "trusted", "b2" * 32),
                             ("gamma.example", "revoked", "c3" * 32), ("stranger.example", "stranger", None)):
            c.execute("INSERT INTO peers (org, url, pubkey, status) VALUES (%s, %s, %s, %s)",
                      (org, f"http://{org}:8845" if org != "beta.example" else None, pub, st))

        def m(fo, fa, to, ta, status="delivered", body="fixture body"):
            c.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, intent, body, status) "
                      "VALUES (%s,%s,%s,%s,'chat',%s,%s)", (fa, fo, ta, to, body, status))
        m("alpha.example", "seed", "local", "seed", body="SECRET-IN-1")
        m("alpha.example", "db", "local", "seed", body="SECRET-IN-2")
        m("local", "seed", "alpha.example", "seed", status="pending", body="SECRET-OUT-1")
        m("local", "seed", "alpha.example", "seed", status="dead", body="SECRET-OUT-2")
        m("local", "seed", "beta.example", "seed", body="SECRET-OUT-3")
        m("local", "seed", "local", "db", body="local only")                       # never a peer's traffic
        c.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, intent, body, ts) VALUES "
                  "('seed', 'alpha.example', 'seed', 'local', 'chat', 'old', now() - interval '40 days')")  # outside 30 d


def audits(url: str) -> int:
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        return c.execute("SELECT count(*) FROM messages WHERE intent = 'federation' AND to_agent = 'seed'").fetchone()[0]


def status_of(url: str, org: str):
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        r = c.execute("SELECT status FROM peers WHERE org = %s", (org,)).fetchone()
    return r and r[0]


def signed(sk, d: dict) -> dict:
    """A gateway's signed hello, built here (not by introduce.py, which this process must never import)."""
    import json
    body = json.dumps({k: v for k, v in d.items() if k != "sig"}, sort_keys=True, separators=(",", ":")).encode()
    return {**d, "sig": sk.sign(body).signature.hex()}


class FakeGateway:
    """A peer's /astryx/introduce on loopback: mode 'good' answers a signed hello, 'forged' one altered after signing,
    'refuse' a 403. Every request is counted."""
    def __init__(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from nacl.encoding import HexEncoder
        from nacl.signing import SigningKey
        self.sk, self.mode, self.hits = SigningKey.generate(), "good", []
        me = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("content-length") or 0)
                me.hits.append((self.path, json.loads(self.rfile.read(n) or b"{}")))
                if me.mode == "refuse":
                    self.send_response(403); self.end_headers(); self.wfile.write(b"no"); return
                d = signed(me.sk, {"astryx": 0, "org": "delta.example", "url": "http://delta.example:8845",
                                   "pubkey": me.sk.verify_key.encode(HexEncoder).decode(), "ts": time.time(), "reply": True})
                if me.mode == "forged":
                    d["org"] = "zeta.example"
                b = json.dumps(d).encode()
                self.send_response(200); self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


def main(tmp: Path, url: str):
    from nacl.encoding import HexEncoder
    from nacl.signing import SigningKey
    import observatory.api  # noqa: F401
    spec = importlib.util.spec_from_file_location("observatory.api.federation", SUBJECT)
    fed = importlib.util.module_from_spec(spec)
    sys.modules["observatory.api.federation"] = fed
    spec.loader.exec_module(fed)
    mspec = importlib.util.spec_from_file_location("main", REPO / "observatory" / "api" / "main.py")
    obs = importlib.util.module_from_spec(mspec)
    sys.modules["main"] = obs
    mspec.loader.exec_module(obs)
    from fastapi.testclient import TestClient
    from fastapi.routing import APIRoute

    home = tmp / "home"
    home.mkdir()
    key = SigningKey.generate().encode(HexEncoder).decode()
    (home / ".env").write_text(f"ASTRYX_ORG={ME}\nASTRYX_SECRET_KEY={key}\nASTRYX_DSN={url}\n")
    envd = {"ASTRYX_GATEWAY_PORT": "9"}                       # never the live home's .env (main._env's fallback)
    fed.bind(lambda: obs.pool, home, owner=lambda r: obs.owner_call(r), env=lambda k: envd.get(k, ""), me=lambda: ME)
    gw = FakeGateway()

    cl = TestClient(obs.app, raise_server_exceptions=False)
    cl.__enter__()
    try:
        # ── G the gate ──────────────────────────────────────────────────────────────────────────────────────────
        served = [(m, r.path) for r in fed.router.routes if isinstance(r, APIRoute) for m in sorted(r.methods)]
        arm("G the module serves its five routes, all under /api/federation/",
            len(served) == 5 and all(p.startswith("/api/federation/") for _, p in served), served)
        arm("G no federation route is a PUBLIC pair", not [x for x in served if x in obs.PUBLIC])
        concrete = [(m, p.replace("{org}", "alpha.example")) for m, p in served]
        leaks = [f"{m} {p} -> {c}" for m, p in concrete + [("HEAD", p) for _, p in concrete] + [("OPTIONS", p) for _, p in concrete]
                 if (c := cl.request(m, p, json={"url": "http://x.example", "action": "trust"}).status_code) != 403]
        arm("G every route is 403 to a visitor (HEAD, OPTIONS too)", not leaks, leaks)
        arm("G a visitor's POST trust changed nothing (no peers row yet, no audit)", audits(url) == 0)

        # ── ID / P on an empty table ────────────────────────────────────────────────────────────────────────────
        r = cl.get("/api/federation/identity", headers=O)
        j = r.json() if r.status_code == 200 else {}
        arm("ID identity answers the owner", r.status_code == 200, r.text[:200])
        arm("ID mode 'none' with neither ASTRYX_URL nor ASTRYX_RELAY", j.get("mode") == "none" and j.get("org") == ME, j)
        arm("ID the down gateway (port 9) is unreachable, not an error",
            j.get("gateway", {}).get("reachable") is False and j.get("gateway", {}).get("as_us") is False, j)
        arm("ID no secret leaves (no key material beyond a public fingerprint)", key not in r.text)
        arm("ID zero peers counted", j.get("peers", {}).get("total") == 0, j)
        r = cl.get("/api/federation/peers", headers=O)
        arm("P an empty peers table lists nobody", r.status_code == 200 and r.json().get("peers") == [], r.text[:200])

        seed(url)
        # ── P listing ───────────────────────────────────────────────────────────────────────────────────────────
        r = cl.get("/api/federation/peers", headers=O)
        ps = {p["org"]: p for p in r.json().get("peers", [])} if r.status_code == 200 else {}
        arm("P all four peers listed", set(ps) == {"alpha.example", "beta.example", "gamma.example", "stranger.example"}, list(ps))
        a = ps.get("alpha.example", {})
        arm("P alpha's wire counts: 2 in, 2 out (1 pending, 1 dead)",
            a.get("traffic") == {"in": 2, "out": 2, "out_pending": 1, "out_dead": 1}, a.get("traffic"))
        arm("P beta: 0 in, 1 out; polls us (no url)", ps.get("beta.example", {}).get("traffic", {}).get("out") == 1
            and ps["beta.example"]["traffic"]["in"] == 0 and ps["beta.example"]["mode"] == "polls us", ps.get("beta.example"))
        arm("P the stranger has no traffic and no last contact", ps.get("stranger.example", {}).get("last_contact") is None
            and ps["stranger.example"]["traffic"]["in"] == 0, ps.get("stranger.example"))
        arm("P alpha has a last contact and a fingerprint", bool(a.get("last_contact")) and a.get("fingerprint") == "a1a1:a1a1:a1a1:a1a1", a)
        arm("P revoked is labelled 'blocked' and sorts last", ps.get("gamma.example", {}).get("label") == "blocked"
            and r.json()["peers"][-1]["org"] == "gamma.example", [p["org"] for p in r.json()["peers"]])
        arm("P the listing carries NO message body", "SECRET-" not in r.text and "fixture body" not in r.text)
        arm("P the local-only message counts for nobody", sum(p["traffic"]["in"] + p["traffic"]["out"] for p in ps.values()) == 5)
        arm("W a 40-day-old message from alpha is outside the 30-day counts", a.get("traffic", {}).get("in") == 2
            and r.json().get("window_days") == 30, a.get("traffic"))
        arm("P anonymous: 403 on the listing", cl.get("/api/federation/peers").status_code == 403)
        pub = cl.get("/api/peers")
        arm("P the PUBLIC /api/peers still shows only org, status, reputation",
            pub.status_code == 200 and all(set(x) == {"org", "status", "reputation"} for x in pub.json()), pub.text[:200])
        j = cl.get("/api/federation/identity", headers=O).json()
        arm("ID counts after seeding: 4 total, 1 trusted, 1 introduced, 1 blocked",
            j.get("peers") == {"total": 4, "trusted": 1, "introduced": 1, "blocked": 1}, j.get("peers"))

        # ── M a peer's messages ─────────────────────────────────────────────────────────────────────────────────
        r = cl.get("/api/federation/peers/alpha.example/messages", headers=O)
        ms = r.json().get("messages", []) if r.status_code == 200 else []
        arm("M alpha's traffic both ways (the 40-day-old one too: this view is not windowed), bodies for the owner", len(ms) == 5 and {x["inbound"] for x in ms} == {True, False}
            and any(x["body"] == "SECRET-IN-1" for x in ms), ms)
        r = cl.get("/api/federation/peers/nobody.example/messages", headers=O)
        arm("M a name with no traffic answers empty", r.status_code == 200 and r.json().get("messages") == [], r.text[:200])
        arm("M a bad name is 400", cl.get("/api/federation/peers/..%2Fx/messages", headers=O).status_code in (400, 404))
        arm("M limit is honoured", len(cl.get("/api/federation/peers/alpha.example/messages?limit=1", headers=O).json()["messages"]) == 1)
        arm("M anonymous: 403, no body", (x := cl.get("/api/federation/peers/alpha.example/messages")).status_code == 403
            and "SECRET" not in x.text)

        # ── T transitions ───────────────────────────────────────────────────────────────────────────────────────
        def act(org, action):
            return cl.post(f"/api/federation/peers/{org}/status", headers=O, json={"action": action})
        n0 = audits(url)
        r = act("alpha.example", "trust")
        arm("T trust: introduced → trusted", r.status_code == 200 and status_of(url, "alpha.example") == "trusted"
            and r.json().get("from") == "introduced", r.text[:200])
        arm("T trust wrote one audit row to seed", audits(url) == n0 + 1)
        r = act("alpha.example", "trust")
        arm("T trust again is a 409 that writes nothing", r.status_code == 409 and audits(url) == n0 + 1, r.text[:200])
        r = act("alpha.example", "untrust")
        arm("T untrust: trusted → introduced", r.status_code == 200 and status_of(url, "alpha.example") == "introduced", r.text[:200])
        r = act("alpha.example", "block")
        arm("T block: introduced → revoked", r.status_code == 200 and status_of(url, "alpha.example") == "revoked"
            and r.json().get("label") == "blocked", r.text[:200])
        r = act("alpha.example", "trust")
        arm("T a blocked peer can't be trusted directly (409)", r.status_code == 409 and status_of(url, "alpha.example") == "revoked")
        r = act("alpha.example", "unblock")
        arm("T unblock: revoked → introduced", r.status_code == 200 and status_of(url, "alpha.example") == "introduced", r.text[:200])
        arm("T four moves, four audit rows", audits(url) == n0 + 4, audits(url) - n0)
        r = act("stranger.example", "trust")
        arm("T a keyless stranger can't be trusted (409, no key)", r.status_code == 409 and status_of(url, "stranger.example") == "stranger", r.text[:200])
        r = act("stranger.example", "block")
        arm("T a stranger can be blocked", r.status_code == 200 and status_of(url, "stranger.example") == "revoked")
        arm("T an absent peer is 404", act("nobody.example", "trust").status_code == 404)
        arm("T an unknown action is 400", act("alpha.example", "promote").status_code == 400)
        arm("T anonymous trust is 403 and moves nothing",
            cl.post("/api/federation/peers/beta.example/status", json={"action": "untrust"}).status_code == 403
            and status_of(url, "beta.example") == "trusted")

        # ── I introduce ─────────────────────────────────────────────────────────────────────────────────────────
        bad = ["", "   ", "ftp://x.example", "http://", "http://u:p@x.example", "http://x.example/?q=1", "http://x.example/#f",
               "javascript:alert(1)", "http://x.example/evil/path", "a b", "../etc", "http://x.example:99999",
               "http://x\n.example", "local", "x" * 400, gw.base + "/?q=1", gw.base.replace("//", "//u:p@"),
               "-h", "--env=/etc/passwd"]
        codes = {b[:30]: cl.post("/api/federation/introduce", headers=O, json={"url": b}).status_code for b in bad}
        arm("I every malformed target is 400", all(c == 400 for c in codes.values()), codes)
        arm("I ... and none reached the network", not gw.hits, gw.hits)

        n1 = audits(url)
        r = cl.post("/api/federation/introduce", headers=O, json={"url": gw.base + "/"})
        seen = gw.hits
        arm("I a good url: the child ran introduce.introduce (one hello, signed by OUR key, to /astryx/introduce)",
            len(seen) == 1 and seen[0][0] == "/astryx/introduce" and seen[0][1].get("org") == ME
            and seen[0][1].get("pubkey") == SigningKey(key.encode(), encoder=HexEncoder).verify_key.encode(HexEncoder).decode()
            and seen[0][1].get("sig"), seen)
        arm("I the outcome names the peer", r.status_code == 200 and r.json().get("org") == "delta.example"
            and r.json().get("via") == "url", r.text[:200])
        arm("I stored as `introduced`", status_of(url, "delta.example") == "introduced")
        arm("I one audit row", audits(url) == n1 + 1)
        arm("I the hello never echoed our secret key", key not in r.text)

        gw.mode = "forged"                                              # org changed after signing
        r = cl.post("/api/federation/introduce", headers=O, json={"url": gw.base})
        arm("I a forged reply is 502 and stores nothing", r.status_code == 502 and status_of(url, "zeta.example") is None
            and audits(url) == n1 + 1, r.text[:200])
        gw.mode = "refuse"
        r = cl.post("/api/federation/introduce", headers=O, json={"url": gw.base + "/o/eta"})
        arm("I a refused introduction is 502 with introduce.py's words", r.status_code == 502
            and "refused" in r.json().get("error", ""), r.text[:200])
        r = cl.post("/api/federation/introduce", headers=O, json={"url": "theta.example"})
        arm("I a relay name with no ASTRYX_RELAY: 502, introduce.py's own words", r.status_code == 502
            and "ASTRYX_RELAY" in r.json().get("error", ""), r.text[:200])

        # ── D dev server ────────────────────────────────────────────────────────────────────────────────────────
        obs._DEV_NO_WIRE = True
        n2 = audits(url)
        r1 = act("beta.example", "untrust")
        r2 = cl.post("/api/federation/introduce", headers=O, json={"url": "http://iota.example"})
        obs._DEV_NO_WIRE = False
        arm("D under ASTRYX_DEV_NO_WIRE every POST is 503 and writes nothing",
            r1.status_code == 503 and r2.status_code == 503 and status_of(url, "beta.example") == "trusted"
            and audits(url) == n2, (r1.status_code, r2.status_code))
        arm("D GETs still answer", cl.get("/api/federation/peers", headers=O).status_code == 200)

        # ── K the secret key never enters this process ───────────────────────────────────────────────────────────
        import ast
        tree = ast.parse(SUBJECT.read_text())
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {
            f"{n.module}.{a.name}" if n.module else a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        code_strs = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                     and not n.value.lstrip().startswith(('"', "astryx observatory"))]
        arm("K federation.py imports no introduce module and no signing library",
            not [i for i in imported if "introduce" in i or i.startswith("nacl")], sorted(imported))
        arm("K federation.py names no secret-key loader (load_env, SigningKey, _key)",
            not ({"load_env", "SigningKey", "_key", "read_env"} & names), sorted({"load_env", "SigningKey", "_key", "read_env"} & names))
        arm("K federation.py's code never names ASTRYX_SECRET_KEY",
            not [x for x in code_strs if "ASTRYX_SECRET_KEY" in x and len(x) < 200])
        arm("K after every route ran, astryx.federation.introduce was never imported in the observatory's process",
            "astryx.federation.introduce" not in sys.modules)
    finally:
        gw.srv.shutdown()
        cl.__exit__(None, None, None)


if __name__ == "__main__":
    t0 = time.time()
    try:
        with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
            os.environ["ASTRYX_DSN"] = fx["url"]
            os.environ["OBS_KEY"] = "test-owner-key"
            os.environ["ASTRYX_ORG"] = ME
            os.environ["ASTRYX_GATEWAY_PORT"] = "9"
            os.environ.setdefault("ASTRYX_COG_REGISTRY", str(Path(td) / "absent.json"))
            main(Path(td), fx["url"])
    except FixtureUnavailable as e:
        from astryx.security.sqlguard.estate import unavailable
        unavailable("test_observatory_federation", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: observatory federation ({fails} failing, {time.time() - t0:.1f}s)")
    sys.exit(1 if fails else 0)
