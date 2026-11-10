"""Authored mutants for devtools/mutation_probe.py's TREE form, run by devtools/mutation_probe.py itself.

    venv/bin/python devtools/mutation_probe.py tests/mutants_mutation_probe_tree.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "mutation_probe.py"
ORACLE = REPO / "tests" / "test_mutation_probe_tree.py"
ENV = "MUTATION_PROBE_SRC"
TIMEOUT = 400
MUTANTS = {
    "Q1 the in-place baseline is skipped (a red oracle grades every mutant CAUGHT)":
        ("        if rc0 != 0:\n", "        if False:\n"),
    "Q2 no canary (an oracle that reads none of its subjects is graded)":
        ("            if rc_c == 0:\n", "            if False:\n"),
    "Q3 the relocated baseline is ignored (a copy missing a file reads CAUGHT)":
        ("            if rc_r != 0:\n", "            if False:\n"),
    "Q4 an oracle's skip (77) is scored CAUGHT":
        ("            elif rc_m == EXIT_SKIP:\n", "            elif False:\n"),
    "Q5 a timed-out mutant is scored CAUGHT":
        ("            if rc_m == TIMED_OUT:\n", "            if False:\n"),
    "Q6 an anchor's count isn't checked (a 2x anchor is applied at its first match)":
        ("            if hits != 1:\n", "            if hits < 1:\n"),
    "Q7 the mutation lands in the CHECKOUT, not the copy":
        ("        (dest / rel).write_text(text)\n", "        (root / rel).write_text(text)\n"),
    "Q8 SIGTERM isn't handled (a TERM'd run strands its copies)":
        ("            self.prev = signal.signal(signal.SIGTERM, self._exit)\n", "            self.prev = None\n"),
    "Q9 the oracle sees the HOST's registry (the pin dropped)":
        ("    env.update(ASTRYX_COG_REGISTRY=", "    env.update(_UNPINNED_REGISTRY="),
    "Q10 a subject git doesn't list is accepted (written into the copy anyway)":
        ("            if rel.as_posix() not in listed:\n", "            if False:\n"),
    "Q11 the tree runner's stdout is block-buffered (a timeout's kill discards what the oracle printed)":
        ('[sys.executable, "-u", oracle.as_posix()]', '[sys.executable, oracle.as_posix()]'),
    "Q12 untracked files don't travel (an uncommitted spec or oracle is missing from the copy)":
        ('"ls-files", "-z", "--cached", "--others", "--exclude-standard"]', '"ls-files", "-z", "--cached"]'),
}
