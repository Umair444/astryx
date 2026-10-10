#!/usr/bin/env python3
"""Oracle: hearing's utterance retention (plan-8674 S1): `utterances` in schema.sql + nucleus/ear_store.py + the shipped
retention trigger, on a FIXTURE database (schema.sql applied whole, dropped after; nothing live is touched).

Arms, each with its RED control:
  TABLE     schema.sql declares `utterances` partitioned by range, with NO default partition: a row for a day that has
            no partition is REFUSED (so nothing can pile up outside retention).
  TTL       GREEN on fresh day partitions. RED on a partition planted ONE DAY past the TTL, and on a DEFAULT partition.
            maintain() DROPs the expired partition (the table is gone; no DELETE: the fresh row is intact). GREEN.
  R1        (a4) an expired day plus a hand-made partition overlapping tomorrow: maintain does not raise, the expired
            words are gone, the other days are made, the create failure is returned and the trigger reports it.
  R2        (a4) the branch-check run base dump (branch_check_prep.DUMP_EXCLUDE) keeps the table, copies no row;
            RED control: the same dump without it carries the words.
  R4        (a4) EAR_TTL_DAYS is clamped to [1, TTL_MAX]: 3650 in .env reads as TTL_MAX.
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

        # a4 R1: one bad partition must not stop retention. An expired day holding words, plus a hand-made partition
        # under another name covering TOMORROW, so creating utterances_p<tomorrow> fails (overlap).
        exp = plant(c, E._day(now) - timedelta(days=5))
        tmw = E._day(now) + timedelta(days=1)
        c.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(f"utterances_p{tmw:%Y%m%d}")))
        c.execute(sql.SQL("CREATE TABLE utterances_manual PARTITION OF utterances FOR VALUES FROM ({}) TO ({})").format(
            sql.Literal(tmw.isoformat()), sql.Literal((tmw + timedelta(days=1)).isoformat())))
        try:
            m = E.maintain(c, ttl=3, ahead=3)
            raised = None
        except Exception as e:                                              # noqa: BLE001
            m, raised = {}, type(e).__name__
        words = c.execute("SELECT count(*) FROM utterances WHERE text = 'planted old words'").fetchone()[0]
        want("R1: an overlapping hand-made partition does not stop retention: maintain does not raise, the expired day "
             "is DROPPED (its words gone), the other days are still made, and the failure is RETURNED",
             raised is None and exp in m.get("dropped", []) and words == 0
             and c.execute("SELECT to_regclass(%s)", (exp,)).fetchone()[0] is None
             and any(v == "create" and n == f"utterances_p{tmw:%Y%m%d}" for v, n, _ in m.get("errors", []))
             and f"utterances_p{tmw + timedelta(days=2):%Y%m%d}" in m.get("created", []),
             f"raised={raised} m={m} words={words}")
        want("R1: the TTL arm is GREEN after (the expired day is gone)", E.ttl_findings(c, ttl=3) == [],
             str(E.ttl_findings(c, ttl=3)))
        st = {}
        r1 = T.tick(st, c)
        want("R1: the trigger still REPORTS the create failure (the overlap is not swallowed)",
             r1 is not None and f"create utterances_p{tmw:%Y%m%d}" in r1 and st["last"]["errors"] == 1, repr(r1))
        c.execute("DROP TABLE utterances_manual")
        want("R1: healed (overlap removed) → the next pass makes the day and the trigger is silent",
             T.tick(st, c) is None and st["last"]["errors"] == 0, str(st))

        # a4 R4: the TTL knob has a ceiling, so "short" survives an .env edit
        import os
        saved = os.environ.get("EAR_TTL_DAYS")
        try:
            for raw, want_d in (("3650", E.TTL_MAX), ("0", 1), ("x", 3), ("5", 5)):
                os.environ["EAR_TTL_DAYS"] = raw
                want(f"R4: EAR_TTL_DAYS={raw} reads as {want_d}", E.ttl_days() == want_d, str(E.ttl_days()))
        finally:
            if saved is None:
                os.environ.pop("EAR_TTL_DAYS", None)
            else:
                os.environ["EAR_TTL_DAYS"] = saved

        # a4 R2: a branch-check run base (nucleus/branch_check_prep.build_base pg_dumps the whole DB) copies the
        # utterances TABLE but never its rows. Same argv list build_base uses, on this fixture.
        import subprocess
        from nucleus import branch_check_prep as bp
        c.execute("INSERT INTO utterances (text, view, backend) VALUES ('words a base must not copy', 'test', 'none')")

        def dumped(extra):
            src, env = bp._argv_safe(fx["dsn"], c.info.dbname)
            r = subprocess.run(["pg_dump", "-Fp", *extra, "-d", src], capture_output=True, text=True, env=env,
                               timeout=120)
            return r.returncode, r.stdout
        rc0, plain = dumped([])
        rc1, cut = dumped(bp.DUMP_EXCLUDE)
        want("RED control: a plain whole-DB dump carries the words", rc0 == 0 and "words a base must not copy" in plain,
             f"rc={rc0}")
        want("R2: build_base's DUMP_EXCLUDE dump carries the utterances table but none of its rows",
             rc1 == 0 and "words a base must not copy" not in cut and "CREATE TABLE public.utterances" in cut,
             f"rc={rc1}")

        # the owner's footnote names backup.sh's keep: the constant must be backup.sh's own default (a4 #43410 R1)
        import re
        keep = re.search(r"^KEEP=\$\{1:-(\d+)\}", (REPO / "nucleus/backup.sh").read_text(), re.M)
        want("BACKUP_KEEP_DAYS is backup.sh's KEEP default (what the ear footnote tells the owner)",
             keep is not None and int(keep.group(1)) == E.BACKUP_KEEP_DAYS, f"{keep and keep.group(1)} vs {E.BACKUP_KEEP_DAYS}")

        # the shipped trigger
        st = {}
        want("trigger tick: maintains and is silent while green", T.tick(st, c) is None and "last" in st, str(st))
        real = E.maintain
        E.maintain = lambda conn, **k: {"created": [], "dropped": [], "errors": []}   # retention broken
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
        import contextlib
        import io
        import os
        os.environ["ASTRYX_DSN"] = fx["dsn"]                       # the CLI, on the fixture
        for verb, rc_want in (("maintain", 0), ("ttl", 0)):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = E.main(["ear_store", verb])
            want(f"CLI `ear_store {verb}` → {rc_want}", rc == rc_want, f"{rc} {buf.getvalue()[-200:]}")
except FixtureUnavailable as e:
    print(f"SKIP: {e}")
    sys.exit(77)

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
