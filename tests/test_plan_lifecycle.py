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

Run:  venv/bin/python tests/test_plan_lifecycle.py [--mutate]
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
    # Calls no user-defined function (builtin pg_notify only) — re-checked 2026-09-29.
    ("messages", "messages_notify"):
        "90dc3a1274f05949d212c2bcf9fe8dacf90180e37e869596154d63fcb8e1524c",
    # BEFORE UPDATE row trigger stamping goals.done_at (the economy's boundary event).
    # Re-audited 2026-09-29 (goal 4227 S3, steward) by reading pg_get_functiondef on the live DB:
    # pure plpgsql, mutates NEW.done_at ONLY — S3 removed the funder-naming and with it the
    # SELECT INTO read from funded_by_watermark; no NOTIFY, no dblink, no COPY, no write to any
    # other table. Calls no user-defined function (builtin now() only). Transaction-local.
    # (Previous pin 3b6883024b6a… = the 3499 body.)
    # Re-read it if this hash moves.
    ("goals", "goals_done_stamp"):
        "3ff956b5ec898883ac5725590746214f44cb77b9b621858f0512061eb68b6409",
    # AFTER INSERT OR UPDATE row trigger freezing the deprecated budget columns (goal 4227 S3).
    # Audited 2026-09-29 (steward) by reading pg_get_functiondef on the live DB: pure plpgsql,
    # reads NEW/OLD and at most RAISEs — no write anywhere, no NOTIFY/dblink/COPY. Inside the
    # scenarios' rolled-back transaction a RAISE only aborts the statement; the scenarios never
    # set budget_tokens/spent_tokens/funded_by, so it never fires. Calls no user-defined
    # function. Transaction-local.
    # Re-read it if this hash moves.
    ("goals", "goals_budget_frozen"):
        "b63554be919a50c376f94c067bf1af255c49210064b709f5f52967244f2664f1",
}
# tests/test_audited_trigger_pins.py checks these pins against THIS tree's schema.sql in a fixture,
# so a branch that changes a pinned trigger is RED at review, not after the live apply (S3's lesson).
# A pin hashes the trigger FUNCTION BODY only: it does not cover CALLEES (plpgsql records no
# pg_depend on functions it calls). If a pinned body ever calls a user-defined helper, pin the
# helper too, or the helper can gain a NOTIFY/dblink/write under an unchanged pin (a2 #23791).


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

    def say(self, to, body, **kw):
        """goal 4227 S1c: the check SAYS its wakes; here they go through the pulse's own writer (emit)
        inside this rolled-back transaction, so the arms see exactly what the chokepoint delivers."""
        sys.path.insert(0, str(REPO))
        from nucleus.pulse import emit
        emit(self._conn, dict(kw, to_agent=to, body=body))

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


@case
def l_stall_clock_ignores_facility_nudges(ctx):
    """A thread being NAGGED must still be able to look quiet (forge, msg 12555):
    plan_verdict_due writes a nudge to the same thread every 15m, so an unfiltered
    max(ts) staleness clock could NEVER accumulate the 2h grace — measured on
    plan-2470's real 3.4h stall, the largest gap all night was 45 min and every one
    was closed by the sibling's own row. The clock must count HUMAN AND AGENT
    movement only. Pre-fix this fixture is silent; the fix makes it fire."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "approve", "5 hours")],
                            goal_age="10 hours")
    ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts) VALUES "
            "('pulse','abstractor-2',%s,'trigger','[trigger plan_verdict_due] nudge', "
            "now() - interval '10 minutes')", (thread,))
    fire = MOD["plan_stall"](ctx)
    assert fire and f"#{gid}" in fire, \
        f"a nagged stall must still fire naming the fixture goal (got: {fire!r})"
    # and the control: genuine agent movement inside the grace still silences it
    ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts) VALUES "
            "('abstractor-2','abstractor-4',%s,'chat','working on it', "
            "now() - interval '10 minutes')", (thread,))
    ctx.state["flagged"] = {}
    fire2 = MOD["plan_stall"](ctx)
    assert not (fire2 and f"#{gid}" in fire2), \
        "real agent movement inside the grace must silence the stall"


@case
def m_climb_clock_ignores_facility_nudges(ctx):
    """The SIBLING clock, same law (a1, msg 13067): plan_climb_due was safe only by
    circumstance — phase-disjointness plus cooldown ≥ grace — and either coincidence
    being tuned away would blind it silently. A mid-climb thread carrying a fresh
    facility nag must still read as agent-quiet: pre-filter this fixture is silent
    (quiet=10min < 45min grace off the nag row), post-filter it pings the next rank."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "chat", "3 hours")], goal_age="4 hours")
    ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts) VALUES "
            "('pulse','abstractor-2',%s,'trigger','[trigger plan_verdict_due] stray nudge', "
            "now() - interval '10 minutes')", (thread,))
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == ["abstractor-2"], \
        "a nagged mid-climb thread must still ping the next rank"
    # control: genuine agent movement inside the grace still holds the climb net
    gid2, thread2 = seed_plan(ctx, [("abstractor-1", "chat", "10 minutes")],
                              goal_age="4 hours")
    ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts) VALUES "
            "('pulse','abstractor-2',%s,'trigger','[trigger plan_verdict_due] stray nudge', "
            "now() - interval '5 minutes')", (thread2,))
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread2) == [], \
        "real agent movement inside the grace must hold, nag or no nag"



