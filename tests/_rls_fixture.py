"""Shared by the cog-rls oracles (tests/test_cog_roles.py, tests/test_rls_leak.py): a fixture database provisioned by
devtools/cog_roles.py with a PER-RUN role set, and two orgs `a` and `b` that log in as their own roles.

Roles are cluster-wide and the fixtures share the live cluster, so every role here carries the prefix
`astryx_cr<pid>_` and is dropped at the end; a killed run's roles are reaped at the next start by that pid (gone).
The roles are made by the provisioner's own code (cog_roles.ensure_roles / ensure_org), never by a statement here.
"""
import contextlib
import os
import re
import secrets
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "src")]

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

from devtools import cog_roles as cr  # noqa: E402
from astryx.security.sqlguard.fixture import fixture_db, live_dsn  # noqa: E402

PFX = re.compile(r"^astryx_cr(\d+)_")


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def drop_roles(adm, roles) -> list:
    """Drop roles, after their grants on databases still standing (a database ACL blocks DROP ROLE). Never raises."""
    left = []
    for r in roles:
        try:
            for (d,) in adm.execute("SELECT DISTINCT d.datname FROM pg_database d, aclexplode(d.datacl) a "
                                    "JOIN pg_roles g ON g.oid = a.grantee WHERE g.rolname = %s", (r,)).fetchall():
                adm.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(sql.Identifier(d), sql.Identifier(r)))
            adm.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(r)))
        except psycopg.Error as e:
            left.append(f"{r}: {type(e).__name__}")
    return left


def _order(roles):
    """org_* logins first, then the five kinds in reverse (an org group can't go while a member stands? it can, but a
    role owning objects can't: the fixture database is dropped before this runs)."""
    return sorted(roles, key=lambda r: (0 if "_org_" in r else 1, r))


def reap(adm) -> list:
    """A killed run's per-run roles (its pid is gone). Only names this module makes."""
    if not adm.execute("SELECT rolcreaterole OR rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:
        return []
    dead = [r for (r,) in adm.execute("SELECT rolname FROM pg_roles").fetchall()
            if PFX.match(r) and _gone(int(PFX.match(r).group(1)))]
    drop_roles(adm, _order(dead))
    return dead


class Org:
    def __init__(self, key, role, dsn):
        self.key, self.role, self.dsn = key, role, dsn

    def connect(self, **kw):
        return psycopg.connect(self.dsn, autocommit=True, **kw)


@contextlib.contextmanager
def provisioned(keys=("a", "b"), extra=()):
    """yield (fx, admin_conn_to_fx, names, {key: Org}). The admin is the fixture's own (live_dsn())."""
    names = cr.Names(f"astryx_cr{os.getpid()}_")
    adm = psycopg.connect(live_dsn(), autocommit=True)
    made = []
    try:
        reap(adm)
        cr.ensure_roles(adm, names)
        made += names.all()
        with fixture_db(extra=extra) as fx:
            c = psycopg.connect(fx["dsn"], autocommit=True)
            try:
                cr.provision_db(c, names)
                out = {}
                for k in keys:
                    pw = secrets.token_urlsafe(18)
                    role = cr.ensure_org(c, names, k, pw=pw)
                    made.append(role)
                    out[k] = Org(k, role, cr.role_dsn(fx["dsn"], role, pw))
                yield fx, c, names, out
            finally:
                c.close()
    finally:
        try:
            drop_roles(adm, _order(set(made)))
        finally:
            adm.close()


def is_super(conn) -> bool:
    return bool(conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0])


def denied(conn, q, args=None) -> tuple[bool, str]:
    """(True, error class) if the statement is refused; (False, 'ran') if it ran. Autocommit connections."""
    try:
        conn.execute(q, args)
        return False, "ran"
    except psycopg.Error as e:
        return True, type(e).__name__
