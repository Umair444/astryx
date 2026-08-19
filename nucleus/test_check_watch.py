#!/usr/bin/env python3
"""Oracle for nucleus/check_watch.sh — the PRODUCER of the live-tree gate stamp.

    venv/bin/python nucleus/test_check_watch.py     (also run by nucleus/check.sh)

WHY THIS EXISTS. check_watch.sh runs the whole gate suite from a systemd timer and writes
one line that a pulse trigger then trusts completely. It is a parser and a classifier
wearing a shell script's clothes, and until this file it had no fixture at all — so both
of its bugs were found in production, on the live stamp:

  * a FAILING run prints no "N verified" line, so the happy-path parse yielded nothing and
    the stamp said "0 verified, 1 failed" over a run where 35 gates had passed
  * provenance was read from INVOCATION_ID, which systemd sets for a unit AND every child
    inherits — every resident body runs under astryx-residents.service, so a hand-typed run
    stamped by=timer and closed the owner gate that exists to say nothing is automatic

Both are the same class: a producer nothing runs in a fixture gets debugged in production,
and a classifier's wrong answers look exactly like right ones from the outside.

WHAT IS ASSERTED: that every outcome the runner can reach produces a stamp (a failing run
that dies before its write leaves the PREVIOUS success standing — restore_verify.sh was
read as proven for eight days that way), that the counts are recovered from the shape
check.sh actually prints on each path, and that provenance identifies the ACTOR rather
than an ancestor, failing to `hand` when it cannot tell.

HERMETIC: a stub suite via CHECK_WATCH_SUITE, a temp stamp and log, a fixture cgroup file.
The live stamp is never touched. The seam between this producer and its reader — real
bytes out of this script, into the real guard — is asserted in nucleus/test_check_stamp.py,
which is where the reader's absence in a clean checkout is already classified.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNER = Path(os.environ.get("CHECK_WATCH_SRC") or (REPO / "nucleus" / "check_watch.sh"))
HEAD_RE = re.compile(r"^(\S+) (\S+) rc=(-?\d+) verified=(\d+) failed=(\d+) unverified=(\d+)"
                     r"(?: by=(\S+))?$")
fails = []

GREEN = "\033[32m"
RESET = "\033[0m"


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        if detail:
            print(f"        {detail}")
        fails.append(name)


def run(tmp, suite, cgroup=None, stamp_name=".last-check"):
    """Drive the real runner against a stub suite. Returns (rc, head-fields, full stamp)."""
    stamp = tmp / stamp_name
    env = dict(os.environ)
    env["CHECK_WATCH_SUITE"] = suite
    env["CHECK_WATCH_STAMP"] = str(stamp)
    env["CHECK_WATCH_LOG"] = str(tmp / "log")
    env["CHECK_WATCH_CGROUP"] = str(cgroup) if cgroup else str(tmp / "no-such-cgroup")
    p = subprocess.run(["bash", str(RUNNER)], cwd=REPO, env=env,
                       capture_output=True, text=True)
    text = stamp.read_text() if stamp.exists() else ""
    m = HEAD_RE.match(text.splitlines()[0]) if text else None
    return p.returncode, m, text


if not RUNNER.exists():
    print(f"FAIL: {RUNNER} is absent — the live-tree runner is tracked, so this is a "
          f"finding, not a skip.")
    sys.exit(1)

print("the live-tree gate runner stamps an outcome that a trigger will believe:")

with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)

    # ── the clean path ─────────────────────────────────────────────────────────────
    rc, m, _ = run(tmp, 'echo "check: ALL CODE INVARIANTS PASS (39 gates verified)"')
    check("a clean suite stamps OK with the gate count recovered from the verdict",
          m and m.group(1) == "OK" and m.group(4) == "39", f"m={m and m.groups()}")
    check("...and exits 0 so a systemd unit does not report a false failure",
          rc == 0, f"rc={rc}")

    # ── provenance: the bug that closed an owner gate on itself ────────────────────
    check("a run with no unit cgroup is stamped by=hand",
          m and m.group(7) == "hand", f"m={m and m.groups()}")

    cg = tmp / "cgroup"
    cg.write_text("0::/system.slice/astryx-check.service\n")
    _, m2, _ = run(tmp, 'echo "check: ALL CODE INVARIANTS PASS (39 gates verified)"', cg)
    check("a run inside the check unit's own cgroup is stamped by=timer",
          m2 and m2.group(7) == "timer", f"m={m2 and m2.groups()}")

    cg_other = tmp / "cgroup-other"
    cg_other.write_text("0::/system.slice/astryx-residents.service\n")
    _, m3, _ = run(tmp, 'echo "check: ALL CODE INVARIANTS PASS (39 gates verified)"',
                   cg_other)
    check("a run inside ANOTHER unit is by=hand — provenance names the actor, not a parent",
          m3 and m3.group(7) == "hand",
          "INVOCATION_ID is inherited by every child; a resident body typing this by hand "
          "stamped by=timer and certified automation that did not exist")

    _, m4, _ = run(tmp, 'echo "check: ALL CODE INVARIANTS PASS (39 gates verified)"',
                   tmp / "definitely-absent")
    check("an UNREADABLE cgroup resolves to hand, not to timer (fail-safe direction)",
          m4 and m4.group(7) == "hand",
          "unknown provenance must nag about automation it cannot see, never certify it")

    # ── red ────────────────────────────────────────────────────────────────────────
    red_suite = ('printf "  \\342\\234\\227 ontology lint invariants\\n"; '
                 'printf "  \\342\\234\\227 tier floor invariants\\n"; '
                 'echo "check: FAILURES above"; exit 1')
    rc, m, text = run(tmp, red_suite)
    check("a failing suite stamps RED with the failure count",
          m and m.group(1) == "RED" and m.group(5) == "2", f"m={m and m.groups()}")
    check("...and NAMES the failing gates in the body, not just a number",
          "ontology lint invariants" in text and "tier floor invariants" in text,
          f"stamp={text!r}")
    check("...and propagates the failing exit code",
          rc == 1, f"rc={rc}")

    # The regression that reached the live stamp: a failing run prints no "N verified"
    # line at all, so the count has to come from the per-gate green lines instead.
    red_with_greens = (f'printf "{GREEN}  \\342\\234\\223 gate one{RESET}\\n"; '
                       f'printf "{GREEN}  \\342\\234\\223 gate two{RESET}\\n"; '
                       f'printf "{GREEN}  \\342\\234\\223 gate three{RESET}\\n"; '
                       'printf "  \\342\\234\\227 gate four\\n"; '
                       'echo "check: FAILURES above"; exit 1')
    _, m, _ = run(tmp, red_with_greens)
    check("a RED run still reports how many gates DID pass (no verdict line to parse)",
          m and m.group(4) == "3" and m.group(5) == "1",
          "a bare :-0 default stamped '0 verified' over a run where 35 gates passed")

    # ── amber ──────────────────────────────────────────────────────────────────────
    amber_suite = ('printf "  \\342\\227\\213 trigger bodies resolve\\n"; '
                   'echo "check: 38 verified, 1 UNVERIFIED"; exit 1')
    _, m, text = run(tmp, amber_suite)
    check("a run with skips and NO failures stamps AMBER, not RED",
          m and m.group(1) == "AMBER" and m.group(6) == "1", f"m={m and m.groups()}")
    check("...and names the unverified gates under their own header",
          "UNVERIFIED:" in text and "trigger bodies resolve" in text, f"stamp={text!r}")

    mixed = ('printf "  \\342\\234\\227 tier floor invariants\\n"; '
             'printf "  \\342\\227\\213 trigger bodies resolve\\n"; '
             'echo "check: FAILURES above"; exit 1')
    _, m, text = run(tmp, mixed)
    check("a run with BOTH a failure and a skip stamps RED — the louder of the two",
          m and m.group(1) == "RED" and m.group(5) == "1" and m.group(6) == "1",
          f"m={m and m.groups()}")
    check("...and keeps the two lists separate, so a failure cannot read as a mere skip",
          "FAILED:" in text and "UNVERIFIED:" in text, f"stamp={text!r}")

    # ── the suite dies ─────────────────────────────────────────────────────────────
    _, m, _ = run(tmp, "exit 2")
    check("a suite that dies before printing anything stamps RED-UNPARSED, not a clean 0",
          m and m.group(1) == "RED-UNPARSED",
          "'no failures parsed' must never become 'no failures' — the anti-vacuity rule")

    # ── the stamp is written on EVERY path ─────────────────────────────────────────
    stamp = tmp / "sequence"
    run(tmp, 'echo "check: ALL CODE INVARIANTS PASS (39 gates verified)"',
        stamp_name="sequence")
    _, m, _ = run(tmp, red_suite, stamp_name="sequence")
    check("a failing run OVERWRITES a previous success (no stale green left standing)",
          m and m.group(1) == "RED",
          "restore_verify.sh died before its write, left the last SUCCESS stamp intact, "
          "and doctor read mtime and called it proven for eight more days")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
