#!/usr/bin/env python3
"""Oracle: every route is a row (identity-channels P2; owner 11-16: "routes.json and route table should be just route
table … no one edits files"). On the fixture database:
  R1 THE IMPORT, once: each routes-<channel>.json becomes standing rows, every key a route said kept in its rule (a note,
     a webhook), a frontend's table keyed by its `frontend`; each account a route TRUSTED becomes one of the owner's
     (identity_own), the list itself not carried; the file leaves for backups/ (gitignored), so nothing reads it again
  R2 THE OWNER'S SAVE (routes.put): a stale version is refused and changes nothing; a save replaces his routes in one
     act; an agent's connection on a chat he now routes ends, and that agent is told
  R3 A CONNECTION IS A ROUTE BUT NEVER A DOORBELL: in the bridges' table an agent's connection reaches it, and its one
     owner route stays its doorbell
Exit 0 · 1 · 77 (no database)."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "src")]
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_routes", REPO, deps=("psycopg", "asyncpg"), env=False)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402
from astryx.core import routes  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


G1, OWNER = "1" * 18 + "@g.us", "9" * 12 + "@s.whatsapp.net"
import psycopg  # noqa: E402

with fixture_db() as d, psycopg.connect(d["url"], autocommit=True) as c, tempfile.TemporaryDirectory() as td:
    est = Path(td)
    (est / "bridges").mkdir()
    (est / "bridges" / "routes-whatsapp.json").write_text(json.dumps(
        [{"chat": G1, "agent": "seed", "enabled": True, "open": True, "note": "Zeta -> seed", "trusted_jids": [OWNER]}]))
    (est / "bridges" / "routes-frontends.json").write_text(json.dumps(
        [{"frontend": "finance", "agent": "finance", "enabled": True, "callback_url_env": "FE_CB"}]))
    (est / "bridges" / "routes.example.json").write_text("[]")
    print("R1 THE IMPORT")
    n = routes.import_files(c, est)
    rows = {(ch, chat): (agent, rule) for ch, chat, agent, rule in c.execute("SELECT channel, chat, agent, rule FROM route")}
    arm("each file's routes are rows, every key kept in the rule (the trusted list aside)",
        n == {"frontends": 1, "whatsapp": 1} and rows[("whatsapp", G1)] == ("seed", {"enabled": True, "open": True, "note": "Zeta -> seed"}), rows)
    arm("a frontend's table is keyed by its frontend", rows.get(("frontends", "finance"), (None, {}))[1].get("callback_url_env") == "FE_CB", rows)
    arm("each trusted account is now the owner's", c.execute("SELECT identity_who('whatsapp', %s, 'wa-x')", (OWNER,)).fetchone()[0] == "owner")
    arm("the files left for backups/ (gitignored); an example stays", not list((est / "bridges").glob("routes-*.json"))
        and (est / "backups" / "routes-imported" / "routes-whatsapp.json").exists() and (est / "bridges" / "routes.example.json").exists())

    async def owner_save():
        import asyncpg
        from bridges.common import Book
        pool = await asyncpg.create_pool(d["url"], min_size=1, max_size=2)
        now = await routes.standing(pool, "whatsapp")
        try:
            await routes.put(pool, "whatsapp", [{**now[0], "agent": "db"}], "0" * 32)
            stale = "written"
        except routes.Conflict:
            stale = "refused"
        unchanged = (await routes.standing(pool, "whatsapp"))[0]["agent"]
        await pool.execute("INSERT INTO route (channel, chat, agent, purpose, person, opened_by, idle, expires_at) VALUES "
                           "('whatsapp', $1, 'lending', 'open', 'wa-9', 'lending', interval '1 day', now() + interval '1 day')", OWNER)
        book = Book("whatsapp")
        await book.refresh(pool)
        held, bell = book.routes().chat(OWNER), book.routes().doorbell("seed")
        tag = await routes.put(pool, "whatsapp", now + [{"chat": OWNER, "agent": "seed", "enabled": True, "note": "own DM"}],
                               await routes.version(pool, "whatsapp"))
        after = await routes.standing(pool, "whatsapp")
        ver = await routes.version(pool, "whatsapp")
        told = await pool.fetchval("SELECT count(*) FROM messages WHERE to_agent='lending' AND body LIKE '%ended: the owner routed%'")
        gone = await pool.fetchval("SELECT count(*) FROM route WHERE agent='lending'")
        await pool.close()
        return stale, unchanged, held, bell, tag, after, told, gone, ver
    stale, unchanged, held, bell, tag, after, told, gone, ver = asyncio.run(owner_save())
    print("\nR2 THE OWNER'S SAVE")
    arm("a stale version is refused and changes nothing", stale == "refused" and unchanged == "seed")
    arm("a save replaces his routes, and answers the new version", [r["chat"] for r in after] == [G1, OWNER]
        and tag == ver, (after, tag, ver))
    arm("an agent's connection on a chat he now routes ends, and that agent is told", told == 1 and gone == 0, (told, gone))
    print("\nR3 A CONNECTION IS A ROUTE, NEVER A DOORBELL")
    arm("the bridges' table reaches the agent through its connection", held and held["agent"] == "lending" and held.get("connection"), held)
    arm("…and seed's one owner route stays its doorbell", bell and bell["chat"] == G1, bell)

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: every route is a row")
sys.exit(1 if fails else 0)
