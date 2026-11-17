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
  sender_tags(pool, uid) the wire names a uid's own messages carry, for /api/admin/activity: 'owner' for an owner
                         account, else its cv-<label>.<n> handles (who-asked, 11-13)
  reach(pool, uid, nodes) of the agents' tree paths given, the ones the uid may reach (schema.sql member_reach), or
                         None for the whole org (owner 11-17: "a member … only the selected agents")
  caps(pool, uid, role)  what the person may use: their role's FEATURES default, as the Admin panel overrode it
                         (member_feature); {feature: minutes-or-None}. set_feature writes one override, or clears it

asyncpg serves the reads (the backend's pool); cogauth is sync psycopg, so a write opens its own connection to the
org's DSN in a thread. The org's DSN is the backend's own; nothing here reaches another org.
"""
from __future__ import annotations

import asyncio
import re
import time

NODE = re.compile(r"^[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*)*$")   # schema's members_node_check, '' aside
MEMBER_ROLES = ("member", "admin")                 # the roles that talk on the wire (cog-who); 'viewer' only reads
_SLUG = re.compile(r"[^a-z0-9_-]+")


def member_handle(sub: str, label: str = "") -> str | None:
    """The wire handle of a signed-in non-owner account (cog-who): cv-<slug(label)>.<uid>, or None for a sub with no
    uid. ONE rule for every surface that names a member (main.py's who-asked, bridges/canvas.py's signed viewer)."""
    n, at, _ = str(sub).partition("@")
    if not at or not n.isdigit():
        return None
    slug = _SLUG.sub("-", (label or "").lower()).strip("-_")[:24].strip("-_") or "u"
    return f"cv-{slug}.{int(n)}"
RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}
# What each role may use when nobody set otherwise (a member_feature row overrides it per person). Dictation and Talk
# were every member's before 11-17 and stay so; the Call (realtime speech-to-speech, the dearest) is given, not assumed.
FEATURES = {"dictate": {"owner", "admin", "member"}, "call": {"owner"}}
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
    """The from_agent values this uid's own messages carry (main.py's wire_handle): 'owner' for an owner account, else
    member_handle's cv-<label>.<n> under every label it has been written with (the label is display only; the uid,
    after the '.', decides). Empty for a sub with no uid."""
    n, at, _ = str(uid).partition("@")
    if not at or not n.isdigit():
        return []
    if await role_of(pool, uid) == "owner":
        return ["owner"]
    rows = await pool.fetch("SELECT DISTINCT from_agent FROM messages WHERE from_org = 'local' AND from_agent ~ $1",
                            rf"^cv-[a-z0-9_-]*\.{int(n)}$")
    return [r["from_agent"] for r in rows]


_NODES: dict[str, tuple[float, dict]] = {}


def agent_nodes(estate) -> dict[str, str]:
    """Every agent's path in the agents/ tree ('lending/scout'), by name: what a membership's node scopes (schema.sql
    member_role). Read from <estate>/agents, kept 15 s. ONE map for every surface that asks a member's reach (the
    observatory's gate, the canvas bridge)."""
    import time
    from pathlib import Path
    from astryx.core import charter
    root = Path(estate) / "agents"
    at, got = _NODES.get(str(root), (0.0, {}))
    if time.monotonic() - at < 15:
        return got
    out: dict[str, str] = {}
    if root.is_dir():
        for f in charter.charter_files(root):
            out.setdefault(f.stem, "/".join([*charter.group_path(f, root), f.stem]))
    _NODES[str(root)] = (time.monotonic(), out)
    return out


async def agents_reached(pool, uid: str, nodes: dict[str, str]) -> set[str] | None:
    """The AGENTS (by name) a member reaches, from `nodes` (agent_nodes): None = every agent (a whole-org row)."""
    got = await reach(pool, uid, list(nodes.values()))
    return None if got is None else {n for n, node in nodes.items() if node in got}


async def reach(pool, uid: str, nodes: list[str]) -> set[str] | None:
    """The tree paths among `nodes` the uid may reach, or None when it holds a whole-org row (it reaches everything,
    even an agent added after this read). The inheritance is member_reach's, in SQL."""
    if await pool.fetchval("SELECT EXISTS (SELECT 1 FROM members WHERE uid = $1 AND node = '')", uid):
        return None
    return {r[0] for r in await pool.fetch("SELECT member_reach($1, $2::text[])", uid, list(nodes))}


async def overrides(pool, uid: str | None = None) -> dict:
    """{uid: {feature: {allowed, minutes}}} as the Admin panel set them (one uid, or all)."""
    got = await pool.fetch("SELECT uid, feature, allowed, minutes FROM member_feature"
                           + (" WHERE uid = $1" if uid else ""), *([uid] if uid else []))
    out: dict = {}
    for r in got:
        out.setdefault(r["uid"], {})[r["feature"]] = {"allowed": r["allowed"], "minutes": r["minutes"]}
    return out


async def caps(pool, uid: str | None, role: str | None) -> dict:
    """{feature: daily minutes (None = only the org's cap)} for what this person may use. The owner: everything,
    unlimited, whatever a row says. Anyone else: the role's default, overridden per feature by member_feature."""
    if role == "owner":
        return {f: None for f in FEATURES}
    own = (await overrides(pool, uid)).get(uid, {}) if uid else {}
    out = {}
    for f, roles in FEATURES.items():
        o = own.get(f)
        if (o["allowed"] if o else role in roles):
            out[f] = o["minutes"] if o else None
    return out


async def set_feature(pool, uid: str, feature: str, allowed: bool | None, minutes: int | None = None) -> None:
    """One person's override of one feature; allowed None clears it (back to the role's default)."""
    if feature not in FEATURES:
        raise ValueError(f"feature is one of {', '.join(FEATURES)}")
    if allowed is None:
        await pool.execute("DELETE FROM member_feature WHERE uid = $1 AND feature = $2", uid, feature)
        return
    if minutes is not None and not 0 <= int(minutes) <= 1440:
        raise ValueError("minutes is a daily limit, 0 to 1440")
    await pool.execute("INSERT INTO member_feature (uid, feature, allowed, minutes) VALUES ($1, $2, $3, $4) "
                       "ON CONFLICT ON CONSTRAINT member_feature_pkey DO UPDATE SET allowed = EXCLUDED.allowed, "
                       "minutes = EXCLUDED.minutes", uid, feature, bool(allowed),
                       None if minutes is None else int(minutes))
