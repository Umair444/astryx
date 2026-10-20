"""Authored mutants for devtools/rebase_equiv.py (a4 night-review 10-21): each is a plausible WRONG equivalence test,
the ones a hand chain uses (blob equality, patch-id, %B messages) included. Every one must be CAUGHT.

    venv/bin/python devtools/mutation_probe.py tests/mutants_rebase_equiv.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "rebase_equiv.py"
ORACLE = REPO / "tests" / "test_rebase_equiv.py"
ENV = "REBASE_EQUIV_SRC"

MUTANTS = {
    "Q1 the verdict is BLOB equality (a context-only rebase reads DIFFERS)":
        ("        same = changed_lines(a, b, f) == changed_lines(c, d, f)\n",
         "        same = git(\"rev-parse\", f\"{b}:{f}\", check=False) == git(\"rev-parse\", f\"{d}:{f}\", check=False)\n"),
    "Q2 the verdict is PATCH-ID (it hashes context: a context-only rebase reads DIFFERS)":
        ("        same = changed_lines(a, b, f) == changed_lines(c, d, f)\n",
         "        same = patch_id(a, b, f) == patch_id(c, d, f)\n"),
    "Q3 the compared lines keep their CONTEXT (' '-led), so a neighbour's edit reads as a change":
        ('    out = git("diff", "--no-renames", "-U0", "--no-color", a, b, "--", f)\n'
         '    return [ln for ln in out.split("\\n") if ln[:1] in "+-"',
         '    out = git("diff", "--no-renames", "--no-color", a, b, "--", f)\n'
         '    return [ln for ln in out.split("\\n") if ln[:1] in "+- "'),
    "Q4 messages are never compared (the stripped '#' line passes)":
        ("        if message(p) != message(q):", "        if False:"),
    "Q5 messages compared after stripping '#' lines, as git's own cleanup does":
        ("    return raw.split(\"\\n\\n\", 1)[1] if \"\\n\\n\" in raw else \"\"",
         "    return \"\\n\".join(ln for ln in (raw.split(\"\\n\\n\", 1)[1] if \"\\n\\n\" in raw else \"\").split(\"\\n\")"
         " if not ln.startswith(\"#\"))"),
    "Q6 the commit count isn't checked":
        ("    if len(old) != len(new):", "    if False:"),
    "Q7 --onto's conflict is printed but never fails the verdict":
        ("            bad.append(f\"ONTO {onto}@{o[:7]}: {d[:7]} CONFLICTS in {paths}, so it does not land as it stands\")",
         "            out.append(f\"ONTO {onto}@{o[:7]}: {d[:7]} CONFLICTS in {paths}, so it does not land as it stands\")"),
    "Q8 a bad ref reads as rc 1 (a difference), not rc 2 (usage)":
        ("        return 2, [f\"rebase_equiv: {e if str(e) else 'want two ranges A..B C..D'}\"]",
         "        return 1, [f\"rebase_equiv: {e if str(e) else 'want two ranges A..B C..D'}\"]"),
    "Q10 a binary file is compared by its (empty) +/- lines, so any two binary changes read equal":
        ("        if binary(a, b, f) or binary(c, d, f):", "        if False:"),
    "Q9 the file set isn't compared (a dropped file passes if the rest is equal)":
        ("    if fo != fn:", "    if False:"),
}
