"""Authored mutants for runtime_env's org login (plan-10224 ORGAUTH), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_auth.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "src" / "astryx" / "core" / "runtime_env.py"
ORACLE = REPO / "tests" / "test_org_auth.py"
ENV = "ORGAUTH_SRC"
TIMEOUT = 300

MUTANTS = {
    "A1 the org key is read from the PROCESS env (the parent's, another org's)":
        ('    key = next((k for k in CLIS.get(cli, ()) if env.get(k)), None)',
         '    import os; env = {**env, **os.environ}; key = next((k for k in CLIS.get(cli, ()) if env.get(k)), None)'),
    "A2 the org key is spliced even when the entry sets its own base_url (the entry no longer wins)":
        ('    if not base_url:\n        login = org_login(env)', '    if True:\n        login = org_login(env)'),
    "A3 the org key is never spliced (every org on the ambient login)":
        ('        if login["key"]:\n            pairs.append', '        if False:\n            pairs.append'),
    "A4 the API key is preferred over the OAuth token":
        ('CLIS = {"claude": ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")}',
         'CLIS = {"claude": ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")}'),
    "A5 a CLI with no launcher runs as claude (no refusal)":
        ('LAUNCHERS = {"claude"}', 'LAUNCHERS = {"claude", "gemini"}'),
    "A6 `--org` prints the value with the name":
        ('        print(json.dumps(org_login()))',
         '        d = org_login(); e = config.read_env(paths.estate(__file__) / ".env"); print(json.dumps({**d, "v": e.get(d["key"] or "")}))'),
    "A7 the unsupported refusal exits 0 (spawn.sh reads it as nothing to add, and runs claude)":
        ('        print(f"runtime_env: {e}", file=sys.stderr)\n        sys.exit(3)',
         '        print(f"runtime_env: {e}", file=sys.stderr)\n        sys.exit(0)'),
}
