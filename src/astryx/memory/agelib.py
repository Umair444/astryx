#!/usr/bin/env python3
"""agelib: prepare a connection to use Apache AGE, the same way for a superuser and for a run role (plan-4918 D1).

A SUPERUSER (prod's genesis) loads AGE per session with `LOAD 'age'`, exactly as before. A NON-superuser can't:
Postgres lets it LOAD only from $libdir/plugins ("access to library "age" is not allowed"), and it can't even
READ session_preload_libraries to find out whether AGE is already loaded. So the gate is the role, not the setting:
branch_check's run role gets AGE through a role-level `session_preload_libraries = 'age'` set by the admin
(runscope.open), and USAGE on ag_catalog in the run-owned databases (branch_check_prep), and never LOADs.
"""
SUPER = "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
PATH = 'SET search_path = ag_catalog, "$user", public'


def prepare(cur) -> None:
    """psycopg (sync) cursor or connection."""
    if cur.execute(SUPER).fetchone()[0]:
        cur.execute("LOAD 'age'")
    cur.execute(PATH)


async def aprepare(conn) -> None:
    """psycopg AsyncConnection."""
    if (await (await conn.execute(SUPER)).fetchone())[0]:
        await conn.execute("LOAD 'age'")
    await conn.execute(PATH)
