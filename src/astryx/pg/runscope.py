#!/usr/bin/env python3
"""runscope: a run's namespace, whose teardown is DERIVED from ownership (plan-4918 R1; a1 F4, a2 P3, a3 G1).

A ritual that creates things (databases, a role, files) must remove exactly what it created and nothing else.
runscope makes that a property of construction, not of a manifest someone keeps:

  run id    `<pid>x<epoch>`, carried by everything the run creates.
  root      <SCOPE_ROOT>/<run id>/, the ONLY directory the run writes. Teardown removes it by absolute path.
  role      bc_<run id>, LOGIN NOSUPERUSER CREATEDB. Every database the run creates is owned by it, so teardown
            is "drop every database WHERE datdba = role, then the role". No name pattern, so a database named
            differently can't be missed (a2's measured rule).
  lock      <root>/lock.json = {pid, starttime}. A later run's stale sweep reaps a scope whose process is gone.
            It keys on BOTH: pids are reused, and a dead run whose pid a later process took would otherwise read
            as alive and never be reaped (a3 BC-3).

The role's password is random, and the server only ever receives a client-computed SCRAM verifier, so the
plaintext never reaches argv, the server log, or a transcript (plan-5497 a1 BC-1, applied here). It lives only in
this process and in the run's generated DSN.

Teardown clears IS_TEMPLATE before each DROP: Postgres refuses to drop a template database, and a run-owned
template would otherwise survive every teardown (a2's binding condition on plan-4918, measured).

LEAK = anything still owned after teardown. It is reported, never silently retried away.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

import psycopg
from psycopg import sql

# shared-on-purpose: the CROSS-RUN ownership ledger. A later run reaps a dead run's postgres debris FROM its lock.json, so
# it never lives under a gate's TMPDIR, which is removed when the gate exits (plan-10108 a2 rider #50743)
SCOPE_ROOT = Path(os.environ.get("ASTRYX_RUNSCOPE_ROOT", "/tmp/astryx-runscope"))
ROLE_PREFIX = "bc_"


def _starttime(pid: int):
    """Process start time in clock ticks since boot (/proc/<pid>/stat field 22), or None if the pid is gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return int(stat.rsplit(")", 1)[1].split()[19])      # fields after "(comm)"; field 22 overall


def alive(lock: dict) -> bool:
    """The lock's process still exists AND is the same process (pid reuse gives a different start time)."""
    st = _starttime(int(lock.get("pid", -1)))
    return st is not None and st == lock.get("starttime")


class RunScope:
    def __init__(self, admin_dsn: str, root: Path = None):
        self.admin_dsn = admin_dsn
        self.run_id = f"{os.getpid()}x{int(time.time())}"
        self.base = (root or SCOPE_ROOT)
        self.root = self.base / self.run_id
        self.role = f"{ROLE_PREFIX}{self.run_id}".lower()
        self._password = secrets.token_urlsafe(24)

    # ── creation ────────────────────────────────────────────────────────────────────────────────────────────
    def open(self) -> "RunScope":
        self.root.mkdir(parents=True, exist_ok=False)
        (self.root / "lock.json").write_text(json.dumps(
            {"pid": os.getpid(), "starttime": _starttime(os.getpid()), "role": self.role,
             "created": time.time()}))
        with psycopg.connect(self.admin_dsn, autocommit=True) as c:
            verifier = c.pgconn.encrypt_password(self._password.encode(), self.role.encode(), b"scram-sha-256")
            c.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER CREATEDB PASSWORD {}").format(
                sql.Identifier(self.role), sql.Literal(verifier.decode())))
            if MACHINE_ID:
                c.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(self.role), sql.Literal(_stamp())))
            # AGE (plan-4918 D1): a non-superuser can't `LOAD 'age'`, so the admin preloads it for this role's
            # sessions. Only where the server offers AGE: a preload of a missing library fails EVERY connection.
            if c.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'age'").fetchone():
                c.execute(sql.SQL("ALTER ROLE {} SET session_preload_libraries = 'age'").format(
                    sql.Identifier(self.role)))
        return self

    def dsn(self, dbname: str, host: str = "127.0.0.1", port: int = 5432, socket_dir: str = None) -> str:
        """The run role's DSN for one of its databases. The only place the plaintext password is rendered.
        With socket_dir, the DSN reaches the server through a unix socket in that directory (the sandbox's only
        route to postgres once its network is unshared)."""
        if socket_dir:
            from urllib.parse import quote
            return f"postgresql://{self.role}:{self._password}@/{dbname}?host={quote(str(socket_dir), safe='/')}&port={port}"
        return f"postgresql://{self.role}:{self._password}@{host}:{port}/{dbname}"

    def create_db(self, name: str, template: str = None) -> str:
        """A database OWNED by the run role (created by the admin, so any template works), born with NO window
        (a3 #32077 R3): connections DISALLOWED at creation, PUBLIC CONNECT revoked, then opened. Otherwise two
        runs that both passed P0-b could CONNECT to each other's prod clones in the gap. The owner keeps CONNECT
        through its own ACL entry."""
        q = sql.SQL("CREATE DATABASE {} OWNER {} ALLOW_CONNECTIONS false").format(
            sql.Identifier(name), sql.Identifier(self.role))
        if template:
            q = q + sql.SQL(" TEMPLATE {}").format(sql.Identifier(template))
        with psycopg.connect(self.admin_dsn, autocommit=True) as c:
            c.execute(q)
            c.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
            c.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(sql.Identifier(name)))
        return name

    # ── teardown ────────────────────────────────────────────────────────────────────────────────────────────
    def owned_dbs(self, conn=None) -> list:
        return owned_dbs(self.admin_dsn, self.role, conn)

    def close(self) -> dict:
        return teardown(self.admin_dsn, self.role, self.root, self.base)

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
        return False


