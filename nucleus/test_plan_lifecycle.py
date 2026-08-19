#!/usr/bin/env python3
"""Oracle for the PLAN LIFECYCLE nets in triggers/seed/plan_consensus.py.

Covers every phase's liveness net and, above all, the handoffs BETWEEN them: the
climb (plan_climb_due), the climb->verdict boundary at consolidation, and each
net's obligation to stay silent in phases it does not own. The class of bug it
exists to catch: a one-shot wire handoff that a fresh boot never replays, leaving
a plan frozen and invisible until stale_goals strands the goal at 48h.

Every scenario runs inside a transaction that is ROLLED BACK. Stated precisely,
because the loose version of this claim is wrong: a rollback isolates ROWS, not
EFFECTS. Two things escape it and the suite now says so out loud rather than
implying a guarantee it never checked (my 08-12 report to seed claimed "no row or
trigger side-effect touched the real org" on the strength of a row COUNT, which
cannot observe an effect at all):
  - DB TRIGGERS on the tables we write fire INSIDE the transaction. `messages`
    carries `messages_notify`, which pg_notify()s the addressee's channel — i.e.
    every synthetic ping in here rings a real agent's doorbell at the substrate
    level. We are safe only because NOTIFY is transactional: queued at raise,
    delivered at COMMIT, discarded on ROLLBACK. That is a property of postgres,
    not of this file, so `preflight_isolation_premise` now VERIFIES it (below)
    instead of assuming it, and refuses to run the scenarios if it cannot.
  - SEQUENCES do not roll back, by design. This suite burns goals/messages ids on
    every run (228 goal ids as of 08-13). Harmless — the ids are bigint and
    nothing derives meaning from contiguity — but it IS a durable effect, so it
    is recorded here rather than filed under "untouched".
Verified able to FAIL, not merely to pass: `--mutate` corrupts the derived rank
chain and 4 cases must go red (that is the oracle's own proof).

Run:  venv/bin/python nucleus/test_plan_lifecycle.py [--mutate]
Skips (exit 0, loudly) where it cannot run honestly: no psycopg, no reachable
DSN, or no trigger file — triggers/ is gitignored, so a fresh clone has no
bodies to test and a silent PASS there would be a lie.
"""
import runpy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRIGGER = REPO / "triggers/seed/plan_consensus.py"


def skip(why):
    print(f"  ○ plan-lifecycle oracle skipped: {why}")
    sys.exit(77)          # 77 = SKIP (automake convention); check.sh counts it UNVERIFIED


try:
    import psycopg
except ImportError:
    skip("psycopg not importable (run with venv/bin/python)")
if not TRIGGER.exists():
    skip(f"{TRIGGER.relative_to(REPO)} absent (triggers/ is gitignored — nothing to test)")
try:
    DSN = next(l.split("=", 1)[1].strip()
               for l in (REPO / ".env").read_text().splitlines()
               if l.startswith("ASTRYX_DSN="))
    psycopg.connect(DSN, connect_timeout=5).close()
except Exception as e:                                   # noqa: BLE001 - any reason is a skip
    skip(f"no reachable org database ({type(e).__name__})")
sys.path.insert(0, str(REPO))
MOD = runpy.run_path(str(TRIGGER))
MUTATE = "--mutate" in sys.argv


# Tables the scenarios INSERT into, and every DB trigger on them that has been AUDITED as
# transaction-local. Pinned by a hash of the function body, because a trigger's NAME is not
# its behaviour: the same name can be CREATE OR REPLACE'd into something that escapes the
# transaction (dblink, COPY TO PROGRAM, an FDW write, a pg_background job) and a name-only
# check would still read green. Detector polarity, per the org's fail-safe law: an
# unrecognised or changed trigger means the isolation premise is UNVERIFIED, so it goes RED
# and the scenarios do not run — never "probably fine".
WRITE_TABLES = ("goals", "messages")
AUDITED_TRIGGERS = {
    # pg_notify only: queued at raise, delivered at COMMIT, discarded on ROLLBACK.
    # Audited 2026-08-13 by reading pg_get_functiondef; re-read it if this hash moves.
    ("messages", "messages_notify"):
        "90dc3a1274f05949d212c2bcf9fe8dacf90180e37e869596154d63fcb8e1524c",
}


