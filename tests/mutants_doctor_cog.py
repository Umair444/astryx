"""Authored mutants for init.sh's cog-safe doctor (plan-11324 S3f S7), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_doctor_cog.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_doctor_cog.py"
ENV = "ORG_HOME_INIT_SRC"
TIMEOUT = 1500

MUTANTS = {
    "M1 the disk side is every file of units/ (another org's and the cog's read as the primary's orphans: 'delete')":
        ('    [ -n "${DOCTOR_COG:-}" ] && disk_list=$(echo "$disk_list" | grep -v \'@\' | grep -vE "^(${_cogstems:-^$})\\.")',
         '    :'),
    "M2 only @ files are filtered (the cog's gateway and front read as the primary's orphans)":
        ('| grep -v \'@\' | grep -vE "^(${_cogstems:-^$})\\.")', '| grep -v \'@\')'),
    "M3 doctor's tmux is bare (an inherited $TMUX's server answers for the primary's seats)":
        ('if [ -n "${DOCTOR_COG:-}" ]; then ROOT="$PWD"; . scripts/org_tmux.sh; fi', ':'),
    "M4 any org that resolves gets doctor (lab's run reads the PRIMARY's estate as its own)":
        ('    [ "$_dorg" = "$(venv/bin/python src/astryx/orgs.py primary 2>/dev/null)" ] && [ "$_dhome" = "$(pwd -P)" ] || {',
         '    true || {'),
    "M5 ASTRYX_HOME is not carried (by the marker, doctor's units() renders the COG's set as the primary's)":
        ('    export ASTRYX_HOME="$_dhome"; DOCTOR_COG=1', '    DOCTOR_COG=1'),
    "M6 the filter applies on one org too (an @-named stray is no longer anyone's orphan)":
        ('    [ -n "${DOCTOR_COG:-}" ] && disk_list=', '    true && disk_list='),
}
