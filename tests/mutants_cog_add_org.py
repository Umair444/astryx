"""Authored mutants for devtools/cog_add_org.py (plan-11324 S3f S5), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_cog_add_org.py

NOT a mutant here, by design: the dry-run that CREATEs its database. Running it would make a non-fixture database from
a gate, the one thing this oracle never does; A1's "no database" arm is its teeth, and S6's rehearsal runs the CREATE.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "devtools/cog_add_org.py"
ORACLE = REPO / "tests" / "test_cog_add_org.py"
ENV = "COG_ADD_SRC"
TIMEOUT = 360

MUTANTS = {
    "G1 the dry-run makes the HOME and its .env":
        ("    if dry:\n        return\n    from nacl.encoding", "    from nacl.encoding"),
    "G2 the dry-run writes the registry":
        ("    if dry:\n        return\n    tmp = out", "    tmp = out"),
    "G3 the .env is world-readable (644: the org's key and DSN password for any local reader)":
        ("    os.chmod(envf, 0o600)\n", "    os.chmod(envf, 0o644)\n"),
    "G4 every org gets one constant key (two orgs, one identity)":
        ("SigningKey.generate().encode(HexEncoder).decode()", "\"ab\" * 32"),
    "G5 PUBLIC CONNECT is never revoked (any local role reaches the org's database)":
        ("        c.execute(sql.SQL(\"REVOKE CONNECT ON DATABASE {} FROM PUBLIC\")", "        (sql.SQL(\"REVOKE CONNECT ON DATABASE {} FROM PUBLIC\")"),
    "G6 the schema is never stamped (init.sh's chk_schema reads it as never applied)":
        ("        c.execute(\"INSERT INTO schema_applied", "        (\"INSERT INTO schema_applied"),
    "G7 the registry is never judged by the authority (a refused one becomes the registry)":
        ("        got = orgs.load({orgs.ENV: str(tmp)})     # RAISES", "        got = orgs.load({orgs.ENV: str(out)}) if out.exists() else {a.key: {\"primary\": False}} or orgs.load  # RAISES"),
    "G8 a HOME inside a git tree is accepted (a marker walk reaches the checkout's org)":
        ("    if g is not None:\n", "    if False:\n"),
    "G9 an existing database is not refused (CREATE over a live one, or a second org on it)":
        ("            if c.execute(\"SELECT 1 FROM pg_database WHERE datname = %s\", (db,)).fetchone():",
         "            if False:"),
    "G10 a non-empty HOME is accepted (another org's estate overwritten)":
        ("    if home.exists() and any(home.iterdir()):\n", "    if False:\n"),
    "G12 the merged registry is judged only at write time (a refused run leaves a HOME with a fresh key: a2 #60860)":
        ("            orgs.load({orgs.ENV: str(probe)})\n", "            pass\n"),
}
