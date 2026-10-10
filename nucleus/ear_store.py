#!/usr/bin/env python3
"""astryx · ear_store — hearing's EAR STORE (plan-8674 S1, D1 + D2's reader census).

TIER IS WHERE THE BYTES LIVE. The raw room transcript is human-personal tier by default (an always-on mic hears
family, health and career talk). So it does not live in the org database with a "personal" flag on it: it lives in
a SEPARATE database, `astryx_ear`. Both copiers we have (backup.sh, branch_check_prep.py) dump ONE database by name,
so a copier that forgets the ear doesn't copy it: omission is the safe polarity (abstractor-4 #42048, M1).

  utterances    partitioned BY DAY (UTC). Retention = DROP the expired partition, never DELETE. Owned by the ear
                service's role, which is the only writer and the only maintainer (it creates and drops partitions).
  login_audit   one row per LOGIN to this database, written by a LOGIN EVENT TRIGGER (PG 17+). The reader census
                reads it, graded on session_user; application_name is reported AS CLAIMED (anyone can set it).

ROLES (all NOSUPERUSER, created here; passwords go to ~/.pgpass only, never .env, never printed):
  astryx_ear_door   NOLOGIN group; the ONE role holding CONNECT (ensure_private_db's `cleared`). Doors join it.
  astryx_ear_svc    door (4), the ear service: LOGIN, owns `utterances`.
  astryx_ear_audit  the census/TTL checker: LOGIN, SELECT on login_audit ONLY. It holds no privilege on utterances,
                    so "the checker never reads text" is PREVENTION (a privilege), not a promise in the code.

GRADES (stated, never rounded up):
  - The org's resident DSN role is SUPERUSER (M2). A separate database is NOT an access boundary against residents.
    A resident that connects here reads everything. The census DETECTS that (durably, via the login trigger); it
    does not prevent it. A superuser can also disable the trigger or delete audit rows: the census then reports the
    trigger missing/disabled (LOUD), but deleted rows are gone. Detection-grade.
  - DROP is LOGICAL erasure at TTL. Dropped tuples survive in recycled WAL segments until overwritten (M3). There is
    no secure-delete claim.
  - genesis-pg publishes 5432 on the LAN (plan-5497's pending unbind): this database is reachable from the LAN WITH
    CREDENTIALS, not host-only.

    venv/bin/python -m nucleus.ear_store apply      # idempotent; the S1 DEPLOYMENT act (superuser DSN)
    venv/bin/python -m nucleus.ear_store ttl        # catalog-only TTL arm      0 green, 1 RED, 77 BLIND
    venv/bin/python -m nucleus.ear_store readers    # reader census (owner-only) 0 green, 1 LOUD, 77 BLIND

Names are parameters so the oracle (tests/test_ear_store.py) runs this exact code on scratch roles and a scratch
database; production passes none.
"""
from __future__ import annotations

import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from psycopg import sql

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

EAR_DB = "astryx_ear"
DOOR = "astryx_ear_door"
SVC = "astryx_ear_svc"
AUDIT = "astryx_ear_audit"
EVT = "ear_login_audit"
EXIT_BLIND = 77

# D2: the named doors out of astryx_ear, by LOGIN ROLE (session_user). S1 ships door (4) only; doors (1)-(3) arrive
# with S2/S3/S5 and are added HERE, each with its own role. AUDITORS log in but hold no privilege on utterances.
DOORS = {SVC: "door 4: the ear service (writer)"}
AUDITORS = {AUDIT: "census/TTL checker (no privilege on utterances)"}


def ttl_days() -> int:
    """Retention in days. SHORT by rule (a): default 3, floor 1. One knob, read by the writer and the arm alike."""
    try:
        return max(1, int(os.environ.get("EAR_TTL_DAYS") or _env("EAR_TTL_DAYS") or 3))
    except ValueError:
        return 3


def _env(key: str) -> str:
    f = REPO / ".env"
    if f.is_file():
        for line in f.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return ""


def admin_dsn() -> str:
    return os.environ.get("ASTRYX_DSN") or _env("ASTRYX_DSN")


