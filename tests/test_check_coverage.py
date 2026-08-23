"""Oracle for nucleus/check.sh's OWN coverage — the aggregator's blind spot.

check.sh exists because "a test nothing runs only proves its last manual invocation"
(its own header). It never applied that thesis to itself: its oracle list is a
hand-maintained snapshot of `run ...` lines, so a newly committed tests/test_*.py
is silently never executed and the suite still prints ALL CODE INVARIANTS PASS.

Reproduced before this file was written (abstractor-1, 2026-08-13): dropping a
tests/test_probe_unwired.py that exits 1 by construction left check.sh green,
exit 0. The drift is one forgotten line away, and it fails OPEN — the direction
that matters, because the missing signal looks exactly like a passing one.

The fix is a single derivation: the expected set comes from where oracles actually live,
never from a second list beside the first. A new oracle is therefore assumed to need
wiring — forgetting fails RED. There is deliberately no exemption allowlist; an oracle
that genuinely should not run in the suite is a decision someone should have to argue
for, not a default.

That derivation is `git ls-tree HEAD`, not a bare glob, and the difference is the difference
between COMMITTED and merely present (steward, 2026-08-15). Five agents share one working
tree here, so an untracked half-built oracle is the normal state of an evening, and while
the expected-set came off the filesystem it turned the whole suite red on somebody's
draft. A suite that is red for a reason unrelated to what it guards is a suite people
stop reading — the failure mode that costs more than the gap it was covering. The law
attaches at COMMIT; drafts stay VISIBLE (a WARN line) without being fatal.

TWO INSTRUMENTS, because one was not enough (2026-08-14). `invoked_oracles` reads the
SYNTAX of check.sh; `executed_oracles` runs it with $PY shimmed and reads which oracles
bash ACTUALLY REACHES. They fail differently — delete a `run` line and only the parser
notices; disable the block around it and only the runtime does — and a third assertion
requires them to AGREE on the live file, because a disagreement means one of them has gone
wrong about check.sh rather than about a mutant.

WHY THE SECOND ONE EXISTS, and it is not a hypothetical: `nucleus/mutation_probe.py`
(abstractor-4) with the authored mutants in `tests/mutants_check_coverage.py`. Mutant M4
wrapped a live `run` line in `if false; then ... fi` — still a line, never a gate — and
EVERY assertion in this file passed. The gate certified an oracle that could not execute,
which is lens 8 (a proxy reported as the terminal observable) inside the tool built to
enforce coverage. My first instinct was to write it up as a declared limit; the org's own
law forbids that, because a declared residual is the one everybody stops reading and it
functions as an alibi. M4 is now caught. Parsing bash control flow would have been the
cleverer-regex trap warned about below; observing the runtime is the honest answer.

GRADED HONESTLY, two limits:

1. This proves each oracle is REACHED when check.sh runs — not that it PASSED. A gate
   that executes and reports a wrong verdict is `test_check_verdict.py`'s question, not
   this file's. (Before 08-14 this limit was larger and read "wired as an invocation
   line, not that it executed"; M4 is what closed the gap between those two claims.)

2. Its authority is a NAMING CONVENTION — `tests/test_*.py` — which is itself
   hand-kept, one level up from the hand-kept list this file replaced. A check named
   outside the convention (`nucleus/foo_guard.sh`) is invisible here and would not be
   required in check.sh. Left unfixed deliberately, not overlooked: as of 08-13 the
   convention has no violators (the only nucleus/ scripts outside check.sh are
   smoke.sh / fedtest.py / doctor-class tools, which are self-declared MANUAL
   diagnostics with Usage lines — running nowhere automatically is their design, not
   a gap). Widening the glob to catch a hypothetical would mean guessing which
   scripts are checks, and a wrong guess makes the suite red for a tool. If an
   unwired non-test check ever appears, THAT is the trigger to generalise this — and
   the honest fix then is a declared kind, not a cleverer regex.

Run: venv/bin/python tests/test_check_coverage.py   (also wired into nucleus/check.sh)
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Env-overridable so nucleus/mutation_probe.py can run this oracle against a deliberately
# WRONG check.sh and record which assertion notices. Defaults to the real file, so nothing
# changes for check.sh or a human run. (Opted in 2026-08-14; see tests/mutants_check_coverage.py.)
CHECK_SH = Path(os.environ.get("CHECK_SH_SRC", REPO / "nucleus" / "check.sh"))

# A shell line only counts if it is a live `run` invocation. Comments are stripped
# first: commenting a test out is the realistic drift (someone silences a red test
# "for now"), and a naive substring search over the whole file would still see the
# filename and call it covered.
INVOKE = re.compile(r"^\s*run\b.*?\btests/(test_[A-Za-z0-9_]+\.py)\b")


def _live_lines(text):
    """check.sh lines with comments removed. Not a shell parser — deliberately: it
    only has to be STRICTER than the shell, so anything it misses fails closed."""
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line.split(" #")[0])
    return out


def invoked_oracles(text):
    """The set of tests/test_*.py files check.sh actually invokes."""
    found = set()
    for line in _live_lines(text):
        m = INVOKE.match(line)
        if m:
            found.add(m.group(1))
    return found


def oracles_on_disk():
    """THE authority. One derivation, from the place oracles really live."""
    return {p.name for p in (REPO / "tests").glob("test_*.py")}


def committed_oracles():
    """The authority for the COVERAGE asserts: oracles that are COMMITTED.

    HEAD, NOT THE INDEX (abstractor-2, msg 11118, reproduced before changing anything: a
    `git add`-only draft is counted by ls-files and absent from ls-tree HEAD). The first
    version of this used `git ls-files`, which lists the INDEX — so the stated law said
    COMMIT and the implementation said `git add`, one command apart. A staged draft exists
    in no clone either, so it fails the same test the docstring below uses to justify the
    boundary. The function was already named for the right thing while the code did
    something narrower; the name, this docstring and the assertion messages now agree,
    because the next reader will trust the sentence over the call.

    Both asserts below say "committed oracle(s)" and both derived their expected-set from
    a filesystem glob, which is not the same set on a machine where work happens. This org
    runs five agents in ONE shared working tree, so a half-built oracle sitting untracked
    for an evening turned the whole suite red — for a reason unrelated to what these gates
    guard, which is the surest way to teach people to stop reading a suite (steward,
    2026-08-15: `bash nucleus/check.sh` on the live tree, red on WIP alone).

    The law these gates enforce — a test nothing runs proves only its last manual
    invocation — ATTACHES AT COMMIT, because that is when the oracle starts appearing in
    every clone and claiming to be part of the floor. Until then it is a draft, and drafts
    are already covered elsewhere: privacy_gate.sh WARNs on untracked nucleus/*.py at push
    time, and pushed_tree_check.sh runs check.sh in a clone where the draft does not exist.

    FALL BACK BROADER, NEVER NARROWER. If git cannot answer (not a checkout, git absent),
    return the on-disk set: over-strict is a false red someone will investigate, while an
    empty expected-set is a green tick certifying nothing — the exact vacuity
    test_the_authority_is_not_empty exists to prevent.
    """
    r = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD", "tests/"],
                       cwd=REPO, capture_output=True, text=True)
    names = {Path(p).name for p in r.stdout.split()
             if Path(p).name.startswith("test_") and p.endswith(".py")}
    return names or oracles_on_disk()


class Unverified(Exception):
    """The instrument could not OBSERVE its subject this run — a THIRD state, never a RED.

    abstractor-3 measured three different verdicts over identical bytes (msg 10971): the
    nested check.sh run below really executes every non-$PY gate, and on a loaded host the
    180s budget expires; TimeoutExpired then surfaced as a failure indistinguishable from
    a coverage regression. memory's escalation (msg 11063) names the real cost: a gate
    that goes red without a defect trains re-run-until-green, which is precisely the
    procedure by which a true regression gets waved through — an authoritative-but-
    unreliable gate is worse than an absent one. The org's own protocol already covers
    this: a not-run gate is exit 77, and the aggregate may not out-claim what ran."""


_EXECUTED_CACHE: dict = {}


def executed_oracles(check_sh):
    """Which oracles does check.sh ACTUALLY REACH when it runs? The second instrument.

    The parser above reads SYNTAX; this reads EXECUTION. It runs check.sh with $PY replaced
    by a recording shim, so every gate becomes a no-op that logs the arguments it was handed
    — nothing real executes, and bash's own control flow decides what gets recorded. A `run`
    line inside `if false`, in a function nobody calls, or after an early exit is invisible
    here exactly as it is to bash.

    Added 2026-08-14 because mutation-probe M4 proved the syntactic reading insufficient:
    wrapping a live `run` line in `if false; then ... fi` left every assertion in this file
    passing, so the gate certified an oracle that could never execute. That is lens 8 — a
    proxy reported as the terminal observable — inside the tool built to enforce coverage.
    Parsing bash control flow instead would be the cleverer-regex trap this file's own limits
    section warns about; observing the runtime is the honest answer.
    """
    # Memoised: two tests ask this question, and the nested run is the expensive,
    # flake-exposed part — one observation per process, both readers share it (and a
    # timeout is not retried into a different answer within one run).
    key = str(check_sh)
    if key in _EXECUTED_CACHE:
        val = _EXECUTED_CACHE[key]
        if isinstance(val, Unverified):
            raise val
        return val
    with tempfile.TemporaryDirectory() as d:
        log, shim = Path(d) / "rec.log", Path(d) / "pyshim"
        shim.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" >> "$REC"\nexit 0\n')
        shim.chmod(0o755)
        # CHECK_ALLOW_SKIP so a shimmed run never exits nonzero on skip accounting; we read
        # the log, never the verdict. cwd lands wherever check.sh's own `cd` puts it, which
        # is harmless: run() passes its arguments through literally and nothing real runs.
        try:
            subprocess.run(["bash", str(check_sh)],
                           env=dict(os.environ, PY=str(shim), REC=str(log),
                                    CHECK_ALLOW_SKIP="1"),
                           capture_output=True, timeout=180)
        except subprocess.TimeoutExpired:
            val = Unverified("nested check.sh run exceeded 180s (loaded host) — "
                             "execution-reach was NOT observed this run")
            _EXECUTED_CACHE[key] = val
            raise val
        if not log.exists():
            _EXECUTED_CACHE[key] = set()
            return set()
        found = set()
        for line in log.read_text().splitlines():
            m = re.search(r"(?:^|/)(test_[A-Za-z0-9_]+\.py)$", line.strip())
            if m:
                found.add(m.group(1))
        _EXECUTED_CACHE[key] = found
        return found


# ---------------------------------------------------------------------------


def test_the_authority_is_not_empty():
    """Anti-vacuity, and the reason this test is first. If the glob ever returned
    nothing, the coverage assert below would pass by having nothing to check — a
    green tick certifying an empty question. A check whose expected-set can go
    silently empty is not a check."""
    disk = oracles_on_disk()
    assert disk, "no tests/test_*.py found at all — the glob authority is broken"
    assert Path(__file__).name in disk, "this file must be visible to its own authority"
    committed = committed_oracles()
    assert committed, "the committed-oracle authority is empty — the coverage asserts "\
                      "below would pass by having nothing to check"
    assert Path(__file__).name in committed, "this file must be visible to its own authority"
    wip = sorted(disk - committed)
    if wip:
        # Visible, not fatal. An uncommitted oracle is a draft, not a hole in the floor —
        # but a draft nobody can see is how one gets left behind (three times in 08-2026).
        # "Uncommitted", not "untracked": a `git add`-only file is equally absent from
        # every clone, and calling it tracked is what put the boundary in the wrong place.
        print(f"  WARN: {len(wip)} uncommitted oracle(s) in nucleus/ — drafts, not yet part "
              f"of the floor: {', '.join(wip)}")


def test_the_parser_recognises_the_real_check_sh():
    """Second anti-vacuity guard, on the other input. A regex that silently stopped
    matching (someone reformats check.sh) would report zero invocations and the
    coverage assert would go red for a bogus reason — so prove the parser reads the
    live file before trusting either verdict it produces."""
    invoked = invoked_oracles(CHECK_SH.read_text())
    assert invoked, f"parsed no `run ... tests/test_*.py` lines from {CHECK_SH}"


def test_every_oracle_in_nucleus_is_invoked_by_check_sh():
    """THE coverage assert. Expected-set derived from the filesystem, independent of
    the artifact being checked — so it proves COMPLETENESS, not merely that check.sh
    is internally consistent with itself."""
    missing = sorted(committed_oracles() - invoked_oracles(CHECK_SH.read_text()))
    assert not missing, (
        "committed oracle(s) that nucleus/check.sh never runs: "
        + ", ".join(missing)
        + " — a test nothing runs proves only its last manual invocation. Add a "
          "`run \"<label>\" \"$PY\" nucleus/<file>` line to check.sh."
    )


def test_every_invoked_oracle_exists_on_disk():
    """The other direction. check.sh invoking a deleted oracle already fails loudly
    at runtime, so this is belt-and-braces — it just names the cause at check time
    instead of leaving a bare python 'No such file' in the log."""
    stale = sorted(invoked_oracles(CHECK_SH.read_text()) - oracles_on_disk())
    assert not stale, f"check.sh invokes oracle(s) that no longer exist: {stale}"


def test_every_oracle_is_actually_REACHED_when_check_sh_runs():
    """THE terminal observable, and the second instrument on the same question.

    The syntactic assert above proves a `run` line is PRESENT; this proves the line is
    REACHED. Both are needed and they fail differently: delete a line and the parser
    notices, disable the block around it and only this does. Two instruments on one
    question, where the disagreement is the finding.
    """
    executed = executed_oracles(CHECK_SH)
    # Anti-vacuity, same discipline as the parser's: if the shim recorded nothing at all,
    # the comparison below would pass by having nothing to compare.
    assert executed, (
        f"runtime probe recorded no invocations from {CHECK_SH} — the shim never ran, so "
        f"this assertion verified nothing rather than finding nothing")
    unreached = sorted(committed_oracles() - executed)
    assert not unreached, (
        "committed oracle(s) present in check.sh but NEVER REACHED when it runs: "
        + ", ".join(unreached)
        + " — a `run` line inside a disabled block, an uncalled function, or after an "
          "early exit is a line, not a gate.")


def test_the_two_instruments_agree_on_the_real_check_sh():
    """Where syntax and execution disagree, one of them is wrong about the live file — so
    say so here rather than letting each assertion pass on its own reading. Parsed-but-never-
    reached is the M4 shape; reached-but-never-parsed means the parser has gone blind to a
    form check.sh actually uses."""
    parsed, executed = invoked_oracles(CHECK_SH.read_text()), executed_oracles(CHECK_SH)
    assert parsed and executed, "anti-vacuity: both instruments must have read something"
    ghost = sorted(parsed - executed)
    unseen = sorted(executed - parsed)
    assert not ghost, f"parsed as invoked but never reached at runtime: {ghost}"
    assert not unseen, f"reached at runtime but the parser cannot see them: {unseen}"


def test_a_commented_out_invocation_does_not_count():
    """The parser's own failing direction, on synthetic input. Silencing a red test
    by commenting its line is the drift most likely to happen under pressure, and it
    must read as UNCOVERED, not as covered."""
    assert invoked_oracles('run "x" "$PY" tests/test_x.py') == {"test_x.py"}
    assert invoked_oracles('#run "x" "$PY" tests/test_x.py') == set()
    assert invoked_oracles('  # run "x" "$PY" tests/test_x.py') == set()
    assert invoked_oracles('run "x" "$PY" tests/test_x.py  # noqa') == {"test_x.py"}
    # a bare mention in prose is not an invocation
    assert invoked_oracles('echo "see tests/test_x.py"') == set()


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = unverified = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except Unverified as e:
            unverified += 1
            print(f"  ○ {fn.__name__} — VERIFIED NOTHING: {e}")
        except Exception:
            failed += 1
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed - unverified}/{len(fns)} passed"
          + (f", {unverified} UNVERIFIED" if unverified else ""))
    if failed:
        sys.exit(1)
    if unverified:
        # A partial skip is a 77 too: the syntactic half may have passed, but this run
        # did not observe execution-reach, and the verdict may not out-claim its parts.
        print("SKIP: the runtime-reach instrument was not observed this run")
        sys.exit(77)
    sys.exit(0)
