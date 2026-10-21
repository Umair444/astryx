#!/usr/bin/env python3
"""Oracle: devtools/cog_add_org.py, adding an org to a cog (plan-11324 S3f S5). It runs the REAL tool in a child.

The real path brings a FIXTURE database (--dsn: no CREATE), with a never-created fxorg_ name as the registry's `db`,
the seam config.dsn allows in a cog. So no gate ever creates a non-fixture database. The positive CREATE DATABASE is
S6's rehearsal (stated limit); here its statement is printed by the dry-run, and an existing name is refused.

  A1 dry-run: rc 0, it prints CREATE DATABASE astryx_<key>, and NOTHING is made (no HOME, no registry file, no database)
  A2 the real path, --dsn a fixture: the HOME tree (marker, local.md = local.template.md, the shipped seed charter,
     homes/, var/); .env mode 600 with ASTRYX_ORG, the fixture's ASTRYX_DSN, a 64-hex ASTRYX_SECRET_KEY, an OBS_KEY,
     ASTRYX_URL empty, the OBS_KEY the primary's (one owner key for the cog); schema_applied's sha = sha256(schema.sql); PUBLIC CONNECT revoked; the registry written reads back
     (orgs.load) as two orgs, the derived primary (`primary` and `door`, its HOME this checkout) and the new org neither
  A3 onto an EXISTING registry: the primary's entry kept byte for byte, the new org added
  A4 refusals, each rc 2 with nothing made: a bad key; a HOME inside a git tree; a non-empty HOME; a database that
     exists (no --dsn); a port another org holds; a key already registered
  A5 no secret VALUE on any output (the admin DSN's password, the new keys); each org's key its own
  A6 a registry the authority refuses (a port for a stem that binds none) is refused at PLAN time, rc 2, with NOTHING
     made: no HOME (no .env, no key), no registry file, the brought database unstamped (a2 #60860 R-1)
  A7 the DSN the tool derives for a CREATEd org (with_db) is a postgresql:// URL that asyncpg connects with, from a
     key=value primary DSN too, on the named database, every other parameter kept (step 4 live, 10-19: a key=value
     DSN in lab's .env crash-looped the cog's gateway)
  A8 its shipped triggers (plan-10224 add-org-parity), with no Windows container named (the gate off; a PATH docker
     shim turns it on): A2's new HOME holds context_compact, pr_review, agent_heal and org_backup in triggers/seed, each
     the one source's text (astryx.pulse.shipped_triggers.shims). --reconcile: on A2's org every shim stands down and no
     file changes (idempotent); --dry-run writes nothing; on a HOME with no triggers, the gate on, all five go in (every
     state read BEFORE any write: windows_idle_stop's shim reads blind, and a blind file defers the next answers); a
     name another agent owns stands its shim down, and org_backup stands down when EITHER of its names is owned (an org
     with its own run_backup gets no second one); a blind file stands every shim down (deferred, never a guess); the
     primary, an unknown key, and an add's flags beside --reconcile are refused (rc 2)
  A9 its federation name (10224 NAMES): a name another org of the cog holds is refused (rc 2, nothing made), a
     malformed one too, and a free one plans
COG_ADD_SRC: a mutant devtools/cog_add_org.py (tests/mutants_cog_add_org.py). Exit 0 · 1 · 77 (no database here).
"""
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate, unavailable  # noqa: E402
gate('test_cog_add_org', REPO, deps=('psycopg', 'nacl', 'asyncpg'), env=False)   # the admin DSN may come by env (fixture.live_dsn)
from astryx.security.sqlguard.fixture import fixture_db, live_dsn  # noqa: E402

