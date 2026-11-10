"""Authored mutants for observatory/api/main.py's org login (plan-11859 U4): each writes a login the owner didn't
choose, keeps an opt-in he withdrew, or hands a value back. Every one must be CAUGHT by tests/test_org_login.py.
(Not here: dropping the handler's own owner check. The default-deny middleware refuses the route first, since it is
not in PUBLIC, so that mutant is masked by structure, and the 403 arm holds either way.)

    venv/bin/python devtools/mutation_probe.py tests/mutants_org_login.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "observatory" / "api" / "main.py"
ORACLE = REPO / "tests" / "test_org_login.py"
ENV = "OBS_MAIN_SRC"

MUTANTS = {
    "U1 a metered key with no billing confirmed (spend the owner never signed: local.md's one HIL gate)":
        ('    if body.choice == "metered" and not body.confirm_billing:', "    if False:"),
    "U2 a subscription keeps an earlier opt-in (a present API key flips the org to metered later)":
        ("        config.unset_env(runtime_env.OPT_IN, ENV_FILE)          # a subscription", "        pass  # a subscription"),
    "U3 a held token is replaced without asking":
        ("    if config.is_set(key, ENV_FILE) and not body.replace:\n        return JSONResponse({\"ok\": False, \"needs_confirm\": True,\n                             \"error\": f\"This org",
         "    if False:\n        return JSONResponse({\"ok\": False, \"needs_confirm\": True,\n                             \"error\": f\"This org"),
    "U4 any text is accepted as a token (no shape)":
        ("    if not _LOGIN_SHAPE[body.choice].fullmatch(token):", "    if False:"),
    "U5 a pasted line break is kept in the token":
        ('    token = "".join(body.token.split())', "    token = body.token.strip()"),
    "U6 ambient leaves the opt-in behind":
        ("    for k in (*row[\"subscription\"], *row[\"metered\"], runtime_env.OPT_IN):",
         "    for k in (*row[\"subscription\"], *row[\"metered\"]):"),
    "U7 the answer carries the token's value":
        ('billing confirmed\n    return {"ok": True, "login": _org_login_view(),',
         'billing confirmed\n    return {"ok": True, "token": body.token, "login": _org_login_view(),'),
    "U9 the shape checks a token's START only (a2 #62549 F-1: whatever follows a good prefix reaches the .env)":
        ("    if not _LOGIN_SHAPE[body.choice].fullmatch(token):", "    if not _LOGIN_SHAPE[body.choice].match(token):"),
    "U8 an org whose CLI has no launcher is written anyway (as claude)":
        ("    if cli not in runtime_env.LAUNCHERS:", "    cli = 'claude'\n    if cli not in runtime_env.LAUNCHERS:"),
}
