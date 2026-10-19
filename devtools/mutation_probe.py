#!/usr/bin/env python3
"""astryx · mutation-probe — WHICH WRONG IMPLEMENTATIONS DOES THIS ORACLE FAIL TO NOTICE?

    venv/bin/python devtools/mutation_probe.py tests/mutants_wedge_watch.py
    venv/bin/python devtools/mutation_probe.py --self-test
    venv/bin/python devtools/mutation_probe.py tests/mutants_wedge_watch.py --only M3   # M3 alone, to read its why

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
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))
from astryx.paths import repo_root  # noqa: E402

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = repo_root(__file__)
EXIT_SKIP = 77
TIMED_OUT = -1          # _run_oracle's sentinel: the oracle didn't finish, so it verified nothing (never a catch)
DEFAULT_TIMEOUT = 120   # a spec whose oracle is slower declares TIMEOUT (the prep oracle takes ~200 s, 10-09)


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REFUSAL_TAIL = 25        # lines of the oracle's own output a REFUSING verdict prints (a4 night 10-16, plan-11253 #57741)
_FAILING = ("FAIL", "✗", "Traceback", "Error", "SKIP", "NOT SEARCHED", "BROKEN")


def _tail(out: str, n: int = REFUSAL_TAIL) -> list:
    """The oracle's output a refusal shows: every line that names a failure (FAIL, ✗, a Traceback, an *Error, a skip)
    first, then the last lines, deduplicated in order, at most n. The verdict line alone said "exit 1"; without the
    failing arm a loaded, one-off refusal can never be attributed (memory #57741: the parity baseline red at load 7.79)."""
    lines = [ln.rstrip() for ln in (out or "").splitlines() if ln.strip()]
    # a line that IS a failure (first token FAIL or ✗) before one that merely MENTIONS a keyword: otherwise >n PASS
    # labels naming "Error" crowd the real FAIL out of the block (a3 #57897, advisory, measured)
    first = [ln for ln in lines if ln.split()[0] in ("FAIL", "✗")]
    hot = [ln for ln in lines if ln not in first and any(k in ln for k in _FAILING)]
    keep, seen = [], set()
    for ln in first + hot + lines[-n:]:
        if ln not in seen:
            seen.add(ln)
            keep.append(ln)
    return keep[:n]


def _run_oracle(oracle: Path, env_var: str, subject_path: Path, timeout: int = DEFAULT_TIMEOUT) -> int:
    return _run_oracle_out(oracle, env_var, subject_path, timeout)[0]


def _run_oracle_out(oracle: Path, env_var: str, subject_path: Path, timeout: int = DEFAULT_TIMEOUT) -> tuple:
    """(rc, the oracle's combined output). TIMED_OUT keeps whatever it printed before the kill."""
    # `-u` below: a Python oracle block-buffers stdout into this pipe, and a timeout's kill discards that buffer, so
    # without it a timed-out oracle "printed nothing" though it did (a3 #57897 R-1, measured). A FLAG, never an
    # environment name: the probe adds NOTHING to the oracle's environment but its ENV seam. PYTHONUNBUFFERED=1 here
    # failed every org-census baseline, whose C4 refuses an unclassed name in its own environment (seed #60425).
    # One pinned exception (plan-11324 S3f S3, a2 #60815 R-1): the oracle never sees the HOST's org registry. A battery
    # the pulse launches (probe_all.sh) or a builder's shell runs reads /etc/astryx/cog.json, so on a cog host every
    # family would run under multi; pinned to a path that names no file, the oracle runs as the checkout's own org,
    # exactly as under check.sh (ASTRYX_COG_REGISTRY is a declared host-class name: data/org_env.json)
    env = dict(os.environ, **{env_var: str(subject_path)})
    env["ASTRYX_COG_REGISTRY"] = f"{tempfile.gettempdir()}/astryx-probe-{os.getpid()}-no-registry/cog.json"
    with tempfile.TemporaryDirectory() as trace:
        # A mutant (or the canary) is NOT the inventoried code, so its SQL is not estate evidence: under check.sh's
        # sqlguard it read BLIND (126 lines, seed #33150, when the smoke family became one with SQL mutants). The
        # oracle child keeps tracing, but into a private dir that dies with the run, never the estate's.
        if "ASTRYX_SQLGUARD_DIR" in env:
            env["ASTRYX_SQLGUARD_DIR"] = trace
        try:
            r = subprocess.run([sys.executable, "-u", str(oracle)], env=env,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            # It used to RAISE, crashing the whole probe after SIGKILLing the oracle mid-run (its finally never ran,
            # so a slow DB oracle stranded debris: a2 F2 #34875). Now it's an outcome: NOT PROBED, named.
            part = [x.decode(errors="replace") if isinstance(x, bytes) else (x or "") for x in (e.stdout, e.stderr)]
            return TIMED_OUT, "".join(part)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _why(out: str) -> str:
    """The line a CAUGHT came from, so a catch names its arm without a second, by-hand run (a4 night 10-19: twice in one
    day I re-applied a mutant by hand only to read WHICH check failed). The oracle's first CHECK line (first token FAIL
    or ✗, never a `FAIL:` summary); else its summary; else, after a Traceback, the exception it ended with, marked a
    CRASH: the mutant broke the run and no check judged it, the weak catch; else the bare exit. `(+k more failing)`
    counts the OTHER check lines (a3 #61207 (a)): k near the oracle's whole count is a collapse, not a targeted catch."""
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    checks = [ln for ln in lines if ln.split()[0] in ("FAIL", "✗")]
    summary = next((ln for ln in lines if ln.split()[0] == "FAIL:"), None)
    if checks:
        more = f" (+{len(checks) - 1} more failing)" if len(checks) > 1 else ""
        return checks[0][:200] + more
    if summary:
        return summary[:200]
    if any(ln.startswith("Traceback") for ln in lines):
        return f"a CRASH, not a check: {lines[-1][:180]}"
    return "no failing line printed (the exit code alone)"


def _print_tail(oracle: Path, out: str, when: str) -> None:
    """The baseline's own failing lines, so a refusal names its arm (a one-off loaded refusal is otherwise lost)."""
    tail = _tail(out)
    print(f"  {oracle.name}'s own output ({when}; failing lines first, then its last lines):")
    empty = "(nothing captured before the kill)" if when == "before the kill" else "(it printed nothing)"
    for ln in tail or [empty]:
        print(f"    | {ln[:220]}")


def _tree_rel(subject: Path, oracle: Path) -> Path:
    """The subject's path below its tree's root, so a subject that resolves by its code-tree tail loads where the
    mutants go (a4 10-19: an extract's bare gateway.py raised at paths.estate and the relocated baseline REFUSED a
    battery that passes in a worktree; a3 #60145). The root, first that holds:
      its git root                                    (observatory/api/main.py), as always;
      the nearest ancestor holding src/astryx/ or astryx.py   repo_root's own marker, so a git-archive extract places
                                                      every copy as a worktree does (a3 #60809: 166 of 166 specs);
      the deepest directory it shares with its oracle  a tree with neither (an oracle beside its subject: the bare name).
    Not repo_root() itself: with no marker it answers this package's tree, which a temp subject is not below."""
    f = subject.resolve()
    for a in f.parents:
        if (a / ".git").exists():
            return f.relative_to(a)
    for a in f.parents:
        if (a / "src" / "astryx").is_dir() or (a / "astryx.py").is_file():
            return f.relative_to(a)
    return f.relative_to(os.path.commonpath([f.parent, oracle.resolve().parent]))


def probe(spec_path: Path, verbose: bool = True, only=()) -> int:
    spec = _load(spec_path)
    # --only: the named mutants alone, every phase before them unchanged. A name is a mutant's FIRST TOKEN, exactly
    # ("T1" is T1, never T10-T19: a3 #61207 (c), measured 11 of 20); a trailing * is a deliberate family ("O4*"). A
    # selector naming none is an error, never an empty run that reads as "nothing survived"
    def named(k, o):
        return k.startswith(o[:-1]) if o.endswith("*") else k.split()[0] == o
    mutants = {k: v for k, v in spec.MUTANTS.items() if not only or any(named(k, o) for o in only)}
    if not mutants:
        print(f"no mutant in {spec_path.name} is named by --only {' '.join(only)}")
        return 1
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
    timeout = int(getattr(spec, "TIMEOUT", DEFAULT_TIMEOUT))
    base, base_out = _run_oracle_out(oracle, spec.ENV, subject, timeout)
    if base == TIMED_OUT:
        print(f"REFUSING: {oracle.name} did not finish within {timeout}s against the unmutated subject. Declare a "
              f"larger TIMEOUT in the spec; every verdict below would be a guess.")
        _print_tail(oracle, base_out, "before the kill")
        return 1
    if base != 0:
        print(f"REFUSING: {oracle.name} does not pass against the unmutated subject "
              f"(exit {base}). Fix the oracle first; mutation results would be noise.")
        _print_tail(oracle, base_out, f"exit {base}")
        return 1

    # THE CANARY (memory, msg 13203; forge's instance msg 13200). The BASELINE above asks
    # "does this oracle pass against the RIGHT code" — it cannot see an oracle that is not
    # reading the subject this tool hands it, because such an oracle reads the real module
    # both times and passes both times. forge's escalation suite was 33/33 with positive
    # controls in every arm and ALL TEN mutants survived: the oracle did a bare
    # `from astryx.core import escalation` and ignored the env, so it graded ten broken copies
    # it never opened. A scattered survivor is a coverage hole; a CLEAN SWEEP of survivors
    # is a wiring fault — and without this control the reader audits every assertion
    # before questioning the harness. So: one mutant the oracle cannot possibly pass — a
    # syntactically destroyed copy — and if the oracle PASSES it, the oracle is not
    # looking. Refuse to grade; every verdict after that point is meaningless BOTH ways.
    caught, survived, skipped = [], [], []
    with tempfile.TemporaryDirectory() as td:
        # Every copy (canary, relocated baseline, mutant) sits at the subject's path RELATIVE TO ITS TREE, never as a bare
        # file: a subject that resolves its own tree (main.py's `paths.estate(__file__)`) finds a copy only by that tail,
        # and a bare-named copy died at import, so every mutant read CAUGHT, a no-op one included (a4 #60129).
        rel = _tree_rel(subject, oracle)

        def seat(slot: str, text: str) -> Path:
            """A fresh directory per copy. One path for every copy let an oracle that IMPORTS its subject run the
            previous copy's cached .pyc whenever the next one had the same size in the same mtime second: memory's D1
            read NOT PROBED (#60378), and a no-op after a caught mutant would read CAUGHT. Oracle arm R7, mutant T9."""
            p = Path(td) / slot / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            return p

        canary = seat("canary", "def ( this file is deliberately not python — the canary\n")
        if _run_oracle(oracle, spec.ENV, canary, timeout) == 0:
            print(f"WIRING FAULT: {oracle.name} PASSED against a syntactically destroyed "
                  f"subject.\n  The oracle is not reading the path {spec.ENV} hands it — "
                  f"likely a bare import or a\n  hardcoded subject. Every mutant verdict "
                  f"would be meaningless in both directions;\n  refusing to grade. Fix the "
                  f"oracle's subject wiring first.")
            return 1
        # THE RELOCATED BASELINE: the canary proves the oracle FAILS a broken copy; this proves it PASSES an unbroken
        # one at the place every mutant runs from. Without it, a copy that can't load there reads as a catch.
        rb, rb_out = _run_oracle_out(oracle, spec.ENV, seat("base", src), timeout)
        if rb != 0:
            print(f"REFUSING: {oracle.name} fails the UNMUTATED subject copied to the mutant location ({rel}; "
                  f"exit {rb}), though it passes it in place. Every mutant would read CAUGHT for that reason alone.")
            _print_tail(oracle, rb_out, "before the kill" if rb == TIMED_OUT else f"exit {rb}")
            return 1
        for i, (name, (old, new)) in enumerate(mutants.items()):
            if old not in src:
                # The mutation did not apply — the subject moved under the mutant list.
                # This is UNKNOWN, never a pass: a stale mutant that silently no-ops would
                # report the oracle as fully probed when nothing was tried.
                skipped.append(name)
                continue
            if src.count(old) > 1:
                skipped.append(f"{name} (pattern is not unique — {src.count(old)} matches)")
                continue
            mpath = seat(f"m{i}", src.replace(old, new, 1))
            t0 = time.monotonic()
            rc, mout = _run_oracle_out(oracle, spec.ENV, mpath, timeout)
            took = f"{time.monotonic() - t0:.0f}s"
            if rc == TIMED_OUT:
                skipped.append(f"{name} (oracle TIMED OUT after {timeout}s — it verified nothing)")
                continue
            # A SKIP IS NOT A CATCH. An oracle that could not run its checks exits 77 and
            # is non-zero, so a naive `rc != 0` would score "the oracle never looked" as
            # "the oracle noticed" — the same not-run-reads-as-a-verdict defect check.sh
            # was repaired for on 08-14, inverted. Caught by finding EXIT_SKIP defined and
            # never used in my own file.
            if rc == EXIT_SKIP:
                skipped.append(f"{name} (oracle SKIPPED — it verified nothing)")
            elif rc != 0:
                caught.append((name, took, _why(mout)))
            else:
                survived.append(name)

    if verbose:
        print(f"mutation-probe · {oracle.name} vs {subject.name}")
        sel = f" ({len(mutants)} selected by --only)" if only else ""
        print(f"  baseline passes; {len(spec.MUTANTS)} authored mutant(s){sel}\n")
        for n, took, why in caught:
            print(f"  CAUGHT                     {n}  ({took})")
            print(f"      why: {why}")
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
        elif skipped:
            # The headline may never out-claim its parts. With a mutant NOT PROBED, "every
            # authored mutant was caught" is false, even though the exit code (2) was honest.
            # A reader who stops at the headline is exactly who this protects (forge, 09-29:
            # a re-anchored oracle left M3 unapplied under an "every mutant caught" line).
            print(f"Every PROBED mutant was caught, but {len(skipped)} of "
                  f"{len(caught) + len(skipped)} were NOT PROBED,\nso this run does NOT show "
                  f"the authored set is caught.")
        elif only:
            # a SUBSET run may never out-claim the set: the headline names what was run, and what was not
            print(f"Every SELECTED mutant was caught ({len(mutants)} of {len(spec.MUTANTS)} authored; --only ran no "
                  f"other).\nThis is not a verdict on the authored set.")
        else:
            print("Every authored mutant was caught. This says nothing about mutations that\n"
                  "were never authored — coverage is bounded by the list, not by the oracle.")
        crashed = [n for n, _, why in caught if why.startswith("a CRASH")]
        if crashed:
            # a3 #61207 (b): the headline is what a reader carries away; a crash-caught mutant is CAUGHT (the verdict and
            # rc are unchanged) but no check judged it
            print(f"\n{len(crashed)} of the {len(caught)} CAUGHT were a CRASH, not a check: read their why.")
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
        buf3 = io.StringIO()
        with contextlib.redirect_stdout(buf3):
            rc = probe(td / "m_stale.py", verbose=True)
        out3 = buf3.getvalue()
        print(f"  {'PASS' if rc == 2 else 'FAIL'}  non-applying mutant does not read as clean")
        ok &= rc == 2
        # The exit code alone isn't enough: a reader stops at the headline. With a mutant NOT
        # PROBED, the headline must not say the authored set was caught.
        head_ok = "Every authored mutant was caught" not in out3 and "NOT PROBED" in out3
        print(f"  {'PASS' if head_ok else 'FAIL'}  the headline never claims the set was caught")
        ok &= head_ok

        # A mutant's SQL must never reach the estate's sqlguard trace (seed #33150): the oracle child sees a
        # private trace dir, and a set-but-empty estate dir stays empty after a probe.
        print("\nSQLGUARD — a mutant's run never writes the estate's trace dir:")
        (td / "oracle_trace.py").write_text(
            _ORACLE_HEAD
            + 'd = os.environ.get("ASTRYX_SQLGUARD_DIR", "")\n'
              'Path(d, "trace-probe.jsonl").write_text("x") if d else fails.append("unset")\n'
            + _GOOD + _ORACLE_TAIL)
        (td / "m_trace.py").write_text(
            f'SUBJECT = {str(td / "subject.py")!r}\n'
            f'ORACLE = {str(td / "oracle_trace.py")!r}\n'
            'ENV = "PROBE_SELFTEST_SRC"\n'
            'MUTANTS = {"threshold moved": ("THRESHOLD = 10", "THRESHOLD = 100")}\n')
        estate = td / "estate_trace"
        estate.mkdir()
        prev = os.environ.get("ASTRYX_SQLGUARD_DIR")
        os.environ["ASTRYX_SQLGUARD_DIR"] = str(estate)
        try:
            rc = probe(td / "m_trace.py", verbose=False)
        finally:
            if prev is None:
                os.environ.pop("ASTRYX_SQLGUARD_DIR", None)
            else:
                os.environ["ASTRYX_SQLGUARD_DIR"] = prev
        tr_ok = rc == 0 and not any(estate.iterdir())
        print(f"  {'PASS' if tr_ok else 'FAIL'}  the oracle traced, into a private dir (estate dir empty, rc {rc})")
        ok &= tr_ok

        # A TIMEOUT is an outcome, never a crash and never a catch (10-09: a 200 s prep oracle against a 120 s limit
        # crashed the probe and stranded its debris).
        print("\nTIMEOUT — a mutant whose oracle doesn't finish is NOT PROBED, and the probe doesn't crash:")
        (td / "oracle_slow.py").write_text(
            _ORACLE_HEAD
            + 'import time\nif "THRESHOLD = 100" in SUBJECT.read_text():\n    time.sleep(30)\n'
            + _GOOD + _ORACLE_TAIL)
        (td / "m_slow.py").write_text(
            f'SUBJECT = {str(td / "subject.py")!r}\n'
            f'ORACLE = {str(td / "oracle_slow.py")!r}\n'
            'ENV = "PROBE_SELFTEST_SRC"\nTIMEOUT = 3\n'
            'MUTANTS = {"threshold moved": ("THRESHOLD = 10", "THRESHOLD = 100")}\n')
        buf4 = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf4):
                rc = probe(td / "m_slow.py", verbose=True)
            out4 = buf4.getvalue()
            slow_ok = rc == 2 and "TIMED OUT after 3s" in out4 and "CAUGHT" not in out4
        except Exception as e:                                   # the old behaviour: the probe itself crashed
            slow_ok, out4 = False, f"{type(e).__name__}: {e}"
        print(f"  {'PASS' if slow_ok else 'FAIL'}  a timed-out mutant reads NOT PROBED (rc 2), never CAUGHT, no crash")
        ok &= slow_ok

    print("\n" + ("SELF-TEST PASS" if ok else "SELF-TEST FAILED"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", nargs="?", help="a tests/mutants_<oracle>.py declaration")
    ap.add_argument("--only", action="append", default=[], metavar="NAME",
                    help="run only the mutant whose name's first token is NAME (repeatable; NAME* for a family), "
                         "to read each one's why")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the probe's own RED and GREEN arms")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.spec:
        ap.error("give a mutants spec, or --self-test")
    return probe(Path(a.spec), only=tuple(a.only))


if __name__ == "__main__":
    sys.exit(main())
