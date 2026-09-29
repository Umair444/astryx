"""Authored mutants for triggers/steward/weekly_economic_review.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_weekly_econ_review.py

THE LIST IS THE JUDGEMENT. The ctx.sql SURFACE is what ARM 6 watches (the pure arms stayed GREEN
through the 2026-09-21 live crash); since goal 4227 S1b there are TWO queries (econ, triggers) —
the LAYER-3 goals query, and with it the old M1 (its literal-% crash restored), retired. M1/M2 are
the bad-identifier class on each remaining query; M3 is L3 coming back. All must redden; if one
does not, that is a live oracle gap to surface, not a mutant to drop.

WHY NO %-LITERAL MUTANT NOW: neither remaining query prefix-matches, so a forced literal % would be
an artificial mutant. ARM6b keeps the executor's %-scan pinned for any future prefix query.

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
    # M1 — the column-typo class on the econ ledger query (the FIRST read).
    "M1 the econ query selects a non-existent column (bad-identifier class)":
        ("SELECT day::text, metrics FROM econ",
         "SELECT day::text, metricsx FROM econ"),

    # M2 — the column-typo class, on the triggers surface, so a regression that names a column no
    # longer selected reddens rather than silently skipping.
    "M2 the triggers query selects a non-existent column (bad-identifier class)":
        ("SELECT agent, name, premium, enabled FROM triggers",
         "SELECT agent, name, premiumx, enabled FROM triggers"),

    # M3 — LAYER 3 restored (goal 4227 S1b retired it): a goals/funded_by read comes back.
    "M3 a LAYER-3 goals/funded_by query is re-added (retired in 4227 S1b)":
        ("    l2 = assess_layer2(roi_by_key, tstate)\n",
         "    l2 = assess_layer2(roi_by_key, tstate)\n"
         "    ctx.sql(\"SELECT id FROM goals WHERE state='active' AND funded_by IS NULL\")\n"),
}
