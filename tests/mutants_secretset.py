"""Authored mutants for nucleus/secretset.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_secretset.py

THE SUBJECT IS secretset.py (the org's one answer to "what is secret here?") AND THE ORACLE IS
tests/test_secretset.py, loaded through SECRETSET_SRC and installed as nucleus.secretset, so the
S1a arms that drive hooks/step.py see the mutant too.

WHY THIS FILE EXISTS (a1 night-review 2026-10-09). Building plan-5497 I checked about fifteen arms
by hand-mutating the subject with sed, watching the arm go RED, and restoring the file. Every one
of those controls was then thrown away: a silent revert would have stayed green, which is my own
09-30 reflection ("a RED control run by hand is not a test") at fifteen times the scale. These are
those mutations, committed, so the mutant battery re-runs them on every change instead of my memory.
Each is a defect that was REAL at some point in the build, or one a reviewer named.

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "secretset.py"
ORACLE = REPO / "tests" / "test_secretset.py"
ENV = "SECRETSET_SRC"

MUTANTS = {
    # B1 (a2 #28956): an unclassified URL with no password/query yielded NOTHING, so a token in a path or
    # the userinfo username was unguarded. Caught by S0.5c/S0.5d.
    "M1 an unclassified URL is no longer guarded whole":
        ("            if k not in URL_CONFIG:\n                pairs.append((k, v))",
         "            if False:\n                pairs.append((k, v))"),
    # 207e865: a URL query param declared "<KEY>:<param>" in NOT_SECRET must not be guarded. S0.6b.
    "M2 the per-parameter NOT_SECRET filter is dropped":
        ("pairs.extend((n, pv) for n, pv in parts if n not in NOT_SECRET)",
         "pairs.extend((n, pv) for n, pv in parts)"),
    # a backslash in a secret is doubled in a JSON transcript line; without this form the sweep and the
    # writer redaction are blind to it (the oracle's own first draft was). S0/S1a arms.
    "M3 the JSON-escaped spelling is no longer a guarded form":
        (', json.dumps(v)[1:-1]}', '}'),
    # a secret that CONTAINS another must redact whole, not leave a tail. S0.15.
    "M4 secrets are no longer redacted longest-first":
        ("return sorted(out, key=lambda s: -len(s.value))", "return out"),
    # redact must walk dict KEYS too. S0.12.
    "M5 redact stops walking dict keys":
        ("return {walk(k): walk(v) for k, v in o.items()}", "return {k: walk(v) for k, v in o.items()}"),
    # a link to a declared holder is not a copy, but a real copy is. M.7.
    "M6 a symlink to a holder is reported as an undeclared copy":
        ("if f.is_symlink() and str(f.resolve()) in declared:", "if False:"),
    # seed #33639 / a2 #33642: an absent out-of-tree copy that a consumer unit loads is DRIFT (dark guard).
    # M.9b, L.6b.
    "M7 an absent copy a consumer unit loads reads NOT SEARCHED, never DRIFT":
        ("                    if users:", "                    if False:"),
    # a2 #33642: keyed on liveness, a unit that went `failed` because the file vanished stops counting. M.10.
    "M8 the consumer is keyed on liveness, not declared intent":
        ("if states[n][0] in CONSUMER_ENABLED or states[n][1] in CONSUMER_ACTIVE], None",
         'if states[n][1] == "active"], None'),
    # a2 #33644: realpath on ONE side only; a symlinked ~/.config hides the consumer. M.11.
    # a2 #39990 (M10): the master POLARITY inverted into a name-pattern denylist, the plausible real-world bug: only
    # keys whose NAME sounds like a credential are guarded, so an unclassified key with an innocent name leaks.
    "M10 an unclassified key is guarded only if its NAME sounds secret (denylist, not fail-safe)":
        ("if k in NOT_SECRET or not v:",
         "if k in NOT_SECRET or not v or not any(t in k for t in "
         "('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'DSN', 'SALT', 'URL')):"),
    "M9 units_using compares the unit's path without realpath":
        ("if os.path.realpath(f) == os.path.realpath(path) and u.name not in names:",
         "if Path(f) == path and u.name not in names:"),
}
