"""Authored mutants for src/astryx/core/cli_adapters.py (plan-11859 U5): each launches a resident the table didn't
declare, unquoted, or deaf. Every one must be CAUGHT by tests/test_cli_adapters.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_cli_adapters.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "core" / "cli_adapters.py"
ORACLE = REPO / "tests" / "test_cli_adapters.py"
ENV = "CLI_ADAPTERS_SRC"

MUTANTS = {
    "C1 the line is interpolated, not quoted (a2 #62560: a charter's Model: with `;` or a space is shell-parsed)":
        ("    return shlex.join(argv)", '    return " ".join(argv)'),
    "C2 a launch with no wire channel is accepted at load (the doorbell dropped silently)":
        ('                raise AdapterError(f"cli adapters: {cli}\'s launch lacks {what}', '                pass  # (f"cli adapters: {cli}\'s launch lacks {what}'),
    "C3 a launch with no {mcp} slot is accepted":
        ('or "{mcp}" not in lt or', "or"),
    "C4 a CLI with no launcher launches anyway":
        ('    if r.get("launcher") is not True:\n        raise AdapterError(r["why"])\n', ""),
    "C5 resume is passed as one glued argument":
        ('"{resume}": ["--resume", resume] if resume else []', '"{resume}": [f"--resume {resume}"] if resume else []'),
    "C6 a non-launcher row needs no why":
        ('            if not r.get("why"):\n', "            if False:\n"),
    "C7 LAUNCHERS counts every row (gemini and codex launch)":
        ('    return {c for c, r in rows.items() if r.get("launcher") is True}', "    return set(rows)"),
}
