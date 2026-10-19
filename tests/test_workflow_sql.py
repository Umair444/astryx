#!/usr/bin/env python3
"""test_workflow_sql — plan-11324 S4's SQL sites run against a throwaway sqlguard fixture database
(src/astryx/security/sqlguard/fixture.py), so sqlguard OBSERVES each one (steward #61020: test_workflow reaches them
only through a fake connection, so all five sat UNEXECUTED, R-NEW).
  W1 goals() / load() on an empty table: [] and None (the WHERE seen at 0 rows)
  W2 save() appends rev 1, then rev 2 through load() -> main_commits() (a goal with no commits on main)
  W3 save() refuses a body naming another goal, and writes nothing
  W4 the observatory's GET /api/goals/{gid}/workflow (the real handler, its pool on the fixture): the latest revision,
     the influence overlay from plan-<gid> edges (planned_happened / planned_unused / unplanned); an absent goal is 404
  W5 the same endpoint for a workflow whose thread has NO influence edge (the edge query seen at 0 rows)
Exit 0 pass · 1 fail · 77 could-not-run."""
import asyncio
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_workflow_sql", REPO, deps=("psycopg", "asyncpg", "fastapi"))

try:
    import psycopg
    from astryx import workflow as wf
    from astryx.security.sqlguard.fixture import fixture_db
except Exception as e:  # noqa: BLE001
    print(f"SKIP: a subject isn't importable ({type(e).__name__}: {e}).")
    sys.exit(77)

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


GOAL = 990001                                  # no commit on main names it: measured stays empty
ROSTER = ["seed", "forge", "abstractor-2", "memory"]
B1 = {"goal": GOAL, "converge": "seed", "tasks": [
    {"id": "S1", "agent": "forge", "review": "abstractor-2", "needs": []},
    {"id": "ship", "agent": "seed", "needs": ["S1"]}]}
B2 = {**B1, "tasks": B1["tasks"] + [{"id": "S2", "agent": "memory", "needs": []}]}
B2["tasks"] = [B2["tasks"][0], B2["tasks"][2], {"id": "ship", "agent": "seed", "needs": ["S1", "S2"]}]

_fx = fixture_db()
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"SKIP: the fixture database couldn't be built ({type(e).__name__}: {e}).")
    sys.exit(77)

try:
    with psycopg.connect(fx["dsn"], autocommit=True) as c:
        check("W1 an empty table: goals() is [] and load() is None", wf.goals(c) == [] and wf.load(c, GOAL) is None,
              f"{wf.goals(c)} {wf.load(c, GOAL)}")
        r1 = wf.save(c, GOAL, B1, "t", ROSTER, REPO)
        r2 = wf.save(c, GOAL, B2, "t", ROSTER, REPO)
        got = wf.load(c, GOAL)
        check("W2 save() appends rev 1 then rev 2; load() returns the latest; goals() lists it",
              (r1, r2) == (1, 2) and got and got[0] == 2 and got[1] == B2 and wf.goals(c) == [GOAL],
              f"{r1} {r2} {got} {wf.goals(c)}")
        try:
            wf.save(c, GOAL, {**B2, "goal": GOAL + 1}, "t", ROSTER, REPO)
            refused = False
        except wf.WorkflowError:
            refused = True
        n = c.execute("SELECT count(*) FROM goal_workflow").fetchone()[0]
        check("W3 a body naming another goal is refused and nothing is written", refused and n == 2, f"{refused} {n}")
        wf.save(c, GOAL + 2, {**B1, "goal": GOAL + 2}, "t", ROSTER, REPO)     # a workflow no influence edge touches
        c.execute("INSERT INTO influence_edge (kind, src, dst, ts, ask_ts, ref, topic, coverage, computed_at) VALUES "
                  "('pass_land', 'forge', 'abstractor-2', now(), now(), 'r1', %s, 1, now()), "
                  "('pass_land', 'memory', 'forge', now(), now(), 'r2', %s, 1, now())",
                  (f"plan-{GOAL}", f"plan-{GOAL}"))

    spec = importlib.util.spec_from_file_location("obs_wfsql", REPO / "observatory" / "api" / "main.py")
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)

    async def _get():
        import asyncpg
        from psycopg.conninfo import conninfo_to_dict
        kw = conninfo_to_dict(fx["dsn"])
        kw["database"] = kw.pop("dbname")
        M.pool = await asyncpg.create_pool(min_size=1, max_size=1, **{k: v for k, v in kw.items()
                                                                       if k in ("host", "port", "user", "password", "database")})
        try:
            return await M.goal_workflow(GOAL), await M.goal_workflow(GOAL + 1), await M.goal_workflow(GOAL + 2)
        finally:
            await M.pool.close()

    hit, miss, quiet = asyncio.run(_get())
    cls = {(e["src"], e["dst"]): e["class"] for e in (hit.get("overlay", {}).get("edges", []) if isinstance(hit, dict) else [])}
    check("W4 the endpoint serves the latest revision with its overlay; an absent goal is 404",
          isinstance(hit, dict) and hit.get("rev") == 2
          and cls.get(("forge", "abstractor-2")) == "planned_happened"
          and cls.get(("seed", "memory")) == "planned_unused"
          and cls.get(("memory", "forge")) == "unplanned"
          and getattr(miss, "status_code", None) == 404,
          f"{hit if not isinstance(hit, dict) else (hit.get('rev'), cls)} {getattr(miss, 'status_code', miss)}")
    qe = quiet.get("overlay", {}).get("edges", []) if isinstance(quiet, dict) else None
    check("W5 a workflow with no influence edges on its thread: every planned edge is planned_unused, none unplanned",
          qe and all(e["class"] == "planned_unused" and e["n"] == 0 for e in qe), f"{qe}")
finally:
    _fx.__exit__(None, None, None)

print("ALL PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