def role_dsn(role: str, db: str = EAR_DB, base: str | None = None, app: str | None = None) -> str:
    """The DSN `role` uses for `db`: the org DSN's host and port, NO password (libpq reads ~/.pgpass)."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    d = conninfo_to_dict(base or admin_dsn())
    d.pop("password", None)
    d.update(user=role, dbname=db)
    if app:
        d["application_name"] = app
    return make_conninfo(**d)


# ── apply: the deployment act ─────────────────────────────────────────────────────────────────────────────────
def _schema(svc: str, audit: str, evt: str) -> list:
    I, L = sql.Identifier, sql.Literal
    return [
        sql.SQL("""CREATE TABLE IF NOT EXISTS utterances (
  id      bigint GENERATED ALWAYS AS IDENTITY,
  ts      timestamptz NOT NULL DEFAULT now(),
  text    text NOT NULL,
  speaker text NOT NULL DEFAULT 'unknown',     -- ROUGH attribution, labelled as such; never used for authority
  view    text,                                -- the observatory view the mic was on
  dur_ms  int,
  stt_ms  int,
  backend text,
  PRIMARY KEY (ts, id)
) PARTITION BY RANGE (ts)"""),
        sql.SQL("ALTER TABLE utterances OWNER TO {}").format(I(svc)),
        sql.SQL("REVOKE ALL ON utterances FROM PUBLIC"),
        sql.SQL("""CREATE TABLE IF NOT EXISTS login_audit (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts            timestamptz NOT NULL DEFAULT now(),
  session_role  text NOT NULL,                 -- session_user: what the census GRADES on
  app_claimed   text,                          -- application_name: reported AS CLAIMED, never trusted
  client_addr   inet,
  backend_pid   int
)"""),
        sql.SQL("REVOKE ALL ON login_audit FROM PUBLIC"),
        sql.SQL("GRANT SELECT ON login_audit TO {}").format(I(audit)),
        # SECURITY DEFINER (owned by the applying superuser) so a login needs no INSERT grant. FAIL-OPEN for the
        # login itself: an audit write that errors must not lock everyone out of the ear (rule (e): the ear never
        # blocks). The miss is a WARNING in the server log; the census's row-gap is the honest bound.
        sql.SQL("""CREATE OR REPLACE FUNCTION ear_login_audit() RETURNS event_trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $f$
BEGIN
  BEGIN
    INSERT INTO public.login_audit (session_role, app_claimed, client_addr, backend_pid)
    VALUES (session_user, current_setting('application_name', true), inet_client_addr(), pg_backend_pid());
  EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'ear login audit write failed (%)', SQLSTATE;
  END;
END $f$"""),
        sql.SQL("REVOKE ALL ON FUNCTION ear_login_audit() FROM PUBLIC"),
        sql.SQL("""DO $d$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_event_trigger WHERE evtname = {}) THEN
    EXECUTE format('CREATE EVENT TRIGGER %I ON login EXECUTE FUNCTION ear_login_audit()', {});
  END IF;
