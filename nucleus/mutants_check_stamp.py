"""Authored mutants for triggers/steward/check_stamp.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py nucleus/mutants_check_stamp.py

THE LIST IS THE JUDGEMENT, WHICH IS WHY IT IS AUTHORED. Every entry is a way a guard of
this shape has ALREADY failed in this org, transplanted onto the new one. That is the
point of writing them before anything regresses: this guard was built in one evening, and
its whole value is that it keeps speaking about a suite nobody watches — so the mutations
worth authoring are the ones that make it go QUIET while still returning cleanly.

M1 is pii_sweep's warn-once (a live finding sat 22 days). M2 is the arm that makes silence
mean something — without it the guard cannot distinguish a clean run from a dead runner.
M4/M5 are the dedup shapes that have cost this org twice: state not cleared by a repair,
and a key too coarse to see a set grow.

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list; the probe reports CAUGHT or
NOT PROBED, never "vacuous". The subject is gitignored (`triggers/`), so in a clean
checkout this file names an estate the repo deliberately does not carry —
nucleus/test_mutants_wellformed.py classifies that rather than assuming it.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "triggers" / "steward" / "check_stamp.py"
ORACLE = REPO / "nucleus" / "test_check_stamp.py"
ENV = "CHECK_STAMP_SRC"

MUTANTS = {
    # Warn-once, restored. The red is still detected and still announced the first time —
    # and then never again, however long it stands. This is the exact shape that let a
    # live PII finding sit unmentioned for 22 days, and it reads as a working guard.
    "M1 a standing red never re-nags (band clock ignored)":
        ('        if key == st.get("red_key") and b <= st.get("red_band", -1):',
         '        if key == st.get("red_key"):'),

    # The staleness arm dies. Every assertion about RED still passes, so the guard looks
    # healthy — but a runner that stopped four days ago now produces exactly the same
    # observable as a suite that ran clean an hour ago: silence.
    "M2 a stopped runner is indistinguishable from a clean one":
        ("    if age > STALE_DAYS:", "    if age > 99999:"),

    # Garbage in the stamp becomes an all-clear. Unknown must resolve to WATCHED for a
    # detector; here it resolves to silence, which is the one direction that cannot be
    # noticed from the outside.
    "M3 an unreadable stamp is treated as fine":
        ('        st["unreadable"] = True', "        return None"),

    # The repair does not clear the red state, so the NEXT occurrence of the same failure
    # is deduped against a finding that was already fixed. The guard goes quiet precisely
    # on a regression — the case it exists for.
    # The repair does not re-arm the band, so the NEXT occurrence of the same failure is
    # deduped against a finding that was already fixed. The guard goes quiet precisely on
    # a regression — the case it exists for.
    # THIS MUTANT WAS RE-AIMED. It first pointed at a second, redundant clear of red_key
    # and came back NOT PROBED — correctly, because that line could not change an outcome.
    # The probe's finding was about the SUBJECT (two writers of one fact, one dead), not
    # about a hole in the oracle; the dead writer is gone and the mutant now points at the
    # line that actually carries the discharge.
    "M4 a repair does not re-arm the band, so a recurrence is swallowed":
        ('    st["red_band"] = -1', "    pass"),

    # Dedup key coarsened to the status alone: a red that GROWS from two failing gates to
    # three says nothing, because it is still just "RED". Dedup on the entity set, not the
    # transition — a coarse key drops late joiners.
    "M5 dedup key ignores WHICH gates failed":
        ('        key = f"{status}|{body}"', "        key = status"),

    # The positive-observation record disappears. The guard still behaves correctly, so
    # nothing fires — but its state no longer proves it ever looked, and a guard whose
    # silence carries no evidence of the last observation is indistinguishable from one
    # that has never run.
    "M6 a clean run leaves no evidence that anything was observed":
        ('    st["last_ok"] = ts_s', "    pass"),

    # The persistence discriminator removed, so every transient skip wakes someone.
    # check.sh is not deterministic over identical bytes — a nested 180s probe times out on
    # a loaded host — and a guard that alarms on that teaches people to re-run until green,
    # which is the failure a3's 77-instead-of-FAILED fix had just prevented one layer down.
    "M7 a single transient skip alarms (persistence discriminator gone)":
        ("        if not persist:", "        if False:"),

    # Intersection becomes union, so ANY gate skipped in either of two runs reads as
    # persistent. The alarm still fires, still names gates, still looks right — and now
    # says "this host can no longer observe X" about a one-off timeout.
    "M8 persistence is a UNION, so a transient skip reads as standing":
        ('        st["amber_persist"] = sorted(cur & prev)',
         '        st["amber_persist"] = sorted(cur | prev)'),

    # UNVERIFIED silently rejoins the pass path: a gate that reported it could check
    # NOTHING, on the one machine where its subject exists, produces no alarm at all. This
    # is A SKIP IS NOT A PASS deleted from the one guard whose whole subject is a suite
    # that distinguishes the two.
    "M9 an unverified gate is treated as a passing one":
        ('    if status == "AMBER":', "    if False:"),
}
