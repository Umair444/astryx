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

from psycopg import sql

ORACLE_BASE = Path(os.environ.get("ASTRYX_RUNSCOPE_ORACLE_ROOT", "/tmp/astryx-runscope-oracle"))
TEST_DB = re.compile(r"^(?:astryx_bctpl_(?:zz|zk|t)_|astryxQbctplQ_)(\d+)$|^bc_(\d+)x\d+_nullacl$")


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def _drop_db(adm, d):
    adm.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE false").format(sql.Identifier(d)))
    adm.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(d)))


def reap(adm) -> list:
    reaped = []
    for (d,) in adm.execute("SELECT datname FROM pg_database").fetchall():
        m = TEST_DB.match(d)
        if m and _gone(int(m.group(1) or m.group(2))):
            _drop_db(adm, d)
            reaped.append(d)
    if ORACLE_BASE.is_dir():
        for scope in ORACLE_BASE.iterdir():
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
    return reaped
