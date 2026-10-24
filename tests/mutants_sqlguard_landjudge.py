"""Authored mutants for the sqlguard land judge (plan-11908 D6), tree form, run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_sqlguard_landjudge.py
"""
LJ = "src/astryx/security/sqlguard/landjudge.py"
ORACLE = "tests/test_sqlguard_landjudge.py"
MUTANTS = {
    "J-M1 the move rule is off (a rename reads as a new site)":
        (LJ, "    return {k for k in new if text_key(k) in gone_tk}", "    return set()"),
    "J-M2 a site below RESPONSIVE passes":
        (LJ, '        elif rung == "RESPONSIVE":', '        elif True:'),
    "J-M3 an R-BLIND in a touched file is not refused":
        (LJ, '        if b["frame"][0] in touched_files:', '        if False:'),
    "J-M4 the cheap trigger is gone: a tests/-only range builds inventories":
        (LJ, "    if not code_changed(tree, a, b):", "    if False:"),
    "J-M6 the children grade with the graded tree's own sqlguard (no -P: the 309d8c23 live replay's KeyError 'seal')":
        (LJ, 'PYC = [sys.executable, "-P"]', "PYC = [sys.executable]"),
    "J-M7 a green verdict keeps its trace dir":
        (LJ, "    if rc == 0:\n        for d in made:", "    if False:\n        for d in made:"),
    "J-M5 a range that adds a site with no oracle passes":
        (LJ, '            log(f"land judge: REFUSED, the range adds {len(intro)} SQL site(s) and no test_*.py oracle to grade them")\n            return 1',
             '            log(f"land judge: REFUSED, the range adds {len(intro)} SQL site(s) and no test_*.py oracle to grade them")\n            return 0'),
}