END $d$""").format(L(evt), L(evt)),
        # ENABLE ALWAYS: it fires under session_replication_role = replica too.
        sql.SQL("ALTER EVENT TRIGGER {} ENABLE ALWAYS").format(I(evt)),
    ]


def _role(admin, name: str, login: bool) -> str | None:
    """Create if absent (returns the new password for a LOGIN role); never ALTER an existing role."""
    from nucleus.people_gate import ROLE_SQL
    if admin.execute(ROLE_SQL, (name,)).fetchone() is not None:
        return None
    pw = secrets.token_hex(24) if login else None
    # the VERIFIER goes over the wire, never the plaintext (a statement log would otherwise hold it)
    ver = admin.pgconn.encrypt_password(pw.encode(), name.encode(), b"scram-sha-256").decode() if login else None
    admin.execute(sql.SQL("CREATE ROLE {} " + ("LOGIN PASSWORD {}" if login else "NOLOGIN")
                          + " NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
                  .format(sql.Identifier(name), *([sql.Literal(ver)] if login else [])))
    return pw


def _pgpass_add(path: Path, host: str, port: str, db: str, role: str, pw: str) -> None:
    """Append one exact-match entry (host literal, BC-a). Mode 0600 kept/forced. Never prints the value."""
    line = f"{host}:{port}:{db}:{role}:{pw}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def apply(admin_dsn_: str, db: str = EAR_DB, door: str = DOOR, svc: str = SVC, audit: str = AUDIT,
          evt: str = EVT, pgpass: Path | None = None) -> dict:
    """Idempotent. As the DSN's superuser: roles, the zero-window database, its schema, the login trigger.
    A LOGIN role created NOW gets a random password written to `pgpass` (default ~/.pgpass) and nowhere else."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from nucleus.people_gate import ensure_private_db
    d = conninfo_to_dict(admin_dsn_)
    host, port = d.get("host", "127.0.0.1"), str(d.get("port", "5432"))
    pgpass = pgpass or Path(os.environ.get("PGPASSFILE") or Path.home() / ".pgpass")
    out = {"created_db": False, "new_roles": []}
    with psycopg.connect(admin_dsn_, autocommit=True) as a:
        _role(a, door, login=False)
        for r in (svc, audit):
            pw = _role(a, r, login=True)
            if pw:
                _pgpass_add(pgpass, host, port, db, r, pw)
                out["new_roles"].append(r)
            a.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(door), sql.Identifier(r)))
        out["created_db"] = ensure_private_db(a, name=db, cleared=door, preload=None)
    with psycopg.connect(make_conninfo(admin_dsn_, dbname=db), autocommit=True) as e:
        e.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        e.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}, {}").format(sql.Identifier(svc), sql.Identifier(audit)))
        e.execute(sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(sql.Identifier(svc)))   # its partitions
        for stmt in _schema(svc, audit, evt):
            e.execute(stmt)
    return out


# ── retention: the writer's maintenance (runs as the svc role, the table's owner) ─────────────────────────────
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
    """Create day partitions [today, today+ahead]; DROP every attached partition whose lower bound is older than
    now - ttl days. Conservative: a day partition goes as soon as its START passes the TTL, so text is kept at most
    ttl days, never longer (and up to one day less). DROP, never DELETE."""
    ttl = ttl or ttl_days()
    now = now or datetime.now(timezone.utc)
    have = {n for n, _, _ in partitions(conn)}
    made, dropped = [], []
    for k in range(ahead + 1):
        lo = _day(now) + timedelta(days=k)
        name = f"utterances_p{lo:%Y%m%d}"
        if name not in have:
            conn.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} PARTITION OF utterances FOR VALUES FROM ({}) TO ({})")
                         .format(sql.Identifier(name), sql.Literal(lo.isoformat()),
                                 sql.Literal((lo + timedelta(days=1)).isoformat())))
            made.append(name)
    cutoff = now - timedelta(days=ttl)
    for name, lo, _ in partitions(conn):
        if lo is None or lo < cutoff:
            conn.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(name)))
            dropped.append(name)
    return {"created": made, "dropped": dropped}


# ── arm: catalog-only TTL ─────────────────────────────────────────────────────────────────────────────────────
def ttl_findings(conn, ttl: int | None = None, now: datetime | None = None) -> list[str]:
    """RED sentences. The OLDEST attached partition's lower bound must be >= now - ttl. A partition with no
    parseable lower bound (DEFAULT, MINVALUE) is RED: it can hold text of any age. Reads pg_catalog only."""
    ttl = ttl or ttl_days()
    now = now or conn.execute("SELECT now()").fetchone()[0]
    cutoff = now - timedelta(days=ttl)
    out = []
    if conn.execute("SELECT to_regclass('public.utterances')").fetchone()[0] is None:
        return ["utterances table is missing"]
    if conn.execute("SELECT relkind FROM pg_class WHERE oid = 'public.utterances'::regclass").fetchone()[0] != "p":
        return ["utterances is not partitioned: retention-by-DROP is impossible"]
    for name, lo, bound in partitions(conn):
        if lo is None:
            out.append(f"partition {name} has no dated lower bound ({bound}): unbounded retention")
        elif lo < cutoff:
            out.append(f"partition {name} starts {lo:%Y-%m-%d %H:%M}Z, older than the {ttl}-day TTL "
                       f"(cutoff {cutoff:%Y-%m-%d %H:%M}Z)")
    return out


