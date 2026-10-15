"""Authored mutants for src/astryx/pg/schema_parity.py (a1 #38264), run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_schema_parity.py

Every destructive arm runs on the oracle's own fixture; the live arm only reads, in a read-only session.
NOT AUTHORED (equivalent): definitions()' internal-trigger exclusion. An internal trigger's OID-derived name never
appears on BOTH sides, and CHANGED compares only shared names, so including them changes nothing observable.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "pg" / "schema_parity.py"
ORACLE = REPO / "tests" / "test_schema_parity.py"
ENV = "SCHEMA_PARITY_SRC"
TIMEOUT = 300
MUTANTS = {
    "P1 a missing column isn't seen (a1's masked IF-NOT-EXISTS add reads green)":
        ('            if c not in live[t]:\n                missing.append(', '            if False:\n                missing.append('),
    "P2 a hand-added column isn't judged":
        ('                extra.append(f"column {name}.{c} ({live[t][c]})")', '                pass'),
    "P3 types aren't compared":
        ('            elif live[t][c] != typ:', '            elif False:'),
    "P4 a missing TABLE isn't seen":
        ('            missing.append(f"table {name}")\n', ''),
    "P6 the live session isn't read-only":
        ('    with psycopg.connect(live_dsn, autocommit=True) as c:\n        c.execute("SET default_transaction_read_only = on")\n',
         '    with psycopg.connect(live_dsn, autocommit=True) as c:\n'),     # run()'s live session (readable() sets its own)
    "P7 drift is reported but never fails (any difference reads green)":
        ('            "drift": bool(missing or extra or typed)}', '            "drift": False}'),
    "P8 a missing OBJECT isn't seen (a hand-dropped messages_notify silences the wire, parity green: a1 #38450)":
        ('    missing = sorted(f"{k} {n}" for k, names in expected.items() for n in names - live.get(k, set()))',
         '    missing = []'),
    "P9 object drift is computed but never fails the run":
        ('    out["drift"] = out["drift"] or o["drift"]', '    out["drift"] = out["drift"]'),
    "P10 internal (FK) triggers are judged (their OID-derived names differ per database: a false MISSING)":
        ('"trigger": "SELECT n.nspname || \'.\' || c.relname || \'.\' || t.tgname FROM pg_trigger t "\n'
         '                   "JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace "\n'
         '                   "WHERE NOT t.tgisinternal AND n.nspname <> ALL(%s)",',
         '"trigger": "SELECT n.nspname || \'.\' || c.relname || \'.\' || t.tgname FROM pg_trigger t "\n'
         '                   "JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace "\n'
         '                   "WHERE n.nspname <> ALL(%s)",'),
    "P11 a body replaced in place passes (CREATE OR REPLACE messages_notify, no notify, parity green: a1 #38541)":
        ("                  if n in live.get(k, {}) and live[k][n] != h)", "                  if False)"),
    "P12 CHANGED is computed but never fails the run":
        ('    out["drift"] = out["drift"] or o["drift"] or bool(out["objects_changed"])',
         '    out["drift"] = out["drift"] or o["drift"]'),
    # F1 (steward #42345): the scoped `geo` database
    "G1 a scoped database's live-only tables are only REPORTED (an ad-hoc table in `track` reads green)":
        ('    if spec.get("exclusive") and out["live_only"]:', '    if False and out["live_only"]:'),
    "G2 the scope is ignored (geo judged as the whole server's shape)":
        ('    if schemas is None:\n        return sh, ob, de', '    if True:\n        return sh, ob, de'),
    "G3 apply() skips the commit-first check (an uncommitted schema file reaches prod)":
        ('        if head.returncode != 0 or head.stdout != (REPO / f).read_text():', '        if False:'),
    "G5 an exclusive schema's hand-made objects stay REPORTED only (a4 #42525 R1: a hand trigger reads green)":
        ('    if spec.get("exclusive") and o["extra_reported"]:', '    if False and o["extra_reported"]:'),
    "G6 exclusivity inferred from having a scope (a future partitioned scoped DB would go red daily)":
        ('    "astryx": {"files": (), "schemas": None, "exclusive": False},', '    "astryx": {"files": (), "schemas": None, "exclusive": True},'),
    "G7 the birth path grants the resident nothing (a fresh geo breaks the ruling by construction)":
        ('    for ns in schemas or ():\n        conn.execute(sql.SQL("GRANT USAGE', '    for ns in ():\n        conn.execute(sql.SQL("GRANT USAGE'),
    "G8 birth grants the resident no CONNECT (a fresh geo is closed to every agent)":
        ('        admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(I(db), I(RESIDENT)))\n', ''),
    "G9 readable() is blind to a missing CONNECT (init's check reads green on a closed database)":
        ("        if not a.execute(\"SELECT has_database_privilege(%s, %s, 'CONNECT')\", (RESIDENT, db)).fetchone()[0]:",
         "        if False:"),
    "G10 readable() is blind to an unreadable table":
        ("                out.append(f\"{RESIDENT} can't SELECT {db}.{t}\")", "                pass"),
    "G11 grant_connect() grants nothing (an existing database never converges)":
        ('    admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db), sql.Identifier(RESIDENT)))\n    return True',
         '    return True'),
    "G4 the presence check's table parse goes blind (it would read green over nothing)":
        ('    if not got:                                   # anti-vacuity', '    if False:                                   # anti-vacuity'),
}
