"""The ONE fixture applier (goal 4243: #22110, #22112, #22115). An oracle that needs a schema calls it:

    from nucleus.sqlguard.fixture import fixture_db
    with fixture_db() as fx:                     # a throwaway DATABASE of its own (BC-a)
        conn = psycopg.connect(fx["dsn"])        # schema.sql applied WHOLE, every relation stamped

WHY A DATABASE. pg_notify is database-wide (#22114): schema.sql's triggers would ring live listeners, and a
bridge would post a fixture step id's REAL step into the owner's chat. A throwaway database also keeps the
file's unqualified DROP VIEWs away from production views by construction.

WHY WHOLE. This is one writer of schema.sql's meaning. It applies the same bytes init.sh applies, including the
ALTER-only columns that block extraction drops (steps.turn_id, messages.delivery, goals.funded_by, ...).

THE STAMP. Every relation gets COMMENT ON TABLE 'astryx-ddl:<file_sha>:<sig_sha>'. sig_sha hashes the sorted
(attname, type, default expr, not-null) set. stamp_valid() recomputes BOTH at credit time: the file sha must
equal the CURRENT schema.sql, and the signature must equal the relation's shape NOW. So a DROP+re-CREATE or a
later ALTER … DROP DEFAULT fails. Graded DETECTION: a same-uid actor can write the comment by hand.

run id: check.sh exports ASTRYX_SQLGUARD_RUN itself (BC-b). A standalone oracle self-ids, and always drops its
database in finally, so the leak arm only ever has to look for this run's prefix.
"""
import contextlib
import hashlib
import itertools
import os
import time
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

REPO = Path(os.environ.get("ASTRYX_SQLGUARD_ROOT") or Path(__file__).resolve().parents[2]).resolve()
SCHEMA = REPO / "nucleus" / "schema.sql"
PREFIX = "astryx_fx_"
STAMP = "astryx-ddl:"
_n = itertools.count()
_side = {}                                   # dbname -> connection (stamp checks, never the caller's)


def estate_absent() -> str | None:
    """Why live_dsn() can't answer on this tree, or None. Absence only: an unreadable .env still raises (loud)."""
    env = REPO / ".env"
    if not env.is_file():
        return ".env absent (a committed-only tree has no live DSN)"
    if not any(l.startswith("ASTRYX_DSN=") for l in env.read_text().splitlines()):
        return ".env has no ASTRYX_DSN line"
    return None


def live_dsn() -> str:
    return next(l.split("=", 1)[1].strip() for l in (REPO / ".env").read_text().splitlines()
                if l.startswith("ASTRYX_DSN="))


def file_sha() -> str:
    return hashlib.sha256(SCHEMA.read_bytes()).hexdigest()


def run_id() -> str:
    rid = os.environ.get("ASTRYX_SQLGUARD_RUN")
    if not rid:                                    # standalone: self-id (and self-clean in finally)
        rid = f"sa{os.getpid()}x{int(time.time())}"
        os.environ["ASTRYX_SQLGUARD_RUN"] = rid
    return rid


SIG_SQL = ("SELECT a.attname, format_type(a.atttypid, a.atttypmod), "
           "coalesce(pg_get_expr(d.adbin, d.adrelid), ''), a.attnotnull "
           "FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
           "WHERE a.attrelid=%s AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attname")


def signature(conn, oid: int) -> str:
    rows = conn.execute(SIG_SQL, (oid,)).fetchall()
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def _stamp_all(conn, sha: str) -> int:
    rels = conn.execute("SELECT c.oid, quote_ident(n.nspname)||'.'||quote_ident(c.relname) FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p','v','m') "
                        "AND n.nspname NOT IN ('pg_catalog','information_schema','ag_catalog','topology') "
                        "AND n.nspname NOT LIKE 'pg_toast%%'").fetchall()
    for oid, qname in rels:
        kind = "VIEW" if conn.execute("SELECT relkind FROM pg_class WHERE oid=%s",
                                      (oid,)).fetchone()[0] in ("v", "m") else "TABLE"
        # COMMENT takes no bind parameters; the value is our own hex, so it's safe to inline.
        conn.execute(f"COMMENT ON {kind} {qname} IS '{STAMP}{sha}:{signature(conn, oid)}'")
    return len(rels)


