#!/usr/bin/env python3
"""Oracle: the floor's two owner routes (seed #60078, goal 11324): GET /api/influence (who knows whom) and GET /api/cog
(the cog's rooms, owner ruling #60083). On a throwaway fixture database, with the API in-process:
  - INFLUENCE: a pair's edges SUM; an edge's weight decays on the 14-day half-life (a 60-day edge is ~5%); a kind under
    the coverage floor weighs 0 and is named in `unmeasured`; the ranks come from ONE compute (the latest), never an
    agent's own latest from an older run; an edge leaves as a pair and a number, never its refs or topic;
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
    spec = importlib.util.spec_from_file_location("main", SUBJECT)
    obs = importlib.util.module_from_spec(spec)
    sys.modules["main"] = obs
    spec.loader.exec_module(obs)
    from fastapi.testclient import TestClient

    with psycopg.connect(url, autocommit=True) as c:
        def edge(kind, src, dst, days, cov):
            c.execute("INSERT INTO influence_edge (scope, kind, src, dst, ts, ask_ts, ref, topic, coverage, computed_at) "
                      "VALUES ('local', %s, %s, %s, now() - make_interval(days => %s), now() - make_interval(days => %s), "
                      "'#1', 'secret-topic', %s, now())", (kind, src, dst, days, days, cov))

        def value(agent, v, hours_ago):
            c.execute("INSERT INTO influence_value (scope, view, agent, value, unmapped, computed_at) VALUES "
                      "('local', 'global', %s, %s, 0, date_trunc('hour', now()) - make_interval(hours => %s))",
                      (agent, v, hours_ago))

        edge("delegation", "ann", "bob", 1, 0.9)
        edge("delegation", "ann", "bob", 1, 0.9)
        edge("pass_land", "ann", "cid", 60, 0.9)
        edge("tool_call", "cid", "ann", 1, 0.4)        # under the 50% coverage floor
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
            e = {(x["src"], x["dst"]): x["w"] for x in j["edges"]}
            ab = e.get(("ann", "bob"), 0)
            arm("INFLUENCE: a pair's edges sum (two day-old delegations ≈ 2 × 0.5^(1/14))", abs(ab - 2 * 0.5 ** (1 / 14)) < 1e-3, e)
            ac = e.get(("ann", "cid"), 0)
            arm("INFLUENCE: a 60-day edge decays on the 14-day half-life (≈ 0.5^(60/14))", abs(ac - 0.5 ** (60 / 14)) < 1e-3, e)
            arm("INFLUENCE: a kind under the coverage floor weighs 0 (no cid→ann edge)", ("cid", "ann") not in e, e)
            arm("INFLUENCE: …and is named in unmeasured", "tool_call" in j["unmeasured"], j["unmeasured"])
            arm("INFLUENCE: an edge leaves as a pair and a number, never its refs or topic",
                all(set(x) == {"src", "dst", "w"} for x in j["edges"]) and "secret-topic" not in json.dumps(j), j["edges"])
            ranks = [(v["agent"], v["rank"]) for v in j["values"]]
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
