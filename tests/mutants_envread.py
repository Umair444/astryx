"""Authored mutants for config.read_env's per-line decode (plan-10224 ENVREAD), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_envread.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "config.py"
ORACLE = REPO / "tests" / "test_envread.py"
ENV = "ENVREAD_CONFIG_SRC"
TIMEOUT = 300

MUTANTS = {
    "V1 the whole file is refused on one bad byte (every key blinded, the DSN too)":
        ('            text = chunk.decode("utf-8")', '            text = raw.decode("utf-8")'),
    "V2 a bad line is decoded with replacement, SILENTLY (no word on stderr)":
        ('        try:\n            text = chunk.decode("utf-8")\n        except UnicodeDecodeError:',
         '        text = chunk.decode("utf-8", "replace")\n        if False:'),
    "V3 the warning prints the bad line (its value leaks to a log)":
        ('            print(f"config.read_env: {p}:{n}: not UTF-8, line skipped"',
         '            print(f"config.read_env: {p}:{n}: not UTF-8, line skipped {chunk!r}"'),
    "V4 the bad line's key is not held absent: its later line is taken in its place":
        ('            if k and k == k.strip() and k not in out and k not in lost:',
         '            if k and k == k.strip() and k not in out:'),
    "V5 the skip is said on stdout, not stderr (a `$(config.py get …)` would swallow it into the value)":
        ('                  + (f" ({k} reads as absent)" if k and k not in out else ""), file=sys.stderr)',
         '                  + (f" ({k} reads as absent)" if k and k not in out else ""))'),
}
