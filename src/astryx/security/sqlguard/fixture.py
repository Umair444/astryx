"""The ONE fixture applier (goal 4243: #22110, #22112, #22115). An oracle that needs a schema calls it:

    from astryx.security.sqlguard.fixture import fixture_db
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
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__)))))))
from astryx.paths import repo_root  # noqa: E402
from astryx import config, paths  # noqa: E402
import contextlib
import hashlib
import itertools
import os
import time
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

REPO = Path(os.environ.get("ASTRYX_SQLGUARD_ROOT") or repo_root(__file__)).resolve()
SCHEMA = REPO / "src" / "astryx" / "sql" / "schema.sql"
PREFIX = "astryx_fx_"
STAMP = "astryx-ddl:"
_n = itertools.count()
_side = {}                                   # dbname -> connection (stamp checks, never the caller's)

# ── THE REAPER (seed #38669): a SIGKILLed oracle skips the `finally` that drops its database, so ~30 oracles each
# leaked their astryx_fx_* DB on a kill, and nothing collected them. Every fixture_db() entry now reaps the dead.
# KEEP IS THE DEFAULT. A database is dropped only when its OWNER STAMP proves its creator is gone:
#   - the stamp is a COMMENT ON DATABASE written at creation: pid, the pid NAMESPACE inode and a host hash. A pid
#     alone is a lie across namespaces: under branch_check's bwrap --unshare-pid a run's pid is a namespace pid
#     (a3 #32897 W1), so the host would see a LIVE sandboxed run as dead, and a sandboxed reaper would see every
#     host run as dead. So a stamp from another namespace or host is never judged, only kept;
#   - no stamp (a legacy name, or the instant between CREATE and COMMENT) → KEEP. The name is never trusted for the
#     verdict: three historical spellings exist (sa<pid>x<epoch>, r<epoch>x<run>, a plain run id), and seed's first
#     parser misread one into a "dead" pid that was a LIVE run. The name's tail pid is parsed for the REPORT only;
#   - pid alive, or reused by another process → KEEP (reuse fails safe). PermissionError means alive.
OWNER = "astryx-fixture-owner:"


def _pidns() -> str:
    try:
        return os.readlink("/proc/self/ns/pid").split("[", 1)[1].rstrip("]")
    except (OSError, IndexError):
        return ""                                    # unknowable → stamps carry "", and "" is never judged


def _host() -> str:
    import socket
    return hashlib.sha256(socket.gethostname().encode()).hexdigest()[:12]


def owner_stamp(pid: int | None = None) -> str:
    return f"{OWNER}pid={pid or os.getpid()};pidns={_pidns()};host={_host()}"


def _parse_stamp(comment: str | None) -> dict | None:
    if not comment or not comment.startswith(OWNER):
        return None
    try:
        kv = dict(p.split("=", 1) for p in comment[len(OWNER):].split(";"))
        return {"pid": int(kv["pid"]), "pidns": kv["pidns"], "host": kv["host"]}
    except (ValueError, KeyError):
        return None


def name_pid(name: str) -> int | None:
    """The pid in a fixture name's shared tail `_<pid>_<n>`, for REPORTING only (never a verdict)."""
    import re
    m = re.search(r"_(\d+)_\d+$", name)
    return int(m.group(1)) if m else None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError, ValueError):
        return True


def verdict(name: str, comment: str | None, alive=_alive, here: tuple | None = None) -> tuple[str, str]:
    """('reap'|'keep', why) for one astryx_fx_* database. Pure given `alive` and `here` = (pidns, host)."""
    pidns, host = here or (_pidns(), _host())
    st = _parse_stamp(comment)
    if st is None:
        return "keep", f"no owner stamp (name tail pid {name_pid(name)}, never trusted)"
    if not st["pidns"] or st["pidns"] != pidns or st["host"] != host:
        return "keep", "stamped by another pid namespace or host: its pid means nothing here"
    if alive(st["pid"]):
        return "keep", f"creator pid {st['pid']} is alive"
    return "reap", f"creator pid {st['pid']} is gone"


