"""Authored mutants for channel/server.mjs's lost-wake recovery — run by mutation_probe.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_wake_recovery.py

THE LIST IS THE JUDGEMENT. Recovery has two failure directions and they pull against each
other, so a mutant set that only attacks one of them would licence the other. M1 is the
pre-fix code verbatim: the wake stays lost. M2–M6 each delete one clause of the timid
predicate, and every one of them makes recovery FIRE TOO MUCH — a duplicate wake, which
for a peer's task is worse than the loss it cures. Each is written to break exactly one
case of the oracle, so a green run after a change locates the clause that rotted.

M7 is the one worth keeping honest about. It breaks nothing a database row can see: the
message is recovered, the counter advances, every SQL assertion passes, and the body is
handed an hours-old wake dressed as a fresh one. It is caught only by reading the MCP
notification the body actually receives — the oracle's second instrument, in a different
medium from the first. If M7 ever moves to NOT PROBED, that instrument has rotted and the
row state is quietly speaking for the wire again.

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list — see the probe's docstring
on why it may never report an assertion as vacuous.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "channel" / "server.mjs"
ORACLE = REPO / "nucleus" / "test_wake_recovery.py"
ENV = "CHANNEL_SERVER_SRC"

MUTANTS = {
    # The pre-fix state: the drain sweeps `pending` and nothing else, so a message claimed
    # by a body that then died is never offered to anything again. This is the standing
    # regression for the 2026-08-15 roster respawn that ate nine agents' morning wake.
    "M1 recovery never called (pre-fix)":
        ("try { await recoverLostWakes() }",
         "try { /* no recovery */ }"),

    # Without the boot boundary every message this session just delivered is a recovery
    # candidate 15 seconds later — the ear starts duplicating its own live traffic.
    "M2 boot boundary dropped":
        ("        AND m.delivered_at < $2\n", ""),

    # A finished turn that outlived the delivery is the strongest evidence of a read there
    # is. Dropping it re-serves messages the agent demonstrably worked through.
    "M3 turn evidence ignored":
        ("""        AND NOT EXISTS (SELECT 1 FROM turns t
                         WHERE t.agent = m.to_agent AND t.started_at < $2
                           AND t.ended_at > m.delivered_at)\n""", ""),

    # turns rows are written at turn END and ended_at is NOT NULL, so a body killed
    # mid-turn leaves no turn row at all. Steps are the only witness for that case; without
    # them an interrupted-but-awake session gets everything served twice.
    "M4 step evidence ignored":
        ("""        AND NOT EXISTS (SELECT 1 FROM steps s
                         WHERE s.agent = m.to_agent AND s.kind <> 'boot'
                           AND s.ts > m.delivered_at AND s.ts < $2)\n""", ""),

    # A wedged agent that is respawned over and over would be re-served the same message
    # every time, forever, with no state that ever stops it.
    "M5 redelivery attempt cap removed":
        ("AND coalesce((m.delivery->>'recovered')::int, 0) < $4",
         "AND coalesce((m.delivery->>'recovered')::int, 0) < 1000000"),

    # An unbounded window redelivers wakes days stale — a heartbeat for a morning that is
    # long over, arriving as if it were now.
    "M6 age window unbounded":
        ("AND m.delivered_at > $2::timestamptz - make_interval(hours => $3)",
         "AND m.delivered_at > $2::timestamptz - make_interval(hours => 99999)"),

    # Silent redelivery. Every row assertion still passes; only the body is lied to, and
    # only the notification stream can tell.
    "M7 redelivery marker dropped":
        ("""  const content = again
    ? `[redelivered wake · sent ${new Date(row.ts).toISOString()} · the session it was ` +
      `first delivered to ended before taking any turn, so nothing read it]\\n${row.body}`
    : row.body""",
         "  const content = row.body"),
}
