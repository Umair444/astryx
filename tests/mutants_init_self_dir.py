"""Mutants for init.sh's start directory (tests/test_init_self_dir.py). Hermetic.

    venv/bin/python devtools/mutation_probe.py tests/mutants_init_self_dir.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "init.sh"
ORACLE = REPO / "tests" / "test_init_self_dir.py"
ENV = "INIT_SELF_SRC"
MUTANTS = {
    "D1 links aren't followed (the PATH link lands in ~/.local/bin: a2 #39198)":
        ('while [ -L "$_self" ]; do', 'while false; do'),
    "D2 a relative link target is taken relative to the CWD, not to its link's directory":
        ('*) _self="$(dirname "$_self")/$_t" ;;', '*) _self="$_t" ;;'),
    "D3 only ONE link is followed (a chain stops halfway)":
        ('  case "$_t" in /*) _self="$_t" ;; *) _self="$(dirname "$_self")/$_t" ;; esac\ndone',
         '  case "$_t" in /*) _self="$_t" ;; *) _self="$(dirname "$_self")/$_t" ;; esac; break\ndone'),
    "D4 the old start directory comes back after the block (a later cd undoes the resolution)":
        ('unset _self _t _hops\n# <<< self dir', 'unset _self _t _hops\n# <<< self dir\ncd "$(dirname "$0")"'),
    "D5 no hop cap (a link cycle hangs init.sh's first act forever, silently: a2 #39682)":
        ('  [ "$_hops" -le 40 ] || { echo "init.sh: link loop at $0" >&2; exit 1; }\n', ''),
}