def _raw_idea_by_top(ctx, gid, thread, ago):
    """The TOP rank ORIGINATES the idea (a4 night-review → plan-4918): a rank-1 task, not a design."""
    ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts) VALUES "
            "('abstractor-4','abstractor-1',%s,'task','a raw idea for rank-1', now() - %s::interval)",
            (thread, ago))


@case
def n_top_originated_is_not_consolidated(ctx):
    """plan-4918 (2026-09-30): the top rank filed the raw idea and nobody has climbed. The verdict net
    must stay silent (a raw idea is not a design; 4 approves would activate it unrefined), and the climb
    net must own the thread: after its grace it pings rank 1."""
    gid, thread = seed_plan(ctx, [], goal_age="3 hours", make_thread=False)
    _raw_idea_by_top(ctx, gid, thread, "3 hours")
    MOD["plan_verdict_due"](ctx)
    assert pings(ctx, thread, "plan_verdict_due") == [], "a top-rank RAW IDEA opened the verdict phase"
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == ["abstractor-1"], pings(ctx, thread)


@case
def o_top_originated_climb_reaches_top(ctx):
    """…then ranks 1-3 climb; rank 3 hands off to the top, which hasn't consolidated yet. The climb net
    pings the TOP (it must not StopIteration on a `posted` set that already holds the originator), and
    the verdict net stays silent."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "refine", "5 hours"),
                                  ("abstractor-2", "refine", "4 hours"),
                                  ("abstractor-3", "refine", "3 hours")],
                            goal_age="7 hours", make_thread=False)
    _raw_idea_by_top(ctx, gid, thread, "6 hours")
    MOD["plan_verdict_due"](ctx)
    assert pings(ctx, thread, "plan_verdict_due") == [], "consolidation not reached: no verdict phase"
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == ["abstractor-4"], pings(ctx, thread)


@case
def p_top_originated_then_consolidated(ctx):
    """…and once the top posts AFTER rank 3's handoff, the verdict phase opens with zero voters."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "refine", "5 hours"),
                                  ("abstractor-2", "refine", "4 hours"),
                                  ("abstractor-3", "refine", "3 hours"),
                                  ("abstractor-4", "chat", "2 hours")],
                            goal_age="7 hours", make_thread=False)
    _raw_idea_by_top(ctx, gid, thread, "6 hours")
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == [], "climb net must stand down at a real consolidation"
    MOD["plan_verdict_due"](ctx)
    assert pings(ctx, thread, "plan_verdict_due") == [
        "abstractor-1", "abstractor-2", "abstractor-3", "abstractor-4"]



def _msg(ctx, thread, frm, to, intent, ago):
    ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts) VALUES "
            "(%s,%s,%s,%s,'x', now() - %s::interval)", (frm, to, thread, intent, ago))


def _climbed_and_consolidated(ctx):
    """ranks 1-3 climbed (rank 3 handed off to the top), and the top consolidated."""
    gid, thread = seed_plan(ctx, [("abstractor-1", "refine", "8 hours"),
                                  ("abstractor-2", "refine", "7 hours"),
                                  ("abstractor-3", "refine", "6 hours")],
                            goal_age="9 hours", make_thread=False)
    _msg(ctx, thread, "abstractor-4", "abstractor-1", "chat", "5 hours")      # the consolidation
    return gid, thread


@case
def q_rework_at_top_after_revise_reopens_verdicts(ctx):
    """plan-14/3407/3408/3410/3499 shape (a1 #24567): a revise sends the rework to the TOP, and the top posts
    its correction with NO fresh rank-3 handoff. It's still consolidated, so the verdict net re-pings all
    four. PINS the unbounded handoff: bounding it by the revise closes this verdict phase (5 live plans)."""
    gid, thread = _climbed_and_consolidated(ctx)
    _msg(ctx, thread, "abstractor-1", "abstractor-4", "revise", "4 hours")    # rework at rank 4
    _msg(ctx, thread, "abstractor-4", "abstractor-1", "chat", "3 hours")      # the top's correction
    MOD["plan_verdict_due"](ctx)
    assert pings(ctx, thread, "plan_verdict_due") == [
        "abstractor-1", "abstractor-2", "abstractor-3", "abstractor-4"], pings(ctx, thread, "plan_verdict_due")