def _drop(admin, name: str) -> str:
    """DROP a fixture database; which path ran ("force" | "plain"). `WITH (FORCE)` must terminate EVERY backend on it,
    and on PG 18 (our 18.6) terminating an AUTOVACUUM worker needs pg_signal_autovacuum_worker, which a branch_check
    run role doesn't hold: a teardown that met autovacuum failed InsufficientPrivilege, at random (steward #55022).
    A PLAIN DROP signals autovacuum workers on the target itself and waits for them, so the refusal retries
    plain. Not the grant: that would let every run role interrupt autovacuum on production databases. Any OTHER
    refusal (another session connected, a template) propagates unchanged, as before."""
    q = '"{}"'.format(name.replace('"', '""'))
    try:
        admin.execute(f"DROP DATABASE IF EXISTS {q} WITH (FORCE)")
        return "force"
    except psycopg.errors.InsufficientPrivilege:
        admin.execute(f"DROP DATABASE IF EXISTS {q}")
        return "plain"


def reap(admin, keep: str = "") -> list[tuple[str, str, str]]:
    """Drop every astryx_fx_* database whose verdict is 'reap'. Never raises: a reaper that fails keeps."""
    out = []
    try:
        rows = admin.execute("SELECT datname, shobj_description(oid, 'pg_database') FROM pg_database "
                             "WHERE starts_with(datname, %s)", (PREFIX,)).fetchall()
    except psycopg.Error:
        return out
    for name, comment in rows:
        if name == keep:            # belt and braces: fixture_db reaps BEFORE its CREATE, so its own name is never
            continue                # listed yet (a3 #39195 M7: dropping this line is an EQUIVALENT mutant)
        act, why = verdict(name, comment)
        if act == "reap":
            try:
                _drop(admin, name)
            except psycopg.Error as e:
                act, why = "keep", f"drop refused ({type(e).__name__}): {why}"
        out.append((name, act, why))
    return out


def url(dsn: str) -> str:
    """The same database as a postgresql:// URL. node-pg and asyncpg take a URL, not psycopg's key=value
    conninfo (forge #23806: every asyncpg oracle was regex-deriving one)."""
    d = conninfo_to_dict(dsn)
    auth = quote(d.get("user", ""), safe="") + (":" + quote(d["password"], safe="") if d.get("password") else "")
    db = quote(d.get("dbname", ""), safe="")
    if d.get("host", "").startswith("/"):
        # a UNIX-SOCKET directory (branch_check's sandbox, where the network is unshared): it can't sit in the
        # authority. `@/dir:5432/db` parses as an empty host, and asyncpg then tries localhost TCP (first e2e #33638).
        q = f"?host={quote(d['host'], safe='/')}" + (f"&port={d['port']}" if d.get("port") else "")
        return f"postgresql://{auth + '@' if auth else ''}/{db}{q}"
    host = d.get("host", "") + (f":{d['port']}" if d.get("port") else "")
    return f"postgresql://{auth + '@' if auth else ''}{host}/{db}"


class FixtureUnavailable(Exception):
    """The ENVIRONMENT can't host a fixture: no .env/DSN, the server unreachable, or a role that can't CREATE
    DATABASE. A consumer that means "skip when there's no database" catches THIS and nothing wider: a broken
    schema.sql, a bad extra DDL or a stamp error propagates as ITSELF, so it reads RED, not "not run". A broad
    `except Exception: skip` had turned a planted schema SyntaxError into UNVERIFIED (a2 #31526, a1 #31528)."""


