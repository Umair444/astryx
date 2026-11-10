#!/usr/bin/env python3
"""test_observatory_overview_roster: the header's agent counts (/api/overview) are the TREE's, as /api/agents reads
them (charter.roster()). The owner, 10-19, saw "18 agents" against 17: a name that once wrote a step without a charter
(seed's onboard.md body, 10-09) was counted. The real handler, its pool on a sqlguard fixture database.
  V1 a step by a name with no charter is not an agent; a live body with no charter is not live; the shipped seed is both
Exit 0 pass · 1 fail · 77 could-not-run."""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_observatory_overview_roster", REPO, deps=("psycopg", "asyncpg", "fastapi"))
try:
    import psycopg
    from astryx.security.sqlguard.fixture import fixture_db
except Exception as e:  # noqa: BLE001
    print(f"SKIP: a subject isn't importable ({type(e).__name__}: {e}).")
    sys.exit(77)

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


GHOST, BODY = f"fxonboard-{os.getpid()}", f"fxbody-{os.getpid()}"   # no charter names either
_fx = fixture_db()
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"SKIP: the fixture database couldn't be built ({type(e).__name__}: {e}).")
    sys.exit(77)
try:
    with psycopg.connect(fx["dsn"], autocommit=True) as c:
        c.execute("INSERT INTO steps (agent, kind, content) VALUES ('seed', 'milestone', 'a charter''s step'), "
                  "(%s, 'milestone', 'a step with no charter')", (GHOST,))
    spec = importlib.util.spec_from_file_location("obs_ovroster", REPO / "observatory" / "api" / "main.py")
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    M.tmux_alive = lambda: {"seed", BODY}

    async def _get():
        import asyncpg
        from psycopg.conninfo import conninfo_to_dict
        kw = conninfo_to_dict(fx["dsn"])
        kw["database"] = kw.pop("dbname")
        M.pool = await asyncpg.create_pool(min_size=1, max_size=1, **{k: v for k, v in kw.items()
                                                                       if k in ("host", "port", "user", "password", "database")})
        try:
            return await M.overview()
        finally:
            await M.pool.close()

    ov = asyncio.run(_get())
    check("V1 the counts are the tree's: the charterless step and the charterless body count nowhere, seed counts",
          ov.get("agents") == 1 and ov.get("live") == 1, f"agents={ov.get('agents')} live={ov.get('live')}")
finally:
    _fx.__exit__(None, None, None)

print("ALL PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
