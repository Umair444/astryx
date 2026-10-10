#!/usr/bin/env python3
"""astryx · ear_store — hearing's utterance RETENTION (plan-8674 S1).

Utterances live in the org's ONE database (owner ruling 2026-10-10, seed #42311: "one database for every agent;
information in astryx is shared and usable by every other agent"). `utterances` is declared in schema.sql like
every other table, partitioned by UTC DAY. What this module owns is the retention: partitions are made ahead and
an expired day is DROPPED whole, never DELETEd row by row.

  maintain(conn)        DROP every partition whose start is older than the TTL, then create day partitions
                        [today, today+2]; each statement alone, failures returned, never raised. Called by the ear service on start and before writes, and on the pulse by
                        nucleus/shipped_triggers/ear_retention.py (an idle week still expires).
  ttl_findings(conn)    the catalog-only TTL arm: the OLDEST attached partition must start within the TTL; a
                        DEFAULT (unbounded) partition is RED. Reads pg_catalog only, never a row.

GRADE, stated: DROP is LOGICAL erasure at the TTL. Dropped tuples survive in recycled WAL until overwritten, and a
nightly backup (nucleus/backup.sh dumps this database, keeps the last 14) holds whatever utterances existed at
dump time for the BACKUP's own retention. Branch-check run bases copy the table but not its rows
(branch_check_prep.DUMP_EXCLUDE). Neither is a secure delete.

    venv/bin/python -m nucleus.ear_store maintain   # one retention pass now
    venv/bin/python -m nucleus.ear_store ttl        # the TTL arm: 0 GREEN, 1 RED, 77 table absent (schema not applied)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import sql

REPO = Path(__file__).resolve().parent.parent
EXIT_BLIND = 77


def _env(key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    f = REPO / ".env"
    if f.is_file():
        for line in f.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return ""


TTL_MAX = 7


def ttl_days() -> int:
    """Retention in days. SHORT by rule (a): default 3, floor 1, CEILING TTL_MAX. One knob, read by the writer and
    the arm alike, so the ceiling is what keeps "short" true: EAR_TTL_DAYS=3650 in .env reads as 7. A longer window
    is a code change, reviewed, never an .env edit."""
    try:
        return min(TTL_MAX, max(1, int(_env("EAR_TTL_DAYS") or 3)))
    except ValueError:
        return 3


def _day(t: datetime) -> datetime:
    t = t.astimezone(timezone.utc)
    return datetime(t.year, t.month, t.day, tzinfo=timezone.utc)


PARTS_SQL = ("SELECT c.relname, (regexp_match(pg_get_expr(c.relpartbound, c.oid), "
             "'FROM \\(''([^'']+)''\\)'))[1]::timestamptz AS lo, pg_get_expr(c.relpartbound, c.oid) AS bound "
             "FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
             "WHERE i.inhparent = 'public.utterances'::regclass ORDER BY 2 NULLS FIRST")


def partitions(conn) -> list[tuple[str, datetime | None, str]]:
    """(name, lower bound, bound text) of every ATTACHED partition. CATALOG ONLY: never touches a row."""
    return [tuple(r) for r in conn.execute(PARTS_SQL).fetchall()]


def maintain(conn, ttl: int | None = None, ahead: int = 2, now: datetime | None = None) -> dict:
    """DROP every attached partition whose lower bound is older than now - ttl days, THEN create day partitions
    [today, today+ahead]. Conservative: a day goes as soon as its START passes the TTL, so text is kept at most ttl
    days (and up to one day less). DROP, never DELETE.

    Erasure first and every statement on its own: one bad partition (a same-day table under another name from a
    restore or a hand fix, a lock) never stops the drops or the other days. A failure is RETURNED in "errors" as
    (verb, partition, error type), never raised, so the caller still runs the TTL arm and reports both."""
    ttl = ttl or ttl_days()
    now = now or datetime.now(timezone.utc)
    made, dropped, errors = [], [], []
    cutoff = now - timedelta(days=ttl)

    def one(verb, name, stmt, into):
        try:
            with conn.transaction():
                conn.execute(stmt)
            into.append(name)
        except psycopg.Error as e:
            errors.append((verb, name, type(e).__name__))

    for name, lo, _ in partitions(conn):
        if lo is None or lo < cutoff:
            one("drop", name, sql.SQL("DROP TABLE {}").format(sql.Identifier(name)), dropped)
    have = {n for n, _, _ in partitions(conn)}
    for k in range(ahead + 1):
        lo = _day(now) + timedelta(days=k)
        name = f"utterances_p{lo:%Y%m%d}"
        if name not in have:
            one("create", name, sql.SQL("CREATE TABLE IF NOT EXISTS {} PARTITION OF utterances FOR VALUES FROM ({}) TO ({})")
                .format(sql.Identifier(name), sql.Literal(lo.isoformat()),
                        sql.Literal((lo + timedelta(days=1)).isoformat())), made)
    return {"created": made, "dropped": dropped, "errors": errors}


def ttl_findings(conn, ttl: int | None = None, now: datetime | None = None) -> list[str]:
    """RED sentences. The OLDEST attached partition's lower bound must be >= now - ttl. A partition with no
    parseable lower bound (DEFAULT, MINVALUE) is RED: it can hold text of any age. Reads pg_catalog only."""
    ttl = ttl or ttl_days()
    now = now or conn.execute("SELECT now()").fetchone()[0]
    cutoff = now - timedelta(days=ttl)
    if conn.execute("SELECT to_regclass('public.utterances')").fetchone()[0] is None:
        return ["utterances table is missing (schema.sql not applied)"]
    if conn.execute("SELECT relkind FROM pg_class WHERE oid = 'public.utterances'::regclass").fetchone()[0] != "p":
        return ["utterances is not partitioned: retention-by-DROP is impossible"]
    out = []
    for name, lo, bound in partitions(conn):
        if lo is None:
            out.append(f"partition {name} has no dated lower bound ({bound}): unbounded retention")
        elif lo < cutoff:
            out.append(f"partition {name} starts {lo:%Y-%m-%d %H:%M}Z, older than the {ttl}-day TTL "
                       f"(cutoff {cutoff:%Y-%m-%d %H:%M}Z)")
    return out


def main(argv) -> int:
    verb = argv[1] if len(argv) > 1 else ""
    dsn = _env("ASTRYX_DSN")
    if verb not in ("maintain", "ttl") or not dsn:
        print(__doc__)
        return 2
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as c:
        if c.execute("SELECT to_regclass('public.utterances')").fetchone()[0] is None:
            print("ear_store: NOT RUN, utterances is absent (apply schema.sql)")
            return EXIT_BLIND
        if verb == "maintain":
            r = maintain(c)
            print(f"ear_store maintain: {len(r['created'])} partition(s) created, {len(r['dropped'])} dropped")
            for verb, name, err in r["errors"]:
                print(f"  ERROR {verb} {name}: {err}")
            return 1 if r["errors"] else 0
        f = ttl_findings(c)
        for x in f:
            print(f"  RED {x}")
        print(f"ear_store ttl: {'RED' if f else 'GREEN'} ({len(partitions(c))} partitions, ttl {ttl_days()}d)")
        return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
