"""Authored mutants for triggers/steward/market_decay.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_market_decay_sql.py

THE LIST IS THE JUDGEMENT. market_decay is the SOLE economic actuator and its four ctx.sql
strings went untested until the SQL-surface oracle (the advisory oracle drives only the pure
_decide/_is_file_backed and never executes them). These mutants exercise the two query classes
across the READ and the WRITE surfaces — a bad identifier in the candidate SELECT (M1) and in
the enabled=false UPDATE (M2). Both must redden the end-to-end arm; a survivor is a live
oracle gap to surface, not a mutant to drop.

ORACLE TARGETING (a4, msg 20725): this points at test_market_decay_sql_surface.py, NOT
test_market_decay_advisory.py — the advisory oracle never executes the queries and would NOT
redden on a SQL regression, so it must not be the ORACLE here.

WHY NO %-LITERAL MUTANT (deliberate, not an omission): the 09-21 %-scan class is plausible
where a query PREFIX-MATCHES (weekly_econ's '(deferred:' LIKE) — and it is covered there. None
of market_decay's four queries prefix-match, so a forced literal-% here would be an artificial
/ equivalent mutant, exactly what the mutation law rejects. The realistic regression class for
these queries is the identifier typo, which M1/M2 cover on both the READ and the WRITE.

NOT A CLAIM OF COMPLETENESS: coverage is bounded by this list; the probe reports CAUGHT or
NOT PROBED, never "vacuous". The subject is gitignored (`triggers/`), so a clean checkout does
not carry it — tests/test_mutants_wellformed.py classifies that rather than assuming it.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "triggers" / "steward" / "market_decay.py"
ORACLE = REPO / "tests" / "test_market_decay_sql_surface.py"
ENV = "MARKET_DECAY_SRC"

MUTANTS = {
    # M1 — bad identifier in the candidate SELECT (the READ). Proven by hand 2026-09-24:
    # premium->premiumx crashes the entrypoint at query 2 with column-does-not-exist, reddening
    # the end-to-end arm before it reaches the writes.
    "M1 the candidate SELECT names a non-existent column (READ surface)":
        ("SELECT premium, enabled, check_src FROM triggers",
         "SELECT premiumx, enabled, check_src FROM triggers"),

    # M2 — bad identifier in the retire UPDATE (the WRITE). Tests that the write query is actually
    # executed against the temp schema (its enabled column), not merely constructed — a typo here
    # would ship green if the oracle only ran the reads.
    "M2 the retire UPDATE targets a non-existent column (WRITE surface)":
        ("UPDATE triggers SET enabled=false",
         "UPDATE triggers SET enabledx=false"),
}
