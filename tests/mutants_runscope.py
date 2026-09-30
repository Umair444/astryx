"""Authored mutants for nucleus/runscope.py (plan-4918 R1), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_runscope.py

One per property the primitive rests on: ownership-derived teardown, the template clear, the (pid, starttime)
liveness key, and the refusal of a scope that isn't bound to its own directory.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "runscope.py"
ORACLE = REPO / "tests" / "test_runscope.py"
ENV = "RUNSCOPE_SRC"

MUTANTS = {
    "R1 teardown by NAME prefix, not ownership (a differently named db is missed)":
        ("    q = \"SELECT d.datname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba WHERE r.rolname = %s ORDER BY 1\"",
         "    q = \"SELECT d.datname FROM pg_database d WHERE d.datname LIKE %s || '%%' ORDER BY 1\""),
    "R2 no IS_TEMPLATE clear before DROP (a run-owned template survives)":
        ("                c.execute(sql.SQL(\"ALTER DATABASE {} IS_TEMPLATE false\").format(sql.Identifier(db)))\n", ""),
    "R3 liveness by pid alone (a reused pid reads alive)":
        ("    return st is not None and st == lock.get(\"starttime\")", "    return st is not None"),
    "R4 the role isn't bound to its directory (a crafted lock can name any role)":
        ("            and role == f\"{ROLE_PREFIX}{root.name}\".lower() and role.startswith(ROLE_PREFIX))",
         "            and role.startswith(ROLE_PREFIX))"),
    "R5 the root isn't bound to the base (any absolute path is removed)":
        ("    return (root.is_absolute() and root.resolve().parent == base.resolve()", "    return (root.is_absolute()"),
    "R7 create_db is born OPEN (a concurrent run role can connect in the gap and keep its session)":
        ("        q = sql.SQL(\"CREATE DATABASE {} OWNER {} ALLOW_CONNECTIONS false\").format(",
         "        q = sql.SQL(\"CREATE DATABASE {} OWNER {}\").format("),
    "R8 create_db never revokes PUBLIC CONNECT":
        ("            c.execute(sql.SQL(\"REVOKE CONNECT ON DATABASE {} FROM PUBLIC\").format(sql.Identifier(name)))\n", ""),
    "R6 the server gets the PLAINTEXT password, not a SCRAM verifier":
        ("sql.Identifier(self.role), sql.Literal(verifier.decode())))",
         "sql.Identifier(self.role), sql.Literal(self._password)))"),
    "R10 live() counts every scope, dead ones included (a stale scope would stop eviction forever)":
        ("            if alive(json.loads((d / \"lock.json\").read_text())):", "            if json.loads((d / \"lock.json\").read_text()):"),
}
