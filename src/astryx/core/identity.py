"""astryx · identity — one person, many accounts (identity-channels P1; owner 11-15: "one identity per person …
make it a standard"; homes/seed/identity-channels/DESIGN.md).

A person is one `identity` row (its wire_name is how every message from them is written); each account they speak
from is an `identity_handle` (channel, account). Everything that decides lives in SQL (schema.sql), so a bridge
(async), the observatory and a hook (sync) all ask the same thing:
  identity_who   the ONE minter: the wire name a message from (channel, account) is written as
  identity_link  the ONE linker: an account joins a person who signed in (the person's own YES, "Your channels")
  identity_own   the owner's accounts only: the route import (each account a route used to trust) and the owner's own
                 YES; no other link can ever reach `owner`

link() below is identity_link for Python callers.
"""
from __future__ import annotations


def link(conn, wire_name: str, channel: str, account: str) -> int:
    """Attach (channel, account) to the person named wire_name (identity_link). Returns its id. Refused (ValueError):
    a name that is no signed-in account, or an account already linked to someone else."""
    import psycopg
    try:
        return conn.execute("SELECT identity_link(%s, %s, %s)", (wire_name, channel, str(account))).fetchone()[0]
    except (psycopg.errors.UniqueViolation, psycopg.errors.ForeignKeyViolation) as e:
        raise ValueError(str(e).splitlines()[0]) from None
