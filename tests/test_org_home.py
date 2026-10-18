#!/usr/bin/env python3
"""Oracle for plan-11324 S3a, THE ORG IS ITS HOME (design #58435 items 1-7; a1 BC-S1 #58437/#58439; a2 BC-S2
#58452/#58453/#58454; a3 BC-S3 #58597/#58598), on a TWO-org fixture registry and an ESTATE-FREE checkout
(tests/org_home_fixture.py). Every child runs from the fixture checkout's code, with a clean environment.

  H1 ABSENCE FAILS CLOSED: from cwd=/ and from the checkout, ASTRYX_HOME unset: config.dsn(), `bash -c 'source .env'`
     and a home.mjs read all exit non-zero, and open no connection.
  H2 THE RUNGS: the env rung binds B; the marker rung binds B from a non-git cwd; an UNregistered ASTRYX_HOME is
     refused; the checkout rung is never taken.
  H3 CORRECTION 2 (the disagreeing pair): ASTRYX_HOME=B with ASTRYX_DSN = A's database → non-zero, refused before
     any connection, in config.dsn(), in home.mjs, AND in a private resolver's replacement (pulse's import-time DSN:
     BC-S1(2)'s arm); a file-only one (econ._dsn) never consults the environment and binds B's own database. The same
     pair with a FIXTURE DSN connects (a real fixture database).
  H4 CORRECTION 1: (ii) an org whose database is the superuser's NAME is refused; (iii) with ASTRYX_DSN unset and
     PGHOST+PGUSER set, `psql ""` reaches no registry org's database; (i) the built environment holds no PG* name.
  H5 THE LAW IS THE ORG'S (BC-S2 arm a): spawn.sh --render for an org-B agent writes a CLAUDE.md whose law section
     is byte-equal to HOME-B/local.md, and the render FAILS when B has no local.md (A's law is never a fallback).
  H6 UNITS (BC-S3(2)): the units B renders run through the builder, carry ASTRYX_HOME=B, no PassEnvironment, no
     ImportEnvironment, no PG*, and no EnvironmentFile but B's own .env.
  H7 A MALFORMED REGISTRY FAILS, never reads as absent: config.dsn exits 1 (not a LookupError skip), home.mjs throws,
     spawn refuses, and the guards' predicate exits 2 even when judging it CRASHES (never 1, which reads one org).
  H8 ONE ORG: with no registry (and with a ONE-entry registry) orgs.multi is false and the resolver is the old one.
  H9 BACKUP IS THE ORG'S (BC-S2 arm b): scripts/backup.sh run for org A (pg_dump/pg_dumpall/pg_isready are PATH
     shims: no real dump) dumps A's DSN into HOME-A/backups and rotates ONLY A's: B's dumps are untouched (names,
     sizes, mtimes), and the checkout gets no backups/. Positive control: A's own old dumps WERE rotated.
Seams: org_home_fixture.SEAMS (a mutant subject copied over its file in the checkout): ORG_HOME_CONFIG_SRC,
ORG_HOME_PATHS_SRC, ORG_HOME_ORGS_SRC, ORG_HOME_MJS_SRC, ORG_HOME_SPAWN_SRC, ORG_HOME_INIT_SRC, ORG_HOME_BACKUP_SRC.
Exit 0 · 1 · 77 (no DB / no git).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "src"))
from org_home_fixture import FixtureUnavailable, OrgHomes  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def py(fx, code, env, cwd):
    """`code` under the fixture checkout's interpreter and src/, as a separate process."""
    return subprocess.run([str(fx.co / "venv" / "bin" / "python"), "-B", "-c",
                           f"import sys; sys.path.insert(0, {str(fx.co / 'src')!r})\n" + code],
                          env=env, cwd=cwd, capture_output=True, text=True, timeout=60)


def node(fx, code, env, cwd):
    return subprocess.run(["node", "--input-type=module", "-e", code], env=env, cwd=cwd, capture_output=True,
                          text=True, timeout=60)


DSN_PROBE = "from astryx import config\nprint('DSN-OF', config.dsn())"
HOME_PROBE = "from astryx import paths\nh, why = paths.resolve_home()\nprint('HOME', h, why)"