def preflight_isolation_premise():
    """Prove the rollback actually isolates, before writing a single synthetic row.

    This suite's whole safety argument is "it runs in a rolled-back transaction". That
    argument is about ROWS; the scenarios also fire this table's DB triggers for real.
    A test cannot claim what it cannot observe, so observe it: enumerate the triggers on
    the tables we write and fail closed on anything not audited as transaction-local.
    """
    with psycopg.connect(DSN) as conn:
        rows = conn.execute(
            "SELECT c.relname, t.tgname, "
            "       encode(sha256(pg_get_functiondef(t.tgfoid)::bytea), 'hex') AS body "
            "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND c.relname = ANY(%s)",
            (list(WRITE_TABLES),)).fetchall()
    problems = []
    for table, tg, body in rows:
        known = AUDITED_TRIGGERS.get((table, tg))
        if known is None:
            problems.append(f"{table}.{tg} is NOT audited — read pg_get_functiondef and "
                            f"confirm it cannot escape a rolled-back transaction, then pin "
                            f"its hash ({body})")
        elif known != body:
            problems.append(f"{table}.{tg} CHANGED since it was audited (pinned {known[:12]}…, "
                            f"now {body[:12]}…) — re-read the body before trusting rollback")
    if problems:
        print("  ✗ isolation premise UNVERIFIED — refusing to run scenarios against a live DB:")
        for p in problems:
            print(f"      · {p}")
        sys.exit(1)
    print(f"  ✓ isolation premise: {len(rows)} trigger(s) on {'/'.join(WRITE_TABLES)} "
          f"audited transaction-local (sequences still burn — see the module docstring)")


class TxCtx:
    """pulse_run.Ctx, but bound to one rolled-back transaction."""

    def __init__(self, conn):
        self.state, self._conn = {}, conn

    def sql(self, query, params=()):
        with self._conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description is None:
                return []
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def seed_plan(ctx, posts, revise_ago=None, goal_age="10 minutes", make_thread=True):
    """A synthetic proposed goal + its plan thread. posts = [(agent, intent, ago)]."""
    gid = ctx.sql("INSERT INTO goals (title, owner, state, ts) VALUES "
                  "('TEST climb oracle','seed','proposed', now() - %s::interval) "
                  "RETURNING id", (goal_age,))[0]["id"]
    thread = f"plan-{gid}"
    if make_thread:
        ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts) VALUES "
                "('seed','abstractor-1',%s,'task','route the idea', now() - %s::interval)",
                (thread, goal_age))
    if revise_ago:
        ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts) VALUES "
                "('abstractor-4','abstractor-2',%s,'revise','rework at rank 2', "
                "now() - %s::interval)", (thread, revise_ago))
    for agent, intent, ago in posts:
        ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts) VALUES "
                "(%s,'abstractor-4',%s,%s,'refinement', now() - %s::interval)",
                (agent, thread, intent, ago))
    return gid, thread


def pings(ctx, thread, name="plan_climb_due"):
    return sorted(r["to_agent"] for r in ctx.sql(
        "SELECT to_agent FROM messages WHERE from_agent='pulse' AND body LIKE %s",
        (f"[trigger {name} {thread}]%",)))


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def a_baton_dropped(ctx):
    """rank 1 posted 3h ago, rank 2 silent -> ping rank 2, directly."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "chat", "3 hours")], goal_age="4 hours")
    fire = MOD["plan_climb_due"](ctx)
    assert fire and "abstractor-2" in fire, fire
    assert pings(ctx, thread) == ["abstractor-2"], pings(ctx, thread)
    assert "quiet 180m" in ctx.sql(
        "SELECT body FROM messages WHERE from_agent='pulse' AND body LIKE %s",
        (f"[trigger plan_climb_due {thread}]%",))[0]["body"]


@case
def b_mid_thought_grace(ctx):
    """rank 1 posted 10m ago -> inside the grace, silent."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "chat", "10 minutes")])
    # SCOPED, not `is None`: the guard reads the whole live estate, so its global return
    # is not a property of this fixture — a real thread qualifying anywhere flips it
    # (steward, msg 12200: plan-2470 crossed its threshold and turned this file red with
    # nothing edited). "This fixture must not wake anyone" is pings(thread) == [].
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == []


@case
def c_consolidated_hands_off(ctx):
    """top rank posted -> climb net silent AND verdict net now fires with ZERO voters."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "chat", "5 hours"),
                                  ("abstractor-2", "chat", "4 hours"),
                                  ("abstractor-3", "chat", "3 hours"),
                                  ("abstractor-4", "chat", "2 hours")], goal_age="6 hours")
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == [], "climb net must stand down at consolidation"
    # pin the fix to its cause: with no derivable rank the guard falls back to the OLD
    # predicate (needs a first voter) and this same fixture goes silent — the hole.
    g = MOD["plan_verdict_due"].__globals__
    real, g["ranked_members"] = g["ranked_members"], lambda: []
    try:
        MOD["plan_verdict_due"](ctx)
        assert pings(ctx, thread, "plan_verdict_due") == [], \
            "pre-fix behaviour should be silent here"
    finally:
        g["ranked_members"] = real
    fire = MOD["plan_verdict_due"](ctx)
    assert fire, "the pre-fix hole: a consolidation with no first voter woke nobody"
    assert pings(ctx, thread, "plan_verdict_due") == [
        "abstractor-1", "abstractor-2", "abstractor-3", "abstractor-4"], fire


@case
def d_revise_reopen_not_derivable(ctx):
    """revise reopened the loop, nobody posted since -> no guessed ping, seed relays."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "chat", "9 hours")],
                            revise_ago="3 hours", goal_age="10 hours")
    fire = MOD["plan_climb_due"](ctx)
    assert fire and "NEEDS YOUR ROUTING" in fire and "reopened by a revise" in fire, fire
    assert str(gid) in fire, "the fixture's goal must be in the summary, not just a live one's"
    assert pings(ctx, thread) == [], "must not invent the reopen rank"


