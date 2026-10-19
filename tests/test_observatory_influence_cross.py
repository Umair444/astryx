#!/usr/bin/env python3
"""Oracle: GET /api/influence/cross, the traffic across this org's boundary (the owner, 10-19: "in cogs orgs can also
communicate with each other … connect those too via influence graph"). The floor and the network draw org <-> org and
agent <-> agent edges to the cog's siblings from it. On a throwaway fixture database (sqlguard's stamped fixture_db),
the API in process (TestClient):

  X1 no key or a wrong key: 403; a window other than 7d/14d: 400
  X2 no crossing traffic: edges [] (the WHERE seen at 0 rows)
  X3 crossing traffic only, aggregated per (from, from_org, to, to_org) with n and the last time, `local`
     read as this org's federation name; a message inside this org is never an edge
  X4 aggregate-only: no body, thread or id leaves (the planted secret body and thread are nowhere in the answer)
  X5 the window cuts by time: 14d keeps a 10-day-old crossing, 7d drops it
Seam: OBS_MAIN_SRC (a mutant main.py). Exit 0 · 1 · 77.
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = Path(os.environ.get("OBS_MAIN_SRC") or REPO / "observatory" / "api" / "main.py")
sys.path.insert(0, str(REPO))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_observatory_influence_cross', REPO, deps=('psycopg', 'asyncpg', 'fastapi'), env=False)   # a worktree: the admin DSN by env
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

fails = 0
O = {"x-obs-key": "test-owner-key"}
ME, LAB = "fixture.example", "lab.fixture.example"


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def main(url, tmp):
    import psycopg
    sys.path.insert(0, str(REPO / "observatory" / "api"))
    subject = SUBJECT
    if os.environ.get("OBS_MAIN_SRC"):              # seated where paths.estate() places a code-tree file
        subject = tmp / "subject" / "observatory" / "api" / "main.py"
        subject.parent.mkdir(parents=True)
        subject.write_text(SUBJECT.read_text())
    spec = importlib.util.spec_from_file_location("main", subject)
    obs = importlib.util.module_from_spec(spec)
    sys.modules["main"] = obs
    spec.loader.exec_module(obs)
    from fastapi.testclient import TestClient

    with psycopg.connect(url, autocommit=True) as c, TestClient(obs.app) as cl:
        def put(frm, fo, to, to_o, days=0, body="hello", thread="t-1"):
            c.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body, ts) "
                      "VALUES (%s, %s, %s, %s, %s, 'task', %s, now() - make_interval(days => %s))",
                      (frm, fo, to, to_o, thread, body, days))

        print("X1 OWNER ONLY, TWO WINDOWS")
        arm("no key: 403", cl.get("/api/influence/cross").status_code == 403)
        arm("a wrong key: 403", cl.get("/api/influence/cross", headers={"x-obs-key": "nope"}).status_code == 403)
        arm("window 30d: 400", cl.get("/api/influence/cross?window=30d", headers=O).status_code == 400)

        print("\nX2 NO CROSSING TRAFFIC")
        put("seed", "local", "forge", "local")                    # inside this org
        put("forge", "local", "seed", "local")
        j = cl.get("/api/influence/cross", headers=O).json()
        arm("edges [] and the org named", j.get("edges") == [] and j.get("org") == ME, j)

        print("\nX3 CROSSING TRAFFIC, AGGREGATED")
        put("seed", "local", "seed", LAB, body="SECRET-BODY-1", thread="SECRET-THREAD")
        put("seed", "local", "seed", LAB)
        put("seed", LAB, "seed", "local")                        # lab's seed wrote to ours (the inbound copy)
        put("forge", "local", "scout", "peer.example.org", days=10)
        j = cl.get("/api/influence/cross", headers=O).json()
        got = {(e["from"], e["from_org"], e["to"], e["to_org"]): e["n"] for e in j.get("edges", [])}
        arm("seed -> seed@lab twice, lab's seed -> seed once, the 10-day peer edge once; nothing inside the org",
            got == {("seed", ME, "seed", LAB): 2, ("seed", LAB, "seed", ME): 1, ("forge", ME, "scout", "peer.example.org"): 1}, got)
        arm("each edge carries its last time", all(e.get("last_ts") for e in j.get("edges", [])), j)

        print("\nX4 AGGREGATE ONLY")
        r = cl.get("/api/influence/cross", headers=O)
        arm("no body, thread or id leaves", "SECRET" not in r.text and all(
            set(e) == {"from", "from_org", "to", "to_org", "n", "last_ts"} for e in r.json()["edges"]), r.text[:300])

        print("\nX5 THE WINDOW")
        j7 = cl.get("/api/influence/cross?window=7d", headers=O).json()
        arm("7d drops the 10-day crossing, keeps the rest",
            {(e["from"], e["to_org"]) for e in j7["edges"]} == {("seed", LAB), ("seed", ME)}, j7)


if __name__ == "__main__":
    from astryx.security.sqlguard.estate import unavailable
    from astryx.security.sqlguard.fixture import FixtureUnavailable
    with tempfile.TemporaryDirectory() as td:
        # never the host's /etc registry (a host in a cog has one): one org, before anything resolves a HOME
        os.environ["ASTRYX_COG_REGISTRY"] = str(Path(td) / "absent.json")
        try:
            with fixture_db() as fx:
                os.environ["ASTRYX_DSN"] = fx["url"]
                os.environ["OBS_KEY"] = "test-owner-key"
                os.environ["ASTRYX_ORG"] = ME
                os.environ["ASTRYX_GATEWAY_PORT"] = "9"          # discard: a real gateway is never asked
                main(fx["url"], Path(td))
        except FixtureUnavailable as e:                          # no admin DSN here: NOT SEARCHED, or BROKEN on a live host
            unavailable("test_observatory_influence_cross", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: observatory influence across orgs ({fails} failing)")
    sys.exit(1 if fails else 0)