def owned_dbs(admin_dsn: str, role: str, conn=None) -> list:
    q = "SELECT d.datname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba WHERE r.rolname = %s ORDER BY 1"
    if conn is not None:
        return [r[0] for r in conn.execute(q, (role,))]
    with psycopg.connect(admin_dsn, autocommit=True) as c:
        return [r[0] for r in c.execute(q, (role,))]


def _bound(role: str, root: Path, base: Path) -> bool:
    """Teardown acts ONLY on a scope whose role is derived from its own directory name, inside the scope base.
    A lockfile is data: a crafted or corrupted one naming another role (genesis) or another path is refused."""
    root, base = Path(root), Path(base)
    return (root.is_absolute() and root.resolve().parent == base.resolve()
            and role == f"{ROLE_PREFIX}{root.name}".lower() and role.startswith(ROLE_PREFIX))


def teardown(admin_dsn: str, role: str, root: Path, base: Path = None) -> dict:
    """Drop everything the role owns, then the role, then the root. Returns {dropped, leaked, role_left, root_left}.
    Every step is attempted even if an earlier one fails, so one error can't strand the rest."""
    out = {"dropped": [], "leaked": [], "errors": [], "role_left": False, "root_left": False}
    if not _bound(role, root, base or SCOPE_ROOT):
        out["errors"].append(f"refused: role {role!r} / root {str(root)!r} is not a scope under {base or SCOPE_ROOT}")
        return out
    with psycopg.connect(admin_dsn, autocommit=True) as c:
        exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    if exists:
        out.update(_drop_owned(admin_dsn, role))         # ONE implementation of "drop what the role owns, then it"
    root = Path(root)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    out["root_left"] = root.exists()
    return out


def live(base: Path = None) -> list:
    """Run ids of the scopes under `base` whose process is alive (pid AND start time), this process's included."""
    base = base or SCOPE_ROOT
    out = []
    for d in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        try:
            if alive(json.loads((d / "lock.json").read_text())):
                out.append(d.name)
        except (OSError, ValueError):
            continue
    return out


ROLE_RX = re.compile(rf"^{ROLE_PREFIX}(\d+)x(\d+)$")
# The role name carries pid and epoch but no HOST, and a postgres the human points us at may serve two hosts. So each
# run role is stamped with this machine's id at creation, and the orphan sweep reaps ONLY roles carrying it: a foreign
# or missing stamp is REPORTED, never dropped (a3 #35480: host A must not read host B's live run as an orphan).
# The id is read from the first source that has one: systemd's, then dbus's (older Linux), then macOS's platform UUID
# (a3 #36112: CLAUDE.md supports macOS, which has neither file). No id at all is the SAFE direction, every role
# unstamped and only reported, but then a crashed run's role is never reaped there: debris accumulates, by design.
def _machine_id():
    for f in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            v = Path(f).read_text().strip()
        except OSError:
            continue
        if v:
            return v
    try:
        out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
    return m.group(1) if m else None


MACHINE_ID = _machine_id()
# An ORACLE's run role is stamped `test:<machine-id>` (a3 #37109 (2)): the property is ownership, not an epoch shape.
# A production (unscoped) sweep reaps ONLY the exact machine id, so it never adopts a live oracle's role, the real-
# epoch crashed-child arm included, which MIN_EPOCH can't see. A scoped sweep (only=) accepts its own test stamp.
# Set by check.sh for every gate, and by tests/_oracle_debris for an oracle run directly (mutation_probe's way).
TEST_ENV = "ASTRYX_RUNSCOPE_TEST"
TEST_STAMP = f"test:{MACHINE_ID}" if MACHINE_ID else None


