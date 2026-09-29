"""Authored mutants for nucleus/toolreg.py find(): the registry door's ranking, run by
nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_toolreg_find.py

One per rule the ranking rests on. Z1 is the pre-fix matching, steward's #25795 case.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "toolreg.py"
ORACLE = REPO / "tests" / "test_toolreg_find.py"
ENV = "TOOLREG_SRC"

MUTANTS = {
    "Z1 substring matching restored ('is' hits 'list')":
        ("    if q == t:\n        return True\n", "    if q in t or t in q:\n        return True\n"),
    "Z2 no rarity weighting (every word counts 1)":
        ("            score = sum(math.log((n + 1) / (df[w] + 0.5)) for w in hit)",
         "            score = float(len(hit))"),
    "Z3 no relative floor (common-word-only matches kept)":
        ("if -sc >= RELATIVE_FLOOR * best][:limit]", "][:limit]"),
    "Z4 stopwords not dropped":
        ("if w not in _STOP and len(w) > 1})", "if len(w) > 1})"),
    "Z5 prefix matching for short tokens too ('run' → 'rung')":
        ("    return len(q) >= 4 and len(t) >= 4 and", "    return len(q) >= 1 and len(t) >= 1 and"),
    "Z6 prefix one way only (a longer question word misses: 'healthy' → 'health')":
        ("(t.startswith(q) or q.startswith(t))", "t.startswith(q)"),
}
