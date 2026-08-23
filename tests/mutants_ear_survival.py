"""Authored mutants for channel/server.mjs's ear-survival guard — run by mutation_probe.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_ear_survival.py

THE LIST IS THE JUDGEMENT. Each entry is a way the fix for the 2026-08-14 deafness could
plausibly be undone or written wrong. Two of them (M1, M2) are the pre-fix code verbatim,
so they are the standing regression for the outage itself. The other three are the shapes
a well-meaning edit takes: a handler that "handles" by rethrowing, a catch that logs and
then exits anyway, and a listener that stops the crash without restoring the hearing.

M5 is the one worth keeping honest about. It does not crash anything — the process lives
through both faults and would pass any "is it still running" test. It is caught only by
the assertion that the ear still DELIVERS afterwards, which is the difference between a
surviving ear and a wedged one. If M5 ever moves to NOT PROBED, that assertion has rotted.

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list — see the probe's docstring
on why it may never report an assertion as vacuous.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "channel" / "server.mjs"
ORACLE = REPO / "nucleus" / "test_ear_survival.py"
ENV = "CHANNEL_SERVER_SRC"

MUTANTS = {
    # The pre-fix line. This IS the 2026-08-14 outage: a postgres restart sends every open
    # backend 57P01, pg.Pool re-emits it, and an EventEmitter 'error' with no listener is
    # an uncaught exception.
    "M1 pool error listener removed (pre-fix)":
        ("pool.on('error', e => console.error('[channel] pooled client died, discarding it:', e.message))",
         "// (no pool error listener)"),

    # The other pre-fix line. An async fn handed straight to setInterval has nowhere to put
    # a rejection, and node exits(1) on an unhandled one.
    "M2 bare async fn on the interval (pre-fix)":
        ("""setInterval(() => refreshSubs().catch(e =>
      console.error('[channel] subscription refresh failed, keeping the ear:', e.message)),
      SUBS_REFRESH_MS)""",
         "setInterval(refreshSubs, SUBS_REFRESH_MS)"),

    # A listener that rethrows is not a listener. Reads as deliberate; behaves as absent.
    "M3 pool handler rethrows":
        ("pool.on('error', e => console.error('[channel] pooled client died, discarding it:', e.message))",
         "pool.on('error', e => { throw e })"),

    # Logs the failure and dies anyway — the shape of a "fix" that only improves the
    # obituary.
    "M4 refresh catch logs then exits":
        ("""setInterval(() => refreshSubs().catch(e =>
      console.error('[channel] subscription refresh failed, keeping the ear:', e.message)),
      SUBS_REFRESH_MS)""",
         """setInterval(() => refreshSubs().catch(e => {
      console.error('[channel] subscription refresh failed:', e.message); process.exit(1) }),
      SUBS_REFRESH_MS)"""),

    # Survives every fault and hears nothing ever again: the LISTEN client's error handler
    # is what redials it. A wedged ear is worse than a dead one — it is indistinguishable
    # from a healthy one from the outside.
    "M5 listener stops crashing but stops reconnecting (WEDGED ear)":
        ("client.on('error', () => setTimeout(listen, 3000))",
         "client.on('error', () => {})"),
}
