"""Authored mutants for nucleus/people_gate.py (people library 1a), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_people_gate.py

One per property the gate rests on. Every mutant here only NARROWS or WIDENS grants on the oracle's own scratch roles
and scratch databases (names carry the oracle's pid), so none can touch a live role or database (seed #34899).
NOT PROBED (named): grant_network_db's preload line; dropping it is masked when the network DB already has it.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "people_gate.py"
ORACLE = REPO / "tests" / "test_people_gate.py"
ENV = "PEOPLE_GATE_SRC"
TIMEOUT = 300

MUTANTS = {
    "G1 the resident gets TABLE-level SELECT on social_person (every detail column readable)":
        ('    conn.execute(sql.SQL("GRANT SELECT ({}) ON social_person TO {}")\n'
         '                 .format(sql.SQL(", ").join(map(I, NETWORK_COLS)), I(resident)))',
         '    conn.execute(sql.SQL("GRANT SELECT ON social_person TO {}").format(I(resident)))'),
    "G2 social_relation is granted to PUBLIC, not revoked from it":
        ('conn.execute(sql.SQL("REVOKE ALL ON {} FROM PUBLIC").format(I(DETAIL_TABLE)))',
         'conn.execute(sql.SQL("GRANT SELECT ON {} TO PUBLIC").format(I(DETAIL_TABLE)))'),
    "G3 the private database keeps PUBLIC CONNECT":
        ('    admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(I(name)))\n'
         '    admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(I(name), I(cleared)))',
         '    admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(I(name), I(cleared)))'),
    "G4 people_cleared never gets SELECT on social_relation":
        ('    conn.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(I(DETAIL_TABLE), I(cleared)))\n', ''),
    "G5 a detail column is in the network set":
        ('NETWORK_COLS = ("org", "id", "kind", "label", "direct", "seen_at")',
         'NETWORK_COLS = ("org", "id", "kind", "label", "direct", "seen_at", "relation")'),
    "G6 the private database is born OPEN (connectable while PUBLIC still holds CONNECT)":
        ('admin.execute(sql.SQL("CREATE DATABASE {} ALLOW_CONNECTIONS false").format(I(name)))',
         'admin.execute(sql.SQL("CREATE DATABASE {}").format(I(name)))'),
    "G7 no AGE preload on the private database (a non-superuser member can't use the graph)":
        ('    admin.execute(sql.SQL("ALTER DATABASE {} SET session_preload_libraries = \'age\'").format(I(name)))\n'
         '    # Always:',
         '    # Always:'),
    "G8 graph grants never happen (drop_graph's lost ACL isn't restored)":
        ('    for r in roles:\n        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA ag_catalog',
         '    for r in ():\n        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA ag_catalog'),
    "G9 production's resident is born LOGIN (1a is no longer inert)":
        ('def ensure_roles(admin, resident: str = RESIDENT, cleared: str = CLEARED, login: bool = False)',
         'def ensure_roles(admin, resident: str = RESIDENT, cleared: str = CLEARED, login: bool = True)'),
    "G10 drift is blind to a detail column the resident can read":
        ('    if leak:\n        out.append(', '    if False:\n        out.append('),
    "G11 drift is blind to PUBLIC on social_relation":
        ('''    if q("SELECT has_table_privilege('public', %s, 'SELECT')", DETAIL_TABLE):''',
         '''    if False and q("SELECT has_table_privilege('public', %s, 'SELECT')", DETAIL_TABLE):'''),
    "G12 a stale resident grant on social_relation survives a re-apply":
        ('    conn.execute(sql.SQL("REVOKE ALL ON {} FROM {}").format(I(DETAIL_TABLE), I(resident)))   # a stale grant\n',
         ''),
}
