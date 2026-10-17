"""Authored mutants for devtools/org_census.py (plan-11324 S3a; a2 #58917 R-1/R-2), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_census.py

Each restores a census that UNDER-reads: the walk a hand-kept list of roots again (R-1), the org's gitignored estate
read as the core's code, and the two shell forms vitals.sh carried (a quoted command substitution, a `:-` default).
The oracle loads the census from ORG_CENSUS_SRC.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "devtools/org_census.py"
ORACLE = REPO / "tests" / "test_org_home_census.py"
ENV = "ORG_CENSUS_SRC"

MUTANTS = {
    "W1 the walk is a hand-kept list of roots again (a2 R-1: skills/, harness/ unread)":
        ('    files = keep if keep is not None else {p for p in root.rglob("*")}\n',
         '    files = {p for p in (keep if keep is not None else root.rglob("*")) if p.relative_to(root).parts[0] in\n'
         '             ("src", "mcp", "devtools", "scripts", "channel", "bridges", "hooks", "observatory", "canvas",\n'
         '              "tests", "init.sh")}\n'),
    "W2 the org's gitignored estate is read as the core's code (merge_check's linked tree)":
        ("    keep = _not_ignored(root)\n", "    keep = None\n"),
    "G1 a quoted command substitution is stripped as a label (vitals.sh:147)":
        (' and not re.search(r"\\$\\(|`", m.group())', ""),
    "G2 a `:-` default is not a lead (vitals.sh:87)":
        ('|:-)(?:\\./)?"""', ')(?:\\./)?"""'),
}
