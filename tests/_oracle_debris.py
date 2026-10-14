"""Shared by the branch_check/runscope oracles: reap the debris a KILLED earlier oracle run left behind.

An oracle can be SIGKILLed mid-run (a timeout, a mutation_probe budget), and then its `finally` never runs. So each
oracle STARTS by reaping its own debris, with raw SQL and never through the subject under test (under a teardown
mutant the subject is the broken code). Debris is recognized ONLY by test-only names that carry the creating pid, and
reaped only when that pid is gone. Real names (astryx_bctpl_<hex12>, bc_<pid>x<epoch> of a live run) never match.
"""
import json
import os
import re
import shutil
from pathlib import Path

from psycopg import errors, sql

# Every run role an oracle makes is a TEST role (src/astryx/pg/runscope.py TEST_STAMP): set here, at import, because every
# RunScope oracle imports this module before it opens a scope, and mutation_probe runs oracles outside check.sh.
os.environ.setdefault("ASTRYX_RUNSCOPE_TEST", "1")
ORACLE_BASE = Path(os.environ.get("ASTRYX_RUNSCOPE_ORACLE_ROOT", "/tmp/astryx-runscope-oracle"))
from devtools.branch_check_prep import TEST_DB                    # noqa: E402 (ONE definition, P0-b's refusal reads it too)
TEST_ROLE = re.compile(r"^astryx_hardendep_(\d+)$"
                       r"|^bc_(\d+)x100[0-3]$")    # runscope's synthetic orphans (reused / outside / foreign / unstamped)        # a LOGIN role test_init_harden plants


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def _drop_db(adm, d):
    # DROP first; clear IS_TEMPLATE only on the server's template refusal (42809). ALTER-first FATALs on an INVALID
    # database (an interrupted DROP) and closes the connection; an invalid database can always be dropped.
    try:
        adm.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(d)))
    except errors.WrongObjectType:
        adm.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE false").format(sql.Identifier(d)))
        adm.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(d)))


def reap(adm) -> list:
    reaped = []
    for (d,) in adm.execute("SELECT datname FROM pg_database").fetchall():
        m = TEST_DB.match(d)
        if m and _gone(int(next(g for g in m.groups() if g))):
            _drop_db(adm, d)
            reaped.append(d)
    for (r,) in adm.execute("SELECT rolname FROM pg_roles").fetchall():     # after the DBs holding its grants
        m = TEST_ROLE.match(r)
        if m and _gone(int(next(g for g in m.groups() if g))):
            for (d,) in adm.execute("SELECT d.datname FROM pg_database d JOIN pg_roles o ON o.oid = d.datdba "
                                    "WHERE o.rolname = %s", (r,)).fetchall():
                _drop_db(adm, d)                            # by OWNERSHIP first: a role owning a DB can't be dropped
                reaped.append(d)
            adm.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(r)))
            reaped.append(r)
    # Scopes sit at ORACLE_BASE/<run id>, or one level down at ORACLE_BASE/o<pid>/<run id> (test_runscope's per-oracle
    # subdir). Reading only the top level missed every killed test_runscope's real-epoch role and its databases
    # (10-11: bc_2741292x… outlived its check_watch run and had to be dropped by hand).
    subdirs, scopes = [], []
    if ORACLE_BASE.is_dir():
        for top in ORACLE_BASE.iterdir():
            if not top.is_dir():
                continue
            if (top / "lock.json").exists():
                scopes.append(top)
            elif re.fullmatch(r"o\d+", top.name):
                subdirs.append(top)
                scopes += [s for s in top.iterdir() if s.is_dir()]
    for scope in scopes:
        try:
            lock = json.loads((scope / "lock.json").read_text())
        except (OSError, ValueError):
            continue
        role = f"bc_{scope.name}".lower()
        if lock.get("role") != role or not _gone(int(lock.get("pid", 0))):
            continue
        if adm.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
            for (d,) in adm.execute("SELECT d.datname FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba "
                                    "WHERE r.rolname=%s", (role,)).fetchall():
                _drop_db(adm, d)
                reaped.append(d)
            adm.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            reaped.append(role)
        shutil.rmtree(scope, ignore_errors=True)
    for sub in subdirs:                                 # a dead oracle's emptied o<pid>: rmdir only, never a tree
        if _gone(int(sub.name[1:])):
            try:
                sub.rmdir()
            except OSError:
                pass
    return reaped
