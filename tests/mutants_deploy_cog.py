"""Authored mutants for scripts/deploy.sh in a cog (plan-11324 S3f S4, seed #60804/#60805), run by
devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_deploy_cog.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "scripts/deploy.sh"
ORACLE = REPO / "tests" / "test_deploy_cog.py"
ENV = "DEPLOY_SRC"
TIMEOUT = 360

MUTANTS = {
    "E1 a cog's unit is the bare stem (lab's verbs restart the primary's units)":
        ('un() { if [ -z "$COGH" ]; then echo "$1"; else', 'un() { if true; then echo "$1"; else'),
    "E2 api restarts the cog's front in a cog (the org's main.py never reloads)":
        ('  api)    if [ -z "$COGH" ]; then restart astryx-observatory; else restart "$(un astryx-observatory-org)"; fi ;;',
         '  api)    restart astryx-observatory ;;'),
    "E3 obs never restarts the front (it serves a stale dist, seed #60805)":
        ('build_web && restart "$(un astryx-observatory-org)" && front; fi ;;', 'build_web && restart "$(un astryx-observatory-org)"; fi ;;'),
    "E4 any org restarts the shared database (lab bounces the primary's postgres)":
        ('  if [ -n "${COGH:-}" ] && [ -z "${UPRIM:-}" ] && [ "$only" != residents ]; then', '  if false; then'),
    "E5 every unit is this org's (the primary's restart reaches lab's @<key> units)":
        ('  [ -z "$COGH" ] && return 0\n  case "$1" in', '  return 0\n  case "$1" in'),
    "E6 the front is restarted unverified (a dead front reads as done)":
        ('curl -sf -m 2 -o /dev/null localhost:8090/api/cog && {', 'true && {'),
    "E7 a cog-wide restart is silent (whoever runs it doesn't know every org felt it)":
        ('cogwide() { [ -n "$COGH" ] && echo "  · $1 restarted: affects every org in the cog"; return 0; }',
         'cogwide() { return 0; }'),
    "E8 units copies every org's files (lab installs the primary's)":
        ('"@" not in stem and stem not in cog if prim else stem.endswith("@" + key)', 'True'),
    "E9 the observatory probe is :8090 in a cog (the front's 409 reads as a down org)":
        ('  [ -n "${COGH:-}" ] && OBS="localhost:', '  false && OBS="localhost:'),
}
