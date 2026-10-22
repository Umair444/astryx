"""Authored mutants for src/astryx/cogauth.py's host CLI (plan-11859 U1+U2: D7, D8, D9). Every one must be CAUGHT by
tests/test_cogauth_cli.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_cogauth_cli.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "cogauth.py"
ORACLE = REPO / "tests" / "test_cogauth_cli.py"
ENV = "COGAUTH_SRC"

MUTANTS = {
    "K1 a reset leaves the account's sessions live":
        ('        conn.execute("UPDATE sessions SET revoked = now() WHERE uid = %s AND revoked IS NULL", (row[0],))\n', ""),
    "K2 a second grant keeps the first role (no upsert)":
        ('ON CONFLICT (uid) DO UPDATE SET role = "\n                     "EXCLUDED.role"', 'ON CONFLICT (uid) DO NOTHING"'),
    "K3 a short password is accepted":
        ("    if len(pw) < 12:", "    if len(pw) < 1:"),
    "K4 restore-verify trusts any dump that restores (the count never compared)":
        ("    if got != have:", "    if False:"),
    "K5 a second init replaces the signing key (every token in flight dies, every backend must re-read)":
        ("    if (home / identity.PRIVATE).exists():", "    if False:"),
    "K6 a usage error repeats a password typed as an argument":
        ('        if message.startswith("unrecognized arguments"):', "        if False:"),
    "K7 restore-verify leaves its scratch database behind":
        ('        finally:\n            live.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch)))\n',
         "        finally:\n            pass\n"),
    "K8 revoke deletes nothing":
        ('    return org_conn.execute("DELETE FROM members WHERE uid = %s", (who,)).rowcount > 0',
         '    return org_conn.execute("SELECT 1 FROM members WHERE uid = %s", (who,)).rowcount > 0'),
    "K9 a cog without a block is managed anyway (no registry block, no refusal)":
        ("    c = orgs.cog(env)\n    if c is None:", "    c = orgs.cog(env) or {'id': 'fxcog-mutant1', 'home': Path('/nonexistent')}\n    if c is None:"),
}
