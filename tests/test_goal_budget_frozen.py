#!/usr/bin/env python3
"""Oracle for goal 4227 S3 — the budget WRITERS retire; the columns stay, read-only, no DROP.

Owner law 2026-09-29: NO budgets, ever. S0-S2 moved every READER off budgets; S3 retires every
WRITER. Found by a writer census (steward, 09-29), not assumed:
  - mcp/org/server.py::propose_goal     wrote budget_tokens=0 on every filed goal
  - observatory/api/main.py::goal_create took an owner-supplied budget_tokens
  - schema.sql goals_done_stamp()        stamped funded_by='(unfunded)' on close (3499 naming)
  (spent_tokens has no writer at all; stale_goals' "budget halves" was prose, never a write.)
The columns are KEPT — the v1 history (11 goals carry a budget, 7 a funder) stays readable and
v1's frozen econ rows reference it — and FROZEN by a BEFORE trigger (goals_budget_frozen): an
insert may not set them, an update may not change them. triggers.premium is EXCLUDED: it is the
survival flag pulse.shed reads, not a budget (a3's sequencing hazard, #21235).

GRADE: ACCIDENT-PROOF, NOT ACTOR-PROOF (a2 #23159). The freeze stops the honest writer who did not
know; every agent's psql is the superuser that owns goals and can disable it unrecorded.

Every arm executes the REAL code against a sqlguard fixture (a throwaway DATABASE with schema.sql
applied whole — goal 4243: a SQL site is RESPONSIVE only when its literal runs in a stamped fixture):
  1. propose_goal (the real MCP function, its _dsn pointed at the fixture) files a goal with NO
     budget written, and its INSERT names no budget column.
  2. goal_create (the real FastAPI handler, its pool on the fixture) ignores a budget in the payload;
     NewGoal has no budget field; the doorbell message still lands.
  3. FREEZE on INSERT: budget_tokens / spent_tokens / funded_by set at insert → rejected.
  4. FREEZE on UPDATE: changing any of the three on a LEGACY budgeted row → rejected; changing
     anything else on that row works, and its budget is still READABLE (read-only ≠ gone).
  4b. LATE WRITER: a later-sorting BEFORE trigger that sets funded_by is still rejected — the
     freeze is an AFTER trigger and sees the final row.
  5. CLOSE: state→done still stamps done_at (W-birth) and no longer writes funded_by.
  6. premium EXCLUDED: UPDATE triggers SET premium succeeds.
  7. NO DROP: every budget column still exists.
Exit 0 pass · 1 fail · 77 no DB / no CREATEDB.
"""
import asyncio
import importlib.util
import inspect
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_SKIP = 77
sys.path.insert(0, str(REPO))

from nucleus.sqlguard.estate import gate  # noqa: E402
gate("test_goal_budget_frozen", REPO, deps=("psycopg", "asyncpg", "fastapi"))
import psycopg  # noqa: E402
from nucleus.sqlguard.fixture import fixture_db  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def rejects(conn, sql, args=()):
    try:
        with conn.transaction():
            conn.execute(sql, args)
        return False, ""
    except Exception as e:  # noqa: BLE001
        return True, f"{type(e).__name__}: {str(e).splitlines()[0]}"


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_fx = fixture_db()
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001 — no CREATEDB / DB down ⇒ cannot verify, don't fake
    print(f"SKIP: the fixture database couldn't be built ({type(e).__name__}: {e}).")
    sys.exit(EXIT_SKIP)
