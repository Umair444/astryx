"""Authored mutants for restore_drill.sh's row-count gate (seed #61553), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_restore_drill_counts.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts" / "restore_drill.sh"
ORACLE = REPO / "tests" / "test_restore_counts.py"
ENV = "RESTORE_DRILL_SRC"
TIMEOUT = 120

MUTANTS = {
    "E1 run alone, an empty table passes (the drill's own gate weakened)":
        ('  elif [ "$n" = 0 ] && [ -n "$live0" ]; then', '  elif [ "$n" = 0 ]; then'),
    "E2 ANY handed live count makes an empty table pass (live holds rows, the restore lost them)":
        ("""case " ${RESTORE_LIVE_COUNTS:-} " in *" $t=0 "*) live0=1 ;; esac""",
         """case " ${RESTORE_LIVE_COUNTS:-} " in *" $t="*) live0=1 ;; esac"""),
    "E3 a table that did not restore passes beside an empty live one":
        ('  elif [ "$n" = 0 ] && [ -n "$live0" ]; then', '  elif [ -n "$live0" ]; then'),
}
