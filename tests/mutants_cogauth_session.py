"""Authored mutants for src/astryx/cogauth.py's session half (plan-11859 U1+U2, D7; F8, I9), as the cog's front runs
it. Every one must be CAUGHT by tests/test_cog_signin.py (its COGAUTH_SRC seam reaches the front's import too).

    venv/bin/python devtools/mutation_probe.py tests/mutants_cogauth_session.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "cogauth.py"
ORACLE = REPO / "tests" / "test_cog_signin.py"
ENV = "COGAUTH_SRC"

MUTANTS = {
    "C1 an unknown email pays no password check (its latency says the account doesn't exist)":
        ("    ok = await check(check_password, pw, row[1] if row else dummy())",
         "    ok = bool(row) and await check(check_password, pw, row[1])"),
    "C2 a wrong password signs in":
        ("    if not (row and ok):", "    if not row:"),
    "C3 a revoked session still signs in (sign-out and reset revoke nothing)":
        ('"WHERE s.digest = %s AND s.revoked IS NULL AND s.expires > now()"', '"WHERE s.digest = %s AND s.expires > now()"'),
    "C4 an expired session still signs in":
        ('"WHERE s.digest = %s AND s.revoked IS NULL AND s.expires > now()"', '"WHERE s.digest = %s AND s.revoked IS NULL"'),
    "C5 the sign-in email is not normalised (an account added as Owner@ can't sign in as owner@)":
        ("    row = await run(_account, norm_email(email))", "    row = await run(_account, email)"),
}
