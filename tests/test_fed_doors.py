#!/usr/bin/env python3
"""Oracle for plan-11324 S3e 2/n: the cog's per-org DOORS on the gateway (bridges/gateway.py), DB-FREE.

The gateway is loaded from FED_GATEWAY_SRC (mutation_probe's seam) in a child process and driven through its real
FastAPI app (httpx TestClient, no lifespan: nothing connects, nothing binds). Each org's Ctx gets a FAKE pool holding
that org's own peers and messages, so per-org trust is exactly "which pool the door read". Three children:

  COG, door a   two registry orgs (fxd-a, fxd-b), each HOME's .env its own name, key and url base; a peer P is
                introduced at A only.
    F1 /o/<X>/astryx/identity and the card answer as X, advertising <base>/o/<X>; an org the cog doesn't hold is 404
    F2 the bare root is the DOOR org's (identity and inbox); the other org answers only at its own /o/
    F3 PER-ORG TRUST: P's envelope to seed@A lands in A through /o/A; the same peer at /o/B is 403 (B never met P)
    F4 ADDRESSED: P's envelope to seed@B, posted to A's door, is 403 and lands nowhere (A trusts P; the `to` decides);
       a `to` with two '@' is 403 at the door of the org it ends in
    F5 the per-IP intro cap is the door's, ONE count across orgs: the 6th hello from one IP is 429 whichever /o/
    R0 no org hosts a relay: every /relay/* path is 404 (and on one org that hosts nothing)
  COG, door b hosts the relay (S3e, step 4 live 10-19: the primary's .env sets ASTRYX_RELAY_HOST=1). The door is the
                registry's SECOND org, so "the door" never reads as "the first org".
    R1 /relay/host answers as B with <base>/o/fxd-b; the relay reads B's database only; no /o/<X>/relay/* path
    R2 a non-door org's ASTRYX_RELAY_HOST=1, or any host in a cog with no door, refuses (CogError naming the org)
  COG, no door  the bare root is 404 (identity, inbox); /o/<X> still answers
  ONE ORG       no registry: /o/<name>/… is 404, the root answers as before with the url unchanged, and an envelope
                whose `to` names no '@' still lands at seed (the historic reading, byte for byte)
    R3 one org hosting a relay: /relay/host's url is its bare base (no /o/), on its own database
Exit 0 pass · 1 fail.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_fed_doors', REPO, deps=('asyncpg', 'fastapi', 'nacl', 'httpx'), env=False)   # the gateway's imports: a committed-only tree without them is 77, a live host 1 (seed #60760)
SRC = Path(os.environ.get("FED_GATEWAY_SRC") or REPO / "bridges" / "gateway.py")
fails = []
# EVERY key the gateway reads through _env, set explicitly in each child. On ONE org _env falls back to the checkout's
# .env for an unset key (ESTATE: the tree gateway.py sits in), so in the MAIN checkout an unset key is the LIVE org's
# (10-19 land: ours sets ASTRYX_RELAY_HOST=1, and R0's "one org hosts nothing" read 200). A worktree has no .env, so it
# passed there. Checked against the subject (ONE_ENV, the env each one-org child got): a key the gateway adds and no
# child is given is a FAIL, never a guess.
AXES = {"ASTRYX_RELAY": "", "ASTRYX_RELAY_LISTED": "0", "ASTRYX_RELAY_HOST": "0", "ASTRYX_RELAY_REACH_PRIVATE": "0",
        "ASTRYX_INBOX_RATE": "60", "ASTRYX_RATE_WINDOW": "3600", "ASTRYX_RELAY_BACKOFF": "60"}
ONE_ENV = []                                    # the ASTRYX_* keys of each one-org child's env, as run() built it


def env_keys(src):
    """(keys, bad) of the gateway's _env reads, from its AST, never its spelling (a2 #61438 A-1): every call to the
    name _env whose first argument is a str literal is a key; a call with any other first argument (a variable, an
    f-string, a starred list) and any use of _env that isn't a call (passed on, aliased) is bad, by line. Bad is a
    FAIL, never a skip: a key the test can't name is one no fixture can set."""
    keys, bad, called, tree = set(), [], set(), ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_env":
            called.add(id(n.func))
            a = n.args[0] if n.args else None
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                keys.add(a.value)
            else:
                bad.append(n.lineno)
    bad += [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == "_env" and id(n) not in called]
    return keys, sorted(bad)