@case
def r_carried_reconsolidation_stays_consolidated(ctx):
    """plan-2789 shape (a1 #24567): the top's own REVISE carries the re-consolidation to a lower rank, then
    verdicts land. The climb net must stay silent through the verdict phase: under a handoff bounded by the
    revise it would read "not consolidated" and ping rank 2 mid-verdict."""
    gid, thread = _climbed_and_consolidated(ctx)
    _msg(ctx, thread, "abstractor-4", "abstractor-1", "revise", "4 hours")    # carried re-consolidation
    _msg(ctx, thread, "abstractor-1", "abstractor-4", "approve", "3 hours")
    _msg(ctx, thread, "abstractor-4", "abstractor-1", "approve", "2 hours")
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == [], pings(ctx, thread)



@case
def s_chat_down_the_chain_is_not_a_climb(ctx):
    """plan-4918 shape (2026-09-30): the top files a raw idea; rank 3 posts a note DOWN the chain (to rank 1);
    rank 1 hands off to rank 2; rank 2 acks DOWN the chain ("refinement pending"). The baton is with RANK 2.
    A post isn't a climb step, a HANDOFF (a message to a higher rank) is: counting any post named the TOP as
    next and would have skipped ranks 2 and 3."""
    gid, thread = seed_plan(ctx, [], goal_age="5 hours", make_thread=False)
    for frm, to, intent, ago in [("abstractor-4", "abstractor-1", "task", "4 hours"),
                                 ("abstractor-3", "abstractor-1", "chat", "4 hours"),
                                 ("abstractor-1", "abstractor-2", "refine", "3 hours"),
                                 ("abstractor-2", "abstractor-1", "chat", "3 hours")]:
        ctx.sql("INSERT INTO messages (from_agent,to_agent,thread,intent,body,ts) VALUES "
                "(%s,%s,%s,%s,'x', now() - %s::interval)", (frm, to, thread, intent, ago))
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == ["abstractor-2"], pings(ctx, thread)


def _approved_then_redesigned(ctx):
    """plan-4918 #28982 shape (seed #29424): all four approve, then the top posts a changed BINDING part as
    intent='design' (not 'revise'), then one voter re-approves naming it. Only 'revise' staled approvals, so the
    old approves still counted: plan_quorum read 4/4 fresh and a4 re-collected verdicts by hand."""
    gid, thread = _climbed_and_consolidated(ctx)
    for v, ago in [("abstractor-1", "4 hours"), ("abstractor-2", "4 hours"),
                   ("abstractor-3", "4 hours"), ("abstractor-4", "4 hours")]:
        _msg(ctx, thread, v, "abstractor-4", "approve", ago)
    _msg(ctx, thread, "abstractor-4", "abstractor-1", "design", "3 hours")    # the binding revision
    _msg(ctx, thread, "abstractor-1", "abstractor-4", "approve", "2 hours")   # a1 re-reads and re-approves
    return gid, thread


@case
def t_design_repost_stales_approvals(ctx):
    """A design post after approvals STALES them, exactly as a revise does: the quorum is 1/4, not 4/4, and
    the verdict net re-pings the three whose approve predates the change."""
    gid, thread = _approved_then_redesigned(ctx)
    met = MOD["plan_consensus"](ctx) or ""
    assert f"#{gid} " not in met, f"quorum fired on approves that predate the design change: {met}"
    MOD["plan_verdict_due"](ctx)
    assert pings(ctx, thread, "plan_verdict_due") == ["abstractor-2", "abstractor-3", "abstractor-4"], \
        pings(ctx, thread, "plan_verdict_due")


@case
def u_design_repost_stays_consolidated(ctx):
    """The design post stales VERDICTS only; it must not reopen the CLIMB. consolidated() keeps the revise-only
    cut: under the verdict cut the top's own design post sits AT the cut, not after it, so the thread would
    read un-consolidated and the climb net would ping rank 1 mid-verdict."""
    gid, thread = _approved_then_redesigned(ctx)
    MOD["plan_climb_due"](ctx)
    assert pings(ctx, thread) == [], pings(ctx, thread)


@case
def v_one_writer_for_change_intents(ctx):
    """The tool and the nets read ONE file, so they can't disagree (seed #29424). The trigger's set IS the
    file's. server.mjs's plan_quorum reads the file and hardcodes no intent in its staleness query."""
    path = REPO / "nucleus" / "plan_change_intents"
    want = {l.strip() for l in path.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")}
    assert {"revise", "design"} <= want, want
    assert set(MOD["change_intents"]()) == want, (MOD["change_intents"](), want)
    js = (REPO / "channel" / "server.mjs").read_text()
    block = js[js.index("if (name === 'plan_quorum')"):js.index("if (name === 'self_edit')")]
    assert "plan_change_intents" in block, "plan_quorum does not read nucleus/plan_change_intents"
    assert "intent='revise'" not in block, "plan_quorum hardcodes intent='revise' in its staleness query"


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
