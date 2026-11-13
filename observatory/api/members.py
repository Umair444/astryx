"""astryx observatory · THIS org's membership, read and written in ONE place (cog-rebuild: the admin panel).

The `members` table is changing shape under a concurrent slice (feat/cog-rls, salvaged from 3f8d5d1): from
(uid PRIMARY KEY, role owner|member|viewer) to (tenant, uid, node DEFAULT '', role owner|admin|member|viewer) with
member_role()/org_role() as the one inheritance rule (the longest matching node prefix) and members_last_owner as the
table's own guard. Every reader and writer in the observatory goes through THIS module, so the change lands here
alone:

  shape(pool)            what the table is today, judged by the catalog (cached SHAPE_TTL s): tree-scoped (a `node`
                         column), org_role() present, and the roles its CHECK admits
  role_of(pool, uid)     the role a signed-in uid holds in the org as a whole: org_role() when the schema has it, else
                         the one row's (the first shape). privacy_gate reads it on every signed request
  rows(pool)             every membership row: uid, node ('' = the whole org), role, added
  grant/revoke(dsn, …)   through astryx.cogauth.grant/revoke, THE one writer of a row (D8), in one transaction that
                         locks the table and judges the END STATE: an org with members and no whole-org owner is
                         refused (LastOwner) on either shape; on the tree shape the table's trigger says so too
  sender_tags(pool, uid) the wire names a uid's own messages carry, for /api/admin/activity. Today none is recorded
                         (POST /api/messages writes 'owner'; the "tag who asked" slice is not built): the empty list
                         means "not attributed", never zero

asyncpg serves the reads (the backend's pool); cogauth is sync psycopg, so a write opens its own connection to the
org's DSN in a thread. The org's DSN is the backend's own; nothing here reaches another org.
"""
from __future__ import annotations

import asyncio
import re
import time

NODE = re.compile(r"^[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*)*$")   # schema's members_node_check, '' aside
RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}
SHAPE_TTL = 30.0


class LastOwner(Exception):
    """The write would leave this org's members with no whole-org owner."""


_shape: tuple[float, dict] | None = None


async def shape(pool) -> dict:
    """{"table": bool, "tree": bool, "org_role": bool, "roles": [...]} for THIS org's members, read from the catalog."""
    global _shape
    now = time.monotonic()
    if _shape and now - _shape[0] < SHAPE_TTL:
        return _shape[1]
    row = await pool.fetchrow(
        "SELECT to_regclass('members') IS NOT NULL AS tbl, "
        "EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass('members') AND attname = 'node' "
        "        AND NOT attisdropped) AS tree, "
        "to_regprocedure('org_role(text)') IS NOT NULL AS fn, "
        "(SELECT string_agg(pg_get_constraintdef(oid), ' ') FROM pg_constraint "
        "  WHERE conrelid = to_regclass('members') AND contype = 'c') AS checks")
    checks = row["checks"] or ""
    roles = [r for r in RANK if f"'{r}'" in checks] or ["owner", "member", "viewer"]
    s = {"table": row["tbl"], "tree": row["tree"], "org_role": row["fn"],
         "roles": sorted(roles, key=lambda r: -RANK[r])}
    _shape = (now, s)
    return s


def forget_shape() -> None:
    global _shape
    _shape = None


async def role_of(pool, uid: str) -> str | None:
    """The role `uid` holds in this org as a whole, or None. Raises on a DB without the table (the caller's public face)."""
    s = await shape(pool)
    if not s["table"]:
        return None
    if s["org_role"]:
        return await pool.fetchval("SELECT org_role($1)", uid)
    return await pool.fetchval("SELECT role FROM members WHERE uid = $1", uid)


async def rows(pool) -> list[dict]:
    s = await shape(pool)
    if not s["table"]:
        return []
    node = "node" if s["tree"] else "''::text AS node"
    got = await pool.fetch(f"SELECT uid, {node}, role, added FROM members ORDER BY added, uid")
    return [{"uid": r["uid"], "node": r["node"], "role": r["role"], "added": r["added"].isoformat()} for r in got]


async def held(pool, uid: str) -> list[dict]:
    """Every row of one uid: [{node, role}]."""
    return [{"node": r["node"], "role": r["role"]} for r in await rows(pool) if r["uid"] == uid]


def _write(dsn: str, act) -> None:
    import psycopg
    from astryx import cogauth  # noqa: F401  (the one writer; imported here so a test's cogauth seam reaches it)
    with psycopg.connect(dsn) as c:
        with c.transaction():
            c.execute("LOCK TABLE members IN SHARE ROW EXCLUSIVE MODE")   # two demotions can't both pass the check
            tree = c.execute("SELECT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass('members') "
                             "AND attname = 'node' AND NOT attisdropped)").fetchone()[0]
            try:
                act(c)
            except psycopg.errors.CheckViolation as e:
                if "last owner" in str(e):
                    raise LastOwner() from None
                raise ValueError("refused by the members table's checks") from None
            root = "role = 'owner' AND node = ''" if tree else "role = 'owner'"
            orphaned = c.execute(f"SELECT EXISTS (SELECT 1 FROM members) AND NOT EXISTS (SELECT 1 FROM members "
                                 f"WHERE {root})").fetchone()[0]
            if orphaned:
                raise LastOwner()      # the transaction rolls back: nothing was written


async def grant(dsn: str, uid: str, role: str, node: str = "") -> None:
    from astryx import cogauth
    await asyncio.to_thread(_write, dsn, lambda c: cogauth.grant(c, uid, role, node))


async def revoke(dsn: str, uid: str, node: str | None = None) -> bool:
    from astryx import cogauth
    out = []
    await asyncio.to_thread(_write, dsn, lambda c: out.append(cogauth.revoke(c, uid, node)))
    return bool(out and out[0])


async def sender_tags(pool, uid: str) -> list[str]:
    """The from_agent values that are this uid's own messages. A `principals` row's handle when that table exists
    (3f8d5d1's shape: the primary owner's is `owner`); else none: the wire does not yet record which signed-in user
    sent a message."""
    if not await pool.fetchval("SELECT to_regclass('principals') IS NOT NULL"):
        return []
    h = await pool.fetchval("SELECT handle FROM principals WHERE uid = $1", uid)
    return [h] if h else []
