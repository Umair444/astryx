"""Authored mutants for spawn.sh's harness-binary resolution (steward 10-21, seed #61942), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_spawn_cli.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "scripts" / "spawn.sh"
ORACLE = REPO / "tests" / "test_spawn_cli.py"
ENV = "SPAWN_SRC"
TIMEOUT = 120

MUTANTS = {
    "K1 the PATH fallback takes the first claude, wrapper or not (the 10-21 boot death)":
        ('    [ "$(realpath -m "$c")" != "$wrap" ] && { CLI=$c; return 0; }\n', '    CLI=$c; return 0\n'),
    "K2 no install-path fallback (a mise that fails at boot leaves nothing)":
        ('  [ -x "$c" ] && { CLI=$c; return 0; }\n', ''),
    "K3 ASTRYX_CLI is ignored":
        ('  if [ -n "${ASTRYX_CLI:-}" ]; then CLI=$ASTRYX_CLI; return 0; fi\n', ''),
    "K4 an unresolved binary falls back to the bare name instead of refusing":
        ('  return 1\n}\nCLI_REFUSED=', '  CLI=claude; return 0\n}\nCLI_REFUSED='),
}
