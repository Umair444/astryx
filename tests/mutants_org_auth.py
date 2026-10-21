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
        ('    cli = env.get("ASTRYX_ORG_CLI") or "claude"',
         '    import os; env = {**env, **os.environ}; cli = env.get("ASTRYX_ORG_CLI") or "claude"'),
    "A2 the org key is spliced even when the entry sets its own base_url (the entry no longer wins)":
        ('    if not base_url:\n        login = org_login(env)', '    if True:\n        login = org_login(env)'),
    "A3 the org key is never spliced (every org on the ambient login)":
        ('        if login["key"]:\n            pairs.append', '        if False:\n            pairs.append'),
    "A4 the metered key is used WITHOUT the opt-in (an API key set for another reason moves agents to metered billing)":
        ('    if opt and opt in metered and env.get(opt):', '    if any(env.get(k) for k in metered):\n        opt = metered[0]\n    if opt and env.get(opt):'),
    "A8 an opt-in may name ANY key (not only a metered key claude reads)":
        ('    if opt and opt in metered and env.get(opt):', '    if opt and env.get(opt):'),
    "A9 a key set but not opted in goes unsaid (the owner never learns why it is ignored)":
        ('        if login["note"]:\n            print(', '        if False:\n            print('),
    "A10 the note carries the key's VALUE":
        ('        notes += [f"{k} is set but not opted in ({OPT_IN}={k}): ignored, so no metered billing" for k in metered',
         '        notes += [f"{k}={env[k]} is set but not opted in ({OPT_IN}={k}): ignored, so no metered billing" for k in metered'),
    "A11 `--org-words` exits 0 on metered billing (the doctor shows it as a plain check)":
        ('        sys.exit(3 if not d["supported"] else 1 if d["billing"] == "metered" else 0)',
         '        sys.exit(3 if not d["supported"] else 0)'),
    "A5 a CLI with no launcher runs as claude (no refusal)":
        ('LAUNCHERS = {"claude"}', 'LAUNCHERS = {"claude", "gemini"}'),
    "A6 `--org` prints the value with the name":
        ('        print(json.dumps(org_login()))',
         '        d = org_login(); e = config.read_env(paths.estate(__file__) / ".env"); print(json.dumps({**d, "v": e.get(d["key"] or "")}))'),
    "A7 the unsupported refusal exits 0 (spawn.sh reads it as nothing to add, and runs claude)":
        ('        print(f"runtime_env: {e}", file=sys.stderr)\n        sys.exit(3)',
         '        print(f"runtime_env: {e}", file=sys.stderr)\n        sys.exit(0)'),
}
