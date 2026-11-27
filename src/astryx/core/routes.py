"""astryx · routes — every route of every channel, one table (identity-channels P2; owner 11-16: "routes.json and route
table should be just route table … no one edits files these days").

A route is one `route` row (schema.sql): channel, chat, agent, purpose (standing: the owner's; open: an agent's
connection; link: an account asked to reply YES), and `rule`, the route's own settings exactly as the bridges have
always read them (open, show, home, tier, signed, note, a Discord webhook, a frontend's callback keys …). As a route
DICT (what bridges/routing.py resolves and validates, and the rail edits) a row is its rule plus chat, agent and, for a
connection or link, its id and person, so no reader changed shape when the files went.

  load(pool, channel)          the live routes of a channel (asyncpg: the bridges and the observatory)
  put(pool, channel, rows, if_match)  the OWNER's routes of a channel replaced as one act (route_put, schema.sql: the
                               one write; put_sync for psycopg): refused if they changed since read (route_version),
                               and a connection on a chat he now routes is ended (his routes win), its agent told
  standing_route(conn, channel, chat)  who the owner routes a chat to (psycopg: connect's guard)
  import_files(conn, estate)   ONCE: each routes-<channel>.json into rows, then the file moves to backups/

CLI: python -m astryx.core.routes import|agents [--estate DIR]   (agents: "channel agent" per enabled owner route)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LIVE = "(expires_at IS NULL OR expires_at > now())"
META = ("id", "purpose", "person", "connection", "opened_by", "expires_at")     # a row's own fields, never in its rule
#                                                                               (route_put strips the same list)
SELECT = ("SELECT id, chat, agent, purpose, rule, person FROM route WHERE channel = $1 AND " + LIVE + " ORDER BY id")


def as_route(r) -> dict:
    """A row as the route dict every reader knows: its rule, its chat and agent; a connection or link carries its id
    (the bridges renew it, link_reply ends it) and its person."""
    rule = r["rule"] if isinstance(r["rule"], dict) else json.loads(r["rule"] or "{}")
    d = {**rule, "chat": r["chat"], "agent": r["agent"]}
    if r["purpose"] != "standing":
        d.update(enabled=True, open=True, show="replies", purpose=r["purpose"], person=r["person"], connection=r["id"])
    return d


def rule_of(route: dict) -> dict:
    """What a route dict says beyond its chat and agent: the row's `rule`, verbatim (an unknown key survives)."""
    return {k: v for k, v in route.items() if k not in ("chat", "agent", *META)}


async def load(pool, channel: str) -> list[dict]:
    return [as_route(r) for r in await pool.fetch(SELECT, channel)]


async def standing(pool, channel: str) -> list[dict]:
    """The owner's routes of a channel, enabled or not (the rail shows and edits all of them)."""
    return [r for r in await load(pool, channel) if "connection" not in r]


async def channels_in_use(pool) -> list[str]:
    return [r["channel"] for r in await pool.fetch("SELECT DISTINCT channel FROM route WHERE purpose = 'standing' ORDER BY 1")]


class Conflict(Exception):
    """The owner's routes changed since they were read."""


async def version(pool, channel: str) -> str:
    return await pool.fetchval("SELECT route_version($1)", channel)


async def put(pool, channel: str, rows: list[dict], if_match: str, by: str = "owner") -> str:
    """Replace a channel's standing routes in one act (route_put, schema.sql: the ONE write, which seed's connect route
    uses too). Returns the new version; Conflict when if_match is stale."""
    import asyncpg
    try:
        return await pool.fetchval("SELECT route_put($1, $2::jsonb, $3, $4)", channel, json.dumps(rows), if_match, by)
    except asyncpg.exceptions.SerializationError:
        raise Conflict() from None


def standing_sync(conn, channel: str) -> list[dict]:
    """The owner's routes of a channel (psycopg), as route dicts."""
    return [as_route({"id": i, "chat": ch, "agent": a, "purpose": "standing", "rule": r, "person": None})
            for i, ch, a, r in conn.execute("SELECT id, chat, agent, rule FROM route WHERE channel = %s AND purpose = "
                                            "'standing' ORDER BY id", (channel,)).fetchall()]


def put_sync(conn, channel: str, rows: list[dict], if_match: str, by: str) -> str:
    """route_put for a psycopg caller (connect's route, on the owner's word)."""
    import psycopg
    try:
        return conn.execute("SELECT route_put(%s, %s::jsonb, %s, %s)", (channel, json.dumps(rows), if_match, by)).fetchone()[0]
    except psycopg.errors.SerializationFailure:
        raise Conflict() from None


def version_sync(conn, channel: str) -> str:
    return conn.execute("SELECT route_version(%s)", (channel,)).fetchone()[0]


def standing_route(conn, channel: str, chat: str) -> str | None:
    """The agent the owner routes this chat to, if any (psycopg)."""
    r = conn.execute("SELECT agent FROM route WHERE channel = %s AND chat = %s AND purpose = 'standing'",
                     (channel, str(chat))).fetchone()
    return r[0] if r else None


def import_files(conn, estate: Path) -> dict[str, int]:
    """ONCE: every bridges/routes-<channel>.json into standing rows (a frontend's table is keyed by `frontend`: that is
    its chat), then the file moves to backups/routes-imported/ (gitignored) so nothing reads it again. A route's
    trusted_* list made its senders the owner: each becomes one of the owner's accounts (identity_own), and the list is
    not carried. Returns rows per channel."""
    out = {}
    for f in sorted((estate / "bridges").glob("routes-*.json")):
        if f.name.endswith(".example.json"):
            continue
        channel = f.name[len("routes-"):-len(".json")]
        rows = json.loads(f.read_text())
        n = 0
        for r in rows if isinstance(rows, list) else []:
            chat = r.get("chat", r.get("frontend"))
            if chat is None or not r.get("agent"):
                continue
            for acct in (r.get("trusted_jids") or []) + (r.get("trusted_ids") or []):   # a trusted sender WAS the owner
                conn.execute("SELECT identity_own(%s, %s)", (channel, str(acct)))      # → one of the owner's accounts
            rule = {k: v for k, v in r.items() if k not in ("chat", "agent", "trusted_jids", "trusted_ids")}
            conn.execute("INSERT INTO route (channel, chat, agent, purpose, rule, opened_by, note) VALUES "
                         "(%s, %s, %s, 'standing', %s::jsonb, 'owner', %s) ON CONFLICT ON CONSTRAINT route_chat_key DO NOTHING",
                         (channel, str(chat), r["agent"], json.dumps(rule), r.get("note")))
            n += 1
        keep = estate / "backups" / "routes-imported"            # backups/ is gitignored: chat ids never reach git
        keep.mkdir(parents=True, exist_ok=True)
        f.rename(keep / f.name)
        out[channel] = n
    return out


if __name__ == "__main__":
    import argparse

    import psycopg

    from astryx import config, paths
    ap = argparse.ArgumentParser(prog="astryx.core.routes")
    ap.add_argument("cmd", choices=["import", "agents"])
    ap.add_argument("--estate", default=str(paths.estate(__file__)))
    a = ap.parse_args()
    with psycopg.connect(config.dsn(Path(a.estate) / ".env", env_first=False)) as conn:
        if a.cmd == "import":
            print("imported", json.dumps(import_files(conn, Path(a.estate))))
        else:
            for ch, agent in conn.execute("SELECT channel, agent FROM route WHERE purpose = 'standing' AND "
                                          "coalesce((rule->>'enabled')::boolean, false) ORDER BY 1, 2").fetchall():
                print(ch, agent)
    sys.exit(0)
