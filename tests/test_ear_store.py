#!/usr/bin/env python3
"""Oracle: hearing's EAR STORE (plan-8674 S1, nucleus/ear_store.py): D1 + the catalog TTL arm + D2's reader census.

Runs the EXACT apply/maintain/census code on SCRATCH roles and a SCRATCH database (astryx_eart_<pid>_*), with a
scratch PGPASSFILE; it never creates, reads or changes the live astryx_ear or a live role. Debris of a killed run is
reaped by pid at start; our own in finally.

Arms (each with its RED control):
  STORE     the database is private (PUBLIC can't CONNECT; a role outside the door group is refused), has NO AGE
            preload, the roles are NOSUPERUSER, passwords went to the pgpass file only (0600), re-apply is a no-op.
  TEXT      the audit role (the census/TTL checker) is REFUSED SELECT on utterances: "never reads text" is a privilege.
  TTL       GREEN on fresh day partitions. RED on a partition planted ONE DAY past the TTL (and on a DEFAULT
            partition). maintain() DROPs it (partition gone; no DELETE: the other partitions' rows are intact), GREEN.
  READERS   a spoofing outsider (application_name='astryx-ear-svc') is reported, graded on session_user, with its
            claim quoted; the door's own login is not. One-shot logins are recorded once each. RED: the trigger
            DISABLED → LOUD; DROPPED → LOUD; re-apply restores it.

Needs a role that can CREATE DATABASE and CREATE ROLE on a PG with login event triggers (17+), else 77.
"""
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
EXIT_SKIP = 77


def skip(m):
    print(f"SKIP: {m}")
    sys.exit(EXIT_SKIP)


try:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
except Exception as e:                                              # noqa: BLE001
    skip(f"{type(e).__name__}: {e} — needs the org runtime")

from nucleus import ear_store as E  # noqa: E402
from nucleus.sqlguard.fixture import live_dsn  # noqa: E402

PID = os.getpid()
NAME = re.compile(r"^astryx_eart_(\d+)_[a-z]+$")
DB, DOOR, SVC, AUD, OUT, EVT = (f"astryx_eart_{PID}_{s}" for s in ("db", "door", "svc", "aud", "out", "evt"))
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


def _gone(pid):
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def reap(adm, mine=False):
    def ours(n):
        m = NAME.match(n)
        return m and (int(m.group(1)) == PID if mine else _gone(int(m.group(1))))
    for (d,) in adm.execute("SELECT datname FROM pg_database").fetchall():
        if ours(d):
            adm.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(d)))
    for (r,) in adm.execute("SELECT rolname FROM pg_roles ORDER BY rolname DESC").fetchall():
        if ours(r):
            adm.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(r)))


def refused(dsn, stmt=None):
    try:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as c:
            if stmt:
                c.execute(stmt).fetchall()
        return None
    except psycopg.Error as e:
        return str(e)


try:
    ADMIN = live_dsn()
    admin = psycopg.connect(ADMIN, autocommit=True, connect_timeout=5)
except Exception as e:                                              # noqa: BLE001
    skip(f"no reachable admin DSN ({type(e).__name__})")
sup, cdb, crole = admin.execute("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles "
                                "WHERE rolname = current_user").fetchone()
if not sup:
    skip("needs a superuser (CREATE EVENT TRIGGER is superuser-only): VERIFIED NOTHING")
if admin.info.server_version < 170000:
    skip(f"server {admin.info.server_version} has no login event triggers (PG 17+)")

TMP = Path(tempfile.mkdtemp(prefix="test-ear-store-"))
PGPASS = TMP / "pgpass"
# The scratch roles' passwords live in THIS scratch pgpass (apply's `pgpass=`), never ~/.pgpass. libpq's own
# PGPASSFILE is left alone: the org DSN is password-less (plan-5497) and authenticates from ~/.pgpass.


def as_(role, app=None):
    pw = next((l.rsplit(":", 1)[1] for l in PGPASS.read_text().splitlines() if l.split(":")[3] == role), None) \
        if PGPASS.exists() else None
    return make_conninfo(E.role_dsn(role, db=DB, base=ADMIN, app=app), **({"password": pw} if pw else {}))


