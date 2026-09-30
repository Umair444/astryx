#!/usr/bin/env python3
"""branch_check SANDBOX oracle (plan-4918 R3/R5): the allowlist holds from INSIDE, every negative probe has its
positive control OUTSIDE, and each probe is shown to FIRE on a planted breach. Exits 77 without bwrap or a DSN.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    from test_branch_check_prep import admin_dsn
    dsn = admin_dsn()
    if not dsn or not shutil.which("bwrap"):
        print("NOT SEARCHED: no ASTRYX_DSN or no bwrap. Nothing was verified.")
        return 77
    import psycopg
    from psycopg import sql
    src = os.environ.get("BRANCH_CHECK_SANDBOX_SRC")
    if src:
        import importlib.util
        spec = importlib.util.spec_from_file_location("bcsb_under_test", src)
        sb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sb)
    else:
        from nucleus import branch_check_sandbox as sb
    from nucleus import runscope as rs
    from _oracle_debris import ORACLE_BASE, reap
    live = sb.LIVE
    if not (live / ".env").is_file():
        print("NOT SEARCHED: the live .env isn't here, so the (iv) control can't run. Nothing was verified.")
        return 77
    adm = psycopg.connect(dsn, autocommit=True)
    reap(adm)
    tmp = Path(tempfile.mkdtemp(prefix="bcsb-oracle-"))
    scope, hard, soft = None, f"bc_{os.getpid()}x0_nullacl", None
    try:
        scope = rs.RunScope(dsn, root=ORACLE_BASE).open()
        own = scope.create_db(f"{scope.role}_own")
        adm.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(hard)))           # hardened, admin-owned
        adm.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(hard)))
        repo, run_tmp = tmp / "repo", tmp / "tmp"
        repo.mkdir()
        run_tmp.mkdir()
        sock = run_tmp / "pg"
        cfg = {"targets": sb.reach_targets(), "live_env": str(live / ".env"), "live_repo": str(live),
               "own_dsn": scope.dsn(own, socket_dir=sock), "foreign_dbs": [hard],
               "run_conn": {"user": scope.role, "password": scope._password, "host": str(sock), "port": 5432},
               "listeners": sb.host_listeners(), "socket_dirs": [str(sock)]}
        out_cfg = {**cfg, "socket_dirs": [], "own_dsn": scope.dsn(own),
                   "run_conn": {**cfg["run_conn"], "host": "127.0.0.1"}}          # OUTSIDE: the same probes over TCP
        bridge = sb.PgBridge(sock).__enter__()
        py = str(live / "venv" / "bin" / "python")
        probe_src = Path(src) if src else REPO / "nucleus" / "branch_check_sandbox.py"

        def inside(ro_extra=(), home=None, c=cfg, share_net=False):
            a = sb.argv(repo, run_tmp, ro_extra=ro_extra, live=live, probe_src=probe_src, share_net=share_net)
            if home:
                a = [x for x in a]
                i = a.index("--setenv")
                a[i + 2] = str(home)                                  # HOME
            r = subprocess.run(a + [py, sb.PROBE_AT], input=json.dumps(c), env=sb.env(c["own_dsn"]),
                               capture_output=True, text=True, timeout=120)
            return json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"error": r.stderr[-400:]}

        # ── node (plan-4918 D3, a3 C3): resolved OUTSIDE, ONE install bound, never the whole mise tree ────────
        nb = None
        try:
            nb = sb.node_bin()
        except sb.NodeUnresolved as e:
            check("D3: node resolves on this host", False, str(e))
        if nb:
            na = sb.argv(repo, run_tmp, live=live, node=nb)
            ran = subprocess.run(na + [str(nb), "-e", "process.stdout.write(process.version)"],
                                 env=sb.env(scope.dsn(own), nb), capture_output=True, text=True, timeout=60)
            check("D3: the resolved node RUNS inside the sandbox", ran.returncode == 0 and ran.stdout.startswith("v"),
                  (ran.stdout + ran.stderr)[-200:])
            inst = sb.MISE_INSTALLS
            if sb.node_dir(nb):
                seen = subprocess.run(na + ["/usr/bin/ls", "-A", str(inst)], env=sb.env(scope.dsn(own), nb),
                                      capture_output=True, text=True, timeout=60)
                shims = subprocess.run(na + ["/usr/bin/ls", str(inst.parent / "shims")], env=sb.env(scope.dsn(own), nb),
                                       capture_output=True, text=True, timeout=60)
                check("C3: inside, the mise installs tree shows ONLY node (no other tool's install, no shims)",
                      seen.stdout.split() == ["node"] and shims.returncode != 0, f"{seen.stdout.split()} shims_rc={shims.returncode}")
        check("D3: the sandbox env hands check.sh the RESOLVED node as ASTRYX_NODE (never the live shim)",
              sb.env("x", Path("/r/node")).get("ASTRYX_NODE") == "/r/node" and "ASTRYX_NODE" not in sb.env("x"))
        nowhere = tmp / "no-system-node"
        failing = tmp / "mise-fails"
        failing.write_text("#!/bin/sh\nexit 3\n")
        failing.chmod(0o755)
        outside = tmp / "mise-outside"
        outside.write_text("#!/bin/sh\necho /usr/bin/true\n")
        outside.chmod(0o755)
        for label, fake in (("fails", failing), ("resolves OUTSIDE its installs tree", outside)):
            try:
                sb.node_bin(mise=str(fake), sys_node=nowhere)
                refused = False
            except sb.NodeUnresolved:
                refused = True
            check(f"C3: a mise that {label} is REFUSED (never a fallback to the whole tree)", refused)

        # a3 #32894 B1: enter, exit, enter again in the SAME dir; the second bridge is ready only when it ACCEPTS
        import socket as _so
        rd = run_tmp / "pg2"
        with sb.PgBridge(rd):
            pass
        b2 = sb.PgBridge(rd).__enter__()
        cs = _so.socket(_so.AF_UNIX, _so.SOCK_STREAM)
        try:
            cs.connect(str(rd / ".s.PGSQL.5432"))
            reuse_ok = True
        except OSError as e:
            reuse_ok = False
        finally:
            cs.close()
            b2.__exit__(None, None, None)
        check("B1: a bridge re-entered in the same dir accepts IMMEDIATELY (no stale-socket readiness)", reuse_ok, "")
        outside = sb.probe(out_cfg)
        ins = inside()
        check("probe ran inside the sandbox", "error" not in ins, str(ins.get("error")))
        bad = sb.verdict(ins, outside)
        check("the boundary holds: no refusal reason inside, every negative probe falsifiable outside", bad == [],
              str(bad))
        check("control (i): a pgpass tuple authenticates password-less OUTSIDE (a3 BC-4)",
              bool(outside["pgpass_reach"]["reached"]), str(outside["pgpass_reach"]))
        check("control (vi): NOTIFY/LISTEN works in the run's own clone THROUGH the bridge", ins.get("own_notify") is True, "")
        check("(vii): with the network unshared, NO host listener (geoloc :8766 among them) is reachable inside",
              ins.get("listeners_reached") == [] and any(":8766" in x for x in outside.get("listeners_reached", [])),
              f"inside={ins.get('listeners_reached')}")
        check("(vii): the internet is unreachable inside", ins.get("external_reached") is False, "")
        leak_net = sb.verdict(inside(share_net=True), outside)
        check("RED (vii): the SAME sandbox with the host network shared reaches the listeners → refusal names (vii)",
              any(r.startswith("(vii) host listeners") and ":8766" in r for r in leak_net), str(leak_net)[:300])
        # ── each probe FIRES on a planted breach ─────────────────────────────────────────────────────────────
        leak_env = sb.verdict(inside(ro_extra=[live / ".env"]), outside)
        check("RED (iv): the live .env bound in → refusal names (iv)", any(r.startswith("(iv) the live") for r in leak_env),
              str(leak_env))
        # (i) now needs TWO fences down: the pgpass entry is host=localhost, which libpq applies to a unix socket
        # only at its DEFAULT socket dir (the bridge's isn't), so with the network unshared there is no route.
        # The RED control therefore drops both: the real HOME with its .pgpass AND the host network.
        leak_home = sb.verdict(inside(ro_extra=[Path.home() / ".pgpass"], home=Path.home(), share_net=True), outside)
        check("RED (i): real HOME + its .pgpass + the host network → refusal names password-less reach",
              any(r.startswith("(i) password-less") for r in leak_home), str(leak_home))
        leak_rw = sb.verdict({**ins, "live_repo_writable": sb.probe(cfg)["live_repo_writable"]}, outside)
        check("RED (v): a world where the live repo IS writable → refusal names (v) (the outside probe sees it)",
              any(r.startswith("(v) the live repo is writable") for r in leak_rw), str(leak_rw))
        sock = Path("/run/docker.sock")
        if sock.exists():
            leak_dk = sb.verdict(inside(ro_extra=[sock]), outside)
            check("RED (iii): the docker socket bound in → refusal names (iii)",
                  any(r.startswith("(iii)") for r in leak_dk), str(leak_dk))
        # ── every VACUITY branch fires (pure: a negative probe with no positive control proves nothing) ─────
        good = {**ins}
        for name, patch_in, patch_out, want in (
                ("(i) VACUOUS", {}, {"pgpass_reach": {"reached": []}}, "(i) VACUOUS"),
                ("(iv) VACUOUS", {}, {"live_env_readable": False}, "(iv) VACUOUS"),
                ("(v) VACUOUS", {}, {"live_repo_writable": False}, "(v) VACUOUS"),
                ("(vi) VACUOUS", {"own_notify": False}, {}, "(vi) VACUOUS"),
                ("(vii) VACUOUS", {}, {"listeners_reached": []}, "(vii) VACUOUS")):
            v = sb.verdict({**good, **patch_in}, {**outside, **patch_out})
            check(f"vacuity: {name} is a refusal reason", any(r.startswith(want) for r in v), str(v))
        soft = f"bc_{os.getpid()}x1_nullacl"                                               # left UNhardened
        adm.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(soft)))
        leak_db = sb.verdict(inside(c={**cfg, "foreign_dbs": [hard, soft]}), outside)
        check("RED (vi): an unhardened database the run doesn't own → refusal names it",
              any(r.startswith("(vi) the run role") and soft in r for r in leak_db), str(leak_db))
    finally:
        try:
            bridge.__exit__(None, None, None)
        except Exception:
            pass
        if scope:
            scope.close()
        for db in (hard, soft):
            if db and adm.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db,)).fetchone():
                adm.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db)))
        shutil.rmtree(tmp, ignore_errors=True)
        adm.close()
    print(f"\n{'FAIL' if fails else 'PASS'}: branch_check sandbox ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
