"""Authored mutants for src/astryx/econ/econ.py's tool DOMAIN (goal 11324 S1) — run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_econ_core_domain.py

Each is a plausible wrong S1: core relabelled "resolved" (a3's HARD), a cut on one count only, a re-typed
CORE_SERVERS, a prefix match, an only-core window read as a measured number, an unbumped version.
toolreg's folds are probed by tests/mutants_econ_core_domain_toolreg.py (the same oracle, the other seam).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "econ" / "econ.py"
ORACLE = REPO / "tests" / "test_econ_core_domain.py"
ENV = "ECON_SRC"

MUTANTS = {
    "C1 no domain: core calls stay in value and coverage":
        ("    return [r for r in rows if not _v2_core(r[0])]", "    return list(rows)"),
    "C2 core relabelled RESOLVED instead of cut (a3 HARD: coverage rises with nothing fixed)":
        ("    return [r for r in rows if not _v2_core(r[0])]",
         "    return [(r[0], r[1], \"platform\", r[3]) if _v2_core(r[0]) else r for r in rows]"),
    "C3 the cut is on the value only: core stays in the denominator":
        ("    rows = _v2_domain(rows)\n    if not rows:\n", "    if not rows:\n"),
    "C4 the cut is on the denominator only: the counted edges (mirror, wash rings) keep core":
        ("for rid, caller, author, dq in _v2_domain(rows) if dq", "for rid, caller, author, dq in rows if dq"),
    "C5 CORE_SERVERS re-typed in econ (it no longer follows toolreg)":
        ("    from astryx.core.toolreg import CORE_SERVERS\n", "    CORE_SERVERS = (\"astryx\", \"tools\")\n"),
    "C6 a prefix match: mcp:toolsx/* and mcp:astryx2/* read as core":
        ("    return bool(m) and m.group(1) in CORE_SERVERS", "    return bool(m) and m.group(1).startswith(CORE_SERVERS)"),
    "C7 an only-core window is not NOT_EVALUATED":
        ('''    rows = _v2_domain(rows)
    if not rows:
        return {"value": None, "version": version, "coverage": 0,
                "status": "NOT_EVALUATED: only core-server calls in window; " + V2_DOMAIN}
''', '''    rows = _v2_domain(rows) or rows[:0] or [("", "", "", False)]
'''),
    "C8 the version isn't bumped (a v2.2 coverage reads as comparable with v2.1's)":
        ('V2_VERSION = "v2.2"', 'V2_VERSION = "v2.1"'),
    "C9 the evaluated status doesn't declare the domain":
        ('''else "OK: usage-GDP, compression=1 declared; " + V2_DOMAIN}''', '''else "OK: usage-GDP, compression=1 declared"}'''),
}