@case
def e_never_routed(ctx):
    """proposed goal, no plan thread at all -> seed's act, summary only."""
    gid, thread = seed_plan(ctx, [], goal_age="5 hours", make_thread=False)
    fire = MOD["plan_climb_due"](ctx)
    assert fire and "no plan-" in fire and "NEEDS YOUR ROUTING" in fire, fire
    assert str(gid) in fire, "the fixture's goal must be in the summary, not just a live one's"
    assert pings(ctx, thread) == []


@case
def e2_never_routed_inside_grace(ctx):
    """same, but only 30m old -> silent (seed may be mid-route)."""
    gid, thread = seed_plan(ctx, [], goal_age="30 minutes", make_thread=False)
    fire = MOD["plan_climb_due"](ctx)
    assert not (fire and str(gid) in fire), "inside the grace the fixture must not be named"


@case
def f_virgin_thread_entry_hop(ctx):
    """seed routed, no abstractor posted, no revise -> ping rank 1."""
    gid, thread = seed_plan(ctx, [], goal_age="3 hours")
    fire = MOD["plan_climb_due"](ctx)
    assert fire and "abstractor-1" in fire, fire
    assert pings(ctx, thread) == ["abstractor-1"]


@case
def g_cooldown_and_pending(ctx):
    """a delivered ping 10m ago -> hold; an unread ping -> never stack."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "chat", "3 hours")], goal_age="4 hours")
    ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts,status) VALUES "
            "('pulse','abstractor-2',%s,'trigger',%s, now() - interval '10 minutes','read')",
            (thread, f"[trigger plan_climb_due {thread}] earlier"))
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == ["abstractor-2"], "cooldown must hold (only the seeded row)"
    ctx.sql("UPDATE messages SET ts = now() - interval '90 minutes' WHERE body LIKE %s",
            (f"[trigger plan_climb_due {thread}] earlier%",))
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == ["abstractor-2", "abstractor-2"], \
        "past cooldown it must re-fire (standing condition)"
    ctx.sql("DELETE FROM messages WHERE body LIKE %s",
            (f"[trigger plan_climb_due {thread}]%",))
    ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts,status) VALUES "
            "('pulse','abstractor-2',%s,'trigger',%s, now() - interval '90 minutes','pending')",
            (thread, f"[trigger plan_climb_due {thread}] unread"))
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == ["abstractor-2"], "an unread alarm must not stack"


@case
def h_unranked_group_is_silent(ctx):
    """no derivable rank order -> peers, not a chain: name nobody."""
    # runpy hands back a COPY of the namespace, so patch the function's own globals
    g = MOD["plan_climb_due"].__globals__
    real, g["ranked_members"] = g["ranked_members"], lambda: []
    try:
        gid, thread = seed_plan(ctx, [("abstractor-1", "chat", "3 hours")], goal_age="4 hours")
        MOD["plan_climb_due"](ctx)
        assert pings(ctx, thread) == []
    finally:
        g["ranked_members"] = real


@case
def i_skipped_rank_is_the_next(ctx):
    """1 and 3 posted, 2 skipped -> the chain's gap is who gets named."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "chat", "5 hours"),
                                  ("abstractor-3", "chat", "3 hours")], goal_age="6 hours")
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == ["abstractor-2"], pings(ctx, thread)


@case
def j_non_proposed_goal_ignored(ctx):
    """an active/refused goal is not this net's business (plan_orphan owns the dead)."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "chat", "3 hours")], goal_age="4 hours")
    ctx.sql("UPDATE goals SET state='active' WHERE id=%s", (gid,))
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == []


@case
def k_regression_siblings_still_silent(ctx):
    """the three untouched nets keep their climb-phase silence on the same fixture."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "chat", "3 hours")], goal_age="4 hours")
    for name in ("plan_consensus", "plan_stall", "plan_orphan", "plan_verdict_due"):
        MOD[name](ctx)
        assert pings(ctx, thread, name) == [], f"{name} must stay silent mid-climb"


def main():
    preflight_isolation_premise()      # fail-closed: never write until rollback is proven
    ok = True
    for fn in CASES:
        with psycopg.connect(DSN) as conn:          # autocommit off: everything rolls back
            ctx = TxCtx(conn)
            try:
                if MUTATE:      # oracle check: corrupt the rank chain, expect failures
                    MOD["plan_climb_due"].__globals__["ranked_members"] = \
                        lambda: [(1, "abstractor-1")]
                fn(ctx)
                print(f"  PASS  {fn.__name__}")
            except AssertionError as e:
                ok = False
                print(f"  FAIL  {fn.__name__}: {e}")
            except Exception as e:
                ok = False
                print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            finally:
                conn.rollback()
    print("ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
