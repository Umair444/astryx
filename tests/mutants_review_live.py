"""Authored mutants for devtools/review_live.py, run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_review_live.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "review_live.py"
ORACLE = REPO / "tests" / "test_review_live.py"
ENV = "REVIEW_LIVE_SRC"
MUTANTS = {
    "W1 the patch is applied AFTER a module imported (its REPO stays the extract: seed's S1d trap)":
        ("    orig = P.repo_root\n", "    import astryx.core.deps  # noqa: F401\n    orig = P.repo_root\n"),
    "W2 PGOPTIONS is dropped (the measured code's writes reach the database)":
        ("e[\"PGOPTIONS\"] = f\"{e.get('PGOPTIONS', '')} {READ_ONLY}\".strip()", "pass"),
    "W3 ASTRYX_AGENT is kept (the measured code posts as the reviewer)":
        ("e.pop(\"ASTRYX_AGENT\", None)", "pass"),
    "W4 every root is rebound, a fixture tree's too (an oracle's fake repo judges live)":
        ("return live if Path(r).resolve() == extract else r", "return live"),
}
MUTANTS["W5 the DSN is not rewritten (asyncpg ignores PGOPTIONS: its writes reach the database, a4 #56228)"] = \
    ("        e[\"ASTRYX_DSN\"] = read_only_dsn(dsn)", "        pass")
MUTANTS["W6 an existing options= is overwritten, not refused (another tool's options silently dropped)"] = \
    ("        if any(k == \"options\" for k, _ in q):\n            raise Refused", "        if False:\n            raise Refused")
