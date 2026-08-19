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
    ok_now = f"OK {iso(0.1)} rc=0 verified=36 failed=0 unverified=0 by=timer\n"
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

    # BOTH READINGS STALE, so the qualifier set is identical and the KEY cannot be what
    # speaks — only the band can. (A fixture where the qualifiers also change would pass
    # even with the band clock deleted, which is the mutant this discriminates.)
    stale_red = lambda d: (f"RED {iso(d)} rc=1 verified=34 failed=2 unverified=0 by=timer\n"
                           "FAILED:\n  ontology lint invariants\n  tier floor invariants\n")
    _, st_s = run(mod, tmp, {"last_timer_ts": iso(4)}, stale_red(4))
    out4, _ = run(mod, tmp, st_s, stale_red(10))
    check("...and an OLD standing red crosses a band and re-nags on the SAME key",
          out4 is not None, "a standing failure that warns once is the 22-day defect")

    # ── discharge, then recurrence ─────────────────────────────────────────────────
    # TIMER-STAMPED THROUGHOUT: ok_now records automation evidence, so a red without a
    # by= field would come back carrying a different qualifier set and be announced for
    # that reason alone — passing this assertion while the band reset was gone.
    timer_red = (f"RED {iso(0.1)} rc=1 verified=34 failed=2 unverified=0 by=timer\n"
                 "FAILED:\n  ontology lint invariants\n  tier floor invariants\n")
    _, st_t0 = run(mod, tmp, {}, timer_red)
    _, st_clean = run(mod, tmp, st_t0, ok_now)
    out5, _ = run(mod, tmp, st_clean, timer_red)
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

    # ── green, and still not automatic ─────────────────────────────────────────────
    # The arm that exists because running the suite BY HAND to test the runner silenced the
    # arm above it. Provenance decides this one, not freshness: a hand run proves the gates
    # are green at that instant and proves nothing about whether anything runs them again.
    hand_now = f"OK {iso(0.1)} rc=0 verified=39 failed=0 unverified=0 by=hand\n"
    out, st_h = run(mod, tmp, {}, hand_now)
    check("a fresh GREEN stamp written BY HAND still says the suite is not automatic",
          out and "NEVER RUN AUTOMATICALLY" in out, f"out={out!r}")
    check("...and carries the one line that fixes it",
          out and "systemctl enable" in out and "astryx-check.timer" in out, f"out={out!r}")
    check("...while saying the green itself is real, not a failure",
          out and "39 gates verified" in out and "RED" not in out, f"out={out!r}")

    out2, _ = run(mod, tmp, st_h, hand_now)
    check("the same by-hand stamp is silent on the next tick (slow ladder, not a drumbeat)",
          out2 is None, f"out={out2!r}")

    legacy = f"OK {iso(0.1)} rc=0 verified=36 failed=0 unverified=0\n"
    out3, st_l = run(mod, tmp, {}, legacy)
    check("a stamp with NO provenance field parses, and does NOT count as automation",
          out3 is not None and "NEVER RUN AUTOMATICALLY" in out3,
          "unknown provenance must not prove the thing the field was added to prove")
    check("...and the legacy stamp is still read for its OUTCOME (a format change is a "
          "migration; the first tick runs against the predecessor's format)",
          st_l.get("last_ok_verified") == 36, f"state={st_l}")

    out4, st_t = run(mod, tmp, {}, ok_now)
    check("a TIMER-written green stamp is silent and records the automation evidence",
          out4 is None and st_t.get("last_timer_ts"), f"out={out4!r} state={st_t}")
    out5, _ = run(mod, tmp, st_t, hand_now)
    check("...and a later hand run does not re-open a gate the owner already cleared",
          out5 is None, f"out={out5!r}")

    stale_timer = dict(st_t, last_timer_ts=iso(6))
    out6, _ = run(mod, tmp, stale_timer, hand_now)
    check("a DEAD timer kept green by hand is announced — the diligent human is the mask",
          out6 and "TIMER HAS STOPPED" in out6,
          "staleness measured on the newest stamp alone lets manual runs hide a dead unit")

    # ── the reading is not the suite (abstractor-2, msg 11875) ─────────────────────
    # RED was absorbing: both arms that describe the READING — how old it is, whether
    # anything automatic produced it — sat below it in a first-match ladder. For four days
    # this guard emitted the same RED naming a gate that had been green since 546bb14, and
    # never once said "this reading is four days old". A stale OK escalates correctly; a
    # stale RED could not, because only a run clears a red and the arm carrying the sudo
    # line for the runner sat underneath.
    old_red = (f"RED {iso(4)} rc=1 verified=34 failed=2 unverified=0 by=timer\n"
               "FAILED:\n  ontology lint invariants\n  tier floor invariants\n")
    out, _ = run(mod, tmp, {"last_timer_ts": iso(4)}, old_red)
    check("a STALE red still reports the failure",
          out and "ontology lint invariants" in out, f"out={out!r}")
    check("...AND says the reading is old, instead of implying it is current",
          out and "LAST KNOWN" in out and "4.0d OLD" in out,
          "only a run can clear a red, so a red that cannot escalate on age is a lie "
          "that repeats on the band clock")

    fresh_red = (f"RED {iso(0.1)} rc=1 verified=34 failed=2 unverified=0 by=timer\n"
                 "FAILED:\n  ontology lint invariants\n  tier floor invariants\n")
    out, _ = run(mod, tmp, {"last_timer_ts": iso(0.1)}, fresh_red)
    check("...while a FRESH red claims no such thing",
          out and "LAST KNOWN" not in out, f"out={out!r}")

    # BY HAND, deliberately: the point is a red on a host where nothing is scheduled to
    # produce the next run. A by=timer stamp is itself the evidence that something is.
    hand_red = (f"RED {iso(0.1)} rc=1 verified=34 failed=2 unverified=0 by=hand\n"
                "FAILED:\n  ontology lint invariants\n  tier floor invariants\n")
    out, _ = run(mod, tmp, {}, hand_red)
    check("a red on a host where nothing is scheduled carries the sudo line with it",
          out and "systemctl enable" in out and "NOTHING AUTOMATIC" in out,
          "the timer is what MAKES the run that would clear this red")

    # THE QUALIFIERS MUST BE IN THE DEDUP KEY, and this fixture is built so that nothing
    # ELSE can carry the signal: 1.2d and 2.0d sit in the SAME band (rungs are 0/1/3/7/14)
    # while STALE_DAYS is 1.5, so the band clock does not move and the failing set does not
    # change. The only difference between the two readings is that the second one is stale.
    band_red = lambda d: (f"RED {iso(d)} rc=1 verified=34 failed=2 unverified=0 by=timer\n"
                          "FAILED:\n  ontology lint invariants\n  tier floor invariants\n")
    _, st_r = run(mod, tmp, {"last_timer_ts": iso(1.2)}, band_red(1.2))
    out, _ = run(mod, tmp, st_r, band_red(2.0))
    check("a standing red that CROSSES INTO stale speaks again — same set, same band",
          out is not None and "LAST KNOWN" in out,
          "the qualifiers of a reading have to be part of its dedup key, or the moment "
          "the reading stops being current is invisible")

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

    # ── THE SEAM: real bytes out of the producer, into this real reader ────────────
    # Every assertion above feeds this guard a stamp I wrote by hand, which tests my BELIEF
    # about the format. The seam belongs to no contributor: nucleus/test_check_watch.py
    # proves the runner writes what it intends, this file proves the guard reads what it
    # expects, and neither notices if the two intentions differ by one token. So here the
    # producer is actually executed and its output goes in unedited.
    runner = REPO / "nucleus" / "check_watch.sh"

    def produce(suite, cgroup_text="0::/system.slice/astryx-residents.service\n"):
        env = dict(os.environ)
        cg = tmp / "seam-cgroup"
        cg.write_text(cgroup_text)
        env.update(CHECK_WATCH_SUITE=suite,
                   CHECK_WATCH_STAMP=str(tmp / "seam-stamp"),
                   CHECK_WATCH_LOG=str(tmp / "seam-log"),
                   CHECK_WATCH_CGROUP=str(cg))
        subprocess.run(["bash", str(runner)], cwd=REPO, env=env, capture_output=True)
        return (tmp / "seam-stamp").read_text()

    if not runner.exists():
        check("the live-tree runner exists to be read from", False,
              f"{runner} is tracked; its absence is a finding, not a skip")
    else:
        real_red = produce('printf "  \\342\\234\\227 tier floor invariants\\n"; '
                           'echo "check: FAILURES above"; exit 1')
        out, _ = run(mod, tmp, {}, real_red)
        check("SEAM: a stamp the REAL runner wrote for a failing suite alarms here",
              out and "tier floor invariants" in out, f"stamp={real_red!r} out={out!r}")

        real_hand = produce('echo "check: ALL CODE INVARIANTS PASS (39 gates verified)"')
        out, _ = run(mod, tmp, {}, real_hand)
        check("SEAM: a REAL by-hand green stamp still says the suite is not automatic",
              out and "NEVER RUN AUTOMATICALLY" in out,
              f"stamp={real_hand!r} out={out!r}")

        real_timer = produce('echo "check: ALL CODE INVARIANTS PASS (39 gates verified)"',
                             "0::/system.slice/astryx-check.service\n")
        out, st_seam = run(mod, tmp, {}, real_timer)
        check("SEAM: a REAL timer-written green stamp is silent — one token, both sides",
              out is None and st_seam.get("last_timer_ts"),
              f"stamp={real_timer!r} out={out!r} state={st_seam}")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
