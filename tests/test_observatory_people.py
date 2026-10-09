#!/usr/bin/env python3
"""Oracle: the observatory shows agents as PEOPLE, from the right sources, to the right viewer.

On a throwaway fixture database (sqlguard's one applier), with the API in-process:
  - the roster is the charter REGISTRY: a name that only ever wrote steps (a body spawned in error)
    is not an agent;
  - an agent's face is public (an <img> can't carry the owner key) while anything shaped like a path
    escape is refused;
  - presence (where an agent's attention is) is owner-only, and the profile carries it plus recent work;
  - the model an agent runs on is its DOMINANT recent model, not whatever its last auxiliary call used.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nucleus.sqlguard.fixture import fixture_db  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def main(url):
    import psycopg
    from nucleus import charter
    real = charter.roster()
    agent = "painter" if "painter" in real else real[0]
    sys.path.insert(0, str(REPO / "observatory" / "api"))
    import main as obs
    from fastapi.testclient import TestClient
    with TestClient(obs.app) as cl0:
        empty = cl0.get("/api/agents", headers={"x-obs-key": "test-owner-key"}).json()
        arm("before any activity the roster still lists every charter (as quiet)", len(empty) == len(real), len(empty))
        arm("a quiet org has no heartbeat yet", cl0.get("/api/pulse", headers={"x-obs-key": "test-owner-key"}).json() == {})
    with psycopg.connect(url) as c:
        c.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'tool','Bash: paint'), "
                  "('onboard-ghost','tool','a body spawned in error')", (agent,))
        c.execute("INSERT INTO turns (agent, session_id, model, ended_at) VALUES "
                  "(%s,'s','claude-opus-5-5',now()), (%s,'s','claude-opus-5-5',now()), "
                  "(%s,'s','claude-haiku-5-5',now() + interval '1 second')", (agent, agent, agent))
        c.execute("INSERT INTO social_person (org, id, label, direct) VALUES ('local', 'p-1', 'Test Person', true)")
        c.execute("INSERT INTO presence (agent, surface, target, say, state) VALUES "
                  "(%s,'canvas:2','#hero','making it count up','working')", (agent,))
        c.commit()

    sys.path.insert(0, str(REPO / "observatory" / "api"))
    import main as obs
    from fastapi.testclient import TestClient
    with TestClient(obs.app) as cl:
        O = {"x-obs-key": "test-owner-key"}
        rows = cl.get("/api/agents", headers=O).json()
        names = {r["agent"] for r in rows}
        arm("the roster is the charter registry: a step-only name is not an agent", "onboard-ghost" not in names and agent in names)
        me = next(r for r in rows if r["agent"] == agent)
        arm("the model label is the DOMINANT recent model, not the last auxiliary call",
            "opus" in (me.get("model") or ""), me.get("model"))
        arm("an agent's face is public (no key)", cl.get(f"/api/agents/{agent}/avatar").status_code in (200, 404))
        arm("a path-shaped avatar name is refused", cl.get("/api/agents/..%2Fsecret/avatar").status_code in (403, 404))
        arm("presence is owner-only", cl.get("/api/presence").status_code == 403)
        arm("the heartbeat (an activity rate) is owner-only", cl.get("/api/pulse").status_code == 403)
        beat = cl.get("/api/pulse", headers=O).json().get(agent, [])
        arm("an agent's heartbeat is 24 hourly buckets, this hour's step in the last one",
            len(beat) == 24 and beat[-1] >= 1 and sum(beat) == beat[-1], beat)
        pr = cl.get("/api/presence", headers=O).json()
        arm("the owner sees where each agent's attention is",
            any(p["agent"] == agent and p["surface"] == "canvas:2" and p["target"] == "#hero" for p in pr), pr)
        prof = cl.get(f"/api/agents/{agent}/profile", headers=O).json()
        arm("the profile carries NOW: presence + recent work",
            (prof.get("presence") or {}).get("say") == "making it count up"
            and any(r["content"] == "Bash: paint" for r in prof.get("recent", [])), prof.get("presence"))
        arm("the profile's model is the dominant one too", "opus" in (prof.get("model") or ""), prof.get("model"))
        # the owner confirms his people: names resolved owner-side, answers appended privately, memory told a COUNT
        anon = cl.get("/api/people/asks")
        arm("people asks are owner-only", anon.status_code == 403)
        asks = cl.get("/api/people/asks", headers=O).json()
        arm("open asks resolve names owner-side (saved name, or 'no saved name')",
            asks["asks"][0]["label"] == "Test Person" and "no saved name" in asks["asks"][1]["label"], [x["label"] for x in asks["asks"]])
        arm("open asks are served with memory's guess and count-only evidence",
            [x["pid"] for x in asks["asks"]] == ["p-1", "p-2"] and asks["asks"][0]["kind"] == "colleague"
            and "dm_msgs" in asks["asks"][0]["evidence"], asks)
        bad = cl.post("/api/people/answers", json={"pid": "p-1", "kind": "nemesis", "closeness": "close"}, headers=O)
        miss = cl.post("/api/people/answers", json={"pid": "not-asked", "kind": "friend", "closeness": "close"}, headers=O)
        arm("an answer outside the offered values, or for a pid never asked, is refused", bad.status_code == 400 and miss.status_code == 404)
        ok = cl.post("/api/people/answers", json={"pid": "p-1", "kind": "friend", "closeness": "close"}, headers=O).json()
        cl.post("/api/people/answers", json={"pid": "p-2", "skip": True}, headers=O)
        left = cl.get("/api/people/asks", headers=O).json()
        lines = [json.loads(l) for l in (Path(os.environ["ASTRYX_PEOPLE_DIR"]) / "answers.jsonl").read_text().splitlines()]
        with psycopg.connect(url) as c:
            notes = [r[0] for r in c.execute("SELECT body FROM messages WHERE to_agent='memory'").fetchall()]
        arm("answers land privately (one per pid) and the ask closes",
            ok.get("answered") == 1 and left["asks"] == [] and [l["pid"] for l in lines] == ["p-1", "p-2"] and lines[1]["skipped"])
        arm("memory is told only a COUNT on the wire — no pid, no name, no relation",
            len(notes) == 2 and not any(("p-1" in n or "friend" in n) for n in notes), notes)
        fr = cl.get("/api/memory/graph?fresh=1", headers=O).json()
        arm("the Memory view's recompile button compiles (it called a memgraph function that did not exist)",
            "compile failed" not in str(fr.get("error", "")), fr.get("error"))
        quiet = next((n for n in real if n != agent), agent)
        q = cl.get(f"/api/agents/{quiet}/profile", headers=O).json()
        arm("a quiet agent's profile has no presence and no recent work", q.get("presence") is None and q.get("recent") == [], q.get("recent"))


if __name__ == "__main__":
    import json
    import tempfile
    pdir = Path(tempfile.mkdtemp())
    (pdir / "asks.jsonl").write_text("".join(json.dumps(a) + "\n" for a in (
        {"pid": "p-1", "candidate_kind": "colleague", "closeness": "close", "confidence": "medium",
         "evidence_summary": {"shared_groups": 2, "dm_msgs": 140}},
        {"pid": "p-2", "candidate_kind": "friend", "closeness": "inner", "confidence": "low",
         "evidence_summary": {"dm_msgs": 610}})))
    os.environ["ASTRYX_PEOPLE_DIR"] = str(pdir)
    with fixture_db() as fx:
        os.environ["ASTRYX_DSN"] = fx["url"]
        os.environ["OBS_KEY"] = "test-owner-key"
        main(fx["url"])
    print(f"{'PASS' if not fails else 'FAIL'}: observatory people ({fails} failing)")
    sys.exit(1 if fails else 0)