# ── arm: the reader census (D2, a1 BC-2 + a3 BC-2) ───────────────────────────────────────────────────────────
def trigger_findings(conn, evt: str = EVT) -> list[str]:
    """LOUD unless the login trigger exists, is ON login, is enabled (O origin / A always), and calls our function."""
    row = conn.execute("SELECT evtevent, evtenabled, evtfoid::regproc::text FROM pg_event_trigger WHERE evtname = %s",
                       (evt,)).fetchone()
    if row is None:
        return [f"LOUD: login event trigger {evt} is MISSING: the census is blind to every new reader"]
    event, enabled, fn = row
    out = []
    if event != "login":
        out.append(f"LOUD: event trigger {evt} fires on {event}, not login")
    if enabled not in ("O", "A"):
        out.append(f"LOUD: login event trigger {evt} is DISABLED (evtenabled={enabled}): the census is blind")
    if fn.split(".")[-1] != "ear_login_audit":
        out.append(f"LOUD: event trigger {evt} calls {fn}, not ear_login_audit")
    return out


def reader_census(conn, after_id: int = 0, doors: dict | None = None, auditors: dict | None = None,
                  evt: str = EVT) -> dict:
    """Readers OUTSIDE the declared doors since audit row `after_id`. Graded on session_role (session_user);
    app_claimed is reported as claimed. {'loud': [...], 'outside': [...], 'last_id': n, 'logins': n}."""
    doors = DOORS if doors is None else doors
    auditors = AUDITORS if auditors is None else auditors
    allowed = set(doors) | set(auditors)
    loud = trigger_findings(conn, evt)
    if conn.execute("SELECT to_regclass('public.login_audit')").fetchone()[0] is None:
        return {"loud": loud + ["LOUD: login_audit table is MISSING"], "outside": [], "last_id": after_id, "logins": 0}
    rows = conn.execute(
        "SELECT session_role, coalesce(app_claimed, ''), count(*), min(ts), max(ts), max(id) "
        "FROM login_audit WHERE id > %s GROUP BY 1, 2 ORDER BY 4", (after_id,)).fetchall()
    outside = [{"role": r, "app_claimed": a, "logins": n, "first": f.isoformat(), "last": l.isoformat()}
               for r, a, n, f, l, _ in rows if r not in allowed]
    last = max([after_id] + [m for *_, m in rows])
    return {"loud": loud, "outside": outside, "last_id": last, "logins": sum(n for _, _, n, *_ in rows)}


def census_text(res: dict) -> str | None:
    """The owner-only report body, or None when there is nothing to say."""
    parts = list(res["loud"])
    for o in res["outside"]:
        parts.append(f"{o['role']} connected to {EAR_DB} {o['logins']}x ({o['first'][:16]} .. {o['last'][:16]}), "
                     f"application_name claimed '{o['app_claimed']}': NOT one of the declared doors")
    if not parts:
        return None
    return ("hearing reader census (astryx_ear, detection-grade; graded on session_user): " + " | ".join(parts))


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _audit_conn():
    import psycopg
    return psycopg.connect(role_dsn(AUDIT, app="astryx-ear-census"), autocommit=True, connect_timeout=5)


def main(argv) -> int:
    import psycopg
    verb = argv[1] if len(argv) > 1 else ""
    if verb == "apply":
        dsn = admin_dsn()
        if not dsn:
            print("ear_store: no ASTRYX_DSN")
            return 1
        r = apply(dsn)
        print(f"ear_store: applied (database created now: {r['created_db']}; new roles: {r['new_roles'] or 'none'}"
              f"{'; passwords written to ~/.pgpass' if r['new_roles'] else ''})")
        return 0
    if verb in ("ttl", "readers"):
        try:
            c = _audit_conn()
        except psycopg.Error as e:
            print(f"ear_store {verb}: BLIND, can't connect as {AUDIT} ({type(e).__name__}): not deployed, or no pgpass")
            return EXIT_BLIND
        with c:
            if verb == "ttl":
                f = ttl_findings(c)
                for x in f:
                    print(f"  RED {x}")
                print(f"ear_store ttl: {'RED' if f else 'GREEN'} ({len(partitions(c))} partitions, ttl {ttl_days()}d)")
                return 1 if f else 0
            res = reader_census(c, after_id=int(argv[2]) if len(argv) > 2 else 0)
            t = census_text(res)
            print(t or f"ear_store readers: GREEN ({res['logins']} logins, all through declared doors)")
            return 1 if t else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
