#!/usr/bin/env python3
"""Oracle for nucleus/check.sh's SKIP accounting — the verdict may never out-claim its parts.

    venv/bin/python tests/test_check_verdict.py      (also run by nucleus/check.sh)

THE DEFECT THIS PINS, reproduced on a clean checkout of HEAD on 2026-08-14: check.sh ran
its full suite, five gates verified NOTHING — two of them because the trigger BODY under
test was absent from the artifact entirely — and it printed `ALL CODE INVARIANTS PASS` and
exited 0. Every one of those oracles announced its skip honestly on stdout. The AGGREGATE
verdict, the single line a human or a CI badge reads, out-claimed all five of them.

It is the second blind spot in that file and the same shape as the first, one level down.
The first was "is every oracle INVOKED" (test_check_coverage.py, 08-13). This is "did every
invoked oracle actually RUN." A suite can only ever assert about what it can OBSERVE, and
check.sh could not observe the difference between a gate that passed and a gate that never
executed, because both arrived as exit 0.

WHAT IS ASSERTED HERE, and why against the REAL file. This sources nucleus/check.sh with
CHECK_LIB_ONLY=1 — which returns before any real gate runs — and then drives the actual
run()/skip()/verdict() functions with SYNTHETIC gates. A reimplementation of the classifier
here would prove only that this file agrees with itself; the whole reason the original
defect survived is a verifier that shared its subject's assumptions
(cf. tests/test_card_canon.py, where the card's own signer was its own verifier).

The protocol: an oracle that verified LESS THAN IT CLAIMS exits 77 (GNU automake's SKIP
convention). Two independent mechanisms enforce it, and BOTH must fail for a vacuous gate
to read green:
  1. the exit code — primary, explicit, silent-proof;
  2. the belt — a gate that ANNOUNCES a skip (a line whose first token is SKIP or ○) and
     still exits 0 is counted UNVERIFIED and reported as a protocol violation. It covers
     oracles that never adopted the convention, which is how the two gates in files this
     author never touched were caught.
The belt can only ever ADD strictness: it upgrades 0 -> 77 and never downgrades a failure,
so `test_a_failure_cannot_launder_itself_as_a_skip` is the load-bearing case.

RESIDUAL, named rather than papered over: a gate that skips SILENTLY — no announcement and
no 77 — is invisible to both mechanisms and still reads as a pass. That is undecidable from
the outside; it needs the oracle's author to be honest at the point of skipping. The
mechanisms narrow the gap to that one case rather than closing it.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "nucleus" / "check.sh"

fails: list[str] = []


def drive(body: str, env: str = "") -> tuple[str, int]:
    """Source the REAL check.sh (definitions only) and run `body` against its functions.

    The child env is SCRUBBED of CHECK_ALLOW_SKIP rather than inherited. Caught by this
    oracle's own first run on a CI-shaped clone: the workflow sets CHECK_ALLOW_SKIP=1, the
    variable leaked into every drive(), and six cases that assert STRICT behaviour flipped
    green-to-red purely from ambient environment. A test whose verdict depends on where it
    is run is the same defect class this file exists to pin — so the strict/allow axis is
    set here explicitly, per case, and never read from the outside.
    """
    child = {k: v for k, v in os.environ.items() if k != "CHECK_ALLOW_SKIP"}
    script = f'CHECK_LIB_ONLY=1 source "{CHECK}"\nunset CHECK_LIB_ONLY\n{env}\n{body}\nverdict\n'
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       cwd=REPO, env=child)
    return p.stdout + p.stderr, p.returncode


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {label}")
    else:
        fails.append(label)
        print(f"  ✗ {label}{': ' + detail if detail else ''}")


# ── the sourcing hook itself: if this breaks, every case below is vacuous ──────────────
_out, _rc = drive('true')
check("check.sh can be sourced without running its real gates",
      _rc == 0 and "charter resolver" not in _out,
      "CHECK_LIB_ONLY must return before the gate list")

# ── 1. classification ─────────────────────────────────────────────────────────────────
out, rc = drive('run "g" bash -c "exit 0"')
check("a gate that exits 0 silently is VERIFIED",
      "ALL CODE INVARIANTS PASS (1 gates verified)" in out and rc == 0, out)

out, rc = drive('run "g" bash -c "exit 77"')
check("a gate that exits 77 is UNVERIFIED even when it says nothing",
      "1 UNVERIFIED" in out and "○ g" in out and rc == 1, out)

out, rc = drive('run "g" bash -c "exit 3"')
check("a gate that exits nonzero-but-not-77 is a FAILURE",
      "FAILED (1)" in out and rc == 1, out)

# ── 2. the belt ───────────────────────────────────────────────────────────────────────
for marker in ("SKIP: prerequisite absent", "  ○ skipped, no database", "SKIP"):
    out, rc = drive(f'run "g" bash -c \'echo "{marker}"; exit 0\'')
    check(f"announcing {marker.strip()[:12]!r} and exiting 0 is a PROTOCOL violation",
          "PROTOCOL" in out and "1 UNVERIFIED" in out and rc == 1, out)

out, rc = drive('run "g" bash -c \'echo "SKIP: cannot run"; exit 1\'')
check("a failure cannot launder itself as a skip",
      "FAILED (1)" in out and "PROTOCOL" not in out and rc == 1, out)

# ── 3. the belt must be NARROW — a real passing suite says these words ────────────────
for benign in ("  ok   i_skipped_rank_is_the_next",
               "this run skipped nothing",
               "note: FOR UPDATE SKIP LOCKED is used here"):
    out, rc = drive(f'run "g" bash -c \'echo "{benign}"; exit 0\'')
    check(f"a PASSING gate printing {benign.strip()[:22]!r} stays verified",
          "ALL CODE INVARIANTS PASS" in out and rc == 0, out)

# ── 4. an absent prerequisite is unverified, never silently omitted ───────────────────
out, rc = drive('skip "g" "av not installed"')
check("skip() records an unrun gate rather than dropping it",
      "1 UNVERIFIED" in out and "av not installed" in out and rc == 1, out)

# ── 5. THE INVARIANT: the verdict may never out-claim its parts ───────────────────────
out, rc = drive('run "a" bash -c "exit 0"; run "b" bash -c "exit 77"')
check("'ALL' is never spoken while any gate is unverified",
      "ALL CODE INVARIANTS PASS" not in out and "1 verified, 1 UNVERIFIED" in out, out)
check("every unverified gate is NAMED in the verdict, not just counted",
      "○ b" in out, out)

out, rc = drive('run "a" bash -c "exit 0"; run "b" bash -c "exit 77"',
                env='CHECK_ALLOW_SKIP=1')
check("CHECK_ALLOW_SKIP downgrades to amber but still refuses to claim ALL",
      rc == 0 and "NOT a full pass" in out and "ALL CODE INVARIANTS PASS" not in out, out)
check("an allowed skip is still NAMED, so the log says what went unchecked",
      "○ b" in out, out)

out, rc = drive('run "a" bash -c "exit 1"; run "b" bash -c "exit 77"',
                env='CHECK_ALLOW_SKIP=1')
check("CHECK_ALLOW_SKIP never rescues a real FAILURE",
      rc == 1 and "FAILURES above" in out, out)

# ── 6. strictness is the DEFAULT: the opt-out must be explicit ────────────────────────
out, rc = drive('run "g" bash -c "exit 77"', env='CHECK_ALLOW_SKIP=')
check("an EMPTY CHECK_ALLOW_SKIP is not an opt-out (only a set value is)",
      rc == 1, "an unset-vs-empty confusion would silently disarm the default")

print()
if fails:
    print(f"CHECK-VERDICT ORACLE FAILED ({len(fails)}):", file=sys.stderr)
    for f in fails:
        print(f"  ✗ {f}", file=sys.stderr)
    sys.exit(1)
print("check.sh accounting: a skip is not a pass, the belt is narrow, the verdict "
      "cannot out-claim its parts ✓")
sys.exit(0)
