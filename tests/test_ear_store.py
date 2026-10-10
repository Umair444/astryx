#!/usr/bin/env python3
"""Oracle: hearing's utterance retention (plan-8674 S1): `utterances` in schema.sql + nucleus/ear_store.py + the shipped
retention trigger, on a FIXTURE database (schema.sql applied whole, dropped after; nothing live is touched).

Arms, each with its RED control:
  TABLE     schema.sql declares `utterances` partitioned by range, with NO default partition: a row for a day that has
            no partition is REFUSED (so nothing can pile up outside retention).
  TTL       GREEN on fresh day partitions. RED on a partition planted ONE DAY past the TTL, and on a DEFAULT partition.
            maintain() DROPs the expired partition (the table is gone; no DELETE: the fresh row is intact). GREEN.
  TRIGGER   the shipped trigger's tick maintains and stays silent while green; with retention broken (maintain a
            no-op) it reports the RED once, stays quiet the next tick, and re-nags after a day.
Needs a DSN that can CREATE DATABASE (the sqlguard fixture), else 77.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import psycopg
    from psycopg import sql
    from nucleus.sqlguard.fixture import FixtureUnavailable, fixture_db
except Exception as e:                                              # noqa: BLE001
    print(f"SKIP: {type(e).__name__}: {e}")
    sys.exit(77)
from nucleus import ear_store as E  # noqa: E402
from nucleus.shipped_triggers import ear_retention as T  # noqa: E402

fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


def plant(c, lo):
    name = f"utterances_p{lo:%Y%m%d}"
    c.execute(sql.SQL("CREATE TABLE {} PARTITION OF utterances FOR VALUES FROM ({}) TO ({})").format(
        sql.Identifier(name), sql.Literal(lo.isoformat()), sql.Literal((lo + timedelta(days=1)).isoformat())))
    c.execute("INSERT INTO utterances (ts, text) VALUES (%s, 'planted old words')", (lo + timedelta(hours=1),))
    return name


try:
    with fixture_db() as fx, psycopg.connect(fx["dsn"], autocommit=True) as c:
        kind = c.execute("SELECT relkind FROM pg_class WHERE oid = 'utterances'::regclass").fetchone()[0]
        want("schema.sql declares utterances partitioned (relkind p)", kind == "p", kind)
        try:
            c.execute("INSERT INTO utterances (text) VALUES ('no day for me')")
            refused = False
        except psycopg.errors.CheckViolation:
            refused = True
        want("RED control: with no partition (and no DEFAULT) a row is REFUSED, never kept outside retention", refused)
        m = E.maintain(c, ttl=3)
        want("maintain creates today + 2 day partitions", len(m["created"]) == 3 and not m["dropped"], str(m))
        c.execute("INSERT INTO utterances (text, view, backend) VALUES ('fresh words', 'test', 'none')")
        want("a row for today lands", c.execute("SELECT count(*) FROM utterances").fetchone()[0] == 1)
        want("TTL GREEN on fresh partitions", E.ttl_findings(c, ttl=3) == [])
        now = datetime.now(timezone.utc)
        old = plant(c, E._day(now) - timedelta(days=4))            # TTL 3 → starts one day past it
        f1 = E.ttl_findings(c, ttl=3)
        want("RED control: a partition planted one day past the TTL turns the arm RED, naming it",
             len(f1) == 1 and old in f1[0], str(f1))
        m = E.maintain(c, ttl=3)
        left = c.execute("SELECT count(*) FROM utterances").fetchone()[0]
        want("maintain DROPs the expired partition (DROP, not DELETE: the table is gone, the fresh row intact)",
             m["dropped"] == [old] and c.execute("SELECT to_regclass(%s)", (old,)).fetchone()[0] is None and left == 1,
             f"{m} left={left}")
        want("TTL GREEN again after the drop", E.ttl_findings(c, ttl=3) == [])
        c.execute("CREATE TABLE utterances_default PARTITION OF utterances DEFAULT")
        f2 = E.ttl_findings(c, ttl=3)
        want("RED control: a DEFAULT partition (unbounded retention) is RED", any("utterances_default" in x for x in f2),
             str(f2))
        E.maintain(c, ttl=3)
        want("maintain drops a DEFAULT partition too", c.execute("SELECT to_regclass('utterances_default')").fetchone()[0]
             is None)

        # the shipped trigger
        st = {}
        want("trigger tick: maintains and is silent while green", T.tick(st, c) is None and "last" in st, str(st))
        real = E.maintain
        E.maintain = lambda conn, **k: {"created": [], "dropped": []}         # retention broken
        try:
            old2 = plant(c, E._day(now) - timedelta(days=10))
            m1 = T.tick(st, c)
            m2 = T.tick(st, c)
            m3 = T.tick(st, c, now=st["nagged"] + T.RENAG_S + 1)
        finally:
            E.maintain = real
        want("RED control: retention broken → the trigger reports the RED once, quiet next tick, re-nags after a day",
             m1 and old2 in m1 and m2 is None and m3 and old2 in m3, f"{m1!r} / {m2!r} / {m3!r}")
        want("healed: the next tick drops it and is silent", T.tick(st, c) is None and E.ttl_findings(c) == [])
except FixtureUnavailable as e:
    print(f"SKIP: {e}")
    sys.exit(77)

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
