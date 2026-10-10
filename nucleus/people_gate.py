#!/usr/bin/env python3
"""astryx · people_gate — the people library's ACCESS declaration: every resident reads it all (owner ruling 10-10).

THE RULING (owner 10-10, via seed #42309/#42323/#42347, verbatim: "database entities should be public to all agents
working inside astryx"). The 1a SPLIT this module used to enforce (network structure for residents, relation DETAILS
for `people_cleared` only, a private AGE database only cleared could CONNECT to) is RETIRED: inside the org there is one
shared memory, and a role built to keep agents out of org data is against the ruling. So `astryx_resident` now holds
table-level SELECT on social_person, social_edge and social_relation, and CONNECT on astryx_people; `people_cleared`
keeps the same grants (a charter that holds it loses nothing).

WHO "ALL AGENTS" IS, stated (steward #42345, seed #42389): the RESIDENT role, never postgres PUBLIC. PUBLIC is every
role on the server, branch_check's sandboxed run roles included, and P0-b requires those never to reach prod data. So
PUBLIC is still REVOKEd on these tables and on astryx_people, and drift() reports any PUBLIC grant.

WHAT STILL STANDS, from local.md, not from here: the human-personal tier stays off the WIRE and out of public artifacts,
and tier.py's PERSONAL_LANES keeps lane rows out of memory's RAG-built artifacts until the owner edits that line.

INERT AS SHIPPED, unchanged: `astryx_resident` is NOLOGIN, and residents connect as the superuser in ASTRYX_DSN, which
reads everything regardless. These grants DECLARE the design, so the day residents switch roles (1b) nothing narrows.

Names are parameters so the oracle (tests/test_people_gate.py) runs this exact code on scratch roles and scratch
databases; production passes none.

    venv/bin/python -m nucleus.people_gate check    # exit 0 green, 1 red (drift printed)
    venv/bin/python -m nucleus.people_gate apply    # idempotent; init.sh's peoplegate node
"""
from __future__ import annotations

import sys
from pathlib import Path

from psycopg import sql

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RESIDENT = "astryx_resident"
CLEARED = "people_cleared"
PRIVATE_DB = "astryx_people"          # the relation-details AGE projection (the name is historical; every resident reads it)
NETWORK_DB = "astryx_social"          # the network graph (nucleus/social_age.py)
DETAIL_TABLE = "social_relation"
# Every org table of the people library: whole-table SELECT for the resident and the cleared role, nothing for PUBLIC.
# Table-level on purpose: a column added later is readable by every resident at once (the ruling's polarity).
ORG_TABLES = ("social_person", "social_edge", DETAIL_TABLE)

ROLE_SQL = "SELECT rolcanlogin FROM pg_roles WHERE rolname = %s"
DB_SQL = "SELECT 1 FROM pg_database WHERE datname = %s"
AGE_SQL = "SELECT 1 FROM pg_available_extensions WHERE name = 'age'"


def _role(admin, name: str, login: bool) -> None:
    """Create if absent; never ALTER an existing role (the owner may have changed it on purpose)."""
    if admin.execute(ROLE_SQL, (name,)).fetchone() is None:
        admin.execute(sql.SQL("CREATE ROLE {} " + ("LOGIN" if login else "NOLOGIN")
                              + " NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
                      .format(sql.Identifier(name)))


def ensure_roles(admin, resident: str = RESIDENT, cleared: str = CLEARED, login: bool = False) -> None:
    """`login` is the oracle's: its scratch resident must connect. Production's resident is NOLOGIN (1a: inert)."""
    _role(admin, resident, login)
    _role(admin, cleared, False)


def grant_main(conn, resident: str = RESIDENT, cleared: str = CLEARED) -> None:
    """In the org's own database (conn is connected to it, as its owner or a superuser). Idempotent. REVOKE first, so a
    stale grant from the retired split (or a PUBLIC grant) can't survive a re-apply; then the table grant."""
    I = sql.Identifier
    db = conn.execute("SELECT current_database()").fetchone()[0]
    for t in ORG_TABLES:
        conn.execute(sql.SQL("REVOKE ALL ON {} FROM PUBLIC").format(I(t)))
        for r in (resident, cleared):
            # a table-level REVOKE also revokes that role's COLUMN privileges on every column (postgres REVOKE), so
            # the retired split's column grants go with it (the oracle's stale-grant arm; a column loop here was dead)
            conn.execute(sql.SQL("REVOKE ALL ON {} FROM {}").format(I(t), I(r)))
            conn.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(I(t), I(r)))
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(I(db), I(resident), I(cleared)))


