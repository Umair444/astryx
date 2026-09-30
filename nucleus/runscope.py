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
import secrets
import shutil
import time
from pathlib import Path

import psycopg
from psycopg import sql

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
        for db in owned_dbs(admin_dsn, role, c) if exists else []:
            try:
                c.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE false").format(sql.Identifier(db)))
                c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db)))
                out["dropped"].append(db)
            except psycopg.Error as e:
                out["errors"].append(f"{db}: {type(e).__name__}")
        if exists:
            out["leaked"] = owned_dbs(admin_dsn, role, c)
            if not out["leaked"]:
                try:
                    c.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
                except psycopg.Error as e:
                    out["errors"].append(f"role: {type(e).__name__}")
            out["role_left"] = bool(c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone())
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


def sweep(admin_dsn: str, base: Path = None) -> list:
    """Reap every scope under `base` whose lock's process is gone (pid AND start time). Returns their reports."""
    base = base or SCOPE_ROOT
    reaped = []
    if not base.is_dir():
        return reaped
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        try:
            lock = json.loads((d / "lock.json").read_text())
        except (OSError, ValueError):
            continue                                   # not a scope we can prove is ours: never touch it
        if alive(lock):
            continue
        rep = teardown(admin_dsn, str(lock.get("role", "")), d, base)
        reaped.append({"scope": d.name, **rep})
    return reaped