reap(admin)
try:
    r1 = E.apply(ADMIN, db=DB, door=DOOR, svc=SVC, audit=AUD, evt=EVT, pgpass=PGPASS)
    want("apply creates the database and both LOGIN roles", r1["created_db"] and sorted(r1["new_roles"]) == sorted([SVC, AUD]),
         str(r1))
    # ── STORE ─────────────────────────────────────────────────────────────────────────────────────────────────
    q = lambda s, *a: admin.execute(s, a).fetchone()[0]
    want("PUBLIC can't CONNECT to the ear database", not q("SELECT has_database_privilege('public', %s, 'CONNECT')", DB))
    want("the door group holds CONNECT", q("SELECT has_database_privilege(%s, %s, 'CONNECT')", DOOR, DB))
    attrs = admin.execute("SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolreplication "
                          "FROM pg_roles WHERE rolname = ANY(%s) ORDER BY 1", ([DOOR, SVC, AUD],)).fetchall()
    want("roles: door NOLOGIN, svc/audit LOGIN; none SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS/REPLICATION",
         len(attrs) == 3 and all(not any(a[2:]) for a in attrs)
         and {a[0]: a[1] for a in attrs} == {DOOR: False, SVC: True, AUD: True}, str(attrs))
    pre = admin.execute("SELECT setconfig FROM pg_db_role_setting s JOIN pg_database d ON d.oid = s.setdatabase "
                        "WHERE d.datname = %s AND s.setrole = 0", (DB,)).fetchone()
    want("no AGE preload on the ear database (preload=None)", not pre or not any("age" in x for x in (pre[0] or [])),
         str(pre))
    lines = PGPASS.read_text().splitlines()
    want("the passwords went to the pgpass file, mode 0600, one exact entry per new role",
         len(lines) == 2 and oct(PGPASS.stat().st_mode & 0o777) == "0o600"
         and {l.split(":")[3] for l in lines} == {SVC, AUD} and all(l.split(":")[2] == DB for l in lines))
    r2 = E.apply(ADMIN, db=DB, door=DOOR, svc=SVC, audit=AUD, evt=EVT, pgpass=PGPASS)
    want("re-apply is a no-op (no new database, no new role, pgpass unchanged)",
         not r2["created_db"] and not r2["new_roles"] and PGPASS.read_text().splitlines() == lines, str(r2))
    admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER").format(
        sql.Identifier(OUT), sql.Literal(admin.pgconn.encrypt_password(b"outsider-pw-123", OUT.encode(),
                                                                       b"scram-sha-256").decode())))
    out_dsn = make_conninfo(E.role_dsn(OUT, db=DB, base=ADMIN), password="outsider-pw-123")
    err = refused(out_dsn)
    want("RED control: a LOGIN role outside the door group is refused CONNECT", err and "permission denied" in err, str(err))

    # ── partitions, a write, TEXT ─────────────────────────────────────────────────────────────────────────────
    with psycopg.connect(as_(SVC, "astryx-ear-svc"), autocommit=True) as s:
        m = E.maintain(s, ttl=3)
        want("maintain (as the svc role) creates today + 2 day partitions", len(m["created"]) == 3 and not m["dropped"], str(m))
        s.execute("INSERT INTO utterances (text, view, backend) VALUES ('sentinel words kept', 'test', 'none')")
        kind = s.execute("SELECT relkind FROM pg_class WHERE oid = 'utterances'::regclass").fetchone()[0]
        want("utterances is partitioned (relkind p) and the svc role can write it", kind == "p")
    err = refused(as_(AUD), "SELECT text FROM utterances")
    want("TEXT: the audit role is REFUSED SELECT on utterances (prevention, not a promise)",
         err and "permission denied" in err, str(err))

    # ── TTL ───────────────────────────────────────────────────────────────────────────────────────────────────
    with psycopg.connect(as_(AUD, "astryx-ear-census"), autocommit=True) as a:
        f0 = E.ttl_findings(a, ttl=3)
        want("TTL GREEN on fresh partitions (run as the audit role: catalog only)", f0 == [], str(f0))
        now = datetime.now(timezone.utc)
        lo = E._day(now) - timedelta(days=4)           # TTL 3 → a partition starting 4 days ago is one day past it
        old = f"utterances_p{lo:%Y%m%d}"
        with psycopg.connect(as_(SVC), autocommit=True) as s:
            s.execute(sql.SQL("CREATE TABLE {} PARTITION OF utterances FOR VALUES FROM ({}) TO ({})").format(
                sql.Identifier(old), sql.Literal(lo.isoformat()), sql.Literal((lo + timedelta(days=1)).isoformat())))
            s.execute("INSERT INTO utterances (ts, text) VALUES (%s, 'planted old words')", (lo + timedelta(hours=1),))
        f1 = E.ttl_findings(a, ttl=3)
        want("RED control: a partition planted one day past the TTL turns the arm RED, naming it",
             len(f1) == 1 and old in f1[0], str(f1))
        with psycopg.connect(as_(SVC), autocommit=True) as s:
            m = E.maintain(s, ttl=3)
            left = s.execute("SELECT count(*) FROM utterances").fetchone()[0]
            gone = s.execute("SELECT to_regclass(%s)", (old,)).fetchone()[0]
        want("maintain DROPs the expired partition (DROP, not DELETE: the table is gone, the fresh row is intact)",
             m["dropped"] == [old] and gone is None and left == 1, f"{m} left={left}")
        want("TTL GREEN again after the drop", E.ttl_findings(a, ttl=3) == [])
        with psycopg.connect(as_(SVC), autocommit=True) as s:
            s.execute("CREATE TABLE utterances_default PARTITION OF utterances DEFAULT")
        f2 = E.ttl_findings(a, ttl=3)
        want("RED control: a DEFAULT partition (unbounded retention) is RED", any("utterances_default" in x for x in f2), str(f2))
        with psycopg.connect(as_(SVC), autocommit=True) as s:
            s.execute("DROP TABLE utterances_default")

    # ── READERS ───────────────────────────────────────────────────────────────────────────────────────────────
    with psycopg.connect(make_conninfo(ADMIN, dbname=DB), autocommit=True) as e:
        e.execute("TRUNCATE login_audit")                  # a clean window: logins from here on
    admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(DOOR), sql.Identifier(OUT)))   # a member, not a door
    for _ in range(2):
        with psycopg.connect(as_(SVC, "astryx-ear-svc"), autocommit=True):
            pass
    with psycopg.connect(make_conninfo(out_dsn, application_name="astryx-ear-svc"), autocommit=True):
        pass                                              # an outsider CLAIMING to be the ear service
    doors, auds = {SVC: "door 4"}, {AUD: "auditor"}
    with psycopg.connect(as_(AUD, "astryx-ear-census"), autocommit=True) as a:
        res = E.reader_census(a, doors=doors, auditors=auds, evt=EVT)
        want("the login trigger exists and is enabled: no LOUD", res["loud"] == [], str(res["loud"]))
        roles = {o["role"]: o for o in res["outside"]}
        want("the spoofing outsider is reported, graded on session_user (its claimed app name quoted)",
             OUT in roles and roles[OUT]["app_claimed"] == "astryx-ear-svc", str(res["outside"]))
        want("the door's own logins are not reported", SVC not in roles, str(res["outside"]))
        n_svc = a.execute("SELECT count(*) FROM login_audit WHERE session_role = %s", (SVC,)).fetchone()[0]
        want("one-shot logins are recorded once each (2 svc connections → 2 rows)", n_svc == 2, str(n_svc))
        txt = E.census_text(res)
        want("the owner report names the outsider and says detection-grade", txt and OUT in txt and "detection" in txt, str(txt))
        res2 = E.reader_census(a, after_id=res["last_id"], doors=doors, auditors=auds, evt=EVT)
        want("the census is incremental (after_id): nothing new → no outsiders", res2["outside"] == [], str(res2))
    with psycopg.connect(make_conninfo(ADMIN, dbname=DB), autocommit=True) as e:
        e.execute(sql.SQL("ALTER EVENT TRIGGER {} DISABLE").format(sql.Identifier(EVT)))
    with psycopg.connect(as_(AUD), autocommit=True) as a:
        loud = E.reader_census(a, doors=doors, auditors=auds, evt=EVT)["loud"]
    want("RED control: the trigger DISABLED → LOUD", any("DISABLED" in x for x in loud), str(loud))
    with psycopg.connect(make_conninfo(ADMIN, dbname=DB), autocommit=True) as e:
        e.execute(sql.SQL("DROP EVENT TRIGGER {}").format(sql.Identifier(EVT)))
    with psycopg.connect(as_(AUD), autocommit=True) as a:
        loud = E.reader_census(a, doors=doors, auditors=auds, evt=EVT)["loud"]
    want("RED control: the trigger DROPPED → LOUD", any("MISSING" in x for x in loud), str(loud))
    E.apply(ADMIN, db=DB, door=DOOR, svc=SVC, audit=AUD, evt=EVT, pgpass=PGPASS)
    with psycopg.connect(as_(AUD), autocommit=True) as a:
        loud = E.reader_census(a, doors=doors, auditors=auds, evt=EVT)["loud"]
    want("re-apply restores the trigger (enabled)", loud == [], str(loud))
finally:
    reap(admin, mine=True)
    admin.close()
    PGPASS.unlink(missing_ok=True)
    TMP.rmdir()

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
sys.exit(1 if fails else 0)
