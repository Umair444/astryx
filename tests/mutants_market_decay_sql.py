"""Authored mutants for triggers/steward/market_decay.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_market_decay_sql.py

THE LIST IS THE JUDGEMENT. market_decay was the SOLE economic actuator (report-only since goal
4227 S1b) and its ctx.sql strings went untested until the SQL-surface oracle (the advisory oracle drives only the pure
_decide/_is_file_backed and never executes them). These mutants exercise both READ queries (M1, M2 —
identifier typos) and, since goal 4227 S1b removed the retire verb, the verb's RETURN (M3 — O3).
All must redden the end-to-end arm; a survivor is a live
oracle gap to surface, not a mutant to drop.

ORACLE TARGETING (a4, msg 20725): this points at test_market_decay_sql_surface.py, NOT
test_market_decay_advisory.py — the advisory oracle never executes the queries and would NOT
redden on a SQL regression, so it must not be the ORACLE here.

WHY NO %-LITERAL MUTANT (deliberate, not an omission): the 09-21 %-scan class is plausible
where a query PREFIX-MATCHES (weekly_econ's '(deferred:' LIKE) — and it is covered there. None
of market_decay's queries prefix-match, so a forced literal-% here would be an artificial
/ equivalent mutant, exactly what the mutation law rejects. The realistic regression class for
these queries is the identifier typo, which M1/M2 cover on both reads;
M3 covers the verb's return.

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
    # premium->premiumx crashes the entrypoint at the per-candidate read with column-does-not-exist,
    # reddening the end-to-end arm.
    "M1 the candidate SELECT names a non-existent column (READ surface)":
        ("SELECT premium, enabled FROM triggers",
         "SELECT premiumx, enabled FROM triggers"),

    # M2 — bad identifier in the econ ledger read (the FIRST query). Before S1b M2 targeted the
    # retire UPDATE; that write no longer exists (goal 4227 S1b), so the second realistic typo
    # site is the other read.
    "M2 the econ ledger read names a non-existent column (READ surface)":
        ("metrics->'trigger_roi' AS roi",
         "metricsx->'trigger_roi' AS roi"),

    # M3 — O3, the regression that matters most: the retire verb comes back. Re-adding the write
    # on the report route must redden the end-to-end O3 arm (candidate still enabled).
    "M3 the retire verb is re-added on the report route (O3 — owner law: no killing)":
        ("            rent.append(f\"{agent}/{name}\")",
         "            ctx.sql(\"UPDATE triggers SET enabled=false WHERE agent=%s AND name=%s\", "
         "(agent, name))\n            rent.append(f\"{agent}/{name}\")"),
}
