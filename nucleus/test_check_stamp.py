#!/usr/bin/env python3
"""Oracle for triggers/steward/check_stamp.py — the guard that reads the live-tree stamp.

    venv/bin/python nucleus/test_check_stamp.py     (also run by nucleus/check.sh)

THE SUBJECT'S JOB. nucleus/check_watch.sh runs the full gate suite on the LIVE tree from a
systemd timer (the only place the gitignored guard estate exists — CI and the push hook
both run check.sh inside a clone, where 20 of 36 gates cannot run at all) and stamps the
OUTCOME to backups/.last-check. This guard reads that stamp on the pulse. The split exists
because the suite takes ~60s and the pulse kills a trigger at 30s.

WHAT IS ACTUALLY ASSERTED HERE, and each line is a way a guard of this shape has failed in
this org before:
  * a RED suite is announced, and RE-NAGGED on widening bands — a failing invariant is a
    CONDITION, not an event (warn-once let a live pii_sweep finding sit 22 days)
  * a red whose FAILING SET CHANGES speaks immediately, not on the band clock: a different
    set is new information, and dedup belongs on the entity set, not on the transition
  * a STALE stamp is announced. This is the arm that makes the guard's SILENCE mean
    something: without it, "checked today, clean" and "nobody has run it since Tuesday"
    are the same observable — a guard whose quiet cannot be distinguished from a dead
    runner is decoration
  * ABSENCE IS CLASSIFIED, not read as health OR as fault. No stamp means the runner has
    never completed, which on this host means an unenabled timer — an OWNER-GATE state,
    which re-nags on its own slower ladder because the only independent re-reader of an
    un-enabled unit is the owner's attention
  * an UNREADABLE stamp is WATCHED, never all-clear (unknown -> watched, the fail-safe
    polarity for a detector)
  * a clean, fresh run leaves POSITIVE EVIDENCE of the observation in state, so a later
    reader can tell "looked, all clear" from "never looked"

HERMETIC: a temp stamp file, a fake ctx, and timestamps written into the past. No clock is
injected because none needs to be — every age in the subject is derived from a value this
oracle controls. The subject lives under the gitignored triggers/ estate, so on a clean
checkout it is ABSENT: classified with `git check-ignore` (ignored -> SKIP 77, tracked but
missing -> FAIL) rather than assumed either way.
"""
import json
import os
import runpy
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("CHECK_STAMP_SRC") or
               (REPO / "triggers" / "steward" / "check_stamp.py"))
EXIT_SKIP = 77
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        if detail:
            print(f"        {detail}")
        fails.append(name)


def load_subject():
    if SUBJECT.exists():
        sys.path.insert(0, str(REPO))          # the subject imports triggers.steward.bands
        return runpy.run_path(str(SUBJECT))
    rc = subprocess.run(["git", "check-ignore", "-q", str(SUBJECT)],
                        cwd=REPO, capture_output=True).returncode
    if rc == 0:
        print(f"SKIP: {SUBJECT} is absent and GITIGNORED — this checkout deliberately does "
              f"not carry the guard estate. Nothing was verified here.")
        sys.exit(EXIT_SKIP)
    print(f"FAIL: {SUBJECT} is absent and NOT ignored ({rc=}) — a tracked guard has "
          f"vanished, which is a finding, not a skip.")
    sys.exit(1)


class FakeCtx:
    def __init__(self, state=None):
        self.state = state if state is not None else {}

    def sql(self, *a, **k):                     # unused by this guard; present so a future
        return []                               # query fails loudly rather than silently


