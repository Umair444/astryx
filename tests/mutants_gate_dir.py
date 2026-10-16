"""Authored mutants for devtools/check.sh's per-gate dir (plan-10108 D1, a1 BC-1, a3 BC-1 i), run by
devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_gate_dir.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools/check.sh"
ORACLE = REPO / "tests" / "test_gate_dir.py"
ENV = "CHECK_SH_SRC"
TIMEOUT = 300

MUTANTS = {
    "the gate dir inherits a long TMPDIR (a1 BC-1: the AF_UNIX socket passes 108 bytes)":
        ('if [ "${#GATE_ROOT}" -gt 40 ]; then', 'if false; then'),
    "the gate dir is never removed":
        ('  GATE_PGID=""\n  _gate_dir_rm\n', '  GATE_PGID=""\n'),
    "the gate is not handed its TMPDIR (it inherits the caller's)":
        ('ASTRYX_SQLGUARD_GATE="$label" TMPDIR="$GATE_DIR" ', 'ASTRYX_SQLGUARD_GATE="$label" '),
    "XDG_CACHE_HOME is not redirected (a3 BC-1 i)":
        ('XDG_CACHE_HOME="$GATE_DIR/cache" ', ''),
    "VITE_CACHE_DIR is not set (D2)":
        ('VITE_CACHE_DIR="$GATE_DIR/vite" ', ''),
    "an escaped descendant carrying TMPDIR=$G is not killed (it rewrites the removed dir)":
        ('grep -lasF -- "TMPDIR=$d" /proc/[0-9]*/environ; ', ''),
    "a descendant naming $G only in its argv (a chromium profile) is not killed":
        ('grep -lasE -- "$re" /proc/[0-9]*/cmdline; ', ''),
    "cleanup kills by the SHARED root, not the gate's own dir":
        ('grep -lasF -- "TMPDIR=$d" /proc/[0-9]*/environ', 'grep -lasF -- "TMPDIR=$GATE_ROOT" /proc/[0-9]*/environ'),
    "the root choice is logged at every gate, not once":
        ('GATE_ROOT_WHY"; GATE_ROOT_LOGGED=1; fi', 'GATE_ROOT_WHY"; fi'),
}
