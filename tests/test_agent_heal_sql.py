#!/usr/bin/env python3
"""test_agent_heal_sql — arm two's one SQL site (stale(): the rows a deaf resident is sitting on) run against a
throwaway fixture database (src/astryx/security/sqlguard/fixture.py), so sqlguard OBSERVES it. Exit 0 pass · 1 fail · 77 could-not-run."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_agent_heal_sql", REPO, deps=("psycopg",))

try:
    import psycopg
    from astryx.pulse.shipped_triggers import agent_heal as H
    from astryx.security.sqlguard.fixture import fixture_db
except Exception as e:  # noqa: BLE001
    print(f"SKIP: a subject isn't importable ({type(e).__name__}: {e}).")
    sys.exit(77)

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


_fx = fixture_db()
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001
    print(f"SKIP: the fixture database couldn't be built ({type(e).__name__}: {e}).")
    sys.exit(77)

try:
    with psycopg.connect(fx["dsn"], autocommit=True) as c:
        rows = [("x", "local", "pending", 900), ("x", "local", "pending", 600), ("x", "local", "pending", 400),
                ("y", "local", "pending", 30),                   # fresh: a live ear just hasn't drained it yet
                ("z", "local", "delivered", 900),                # heard
                ("w", "other.org", "pending", 900)]              # federation outbound, not a local ear's inbox
        for to, org, status, age in rows:
            c.execute("INSERT INTO messages (from_agent, to_agent, to_org, body, status, ts) "
                      "VALUES ('t', %s, %s, 'b', %s, now() - make_interval(secs => %s))", (to, org, status, age))
    got = H.stale(300, dsn=fx["dsn"])
    check("only LOCAL rows still PENDING past the age count", got is not None and set(got) == {"x"}, got)
    check("…with their count and the oldest's age", got and got["x"][0] == 3 and 895 <= got["x"][1] <= 960, got)
    check("an unreachable database is BLIND (None), never an empty inbox",
          H.stale(300, dsn="postgresql://nobody@127.0.0.1:1/none") is None)
finally:
    _fx.__exit__(None, None, None)

print("ALL PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
