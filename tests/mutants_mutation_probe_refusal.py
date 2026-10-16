"""Authored mutants for devtools/mutation_probe.py's refusal tail, run by devtools/mutation_probe.py itself.

    venv/bin/python devtools/mutation_probe.py tests/mutants_mutation_probe_refusal.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "mutation_probe.py"
ORACLE = REPO / "tests" / "test_mutation_probe_refusal.py"
ENV = "MUTATION_PROBE_SRC"
TIMEOUT = 200
MUTANTS = {
    "T1 a failing baseline's refusal prints no tail (the bare 'exit 1' again)":
        ('        _print_tail(oracle, base_out, f"exit {base}")\n', ''),
    "T2 a timed-out baseline's refusal prints no tail":
        ('        _print_tail(oracle, base_out, "before the kill")\n', ''),
    "T3 the failing lines aren't put first (only the last lines: an early FAIL scrolls away)":
        ('    for ln in hot + lines[-n:]:', '    for ln in lines[-n:]:'),
    "T4 a timeout drops what the oracle printed before the kill":
        ('            return TIMED_OUT, "".join(part)', '            return TIMED_OUT, ""'),
    "T5 the block is not capped":
        ('    return keep[:n]', '    return keep'),
}
