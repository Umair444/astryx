#!/usr/bin/env python3
"""Oracle for nucleus/wake_audit.py — the four states, each isolated.

WHY SYNTHETIC AND NOT A LIVE ASSERTION: the audit's value is entirely in what it does NOT
report. Run against live data it prints a number nobody can check, and the expensive
mistake in this area — twice now — was trusting a signal whose false-positive class was
never measured. So each fixture below is built so that exactly ONE exclusion clause can be
responsible for its verdict; if a clause is deleted or inverted, precisely one case flips
and names itself. A test where several clauses could explain the same pass proves nothing
about any of them.

Every fixture agent gets its own name, its rows go in inside a transaction, and the
transaction is ROLLED BACK. Safe because `messages_notify` (the only trigger on the table)
is a pure pg_notify, which postgres delivers at COMMIT — a rollback sends no wake to any
real agent. Checked in pg_trigger before writing this, because a rolled-back transaction
isolates ROWS, not side EFFECTS.

    venv/bin/python nucleus/test_wake_audit.py        (also run by nucleus/check.sh)
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def skip(why: str) -> None:
    print(f"  ○ wake-audit oracle skipped: {why}")
    sys.exit(0)


try:
    import psycopg
except ImportError:
    skip("psycopg not importable (run with venv/bin/python)")

from nucleus import wake_audit  # noqa: E402

try:
    conn = psycopg.connect(wake_audit.dsn(), connect_timeout=5)
except Exception as e:  # noqa: BLE001 — any reason at all is a skip, never a failure
    skip(f"no reachable org database ({type(e).__name__})")

FX = "fx-wakeaudit-"          # every fixture name is prefixed so the assertions can scope
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        fails.append(f"{label}{': ' + detail if detail else ''}")


def msg(cur, to_agent: str, minutes_ago: int, frm: str = "pulse") -> int:
    return cur.execute(
        "INSERT INTO messages (from_agent, to_agent, intent, body, status, ts, delivered_at) "
        "VALUES (%s,%s,'trigger','fixture','delivered', now() - make_interval(mins => %s), "
        "        now() - make_interval(mins => %s)) RETURNING id",
        (frm, to_agent, minutes_ago, minutes_ago)).fetchone()[0]


def turn(cur, agent: str, start_min: int, end_min: int, input_msg_id: int | None = None) -> None:
    cur.execute(
        "INSERT INTO turns (agent, started_at, ended_at, input_msg_id, source) "
        "VALUES (%s, now() - make_interval(mins => %s), now() - make_interval(mins => %s), "
        "        %s, 'trigger')", (agent, start_min, end_min, input_msg_id))


with conn:                                    # rolled back explicitly below
    cur = conn.cursor()

    # ---- CONSUMED: a turn carries it as input_msg_id -------------------------------
    a = FX + "consumed"
    m_consumed = msg(cur, a, 600)
    turn(cur, a, 600, 590, m_consumed)

    # ---- MID-TURN: landed inside a running turn; no later turn within grace --------
    # started BEFORE the message, so the "picked up by a later turn" clause cannot fire
    # and only the spanning clause can explain the exclusion.
    b = FX + "midturn"
    m_mid = msg(cur, b, 600)
    turn(cur, b, 605, 595)

    # ---- ABSORBABLE: no spanning turn, but the agent took a turn LATER -------------
    # 8h later, far outside any plausible grace window. This is the case that produced a
    # false alarm about a human being ignored: an owner message sat 3h49m and rode into a
    # turn opened by an unrelated trigger. ANY later turn makes consumption unknowable.
    c = FX + "absorbable"
    m_absorbable = msg(cur, c, 600)
    turn(cur, c, 120, 110)

    # ---- DROPPED: delivered, nothing before, during, or after ----------------------
    # The old turn exists only so the agent qualifies as a turn-taker at all.
    d = FX + "dropped"
    turn(cur, d, 3000, 2990)
    m_dropped = msg(cur, d, 600)

    rows = wake_audit.dropped(conn, hours=48, grace=2)
    got = {r["id"] for r in rows if r["to_agent"].startswith(FX)}

    check("DROPPED is reported", m_dropped in got, "the one real drop was not flagged")
    check("CONSUMED is not reported", m_consumed not in got,
          "a message a turn provably consumed was called dropped")
    check("MID-TURN is not reported", m_mid not in got,
          "a message folded into a running turn was called dropped — this is the ~25% "
          "false-positive class the mid-turn clause exists to remove")
    check("ABSORBABLE is not reported", m_absorbable not in got,
          "a message followed by ANY later turn was called dropped — that turn could have "
          "absorbed it, and claiming otherwise is how a human gets falsely reported ignored")
    check("exactly one fixture drop", got == {m_dropped}, f"got {sorted(got)}")

    # ---- grace: a wake younger than the grace window is in flight, not dropped -----
    e = FX + "inflight"
    turn(cur, e, 3000, 2990)
    m_fresh = msg(cur, e, 5)                          # 5 minutes old
    fresh_rows = wake_audit.dropped(conn, hours=48, grace=2)
    check("in-flight wake is not reported",
          m_fresh not in {r["id"] for r in fresh_rows},
          "a wake delivered minutes ago was called dropped — its turn has not hit Stop yet")

    # ---- by_source separates the human from the machinery -------------------------
    f = FX + "owner-ignored"
    turn(cur, f, 3000, 2990)
    m_owner = msg(cur, f, 600, frm="owner")
    split = wake_audit.by_source(
        [r for r in wake_audit.dropped(conn, hours=48, grace=2)
         if r["to_agent"].startswith(FX)])
    check("owner drop is counted as owner", split["owner"] == 1, f"got {split}")
    check("pulse drops stay pulse", split["pulse"] == 1, f"got {split}")

    # ---- consecutive_drops: a consumed wake BREAKS the streak ---------------------
    # Newest-first: drop, drop, consumed, drop. The streak is the unbroken RUN from the
    # newest end (2) — not the total (3). A count that ignores the break would report an
    # agent as wedged on the strength of drops it has since recovered from.
    g = FX + "streak"
    turn(cur, g, 3000, 2990)
    msg(cur, g, 800)                                   # oldest: dropped (beyond the break)
    m_break = msg(cur, g, 700)
    turn(cur, g, 699, 698, m_break)                    # consumed → breaks the streak
    msg(cur, g, 600)                                   # dropped
    msg(cur, g, 500)                                   # dropped (newest)
    streaks = dict(wake_audit.consecutive_drops(conn, hours=48))
    check("streak counts only the unbroken run from the newest wake",
          streaks.get(g) == 2, f"got {streaks.get(g)} for {g}, expected 2")

    conn.rollback()                                    # fixtures never commit

if fails:
    print("WAKE-AUDIT ORACLE FAILED:", file=sys.stderr)
    for f_ in fails:
        print(f"  ✗ {f_}", file=sys.stderr)
    sys.exit(1)
print("wake-audit: consumed/mid-turn/picked-up/dropped classified correctly, grace holds, "
      "owner split intact, streak breaks on a consumed wake ✓")
