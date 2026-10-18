"""Authored mutants for init.sh (plan-11324 S3b 4/n: a unit NAME is host-wide), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_units_init.py

Each is units() writing another org's name, or a unit no org should write.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_org_home_units.py"
ENV = "ORG_HOME_INIT_SRC"
TIMEOUT = 300

MUTANTS = {
    'V1 in a cog of several orgs the file is the plain name (two orgs write one file)':
        ('    _UF="$UD/$1@$UORG.$2"\n',
         '    _UF="$UD/$1.$2"\n'),
    "V2 a COG-scoped unit is written by an org's run":
        ('    case " $UCOG " in *" $1 "*) echo',
         '    case " " in *" $1 "*) echo'),
    'V3 a port-binding unit is written with its fixed port in a cog of several orgs':
        ('    case " $UPORT " in *" $1 "*) echo',
         '    case " " in *" $1 "*) echo'),
    'V4 a unit write bypasses _uw (the pulse timer, plain name, every org)':
        ('  _uw astryx-pulse timer && cat > "$_UF" <<EOF\n',
         '  cat > "$UD/astryx-pulse.timer" <<EOF\n'),
}
