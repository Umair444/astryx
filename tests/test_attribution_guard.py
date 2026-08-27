#!/usr/bin/env python3
"""Oracle for nucleus/attribution_guard.py — economy-boundary conservation (goal 3408).

Proves Baum's ceiling against the REAL econ.value_flow SQL on a throwaway postgres:
  · the real attribution CONSERVES on a known fixture (Σ credited == Σ shipped budgets);
  · the BOUNDARY holds — turns on an UNSHIPPED goal and turns with a NULL goal_id are NOT
    credited (value_flow's join is turns.goal_id→goals(done_at), the one boundary);
  · a DOUBLE-CREDITING attribution is CAUGHT (MINT) — the wash-trading failure Baum names;
  · a credit path that reaches nobody (the dead steps.goal_id, all-NULL) is CAUGHT
    (ROUTING-HOLE) — the shortfall blows past the truncation bound.

The pure check_conservation() arms need no DB. The substrate arms build a REAL throwaway
database (NEVER the org's own — the role must be able to CREATE DATABASE, else SKIP 77), so
the proof is against the real SQL, not a re-implementation of it (a verifier must not share
the emitter's code). Run by nucleus/check.sh.
"""
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

EXIT_SKIP = 77


def skip(msg: str):
    print(f"SKIP: {msg}")
    sys.exit(EXIT_SKIP)


try:
    import psycopg
    from nucleus.attribution_guard import check_conservation, run as guard_run, _budgets_and_rows
    from nucleus import econ
except Exception as e:                                              # noqa: BLE001
    skip(f"{type(e).__name__}: {e} — the attribution oracle needs the org runtime (fresh clone)")

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        got:  {got!r}\n        want: {want!r}")
        fails.append(label)


# ── PURE arms — the invariant with no DB ─────────────────────────────────────────────
print("PURE — the conservation invariant:")
check("conserving input passes",
      check_conservation([{"agent": "a", "value_earned": 998}], 1000, 3), [])
check("MINT: earned > budgets is caught",
      check_conservation([{"agent": "a", "value_earned": 1500}], 1000, 3)[0].kind, "MINT")
check("ROUTING-HOLE: shortfall past truncation bound is caught",
      check_conservation([], 1000, 3)[0].kind, "ROUTING-HOLE")
check("shortfall EQUAL to the truncation bound still passes (boundary)",
      check_conservation([{"agent": "a", "value_earned": 997}], 1000, 3), [])


# ── SUBSTRATE arms — real value_flow on a throwaway postgres ──────────────────────────
def dsn():
    if os.environ.get("ASTRYX_DSN"):
        return os.environ["ASTRYX_DSN"].strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ASTRYX_DSN="):
                return line[len("ASTRYX_DSN="):].strip().strip('"').strip("'")
    return None


ADMIN_DSN = dsn()
if not ADMIN_DSN:
    skip("no ASTRYX_DSN (env or .env) — no substrate to build a throwaway on")
SCHEMA = REPO / "nucleus" / "schema.sql"
if not SCHEMA.exists():
    skip("nucleus/schema.sql is absent — cannot build a throwaway database")
try:
    admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=5)
except Exception as e:                                              # noqa: BLE001
    skip(f"database unreachable ({type(e).__name__}) — no substrate")
row = admin.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()
if not row or not row[0]:
    admin.close()
    skip("this role cannot CREATE DATABASE — a throwaway is the only safe substrate "
         "(this oracle NEVER touches the org's own database)")

PROBE_DB = f"astryx_attribprobe_{os.getpid()}"
PROBE_DSN = re.sub(r"/[^/?]+(\?|$)", f"/{PROBE_DB}\\1", ADMIN_DSN, count=1)
if PROBE_DB not in PROBE_DSN:
    admin.close()
    skip("could not derive a throwaway DSN from ASTRYX_DSN (unexpected shape)")


def cleanup():
    try:
        admin.execute(f'DROP DATABASE IF EXISTS "{PROBE_DB}" WITH (FORCE)')
    except Exception:                                              # noqa: BLE001
        pass
    admin.close()


try:
    admin.execute(f'DROP DATABASE IF EXISTS "{PROBE_DB}" WITH (FORCE)')
    admin.execute(f'CREATE DATABASE "{PROBE_DB}"')
    # apply schema (no params → simple protocol → multi-statement runs)
    with psycopg.connect(PROBE_DSN, autocommit=True, connect_timeout=5) as sc:
        sc.execute(SCHEMA.read_text())

    with psycopg.connect(PROBE_DSN, connect_timeout=5) as conn:
        # ── fixture ──────────────────────────────────────────────────────────────
        # G1 SHIPPED (budget 3000); G2 active/unshipped (budget 5000). done_at is set by a
        # BEFORE-UPDATE trigger only, so a direct INSERT of done_at is honoured.
        conn.execute("INSERT INTO goals (id,title,owner,state,budget_tokens,done_at) "
                     "VALUES (1,'g1','forge','done',3000,'2026-08-01 00:00:00+00')")
        conn.execute("INSERT INTO goals (id,title,owner,state,budget_tokens,done_at) "
                     "VALUES (2,'g2','forge','active',5000,NULL)")

        def turn(agent, goal_id, bill):
            conn.execute("INSERT INTO turns (agent,goal_id,raw_payload) VALUES (%s,%s,%s::jsonb)",
                         (agent, goal_id, json.dumps({"usage": {"billable_equiv_in": bill}})))

        turn("alice", 1, 1000)      # shipped G1 spend: alice 1000 + bob 2000 = 3000 == budget
        turn("bob", 1, 2000)
        turn("carol", 2, 4000)      # UNSHIPPED goal — must NOT be credited
        turn("dave", None, 9000)    # NULL goal_id — must NOT be credited
        conn.commit()

        since = datetime(2020, 1, 1, tzinfo=timezone.utc)
        until = datetime(2030, 1, 1, tzinfo=timezone.utc)
        rows = econ.value_flow(conn, since, until)
        earned = {r["agent"]: int(r["value_earned"] or 0) for r in rows}

        print("\nSUBSTRATE — real value_flow on a throwaway DB:")
        check("real value_flow CONSERVES (guard finds no violation)", guard_run(conn, since, until), [])
        check("alice credited her flux share (1000)", earned.get("alice"), 1000)
        check("bob credited his flux share (2000)", earned.get("bob"), 2000)
        check("Σ credited == shipped budget (3000), spend divides even → no truncation",
              sum(earned.values()), 3000)
        check("BOUNDARY: unshipped-goal agent carol NOT credited", "carol" in earned, False)
        check("BOUNDARY: null-goal agent dave NOT credited", "dave" in earned, False)

        # substrate RED — a double-crediting attribution (the wash failure) is caught as MINT
        b, nrows = _budgets_and_rows(conn, since, until)
        doubled = [{**r, "value_earned": int(r["value_earned"] or 0) * 2} for r in rows]
        v = check_conservation(doubled, b, nrows)
        check("DOUBLE-CREDIT attribution over real data → MINT caught", v[0].kind if v else None, "MINT")
        # substrate RED — credit that reaches nobody (dead steps.goal_id join → empty) → HOLE
        v2 = check_conservation([], b, nrows)
        check("credit routed through the dead column (nobody paid) → ROUTING-HOLE",
              v2[0].kind if v2 else None, "ROUTING-HOLE")
finally:
    cleanup()

print()
if fails:
    print(f"test_attribution_guard: {len(fails)} FAIL — {fails}")
    sys.exit(1)
print("test_attribution_guard: ALL PASS")
sys.exit(0)
