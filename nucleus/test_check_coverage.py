"""Oracle for nucleus/check.sh's OWN coverage — the aggregator's blind spot.

check.sh exists because "a test nothing runs only proves its last manual invocation"
(its own header). It never applied that thesis to itself: its oracle list is a
hand-maintained snapshot of `run ...` lines, so a newly committed nucleus/test_*.py
is silently never executed and the suite still prints ALL CODE INVARIANTS PASS.

Reproduced before this file was written (abstractor-1, 2026-08-13): dropping a
nucleus/test_probe_unwired.py that exits 1 by construction left check.sh green,
exit 0. The drift is one forgotten line away, and it fails OPEN — the direction
that matters, because the missing signal looks exactly like a passing one.

The fix is a single derivation: the expected set comes from the FILESYSTEM (where
oracles actually live), never from a second list beside the first. A new oracle is
therefore assumed to need wiring — forgetting fails RED. There is deliberately no
exemption allowlist; an oracle that genuinely should not run in the suite is a
decision someone should have to argue for, not a default.

GRADED HONESTLY, two limits:

1. This proves each oracle is WIRED AS AN INVOCATION LINE, not that it EXECUTED and
   passed. That is one notch below the terminal observable (which would mean running
   the suite and watching each oracle report), and it is the notch this file claims.

2. Its authority is a NAMING CONVENTION — `nucleus/test_*.py` — which is itself
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

Run: venv/bin/python nucleus/test_check_coverage.py   (also wired into nucleus/check.sh)
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK_SH = REPO / "nucleus" / "check.sh"

# A shell line only counts if it is a live `run` invocation. Comments are stripped
# first: commenting a test out is the realistic drift (someone silences a red test
# "for now"), and a naive substring search over the whole file would still see the
# filename and call it covered.
INVOKE = re.compile(r"^\s*run\b.*?\bnucleus/(test_[A-Za-z0-9_]+\.py)\b")


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
    """The set of nucleus/test_*.py files check.sh actually invokes."""
    found = set()
    for line in _live_lines(text):
        m = INVOKE.match(line)
        if m:
            found.add(m.group(1))
    return found


def oracles_on_disk():
    """THE authority. One derivation, from the place oracles really live."""
    return {p.name for p in (REPO / "nucleus").glob("test_*.py")}


# ---------------------------------------------------------------------------


def test_the_authority_is_not_empty():
    """Anti-vacuity, and the reason this test is first. If the glob ever returned
    nothing, the coverage assert below would pass by having nothing to check — a
    green tick certifying an empty question. A check whose expected-set can go
    silently empty is not a check."""
    disk = oracles_on_disk()
    assert disk, "no nucleus/test_*.py found at all — the glob authority is broken"
    assert Path(__file__).name in disk, "this file must be visible to its own authority"


def test_the_parser_recognises_the_real_check_sh():
    """Second anti-vacuity guard, on the other input. A regex that silently stopped
    matching (someone reformats check.sh) would report zero invocations and the
    coverage assert would go red for a bogus reason — so prove the parser reads the
    live file before trusting either verdict it produces."""
    invoked = invoked_oracles(CHECK_SH.read_text())
    assert invoked, f"parsed no `run ... nucleus/test_*.py` lines from {CHECK_SH}"


def test_every_oracle_in_nucleus_is_invoked_by_check_sh():
    """THE coverage assert. Expected-set derived from the filesystem, independent of
    the artifact being checked — so it proves COMPLETENESS, not merely that check.sh
    is internally consistent with itself."""
    missing = sorted(oracles_on_disk() - invoked_oracles(CHECK_SH.read_text()))
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


def test_a_commented_out_invocation_does_not_count():
    """The parser's own failing direction, on synthetic input. Silencing a red test
    by commenting its line is the drift most likely to happen under pressure, and it
    must read as UNCOVERED, not as covered."""
    assert invoked_oracles('run "x" "$PY" nucleus/test_x.py') == {"test_x.py"}
    assert invoked_oracles('#run "x" "$PY" nucleus/test_x.py') == set()
    assert invoked_oracles('  # run "x" "$PY" nucleus/test_x.py') == set()
    assert invoked_oracles('run "x" "$PY" nucleus/test_x.py  # noqa') == {"test_x.py"}
    # a bare mention in prose is not an invocation
    assert invoked_oracles('echo "see nucleus/test_x.py"') == set()


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
