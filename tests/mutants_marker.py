"""Authored mutants for devtools/marker.sh (a4 night-review 10-22). Every one must be CAUGHT by tests/test_marker.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_marker.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "marker.sh"
ORACLE = REPO / "tests" / "test_marker.py"
ENV = "MARKER_SRC"

MUTANTS = {
    "K1 the range's base is the base ref's tip, not the merge-base (other people's commits ride the range)":
        ('echo "range (full): $BR $MB..$HEAD_SHA"', 'echo "range (full): $BR $BASE_SHA..$HEAD_SHA"'),
    "K2 a branch that moved during the check still gets a clause (it names a tip nobody checked)":
        ('[ "$NOW" = "$HEAD_SHA" ] || die', 'true || die'),
    "K3 a check with no verdict line still gets a clause (a killed run reads like a result)":
        ('[ -n "$verdict" ] || die', 'true || die'),
    "K4 the FAILED set is never copied (every clause says FAILED none)":
        ("sed -n 's/^  ✗ //p'", "sed -n 's/^NEVER //p'"),
    "K5 the check is handed a 12-hex prefix, not the full sha":
        ('$PTC "$HEAD_SHA" >"$LOG" 2>&1; rc=$?', '$PTC "${HEAD_SHA:0:12}" >"$LOG" 2>&1; rc=$?'),
    "K6 the clause prints a merge-ready line itself (self-marking)":
        ('echo "marker clause: $BR', 'echo "merge-ready: $BR'),
    "K7 PY unset falls back to a bare python3 (every DSN/venv suite hides as a 77 skip)":
        ('export PY=${PY:-$(dirname "$here")/venv/bin/python}', 'export PY=${PY:-python3}'),
    "K8 --by is parsed but the clause still says (author)":
        ('pushed_tree_check ${HEAD_SHA:0:12} ($BY): rc', 'pushed_tree_check ${HEAD_SHA:0:12} (author): rc'),
    "K9 --by takes any string (a clause can name a non-agent)":
        ('[[ $2 =~ ^[a-z0-9][a-z0-9-]*$ ]]', 'true'),
}
