#!/usr/bin/env python3
"""init.sh's `harden` reconcile node (plan-4918 P0-a, seed #33389): no database the org administers grants PUBLIC
CONNECT, so a fresh org is born with what seed applied live by hand.

The block is EXTRACTED from init.sh (between its `# >>> harden` / `# <<< harden` markers) and run in bash with a
psql_q bound to the admin DSN, against two scratch databases this oracle creates OPEN (Postgres's default ACL). Every
call names them, so the live estate is never touched: the name filter is itself an arm (the unnamed one stays open).
Exits 77 without a DSN, psql, or CREATE DATABASE rights.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INIT = Path(os.environ.get("INIT_HARDEN_SRC") or (REPO / "init.sh"))       # mutation_probe points this at a mutant
sys.path.insert(0, str(REPO / "tests"))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    try:
        import psycopg
    except ModuleNotFoundError as e:
        if e.name != "psycopg":
            raise
        print(f"NOT SEARCHED: psycopg is not importable by {sys.executable}; no arm ran.")
        return 77
    from psycopg import sql
    from test_branch_check_prep import admin_dsn
    dsn = admin_dsn()
    if not dsn or not shutil.which("psql"):
        print("NOT SEARCHED: no admin DSN or no psql on PATH; no arm ran.")
        return 77
    src = INIT.read_text()
    m = re.search(r"^# >>> harden.*?^# <<< harden$", src, re.S | re.M)
    check("init.sh carries the harden block between its markers", bool(m))
    nodes = re.search(r"^RECONCILE_NODES=\((.*?)\)", src, re.S | re.M)
    order = re.findall(r'"(\w+)\|(\w+)"', nodes.group(1)) if nodes else []
    names = [n for n, _ in order]
    check("the reconciler runs harden as an INTERIOR node after schema",
          ("harden", "interior") in order and "schema" in names and names.index("harden") > names.index("schema"),
          str(order))
    if not m:
        return 1

    def sh(fn, *dbs, dsn_=dsn):
        prog = "say() { :; }\npsql_q() { psql \"$HARDEN_DSN\" \"$@\"; }\n" + m.group(0) + f'\n{fn} "$@"\n'
        return subprocess.run(["bash", "-c", prog, "harden", *dbs], env={**os.environ, "HARDEN_DSN": dsn_},
                              capture_output=True, text=True, timeout=60)

    adm = psycopg.connect(dsn, autocommit=True)
    from _oracle_debris import reap
    reap(adm)
    a, b = f"astryx_hardenprobe_a_{os.getpid()}", f"astryx_hardenprobe_b_{os.getpid()}"
    pub = lambda d: adm.execute("SELECT has_database_privilege('public', %s, 'CONNECT')", (d,)).fetchone()[0]
    try:
        try:
            for d in (a, b):
                adm.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(d)))   # born OPEN: the default ACL
        except psycopg.errors.InsufficientPrivilege:
            print("NOT SEARCHED: this role can't CREATE DATABASE; no arm ran.")
            return 77
        check("control: a database born with the default ACL grants PUBLIC CONNECT", pub(a) and pub(b))
        r = sh("_open_dbs", a)
        check("_open_dbs names the open scratch DB", r.returncode == 0 and r.stdout.split() == [a], r.stdout + r.stderr)
        check("RED: _chk_harden fails while it is open", sh("_chk_harden", a).returncode != 0)
        r = sh("_act_harden", a)
        check("_act_harden exits 0", r.returncode == 0, r.stderr[-300:])
        check("…and PUBLIC CONNECT is revoked, server-verified", not pub(a))
        check("…ONLY on the named database: the unnamed one is still open (the filter the reconciler omits)", pub(b))
        # read from the ACL, not by connecting: the admin is a superuser, and a superuser connects regardless of any ACL
        own = adm.execute("SELECT coalesce(bool_or(x.privilege_type = 'CONNECT'), false) FROM pg_database d, "
                          "aclexplode(d.datacl) x WHERE d.datname = %s AND x.grantee = d.datdba", (a,)).fetchone()[0]
        check("the owner keeps CONNECT through its own explicit ACL entry, server-read", own)
        check("GREEN: _chk_harden passes once hardened", sh("_chk_harden", a).returncode == 0)
        r = sh("_act_harden", a)
        check("idempotent: a second _act_harden exits 0 and changes nothing", r.returncode == 0 and not pub(a),
              r.stderr[-300:])
        r = sh("_chk_harden", a, dsn_="postgresql://nobody@127.0.0.1:1/x?connect_timeout=2")
        check("fail-closed: an unreachable server reads RED, never green", r.returncode != 0)
    finally:
        for d in (a, b):
            adm.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(d)))
        left = adm.execute("SELECT count(*) FROM pg_database WHERE datname IN (%s, %s)", (a, b)).fetchone()[0]
        adm.close()
    check("teardown: both scratch databases dropped", left == 0)
    print(f"\n{'FAIL' if fails else 'PASS'}: init.sh harden ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
