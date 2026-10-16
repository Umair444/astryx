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
        ('  rm -f "triggers/seed/.retired/$n"\n',
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
        ('        absent)    if _chk_"$_tnode" >/dev/null 2>&1; then ok "trigger $_tn: not used on this host"\n',
         '        absent)    if false; then ok "trigger $_tn: not used on this host"\n'),
}
