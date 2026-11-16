"""astryx · identity — one person, many accounts (identity-channels P1; owner 11-15: "one identity per person …
make it a standard"; homes/seed/identity-channels/DESIGN.md).

A person is one `identity` row (its wire_name is how every message from them is written); each account they speak
from is an `identity_handle` (channel, account). The ONE minter is the SQL function identity_who (schema.sql), so a
bridge (async), the observatory and a hook (sync) all ask the same thing. This module holds the two writes around it:

  link(conn, wire_name, channel, account)  attach an account to a person (the person confirmed it from that account:
                                           connect(action=link), P3; or the owner's own numbers, below)
  import_owner(conn, estate)               ONCE: every account a route trusted (trusted_jids / trusted_ids, which
                                           made its holder `owner`) becomes a handle of the identity `owner`, so the
                                           bridges stop reading those lists and the owner's power has one source

CLI: python -m astryx.core.identity import-owner [--estate DIR]   (idempotent; prints counts, never an id)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from astryx.core import channels


def link(conn, wire_name: str, channel: str, account: str, label: str | None = None) -> int:
    """Attach (channel, account) to the person named wire_name, creating that identity if it is new. Returns its id.
    An account already linked to SOMEONE ELSE is refused (ValueError): moving a handle between people is an unlink
    first, never a silent overwrite."""
    conn.execute("INSERT INTO identity (wire_name, label) VALUES (%s, %s) ON CONFLICT ON CONSTRAINT identity_wire_name_key "
                 "DO NOTHING", (wire_name, label))
    pid = conn.execute("SELECT id FROM identity WHERE wire_name = %s", (wire_name,)).fetchone()[0]
    held = conn.execute("SELECT identity_id FROM identity_handle WHERE channel = %s AND account = %s",
                        (channel, str(account))).fetchone()
    if held and held[0] not in (None, pid):
        raise ValueError(f"that {channel} account is already linked to another person")
    conn.execute("INSERT INTO identity_handle (channel, account, identity_id) VALUES (%s, %s, %s) "
                 "ON CONFLICT ON CONSTRAINT identity_handle_pkey DO UPDATE SET identity_id = EXCLUDED.identity_id",
                 (channel, str(account), pid))
    return pid


def import_owner(conn, estate: Path) -> int:
    """Each trusted account in every channel's routes file → a handle of `owner`. Returns how many were linked."""
    n = 0
    for c in channels.CHANNELS:
        f = estate / "bridges" / f"routes-{c.name}.json"
        try:
            rows = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        for r in rows if isinstance(rows, list) else []:
            for acct in (r.get("trusted_jids") or []) + (r.get("trusted_ids") or []) if isinstance(r, dict) else []:
                link(conn, "owner", c.name, str(acct))
                n += 1
    return n


if __name__ == "__main__":
    import argparse

    import psycopg

    from astryx import config, paths
    ap = argparse.ArgumentParser(prog="astryx.core.identity")
    ap.add_argument("cmd", choices=["import-owner"])
    ap.add_argument("--estate", default=str(paths.estate(__file__)))
    a = ap.parse_args()
    dsn = config.read_env(Path(a.estate) / ".env").get("ASTRYX_DSN")
    with psycopg.connect(dsn) as conn:
        print(f"linked {import_owner(conn, Path(a.estate))} trusted account(s) to the owner")
    sys.exit(0)