@contextlib.contextmanager
def fixture_db():
    """A fresh database, schema.sql applied whole, every relation stamped; dropped WITH (FORCE) in finally."""
    name = f"{PREFIX}{run_id()}_{os.getpid()}_{next(_n)}".lower()
    admin = psycopg.connect(live_dsn(), autocommit=True)
    t0 = time.monotonic()
    try:
        admin.execute(f'CREATE DATABASE "{name}"')
        dsn = make_conninfo(live_dsn(), dbname=name)
        sha = file_sha()
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(SCHEMA.read_text())          # the WHOLE file, the same bytes init.sh applies
            n = _stamp_all(c, sha)
        yield {"dbname": name, "dsn": dsn, "file_sha": sha, "relations": n,
               "apply_s": round(time.monotonic() - t0, 3)}
    finally:
        try:
            s = _side.pop(name, None)
            if s is not None:
                s.close()
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            admin.close()


_REL_SQL = ("SELECT c.oid, obj_description(c.oid, 'pg_class') FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p','v','m') "
            "AND n.nspname NOT IN ('pg_catalog','information_schema','ag_catalog','topology') "
            "AND n.nspname NOT LIKE 'pg_toast%%'")
_ALLSIG_SQL = ("SELECT a.attrelid, a.attname, format_type(a.atttypid, a.atttypmod), "
               "coalesce(pg_get_expr(d.adbin, d.adrelid), ''), a.attnotnull "
               "FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
               "WHERE a.attrelid = ANY(%s) AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attrelid, a.attname")


def _side_conn(dbname: str):
    """The observer connection, BOUNDED (a3 D-C). pg_get_expr needs AccessShare on the relation, and a caller that
    holds uncommitted DDL (AccessExclusive) would block it forever. The caller is stuck inside the shim waiting on
    us, so that's a cross-client deadlock Postgres can't detect. With lock_timeout, the read gives up in 250ms,
    and a timeout means NO CREDIT (the safe direction). It's also the RIGHT answer: a side connection sees only
    the COMMITTED shape, so it can't vouch for an uncommitted one anyway."""
    c = _side.get(dbname)
    if c is None or c.closed:
        c = _side[dbname] = psycopg.connect(make_conninfo(live_dsn(), dbname=dbname), autocommit=True)
        c.execute("SET lock_timeout = '250ms'")
        c.execute("SET statement_timeout = '2s'")
    return c


def db_stamp_map(dbname: str) -> dict:
    """{oid: stamp-valid NOW} for every org relation in a fixture DB. Two catalog queries, no cache.

    It is recomputed at EVERY credit (a3 D-A): an ALTER keeps the OID, so any cache keyed by (db, oid) would go
    on crediting the altered relation, which is #3's hiding place re-opened. A process-local cache also can't see
    DDL run by ANOTHER process against the same fixture (a hook under test), so correctness here comes by
    construction, not by invalidation. The signature is computed exactly as signature() computes it (same
    columns, order and repr), so the stamper and the checker can't drift."""
    try:
        c = _side_conn(dbname)
        rels = c.execute(_REL_SQL).fetchall()
        rows = {}
        for relid, *attr in c.execute(_ALLSIG_SQL, ([o for o, _ in rels],)).fetchall():
            rows.setdefault(relid, []).append(tuple(attr))
        cur_sha, out = file_sha(), {}
        for oid, text in rels:
            ok = bool(text) and text.startswith(STAMP)
            if ok:
                sha, _, sig = text[len(STAMP):].partition(":")
                ok = sha == cur_sha and sig == hashlib.sha256(repr(rows.get(oid, [])).encode()).hexdigest()
            out[oid] = ok
        return out
    except Exception:
        return {}


def stamp_valid(dbname: str, oid: int) -> bool:
    """At CREDIT time: the relation carries a stamp whose file sha is the CURRENT schema.sql's, and whose
    signature equals the relation's shape now. Any failure (no comment, stale sha, altered shape, unreadable)
    is False, which gives no credit: the safe direction."""
    try:
        c = _side_conn(dbname)
        row = c.execute("SELECT obj_description(%s, 'pg_class')", (oid,)).fetchone()
        text = row[0] if row else None
        if not text or not text.startswith(STAMP):
            return False
        sha, _, sig = text[len(STAMP):].partition(":")
        return sha == file_sha() and sig == signature(c, oid)
    except Exception:
        return False
