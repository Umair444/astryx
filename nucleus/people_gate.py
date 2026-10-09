#!/usr/bin/env python3
"""astryx · people_gate — the people library's privilege boundary (build 1a of seed #35894 / memory #35896).

THE SPLIT. The network layer is STRUCTURE: who exists, and that two people are related at all (social_person's
id/label/direct, social_edge, the astryx_social graph). Every agent may read it. The DETAILS (what a relation IS,
who someone is to the owner, the behavioural shape, how sure we are) live in `social_relation`, readable only by
the `people_cleared` role, and are projected into a PRIVATE AGE database whose CONNECT only people_cleared holds.
Granting people_cleared to a charter is the owner's call (Grant: people), never this module's.

GRADE: ACCIDENT-GRADE, NOT PREVENTION (seed #36018, a4 #36015). Every resident runs as the same OS user with full
Bash, and the superuser credential sits in .env (ASTRYX_DSN) and ~/.pgpass, both readable by every resident. A
resident that WANTS the details connects as the superuser and reads them; no GRANT here stops that. What this does
gate: tool paths and default DSNs. Once residents connect as `astryx_resident` (build 1b), an ordinary query or a
graph walk physically can't reach a detail, and a deliberate read needs an explicit credential grab that leaves a
step trail (detection, by org-form + steward). Prevention needs the superuser credential OFF every resident-readable
surface (a separate OS user for admin and services, or a credential broker): owner-level infrastructure.

INERT AS SHIPPED (1a). `astryx_resident` is created NOLOGIN with no password: nothing can connect as it until 1b
(ALTER ROLE ... LOGIN PASSWORD, then the residents' DSN switch) is decided on the privilege census's numbers
(nucleus/privilege_census.py). The grants are real and the oracle proves them on scratch roles.

FAIL-CLOSED POLARITY. The resident reads social_person through a COLUMN-level grant on NETWORK_COLS, so a column
added later is unreadable until someone names it here: an unknown member defaults to hidden.

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
PRIVATE_DB = "astryx_people"          # the private AGE projection; its graph shares the name
NETWORK_DB = "astryx_social"          # the all-agent network graph (nucleus/social_age.py)
NETWORK_COLS = ("org", "id", "kind", "label", "direct", "seen_at")
NETWORK_TABLES = ("social_edge",)     # whole-table SELECT for the resident
DETAIL_TABLE = "social_relation"

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
    """In the org's own database (conn is connected to it, as its owner or a superuser). Idempotent."""
    I = sql.Identifier
    db = conn.execute("SELECT current_database()").fetchone()[0]
    conn.execute(sql.SQL("REVOKE ALL ON {} FROM PUBLIC").format(I(DETAIL_TABLE)))
    conn.execute(sql.SQL("REVOKE ALL ON {} FROM {}").format(I(DETAIL_TABLE), I(resident)))   # a stale grant
    conn.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(I(DETAIL_TABLE), I(cleared)))
    # A table-level SELECT would carry every detail column; REVOKE ALL first so a stale whole-table grant can't
    # survive a re-apply, then the column grant.
    conn.execute(sql.SQL("REVOKE ALL ON social_person FROM {}").format(I(resident)))
    conn.execute(sql.SQL("GRANT SELECT ({}) ON social_person TO {}")
                 .format(sql.SQL(", ").join(map(I, NETWORK_COLS)), I(resident)))
    for t in NETWORK_TABLES:
        conn.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(I(t), I(resident)))
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(I(db), I(resident), I(cleared)))


def ensure_private_db(admin, name: str = PRIVATE_DB, cleared: str = CLEARED) -> bool:
    """The private projection's database, BORN ZERO-WINDOW (plan-4918 #28982): created with connections disallowed,
    PUBLIC revoked and CONNECT granted to `cleared` only, THEN opened. Returns True if it was created now."""
    I = sql.Identifier
    made = admin.execute(DB_SQL, (name,)).fetchone() is None
    if made:
        admin.execute(sql.SQL("CREATE DATABASE {} ALLOW_CONNECTIONS false").format(I(name)))
    admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(I(name)))
    admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(I(name), I(cleared)))
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
    """What is NOT as this module promises, as sentences. Empty = green. `conn` is the org database; `admin` (any
    connection to the cluster, defaults to conn) reads the cluster-wide database ACLs."""
    admin = admin or conn
    out = []
    for r in (resident, cleared):
        if conn.execute(ROLE_SQL, (r,)).fetchone() is None:
            return [f"role {r} is missing"]
    if conn.execute("SELECT to_regclass(%s)", (DETAIL_TABLE,)).fetchone()[0] is None:
        return [f"table {DETAIL_TABLE} is missing (schema.sql not applied)"]
    q = lambda s, *a: conn.execute(s, a).fetchone()[0]
    if q("SELECT has_table_privilege('public', %s, 'SELECT')", DETAIL_TABLE):
        out.append(f"PUBLIC can SELECT {DETAIL_TABLE}")
    if q("SELECT has_table_privilege(%s, %s, 'SELECT')", resident, DETAIL_TABLE):
        out.append(f"{resident} can SELECT {DETAIL_TABLE}")
    if not q("SELECT has_table_privilege(%s, %s, 'SELECT')", cleared, DETAIL_TABLE):
        out.append(f"{cleared} can't SELECT {DETAIL_TABLE}")
    hidden = [c for (c,) in conn.execute(
        "SELECT attname FROM pg_attribute WHERE attrelid = 'social_person'::regclass AND attnum > 0 "
        "AND NOT attisdropped AND attname <> ALL(%s) ORDER BY attnum", (list(NETWORK_COLS),)).fetchall()]
    leak = [c for c in hidden if q("SELECT has_column_privilege(%s, 'social_person', %s, 'SELECT')", resident, c)]
    if leak:
        out.append(f"{resident} can read social_person detail column(s) {', '.join(leak)}")
    miss = [c for c in NETWORK_COLS if not q("SELECT has_column_privilege(%s, 'social_person', %s, 'SELECT')",
                                             resident, c)]
    if miss:
        out.append(f"{resident} can't read network column(s) {', '.join(miss)}")
    if admin.execute(DB_SQL, (private_db,)).fetchone() is None:
        out.append(f"database {private_db} is missing")
    else:
        for who, want in (("public", False), (resident, False), (cleared, True)):
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
                p.execute(sql.SQL("GRANT USAGE ON SCHEMA ag_catalog TO {}").format(sql.Identifier(CLEARED)))
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
