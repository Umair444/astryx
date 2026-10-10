"""Authored mutants for nucleus/social_age.py's declared-design check, run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_social_age_design.py

Each mutant blinds drift() or weakens ensure() in one way the oracle claims to see. They act only on the oracle's own
scratch databases, scratch roles and stamped fixtures (pid-scoped names), never a live one.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "social_age.py"
ORACLE = REPO / "tests" / "test_social_age_design.py"
ENV = "SOCIAL_AGE_SRC"
TIMEOUT = 400

MUTANTS = {
    "S1 a plain TABLE outside the graph is invisible ('r' dropped from the ad-hoc scan; a3 #42994)":
        ("\"WHERE c.relkind IN ('r','p','v','m','f') AND n.nspname NOT IN ('pg_catalog','information_schema',\"",
         "\"WHERE c.relkind IN ('p','v','m','f') AND n.nspname NOT IN ('pg_catalog','information_schema',\""),
    "S2 a plain TABLE inside the graph's schema is invisible ('r' dropped from the stray scan)":
        ("\"WHERE n.nspname = %s AND c.relkind IN ('r','p','v','m','f') AND c.oid NOT IN (\"",
         "\"WHERE n.nspname = %s AND c.relkind IN ('p','v','m','f') AND c.oid NOT IN (\""),
    "S3 ensure births a database OPEN (PUBLIC not revoked)":
        ('                a.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(I(db)))\n', ''),
    "S4 drift is blind to PUBLIC CONNECT":
        ('            if q("public", db):\n', '            if False:\n'),
    "S5 drift is blind to an undeclared CONNECT grantee (one-way ACL)":
        ('                if role not in want.get("connect", ()):\n', '                if False:\n'),
    "S6 the builder stops materializing labels (an empty graph misses its design)":
        ('    for lab in d["v"]:\n        cur.execute("SELECT create_vlabel(%s, %s)", (graph, lab))\n', ''),
}
