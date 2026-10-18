#!/usr/bin/env python3
"""Oracle: the floor's two owner routes (seed #60078, goal 11324): GET /api/influence (who knows whom) and GET /api/cog
(the cog's rooms, owner ruling #60083). On a throwaway fixture database, with the API in-process:
  - INFLUENCE (design #60089): one edge per (src, dst, kind) with its count n, its LAST time and its top threads
    (<= 3, by count); the window cuts by the edge's time (7d drops a 10-day edge, 14d keeps it; anything else is
    400); every kind is listed with its coverage, and one under the coverage floor reads measured=false (shown, never
    hidden); the ranks come from ONE compute (the latest), never an agent's own latest from an older run; an edge
    never carries its authority ref out;
  - COG: an ABSENT registry is a cog of one room, this org's, named, with the gateway pubkey's badge; a planted
    two-org registry is two rooms, ours marked `this`, with no home or database in the answer; a registry that
    refuses is a 500, never a quiet one-room answer;
  - GATE: no key or a wrong key is 403 on both.
The registry is planted PER REQUEST (ASTRYX_ORG_REGISTRY), never at import: a two-org registry at import makes
orgs.multi() true and paths.estate() refuses the unregistered checkout before main.py loads.
The subject is OBS_MAIN_SRC (a mutated copy; tests/mutants_observatory_floor.py), else the real main.py.
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = Path(os.environ.get("OBS_MAIN_SRC") or REPO / "observatory" / "api" / "main.py")
sys.path.insert(0, str(REPO))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_observatory_floor', REPO, deps=('psycopg', 'asyncpg', 'fastapi'))
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

fails = 0
O = {"x-obs-key": "test-owner-key"}


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def main(url, tmp):
    import psycopg
    sys.path.insert(0, str(REPO / "observatory" / "api"))
    subject = SUBJECT
    if os.environ.get("OBS_MAIN_SRC"):
        # a mutant copy sits wherever the probe wrote it, and paths.estate() places a file only by its path in the code
        # tree (a bare copy is NoHome, and every mutant "died" at import: a4 #60129 R-1). Seat it at
        # <tmp>/observatory/api/main.py, a tree the resolver accepts, so the mutant itself is what runs.
        subject = tmp / "subject" / "observatory" / "api" / "main.py"
        subject.parent.mkdir(parents=True)
        subject.write_text(SUBJECT.read_text())
    spec = importlib.util.spec_from_file_location("main", subject)
    obs = importlib.util.module_from_spec(spec)
    sys.modules["main"] = obs
    spec.loader.exec_module(obs)
    from fastapi.testclient import TestClient

    with TestClient(obs.app) as cl0:
        j = cl0.get("/api/influence", headers=O).json()
        arm("INFLUENCE: an empty cache is no edges, no nodes, no computed_at (the floor's honest empty state)",
            j["edges"] == [] and j["nodes"] == [] and j["computed_at"] is None, j)

    with psycopg.connect(url, autocommit=True) as c:
        def edge(kind, src, dst, days, cov, topic):
            c.execute("INSERT INTO influence_edge (scope, kind, src, dst, ts, ask_ts, ref, topic, coverage, computed_at) "
                      "VALUES ('local', %s, %s, %s, now() - make_interval(days => %s), now() - make_interval(days => %s), "
                      "'#424242', %s, %s, now())", (kind, src, dst, days, days, topic, cov))

        def value(agent, v, hours_ago):
            c.execute("INSERT INTO influence_value (scope, view, agent, value, unmapped, computed_at) VALUES "
                      "('local', 'global', %s, %s, 0, date_trunc('hour', now()) - make_interval(hours => %s))",
                      (agent, v, hours_ago))

        for days, topic in ((1, "t-1"), (2, "t-1"), (3, "t-3"), (4, "t-2"), (5, "t-4"), (5, None)):
            edge("delegation", "ann", "bob", days, 0.9, topic)
        edge("pass_land", "ann", "bob", 2, 0.8, "plan-1")       # same pair, another kind: its own edge
        edge("pass_land", "ann", "cid", 10, 0.8, "plan-1")      # inside 14d, outside 7d
        edge("tool_call", "cid", "ann", 1, 0.4, None)           # under the 50% coverage floor
        value("ann", 0.9, 30)                          # an OLDER compute, where ann led
        value("bob", 0.1, 30)
        value("dee", 0.5, 30)                          # in the older run only
        value("bob", 0.6, 2)                           # the latest compute
        value("ann", 0.3, 2)
        value("cid", 0.1, 2)

        with TestClient(obs.app) as cl:
            for path in ("/api/influence", "/api/cog"):
                arm(f"GATE: {path} with no key is 403", cl.get(path).status_code == 403)
                arm(f"GATE: {path} with a wrong key is 403", cl.get(path, headers={"x-obs-key": "nope"}).status_code == 403)

            j = cl.get("/api/influence", headers=O).json()
            e = {(x["src"], x["dst"], x["kind"]): x for x in j["edges"]}
            ab = e.get(("ann", "bob", "delegation"), {})
            arm("INFLUENCE: one edge per (src, dst, kind), counted", ab.get("n") == 6 and e.get(("ann", "bob", "pass_land"), {}).get("n") == 1, e)
            arm("INFLUENCE: …its top threads are <= 3, by count (ties by name)", ab.get("top_threads") == ["t-1", "t-2", "t-3"], ab)
            day = cl.get("/api/influence?window=7d", headers=O).json()
            arm("INFLUENCE: …its last_ts is the newest edge's", ab.get("last_ts", "") > e.get(("ann", "cid", "pass_land"), {}).get("last_ts", "~"), ab)
            arm("INFLUENCE: the 14d window keeps a 10-day edge, 7d drops it",
                ("ann", "cid", "pass_land") in e and not any((x["src"], x["dst"]) == ("ann", "cid") for x in day["edges"]), day["edges"])
            arm("INFLUENCE: any other window is 400", cl.get("/api/influence?window=30d", headers=O).status_code == 400)
            k = {x["kind"]: x for x in j["kinds"]}
            arm("INFLUENCE: a kind under the coverage floor is listed measured=false, with its coverage (shown, not hidden)",
                k.get("tool_call", {}).get("measured") is False and k["tool_call"]["coverage"] == 0.4
                and ("cid", "ann", "tool_call") in e, (k, e.keys()))
            arm("INFLUENCE: a measured kind reads measured=true", k.get("delegation", {}).get("measured") is True, k)
            arm("INFLUENCE: a hard-UNMEASURED kind says why", bool(k.get("merge_landed", {}).get("why")), k)
            arm("INFLUENCE: an edge never carries its authority ref out",
                all(set(x) == {"src", "dst", "kind", "n", "last_ts", "top_threads"} for x in j["edges"]) and "424242" not in json.dumps(j), j["edges"][:1])
            ranks = [(v["agent"], v["rank"]) for v in j["nodes"]]
            arm("INFLUENCE: the ranks are the LATEST compute's, in order", ranks == [("bob", 1), ("ann", 2), ("cid", 3)], ranks)
            arm("INFLUENCE: …and never an older run's agent (dee)", "dee" not in dict(ranks), ranks)
            arm("INFLUENCE: computed_at is given", bool(j["computed_at"]), j)

            os.environ["ASTRYX_ORG_REGISTRY"] = str(tmp / "absent.json")
            obs._identity_cache.clear()
            obs._identity_cache["v"] = {"org": "gw.example", "pubkey": "6f8e6e10be228806"}
            j = cl.get("/api/cog", headers=O).json()
            arm("COG: an ABSENT registry is a cog of one room, this org's, named",
                j.get("registry") is False and [(r["org"], r["this"]) for r in j["rooms"]] == [("fixture.example", True)], j)
            arm("COG: …with the gateway pubkey's badge", j["rooms"][0].get("badge") == "6f8e6e10", j)

            reg = tmp / "cog.json"
            reg.write_text(json.dumps({"orgs": {"zeta": {"home": str(tmp / "zeta"), "db": "zeta_db"},
                                                "alpha": {"home": str(obs.ESTATE), "db": "alpha_db"}}}))
            os.environ["ASTRYX_ORG_REGISTRY"] = str(reg)
            r = cl.get("/api/cog", headers=O)
            j = r.json() if r.status_code == 200 else {}
            rooms = [(x["org"], x["this"]) for x in j.get("rooms", [])]
            arm("COG: a two-org registry is two rooms, ours marked this", rooms == [("alpha", True), ("zeta", False)], (r.status_code, j))
            arm("COG: …and no home or database leaves", r.status_code == 200 and str(tmp) not in r.text
                and "zeta_db" not in r.text and "alpha_db" not in r.text, r.text)

            reg.write_text("{not json")
            r = cl.get("/api/cog", headers=O)
            arm("COG: a registry that refuses is a 500, never a quiet one-room answer", r.status_code == 500, (r.status_code, r.text))
            arm("COG: …and it says why, for the floor to show (seed #60095)",
                r.headers.get("content-type", "").startswith("application/json") and r.json().get("error", "").startswith("cog registry refused: "), r.text)
            os.environ.pop("ASTRYX_ORG_REGISTRY", None)


if __name__ == "__main__":
    with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
        os.environ["ASTRYX_DSN"] = fx["url"]
        os.environ["OBS_KEY"] = "test-owner-key"
        os.environ["ASTRYX_ORG"] = "fixture.example"
        os.environ["ASTRYX_GATEWAY_PORT"] = "9"          # discard: a real gateway is never asked
        os.environ.pop("ASTRYX_ORG_REGISTRY", None)
        main(fx["url"], Path(td))
    print(f"{'PASS' if not fails else 'FAIL'}: observatory floor ({fails} failing)")
    sys.exit(1 if fails else 0)