def live_dsn() -> str:
    """The org's DSN (the .env FILE: the admin connection is the org's own, never a fixture's), through the ONE resolver.
    The .env is the ASTRYX_SQLGUARD_ROOT tree's when one is named (as REPO's was), else the org's estate.
    ASTRYX_FIXTURE_ADMIN_DSN, when set, is that DSN passed by env instead: a worktree holds no .env, and the live one is
    never linked into it (seed #59548). It's a name of its own, never ASTRYX_DSN, which an oracle binds to a fixture;
    a fixture DSN in it is refused loud, not used as the admin."""
    v = os.environ.get("ASTRYX_FIXTURE_ADMIN_DSN")
    if v:
        from astryx import orgs
        if orgs.is_fixture(v):
            raise ValueError("ASTRYX_FIXTURE_ADMIN_DSN names a fixture database: the admin connection is the org's own")
        return v
    base = REPO if os.environ.get("ASTRYX_SQLGUARD_ROOT") else paths.estate(__file__)
    return config.dsn(base / ".env", env_first=False)


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
# format_type() and pg_get_expr() render a name relative to the CALLER's search_path (`graphid` vs
# `ag_catalog.graphid`, `nextval('s'::regclass)` vs `nextval('sp.s'::regclass)`). So the signer and the checker
# BOTH read signatures under this one fixed path (a3 #50071), never whatever path a DDL extra or a DSN left behind.
SIG_PATH = "SET LOCAL search_path = pg_catalog"


def signature(conn, oid: int) -> str:
    """PRECONDITION: `conn` is on SIG_PATH (the signer's SET LOCAL, or _side_conn's pin). Any other path renders
    names differently, and the signature then silently disagrees with one taken on SIG_PATH (a3 #51125)."""
    rows = conn.execute(SIG_SQL, (oid,)).fetchall()
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def _stamp_all(conn, sha: str) -> int:
    # SET LOCAL ends at the end of the TOP-LEVEL transaction. fixture_db's applier is autocommit, so this opens a real
    # transaction and the pin ends with it. Inside a caller's transaction this would be a savepoint, and the pin
    # would outlive it into the caller's session (a3 #51125).
    with conn.transaction():
        conn.execute(SIG_PATH)
        return _stamp_rels(conn, sha)


def _stamp_rels(conn, sha: str) -> int:
    rels = conn.execute("SELECT c.oid, quote_ident(n.nspname)||'.'||quote_ident(c.relname) " + _ORG_RELS).fetchall()
    for oid, qname in rels:
        kind = "VIEW" if conn.execute("SELECT relkind FROM pg_class WHERE oid=%s",
                                      (oid,)).fetchone()[0] in ("v", "m") else "TABLE"
        # COMMENT takes no bind parameters; the value is our own hex, so it's safe to inline.
        conn.execute(f"COMMENT ON {kind} {qname} IS '{STAMP}{sha}:{signature(conn, oid)}'")
    return len(rels)


def fresh_name() -> str:
    """A fixture name, unique per process: PREFIX + `<run>_<pid>_<n>` (the shared tail name_pid() parses). A database a
    caller makes OUTSIDE fixture_db but hands to a Batch (the parity oracle's birth database) takes it too, so batch
    members never collide and the reaper's prefix covers them (a4 #57168 §3)."""
    return f"{PREFIX}{run_id()}_{os.getpid()}_{next(_n)}".lower()


# ── THE LIFETIME SEAM (plan-11253 S3, a4 #57171; ONE seam with plan-11254, a4 #57439 §1). fixture_db(lifetime=...):
#   "immediate" (the DEFAULT, every existing caller): dropped at block exit, as always. Several suites assert "gone at
#               exit" (the reaper and sigpath arms), so flipping the default is 11254's, behind its own gate.
#   "batch"     (opt-in, with batch=): NOT dropped at block exit. The name is enrolled in the Batch, which drops every
#               member at its close, CONCURRENTLY. Each DROP forces a checkpoint and one admin session is serial: a3
#               measured 3 concurrent drops at 2.9-3.7 s against 19-25 s sequential (#57352).
# plan-11254's "retire" is one more branch of the SAME exit dispatch below, never a second mechanism. Members keep the
# PREFIX name and the owner stamp exactly as today, so a process killed before its close leaves databases reap() still
# collects (the backstop).
LIFETIMES = ("immediate", "batch")
BATCH_THREAD = "astryx-fixture-batch"              # the close's worker threads: an execute-layer counter can attribute


