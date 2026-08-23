"""Authored mutants for memory's wiki_drift index-state parser — run by mutation_probe.

    venv/bin/python nucleus/mutation_probe.py nucleus/mutants_wiki_drift.py

M1 IS THE REAL DEFECT, not an invented one: the character class that was narrower than its
own caller's `.lower()`, so the normalisation was decoration and a capitalised state raised
a false UNPARSED on a healthy line. It stays here because the fix is one character wide and
the next person widening this regex has no other way to learn what it cost.

M3 and M5 attack the two directions this parser can fail. M3 makes an unreadable line report
a plausible state — failing SILENT, which for a detector is the direction that buys nothing.
M5 makes every line readable, which is the same failure wearing confidence. Between them
they pin that UNPARSED must mean UNPARSED and must not mean "whatever word was nearby".

THIS FILE ALSO EXISTS TO PROVE THE ORACLE IS WIRED. forge lost a 33/33 suite on 2026-08-20
to an oracle that ignored the subject path the probe handed it and imported the real module
instead — green against ten broken copies it never opened. A clean sweep of NOT PROBED here
would mean the same fault, not ten coverage gaps.

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list — see the probe's docstring
on why it may never report an assertion as vacuous.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "triggers" / "memory" / "wiki_drift.py"
ORACLE = REPO / "tests" / "test_wiki_drift.py"
ENV = "WIKI_DRIFT_SRC"

MUTANTS = {
    # The defect that motivated the oracle: a matcher narrower than its own normaliser.
    "M1 class narrowed back to lower case (the real defect)":
        ('INDEX_STATE_RE = re.compile(r"→\\s*([A-Za-z-]+)")',
         'INDEX_STATE_RE = re.compile(r"→\\s*([a-z-]+)")'),

    # Hyphens gone: `blocked-on-him` truncates to `blocked` and silently becomes a state
    # nobody declared, which the goal-state comparison would then report as drift.
    "M2 hyphen dropped from the state class":
        ('INDEX_STATE_RE = re.compile(r"→\\s*([A-Za-z-]+)")',
         'INDEX_STATE_RE = re.compile(r"→\\s*([A-Za-z]+)")'),

    # FAILING SILENT: an unreadable line reports a plausible state instead of admitting it
    # could not read one. The index could then rot indefinitely with the lint quiet.
    "M3 UNPARSED replaced by a plausible default":
        ('out[int(gid)] = m.group(1).lower() if m else "UNPARSED"',
         'out[int(gid)] = m.group(1).lower() if m else "shipped"'),

    # The normalisation removed: case now leaks into the comparison, which is the original
    # defect from the other end — the matcher admits it and the caller no longer folds it.
    "M4 .lower() removed from the caller":
        ('out[int(gid)] = m.group(1).lower() if m else "UNPARSED"',
         'out[int(gid)] = m.group(1) if m else "UNPARSED"'),

    # The arrow was the whole discriminator between "this line states a state" and "this
    # line contains a word". Without it, prose parses.
    "M5 arrow anchor dropped — any nearby word becomes the state":
        ('INDEX_STATE_RE = re.compile(r"→\\s*([A-Za-z-]+)")',
         'INDEX_STATE_RE = re.compile(r"([A-Za-z-]+)")'),

    # Only the first goal line in the file is seen; every later one silently vanishes from
    # the expected set, so the index can drift anywhere below line one.
    "M6 MULTILINE dropped from the line regex":
        ('INDEX_LINE_RE = re.compile(r"^\\s*-\\s*\\[\\[goal-(\\d+)\\]\\](.*)$", re.MULTILINE)',
         'INDEX_LINE_RE = re.compile(r"^\\s*-\\s*\\[\\[goal-(\\d+)\\]\\](.*)$")'),
}
