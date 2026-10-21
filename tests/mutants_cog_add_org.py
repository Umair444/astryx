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
    "T1 the reconcile installs over an installed name (a duplicated actuator: two run_backups)":
        ('        if all(s == "absent" for s, _ in st.values()):', '        if True:'),
    "T2 a shim stands down only when ALL its names are owned (an org's own run_backup gets a second one)":
        ('        if all(s == "absent" for s, _ in st.values()):', '        if any(s == "absent" for s, _ in st.values()):'),
    "T3 each shim is written as it is judged (a blind shim written first defers every later answer)":
        ('            plan_.append((shim, "install", "every name it registers is absent"))\n',
         '            plan_.append((shim, "install", "every name it registers is absent"))\n'
         '            if not dry:\n                tdir.mkdir(parents=True, exist_ok=True)\n                shims.write(shim, tdir)\n'),
    "T4 the state child inherits ASTRYX_* (the primary's DSN asks the primary's triggers table about the org)":
        ('    env = {k: v for k, v in os.environ.items() if not k.startswith("ASTRYX_")}\n', '    env = dict(os.environ)\n'),
    "T5 windows_idle_stop is installed where no Windows container is":
        ('    if shim != "windows_idle_stop":\n        return True\n', '    return True\n'),
    "T6 a new org gets no backup trigger":
        ('COG_SHIMS = ("context_compact", "pr_review", "windows_idle_stop", "agent_heal", "org_backup")',
         'COG_SHIMS = ("context_compact", "pr_review", "windows_idle_stop", "agent_heal")'),
    "T7 the reconcile serves the primary (whose checkout ./init.sh reconciles)":
        ('    if e["primary"]:\n', '    if False:\n'),
    "T8 a dry-run reconcile writes":
        ('        if act == "install" and not dry:\n', '        if act == "install":\n'),
    "T9 a federation name another org holds is accepted (two orgs, one address: 10224 NAMES)":
        ("    if clash:\n", "    if False:\n"),
    "T10 a malformed federation name is accepted":
        ("    if not orgname.org_ok(a.name):\n", "    if False:\n"),
}
