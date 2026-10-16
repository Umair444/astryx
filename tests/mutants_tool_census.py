"""Authored mutants for devtools/tool_census.py (goal 11324 S1's Done instrument) — run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_tool_census.py

Each is a census that would misreport: a domain toggle that toggles nothing, B1 counting core, B2x that is just
naming, a residual that isn't a partition, a cause that never fires, a 'before' that is really 'after'.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "devtools" / "tool_census.py"
ORACLE = REPO / "tests" / "test_tool_census.py"
ENV = "CENSUS_SRC"
TIMEOUT = 300

MUTANTS = {
    "K1 (a)'s 'core in' side keeps the cut (the toggle toggles nothing)":
        ("        toolreg.CORE_SERVERS = ()\n", "        pass\n"),
    "K2 B1 counts the core servers too":
        (''' - set(toolreg.CORE_SERVERS)   # the domain''', '''   # the domain'''),
    "K3 B2x is naming (any position)":
        ("            out += SCRIPT_RE.findall(\" \" + w[0])", "            out += SCRIPT_RE.findall(\" \" + \" \".join(w))"),
    "K4 moved counts every before-unknown row (residual not subtracted)":
        ("        moved = [p for b, p in both if b[2] in bad and p[2] not in bad]", "        moved = [p for b, p in both if b[2] in bad]"),
    "K5 the removed-checkout cause ignores pre-move paths":
        ("[sp] + [k for k, v in toolreg._MOVED.items() if v == sp]", "[sp]"),
    "K6 'before' authors with this tree's toolreg":
        ("            wb = tb.authorship(cur, sorted({r[0] for r in raw}))", "            wb = toolreg.authorship(cur, sorted({r[0] for r in raw}))"),
}