SRC = Path(os.environ.get("COG_ADD_SRC") or REPO / "devtools" / "cog_add_org.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def main():
    import psycopg
    from psycopg import sql
    from astryx import orgs
    try:
        admin = live_dsn()
    except LookupError as e:                     # no admin DSN: 77 on a committed-only tree, 1 on a live one (seed #61038)
        unavailable("test_cog_add_org", REPO, e)
    pid = os.getpid()
    key = f"fxlab{pid}"
    created = "astryx_" + key                    # the name A1's CREATE would take: dropped in finally if a mutant made it
    made9 = [f"fxorg_lab9{s}_{pid}" for s in "ab"]   # A9's refused arms, one database each: dropped if a mutant made one
    t = Path(tempfile.mkdtemp(prefix="cogadd-")).resolve()
    tool = t / "devtools" / "cog_add_org.py"     # the tool runs from a copy beside THIS tree's src/ (a mutant's seam)
    tool.parent.mkdir()
    shutil.copy(SRC, tool)
    for n in ("src", "local.template.md", "agents"):
        (t / n).symlink_to(REPO / n)

    owner = f"fx-owner-key-{pid}-{secrets.token_hex(6)}"   # the primary's OBS_KEY, by env (a one-org primary)

    # the new org's ports, HELD for the run (bound, never listening: nothing answers there, and no other process can
    # take them), never the runbook's defaults: a live cog on this host serves its lab on 18190/18091 (10-19)
    import socket
    held = []
    for _ in range(3):                       # [2]: the existing registry's primary, an org's port that nothing answers
        so = socket.socket()
        so.bind(("127.0.0.1", 0))
        held.append(so)
    own_ports = f"astryx-observatory-org={held[0].getsockname()[1]},astryx-canvas={held[1].getsockname()[1]}"

    def run(*args, dsn=admin, path=None, windows=f"fx-no-windows-{pid}"):
        if "--ports" not in args and "--reconcile" not in args:
            args = (*args, "--ports", own_ports)
        p = subprocess.run([sys.executable, str(tool), *args], capture_output=True, text=True, timeout=300,
                           env={"PATH": path or os.environ["PATH"], "HOME": os.environ.get("HOME", str(t)),
                                "ASTRYX_DSN": dsn, "ASTRYX_COG_REGISTRY": str(t / "no-host-registry.json"),
                                "OBS_KEY": owner, "WINDOWS_CONTAINER": windows})
        return p.returncode, p.stdout + p.stderr

    def db_exists(name):
        with psycopg.connect(admin, autocommit=True) as c:
            return bool(c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone())

    outs = []
    try:
        with fixture_db() as fx:
            print("A1 DRY-RUN: THE PLAN, NOTHING MADE")
            h1, o1 = t / "h1", t / "h1.cog.json"
            rc, out = run(key, "--home", str(h1), "--name", "lab.fixture.test", "--dry-run")
            outs.append(out)
            check("rc 0, and it prints CREATE DATABASE astryx_<key>", rc == 0 and f"CREATE DATABASE {created}" in out,
                  out[-400:])
            check("...and makes NOTHING: no HOME, no registry file, no database", not h1.exists() and not o1.exists()
                  and not db_exists(created), f"home={h1.exists()} out={o1.exists()}")

            print("\nA2 THE REAL PATH, A FIXTURE DATABASE BROUGHT BY --dsn")
            h2, o2 = t / "h2", t / "h2.cog.json"
            rdb = f"fxorg_lab_{pid}"
            prim_dsn = orgs.conninfo(admin)
            prim_dsn["dbname"] = f"fxorg_prim_{pid}"
            from psycopg.conninfo import make_conninfo
            with psycopg.connect(admin, autocommit=True) as c:   # open it first, so the tool's REVOKE is what closes it
                c.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO PUBLIC").format(sql.Identifier(fx["dbname"])))
            rc, out = run(key, "--home", str(h2), "--name", "lab.fixture.test", "--dsn", fx["url"], "--db", rdb,
                          dsn=make_conninfo(**prim_dsn))
            outs.append(out)
            check("rc 0", rc == 0, out[-500:])
            check("the HOME: a .astryx marker FILE, local.md = local.template.md, the shipped seed charter, homes/, var/",
                  (h2 / ".astryx").is_file() and (h2 / "local.md").read_bytes() == (REPO / "local.template.md").read_bytes()
                  and (h2 / "agents/seed/seed.md").read_bytes() == (REPO / "agents/seed/seed.md").read_bytes()   # org-home: the SHIPPED seed charter (tracked), compared as data
                  and (h2 / "homes").is_dir() and (h2 / "var").is_dir(), str(sorted(p.name for p in h2.iterdir()))
                  if h2.exists() else "no HOME")
            envf = h2 / ".env"
            e = dict(ln.split("=", 1) for ln in envf.read_text().splitlines() if "=" in ln) if envf.exists() else {}
            check(".env mode 600", envf.exists() and stat.S_IMODE(envf.stat().st_mode) == 0o600,
                  oct(envf.stat().st_mode) if envf.exists() else "absent")
            check(".env: ASTRYX_ORG, the fixture's ASTRYX_DSN, a 64-hex ASTRYX_SECRET_KEY, an OBS_KEY, ASTRYX_URL empty",
                  e.get("ASTRYX_ORG") == "lab.fixture.test" and orgs.db_of(e.get("ASTRYX_DSN", "")) == fx["dbname"]
                  and len(e.get("ASTRYX_SECRET_KEY", "")) == 64 and all(ch in "0123456789abcdef" for ch in
                                                                        e.get("ASTRYX_SECRET_KEY", "x"))
                  and len(e.get("OBS_KEY", "")) >= 20 and e.get("ASTRYX_URL") == "", str(sorted(e)))
            check(".env: OBS_KEY is the PRIMARY's (one owner key opens every room of the cog, owner 10-19)",
                  e.get("OBS_KEY") == owner, "a key of its own")
            with psycopg.connect(fx["url"], autocommit=True) as c:
                stamp = c.execute("SELECT sha FROM schema_applied WHERE id = 1").fetchone()
                pub = c.execute("SELECT has_database_privilege('public', current_database(), 'CONNECT')").fetchone()[0]
            want = hashlib.sha256((REPO / "src/astryx/sql/schema.sql").read_bytes()).hexdigest()
            check("schema_applied's sha is sha256(schema.sql)", stamp and stamp[0] == want, str(stamp))
            check("PUBLIC CONNECT revoked on it (granted before the run: the tool's REVOKE closed it)", pub is False, str(pub))
            got = orgs.load({orgs.ENV: str(o2)}) if o2.exists() else {}
            check("the registry reads back (orgs.load): the derived primary (its HOME this checkout, primary and door) "
                  "and the new org (neither)", set(got) == {"astryx", key} and got["astryx"]["primary"]
                  and got["astryx"]["door"] and got["astryx"]["home"] == (t).resolve()
                  and not got[key]["primary"] and not got[key]["door"] and got[key]["db"] == rdb,
                  str({k: (str(v["home"]), v["primary"], v["door"]) for k, v in got.items()}))

            print("\nA3 ONTO AN EXISTING REGISTRY")
            ex = t / "existing.json"
            prim = {"home": str(t / "prim-home"), "db": "fxorg_existing_p", "primary": True, "door": True,
                    "ports": {"astryx-observatory-org": held[2].getsockname()[1], "astryx-canvas": 8091}}
            ex.write_text(json.dumps({"orgs": {"astryx": prim}}))
            h3, o3 = t / "h3", t / "h3.cog.json"
            rc, out = run(key, "--home", str(h3), "--name", "lab.fixture.test", "--dsn", fx["url"], "--db",
                          f"fxorg_lab3_{pid}", "--registry", str(ex))
            outs.append(out)
            raw = json.loads(o3.read_text())["orgs"] if o3.exists() else {}
            check("the primary's entry kept byte for byte, the new org added", rc == 0 and raw.get("astryx") == prim
                  and key in raw, out[-300:])
            k3 = dict(ln.split("=", 1) for ln in (h3 / ".env").read_text().splitlines() if "=" in ln) if (h3 / ".env").exists() else {}
            check("each org's key is its OWN (A2's and A3's ASTRYX_SECRET_KEY differ: generated, never a constant)",
                  k3.get("ASTRYX_SECRET_KEY") and k3.get("ASTRYX_SECRET_KEY") != e.get("ASTRYX_SECRET_KEY"))

            print("\nA6 A REGISTRY THE AUTHORITY REFUSES: REFUSED BEFORE ANYTHING IS MADE")
            h6, o6 = t / "h6", t / "h6.cog.json"
            with fixture_db() as fx6:                     # a FRESH database: no stamp, so "untouched" is observable
                rc, out = run(key, "--home", str(h6), "--name", "x", "--dsn", fx6["url"], "--db", f"fxorg_lab6_{pid}",
                              "--registry", str(ex), "--ports", "astryx-pulse=18001")     # a stem that binds no port
                with psycopg.connect(fx6["url"], autocommit=True) as c:
                    has = c.execute("SELECT to_regclass('schema_applied') IS NOT NULL").fetchone()[0] and bool(
                        c.execute("SELECT 1 FROM schema_applied").fetchone())
            outs.append(out)
            check("a port for a stem that binds none: refused by the authority at PLAN time, rc 2 (a2 #60860 R-1)",
                  rc == 2 and "refused by the authority" in out, f"rc {rc} {out[-200:]}")
            check("...and NOTHING made: no HOME (no .env, no key), no registry file, the brought database unstamped",
                  not h6.exists() and not o6.exists() and not o6.with_name(o6.name + ".tmp").exists() and not has,
                  f"home={h6.exists()} out={o6.exists()} stamped={has}")

            print("\nA4 REFUSALS: rc 2, NOTHING MADE")
            (t / "full").mkdir()
            (t / "full" / "x").write_text("x")
            cases = [
                ("a bad key", "is not a registry key", ["Bad_Key", "--home", str(t / "r1"), "--name", "x", "--dry-run"], t / "r1"),
                ("a HOME inside a git tree", "inside the git tree", [key, "--home", str(REPO / "homes" / f"fxr{pid}"), "--name", "x"],   # org-home: a path INSIDE the git tree on purpose (the refusal), never created
                 REPO / "homes" / f"fxr{pid}"),   # org-home: the same path, checked never created
                ("a non-empty HOME", "is not empty", [key, "--home", str(t / "full"), "--name", "x", "--dsn", fx["url"]], None),
                ("a database that exists (no --dsn)", "already exists", [key, "--home", str(t / "r4"), "--name", "x", "--db", fx["dbname"]],
                 t / "r4"),
                ("a port another org holds (the authority refuses it)", "refused by the authority", [key, "--home", str(t / "r5"), "--name", "x", "--dsn", fx["url"],
                                              "--registry", str(ex), "--ports", f"astryx-observatory-org={held[2].getsockname()[1]}"], t / "r5"),   # held, and nothing answers there
                ("a key already registered", "already registered", ["astryx", "--home", str(t / "r6"), "--name", "x", "--dsn", fx["url"],
                                              "--registry", str(ex)], t / "r6"),
            ]
            for why, reason, args, home in cases:      # each refused for ITS reason, never another's
                rc, out = run(*args)
                outs.append(out)
                check(f"{why}: rc 2, refused for its own reason ('{reason}'), nothing made", rc == 2 and reason in out
                      and (home is None or not home.exists()), f"rc {rc} {out[-200:]}")

            print("\nA5 NO SECRET VALUE ON ANY OUTPUT")
            pw = orgs.conninfo(admin).get("password") or ""
            secrets_ = [v for v in (pw, e.get("ASTRYX_SECRET_KEY", ""), e.get("OBS_KEY", "")) if len(v) >= 8]
            check("the admin DSN's password and the new org's keys appear in no output", secrets_
                  and not any(s in o for s in secrets_ for o in outs), "a secret value was printed")

            print("\nA7 THE DERIVED DSN IS A URL ASYNCPG CONNECTS WITH")
            import asyncio
            import importlib.util
            import asyncpg
            spec = importlib.util.spec_from_file_location("cog_add_org_a7", tool)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            base = orgs.conninfo(admin)
            for form, src in (("a URL", admin), ("key=value", make_conninfo(**base))):
                u = mod.with_db(src, fx["dbname"])
                got = orgs.conninfo(u)
                want = dict(base, dbname=fx["dbname"])

                async def cur(u=u):
                    c = await asyncpg.connect(u)
                    try:
                        return await c.fetchval("SELECT current_database()")
                    finally:
                        await c.close()
                try:
                    db_now = asyncio.run(cur())
                except Exception as ex:  # noqa: BLE001
                    db_now = f"{type(ex).__name__}"
                check(f"from {form}: a postgresql:// URL, every parameter kept, asyncpg connects on the named database",
                      u.startswith("postgresql://") and got == want and db_now == fx["dbname"],
                      f"url-form={u.startswith('postgresql://')} same={got == want} db={db_now}")

            print("\nA8 ITS SHIPPED TRIGGERS: ONE SOURCE, INSTALLED, RECONCILED DEFERENTIALLY")
            from astryx.pulse.shipped_triggers import shims
            trig = 'from astryx import trigger\n\n\n@trigger("*/5 * * * *", note="x")\ndef {}(ctx):\n    return None\n'
            four = {"context_compact", "pr_review", "agent_heal", "org_backup"}
            sd2 = h2 / "triggers" / "seed"
            got2 = {f.stem: f.read_text() for f in sd2.glob("*.py")} if sd2.is_dir() else {}
            check("A2's new HOME: triggers/seed holds context_compact, pr_review, agent_heal, org_backup (no Windows "
                  "container named), each the one source's text", set(got2) == four
                  and all(got2[s] == shims.SHIMS[s] for s in got2), str(sorted(got2)))
            before = {f.name: (f.read_bytes(), f.stat().st_mtime_ns) for f in sd2.glob("*.py")}
            rc, out = run("--reconcile", key, "--registry", str(o2))
            outs.append(out)
            check("--reconcile on A2's org: rc 0, every shim stands down (installed), no file changes (idempotent)",
                  rc == 0 and out.count("stand down trigger") == 4 and "install trigger" not in out
                  and {f.name: (f.read_bytes(), f.stat().st_mtime_ns) for f in sd2.glob("*.py")} == before, out[-500:])
            sd3 = h3 / "triggers"

            def clear():
                shutil.rmtree(sd3, ignore_errors=True)

            def seed3():
                d = sd3 / "seed"
                return {f.stem for f in d.glob("*.py")} if d.is_dir() else set()
            clear()
            rc, out = run("--reconcile", key, "--registry", str(o3), "--dry-run")
            check("--dry-run: rc 0, the plan printed, NOTHING written", rc == 0 and "would install trigger org_backup"
                  in out and not sd3.exists(), out[-300:])
            dshim = t / "dockershim"
            dshim.mkdir()
            (dshim / "docker").write_text('#!/bin/sh\n[ "$1" = inspect ] && [ "$2" = fxwin ] && exit 0\nexit 1\n')
            (dshim / "docker").chmod(0o755)
            rc, out = run("--reconcile", key, "--registry", str(o3), path=f"{dshim}:{os.environ['PATH']}",
                          windows="fxwin")
            outs.append(out)
            check("no triggers, a Windows container here: all FIVE go in (every state read before any write)",
                  rc == 0 and seed3() == four | {"windows_idle_stop"}, f"{sorted(seed3())} {out[-300:]}")
            clear()
            (sd3 / "steward").mkdir(parents=True)
            (sd3 / "steward" / "own_backup.py").write_text(trig.format("run_backup"))   # its OWN backup, no verify
            (sd3 / "medic").mkdir()
            (sd3 / "medic" / "heal.py").write_text(trig.format("agent_heal"))
            rc, out = run("--reconcile", key, "--registry", str(o3))
            outs.append(out)
            check("another agent's agent_heal stands its shim down, and org_backup stands down on EITHER name "
                  "(run_backup owned, run_restore_verify not): only context_compact and pr_review go in",
                  rc == 0 and seed3() == {"context_compact", "pr_review"} and "stand down trigger org_backup" in out
                  and "run_backup installed" in out, f"{sorted(seed3())} {out[-400:]}")
            clear()
            (sd3 / "x").mkdir(parents=True)
            (sd3 / "x" / "blind.py").write_text("if True:\n    import os\n")
            rc, out = run("--reconcile", key, "--registry", str(o3))
            check("a blind file: every shim stands down (deferred), none written", rc == 0 and not seed3()
                  and "deferred" in out and "install trigger" not in out, f"{sorted(seed3())} {out[-300:]}")
            clear()
            for why, args, reason in (("the primary", ["--reconcile", "astryx", "--registry", str(o3)], "primary"),
                                      ("an unknown key", ["--reconcile", "nosuch", "--registry", str(o3)], "not an org"),
                                      ("an add's flags beside it", ["--reconcile", key, "--home", str(h3)], "takes only")):
                rc, out = run(*args)
                check(f"--reconcile refuses {why}: rc 2 ('{reason}'), nothing written", rc == 2 and reason in out
                      and not sd3.exists(), f"rc {rc} {out[-200:]}")

            print("\nA9 ITS FEDERATION NAME (10224 NAMES): ONE ADDRESS PER ORG")
            h9a, h9b, h9c = (t / f"h9{s}" for s in "abc")   # one home per arm: an arm a mutant lets through makes
            # ITS home, so the next arm (the control above all) still asks its own question (a2 #61826 A-2)
            for _ in range(2):                    # A9's own held ports: A2's are its org's in o2, the authority refuses a reuse
                so = socket.socket()
                so.bind(("127.0.0.1", 0))
                held.append(so)
            p9 = f"astryx-observatory-org={held[-2].getsockname()[1]},astryx-canvas={held[-1].getsockname()[1]}"
            rc, out = run(key + "x", "--home", str(h9a), "--name", "lab.fixture.test", "--dsn", fx["url"], "--db",
                          made9[0], "--registry", str(o2), "--ports", p9)
            check("a name ANOTHER org of the cog holds (A2's lab.fixture.test): rc 2, refused naming that org, "
                  "nothing made", rc == 2 and "already the federation name of" in out and key in out
                  and not h9a.exists(), f"rc {rc} {out[-200:]}")
            rc, out = run(key + "x", "--home", str(h9b), "--name", "Lab.Fixture.Test", "--dsn", fx["url"], "--db",
                          made9[1], "--registry", str(o2), "--ports", p9)
            check("...its uppercase spelling: refused too (not a federation name)", rc == 2
                  and "not a federation name" in out and not h9b.exists(), f"rc {rc} {out[-200:]}")
            rc, out = run(key + "x", "--home", str(h9c), "--name", "lab9.fixture.test", "--registry", str(o2), "--dry-run",
                          "--ports", p9)
            check("control: a name no org holds plans (rc 0, dry-run)", rc == 0, f"rc {rc} {out[-200:]}")
    finally:
        try:
            with psycopg.connect(admin, autocommit=True) as c:      # only THIS run's unique names, if a mutant made one
                for db in (created, *made9):
                    c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db)))
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(t, ignore_errors=True)
        for so in held:
            so.close()


if __name__ == "__main__":
    from astryx.security.sqlguard.estate import unavailable
    from astryx.security.sqlguard.fixture import FixtureUnavailable
    try:
        main()
    except FixtureUnavailable as e:
        unavailable("test_cog_add_org", REPO, e)
    print()
    print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
          "cog_add_org: an org's own setup path, every step judged first, nothing made on a dry-run")
    sys.exit(1 if fails else 0)
