"""Authored mutants for init.sh's cog-safe doctor (plan-11324 S3f S7; S7b, goal 10224), run by devtools/mutation_probe.py.

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
        ('    [ -n "${DOCTOR_COG:-}" ] && disk_list=$(echo "$disk_list" | _mine)', '    :'),
    "M2 only @ files are filtered (the cog's gateway and front read as the primary's orphans)":
        ('grep -v \'@\' | grep -vE "^(${_cogstems:-^$})\\."', "grep -v '@'"),
    "M3 doctor's tmux is bare (an inherited $TMUX's server answers for the primary's seats)":
        ('if [ -n "${DOCTOR_COG:-}" ]; then ROOT="$PWD"; . scripts/org_tmux.sh; fi', ':'),
    "M4 the primary runs from any checkout (its estate read from a tree that isn't its HOME)":
        ('    [ "$_dorg" != "$_dprim" ] || [ "$_dhome" = "$(pwd -P)" ] || {', '    true || {'),
    "M5 ASTRYX_HOME is not carried (by the marker, doctor's units() renders the COG's set as the primary's)":
        ('    export ASTRYX_HOME="$_dhome"; DOCTOR_COG=1', '    DOCTOR_COG=1'),
    "M6 the filter applies on one org too (an @-named stray is no longer anyone's orphan): _mine's one-org branch":
        ('  _mine() { if [ -z "${DOCTOR_COG:-}" ]; then cat', '  _mine() { if false; then cat'),
    "M7 another org's estate root is this checkout (S7b's reads all land on the primary's)":
        ('{ DOCTOR_ORG="$_dorg"; DOCTOR_ORGH="$_dhome"; }', '{ DOCTOR_ORG="$_dorg"; }'),
    "M8 .env read from the checkout":
        ('  if [ -f "$ORGH/.env" ]; then', '  if [ -f .env ]; then'),
    "M9 local.md read from the checkout":
        ('  [ -f "$ORGH/local.md" ] && ok', '  [ -f local.md ] && ok'),
    "M10 backups/ read from the checkout":
        ('ls -1t "$ORGH"/backups/astryx-*.dump', 'ls -1t backups/astryx-*.dump'),
    "M11 the restore-verify stamp read from the checkout":
        ('  if [ -f "$ORGH/backups/.last-restore-ok" ]; then', '  if [ -f backups/.last-restore-ok ]; then'),
    "M12 the routes read from the checkout":
        ('  for rf in "$ORGH"/bridges/routes-*.json; do', '  for rf in bridges/routes-*.json; do'),
    "M13 the dep groups derived from the checkout's channels":
        ('    DGROUPS=$(active_dep_groups "$ORGH")', '    DGROUPS=$(active_dep_groups)'),
    "M14 the docker host address read from the checkout's .env":
        ('  _dhip=$(_docker_host_ip "$ORGH/.env")', '  _dhip=$(_docker_host_ip)'),
    "M15 (iii) undeclared is unscoped (the 10-20 live false RED: another org's and the cog's units are the primary's)":
        ("awk '{print $1}' | _mine); do", "awk '{print $1}'); do"),
    "M16 another org's units are every file (the primary's and the cog's read as its own)":
        ('            else grep -F "@$DOCTOR_ORG."; fi; }', '            else cat; fi; }'),
    "M17 another org's remedy is ./init.sh (which serves only the primary's checkout)":
        ('  _fix="./init.sh"; [ -n "${DOCTOR_ORGH:-}" ] && _fix=', '  _fix="./init.sh"; false && _fix='),
    "M18 another org's backup remedy is the one-org line (./scripts/backup.sh in the checkout, a retired timer)":
        ('    if [ -n "${DOCTOR_ORGH:-}" ]; then\n      bad "NO database backup', '    if false; then\n      bad "NO database backup'),
    "M19 a unit's content is never compared (a stale body under a matching name reads \"no drift\": UDRIFT)":
        ('      cmp -s "$GEN/$u" "units/$u" 2>/dev/null || stale="$stale $u"', '      true'),
    "M20 the ✓ no-drift line ignores a stale body":
        ('      [ -z "$stale" ] && ok "units/ ≡ generated set', '      ok "units/ ≡ generated set'),
    "M21 another org's stale-content remedy renders the PRIMARY's units (no ASTRYX_HOME)":
        ('${DOCTOR_ORGH:+ASTRYX_HOME=$ORGH }./init.sh units, then', './init.sh units, then'),
    "M22 a shared federation name reads green (doctor never asks: 10224 NAMES)":
        ('      1) bad "orgs of this cog SHARE a federation name', '      9) bad "orgs of this cog SHARE a federation name'),
    "M23 a .env line skipped as not UTF-8 goes unsaid (doctor swallows read_env's word: 10224 ENVREAD)":
        ('         [ -n "$_dnw" ] && { warn', '         [ -z "$_dnw" ] && { warn'),
    "M23o metered billing reads as a plain check (the doctor never says per-token billing: 10224 ORGAUTH)":
        ('    1) warn "$(printf \'%s\\n\' "$_ol" | head -1): every agent', '    1) ok "$(printf \'%s\\n\' "$_ol" | head -1): every agent'),
    "M24 any stderr from orgs.py reads as a skipped .env line (the ⚠'s label lies: a2 #61867 A-1)":
        ("""         _dnw=$(printf '%s\\n' "$_dn" | sed -n 's/^config\\.read_env: /        /p')""",
         """         _dnw=$(printf '%s\\n' "$_dn" | sed 's/^/        /')"""),
}
