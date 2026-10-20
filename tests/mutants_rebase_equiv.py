"""Authored mutants for devtools/rebase_equiv.py (a4 night-review 10-21, rebuilt on a3 #61571's per-commit replay): each
is a plausible WRONG equivalence test, the ones a hand chain or this tool's first cut used included. Every one must be
CAUGHT.

    venv/bin/python devtools/mutation_probe.py tests/mutants_rebase_equiv.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "rebase_equiv.py"
ORACLE = REPO / "tests" / "test_rebase_equiv.py"
ENV = "REBASE_EQUIV_SRC"

MUTANTS = {
    "R1 a clean replay is PROVEN without comparing its tree to the rebased one (the first cut's blind spot)":
        ("        if diff:\n            bad.append(f\"{tag}: the replay is clean but its tree differs",
         "        if False:\n            bad.append(f\"{tag}: the replay is clean but its tree differs"),
    "R2 a conflicted replay is treated as PROVEN (hand resolution reads as machine proof)":
        ("    return bool(hand)\n", "    return False\n"),
    "R3 the replay is skipped: the first cut's range-level -U0 compare is the verdict":
        ("            hand |= replay(i, p, q, out, bad)",
         "            [bad.append(f'CHANGE in {f}') for f in files(f'{p}^', p) if changed_lines(f'{p}^', p, f) "
         "!= changed_lines(f'{q}^', q, f)]"),
    "R4 the merge base is q^ (a plain 3-way of the twins' parents), not the reviewed commit's own parent":
        ('f"--merge-base={p}^", f"{q}^", p]', 'f"--merge-base={q}^", f"{q}^", p]'),
    "R5 non-conflicted files of a conflicted commit aren't compared":
        ("    if others:\n        bad.append(", "    if False:\n        bad.append("),
    "R6 the fallback keeps CONTEXT (' '-led lines), so a neighbour's edit reads as a change":
        ('    return [ln for ln in out.split("\\n") if ln[:1] in "+-"',
         '    out = git("diff", "--no-renames", "--no-color", a, b, "--", f)\n'
         '    return [ln for ln in out.split("\\n") if ln[:1] in "+- "'),
    "R7 the fallback ignores the mode":
        ('    if entry(p, f).split(" ")[0] != entry(q, f).split(" ")[0]:', "    if False:"),
    "R8 the fallback compares a binary by its (empty) +/- lines":
        ("    if binary(f\"{p}^\", p, f) or binary(f\"{q}^\", q, f):", "    if False:"),
    "R9 messages are never compared (the stripped '#' line passes)":
        ("        if message(p) != message(q):", "        if False:"),
    "R10 messages compared after stripping '#' lines, as git's own cleanup does":
        ("    return raw.split(\"\\n\\n\", 1)[1] if \"\\n\\n\" in raw else \"\"",
         "    return \"\\n\".join(ln for ln in (raw.split(\"\\n\\n\", 1)[1] if \"\\n\\n\" in raw else \"\").split(\"\\n\")"
         " if not ln.startswith(\"#\"))"),
    "R11 the commit count isn't checked":
        ("    if len(old) != len(new):", "    if False:"),
    "R12 a merge commit in a range isn't refused":
        ("    if merges:\n        return 2,", "    if False:\n        return 2,"),
    "R13 --onto's conflict is printed but never fails the verdict":
        ("            bad.append(f\"ONTO {onto}@{o[:7]}: {d[:7]} CONFLICTS in {paths}, so it does not land as it stands\")",
         "            out.append(f\"ONTO {onto}@{o[:7]}: {d[:7]} CONFLICTS in {paths}, so it does not land as it stands\")"),
    "R14 HAND-RESOLVED returns rc 0 (unproven placement reads as SAME WORK)":
        ("        return 3, out", "        return 0, out"),
    "R15 a bad ref reads as rc 1 (a difference), not rc 2 (usage)":
        ("        return 2, [f\"rebase_equiv: {e if str(e) else 'want two ranges A..B C..D'}\"]",
         "        return 1, [f\"rebase_equiv: {e if str(e) else 'want two ranges A..B C..D'}\"]"),
}
