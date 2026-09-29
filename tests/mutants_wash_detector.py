"""Authored mutants for nucleus/wash_detector.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_wash_detector.py

THE LIST IS THE JUDGEMENT: each mutant is one of the plausible WRONG ring detectors the oracle's
docstring names. A survivor is a live oracle gap to surface, not a mutant to drop. Coverage is
bounded by this list; the probe reports CAUGHT or NOT PROBED, never "vacuous".
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "wash_detector.py"
ORACLE = REPO / "tests" / "test_wash_detector.py"
ENV = "WASH_SRC"

MUTANTS = {
    "M1 a two-agent ring is not reported (components of 3+ only)":
        ("comps = [c for c in _sccs(edges) if len(c) > 1]",
         "comps = [c for c in _sccs(edges) if len(c) > 2]"),
    "M2 unresolved authors become edges (every 'unknown' tool merges into one fake ring)":
        ("        if author in _UNRESOLVED or caller in _UNRESOLVED:\n            continue\n", ""),
    "M3 raw rows instead of the GDP-counted set (self-use and unqualified calls count)":
        ("    counted = _v2_counted(rows)\n",
         "    counted = {(r[0], r[1], r[2]) for r in rows}\n"),
    "M4 any cross-use is a ring (edges made undirected)":
        ("        edges.setdefault(caller, set()).add(author)\n",
         "        edges.setdefault(caller, set()).add(author)\n"
         "        edges.setdefault(author, set()).add(caller)\n"),
    "M5 an empty window reads as a measured 0 share":
        ('''        return {"rings": [], "ring_pairs": 0, "counted_pairs": 0, "share": None,''',
         '''        return {"rings": [], "ring_pairs": 0, "counted_pairs": 0, "share": 0.0,'''),
}
