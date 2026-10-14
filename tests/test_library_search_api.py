#!/usr/bin/env python3
"""test_library_search_api — the reference desk's endpoint over library.search (plan-8018 S3; seed's half of the
SPLIT): /api/memory/search maps each graph name to a book (shelf/slug/anchor) or a wiki stem, keeps the snippet as
plain text with ⟦⟧ marks, returns nothing for a blank q, and reports `unavailable` (not a 500) where library.* is
absent. A fixture database only (schema.sql applied whole); passages are seeded directly, so memory's ingest isn't
needed here (its own oracle is tests/test_library_passage.py)."""
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_library_search_api", REPO, deps=("psycopg", "asyncpg", "fastapi"))
import asyncpg  # noqa: E402
import psycopg  # noqa: E402
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails += 1


DOCS = [("library:architecture/the-room#voices", "Voices", "The room speaks in each agent's own voice."),
        ("library:architecture/the-room", "The Room", "One voice for the org: the ear hears, the wire carries."),
        ("agents", "Agents", "Every agent has a charter and a home.")]

with fixture_db() as fx:
    os.environ.update({"ASTRYX_DSN": fx["dsn"], "OBS_KEY": "test-library-search"})
    c = psycopg.connect(fx["dsn"], autocommit=True)
    for nid, head, text in DOCS:
        c.execute("INSERT INTO library.passage (node_id, heading, text, len, root_digest) VALUES (%s, %s, %s, %s, 'r')",
                  (nid, head, text, len(text.split())))
    c.execute("INSERT INTO library.lexeme_df (word, ndoc, root_digest) SELECT w, count(*), 'r' FROM library.passage, "
              "unnest(tsvector_to_array(tsv)) w GROUP BY w")
    c.execute("INSERT INTO library.stats (n, avgdl, root_digest) SELECT count(*), avg(len), 'r' FROM library.passage")

    from observatory.api import main as M

    async def run():
        M.pool = await asyncpg.create_pool(fx["url"], min_size=1, max_size=2)
        try:
            r = await M.library_search("voice", 5)
            ids = [h["id"] for h in r["hits"]]
            arm("a query finds the passage that holds it", "library:architecture/the-room#voices" in ids, r)
            h = next((x for x in r["hits"] if x["id"] == "library:architecture/the-room#voices"), {})
            arm("a book section maps to its shelf, slug and anchor",
                (h.get("kind"), h.get("shelf"), h.get("slug"), h.get("anchor")) == ("book", "architecture", "the-room", "voices"), h)
            arm("the snippet is plain text with ⟦⟧ marks, never HTML", "⟦" in h.get("snippet", "") and "<" not in h.get("snippet", "<"), h)
            w = (await M.library_search("charter", 5))["hits"]
            arm("a wiki passage maps to its stem", [(x["kind"], x["slug"], x["shelf"]) for x in w] == [("wiki", "agents", None)], w)
            arm("a query nothing matches returns no hits", (await M.library_search("zeppelin", 5))["hits"] == [])
            arm("a blank query returns no hits without touching the DB", (await M.library_search("   ", 5)) == {"hits": []})
            c.execute("ALTER SCHEMA library RENAME TO library_gone")
            try:
                u = await M.library_search("voice", 5)
            finally:
                c.execute("ALTER SCHEMA library_gone RENAME TO library")
            arm("an org without library.* gets 'unavailable', not a 500", u == {"hits": [], "unavailable": True}, u)
        finally:
            await M.pool.close()

    asyncio.run(run())
    c.close()

print("ALL PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