def _stamp():
    return TEST_STAMP if os.environ.get(TEST_ENV) else MACHINE_ID


def _started_at(pid: int):
    """Wall-clock start of the process now holding `pid` (boot time + its start ticks), or None if the pid is gone."""
    st = _starttime(pid)
    if st is None:
        return None
    btime = next(int(ln.split()[1]) for ln in Path("/proc/stat").read_text().splitlines() if ln.startswith("btime "))
    return btime + st / os.sysconf("SC_CLK_TCK")


# No real run role predates 2020: its epoch is the run's start (on a host with a working clock: one that boots with no
# RTC reads 1970 until NTP, so its runs read synthetic and are never reaped there, the safe direction, a3 #37109). A smaller epoch is SYNTHETIC, an oracle's planted role
# (test_runscope's bc_<pid>x1000..1003), and an UNSCOPED (production) sweep must never adopt one: it belongs to a
# live oracle that is asserting on it (a2 F-RS #36873: a real branch_check sweep reaped a3's running mutant battery's
# planted roles, and crashed in the race). Reported, never dropped. A scoped sweep (only=) still judges them.
MIN_EPOCH = 1_577_836_800


def orphan_roles(admin_dsn: str, only=None, foreign=None, synthetic=None) -> list:
    """Run roles whose creator is GONE, read from POSTGRES, not from lockfiles (a2 F1 #34875): a reboot or a removed
    scope dir erases the lock, never the role or its databases. The role's name is its creator, `bc_<pid>x<epoch>`.
    Gone means the pid is dead, OR the process now holding it started AFTER the role's epoch (pids are reused, most
    of all after a reboot), so it can't be the creator. A live run is never an orphan, with or without its lock.
    `only` restricts the CANDIDATES before any test (a3 D1 #35480): production passes None (the org-wide sweep it
    needs); an oracle passes exactly the roles it made, so even a mutated predicate can destroy nothing else.
    An orphan not stamped with THIS machine's id is appended to `foreign` (reported), never returned (dropped).
    Unscoped, an ORACLE's role (stamp TEST_STAMP) counts as foreign too; only a scoped sweep reaps it.
    Unscoped, a role with a SYNTHETIC epoch (< MIN_EPOCH) is appended to `synthetic` and never judged."""
    with psycopg.connect(admin_dsn, autocommit=True) as c:
        roles = [r[0] for r in c.execute("SELECT rolname FROM pg_roles WHERE rolname LIKE 'bc\\_%'")]
        out = []
        for r in roles:
            if only is not None and r not in only:
                continue
            m = ROLE_RX.match(r)
            if not m:
                continue
            if only is None and int(m.group(2)) < MIN_EPOCH:
                if synthetic is not None:
                    synthetic.append(r)
                continue
            started = _started_at(int(m.group(1)))
            if started is not None and started <= int(m.group(2)) + 2:      # the creator (or older) is still alive
                continue
            stamp = c.execute("SELECT shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname = %s",
                              (r,)).fetchone()
            ok = {MACHINE_ID} if only is None else {MACHINE_ID, TEST_STAMP}       # a test stamp: scoped sweeps only
            if not MACHINE_ID or not stamp or stamp[0] not in ok:
                if foreign is not None:
                    foreign.append(r)
                continue
            out.append(r)
    return sorted(out)


def _drop_owned(admin_dsn: str, role: str) -> dict:
    """teardown()'s database half, for a role with no root to bind (an orphan): every DB it owns, then the role.
    A lost connection (another sweep dropped the same DB first, an admin terminated us) is REPORTED in `errors`,
    never raised: one orphan must not crash the run (a2 F-RS #36873). `role_left` is then None: unknown."""
    out = {"dropped": [], "leaked": [], "errors": [], "role_left": False}
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as c:
            for db in owned_dbs(admin_dsn, role, c):
                try:
                    # DROP first; clear IS_TEMPLATE only when the server refuses a TEMPLATE (42809, an ordinary
                    # ERROR). Not ALTER-first: an INVALID database (an interrupted DROP, e.g. its run was killed)
                    # answers ALTER with FATAL and closes this connection, so every later drop here failed too
                    # (10-11, bc_2741292x…_tpl). An invalid database can always be dropped.
                    try:
                        c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db)))
                    except psycopg.errors.WrongObjectType:
                        c.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE false").format(sql.Identifier(db)))
                        c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db)))
                    out["dropped"].append(db)
                except psycopg.Error as e:
                    out["errors"].append(f"{db}: {type(e).__name__}")
            out["leaked"] = owned_dbs(admin_dsn, role, c)
            if not out["leaked"]:
                try:
                    c.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
                except psycopg.Error as e:
                    out["errors"].append(f"role: {type(e).__name__}")
            out["role_left"] = bool(c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone())
    except psycopg.Error as e:
        out["errors"].append(f"connection: {type(e).__name__}: {str(e).strip()[:120]}")
        out["role_left"] = None
    return out


