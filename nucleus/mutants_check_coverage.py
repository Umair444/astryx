"""Authored mutants for nucleus/check.sh — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py nucleus/mutants_check_coverage.py

THE SUBJECT IS check.sh AND THE ORACLE IS test_check_coverage.py, so each mutant is a
plausibly-wrong check.sh and the question is whether my coverage gate notices. That gate is
the one everything else in the suite is trusted through — it is what guarantees a committed
oracle is actually invoked — so an assertion of mine that cannot fail makes the whole
coverage claim hollow rather than merely weak.

WHY I AM PROBING MY OWN GATE. The governing law (steward + abstractor-4, 2026-08-14) is that
after writing an assertion you ask what implementation would make it fail, and answer it by
BUILDING the wrong one rather than by eye — because both authors of that law shipped a
vacuous assertion in their own oracle within two hours of filing it. I wrote thirteen
assertions the night before and eyeballed most of them. This file is me declining to be the
third instance.

THE LIST IS THE JUDGEMENT. Each entry is a way check.sh could plausibly drift such that a
committed oracle stops running. M1-M3 and M5-M6 are the forms my assertions were written
against and should be caught. M4 is the one I did NOT consider when I wrote the gate, and I
expect it to survive — a `run` line is a syntactic invocation to my parser but a dead line
to bash if it sits inside a disabled block. Keeping a mutant I expect to survive is the
point: an authored list is reviewable precisely because someone claimed each entry is a real
risk, and the ones that turn out real are the reason to run it.

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list; every mutant being caught
would mean the authored risks are probed and nothing more.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "check.sh"
ORACLE = REPO / "nucleus" / "test_check_coverage.py"
ENV = "CHECK_SH_SRC"

_CHARTER = 'run "charter resolver invariants"      "$PY" nucleus/test_charter.py'

MUTANTS = {
    # THE core defect this gate exists to prevent, and the one I reproduced by hand on
    # 08-13 with a probe oracle: a committed nucleus/test_*.py that check.sh never runs,
    # while the suite still prints ALL CODE INVARIANTS PASS.
    "M1 a committed oracle is never invoked (run line deleted)":
        (_CHARTER, ""),

    # The realistic drift under pressure: someone silences a red gate "for now". The whole
    # reason the parser strips comments before matching rather than substring-searching
    # the file — a naive search would still see the filename and call it covered.
    "M2 invocation commented out (silenced 'for now')":
        (_CHARTER, "# " + _CHARTER),

    # A mention is not an invocation. This is the proxy error I committed against myself on
    # 08-13 while scanning for invokers by grepping for filenames.
    "M3 invocation degraded to a bare prose mention":
        (_CHARTER, 'echo "see nucleus/test_charter.py for the charter invariants"'),

    # THE ONE I DID NOT CONSIDER. Syntactically a `run` line, so my regex counts it as
    # invoked; semantically dead, so the oracle never executes. Same end state as M1 — a
    # committed oracle that does not run — reached by a route my parser cannot see. If this
    # survives, my gate proves a line EXISTS rather than that a gate RUNS, which is lens 8
    # (the terminal observable) failing inside the tool I built to enforce lens 3.
    "M4 run line alive but inside a disabled block (if false)":
        (_CHARTER, "if false; then\n" + _CHARTER + "\nfi"),

    # The other direction: check.sh invoking an oracle that no longer exists. Already fails
    # loudly at runtime, so this assertion only names the cause at check time — but it
    # should still be the assertion that speaks.
    "M5 check.sh invokes a deleted oracle":
        (_CHARTER, 'run "ghost gate" "$PY" nucleus/test_this_was_deleted.py'),

    # The OTHER direction, and the one that tests the new runtime instrument rather than the
    # parser: the path moved into a shell variable. bash still runs the oracle, so execution
    # sees it; the regex cannot, so syntax does not. Reached-but-not-parsed means the parser
    # has gone blind to a form check.sh actually uses, and the two instruments disagreeing is
    # the only way to notice. (Replaces an earlier M6 whose pattern matched 33 times and so
    # never applied — a mutant that does not apply is not a passing one, and the probe was
    # right to score it NOT PROBED rather than clean.)
    "M6 oracle path moved into a shell variable (runtime sees it, parser cannot)":
        (_CHARTER,
         'T=nucleus/test_charter.py\nrun "charter resolver invariants"      "$PY" "$T"'),
}
