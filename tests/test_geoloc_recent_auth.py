#!/usr/bin/env python3
"""Oracle: geoloc's GET /recent serves location history ONLY to a caller holding GEOLOC_TOKEN,
localhost included (a3 #32078).

    venv/bin/python tests/test_geoloc_recent_auth.py      (also run by nucleus/check.sh)
    GEOLOC_SRC=<path> …                                   (the subject; mutation_probe sets it)

/recent returns the last 20 location fixes: human-personal tier. It let any 127.0.0.1/::1
client in with no token. On this host that means every local process: every agent's Bash, and
every service. Localhost is not an identity.

The subject is bridges/geoloc.py, which is GITIGNORED (the org's geoloc estate). This file is
the tracked, reviewable half: it loads the body by path and exits 77 where the body is absent (a
clean clone), which means NOTHING verified, never a pass.

NO LOCATION DATA TOUCHES THIS TEST. The token and DSN are set EXPLICITLY (a fake token, a DSN
that points nowhere), and the module's pool is a fake that returns no rows and only records that
it was queried. The subject is the AUTH GATE; an unauthorized request must never reach the
query at all. Response bodies are never printed.

  G1 a tokenless request from 127.0.0.1 → 401, and the query is never reached
  G2 ...from ::1 → 401
  G3 ...from a non-local client → 401
  G4 the token by ?token=, X-Token and Bearer → 200 (the query runs)
  G5 a wrong token → 401; an empty ?token= → 401
  G6 the comparison is constant-time (hmac.compare_digest in authorized(), read from the AST)
  G7 authorized() also guards POST /loc, whose JSON "token" can be ANY type: an int, a non-ASCII
     string or a list is a 401, never a 500 (compare_digest raises on those. The first hardened
     version turned all three into 500s, caught by probing before review).
"""
import ast
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("GEOLOC_SRC") or REPO / "bridges" / "geoloc.py")
TOKEN = "t-geoloc-oracle-7f3"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


if not SRC.exists():
    print(f"SKIP: {SRC.relative_to(REPO) if SRC.is_relative_to(REPO) else SRC} is absent "
          f"(gitignored geoloc estate, e.g. a clean clone). Nothing was verified here.")
    sys.exit(77)
try:
    # Via fastapi, the DECLARED dependency (nucleus/deps.conf core), and the framework geoloc itself
    # is written against. It re-exports starlette's TestClient, the same object; importing starlette
    # directly would lean on a transitive dep that the one dep authority doesn't list.
    from fastapi.testclient import TestClient
except Exception as e:  # noqa: BLE001
    print(f"SKIP: fastapi's TestClient is unavailable ({type(e).__name__}). Nothing verified.")
    sys.exit(77)

# The axis under test is set EXPLICITLY, never inherited: a real GEOLOC_TOKEN in the ambient env
# must not decide the verdict.
os.environ["GEOLOC_TOKEN"] = TOKEN
os.environ["GEOLOC_DSN"] = "postgresql://nobody@127.0.0.1:1/none"
sys.path.insert(0, str(SRC.parent))
# An explicit loader: the subject path may not end in .py (a backup, a mutant copy).
from importlib.machinery import SourceFileLoader  # noqa: E402
spec = importlib.util.spec_from_file_location("geoloc_under_test", SRC,
                                              loader=SourceFileLoader("geoloc_under_test", str(SRC)))
geo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(geo)


class FakePool:
    def __init__(self):
        self.queried = 0

    async def fetch(self, *a, **k):
        self.queried += 1
        return []


def get(client_host, path="/recent", headers=None):
    geo.pool = FakePool()
    # No `with`: the app's lifespan (which would open the real DB pool) never runs.
    c = TestClient(geo.app, client=(client_host, 40000))
    r = c.get(path, headers=headers or {})
    return r.status_code, geo.pool.queried


code, q = get("127.0.0.1")
check("G1 tokenless from 127.0.0.1 → 401", code == 401, f"status {code}")
check("G1 ...and the query was never reached", q == 0, f"queried {q}x")
code, q = get("::1")
check("G2 tokenless from ::1 → 401, query unreached", code == 401 and q == 0, f"status {code}, {q}x")
code, q = get("203.0.113.9")
check("G3 tokenless from a non-local client → 401", code == 401 and q == 0, f"status {code}")

for how, path, hdr in (("?token=", f"/recent?token={TOKEN}", None),
                       ("X-Token", "/recent", {"X-Token": TOKEN}),
                       ("Bearer", "/recent", {"Authorization": f"Bearer {TOKEN}"})):
    code, q = get("127.0.0.1", path, hdr)
    check(f"G4 token by {how} → 200, the query runs", code == 200 and q == 1,
          f"status {code}, {q}x")

code, q = get("127.0.0.1", "/recent?token=wrong-token")
check("G5 a wrong token → 401", code == 401 and q == 0, f"status {code}")
code, q = get("127.0.0.1", "/recent?token=")
check("G5 an empty token → 401", code == 401 and q == 0, f"status {code}")

for label, body in (("an int", '{"token": 123, "lat": 1, "lon": 2}'),
                    ("a non-ASCII string", '{"token": "\u00f1", "lat": 1, "lon": 2}'),
                    ("a list", '{"token": ["x"], "lat": 1, "lon": 2}')):
    geo.pool = FakePool()
    c = TestClient(geo.app, client=("203.0.113.9", 40000), raise_server_exceptions=False)
    code = c.post("/loc", content=body, headers={"content-type": "application/json"}).status_code
    check(f"G7 POST /loc with {label} as the token → 401, never 500", code == 401, f"status {code}")

fn = next((n for n in ast.walk(ast.parse(SRC.read_text()))
           if isinstance(n, ast.FunctionDef) and n.name == "authorized"), None)
calls = {getattr(c.func, "attr", getattr(c.func, "id", "")) for c in ast.walk(fn)
         if isinstance(c, ast.Call)} if fn else set()
check("G6 authorized() compares with hmac.compare_digest (constant-time)",
      "compare_digest" in calls, f"calls in authorized(): {sorted(calls)}")

if fails:
    print(f"\nFAIL: {len(fails)} /recent auth invariant(s) broken")
    sys.exit(1)
print("\nPASS: /recent serves location history only to a token holder, localhost included")
