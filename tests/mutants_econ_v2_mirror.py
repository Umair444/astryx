"""Authored mutants for nucleus/econ.py's S2 surface — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_econ_v2_mirror.py

THE LIST IS THE JUDGEMENT: each is a plausible wrong S2 — a gate that admits the tainted v2.0
rows, a ledger read that counts unversioned calls, a mirror that counts self-use or leaks a
name, a line that ranks. A survivor is a live oracle gap to surface, not a mutant to drop.
Coverage is bounded by this list; the probe reports CAUGHT or NOT PROBED, never "vacuous".
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "econ.py"
ORACLE = REPO / "tests" / "test_econ_v2_mirror.py"
ENV = "ECON_SRC"

MUTANTS = {
    "M1 the gate admits any versioned record (v2.0 included)":
        ("    return v2 if ver is not None and ver >= V2_MIN else None",
         "    return v2 if ver is not None else None"),
    "M2 the gate is == V2_MIN (a later minor is refused — the next bump would blind every reader)":
        ("    return v2 if ver is not None and ver >= V2_MIN else None",
         "    return v2 if ver is not None and ver == V2_MIN else None"),
    "M3 the ledger read counts unversioned calls (no meta.v filter)":
        ("s.meta ? 'registry_id' AND s.meta ? 'v'", "s.meta ? 'registry_id'"),
    "M4 the mirror counts self-use (raw rows, not the GDP-counted set)":
        ("    for rid, caller, author in _v2_counted(rows):\n        if author in (None, \"unknown\"):",
         "    for rid, caller, author in {(r[0], r[1], r[2]) for r in rows}:\n"
         "        if author in (None, \"unknown\"):"),
    "M5 the mirror keeps caller NAMES (a record is no longer self-scoped)":
        ('''    return {"value": {k: {f: len(v[f]) for f in ("tools", "callers", "pairs")} for k, v in per.items()},''',
         '''    return {"value": {k: {**{f: len(v[f]) for f in ("tools", "callers", "pairs")}, "who": sorted(v["callers"])} for k, v in per.items()},'''),
    "M6 the line ranks the reader":
        ('''agent(s), {mine['pairs']} tool×caller pair(s) ({tail})")''',
         '''agent(s), {mine['pairs']} tool×caller pair(s) ({tail}) · rank 3")'''),
    "M7 a degenerate ledger renders as a measured 'no tool of yours'":
        ('''    if not status or status.startswith("NOT_EVALUATED"):''',
         '''    if not status:'''),
}
