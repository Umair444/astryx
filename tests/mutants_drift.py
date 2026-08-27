"""Authored mutants for memory's consolidated drift-lint — run by mutation_probe.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_drift.py

These are the SAME six defects the retired mutants_wiki_drift.py pinned, re-aimed at
memory/lints/drift.py — the 5→1 consolidation must not lose kill-coverage when it retires the
old oracle. M1 is the real defect that first motivated an oracle here (a character class
narrower than its own caller's `.lower()`, making the normalisation decoration). M3/M5 attack
the two directions the parser can fail: M3 makes an unreadable line report a plausible state
(failing SILENT — the direction that buys nothing for a detector); M5 makes any nearby word a
state (the same failure wearing confidence). Between them they pin that UNPARSED must mean
UNPARSED and must not mean "whatever word was nearby".

THIS FILE ALSO PROVES THE ORACLE IS WIRED to its subject argument: mutation_probe hands the
oracle a mutated COPY via DRIFT_SRC, and test_drift.py reads exactly that path. A clean sweep
of NOT PROBED would be a wiring fault (forge lost a 33/33 suite to that in 2026-08-20), not
coverage. Coverage is bounded by this list — not a claim of completeness.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "memory" / "lints" / "drift.py"
ORACLE = REPO / "tests" / "test_drift.py"
ENV = "DRIFT_SRC"

MUTANTS = {
    # M1 — the real defect: matcher narrower than its own normaliser. Killed by the
    # case-fold arm (ACTIVE would no longer match, raising a false UNPARSED).
    "M1 class narrowed back to lower case (the real defect)":
        ('INDEX_STATE_RE = re.compile(r"→\\s*([A-Za-z-]+)")',
         'INDEX_STATE_RE = re.compile(r"→\\s*([a-z-]+)")'),

    # M2 — hyphen dropped: `blocked-on-him` truncates to `blocked`, a state nobody declared,
    # which the comparison then reports as drift. Killed by the hyphenated-state arm.
    "M2 hyphen dropped from the state class":
        ('INDEX_STATE_RE = re.compile(r"→\\s*([A-Za-z-]+)")',
         'INDEX_STATE_RE = re.compile(r"→\\s*([A-Za-z]+)")'),

    # M3 — FAILING SILENT: an unreadable line reports a plausible state instead of UNPARSED.
    # Killed by the unparsed arm (raw='active' so the planted 'shipped' becomes drift, not the
    # expected unparsed finding).
    "M3 UNPARSED replaced by a plausible default":
        ('out[int(gid)] = s.group(1).lower() if s else "UNPARSED"',
         'out[int(gid)] = s.group(1).lower() if s else "shipped"'),

    # M4 — normalisation removed: case leaks into the comparison. Killed by the case-fold arm.
    "M4 .lower() removed from the caller":
        ('out[int(gid)] = s.group(1).lower() if s else "UNPARSED"',
         'out[int(gid)] = s.group(1) if s else "UNPARSED"'),

    # M5 — arrow anchor dropped: any nearby word becomes the state; prose parses. Killed by
    # the preceding-prose arm ("toy test" would be read as the state).
    "M5 arrow anchor dropped — any nearby word becomes the state":
        ('INDEX_STATE_RE = re.compile(r"→\\s*([A-Za-z-]+)")',
         'INDEX_STATE_RE = re.compile(r"([A-Za-z-]+)")'),

    # M6 — MULTILINE dropped: only the first goal line is seen; the index can drift anywhere
    # below line one. Killed by the later-line-divergence arm.
    "M6 MULTILINE dropped from the line regex":
        ('INDEX_LINE_RE = re.compile(r"^\\s*-\\s*\\[\\[goal-(\\d+)\\]\\](.*)$", re.MULTILINE)',
         'INDEX_LINE_RE = re.compile(r"^\\s*-\\s*\\[\\[goal-(\\d+)\\]\\](.*)$")'),
}
