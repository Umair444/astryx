"""Authored mutants for nucleus/people_gate.py (the people library's access declaration, owner ruling 10-10), run by
nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_people_gate.py

One per property the declaration rests on: every resident READS the people library, PUBLIC never does, a re-apply
repairs drift (a stale column grant from the retired 1a split included), and the relation database is born zero-window.
Every mutant only NARROWS or WIDENS grants on the oracle's own scratch roles and scratch databases (names carry the
oracle's pid), so none can touch a live role or database (seed #34899).
NOT PROBED (named): a column-level REVOKE loop (an equivalent mutant: a table REVOKE already takes the role's column
privileges, measured 10-10); grant_network_db's preload line (masked when the network DB already has it); apply()'s ag_catalog
USAGE (the oracle drives the parts, not apply()).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "people_gate.py"
ORACLE = REPO / "tests" / "test_people_gate.py"
ENV = "PEOPLE_GATE_SRC"
TIMEOUT = 300

MUTANTS = {
    "O1 the resident is granted only the FIRST people table (social_relation stays unreadable)":
        ('    for t in ORG_TABLES:\n        conn.execute(sql.SQL("REVOKE ALL ON {} FROM PUBLIC")',
         '    for t in ORG_TABLES[:1]:\n        conn.execute(sql.SQL("REVOKE ALL ON {} FROM PUBLIC")'),
    "O2 PUBLIC is never revoked (a planted PUBLIC grant survives the re-apply)":
        ('        conn.execute(sql.SQL("REVOKE ALL ON {} FROM PUBLIC").format(I(t)))\n', ''),
    "O4 the relation database never grants the resident CONNECT":
        ('                                        ([resident, cleared],)).fetchall()]',
         '                                        ([cleared],)).fetchall()]'),
    "O5 the relation database is born OPEN (connectable while PUBLIC still holds CONNECT)":
        ('admin.execute(sql.SQL("CREATE DATABASE {} ALLOW_CONNECTIONS false").format(I(name)))',
         'admin.execute(sql.SQL("CREATE DATABASE {}").format(I(name)))'),
    "O6 drift is blind to PUBLIC on a people table":
        ('''        if q("SELECT has_table_privilege('public', %s, 'SELECT')", t):''',
         '''        if False and q("SELECT has_table_privilege('public', %s, 'SELECT')", t):'''),
    "O7 drift is blind to a resident who can't read a table":
        ("            if not q(\"SELECT has_table_privilege(%s, %s, 'SELECT')\", r, t):",
         "            if False and not q(\"SELECT has_table_privilege(%s, %s, 'SELECT')\", r, t):"),
    "O8 graph grants never happen (drop_graph's lost ACL isn't restored)":
        ('    for r in roles:\n        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA ag_catalog',
         '    for r in ():\n        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA ag_catalog'),
    "O9 production's resident is born LOGIN (still inert until 1b)":
        ('def ensure_roles(admin, resident: str = RESIDENT, cleared: str = CLEARED, login: bool = False)',
         'def ensure_roles(admin, resident: str = RESIDENT, cleared: str = CLEARED, login: bool = True)'),
    "O10 no AGE preload on the relation database (a non-superuser can't use the graph)":
        ('    admin.execute(sql.SQL("ALTER DATABASE {} SET session_preload_libraries = \'age\'").format(I(name)))\n'
         '    # Always:',
         '    # Always:'),
}
