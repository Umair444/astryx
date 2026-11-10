"""Authored mutants for devtools/probe_all.sh's refusal block, run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_probe_all.py

RESOLUTION, stated: no arm requires a MINIMUM number of tail lines, so `tail -8` → `tail -3` survives by design (the
header, not the tail's length, is the discriminator); the upper bound is pinned by A4 (P2).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "probe_all.sh"
ORACLE = REPO / "tests" / "test_probe_all.py"
ENV = "PROBE_ALL_SRC"
MUTANTS = {
    "P1 the header is never printed (today's bare tail)":
        ('then printf \'%s\\n\' "$hdr"; fi', "then :; fi"),
    "P2 the tail is unbounded enough to flood the log (tail -30)":
        ('last=$(tail -8 <<<"$out")', 'last=$(tail -30 <<<"$out")'),
    "P3 the header is printed even when the tail already holds it (twice)":
        ('if [ -n "$hdr" ] && ! grep -qF -- "$hdr" <<<"$last"; then', 'if [ -n "$hdr" ]; then'),
    "P4 only REFUSING is a header (a WIRING FAULT is cut off again)":
        ("grep -E '^(REFUSING|WIRING FAULT):'", "grep -E '^(REFUSING):'"),
    "P5 the refused set no longer names its spec":
        ('echo "REFUSED: ${REFUSED[*]} — the oracle', 'echo "REFUSED: — the oracle'),
}
