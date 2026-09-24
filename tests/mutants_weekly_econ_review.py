"""Authored mutants for triggers/steward/weekly_economic_review.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_weekly_econ_review.py

THE LIST IS THE JUDGEMENT. These are the two ways the ctx.sql SURFACE of this trigger can
regress — the surface ARM 6 was built to watch after the pure-helper arms (1-5) stayed GREEN
through the 2026-09-21 live crash. M1 is that exact crash restored; M2 is the column-typo
class on a different one of the three queries. Both must redden ARM6a (which asserts all
THREE ctx.sql surfaces — econ, triggers, goals — parse & execute); if either does not, that
is a live oracle gap to surface, not a mutant to drop.

WHY NO MORE THAN TWO: the three queries fail the same two ways (a literal-% under
execute(query, params), or a bad identifier). One mutant per class, on distinct queries, is
the authored judgement — a generic mutator would emit mostly equivalent mutants and drown it.

NOT A CLAIM OF COMPLETENESS: coverage is bounded by this list; the probe reports CAUGHT or
NOT PROBED, never "vacuous". The subject is gitignored (`triggers/`), so a clean checkout
does not carry it — tests/test_mutants_wellformed.py classifies that rather than assuming it.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "triggers" / "steward" / "weekly_economic_review.py"
ORACLE = REPO / "tests" / "test_weekly_econ_review.py"
ENV = "WEEKLY_ECON_SRC"

MUTANTS = {
    # M1 — THE 2026-09-21 CRASH, RESTORED (load-bearing). The LAYER-3 goals query legitimately
    # prefix-matches the '(deferred:' sentinel; the trigger uses left(funded_by,10)='(deferred:'
    # precisely because a literal % (LIKE '(deferred:%') is scanned as a placeholder by psycopg
    # under pulse_run.Ctx.sql's execute(query, params=()) and raises "only %s/%b/%t allowed". The
    # pure arms never executed this query, so it shipped GREEN. Anchored on the 'funded_by IS NULL
    # OR left(...' prefix so it hits the executed line, NOT the 265-line explanatory comment (which
    # carries left(funded_by,10)='(deferred:' too — the non-unique-pattern trap a4 hit in build).
    "M1 the LAYER-3 goals query reverts to a literal-% LIKE (the 09-21 execute-time crash)":
        ("funded_by IS NULL OR left(funded_by,10)='(deferred:'",
         "funded_by IS NULL OR funded_by LIKE '(deferred:%'"),

    # M2 — the column-typo class, on the triggers surface (a DIFFERENT query than M1's goals one),
    # so a regression that names a column no longer selected reddens rather than silently skipping.
    "M2 the triggers query selects a non-existent column (bad-identifier class)":
        ("SELECT agent, name, premium, enabled FROM triggers",
         "SELECT agent, name, premiumx, enabled FROM triggers"),
}