CHILD = r"""
import importlib.util, json, sys, time, uuid
from types import SimpleNamespace
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("gateway", src)
gw = importlib.util.module_from_spec(spec); sys.modules["gateway"] = gw; spec.loader.exec_module(gw)
from fastapi.testclient import TestClient
from nacl.encoding import HexEncoder
from nacl.signing import SigningKey


class Pool:
    def __init__(self, peers):
        self.peers, self.msgs, self.relay = dict(peers), [], []
    async def fetchrow(self, q, *a):
        if "FROM peers" in q:
            return self.peers.get(a[0])
        return None
    async def fetchval(self, q, *a):
        return 0
    async def fetch(self, q, *a):
        if "relay_orgs" in q:
            self.relay.append(q.split()[0])        # which org's database the relay read (R1: the door's)
        return []
    async def execute(self, q, *a):
        if q.lstrip().startswith("INSERT INTO messages"):
            self.msgs.append(a)
        elif "INSERT INTO peers" in q:
            self.peers.setdefault(a[0], {"pubkey": a[2], "status": "introduced", "caps_granted": None})
        return "OK"


pk = SigningKey(("c3" * 32).encode(), encoder=HexEncoder)
P = {"pubkey": pk.verify_key.encode(HexEncoder).decode(), "status": "introduced", "caps_granted": None}
c = gw.cog()
out = {"names": sorted(c)}
for n, x in c.items():
    x.pool = Pool({"fxpeer": P, "fxtrust": {**P, "status": "trusted"}} if n in ("fxd-a", "fxone") else {})
cl = TestClient(gw.app)


def env(to, frm="scout@fxpeer"):
    return gw.sign(SimpleNamespace(key=pk), {"astryx": 0, "id": str(uuid.uuid4()), "from": frm, "to": to,
                                              "thread": "fx", "intent": "chat", "body": "hi", "ts": time.time()})


def get(p):
    r = cl.get(p)
    return [r.status_code, r.json() if r.status_code == 200 else None]


def post(p, e):
    return cl.post(p, json=e).status_code


def landed():
    return {n: [m[2] for m in x.pool.msgs] for n, x in c.items()}


for p in ("/astryx/identity", "/o/fxd-a/astryx/identity", "/o/fxd-b/astryx/identity", "/o/fxd-c/astryx/identity",
          "/o/fxone/astryx/identity"):
    out["get " + p] = get(p)
out["card a"] = cl.get("/o/fxd-a/.well-known/agent-card.json").status_code
out["card c"] = cl.get("/o/fxd-c/.well-known/agent-card.json").status_code
out["inbox root to a"] = post("/astryx/inbox", env("seed@fxd-a"))
out["inbox root to one"] = post("/astryx/inbox", env("seed"))
out["after root"] = landed()
out["inbox /o/a to a"] = post("/o/fxd-a/astryx/inbox", env("seed@fxd-a"))
out["inbox /o/b to b"] = post("/o/fxd-b/astryx/inbox", env("seed@fxd-b"))
out["inbox /o/a to b"] = post("/o/fxd-a/astryx/inbox", env("seed@fxd-b"))
out["inbox /o/a to a@b"] = post("/o/fxd-a/astryx/inbox", env("seed@fxd-b@fxd-a"))
out["trusted to forge@a"] = post("/o/fxd-a/astryx/inbox", env("forge@fxd-a", "scout@fxtrust"))
out["inbox /o/c"] = post("/o/fxd-c/astryx/inbox", env("seed@fxd-c"))
out["landed"] = landed()
hello = {"astryx": 0, "org": "fxhello", "pubkey": P["pubkey"], "url": None}
codes = []
for i in range(6):
    h = gw.sign(SimpleNamespace(key=pk), {**hello, "ts": time.time() + i * 1e-3})
    codes.append(post("/o/fxd-a/astryx/introduce" if i % 2 else "/o/fxd-b/astryx/introduce", h))
out["intro codes"] = codes
gw.HOLD = 0                                     # the long-poll returns at once: nothing is pending
ts = str(time.time())
claim = gw.sign(SimpleNamespace(key=pk), {"op": "pickup", "org": "fxpeer", "since": 0, "ts": ts})
for n in ("fxd-a", "fxd-b", "fxd-c"):
    r = cl.get(f"/o/{n}/astryx/pickup", params={"org": "fxpeer", "since": 0, "ts": ts, "sig": claim["sig"]})
    out["pickup " + n] = [r.status_code, r.json() if r.status_code == 200 else None]
for p in ("/relay/host", "/relay/directory", "/o/fxd-a/relay/host", "/o/fxd-b/relay/host"):
    out["get " + p] = get(p)
out["relay read"] = {n: x.pool.relay for n, x in c.items()}
print("OUT " + json.dumps(out, default=str))
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def run(d, door, host=None):
    """One child: door 'a' / None (a cog of two), or 'one' (no registry). `host`: the org ('a', 'b', 'one') whose
    .env (the one org: its environment) sets ASTRYX_RELAY_HOST=1. A child that refuses returns {"refused": tail}."""
    d = Path(d)
    env = {k: v for k, v in os.environ.items() if not k.startswith("ASTRYX_")}
    env["PYTHONPATH"] = os.pathsep.join([str(REPO / "src"), str(REPO), str(REPO / "bridges")])
    keys = {"a": "a1", "b": "b2"}
    if door == "one":
        env.update(AXES, ASTRYX_ORG="fxone", ASTRYX_SECRET_KEY="d4" * 32, ASTRYX_URL="https://one.example/",
                   ASTRYX_DSN="postgresql://fx@127.0.0.1:1/fxdoor_one", ASTRYX_COG_REGISTRY=str(d / "absent.json"),
                   ASTRYX_RELAY_HOST="1" if host == "one" else "0")
        ONE_ENV.append({k for k in env if k.startswith("ASTRYX_")})
    else:
        reg = {"orgs": {}}
        for o in ("a", "b"):
            h = d / f"home-{o}"
            (h / "agents").mkdir(parents=True, exist_ok=True)
            (h / ".env").write_text(f"ASTRYX_DSN=postgresql://fx@127.0.0.1:1/fxdoor_{o}\nASTRYX_ORG=fxd-{o}\n"
                                    f"ASTRYX_SECRET_KEY={keys[o] * 32}\nASTRYX_URL=https://cog.example/\n"
                                    + ("ASTRYX_RELAY_HOST=1\n" if host == o else ""))
            reg["orgs"][o] = {"home": str(h), "db": f"fxdoor_{o}", "door": door == o, "primary": door == o}
        (d / "cog.json").write_text(json.dumps(reg))
        env["ASTRYX_COG_REGISTRY"] = str(d / "cog.json")
    # own-env: both branches of `if door` set ASTRYX_COG_REGISTRY (env.update(…) / env[…] =); the gate can't see a set that only dominates by covering every branch
    r = subprocess.run([sys.executable, "-B", "-c", CHILD, str(SRC)], env=env, cwd=d, capture_output=True, text=True,
                       timeout=120)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("OUT ")), None)
    if not line:
        if host is not None:
            return {"refused": (r.stdout + r.stderr)[-800:]}
        check(f"{door}: the child serves", False, (r.stdout + r.stderr)[-800:])
        return {}
    return json.loads(line[4:])


def main():
    print("S3e 2/n the cog's per-org doors (gateway, DB-free)")

    with tempfile.TemporaryDirectory() as t:
        os.mkdir(f"{t}/door")
        o = run(f"{t}/door", "a")
        if o:
            print("COG, door a")
            ia, ib = o["get /o/fxd-a/astryx/identity"], o["get /o/fxd-b/astryx/identity"]
            check("F1 /o/fxd-a/astryx/identity answers as A, advertising <base>/o/fxd-a",
                  ia[0] == 200 and ia[1]["org"] == "fxd-a" and ia[1]["url"] == "https://cog.example/o/fxd-a", str(ia))
            check("F1 /o/fxd-b/astryx/identity answers as B, with B's own key",
                  ib[0] == 200 and ib[1]["org"] == "fxd-b" and ib[1]["pubkey"] != ia[1]["pubkey"], str(ib))
            check("F1 an org the cog doesn't hold is 404 (identity, card, inbox)",
                  o["get /o/fxd-c/astryx/identity"][0] == 404 and o["card c"] == 404 and o["inbox /o/c"] == 404,
                  f'{o["get /o/fxd-c/astryx/identity"][0]} {o["card c"]} {o["inbox /o/c"]}')
            check("F1 A's card answers at /o/fxd-a", o["card a"] == 200, str(o["card a"]))
            root = o["get /astryx/identity"]
            check("F2 the bare root is the DOOR org's identity", root[0] == 200 and root[1]["org"] == "fxd-a", str(root))
            check("F2 an envelope to seed@A at the bare root lands in A",
                  o["inbox root to a"] == 200 and o["after root"].get("fxd-a") == ["seed"], f'{o["inbox root to a"]} '
                  f'{o["after root"]}')
            check("F2 in a cog, a `to` naming no org is refused at the root (403), nothing lands",
                  o["inbox root to one"] == 403 and len(o["after root"].get("fxd-a", [])) == 1, str(o["inbox root to one"]))
            check("F3 P's envelope to seed@A through /o/fxd-a lands in A", o["inbox /o/a to a"] == 200,
                  str(o["inbox /o/a to a"]))
            check("F3 PER-ORG TRUST: the same peer at /o/fxd-b is 403 (B never met P), nothing in B",
                  o["inbox /o/b to b"] == 403 and o["landed"].get("fxd-b") == [], f'{o["inbox /o/b to b"]} {o["landed"]}')
            check("F3 a TRUSTED peer's forge@fxd-a lands at A's forge (the agent read through split_to)",
                  o["trusted to forge@a"] == 200 and o["landed"].get("fxd-a", [])[-1:] == ["forge"],
                  f'{o["trusted to forge@a"]} {o["landed"]}')
            check("F4 ADDRESSED: P's seed@B posted to A's door is 403, and A holds only its three",
                  o["inbox /o/a to b"] == 403 and len(o["landed"].get("fxd-a", [])) == 3, f'{o["inbox /o/a to b"]} '
                  f'{o["landed"]}')
            check("F4 a `to` with two '@' (seed@fxd-b@fxd-a) is 403 at A's door", o["inbox /o/a to a@b"] == 403,
                  str(o["inbox /o/a to a@b"]))
            check("F5 the per-IP intro cap is ONE count across orgs: 5 answered, the 6th is 429",
                  o["intro codes"][-1] == 429 and 429 not in o["intro codes"][:5], str(o["intro codes"]))
            check("R0 no org hosts a relay: every /relay/* path is 404 (bare and /o/)",
                  [o[f"get {p}"][0] for p in ("/relay/host", "/relay/directory", "/o/fxd-a/relay/host")] == [404] * 3,
                  str([o[f"get {p}"] for p in ("/relay/host", "/relay/directory")]))
            check("F3 pickup: P collects at /o/fxd-a (200, nothing pending), is 403 at /o/fxd-b, 404 at /o/fxd-c",
                  o["pickup fxd-a"] == [200, {"envelopes": []}] and o["pickup fxd-b"][0] == 403
                  and o["pickup fxd-c"][0] == 404, f'{o["pickup fxd-a"]} {o["pickup fxd-b"]} {o["pickup fxd-c"]}')
        os.mkdir(f"{t}/host")
        o = run(f"{t}/host", "b", host="b")       # the door is the registry's SECOND org: never "the first one"
        print("COG, door b hosts the relay (its .env: ASTRYX_RELAY_HOST=1, the live primary's)")
        if "refused" in o:
            check("R1 the cog serves a relay-hosting door org", False, o["refused"])
        else:
            h = o["get /relay/host"]
            check("R1 the cog serves a relay-hosting door org: /relay/host answers as B, url <base>/o/fxd-b",
                  h[0] == 200 and h[1] == {"org": "fxd-b", "pubkey": o["get /o/fxd-b/astryx/identity"][1]["pubkey"],
                                           "url": "https://cog.example/o/fxd-b"}, str(h))
            check("R1 the relay reads the DOOR's database, never the sibling's (A, the registry's first)",
                  o["get /relay/directory"] == [200, {"orgs": []}] and o["relay read"] == {"fxd-a": [],
                                                                                            "fxd-b": ["SELECT"]},
                  f'{o["get /relay/directory"]} {o["relay read"]}')
            check("R1 the relay is the bare root's: no /o/<X>/relay/* path (404)",
                  o["get /o/fxd-a/relay/host"][0] == 404 and o["get /o/fxd-b/relay/host"][0] == 404,
                  f'{o["get /o/fxd-a/relay/host"]} {o["get /o/fxd-b/relay/host"]}')
            check("R1 the doors are unchanged beside it (B's identity at the root, A's at /o/fxd-a)",
                  o["get /astryx/identity"][1]["org"] == "fxd-b" and o["get /o/fxd-a/astryx/identity"][1]["org"]
                  == "fxd-a", str(o["get /astryx/identity"]))
        os.mkdir(f"{t}/hostb")
        o = run(f"{t}/hostb", "b", host="a")
        check("R2 a NON-door org's ASTRYX_RELAY_HOST=1 refuses (CogError naming the org and the rule)",
              "CogError" in o.get("refused", "") and "cog org a:" in o["refused"] and "door org" in o["refused"],
              str(o)[-300:])
        os.mkdir(f"{t}/hostnodoor")
        o = run(f"{t}/hostnodoor", None, host="a")
        check("R2 a cog with NO door refuses a relay host (no bare path to serve it on)",
              "CogError" in o.get("refused", "") and "cog org a:" in o["refused"] and "door" in o["refused"], str(o)[-300:])
        os.mkdir(f"{t}/nodoor")
        o = run(f"{t}/nodoor", None)
        if o:
            print("COG, no door")
            check("the bare root is 404 (identity, inbox)",
                  o["get /astryx/identity"][0] == 404 and o["inbox root to a"] == 404,
                  f'{o["get /astryx/identity"][0]} {o["inbox root to a"]}')
            check("/o/fxd-a still answers as A", o["get /o/fxd-a/astryx/identity"][0] == 200)
        os.mkdir(f"{t}/one")
        o = run(f"{t}/one", "one")
        if o:
            print("ONE ORG")
            root = o["get /astryx/identity"]
            check("the root answers as the org, the url its base unchanged",
                  root[0] == 200 and root[1]["org"] == "fxone" and root[1]["url"] == "https://one.example/", str(root))
            check("one org has no /o/ doors (its own name included): 404",
                  o["get /o/fxone/astryx/identity"][0] == 404, str(o["get /o/fxone/astryx/identity"]))
            check("a `to` naming no '@' still lands at seed (the historic reading)",
                  o["inbox root to one"] == 200 and o["landed"].get("fxone", [])[:2] == ["seed", "seed"],
                  f'{o["inbox root to one"]} {o["landed"]}')
            check("R0 one org that hosts nothing mounts no relay (404)", o["get /relay/host"][0] == 404,
                  str(o["get /relay/host"]))
        os.mkdir(f"{t}/onehost")
        o = run(f"{t}/onehost", "one", host="one")
        if "refused" in o:
            check("R3 one org hosting a relay serves it", False, o["refused"])
        else:
            print("ONE ORG hosting a relay")
            check("R3 /relay/host answers as the org, the url its base unchanged (no /o/)",
                  o["get /relay/host"] == [200, {"org": "fxone", "pubkey": o["get /astryx/identity"][1]["pubkey"],
                                                 "url": "https://one.example/"}], str(o["get /relay/host"]))
            check("R3 the relay reads the org's database", o["get /relay/directory"] == [200, {"orgs": []}]
                  and o["relay read"] == {"fxone": ["SELECT"]}, f'{o["get /relay/directory"]} {o["relay read"]}')
    read, bad = env_keys(SRC.read_text())
    check("every key the gateway reads through _env is set in each one-org child (none falls back to a checkout .env)",
          bool(read) and not bad and len(ONE_ENV) == 2 and all(read <= e for e in ONE_ENV),
          f"unset: {[sorted(read - e) for e in ONE_ENV]}, _env not on a literal key at lines {bad}")
    print(f"{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