class BatchDropError(RuntimeError):
    """Batch.close() could not drop members that STILL EXIST. `failed` = {name: why}; every one is named."""

    def __init__(self, failed: dict):
        self.failed = dict(failed)
        super().__init__("fixture batch: %d member(s) still exist after the close: %s" % (
            len(failed), "; ".join(f"{n} ({w})" for n, w in sorted(failed.items()))))


class Batch:
    """Opt-in batch teardown. Members are fixture_db(lifetime="batch", batch=B) databases (B.fixture is that creator,
    the shape run()'s `fixture=` takes) and any name a caller enrolls. close() drops them all CONCURRENTLY, one admin
    session per member, waits for every one, and then judges each by what EXISTS (a3 BC-6 #57352): a member already
    gone (a stale sweep, an arm, a race) is dropped; only one that still exists is a failure. Failures are collected
    and raised ONCE, each by name, never swallowed. A context manager: leaving the block closes it."""

    def __init__(self):
        self.members, self.report, self.closed = [], [], False

    def enroll(self, name: str) -> str:
        if self.closed:
            raise RuntimeError(f"fixture batch is closed; {name} would never be dropped")
        if name not in self.members:
            self.members.append(name)
        return name

    def fixture(self, extra: tuple = ()):
        return fixture_db(extra=extra, lifetime="batch", batch=self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _drop_one(self, name: str) -> dict:
        r = {"name": name, "pid": None, "path": None, "error": None, "start": None, "end": None}
        try:
            with psycopg.connect(live_dsn(), autocommit=True) as a:      # its OWN session: one session is serial
                r["pid"] = a.info.backend_pid
                r["start"] = time.monotonic()
                r["path"] = _drop(a, name)
                r["end"] = time.monotonic()
        except Exception as e:                       # judged below by existence, never here (BC-6)
            r["error"] = f"{type(e).__name__}: {e}".strip()
        return r

    def close(self) -> list[dict]:
        """Drop every member concurrently and wait. Returns one report per member (name, backend pid, drop path,
        start/end monotonic, error). Raises BatchDropError naming every member that STILL EXISTS."""
        if self.closed:
            return self.report
        self.closed = True
        names = list(self.members)
        if not names:
            return self.report
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(names), thread_name_prefix=BATCH_THREAD) as pool:
            self.report = list(pool.map(self._drop_one, names))
        with psycopg.connect(live_dsn(), autocommit=True) as a:
            left = {r[0] for r in a.execute("SELECT datname FROM pg_database WHERE datname = ANY(%s)",
                                            (names,)).fetchall()}
        failed = {r["name"]: r["error"] or "still exists after its drop" for r in self.report if r["name"] in left}
        if failed:
            raise BatchDropError(failed)
        return self.report


