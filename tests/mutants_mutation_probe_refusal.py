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
        ('[sys.executable, "-u", str(oracle)]', '[sys.executable, str(oracle)]'),
    "T7 failures aren't ranked above keyword mentions (30 PASS labels crowd the real FAIL out)":
        ('    for ln in first + hot + lines[-n:]:', '    for ln in hot + first + lines[-n:]:'),
    "T8 no relocated baseline (an unmutated copy that dies at the mutant location grades every mutant CAUGHT: a4 #60129)":
        ('        if rb != 0:\n', '        if False:\n'),
    "T9 every copy shares one path again (a same-size copy in the same mtime second runs the previous copy's .pyc: memory #60378)":
        ('            p = Path(td) / slot / rel\n', '            p = Path(td) / rel\n'),
    "T10 the probe adds a name to the oracle's environment again (every org-census baseline refused: seed #60425)":
        ('    env = dict(os.environ, **{env_var: str(subject_path)})', '    env = dict(os.environ, PYTHONUNBUFFERED="1", **{env_var: str(subject_path)})'),
    "T11 outside a git tree the copy is the bare name again (an extract's gateway.py REFUSED a passing battery: a3 #60145)":
        ('    return f.relative_to(os.path.commonpath([f.parent, oracle.resolve().parent]))\n', '    return Path(f.name)\n'),
    "T12 the git root no longer decides the tail (the oracle's shared directory does, inside a tree too)":
        ('        if (a / ".git").exists():\n            return f.relative_to(a)\n', '        if False:\n            return f.relative_to(a)\n'),
    "T13 the estate's marker no longer decides outside git (a subject beside its oracle in tests/ is the bare name: a3 #60809)":
        ('        if (a / "src" / "astryx").is_dir() or (a / "astryx.py").is_file():\n', '        if False:\n'),
    "T14 no registry pin (on a cog host the pulse's monthly battery refuses family after family: a2 #60815)":
        ('    env["ASTRYX_COG_REGISTRY"] = f"{tempfile.gettempdir()}/astryx-probe-{os.getpid()}-no-registry/cog.json"\n', ''),
    'T15 why prefers the `FAIL:` summary over the check line (R13)':
        ('    if checks:\n        more =', '    if checks and not summary:\n        more ='),
    "T16 a crash's why is dressed as a plain exit (R14)":
        ('        return f"a CRASH, not a check: {lines[-1][:180]}"', '        return "no failing line printed (the exit code alone)"'),
    'T17 --only is ignored: every mutant runs (R15)':
        ('    mutants = {k: v for k, v in spec.MUTANTS.items() if not only or any(named(k, o) for o in only)}', '    mutants = dict(spec.MUTANTS)'),
    'T18 a prefix naming no mutant runs nothing and passes (R15)':
        ('    if not mutants:\n        print(f"no mutant in', '    if False:\n        print(f"no mutant in'),
    "T19 a subset's headline claims the authored set (R15)":
        ('        elif only:\n', '        elif False:\n'),
    'T20 the CAUGHT line drops its elapsed seconds (R13)':
        ('            print(f"  CAUGHT                     {n}  ({took})")', '            print(f"  CAUGHT                     {n}")'),
    'T21 --only matches a name PREFIX again (T1 selects T10-T19: R15)':
        ('        return k.startswith(o[:-1]) if o.endswith("*") else k.split()[0] == o', '        return k.startswith(o.rstrip("*"))'),
    'T22 a why drops its (+k more failing) count (R13)':
        ('        return checks[0][:200] + more', '        return checks[0][:200]'),
    "T23 the headline doesn't count crash-caught mutants (R14)":
        ('        if crashed:\n', '        if False:\n'),
}