def iso(days_ago):
    return (datetime.now(timezone.utc)
            - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(mod, tmp, state, stamp_text=None):
    """Run the guard with STAMP pointed at a temp file. NOT `mod["STAMP"] = ...`:
    runpy.run_path hands back a COPY of the module globals, so writing to that dict
    repoints nothing and the guard reads the REAL stamp — a test that quietly tests the
    live host instead of its fixture (caught the hard way on pii_sweep, 2026-08-16)."""
    stamp = tmp / ".last-check"
    if stamp_text is None:
        stamp.unlink(missing_ok=True)
    else:
        stamp.write_text(stamp_text)
    mod["check_stamp"].__globals__["STAMP"] = stamp
    ctx = FakeCtx(json.loads(json.dumps(state)))
    return mod["check_stamp"](ctx), ctx.state


mod = load_subject()
print("the live-tree check guard cannot go quiet on a red, a stale, or a missing suite:")

with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)

    # ── absence: the owner-gate state ──────────────────────────────────────────────
    out, st = run(mod, tmp, {})
    check("no stamp at all is announced as NEVER RUN, not as health",
          out and "NEVER RUN" in out, f"out={out!r}")
    check("...and it carries the exact command that fixes it",
          out and "systemctl enable" in out and "astryx-check.timer" in out, f"out={out!r}")
    check("...and it is framed as an owner gate, not an agent fault",
          out and "owner-gate" in out.lower(), f"out={out!r}")

    out2, st2 = run(mod, tmp, st)
    check("the same absence on the next tick is silent (no drumbeat)",
          out2 is None, f"out={out2!r}")

    aged = dict(st, never_first=(datetime.now(timezone.utc)
                                 - timedelta(days=9)).isoformat())
    out3, _ = run(mod, tmp, aged)
    check("...but an OLDER absence crosses a band and speaks again",
          out3 is not None, "an unenabled runner that goes permanently quiet is warn-once")

    # ── clean and fresh ────────────────────────────────────────────────────────────
    ok_now = f"OK {iso(0.1)} rc=0 verified=36 failed=0 unverified=0\n"
    out, st = run(mod, tmp, {}, ok_now)
    check("a fresh clean run is silent", out is None, f"out={out!r}")
    check("...and leaves POSITIVE evidence of the observation in state",
          st.get("last_ok") and st.get("last_ok_verified") == 36, f"state={st}")

    # ── stale ──────────────────────────────────────────────────────────────────────
    out, st_stale = run(mod, tmp, {}, f"OK {iso(4)} rc=0 verified=36 failed=0 unverified=0\n")
    check("an OK stamp four days old is announced as STOPPED RUNNING",
          out and "STOPPED RUNNING" in out, f"out={out!r}")
    check("...and does not claim the suite is failing (it is not — nobody is running it)",
          out and "RED" not in out, f"out={out!r}")
    out2, _ = run(mod, tmp, st_stale, f"OK {iso(4)} rc=0 verified=36 failed=0 unverified=0\n")
    check("a stale stamp at the same age is silent on the next tick",
          out2 is None, f"out={out2!r}")

    # ── red ────────────────────────────────────────────────────────────────────────
    red_a = (f"RED {iso(0.1)} rc=1 verified=34 failed=2 unverified=0\n"
             "FAILED:\n  ontology lint invariants\n  tier floor invariants\n")
    out, st_red = run(mod, tmp, {}, red_a)
    check("a red suite is announced", out and "RED" in out, f"out={out!r}")
    check("...naming the gates that failed, not just a count",
          out and "ontology lint invariants" in out and "tier floor invariants" in out,
          f"out={out!r}")
    check("...and saying these gates run nowhere else",
          out and "clone" in out, f"out={out!r}")

    out2, st_red2 = run(mod, tmp, st_red, red_a)
    check("the SAME red on the next tick is silent (band, not drumbeat)",
          out2 is None, f"out={out2!r}")

    red_b = (f"RED {iso(0.1)} rc=1 verified=33 failed=3 unverified=0\n"
             "FAILED:\n  ontology lint invariants\n  tier floor invariants\n  world layer\n")
    out3, _ = run(mod, tmp, st_red2, red_b)
    check("a red whose FAILING SET GREW speaks immediately, not on the band clock",
          out3 is not None and "world layer" in out3,
          "dedup on the entity SET, not the transition — a coarse key drops late joiners")

    aged_red = dict(st_red, red_band=0)
    out4, _ = run(mod, tmp, aged_red,
                  (f"RED {iso(5)} rc=1 verified=34 failed=2 unverified=0\n"
                   "FAILED:\n  ontology lint invariants\n  tier floor invariants\n"))
    check("...and an OLD standing red crosses a band and re-nags",
          out4 is not None, "a standing failure that warns once is the 22-day defect")

    # ── discharge, then recurrence ─────────────────────────────────────────────────
    _, st_clean = run(mod, tmp, st_red, ok_now)
    out5, _ = run(mod, tmp, st_clean, red_a)
    check("a red that returns AFTER a clean run is announced again, not deduped away",
          out5 is not None, "state from the last red must be cleared by the repair")

    # ── amber: unverified, which is neither a pass nor a failure ───────────────────
    amber1 = (f"AMBER {iso(1.0)} rc=1 verified=35 failed=0 unverified=1\n"
              "UNVERIFIED:\n  ontology lint invariants\n")
    out, st_a1 = run(mod, tmp, {}, amber1)
    check("ONE unverified gate is not an alarm (a loaded host times a nested probe out)",
          out is None, f"out={out!r}")
    check("...but it is REMEMBERED, so a second run can tell persistent from transient",
          st_a1.get("amber_set") == ["ontology lint invariants"], f"state={st_a1}")

    amber2 = (f"AMBER {iso(0.1)} rc=1 verified=35 failed=0 unverified=1\n"
              "UNVERIFIED:\n  ontology lint invariants\n")
    out, st_a2 = run(mod, tmp, st_a1, amber2)
    check("the SAME gate unverified on two consecutive runs IS announced",
          out and "ontology lint invariants" in out, f"out={out!r}")
    check("...and says explicitly that nothing FAILED — a skip is a third state",
          out and "Nothing FAILED" in out, f"out={out!r}")

    out2, _ = run(mod, tmp, st_a2, amber2)
    check("re-reading the SAME stamp does not count as another run",
          out2 is None, "the trigger fires 6x/day and the runner once — a stamp is one run")

    amber_other = (f"AMBER {iso(0.1)} rc=1 verified=35 failed=0 unverified=1\n"
                   "UNVERIFIED:\n  media in-process decode\n")
    out3, _ = run(mod, tmp, st_a1, amber_other)
    check("a DIFFERENT gate unverified next run is transient, not persistent",
          out3 is None, f"out={out3!r}")

    _, st_ok = run(mod, tmp, st_a2, ok_now)
    out4, _ = run(mod, tmp, st_ok, amber1)
    check("a clean run re-arms amber too (no stale persistence carried past a repair)",
          out4 is None, f"out={out4!r}")

    mixed = (f"RED {iso(0.1)} rc=1 verified=34 failed=1 unverified=1\n"
             "FAILED:\n  tier floor invariants\n"
             "UNVERIFIED:\n  ontology lint invariants\n")
    out5, _ = run(mod, tmp, {}, mixed)
    check("a stamp with BOTH a failure and a skip is reported as RED, not amber",
          out5 and "tier floor invariants" in out5 and "RED" in out5, f"out={out5!r}")

    # ── unreadable ─────────────────────────────────────────────────────────────────
    out, st_bad = run(mod, tmp, {}, "")
    check("an EMPTY stamp is WATCHED, never read as all-clear",
          out and "UNREADABLE" in out, f"out={out!r}")
    out, _ = run(mod, tmp, {}, "check ran fine :)\n")
    check("a stamp in an unknown FORMAT is watched too",
          out and "UNREADABLE" in out, f"out={out!r}")
    check("...and says explicitly that it is not an all-clear",
          out and "not an all-clear" in out, f"out={out!r}")

    out, _ = run(mod, tmp, {},
                 f"RED-UNPARSED {iso(0.1)} rc=2 verified=0 failed=0 unverified=0\n")
    check("a run that died before printing a verdict is RED, not a clean zero-failure pass",
          out is not None and "RED" in out, f"out={out!r}")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