def ensure_private_db(admin, name: str = PRIVATE_DB, cleared: str = CLEARED, resident: str = RESIDENT) -> bool:
    """The relation projection's database, BORN ZERO-WINDOW (plan-4918 #28982): created with connections disallowed,
    PUBLIC revoked, CONNECT granted to the resident and the cleared role, THEN opened. Returns True if created now."""
    I = sql.Identifier
    made = admin.execute(DB_SQL, (name,)).fetchone() is None
    if made:
        admin.execute(sql.SQL("CREATE DATABASE {} ALLOW_CONNECTIONS false").format(I(name)))
    admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(I(name)))
    have = [r for (r,) in admin.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                                        ([resident, cleared],)).fetchall()]
    if have:
        admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(I(name), sql.SQL(", ").join(map(I, have))))
    # A non-superuser can't LOAD 'age' (agelib), and a GROUP role's settings don't reach its members, so the
    # preload is set on the DATABASE.
    admin.execute(sql.SQL("ALTER DATABASE {} SET session_preload_libraries = 'age'").format(I(name)))
    # Always: a run killed between CREATE and here left it closed, and only now is its ACL known to be right.
    admin.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(I(name)))
    return made


def grant_network_db(admin, name: str = NETWORK_DB, resident: str = RESIDENT, cleared: str = CLEARED) -> bool:
    """The all-agent network graph: CONNECT for the resident and the cleared (cleared ⊇ network). False if absent."""
    I = sql.Identifier
    if admin.execute(DB_SQL, (name,)).fetchone() is None:
        return False
    admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(I(name), I(resident), I(cleared)))
    admin.execute(sql.SQL("ALTER DATABASE {} SET session_preload_libraries = 'age'").format(I(name)))
    return True


def grant_graph(cur, graph: str, *roles: str) -> None:
    """Read access to one AGE graph, re-granted after every rebuild (drop_graph drops the schema and its ACL)."""
    I = sql.Identifier
    for r in roles:
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA ag_catalog TO {}").format(I(r)))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(I(graph), I(r)))
        cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(I(graph), I(r)))


# ── the check: one predicate list, read from the server, shared by init.sh's node and the oracle ─────────────
def drift(conn, admin=None, resident: str = RESIDENT, cleared: str = CLEARED,
          private_db: str = PRIVATE_DB) -> list:
    """What is NOT as this module declares, as sentences. Empty = green. `conn` is the org database; `admin` (any
    connection to the cluster, defaults to conn) reads the cluster-wide database ACLs."""
    admin = admin or conn
    out = []
    for r in (resident, cleared):
        if conn.execute(ROLE_SQL, (r,)).fetchone() is None:
            return [f"role {r} is missing"]
    if conn.execute("SELECT to_regclass(%s)", (DETAIL_TABLE,)).fetchone()[0] is None:
        return [f"table {DETAIL_TABLE} is missing (schema.sql not applied)"]
    q = lambda s, *a: conn.execute(s, a).fetchone()[0]      # noqa: E731
    for t in ORG_TABLES:
        if q("SELECT has_table_privilege('public', %s, 'SELECT')", t):
            out.append(f"PUBLIC can SELECT {t} (all agents = the resident role, never PUBLIC)")
        for r in (resident, cleared):
            if not q("SELECT has_table_privilege(%s, %s, 'SELECT')", r, t):
                out.append(f"{r} can't SELECT {t} (the ruling: every resident reads org data)")
    if admin.execute(DB_SQL, (private_db,)).fetchone() is None:
        out.append(f"database {private_db} is missing")
    else:
        for who, want in (("public", False), (resident, True), (cleared, True)):
            if admin.execute("SELECT has_database_privilege(%s, %s, 'CONNECT')",
                             (who, private_db)).fetchone()[0] != want:
                out.append(f"{who} {'can' if not want else 'can not'} CONNECT to {private_db}")
    return out


def apply(admin_dsn: str) -> list:
    """The reconciler's act, as the DSN's (superuser) role. Returns the drift left afterwards."""
    import psycopg
    with psycopg.connect(admin_dsn, autocommit=True) as c:
        ensure_roles(c)
        grant_main(c)
        ensure_private_db(c)
        grant_network_db(c)
    from psycopg.conninfo import make_conninfo
    with psycopg.connect(admin_dsn, autocommit=True) as c:
        if c.execute(AGE_SQL).fetchone():
            with psycopg.connect(make_conninfo(admin_dsn, dbname=PRIVATE_DB), autocommit=True) as p:
                p.execute("CREATE EXTENSION IF NOT EXISTS age")
                for r in (RESIDENT, CLEARED):
                    p.execute(sql.SQL("GRANT USAGE ON SCHEMA ag_catalog TO {}").format(sql.Identifier(r)))
        return drift(c)


def main(argv) -> int:
    import psycopg
    from nucleus import people
    dsn = people._dsn()
    if not dsn:
        print("people_gate: no ASTRYX_DSN")
        return 1
    if argv[1:2] == ["apply"]:
        left = apply(dsn)
    else:
        with psycopg.connect(dsn, autocommit=True) as c:
            left = drift(c)
    for d in left:
        print(f"  people_gate: {d}")
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
