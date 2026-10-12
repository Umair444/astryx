"""Authored mutants for nucleus/hands_desktop.py's failure message (seed #50593), run by nucleus/mutation_probe.py:

    venv/bin/python nucleus/mutation_probe.py tests/mutants_hands_run_errors.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "nucleus/hands_desktop.py"
ORACLE = REPO / "tests" / "test_hands_run_errors.py"
ENV = "HANDS_DESKTOP_SRC"
TIMEOUT = 60

MUTANTS = {
    "back to stderr only (the canopus symptom: 'grim failed: ')":
        ("        raise HandsError(_failure(argv[0], r.returncode, r.stderr))\n",
         "        raise HandsError(f\"{argv[0]} failed: {r.stderr.decode(errors='replace').strip()[:300]}\")\n"),
    "the signal isn't named":
        ('        how = f"killed by {name}" + (f" ({_SIGNAL_HINT[name]})" if name in _SIGNAL_HINT else "")\n',
         '        how = "killed"\n'),
    "no hint for a known signal":
        ('        how = f"killed by {name}" + (f" ({_SIGNAL_HINT[name]})" if name in _SIGNAL_HINT else "")\n',
         '        how = f"killed by {name}"\n'),
    "stderr is dropped":
        ('    return f"{argv0} failed: {how}" + (f": {err}" if err else ", no stderr")\n',
         '    return f"{argv0} failed: {how}"\n'),
    "the exit code isn't said":
        ('        how = f"exit {rc}"\n',
         '        how = "failed"\n'),
}