conn = psycopg.connect(fx["dsn"], autocommit=True)
try:
    # ── 1. propose_goal ───────────────────────────────────────────────────────────────────
    print("1. propose_goal (real MCP function):")
    os.environ["ASTRYX_AGENT"] = "t_s3_owner"
    S = load("orgsrv_s3", "mcp/org/server.py")
    S._dsn = lambda: fx["dsn"]
    out = S.propose_goal("t_s3 goal via mcp", scope_note="s3 oracle")
    row = conn.execute("SELECT id, budget_tokens, spent_tokens, funded_by, owner FROM goals "
                       "WHERE title='t_s3 goal via mcp'").fetchone()
    check("propose_goal filed the goal", row is not None and "filed" in out, out)
    check("...with budget 0, spent 0, no funder (nothing written)",
          row is not None and row[1:4] == (0, 0, None), str(row))
    src = inspect.getsource(S.propose_goal)
    check("propose_goal's SQL names no budget column (it stopped taking budgets)",
          "budget_tokens" not in src.split('"""', 2)[-1], "budget_tokens in the body")
    check("propose_goal takes no budget parameter",
          not any("budget" in p for p in inspect.signature(S.propose_goal).parameters))

    # ── 2. goal_create (observatory) ──────────────────────────────────────────────────────
    print("\n2. goal_create (real FastAPI handler):")
    M = load("obs_s3", "observatory/api/main.py")
    check("NewGoal has no budget field", "budget_tokens" not in M.NewGoal.model_fields,
          str(list(M.NewGoal.model_fields)))

    class Req:
        headers = {"x-obs-key": "t_s3_key"}

    async def _create():
        import asyncpg
        from psycopg.conninfo import conninfo_to_dict
        kw = conninfo_to_dict(fx["dsn"])                 # asyncpg takes kwargs, not key=value text
        kw["database"] = kw.pop("dbname")
        M.pool = await asyncpg.create_pool(min_size=1, max_size=1,
                                           **{k: v for k, v in kw.items()
                                              if k in ("host", "port", "user", "password", "database")})
        M.OBS_KEY = "t_s3_key"
        try:
            g = M.NewGoal(title="t_s3 goal via api", assignee="t_s3_agent",
                          **{"budget_tokens": 999_999})       # an old client still sending one
            return await M.goal_create(g, Req())
        finally:
            await M.pool.close()

    res = asyncio.run(_create())
    row = conn.execute("SELECT budget_tokens, funded_by FROM goals WHERE title='t_s3 goal via api'"
                       ).fetchone()
    check("goal_create filed the goal and IGNORED the payload's budget",
          isinstance(res, dict) and row == (0, None), f"res={res} row={row}")
    msg = conn.execute("SELECT count(*) FROM messages WHERE to_agent='t_s3_agent' AND intent='task'"
                       ).fetchone()[0]
    check("...and the assignment doorbell still landed", msg == 1, f"messages={msg}")

    # ── 3. FREEZE on INSERT ───────────────────────────────────────────────────────────────
    print("\n3. FREEZE on INSERT:")
    for col, val in (("budget_tokens", 5), ("spent_tokens", 5), ("funded_by", "seed")):
        bad, why = rejects(conn, f"INSERT INTO goals (title, owner, {col}) VALUES ('t_s3 x', 'o', %s)",
                           (val,))
        check(f"INSERT setting {col} is rejected", bad, why or "accepted")
    ok_, why = rejects(conn, "INSERT INTO goals (title, owner) VALUES ('t_s3 plain', 'o')")
    check("a plain INSERT (no budget columns) is accepted", not ok_, why)

    # ── 4. FREEZE on UPDATE, over a LEGACY budgeted row ───────────────────────────────────
    print("\n4. FREEZE on UPDATE (legacy row):")
    conn.execute("ALTER TABLE goals DISABLE TRIGGER goals_budget_frozen")   # seed v1 history only
    gid = conn.execute("INSERT INTO goals (title, owner, state, budget_tokens, funded_by) VALUES "
                       "('t_s3 legacy', 'o', 'active', 1000, 'seed') RETURNING id").fetchone()[0]
    conn.execute("ALTER TABLE goals ENABLE TRIGGER goals_budget_frozen")
    for col, val in (("budget_tokens", 2000), ("budget_tokens", 0), ("spent_tokens", 1),
                     ("funded_by", None), ("funded_by", "someone")):
        bad, why = rejects(conn, f"UPDATE goals SET {col}=%s WHERE id=%s", (val, gid))
        check(f"UPDATE {col}={val!r} on a legacy row is rejected", bad, why or "accepted")
    ok_, why = rejects(conn, "UPDATE goals SET title='t_s3 legacy renamed', state='hibernated' "
                             "WHERE id=%s", (gid,))
    check("updating OTHER columns of a budgeted row still works", not ok_, why)
    after = conn.execute("SELECT budget_tokens, funded_by FROM goals WHERE id=%s", (gid,)).fetchone()
    check("the v1 budget is still READABLE (read-only, not erased)", after == (1000, "seed"), str(after))

    # ── 4b. LATE WRITER (a2 #23159) ─────────────────────────────────────────────────────
    # BEFORE ROW triggers fire in NAME order and a later one's NEW is never re-checked, so a BEFORE
    # freeze is a gate any later-sorting BEFORE trigger writes through (goals_done_stamp is exactly
    # that shape — it used to write funded_by). The freeze must see the FINAL row: an AFTER trigger.
    print("\n4b. a later-sorting BEFORE trigger cannot write through the freeze:")
    conn.execute("CREATE FUNCTION t_s3_late() RETURNS trigger AS $$ BEGIN "
                 "NEW.funded_by := 'late-writer'; RETURN NEW; END $$ LANGUAGE plpgsql")
    conn.execute("CREATE TRIGGER goals_zz_late BEFORE UPDATE ON goals FOR EACH ROW "
                 "EXECUTE FUNCTION t_s3_late()")
    bad, why = rejects(conn, "UPDATE goals SET title='t_s3 late probe' WHERE id=%s", (gid,))
    late = conn.execute("SELECT funded_by FROM goals WHERE id=%s", (gid,)).fetchone()[0]
    conn.execute("DROP TRIGGER goals_zz_late ON goals")
    check("a late BEFORE trigger setting funded_by is REJECTED (the freeze sees the final row)",
          bad and late == "seed", f"rejected={bad} funded_by={late!r} {why}")
    tg = conn.execute("SELECT tgtype & 2 FROM pg_trigger WHERE tgname='goals_budget_frozen'").fetchone()
    check("goals_budget_frozen is an AFTER trigger", tg is not None and tg[0] == 0, str(tg))

    # ── 5. CLOSE ──────────────────────────────────────────────────────────────────────────
    print("\n5. CLOSE (W-birth kept, funder-naming retired):")
    new = conn.execute("SELECT id FROM goals WHERE title='t_s3 goal via mcp'").fetchone()[0]
    conn.execute("UPDATE funded_by_watermark SET legacy_max_id = 0")       # every goal is 'new'
    ok_, why = rejects(conn, "UPDATE goals SET state='done' WHERE id=%s", (new,))
    done = conn.execute("SELECT done_at IS NOT NULL, funded_by FROM goals WHERE id=%s", (new,)).fetchone()
    check("closing a goal succeeds", not ok_, why)
    check("...stamps done_at (W-birth intact)", done[0] is True, str(done))
    check("...and writes NO funded_by (no '(unfunded)' sentinel)", done[1] is None, str(done))

    # ── 6. premium EXCLUDED ───────────────────────────────────────────────────────────────
    print("\n6. premium excluded:")
    conn.execute("INSERT INTO triggers (agent, name, schedule, kind, check_src) "
                 "VALUES ('t_s3', 't_s3_guard', '0 0 * * *', 'sql', 'SELECT 1')")
    ok_, why = rejects(conn, "UPDATE triggers SET premium=1000000 WHERE agent='t_s3'")
    check("UPDATE triggers.premium succeeds (the survival flag is not a budget)", not ok_, why)

    # ── 7. NO DROP ────────────────────────────────────────────────────────────────────────
    print("\n7. no DROP:")
    cols = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns "
                                       "WHERE table_name='goals'")}
    check("budget_tokens, spent_tokens, funded_by all still exist",
          {"budget_tokens", "spent_tokens", "funded_by"} <= cols, str(sorted(cols)))
finally:
    conn.close()
    _fx.__exit__(None, None, None)

print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
print("goal budgets: writers retired (propose_goal, goal_create, close), columns frozen read-only, "
      "no DROP, premium excluded")
sys.exit(0)
