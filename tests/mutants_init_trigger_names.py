"""Authored mutants for init.sh's trigger installs (plan-9853 D3/D4), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_init_trigger_names.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_init_trigger_names.py"
ENV = "INIT_TRIGGERS_SRC"
TIMEOUT = 900

MUTANTS = {
    "back to the filename glob (the goal's defect: an owner's copy under another name gets a duplicate)":
        ("_chk_ccompact() { _trigger_chk context_compact; }",
         "_chk_ccompact() { ls triggers/*/context_compact.py >/dev/null 2>&1; }"),
    "an unreadable or deferred answer installs (only installed/retired stand it down)":
        ('  [ "$s" != absent ]\n}',
         '  [ "$s" = installed ] || [ "$s" = retired ]\n}'),
    "--reinstall keeps seed's tombstone (a3 BC-2)":
        ('  for e in "${TRIGGER_NODES[@]}"; do [ "${e##*|}" = "$node" ] && rm -f "triggers/seed/.retired/${e%%|*}"; done\n',
         ''),
    "--reinstall doesn't override a deferral (the owner's exit is a no-op)":
        ('  [ "${_REINSTALL:-}" = "$1" ] && [ "$s" = deferred ] && return 1     # the owner chose: install it\n',
         ''),
    "--reinstall accepts any name":
        ('  [ -n "$node" ] || die "--reinstall:',
         '  [ -n "$node" ] || return 0; : "--reinstall:'),
    "doctor is silent about a deferred name":
        ('        deferred)  warn "trigger $_tn DEFERRED, so init.sh won\'t install it: ${_ts#deferred }" ;;\n',
         '        deferred)  : ;;\n'),
    "doctor calls an absent name with its gate off a failure":
        ('        absent)    if _chk_"$_tnode" >/dev/null 2>&1; then\n',
         '        absent)    if false; then\n'),
    "a sibling-owned absent name reads green \"not used on this host\" (a2 #61535 A-1: a detector's wrong direction)":
        ('                     if _ts2=$(_trigger_sibling "$_tn" "$_tnode"); then', '                     if false; then'),
    "the pair's reinstall clears only the named tombstone (the sibling's keeps the pair retired: two reinstalls)":
        ('  for e in "${TRIGGER_NODES[@]}"; do [ "${e##*|}" = "$node" ] && rm -f "triggers/seed/.retired/${e%%|*}"; done',
         '  rm -f "triggers/seed/.retired/$n"'),
    "an INSTALLED sibling is told to --reinstall (which would register a second copy of it)":
        ('                         installed*) warn', '                         installedX*) warn'),
}
