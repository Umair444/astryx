"""Authored mutants for scripts/org_tmux.sh (plan-11324 S3b, host-wide namespaces: kind tmux), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_home_ns_orgtmux.py

Each is a plausible wrong shell door: the function dropping the socket, a refusal read as one org, one org asking
python anyway.
The oracle runs every child from an estate-free fixture checkout; the fixture writes the mutant over this subject
there (tests/org_home_fixture.py SEAMS), so a mutant is executed where the arms execute, never from a temp path.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts/org_tmux.sh"
ORACLE = REPO / "tests" / "test_org_home_namespace.py"
ENV = "ORG_HOME_ORGTMUX_SRC"
TIMEOUT = 300

MUTANTS = {
    'Z1 the tmux function drops -L (spawn on the default socket)':
        ('tmux() { command tmux ${AX_SOCK:+-L "$AX_SOCK"} "$@"; }\n',
         'tmux() { command tmux "$@"; }\n'),
    'Z2 an unplaceable HOME is read as one org (the default socket as a guess)':
        ('       exit 2 ;;\n',
         '       AX_SOCK="" ;;\n'),
    'Z3 one org asks python too (a host with no registry still needs one)':
        ('if [ -e "${ASTRYX_ORG_REGISTRY:-/etc/astryx/orgs.json}" ]; then\n',
         'if true; then\n'),
}
