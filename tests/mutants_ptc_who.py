"""Authored mutants for devtools/pushed_tree_check.sh's WHO LAST TOUCHED block (a4 10-25). Every one must be CAUGHT by
tests/test_ptc_who.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_ptc_who.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "pushed_tree_check.sh"
ORACLE = REPO / "tests" / "test_ptc_who.py"
ENV = "PTC_SRC"

MUTANTS = {
    "P1 the FAILED labels are the old sed range over the whole log (a gate's own ✗ is listed, a1 #62905)":
        ('  fails=$(python3 -I "$REPO/devtools/check_verdict.py" --failed "$LOG" 2>"$TMP/verdict.err"); frc=$?',
         "  fails=$(sed -n '/^FAILED (/,/^UNVERIFIED (/p' \"$LOG\" | sed -n 's/^  ✗ //p'); frc=$?"),
    "P2 only a nucleus/ word maps (every gate since goal 10224 reads 'could not map')":
        ("grep -m1 -E '^(tests|src|devtools|scripts|nucleus|bridges|observatory)/')", "grep -m1 '^nucleus/')"),
    "P3 a `-m a.b.c` run line is never mapped":
        ('        [ -n "$mod" ] && script="src/${mod//.//}.py"', '        true'),
    "P4 a label's quotes are matched raw (check.sh's source writes \\\")":
        ('        line=$(grep -F -- "run \\"${key//\\"/\\\\\\"}\\"" "$TREE/devtools/check.sh" | head -1)',
         '        line=$(grep -F -- "run \\"$key\\"" "$TREE/devtools/check.sh" | head -1)'),
    "P5 a FAILED entry is looked up only as is (check.sh's own TIMED OUT suffix reads 'could not map', a1 #62937)":
        ("        key=${key% (*}\n", "        break\n"),
    "P6 a parser that can't answer leaves no trace (the WHO list silently vanishes on a red run)":
        ('    echo "WHO LAST TOUCHED: could not read the FAILED block (check_verdict.py rc $frc): ${err##*$\'\\n\'}"\n', ""),
    "P7 the parser's stderr is folded into the label list (a warning on rc 0 is listed as a failing gate)":
        ('--failed "$LOG" 2>"$TMP/verdict.err"); frc=$?', '--failed "$LOG" 2>&1); frc=$?'),
}