def arms(fx):
    co, A, B = fx.co, fx.home["a"], fx.home["b"]
    homemjs = (co / "channel" / "home.mjs").as_uri()
    mjs_read = f"const m = await import({homemjs!r}); console.log('DSN-OF', m.dsn())"

    print("H1 ABSENCE FAILS CLOSED (ASTRYX_HOME unset):")
    for where, cwd in (("cwd=/", "/"), ("cwd=the estate-free checkout", str(co))):
        env = fx.env()
        r = py(fx, DSN_PROBE, env, cwd)
        check(f"[{where}] config.dsn() exits non-zero (no HOME), never a checkout DSN",
              r.returncode != 0 and "DSN-OF" not in r.stdout and "NoHome" in r.stderr, (r.stdout + r.stderr)[-300:])
        r = subprocess.run(["bash", "-c", "source .env"], env=env, cwd=cwd, capture_output=True, text=True)
        check(f"[{where}] `bash -c 'source .env'` exits non-zero (the checkout carries no .env)", r.returncode != 0)
        r = node(fx, mjs_read, env, cwd)
        check(f"[{where}] a home.mjs read throws", r.returncode != 0 and "DSN-OF" not in r.stdout
              and "registered HOME" in r.stderr, (r.stdout + r.stderr)[-300:])

    print("\nH2 THE RUNGS:")
    r = py(fx, HOME_PROBE, fx.env(ASTRYX_HOME=str(B)), "/")
    check("the env rung binds B (a registered HOME, whatever checkout runs the code)",
          r.stdout.strip() == f"HOME {B} env", (r.stdout + r.stderr)[-300:])
    r = py(fx, DSN_PROBE, fx.env(ASTRYX_HOME=str(B)), "/")
    check("...and config.dsn() reads B's .env", r.stdout.strip() == f"DSN-OF {fx.dsn['b']}", (r.stdout + r.stderr)[-300:])
    sub = B / "work" / "deeper"
    sub.mkdir(parents=True)
    r = py(fx, HOME_PROBE, fx.env(), str(sub))
    check("the marker rung binds B from a non-git cwd under it", r.stdout.strip() == f"HOME {B} marker",
          (r.stdout + r.stderr)[-300:])
    stray = fx.t / "stray"
    stray.mkdir()
    (stray / ".astryx").write_text("astryx home\n")
    r = py(fx, HOME_PROBE, fx.env(ASTRYX_HOME=str(stray)), str(stray))
    check("an UNregistered ASTRYX_HOME (and its marker) is refused", r.returncode != 0 and "NoHome" in r.stderr,
          (r.stdout + r.stderr)[-300:])
    r = py(fx, HOME_PROBE, fx.env(ASTRYX_HOME=str(co)), str(co))
    check("ASTRYX_HOME = the checkout itself is refused (the checkout rung never serves a multi-org host)",
          r.returncode != 0 and "NoHome" in r.stderr, (r.stdout + r.stderr)[-300:])

    print("\nH3 CORRECTION 2 (an environment DSN that disagrees with the HOME):")
    bad = fx.env(ASTRYX_HOME=str(B), ASTRYX_DSN=fx.dsn["a"])
    r = py(fx, DSN_PROBE, bad, "/")
    check("ASTRYX_HOME=B + A's DSN: config.dsn() exits non-zero with ForeignDSN, no DSN handed out",
          r.returncode != 0 and "ForeignDSN" in r.stderr and "DSN-OF" not in r.stdout, (r.stdout + r.stderr)[-300:])
    r = node(fx, mjs_read, bad, "/")
    check("...home.mjs refuses the same pair", r.returncode != 0 and "correction 2" in r.stderr,
          (r.stdout + r.stderr)[-300:])
    r = py(fx, "import astryx.pulse.pulse", bad, "/")
    check("...pulse.py's DSN (a1's private resolver, now routed) refuses it at import",
          r.returncode != 0 and "ForeignDSN" in r.stderr, (r.stdout + r.stderr)[-400:])
    r = py(fx, "from astryx.econ import econ\nprint('DSN-OF', econ._dsn())", bad, "/")
    # econ never read the environment (main: the checkout's .env only) and still doesn't (env_first=False): A's DSN in
    # its environment is never consulted, so the pair can't disagree. Its census site was the CHECKOUT read; routed, it
    # binds the HOME's own database (the estate-free checkout has no .env: a checkout read fails here)
    check("...econ._dsn (a file-only census site) binds HOME-B's database, never the environment's A",
          r.returncode == 0 and f"DSN-OF {fx.dsn['b']}" in r.stdout and fx.db["a"] not in r.stdout,
          (r.stdout + r.stderr)[-400:])
    from astryx.security.sqlguard.fixture import fixture_db
    with fixture_db() as f:
        code = DSN_PROBE + "\nimport psycopg\nwith psycopg.connect(config.dsn(), connect_timeout=5) as c:\n" \
               "    print('DB', c.execute('select current_database()').fetchone()[0])"
        r = py(fx, code, fx.env(ASTRYX_HOME=str(B), ASTRYX_DSN=f["dsn"]), "/")
        check("positive control: ASTRYX_HOME=B + a FIXTURE DSN connects (the oracles' binding still works)",
              r.returncode == 0 and "DB astryx_fx_" in r.stdout, (r.stdout + r.stderr)[-300:])

    print("\nH4 CORRECTION 1 (libpq's own fallbacks):")
    with OrgHomes(user_db_for="b") as fx2:
        r = py(fx2, DSN_PROBE, fx2.env(ASTRYX_HOME=str(fx2.home["b"])), "/")
        check("(ii) an org whose registry database is the superuser's NAME is refused",
              r.returncode != 0 and "correction 1" in r.stderr, (r.stdout + r.stderr)[-300:])
        r = py(fx2, DSN_PROBE, fx2.env(ASTRYX_HOME=str(fx2.home["a"])), "/")
        check("...for EVERY org on that registry (the default database is the whole host's)",
              r.returncode != 0 and "correction 1" in r.stderr, (r.stdout + r.stderr)[-300:])
    pg = {"PGHOST": fx.parts.get("host", "127.0.0.1"), "PGUSER": fx.parts["user"]}
    if fx.parts.get("port"):
        pg["PGPORT"] = str(fx.parts["port"])
    r = subprocess.run(["psql", "", "-w", "-tAc", "select current_database()"], env=fx.env(ASTRYX_HOME=str(B), **pg),
                       cwd="/", capture_output=True, text=True, timeout=30)
    reached = r.stdout.strip()
    check("(iii) ASTRYX_DSN unset, PGHOST+PGUSER set: `psql \"\"` reaches no registry org's database",
          reached not in (fx.db["a"], fx.db["b"]), reached or r.stderr[-200:])
    check("...positive control: what it reached (if anything) is libpq's user-named default, which (ii) forbids",
          reached in ("", fx.parts["user"]), reached)
    r = py(fx, "from astryx import orgenv\nfrom pathlib import Path\nimport os\n"
               f"e = orgenv.build(dict(os.environ), Path({str(B)!r}), 'fx-agent')\n"
               "print('NAMES', sorted(e))", fx.env(**pg, PGDATABASE="astryx", PGSERVICE="x", ASTRYX_HOME=str(B)), "/")
    names = r.stdout.split("NAMES", 1)[-1]
    check("(i) the built environment holds no PG* name, though PGHOST/PGUSER/PGDATABASE/PGSERVICE were inherited",
          r.returncode == 0 and "PG" not in names and "'ASTRYX_HOME'" in names, (r.stdout + r.stderr)[-300:])

    print("\nH5 THE LAW IS THE ORG'S (spawn.sh --render, an org-B agent):")
    spawn = co / "scripts" / "spawn.sh"
    (B / "agents" / "fxorgb-agent.md").write_text("# fxorgb-agent\nA fixture resident of fixture org b.\n")
    out = fx.t / "render-b"
    r = subprocess.run(["bash", str(spawn), "--render", "fxorgb-agent", str(out)], env=fx.env(ASTRYX_HOME=str(B)),
                       cwd="/", capture_output=True, text=True, timeout=120)
    md = (out / "CLAUDE.md").read_bytes() if (out / "CLAUDE.md").is_file() else b""
    law = md.split(b"## The law (local.md)\n", 1)[-1] if b"## The law (local.md)\n" in md else None
    check("the render succeeds for B's agent, found in B's agents/ (the checkout has none)", r.returncode == 0,
          (r.stdout + r.stderr)[-400:])
    check("its law section is byte-equal to HOME-B/local.md", law == (B / "local.md").read_bytes(), repr(law)[:200])
    mcp = json.loads((out / ".mcp.json").read_text()) if (out / ".mcp.json").is_file() else {}
    st = json.loads((out / ".claude" / "settings.json").read_text()) if (out / ".claude/settings.json").is_file() else {}
    check("its channel server and settings carry ASTRYX_HOME = B, never the checkout",
          mcp.get("mcpServers", {}).get("astryx", {}).get("env", {}).get("ASTRYX_HOME") == str(B)
          and st.get("env", {}).get("ASTRYX_HOME") == str(B), f"{mcp.get('mcpServers', {}).get('astryx')}")
    (A / "agents" / "fxorga-agent.md").write_text("# fxorga-agent\n")
    (A / "local.md").unlink()
    r = subprocess.run(["bash", str(spawn), "--render", "fxorga-agent", str(fx.t / "render-a")],
                       env=fx.env(ASTRYX_HOME=str(A)), cwd="/", capture_output=True, text=True, timeout=120)
    check("an org with NO local.md fails its render (never another org's law as a fallback)",
          r.returncode != 0 and not (fx.t / "render-a" / ".mcp.json").exists(), (r.stdout + r.stderr)[-300:])
    r = subprocess.run(["bash", str(spawn), "--render", "fxorgb-agent", str(fx.t / "render-x")],
                       env=fx.env(ASTRYX_HOME=str(A)), cwd="/", capture_output=True, text=True, timeout=120)
    check("org A cannot render org B's agent (the roster is the HOME's)", r.returncode != 0, (r.stdout + r.stderr)[-300:])

    print("\nH6 UNITS (init.sh units() for org B):")
    import re
    block = re.search(r"^units\(\) \{.*?^\}$", (co / "init.sh").read_text(), re.S | re.M).group(0)
    (co / "units_fx.sh").write_text("die() { echo \"$*\" >&2; exit 1; }\n_docker_host_ip() { echo 172.17.0.1; }\n"
                                    + block + "\nUNITS_DIR=units_fx_out units\n")
    r = subprocess.run(["bash", "-euo", "pipefail", "units_fx.sh"], env=fx.env(ASTRYX_HOME=str(B)), cwd=co,
                       capture_output=True, text=True, timeout=60)
    units = {p.name: p.read_text() for p in (co / "units_fx_out").glob("*")} if (co / "units_fx_out").is_dir() else {}
    svc = {n: u for n, u in units.items() if n.endswith(".service")}
    check("units() renders for B (rc 0, its own pulse and residents: S3b's @<org> files)", r.returncode == 0
          and {f"astryx-pulse@{fx.org['b']}.service", f"astryx-residents@{fx.org['b']}.service"} <= set(svc),
          f"rc {r.returncode} {sorted(units)} {r.stderr[-300:]}")
    exe = [ln for u in svc.values() for ln in u.splitlines() if ln.startswith("ExecStart=")]
    check("every ExecStart runs through the builder (orgenv exec --home B)",
          exe and all(f"src/astryx/orgenv.py exec --home {B} -- " in ln for ln in exe), "\n".join(exe)[:400])
    check("every unit carries ASTRYX_HOME=B and none the checkout",
          all(f"Environment=ASTRYX_HOME={B}\n" in u for u in svc.values())
          and not any(f"ASTRYX_HOME={co}\n" in u for u in svc.values()))
    flat = "\n".join(units.values())
    check("no PassEnvironment, no ImportEnvironment, no PG* anywhere",
          not re.search(r"^(PassEnvironment|ImportEnvironment)=|\bPG[A-Z]+=", flat, re.M))
    envfiles = re.findall(r"^EnvironmentFile=-?(.*)$", flat, re.M)
    check("the only EnvironmentFile a unit may name is B's own .env", all(e == f"{B}/.env" for e in envfiles),
          str(envfiles))

    print("\nH7 A MALFORMED REGISTRY FAILS (never read as absent):")
    good = fx.reg.read_text()
    fx.reg.write_text("{not json")
    try:
        r = py(fx, DSN_PROBE, fx.env(ASTRYX_HOME=str(B), ASTRYX_DSN=fx.dsn["b"]), "/")
        check("config.dsn() exits non-zero with RegistryError (a RuntimeError: never an oracle's LookupError skip)",
              r.returncode != 0 and "RegistryError" in r.stderr, (r.stdout + r.stderr)[-300:])
        r = node(fx, mjs_read, fx.env(ASTRYX_HOME=str(B)), "/")
        check("home.mjs throws on it", r.returncode != 0 and "malformed" in r.stderr, (r.stdout + r.stderr)[-200:])
        r = subprocess.run(["bash", str(spawn), "--render", "fxorgb-agent", str(fx.t / "render-m")],
                           env=fx.env(ASTRYX_HOME=str(B)), cwd="/", capture_output=True, text=True, timeout=60)
        check("spawn.sh refuses on it", r.returncode != 0 and not (fx.t / "render-m").exists(),
              (r.stdout + r.stderr)[-200:])
        # a registry the parser can't even finish (nested past python's recursion limit: RecursionError, not a
        # ValueError). Python's own crash exit is 1, which every shell guard reads as "one org": it must say 2.
        fx.reg.write_text('{"orgs": ' + "[" * 100000)
        r = subprocess.run([str(co / "venv" / "bin" / "python"), "-B", str(co / "src" / "astryx" / "orgs.py"), "multi"],
                           env=fx.env(), cwd="/", capture_output=True, text=True, timeout=60)
        check("the guards' predicate (orgs.py multi) REFUSES (2) a registry it can't judge, never 1 (= one org)",
              r.returncode == 2, f"rc {r.returncode} {r.stderr[-200:]}")
    finally:
        fx.reg.write_text(good)

    print("\nH8 ONE ORG:")
    one = fx.t / "one.json"
    one.write_text(json.dumps({"orgs": {"fxa": {"home": str(A), "db": fx.db["a"]}}}))
    for label, regpath in (("no registry file", fx.t / "absent.json"), ("a ONE-entry registry", one)):
        r = py(fx, "from astryx import orgs\nprint('MULTI', orgs.multi())\n" + HOME_PROBE,
               fx.env(ASTRYX_ORG_REGISTRY=str(regpath)), str(co))
        check(f"[{label}] multi is false and the checkout rung serves, as before",
              "MULTI False" in r.stdout and f"HOME {co} checkout" in r.stdout, (r.stdout + r.stderr)[-300:])


    print("\nH9 BACKUP IS THE ORG'S (scripts/backup.sh for org A, KEEP=3):")
    shim = fx.t / "pgshim"
    shim.mkdir()
    rec = fx.t / "pg_dump.dsn"
    for name, body in (("pg_isready", "exit 0"),
                       ("pg_dump", f'printf "%s" "$2" > {str(rec)!r}; printf "PGDMP fixture"'),
                       ("pg_dumpall", "echo 'CREATE ROLE fxorg_role;'")):
        (shim / name).write_text(f"#!/bin/sh\n{body}\n")
        (shim / name).chmod(0o755)
    olds = {}
    for o in ("a", "b"):
        bk = fx.home[o] / "backups"
        bk.mkdir()
        for i in range(6):
            for ext in ("dump", "state.tgz", "roles.sql"):
                f = bk / f"astryx-20200101T0000{i:02d}.{ext}"
                f.write_text(f"old {o} {i}\n")
                os.utime(f, (1577836800 + i, 1577836800 + i))
        olds[o] = {f.name: (f.stat().st_size, f.stat().st_mtime_ns) for f in bk.iterdir()}
    userhome = fx.t / "userhome"          # the backup tars $HOME's agent memory: never the real user's, here
    userhome.mkdir()
    r = subprocess.run(["bash", str(co / "scripts" / "backup.sh"), "3"], cwd="/", capture_output=True, text=True,
                       timeout=300, env=fx.env(ASTRYX_HOME=str(A), HOME=str(userhome), BACKUP_DB_WAIT_S="0",
                                               PATH=f"{shim}:{os.environ.get('PATH', '/usr/bin:/bin')}"))
    check("backup.sh for A exits 0", r.returncode == 0, (r.stdout + r.stderr)[-400:])
    check("it dumped A's database (the DSN it handed pg_dump is HOME-A's)",
          rec.is_file() and rec.read_text() == fx.dsn["a"], "differs" if rec.is_file() else "pg_dump never ran")
    bka = fx.home["a"] / "backups"
    dumps = sorted(bka.glob("astryx-*.dump"))
    check("A's new dump is in HOME-A/backups (and is the pg_dump archive)",
          any(not f.name.startswith("astryx-2020") and f.read_text().startswith("PGDMP") for f in dumps),
          str([f.name for f in dumps]))
    check("positive control: A's OWN old dumps were rotated (3 of each kind kept)",
          all(len(list(bka.glob(f"astryx-*.{ext}"))) == 3 for ext in ("dump", "state.tgz", "roles.sql")),
          str(sorted(f.name for f in bka.iterdir())))
    bkb = fx.home["b"] / "backups"
    now_b = {f.name: (f.stat().st_size, f.stat().st_mtime_ns) for f in bkb.iterdir()}
    check("B's dumps are untouched (every name, size and mtime)", now_b == olds["b"],
          f"{len(now_b)} vs {len(olds['b'])}")
    check("the checkout gets no backups/ (it holds no org's state)", not (co / "backups").exists())

def main():
    try:
        with OrgHomes() as fx:
            arms(fx)
    except FixtureUnavailable as e:
        print(f"SKIP (77): {e}")
        return 77
    return 1 if fails else 0


if __name__ == "__main__":
    rc = main()
    print()
    if rc == 1:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    elif rc == 0:
        print("org home: a multi-org host binds each process to ITS org's HOME, database and law, and refuses the rest")
    sys.exit(rc)
