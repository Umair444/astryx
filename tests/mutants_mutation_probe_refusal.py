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
        ('    for ln in first + hot + lines[-n:]:', '    for ln in lines[-n:]:'),
    "T4 a timeout drops what the oracle printed before the kill":
        ('            return TIMED_OUT, "".join(part)', '            return TIMED_OUT, ""'),
    "T5 the block is not capped":
        ('    return keep[:n]', '    return keep'),
    "T6 the oracle's stdout is block-buffered again (a timeout's kill discards it: a3 #57897 R-1)":
        ('    env = dict(os.environ, PYTHONUNBUFFERED="1", **{env_var: str(subject_path)})',
         '    env = dict(os.environ, **{env_var: str(subject_path)})'),
    "T7 failures aren't ranked above keyword mentions (30 PASS labels crowd the real FAIL out)":
        ('    for ln in first + hot + lines[-n:]:', '    for ln in hot + first + lines[-n:]:'),
    "T8 no relocated baseline (an unmutated copy that dies at the mutant location grades every mutant CAUGHT: a4 #60129)":
        ('        if rb != 0:\n', '        if False:\n'),
    "T9 every copy shares one path again (a same-size copy in the same mtime second runs the previous copy's .pyc: memory #60378)":
        ('            p = Path(td) / slot / rel\n', '            p = Path(td) / rel\n'),
}
