"""The org's NOTIFY channels (cog-rls slice 3, RLS.md §2): `ax<n>_<suffix>`, n = cog.orgs.n of the LOGIN role's org.

NOTIFY is database-wide and any role may LISTEN on any name, so every doorbell carries the org that rang it. The
database is the ONE place a name is built (cog.chan for a listener, cog.chan_of(tenant, …) in the senders' triggers),
so Python, node and SQL can't drift. Callers keep the old logical names (`astryx_wire`, `astryx_steps`, …) for their
dispatch; this maps physical → logical.
"""


async def listen(conn, suffixes, put) -> dict:
    """asyncpg: LISTEN on this org's channel for each suffix ('wire', 'steps', 'msg_seed', …); every notification is
    handed to put(logical, payload) with logical = 'astryx_<suffix>'. Returns {physical: logical}."""
    names = {}
    for sfx in suffixes:
        names[await conn.fetchval("SELECT cog.chan($1::text)", sfx)] = f"astryx_{sfx}"
    for ch in names:
        await conn.add_listener(ch, lambda c, p, chan, payload: put(names.get(chan, chan), payload))
    return names


async def chan(conn, suffix: str) -> str:
    """asyncpg: this org's physical channel for one suffix (a sender that rings by hand)."""
    return await conn.fetchval("SELECT cog.chan($1::text)", suffix)
