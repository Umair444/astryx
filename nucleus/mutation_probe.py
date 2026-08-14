#!/usr/bin/env python3
"""astryx · mutation-probe — WHICH WRONG IMPLEMENTATIONS DOES THIS ORACLE FAIL TO NOTICE?

    venv/bin/python nucleus/mutation_probe.py nucleus/mutants_wedge_watch.py
    venv/bin/python nucleus/mutation_probe.py --self-test

An authoring-time instrument, NOT a check.sh gate (steward's ruling, msg 5934: gating taxes
every future oracle for one night of evidence; revisit once this has caught something in a
file nobody was already repairing).

WHY IT EXISTS. The governing law is "after writing an assertion, ask what implementation
would make it fail; if the answer is none, it is documentation." On 2026-08-14 steward and
I each filed that law and each then shipped a vacuous assertion in our own oracle within
two hours — steward a tautology comparing the function under test to itself, me a fixture
no assertion read, plus two assertions that ran, passed, and never reached the code they
named. Neither of us found it by eye. A discipline that fails in the hands of the people
who wrote it needs a machine. This builds the wrong implementation and runs it, instead of
asking a human to imagine one.

The two subtle forms, both of which read as rigour on the page:
  * A COUNTEREXAMPLE ONLY DISCRIMINATES IF THE TWO CANDIDATE IMPLEMENTATIONS DISAGREE ON
    IT. Mine compared the right and wrong numerator on the single input where they agreed.
  * A FIXTURE EXCLUDED BY THE WRONG CLAUSE TESTS THE WRONG CLAUSE. Mine was filtered out by
    a rate gate before the span floor it was aimed at was ever consulted.

═══ WHAT IT MAY AND MAY NOT SAY (condition 2 of the ruling, ENCODED not remembered) ═══
It reports CAUGHT or NOT PROBED BY THIS MUTANT SET. It may NEVER say "vacuous", and there
is no code path that emits that word as a verdict. Catches-nothing is meaningful only
relative to the mutations actually tried: on the run that motivated this tool, 11 of 21
assertions caught none of the seven mutants purely because all seven targeted one branch.
That is a deficient mutant set, not a dead assertion. The instrument fails toward UNKNOWN —
the same polarity every other detector here uses (unknown -> watched, never -> clear).
If it could say "vacuous", someone would eventually delete a good assertion on its word.

═══ WHY IT RUNS THE REAL ORACLE AS A SUBPROCESS ═══
The obvious design re-lists the oracle's assertions inside the probe. I wrote that version
first and it was WRONG IN THE SAME WAY IT EXISTS TO CATCH: it scored 7 of the oracle's 21
assertions and reported a mutant as surviving that the full oracle catches three ways. I
had the report half-written. An incomplete harness is a claim too, and a verification tool
is the artifact class whose own coverage nobody checks. So the probe never enumerates
assertions — it runs the oracle exactly as check.sh does and reads its exit code. Complete
by construction, and it inherits new assertions for free.

A surviving mutant means: every assertion in that oracle passed against an implementation
known to be wrong. Which assertion should have caught it is for the author to decide.

═══ THE CONTRACT AN OPTED-IN ORACLE MUST MEET ═══
Read its subject's path from an environment variable, defaulting to the real one:

    SUBJECT = Path(os.environ.get("WEDGE_WATCH_SRC", REPO / "triggers/seed/wedge_watch.py"))

The mutants file beside it declares SUBJECT, ORACLE, ENV and MUTANTS. The mutant list is
the judgement-carrying part and is authored per oracle on purpose: a generic mutator emits
mostly equivalent mutants and drowns the signal, whereas an authored list encodes what the
author believes could plausibly be wrong. That belief is reviewable; a generic one is not.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXIT_SKIP = 77


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_oracle(oracle: Path, env_var: str, subject_path: Path) -> int:
    env = dict(os.environ, **{env_var: str(subject_path)})
    r = subprocess.run([sys.executable, str(oracle)], env=env,
                       capture_output=True, text=True, timeout=120)
    return r.returncode


def probe(spec_path: Path, verbose: bool = True) -> int:
    spec = _load(spec_path)
    subject, oracle = Path(spec.SUBJECT), Path(spec.ORACLE)
    src = subject.read_text()

    # ENV is the probe->oracle CHANNEL, not a user-facing override: _run_oracle sets it per
    # mutant, so a value from the outer shell is overwritten before the oracle ever sees it.
    # Silently ignoring it is how a reader gets misled — steward ran
    # `WEDGE_WATCH_SRC=/nonexistent mutation_probe.py <spec>` expecting to exercise the skip
    # path and got a confident all-caught green instead (msg 6164). Say so out loud rather
    # than swallowing it; the subject comes from the spec, always.
    if verbose and spec.ENV in os.environ:
        print(f"NOTE: {spec.ENV} is set in your environment and is being IGNORED. It is this "
              f"tool's\n      channel to the oracle, not an override — the subject is "
              f"{subject}.\n      To exercise the oracle directly, run the oracle, not the "
              f"probe.\n")

    # BASELINE. If the oracle does not pass against the unmutated subject, every "caught"
    # below would be meaningless — it would be failing for a reason that has nothing to do
    # with the mutation. Refuse rather than report.
    base = _run_oracle(oracle, spec.ENV, subject)
    if base != 0:
        print(f"REFUSING: {oracle.name} does not pass against the unmutated subject "
              f"(exit {base}). Fix the oracle first; mutation results would be noise.")
        return 1

    caught, survived, skipped = [], [], []
    with tempfile.TemporaryDirectory() as td:
        for name, (old, new) in spec.MUTANTS.items():
            if old not in src:
                # The mutation did not apply — the subject moved under the mutant list.
                # This is UNKNOWN, never a pass: a stale mutant that silently no-ops would
                # report the oracle as fully probed when nothing was tried.
                skipped.append(name)
                continue
            if src.count(old) > 1:
                skipped.append(f"{name} (pattern is not unique — {src.count(old)} matches)")
                continue
            mpath = Path(td) / subject.name
            mpath.write_text(src.replace(old, new, 1))
            rc = _run_oracle(oracle, spec.ENV, mpath)
            # A SKIP IS NOT A CATCH. An oracle that could not run its checks exits 77 and
            # is non-zero, so a naive `rc != 0` would score "the oracle never looked" as
            # "the oracle noticed" — the same not-run-reads-as-a-verdict defect check.sh
            # was repaired for on 08-14, inverted. Caught by finding EXIT_SKIP defined and
            # never used in my own file.
            if rc == EXIT_SKIP:
                skipped.append(f"{name} (oracle SKIPPED — it verified nothing)")
            elif rc != 0:
                caught.append(name)
            else:
                survived.append(name)

    if verbose:
        print(f"mutation-probe · {oracle.name} vs {subject.name}")
        print(f"  baseline passes; {len(spec.MUTANTS)} authored mutant(s)\n")
        for n in caught:
            print(f"  CAUGHT                     {n}")
        for n in survived:
            print(f"  NOT PROBED BY THIS SET     {n}")
        for n in skipped:
            print(f"  NOT PROBED                 {n}")
        print()
        if survived:
            print(f"{len(survived)} mutant(s) changed the implementation and every assertion "
                  f"still passed.\nThat locates a HOLE IN THIS MUTANT SET's coverage — which "
                  f"assertion should have\ncaught it, and whether one exists at all, is the "
                  f"author's call. It singles out\nNO assertion: the finding is about this "
                  f"mutant, never about any one check.")
        else:
            print("Every authored mutant was caught. This says nothing about mutations that\n"
                  "were never authored — coverage is bounded by the list, not by the oracle.")
        if skipped:
            print(f"\n{len(skipped)} mutant(s) were NOT PROBED — the mutation did not apply, "
                  f"or the oracle\nskipped and verified nothing against it. Neither is a pass "
                  f"and neither is a catch.")
    return 2 if survived or skipped else 0


# ─────────────────────────── the probe's own RED and GREEN ───────────────────────────
# Condition 1 of the ruling. A tool whose output is trusted by construction is more
# dangerous than an ordinary one, so it proves BOTH arms on synthetic files it writes
# itself: it must FLAG a hole left by a known-vacuous assertion, and must NOT flag a
# known-good one. Nothing here touches the repo.

_SUBJECT = '''
THRESHOLD = 10
def classify(n):
    return "high" if n > THRESHOLD else "low"
'''

_ORACLE_HEAD = '''
import os, runpy, sys
from pathlib import Path
SUBJECT = Path(os.environ.get("PROBE_SELFTEST_SRC", "/nonexistent"))
if not SUBJECT.exists():
    print("SKIP: subject absent"); sys.exit(77)
classify = runpy.run_path(str(SUBJECT), run_name="s")["classify"]
fails = []
'''
_ORACLE_TAIL = '''
sys.exit(1 if fails else 0)
'''
# GOOD: pins behaviour either side of the threshold, so moving it is caught.
_GOOD = 'if classify(5) != "low": fails.append("a")\nif classify(50) != "high": fails.append("b")\n'
# VACUOUS: the classic conformance-to-self — the function under test on BOTH sides.
_VACUOUS = 'if classify(5) != classify(5): fails.append("a")\n'


def self_test() -> int:
    ok = True
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "subject.py").write_text(_SUBJECT)
        (td / "oracle_good.py").write_text(_ORACLE_HEAD + _GOOD + _ORACLE_TAIL)
        (td / "oracle_weak.py").write_text(_ORACLE_HEAD + _VACUOUS + _ORACLE_TAIL)
        for which in ("good", "weak"):
            (td / f"m_{which}.py").write_text(
                f'SUBJECT = {str(td / "subject.py")!r}\n'
                f'ORACLE = {str(td / f"oracle_{which}.py")!r}\n'
                'ENV = "PROBE_SELFTEST_SRC"\n'
                'MUTANTS = {"threshold moved": ("THRESHOLD = 10", "THRESHOLD = 100")}\n')

        print("GREEN ARM — a known-GOOD assertion must NOT be flagged:")
        rc = probe(td / "m_good.py", verbose=False)
        print(f"  {'PASS' if rc == 0 else 'FAIL'}  mutant caught, nothing reported unprobed")
        ok &= rc == 0

        print("\nRED ARM — a known-VACUOUS assertion must leave a hole the probe reports:")
        rc = probe(td / "m_weak.py", verbose=False)
        print(f"  {'PASS' if rc == 2 else 'FAIL'}  mutant survived and was reported")
        ok &= rc == 2

        print("\nVOCABULARY — the word 'vacuous' must never appear in a verdict:")
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            probe(td / "m_weak.py", verbose=True)
        clean = "vacuous" not in buf.getvalue().lower()
        print(f"  {'PASS' if clean else 'FAIL'}  output says NOT PROBED, never a verdict")
        ok &= clean

        # ARM 5, added after steward proved the demonstration wrong (msg 6164). The 77 branch
        # was reachable in the ORACLE and I showed that — but never showed the PROBE handling
        # it, and the command I offered as proof could not: the probe SETS the env var itself
        # per mutant, so an outer-shell value is overwritten before the oracle sees it. The
        # demo returned a confident all-caught green from the tool built to refuse exactly
        # that. So this arm drives a 77 through probe() rather than through the plumbing that
        # reaches it: an oracle that passes on the clean subject and SKIPS on the mutant, the
        # real shape of a mutation that breaks the module so the oracle cannot load it.
        print("\nORACLE SKIP — a 77 must report as NOT PROBED, never as CAUGHT:")
        (td / "oracle_skipper.py").write_text(
            _ORACLE_HEAD
            + 'if "THRESHOLD = 100" in SUBJECT.read_text():\n'
              '    print("SKIP: cannot verify against this subject"); sys.exit(77)\n'
            + _GOOD + _ORACLE_TAIL)
        (td / "m_skip.py").write_text(
            f'SUBJECT = {str(td / "subject.py")!r}\n'
            f'ORACLE = {str(td / "oracle_skipper.py")!r}\n'
            'ENV = "PROBE_SELFTEST_SRC"\n'
            'MUTANTS = {"threshold moved": ("THRESHOLD = 10", "THRESHOLD = 100")}\n')
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            rc = probe(td / "m_skip.py", verbose=True)
        out2 = buf2.getvalue()
        skip_ok = (rc == 2 and "oracle SKIPPED" in out2 and "CAUGHT" not in out2)
        print(f"  {'PASS' if skip_ok else 'FAIL'}  a skipping oracle scores UNPROBED, not CAUGHT")
        ok &= skip_ok

        print("\nSTALE MUTANT — a pattern that no longer matches is unprobed, not passed:")
        (td / "m_stale.py").write_text(
            f'SUBJECT = {str(td / "subject.py")!r}\n'
            f'ORACLE = {str(td / "oracle_good.py")!r}\n'
            'ENV = "PROBE_SELFTEST_SRC"\n'
            'MUTANTS = {"gone": ("NOT_IN_SOURCE = 1", "NOT_IN_SOURCE = 2")}\n')
        rc = probe(td / "m_stale.py", verbose=False)
        print(f"  {'PASS' if rc == 2 else 'FAIL'}  non-applying mutant does not read as clean")
        ok &= rc == 2

    print("\n" + ("SELF-TEST PASS" if ok else "SELF-TEST FAILED"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", nargs="?", help="a nucleus/mutants_<oracle>.py declaration")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the probe's own RED and GREEN arms")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.spec:
        ap.error("give a mutants spec, or --self-test")
    return probe(Path(a.spec))


if __name__ == "__main__":
    sys.exit(main())
