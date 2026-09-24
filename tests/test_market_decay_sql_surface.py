#!/usr/bin/env python3
"""SQL-surface oracle for market_decay (triggers/steward/market_decay.py).

WHY THIS EXISTS (2026-09-24, a4 night-review; steward-delegated msg 20692). test_market_decay_advisory
drives the PURE _decide/_is_file_backed and NEVER invokes market_decay(ctx) — so the trigger's four
ctx.sql query strings were untested. A %-literal / bad-column / typo regression in any of them ships
GREEN through check.sh and only surfaces the next time the trigger fires (loud via run_python, but a
day late), and market_decay is the SOLE economic actuator — a broken query there means the market
silently stops regulating until it next fires. This arm executes all four queries FOR REAL through
psycopg's execute(query, params) signature (the %-scan crash lives at EXECUTE-time, not python
string-parse — so NO non-executing stub), so such a regression reddens at gate time. Same class as
weekly_econ's ARM 6; see tests/test_weekly_econ_review.py and reference_trigger_sql_percent_gotcha.

WRITE-SAFETY (the crux of steward's contract). market_decay WRITES: query 3 is
`UPDATE triggers SET enabled=false` and query 4 INSERTs a wire message. Running the entrypoint against
the LIVE Ctx would retire a real trigger AND ring the doorbell. So this runs against a HERMETIC TEMP
SCHEMA built from the real schema.sql DDL (the authority, not a hand copy — a column rename in
schema.sql that breaks a query is caught too). search_path is the temp schema ONLY, never public:
goal-3833's temp-schema test dropped the PROD view by leaving public reachable, so every unqualified
statement here resolves to the throwaway schema and the UPDATE/INSERT can never touch production.

The seed data drives _decide to the RETIRE branch so ALL FOUR queries execute (a candidate that only
reported would never reach the UPDATE/INSERT). RED-first: reintroduce a %-literal or a bad column into
one of the four strings → the end-to-end arm reddens; green on the fix.

Clean clone (no gitignored body / no DB / no .env) → SKIP 77, verifies nothing, never a false pass.
Exit 0 pass · 1 fail · 77 could-not-run.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_SKIP = 77
BODY = REPO / "triggers" / "steward" / "market_decay.py"
ENV = REPO / ".env"
if not BODY.exists() or not ENV.exists():
    print("SKIP: market_decay body and/or .env absent (gitignored body / bare clone) — nothing asserted.")
    sys.exit(EXIT_SKIP)

# REPO on sys.path so the path-loaded body's own `from astryx import trigger` resolves at exec time —
# a runtime insert, NOT a static `from triggers...` node, so deps.py's clean-clone AST scan is unaffected.
sys.path.insert(0, str(REPO))
try:
    _spec = importlib.util.spec_from_file_location("market_decay_sql_under_test", BODY)
    m = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(m)
    # pulse_run's OWN Ctx (imported, not re-implemented — arity fidelity: a stand-in with a different
    # execute() arity is exactly what masked the 09-21 dry-run). Reads .env DSN at import.
    _pr_spec = importlib.util.spec_from_file_location("pulse_run_md", REPO / "nucleus" / "pulse_run.py")
    pr = importlib.util.module_from_spec(_pr_spec)
    _pr_spec.loader.exec_module(pr)
    import psycopg
except Exception as e:  # noqa: BLE001 — unimportable body / no psycopg / no DSN ⇒ cannot verify, don't fake
    print(f"SKIP: market_decay SQL-surface prerequisites unavailable ({type(e).__name__}: {e}).")
    sys.exit(EXIT_SKIP)

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def _table_ddl(name):
    """Extract `CREATE TABLE IF NOT EXISTS <name> ( ... );` from schema.sql — the real column DDL, the
    authority. Stops at the first ');' so trailing ALTER/INDEX/FK statements (e.g. messages→turns) are
    NOT dragged into the hermetic schema."""
    text = (REPO / "nucleus" / "schema.sql").read_text()
    i = text.index(f"CREATE TABLE IF NOT EXISTS {name} (")
    return text[i:text.index(");", i) + 2]


DSN = pr.DSN
SCH = f"t_mdsql_{os.getpid()}"
conn = psycopg.connect(DSN, autocommit=True)
try:
    conn.execute(f"DROP SCHEMA IF EXISTS {SCH} CASCADE")
    conn.execute(f"CREATE SCHEMA {SCH}")
    # SCH ONLY — never `SCH, public`. A statement that fell through to public could hit a PROD table;
    # the market_decay UPDATE/INSERT MUST land only in the throwaway schema (goal-3833's footgun).
    # pg_catalog (types, now()) is always implicitly searched, so SCH-only is sufficient and isolates.
    conn.execute(f"SET search_path TO {SCH}")
    for t in ("econ", "triggers", "messages"):
        conn.execute(_table_ddl(t))

    # ── seed data that drives _decide -> "retire" so ALL FOUR queries execute ─────────────────
    # CONSECUTIVE(=3) econ rows, W>0 (priced), each naming the SAME candidate with roi<0 ∧
    # fires>=MIN_FIRES → verdict==3 → candidate. A made-up (agent,name) that exists in no real org.
    CAND = ("t_victim_agent", "t_money_pit_trigger")
    roi_entry = [{"agent": CAND[0], "trigger": CAND[1], "roi": -9, "fires": 50}]
    for d in ("2026-09-24", "2026-09-23", "2026-09-22"):
        conn.execute("INSERT INTO econ (day, metrics) VALUES (%s::date, %s::jsonb)",
                     (d, json.dumps({"thermo": {"W": "1000000"}, "trigger_roi": roi_entry})))
    # the candidate trigger: premium=0, enabled=true, DB-defined check_src (no on-disk .py) → retire
    conn.execute("INSERT INTO triggers (agent, name, schedule, kind, check_src, enabled, premium) "
                 "VALUES (%s, %s, '0 0 * * *', 'sql', 'SELECT 1', true, 0)", CAND)

    # ── the ctx: pulse_run's OWN Ctx, but PINNED to the temp-schema connection (write-safe) ────
    # Subclass so the execute(query, params) call surface is byte-identical to production; only the
    # connection differs (temp schema, not prod), so the UPDATE/INSERT land in the throwaway schema.
    class TempCtx(pr.Ctx):
        def __init__(self, state, connection):
            super().__init__(state)
            self._conn = connection      # pin to temp-schema conn; skips Ctx.sql's lazy prod-connect

    ctx = TempCtx({}, conn)

    # faithfulness insurance (contract pt 1): the ctx really %-scans at EXECUTE-time — a literal-%
    # query RAISES, so a non-executing stub could never have slipped in as the executor.
    def _raises(q):
        try:
            ctx.sql(q)
            return False
        except Exception:
            return True
    check("EXECUTOR reproduces the %-scan at execute-time (a literal-% query RAISES — proves this is "
          "not a non-executing stub)", _raises("SELECT 1 WHERE 'z' LIKE '(x:%'"))

    # ── run the entrypoint end to end: all four queries execute against the temp schema ────────
    try:
        out = m.market_decay(ctx)
        ran_ok, err = True, ""
    except Exception as e:  # noqa: BLE001 — a regression in ANY of the 4 query strings surfaces HERE
        ran_ok, err, out = False, f"{type(e).__name__}: {e}", None
    check("entrypoint runs end-to-end through the temp-schema ctx — all 4 ctx.sql strings (econ "
          "SELECT, triggers SELECT, triggers UPDATE, messages INSERT) parse & execute", ran_ok, err)

    # reaching RETIRE proves the WRITE queries (3 and 4) actually ran, in the temp schema:
    en = conn.execute("SELECT enabled FROM triggers WHERE agent=%s AND name=%s", CAND).fetchone()
    check("query 3 (UPDATE enabled=false) executed — the candidate is retired IN THE TEMP SCHEMA",
          en is not None and en[0] is False, f"enabled={en}")
    msg = conn.execute("SELECT from_agent, intent FROM messages WHERE to_agent=%s", (CAND[0],)).fetchone()
    check("query 4 (INSERT messages) executed — the loud notice landed IN THE TEMP SCHEMA",
          msg is not None and msg[0] == "steward" and msg[1] == "market", f"msg={msg}")
    check("the entrypoint reported the retirement (RETIRED segment present)",
          isinstance(out, str) and "RETIRED" in out, f"out={out!r}")

    # CONTAINMENT: the writes went to SCH, not public — the real actuator table is untouched.
    pub = conn.execute("SELECT count(*) FROM public.triggers WHERE agent=%s AND name=%s", CAND).fetchone()
    check("CONTAINMENT: no victim row leaked to public.triggers (search_path SCH-only held)",
          pub is not None and pub[0] == 0)
finally:
    conn.execute(f"DROP SCHEMA IF EXISTS {SCH} CASCADE")
    conn.close()

print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
print("market_decay SQL-surface: all 4 ctx.sql strings execute against a hermetic temp schema "
      "(write-safe — UPDATE/INSERT contained), the %-scan is reproduced, production untouched")
sys.exit(0)
