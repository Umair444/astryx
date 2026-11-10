"""Authored mutants for devtools/org_apply.py (plan-12214, a2 msg 65118 R-1). venv/bin/python devtools/mutation_probe.py tests/mutants_org_apply.py"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "org_apply.py"
ORACLE = REPO / "tests" / "test_trigger_tool.py"
ENV = "ORG_APPLY_SRC"
TIMEOUT = 400

MUTANTS = {
    "a failed git show counts as committed (the fail-open R-1 found)":
        ("return got.returncode == 0 and got.stdout == SCHEMA.read_bytes()",
         "return got.returncode != 0 or got.stdout == SCHEMA.read_bytes()"),
    "a hook's GIT_DIR reaches the git show":
        ('env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})', "env=dict(os.environ))"),
    "the commit-first refusal is gone":
        ('    if mode == "--all" and not _committed():', '    if False:'),
    "main reads the registry's map through a key it doesn't have":
        ("    return _fan_out(reg, one)", '    return _fan_out(reg["orgs"], one)'),
}
