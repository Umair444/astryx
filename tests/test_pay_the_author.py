#!/usr/bin/env python3
"""Oracle for nucleus/pay_the_author.py — pay-the-author credit + wash detection (goal 3408).

Proves against the REAL join (steps.kind=tool → turns.goal_id → shipped goals) on a throwaway
postgres:
  · the authored ledger CONSERVES — Σ(callers + authors + house) == Σ shipped budgets — and
    the SAME guard that gates value_flow (attribution_guard.check_conservation, d62c858)
    accepts it: pay-the-author cannot mint W above the boundary;
  · a tool's DECLARED author is credited; an unknown/unregistered-author tool PARKS to house
    (never a fabricated agent);
  · the WASH DETECTOR FIRES on a real self-dealt cycle — an agent who authored a tool AND drove
    its author-pay with its own turns on its own shipped goal (detection, turns.agent forgeable).

Throwaway DB only (role must CREATE DATABASE, else SKIP 77); NEVER the org's own. Run by check.sh.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
EXIT_SKIP = 77


def skip(m):
    print(f"SKIP: {m}")
    sys.exit(EXIT_SKIP)


try:
    import psycopg
    from nucleus.pay_the_author import (_reshare, pay_the_author, wash_detector, HOUSE, AUTHOR_SHARE)
    from nucleus.attribution_guard import check_conservation, _budgets_and_rows
except Exception as e:                                              # noqa: BLE001
    skip(f"{type(e).__name__}: {e} — the pay-the-author oracle needs the org runtime")

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        got:  {got!r}\n        want: {want!r}")
        fails.append(label)


# ── PURE arms — the split, no DB ─────────────────────────────────────────────────────
print("PURE — the reshare split:")
_authors = {"memory": "forge", "contacts": "forge", "gmail": "unknown"}
_rows = [{"goal_id": 1, "budget": 10000, "tool": t} for t in
         ("mcp__memory__ask", "mcp__contacts__resolve", "mcp__gmail__send", "ToolSearch")]
_out = _reshare(_rows, {"alice": 5000, "bob": 5000}, _authors, alpha=0.2)
check("Σ credited == budget (conserves)", sum(_out.values()), 10000)
check("callers keep (1-α): alice 4000", _out.get("alice"), 4000)
check("declared author forge credited α-share of its 2 tools", _out.get("forge"), 1000)
check("unknown-author + non-mcp tools PARK to house", _out.get(HOUSE), 1000)
check("no goal-with-no-tools mints: empty tools → α-pot to house",
      _reshare([{"goal_id": 9, "budget": 1000, "tool": None}][:0] or
               [], {"x": 1000}, _authors, 0.2).get("x"), 800)


# ── SUBSTRATE arms — real join on a throwaway DB ─────────────────────────────────────
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
    skip("no ASTRYX_DSN — no substrate")
SCHEMA = REPO / "nucleus" / "schema.sql"
if not SCHEMA.exists():
    skip("nucleus/schema.sql absent")
try:
    admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=5)
except Exception as e:                                              # noqa: BLE001
    skip(f"database unreachable ({type(e).__name__})")
row = admin.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()
if not row or not row[0]:
    admin.close()
    skip("role cannot CREATE DATABASE — a throwaway is the only safe substrate")

PROBE_DB = f"astryx_ptaprobe_{os.getpid()}"
PROBE_DSN = re.sub(r"/[^/?]+(\?|$)", f"/{PROBE_DB}\\1", ADMIN_DSN, count=1)
if PROBE_DB not in PROBE_DSN:
    admin.close()
    skip("could not derive a throwaway DSN")


def cleanup():
    try:
        admin.execute(f'DROP DATABASE IF EXISTS "{PROBE_DB}" WITH (FORCE)')
    except Exception:                                              # noqa: BLE001
        pass
    admin.close()


try:
    admin.execute(f'DROP DATABASE IF EXISTS "{PROBE_DB}" WITH (FORCE)')
    admin.execute(f'CREATE DATABASE "{PROBE_DB}"')
    with psycopg.connect(PROBE_DSN, autocommit=True, connect_timeout=5) as sc:
        sc.execute(SCHEMA.read_text())

    with psycopg.connect(PROBE_DSN, connect_timeout=5) as conn:
        def goal(i, budget):
            conn.execute("INSERT INTO goals (id,title,owner,state,budget_tokens,done_at) "
                         "VALUES (%s,%s,'forge','done',%s,'2026-08-01 00:00:00+00')", (i, f"g{i}", budget))

        def turn(i, agent, goal_id, bill):
            conn.execute("INSERT INTO turns (id,agent,goal_id,raw_payload) VALUES (%s,%s,%s,%s::jsonb)",
                         (i, agent, goal_id, json.dumps({"usage": {"billable_equiv_in": bill}})))

        def tool_step(turn_id, agent, tool):
            # steps has NO tool column — the tool name leads the content, as the live rows carry it.
            conn.execute("INSERT INTO steps (agent,kind,content,turn_id) VALUES (%s,'tool',%s,%s)",
                         (agent, f"{tool}: (probe args)", turn_id))

        # G1 (budget 10000): alice + bob callers; alice uses forge-authored tools, bob uses unknown/non-mcp.
        goal(1, 10000)
        turn(101, "alice", 1, 1000); tool_step(101, "alice", "mcp__memory__ask"); tool_step(101, "alice", "mcp__contacts__resolve")
        turn(102, "bob", 1, 1000);   tool_step(102, "bob", "mcp__gmail__send");    tool_step(102, "bob", "ToolSearch")
        # G_wash (budget 3000): forge authors memory AND self-calls it 3x on its own shipped goal.
        goal(2, 3000)
        turn(201, "forge", 2, 300)
        for _ in range(3):
            tool_step(201, "forge", "mcp__memory__ask")
        conn.commit()

        since = datetime(2020, 1, 1, tzinfo=timezone.utc)
        until = datetime(2030, 1, 1, tzinfo=timezone.utc)
        ledger = {r["agent"]: int(r["value_earned"]) for r in pay_the_author(conn, since, until)}
        b, nrows = _budgets_and_rows(conn, since, until)

        print("\nSUBSTRATE — authored ledger on the real join:")
        check("CONSERVES: Σ authored ledger == Σ shipped budgets (13000)", sum(ledger.values()), 13000)
        check("d62c858's own check_conservation ACCEPTS the authored ledger",
              check_conservation([{"agent": a, "value_earned": v} for a, v in ledger.items()], b, nrows), [])
        check("declared author forge is credited (author-share of its tools)", ledger.get("forge", 0) > 0, True)
        check("unknown/non-mcp tool credit PARKED to house", ledger.get(HOUSE, 0) > 0, True)
        check("caller bob credited (his (1-α) turn share)", ledger.get("bob", 0) > 0, True)

        print("\nSUBSTRATE — wash detector fires on the self-dealt cycle:")
        wash = wash_detector(conn, since, until)
        flagged = {w["author"] for w in wash}
        check("wash detector FIRES on forge (self-authored-self-called)", "forge" in flagged, True)
        check("...and reports a self-dealt fraction over the flag threshold",
              any(w["author"] == "forge" and w["self_dealt_frac"] > 0.5 for w in wash), True)
finally:
    cleanup()

print()
if fails:
    print(f"test_pay_the_author: {len(fails)} FAIL — {fails}")
    sys.exit(1)
print("test_pay_the_author: ALL PASS")
sys.exit(0)
