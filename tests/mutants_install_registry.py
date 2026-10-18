"""Authored mutants for install.sh's org-registry refusal (plan-11324 S3b, a2 #59696 R-1), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_install_registry.py

On a host with an org registry every org's seed is on its own tmux server, so the installer's "an org is running
here" check is blind, and a pull or reinstall of the core checkout would change code under every live org. The
oracle's D13 arm runs the mutant installer for REAL under trapped git/curl/pipx/sudo (a mutant run writes nothing:
measured by hand, the guard-less installer's only act was the trapped `git clone`).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "install.sh"
ORACLE = REPO / "tests" / "oracle_install_platform.py"   # runs test_install_platform.sh
ENV = "INSTALL_SRC"

MUTANTS = {
    "I1 the registry refusal is gone (the blind tmux check is the only guard)":
        ('  if [ -e "${ASTRYX_COG_REGISTRY:-/etc/astryx/cog.json}" ]; then\n    die "this install is a cog',
         '  if false; then\n    die "this install is a cog'),
    "I2 the refusal fires only when the checkout already exists (a FRESH clone onto a cog of several orgs proceeds)":
        ('  if [ -e "${ASTRYX_COG_REGISTRY:-/etc/astryx/cog.json}" ]; then\n    die "this install is a cog',
         '  if [ -e "${ASTRYX_COG_REGISTRY:-/etc/astryx/cog.json}" ] && [ -e "$ASTRYX_DIR/.git" ]; then\n    die "this install is a cog'),
}
