"""Authored mutants for src/astryx/core/toolreg.py's one-id-across-the-move folds, as econ reads them (goal 11324 S1
transition arm, a1) — run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_econ_core_domain_toolreg.py

A pre-bump row (script:nucleus/x, LEDGER_V 1) and a post-bump row (script:<moved>/x, LEDGER_V 2) must be one id
with one author. Each mutant drops one fold, so history splits into two tools or loses its author.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "core" / "toolreg.py"
ORACLE = REPO / "tests" / "test_econ_core_domain.py"
ENV = "TOOLREG_SRC"

MUTANTS = {
    "R1 canonical() is the identity: a pre-move call is a second tool":
        ('        return "script:" + _MOVED.get(p, p)\n    return rid', '        return rid\n    return rid'),
    "R2 authorship doesn't fold a pre-move Write onto where the tool lives now":
        ("        path = _MOVED.get(path, path)          # a write before the reorg", "        pass  # a write before the reorg"),
    "R3 source_path doesn't canonicalize: a pre-move id finds no author":
        ('    """The file whose authorship a registry id inherits. An MCP tool inherits its server\'s."""\n    rid = canonical(rid)\n',
         '    """The file whose authorship a registry id inherits. An MCP tool inherits its server\'s."""\n'),
    "R4 CORE_SERVERS loses the door":
        ('CORE_SERVERS = ("astryx", "tools")', 'CORE_SERVERS = ("astryx",)'),
}