def dead_scopes(base: Path = None, unprovable: list = None) -> list:
    """(dir, lock) of every scope under `base` whose lock's process is gone (pid AND start time). The sweep reaps
    exactly these, and the census reports exactly these: one predicate, so the two can't disagree. A dir with no
    readable lock is not a scope we can prove is ours: appended to `unprovable` (reported), never returned."""
    base = base or SCOPE_ROOT
    out = []
    for d in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        try:
            lock = json.loads((d / "lock.json").read_text())
        except (OSError, ValueError):
            if unprovable is not None:
                unprovable.append(d.name)
            continue
        if not alive(lock):
            out.append((d, lock))
    return out


def census(admin_dsn: str, base: Path = None, only=None) -> dict:
    """READ-ONLY: what sweep() WOULD reap, and what it would only report. Nothing is dropped or removed.

    sweep() runs only at the start of a branch_check, so a killed run's debris stays until someone runs one again.
    This is the standing read of that gap. It keys on the SWEEP'S OWN predicate (a dead (pid, starttime), or a role
    whose creator is gone), never on AGE: a healthy full run takes over 50 minutes, and an age rule accuses it
    (steward #45223 → a4 #45225, measured on two live runs that an age rule would have called leaks).
      dead_scopes  scope dirs whose process is gone           (debris: sweep reaps them)
      orphans      this host's run roles whose creator is gone (debris: sweep reaps them)
      foreign      orphans another host (or an oracle) stamped  (reported, never debris here)
      unprovable   dirs under the root with no readable lock     (reported, never touched)"""
    unprovable, foreign, synthetic = [], [], []
    dead = [d.name for d, _ in dead_scopes(base, unprovable)]
    orphans = orphan_roles(admin_dsn, only=only, foreign=foreign, synthetic=synthetic)
    return {"dead_scopes": dead, "orphans": orphans, "foreign": sorted(foreign), "unprovable": unprovable}


def sweep(admin_dsn: str, base: Path = None, only=None) -> list:
    """Reap every scope under `base` whose lock's process is gone (pid AND start time). Returns their reports."""
    base = base or SCOPE_ROOT
    reaped = []
    for d, lock in dead_scopes(base):                  # a dir with no readable lock: never touched
        rep = teardown(admin_dsn, str(lock.get("role", "")), d, base)
        reaped.append({"scope": d.name, **rep})
    foreign, synthetic = [], []
    for role in orphan_roles(admin_dsn, only=only, foreign=foreign, synthetic=synthetic):   # a2 F1: lock gone, role not
        try:
            rep = _drop_owned(admin_dsn, role)
        except Exception as e:                         # noqa: BLE001 — one orphan never crashes the run (a2 F-RS)
            rep = {"dropped": [], "errors": [f"{type(e).__name__}: {str(e)[:120]}"], "role_left": None}
        reaped.append({"scope": role[len(ROLE_PREFIX):], "orphan": True, **rep})
    for role in synthetic:
        reaped.append({"scope": role[len(ROLE_PREFIX):], "orphan": True, "dropped": [],
                       "skipped": "synthetic epoch (an oracle's planted role): an unscoped sweep never drops it"})
    for role in foreign:
        reaped.append({"scope": role[len(ROLE_PREFIX):], "orphan": True, "dropped": [],
                       "skipped": "not stamped with this machine's id: another host's (or a pre-stamp) run role. "
                                  "Reported, never dropped"})
    return reaped


def main(argv=None) -> int:
    """`python -m astryx.pg.runscope census`: the read-only census. rc 0 none · 1 debris (named) · 77 no DSN.
    Names are role and run ids only (pid x epoch): metadata, nothing a run carried."""
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["census"]:
        print("usage: python -m astryx.pg.runscope census")
        return 2
    dsn = os.environ.get("ASTRYX_DSN")
    if not dsn:
        print("runscope census: NOT SEARCHED (rc 77): no ASTRYX_DSN")
        return 77
    c = census(dsn)
    for k in ("dead_scopes", "orphans", "foreign", "unprovable"):
        print(f"  {k}: {len(c[k])}" + "".join(f"\n    {x}" for x in c[k]))
    debris = len(c["dead_scopes"]) + len(c["orphans"])
    print(f"runscope census: {debris} debris (sweep would reap), {len(c['foreign']) + len(c['unprovable'])} reported")
    return 1 if debris else 0


if __name__ == "__main__":
    raise SystemExit(main())