@contextlib.contextmanager
def fixture_db(extra: tuple = (), lifetime: str = "immediate", batch: Batch | None = None):
    """A fresh database, schema.sql applied whole, every relation stamped; at block exit, its LIFETIME decides
    (the seam above): "immediate" (default) drops it WITH (FORCE) in finally; "batch" enrolls it in `batch`.

    `extra` is DDL a module owns OUTSIDE schema.sql (or an oracle's own probe relations). It is applied here,
    after schema.sql and BEFORE the stamp, so those relations are stamped too and their CREATE runs under
    this applier rather than in the oracle."""
    if lifetime not in LIFETIMES:
        raise ValueError(f"fixture_db: unknown lifetime {lifetime!r} (one of {LIFETIMES})")
    if lifetime == "batch" and batch is None:
        raise ValueError('fixture_db: lifetime="batch" needs batch=, the Batch that drops it')
    name = fresh_name()
    if lifetime == "batch":
        # enrolled BEFORE the CREATE: a closed batch refuses here, having made nothing, and every database that exists
        # is already a member (a name the CREATE never made is "already gone" at the close, BC-6). A close issued while
        # this block is still open drops it under the caller: closing a batch is the caller's last act.
        batch.enroll(name)
    try:
        admin = psycopg.connect(live_dsn(), autocommit=True)
    except (OSError, StopIteration, LookupError, psycopg.OperationalError) as e:
        raise FixtureUnavailable(f"no reachable admin DSN ({type(e).__name__})") from e
    t0 = time.monotonic()
    reap(admin, keep=name)                           # the dead runs' leftovers first (never raises; keep is default)
    try:
        # branch_check (plan-4918 P0-c) runs this as a NOSUPERUSER role that can't CREATE EXTENSION. It points
        # ASTRYX_FIXTURE_TEMPLATE at a cached template that already carries them; schema.sql's IF NOT EXISTS then
        # no-ops. Without the template, a non-superuser fixture silently LACKS vector/postgis/age (a2's find).
        tpl = os.environ.get("ASTRYX_FIXTURE_TEMPLATE")
        # Hardened at the CREATOR with NO window (plan-4918 #28982, a3 BC-5): born with connections DISALLOWED (nobody,
        # superuser included, can connect, and P0-b's datallowconn listing never sees it), PUBLIC CONNECT revoked,
        # THEN opened. A REVOKE after an open CREATE wouldn't evict a session a concurrent run role got in the gap.
        try:
            admin.execute(f'CREATE DATABASE "{name}" ALLOW_CONNECTIONS false'
                          + (f' TEMPLATE "{tpl}"' if tpl and tpl.replace("_", "").isalnum() else ""))
        except psycopg.errors.InsufficientPrivilege as e:
            raise FixtureUnavailable("this role can't CREATE DATABASE") from e
        admin.execute(f'REVOKE CONNECT ON DATABASE "{name}" FROM PUBLIC')
        admin.execute(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS true')
        # the OWNER STAMP the reaper judges by, AFTER BC-5's CREATE → REVOKE → ALTER (that order is an access
        # invariant, armed in test_branch_check_prep). Unstamped for an instant → the reaper KEEPS it (safe).
        try:
            admin.execute(f'COMMENT ON DATABASE "{name}" IS \'{owner_stamp()}\'')    # inline: digits/hex only
        except psycopg.Error:
            pass                                     # unstamped → kept; never fail a fixture for this
        dsn = make_conninfo(live_dsn(), dbname=name)
        sha = file_sha()
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(SCHEMA.read_text())          # the WHOLE file, the same bytes init.sh applies
            for ddl in extra:
                c.execute(ddl)
            # An extra that left search_path at ag_catalog once stamped every AGE label table `graphid` against a
            # check-time `ag_catalog.graphid`, which withheld DB-grain credit from every write in the fixture
            # (forge #50063). _stamp_all pins SIG_PATH itself, so no extra's path reaches the signature.
            n = _stamp_all(c, sha)
        yield {"dbname": name, "dsn": dsn, "url": url(dsn), "file_sha": sha, "relations": n,
               "apply_s": round(time.monotonic() - t0, 3)}
    finally:
        try:
            s = _side.pop(name, None)
            if s is not None:
                s.close()
            if lifetime == "batch":
                pass                                 # a member since entry: dropped at the batch's close, concurrently
            else:
                _drop(admin, name)                   # "immediate": gone at block exit, as every caller expects
        finally:
            admin.close()


# The ORG relations: ONE predicate shared by the stamper and the checker, so they can't disagree about the domain.
# Extension MEMBERS (postgis's geography_columns/geometry_columns views, …) aren't built by schema.sql, so they're
# never stamped. Under a NOSUPERUSER run role cloning a template the extensions came from, they're owned by the
# template's owner, and COMMENT on them fails "must be owner" (plan-4918 P0-c, measured). Before this, superuser
# stamped them silently.
_ORG_RELS = ("FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p','v','m') "
             "AND n.nspname NOT IN ('pg_catalog','information_schema','ag_catalog','topology') "
             "AND n.nspname NOT LIKE 'pg_toast%%' "
             "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass "
             "AND d.objid = c.oid AND d.deptype = 'e')")
_REL_SQL = "SELECT c.oid, obj_description(c.oid, 'pg_class') " + _ORG_RELS
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
        c.execute(SIG_PATH.replace("LOCAL ", ""))   # session-wide: this connection only ever reads signatures
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
