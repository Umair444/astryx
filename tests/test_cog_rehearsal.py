#!/usr/bin/env python3
"""The cog rehearsal (plan-11324 S3f S6): devtools/cog_add_org.md's steps 2 to 6, end to end, on a FIXTURE registry,
before anything is written to /etc.

    venv/bin/python tests/test_cog_rehearsal.py      (also run by devtools/check.sh)

Every other cog oracle proves one part on a registry it writes by hand. This one runs the owner's path in order, each
step consuming what the step before it WROTE, so the seams between them are what it proves:

  R1 step 2, the plan: `cog_add_org.py --dry-run` on a one-org host (no registry) names every target (CREATE, schema,
     REVOKE) as the FIXTURE database, and makes nothing. It runs BEFORE the real path, so a tool whose DSN swap went
     wrong is refused here, before any statement reaches a database.
  R2 step 2, the real path, on a FIXTURE database brought by --dsn (the registry names a never-created fxorg_ db:
     test_cog_add_org A2's seam): the primary's registry entry is DERIVED (the checkout, primary + door), and
     verify_lab() judges the made thing: the .env (600, its keys), schema_applied = sha256(schema.sql), PUBLIC
     CONNECT revoked, the registry read back through orgs.load (lab neither primary nor door), no secret value on
     any output.
  R3 step 4.3, the units, from THAT registry, three ways (`./init.sh units`, UNITS_DIR, never units/): the primary's
     are its one-org set byte for byte but the observatory (the front's now) and the gateway (the cog's), plus
     astryx-observatory-org; lab's are all @<lab>, through orgenv, on its registry ports; the cog's are the gateway
     (naming the registry) and the front. No file is in two sets.
  R4 step 5, the residents' servers: the primary keeps the "default" tmux socket, lab is -L ax-<lab>.
  R5 the double spawn (a2 #60783; the runbook's §6): on the primary's live-shaped seats (its residents on the
     default socket), agent_heal under the written registry plans NOTHING. The same registry with S1 reverted (no
     primary, so no door) moves the primary to -L ax-<key>, where no server runs, and agent_heal plans every seat:
     the negative control that shows the arm can see the double spawn it guards against.
  R6 the drift gates on a registry host: seed's service_deploy_drift resolves lab's REAL @lab observatory ExecStart
     (orgenv-prefixed) to the service's own module, never orgenv.py (seed #61005/#61007), and the primary's plain one
     likewise (positive control); `./init.sh doctor` serves the primary (S7, seed #61003/#61017) and refuses lab,
     naming lab's own vitals.sh and smoke.sh (tests/test_doctor_cog.py holds S7's arms).

The HTTP checks of §6 (/api/cog, /o/<org>/, the gateway's to_org) are test_observatory_cog's and test_gateway_cog's,
on fixtures; this file starts no service and binds no port (lab's ports are free ones, declared only).

THE POSITIVE CREATE IS NOT A GATE, BY LAW (seed #61010/#61011). No gate creates a non-fixture database; orgs.load
refuses an org db that is a fixture's (a registry must never name what the reaper may drop); and cog_add_org judges
the merged registry BEFORE its CREATE. So any --db the tool would CREATE is one a gate may not make. R1 rehearses the
CREATE path's plan; the CREATE itself is proven by the REAL step 2 (seed runs it, reversible, before /etc), then:

    venv/bin/python tests/test_cog_rehearsal.py --verify-lab <lab HOME> <its --out> [<step 2's output, teed>]

which runs verify_lab() (the same judgement R2 makes on the fixture) against the database step 2 CREATED. Read-only.

Seams for the tests/mutants_cog_rehearsal_*.py files: COG_ADD_SRC (the tool, written over the fixture checkout's copy),
SERVICE_DEPLOY_DRIFT_SRC (seed's trigger, read in place), and org_home_fixture's ORG_HOME_ORGS_SRC, ORG_HOME_INIT_SRC
and ORG_HOME_HEAL_SRC (OrgHomes writes each over its file in the fixture checkout, where every child runs). Exit 0 · 1 · 77 (no tmux, no fixture DSN, no git checkout).
"""
import json
import os
import re
import runpy
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_cog_rehearsal', REPO, deps=('psycopg', 'nacl'), env=False)   # the admin DSN may come by env
from astryx.security.sqlguard.fixture import fixture_db, live_dsn  # noqa: E402
from org_home_fixture import FixtureUnavailable, OrgHomes, kill_server, private_tmux  # noqa: E402
from org_estate import astryx_call  # noqa: E402

ESTATE = astryx_call(REPO, "paths", "estate", __file__)   # this tree on one org, its HOME on several (S3a)

fails = []

HEAL = r"""
import importlib.util, json, sys
sys.path.insert(0, sys.argv[1] + "/src")
s = importlib.util.spec_from_file_location("heal_r", sys.argv[1] + "/src/astryx/pulse/shipped_triggers/agent_heal.py")
h = importlib.util.module_from_spec(s); s.loader.exec_module(h)
want, have = h.expected(), h.bodies()
r = h.heal({}, now=1e9, do=lambda *a, **k: (True, "recorded, never launched"))
print(json.dumps({"want": want, "have": None if have is None else sorted(have), "healed": r["healed"]}))
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


HELD = []      # the fixture's ports, HELD for the whole run (bound, never listening): no concurrent gate can take one,
#                and a connect is refused, so cog_add_org's "answering" probe reads it free. Closed in main's finally.


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    HELD.append(s)
    return s.getsockname()[1]


def files(d: Path) -> dict:
    return {p.name: p.read_bytes() for p in d.iterdir()} if d.is_dir() else {}


def unit_props(text: str) -> dict:
    """A rendered unit's ExecStart and WorkingDirectory, as `systemctl show` reports them (argv[]=… ;)."""
    ex = next((ln.split("=", 1)[1] for ln in text.splitlines() if ln.startswith("ExecStart=")), "")
    wd = next((ln.split("=", 1)[1] for ln in text.splitlines() if ln.startswith("WorkingDirectory=")), "")
    return {"ExecStart": f"{{ path={ex.split()[0] if ex else ''} ; argv[]={ex} ; ignore_errors=no }}",
            "WorkingDirectory": wd}


def verify_lab(home: Path, out: Path, key: str, admin: str, outs: list, regdb: str | None = None,
               schema: Path = REPO / "src" / "astryx" / "sql" / "schema.sql") -> dict:
    """The org cog_add_org made, judged: its .env, its database (as the .env's DSN names it), the registry it wrote.
    R2 calls it on the fixture-backed lab; --verify-lab on the real step 2's. Read-only. Returns the registry's orgs."""
    import hashlib
    import psycopg
    from psycopg.conninfo import make_conninfo
    from astryx import orgs
    envf = home / ".env"
    e = {}
    if envf.exists():
        e = dict(ln.split("=", 1) for ln in envf.read_text().splitlines() if "=" in ln and not ln.startswith("#"))
    dbn = orgs.db_of(e.get("ASTRYX_DSN", "")) if e.get("ASTRYX_DSN") else None
    check(".env mode 600: ASTRYX_ORG, ASTRYX_DSN, a 64-hex ASTRYX_SECRET_KEY, an OBS_KEY, ASTRYX_URL empty",
          envf.exists() and stat.S_IMODE(envf.stat().st_mode) == 0o600 and bool(e.get("ASTRYX_ORG")) and bool(dbn)
          and re.fullmatch(r"[0-9a-f]{64}", e.get("ASTRYX_SECRET_KEY", "")) is not None
          and len(e.get("OBS_KEY", "")) >= 20 and e.get("ASTRYX_URL") == "", str(sorted(e)))
    if dbn:
        with psycopg.connect(admin, autocommit=True) as c:
            there = bool(c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbn,)).fetchone())
        check(f"its database exists ({'the fixture' if regdb else dbn})", there)
        if there:
            want = hashlib.sha256(schema.read_bytes()).hexdigest()
            with psycopg.connect(make_conninfo(admin, dbname=dbn)) as c:
                stamp = c.execute("SELECT sha FROM schema_applied WHERE id = 1").fetchone()
                pub = c.execute("SELECT has_database_privilege('public', current_database(), 'CONNECT')").fetchone()[0]
            check("schema.sql applied whole and stamped (schema_applied = sha256(schema.sql))",
                  bool(stamp) and stamp[0] == want, str(stamp))
            check("PUBLIC CONNECT revoked on it", pub is False, str(pub))
    raw = {}
    try:
        orgs.load({orgs.ENV: str(out)})
        raw = json.loads(out.read_text())["orgs"]
    except Exception as x:  # noqa: BLE001
        check("the registry it wrote reads back through orgs.load", False, f"{type(x).__name__}: {x}")
    if raw:
        me = raw.get(key, {})
        prims = [k for k, v in raw.items() if v.get("primary") is True]
        check("the registry: lab is in it, neither primary nor door, its HOME and its db; exactly one OTHER org primary",
              bool(me) and "primary" not in me and "door" not in me and Path(me.get("home", "/")) == home.resolve()
              and me.get("db") == (regdb or dbn) and len(prims) == 1 and prims[0] != key, json.dumps(raw)[:600])
    pw = orgs.conninfo(admin).get("password") or ""
    secrets_ = [v for v in (pw, e.get("ASTRYX_SECRET_KEY", ""), e.get("OBS_KEY", "")) if len(v) >= 8]
    if outs:
        check("no secret VALUE on any output (the admin password, lab's new keys)", len(secrets_) >= 2
              and not any(s in o for s in secrets_ for o in outs), f"{len(secrets_)} secrets known")
    else:
        print("  SKIP  no secret on the output: no output given (pass step 2's teed output): NOT verified")
    return raw


def verify_main(argv) -> int:
    if len(argv) not in (3, 4):
        print("usage: test_cog_rehearsal.py --verify-lab <lab HOME> <its --out registry> [<step 2's output>]")
        return 2
    home, out = Path(argv[1]).resolve(), Path(argv[2])
    outs = [Path(argv[3]).read_text(errors="replace")] if len(argv) == 4 else []
    key = next((k for k, v in json.loads(out.read_text())["orgs"].items()
                if Path(v.get("home", "/")).resolve() == home), "") if out.exists() else ""
    print(f"VERIFY-LAB {home} (key {key or '?'}), read-only")
    verify_lab(home, out, key, live_dsn(), outs)
    print()
    if fails:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
        return 1
    print("ALL PASS")
    return 0


def main():
    if not shutil.which("tmux"):
        print("SKIP (77): no tmux")
        return 77
    tdir = private_tmux()             # every server here, "default" included, is private: never the host's residents
    try:
        fx = OrgHomes().__enter__()
    except FixtureUnavailable as e:
        shutil.rmtree(tdir, ignore_errors=True)
        print(f"SKIP (77): {e}")
        return 77
    import contextlib
    import psycopg
    admin = live_dsn()
    pid = os.getpid()
    lab, prim = f"fxlab{pid}", f"fxprim{pid}"
    plan_db, reg_db = f"fxorg_plan_{pid}", f"fxorg_lab_{pid}"   # NAMES only: never created (dry-run; the --dsn seam)
    co = fx.co
    py = str(co / "venv" / "bin" / "python")
    if os.environ.get("COG_ADD_SRC"):
        (co / "devtools" / "cog_add_org.py").write_bytes(Path(os.environ["COG_ADD_SRC"]).read_bytes())
    etc = fx.t / "etc" / "cog.json"   # the fixture's /etc/astryx/cog.json: absent until step 4.2 installs it
    home = fx.t / "orgs" / "lab"
    out = fx.t / "lab.cog.json"
    pobs, pcan = free_port(), free_port()
    outs = []

    def tool(*args):
        p = subprocess.run([py, str(co / "devtools" / "cog_add_org.py"), lab, "--home", str(home), "--name",
                            "lab.fixture.test", "--ports", f"astryx-observatory-org={pobs},astryx-canvas={pcan}",
                            "--primary-key", prim, "--out", str(out), *args],
                           capture_output=True, text=True, timeout=300, cwd=co,
                           env={**fx.env(ASTRYX_COG_REGISTRY=str(etc)), "ASTRYX_DSN": admin})
        outs.append(p.stdout + p.stderr)
        return p.returncode, p.stdout + p.stderr

    def db_exists(name):
        with psycopg.connect(admin, autocommit=True) as c:
            return bool(c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone())

    def units(env_over, d):           # under the registry step 2 WROTE (installed at etc), never the fixture's own
        r = subprocess.run(["bash", "init.sh", "units"], cwd=co, capture_output=True, text=True, timeout=180,
                           env={**fx.env(**{"ASTRYX_COG_REGISTRY": str(etc), **env_over}), "UNITS_DIR": str(d)})
        return r, files(d)

    stack = contextlib.ExitStack()
    try:
        print("R1 STEP 2, THE PLAN: --dry-run of the CREATE path on a one-org host, every target its --db, nothing made")
        rc, o = tool("--db", plan_db, "--dry-run")
        targets = {"CREATE": re.search(r"CREATE DATABASE (\S+) on", o), "schema": re.search(r"apply schema\.sql .*? to "
                   r"\S+/(\S+) and stamp", o), "REVOKE": re.search(r"REVOKE CONNECT ON DATABASE (\S+) FROM PUBLIC", o)}
        named = {k: m.group(1) if m else None for k, m in targets.items()}
        check("rc 0; CREATE, the schema and the REVOKE each name --db", rc == 0 and set(named.values()) == {plan_db},
              f"rc {rc} {named} {o[-400:]}")
        check("...and nothing is made: no database, no HOME, no registry file, no /etc", not db_exists(plan_db)
              and not home.exists() and not out.exists() and not etc.exists())
        if rc or set(named.values()) != {plan_db}:
            print("  (the real path is NOT run: its plan names another database)")
            return 1

        print("\nR2 STEP 2, THE REAL PATH (a fixture database by --dsn; the positive CREATE is step 2's own, seed "
              "#61011): the derived registry")
        fxdb = stack.enter_context(fixture_db())
        with psycopg.connect(admin, autocommit=True) as c:   # opened first, so the tool's REVOKE is what closes it
            c.execute(f'GRANT CONNECT ON DATABASE "{fxdb["dbname"]}" TO PUBLIC')
        rc, o = tool("--dsn", fxdb["url"], "--db", reg_db)
        check("rc 0", rc == 0, o[-500:])
        raw = verify_lab(home, out, lab, admin, outs, regdb=reg_db, schema=co / "src" / "astryx" / "sql" / "schema.sql") if rc == 0 else {}
        check("the primary is DERIVED from a one-org host: this checkout, its key, primary + door",
              bool(raw) and raw.get(prim, {}).get("home") == str(co) and set(raw) == {prim, lab}, json.dumps(raw)[:400])
        check("lab's ports are the ones it was given, never a cog port (8090, 8845)",
              bool(raw) and raw[lab].get("ports") == {"astryx-observatory-org": pobs, "astryx-canvas": pcan})
        if not raw:
            return 1
        # --verify-lab, the mode seed runs on the REAL step 2, driven here end to end on the fixture lab: every check
        # reached, and exactly ONE fails, the registry's db, because the --dsn seam names a never-created fxorg_ db
        # there while the .env binds the fixture's (the real step 2 has one name for both)
        log = fx.t / "step2.log"
        log.write_text(outs[-1])
        vm = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--verify-lab", str(home), str(out), str(log)],
                            capture_output=True, text=True, timeout=120, env={**os.environ})
        vf = [ln for ln in vm.stdout.splitlines() if ln.startswith("  FAIL")]
        check("--verify-lab on the fixture lab: rc 1, and its one FAIL is the seam's registry db (every check reached)",
              vm.returncode == 1 and len(vf) == 1 and "the registry: lab is in it" in vf[0]
              and vm.stdout.count("  PASS") == 5, vm.stdout[-600:] + vm.stderr[-200:])

        print("\nR3 STEP 4.3, THE UNITS FROM THAT REGISTRY, THREE WAYS (`./init.sh units`, UNITS_DIR only)")
        etc.parent.mkdir(parents=True)
        shutil.copy(out, etc)                                  # step 4.2's install, to the fixture's /etc
        r1, one = units({"ASTRYX_COG_REGISTRY": str(fx.t / "no-registry" / "cog.json")}, fx.t / "u_one")
        rp, pu = units({"ASTRYX_HOME": str(co)}, fx.t / "u_prim")
        rl, lu = units({"ASTRYX_HOME": str(home)}, fx.t / "u_lab")
        rc_, cu = units({}, fx.t / "u_cog")
        check("each render rc 0 (one org, the primary, lab, the cog's)", not any(r.returncode for r in (r1, rp, rl, rc_))
              and one and pu and lu and cu, " | ".join(f"{r.returncode} {r.stderr[-160:]}" for r in (r1, rp, rl, rc_)))
        want = (set(one) - {"astryx-observatory.service", "astryx-gateway.service"}) | {"astryx-observatory-org.service"}
        check("the primary: its one-org set, the observatory and gateway out, astryx-observatory-org in",
              set(pu) == want, f"got {sorted(pu)} want {sorted(want)}")
        diff = sorted(n for n in set(pu) & set(one) if pu[n] != one[n])
        check("...and every file it shares with the one-org render is byte-identical (no orgenv, plain names)",
              not diff, str(diff))
        po = pu.get("astryx-observatory-org.service", b"").decode()
        check("its observatory backend on its registry port (8190, derived), its HOME, no orgenv",
              "--port 8190" in po and f"Environment=ASTRYX_HOME={co}\n" in po and "orgenv" not in po, po[-300:])
        lsvc = {k: v.decode() for k, v in lu.items() if k.endswith(".service")}
        check("lab: every file is @<lab>, every service through orgenv with lab's HOME", lu
              and all(f"@{lab}." in k for k in lu) and lsvc
              and all(f"orgenv.py exec --home {home.resolve()} --" in v for v in lsvc.values()), str(sorted(lu)))
        lo = lsvc.get(f"astryx-observatory-org@{lab}.service", "")
        lc = lsvc.get(f"astryx-canvas@{lab}.service", "")
        check("lab's observatory and canvas bind its registry ports", f"--port {pobs}" in lo and str(pcan) in lc,
              (lo[-200:], lc[-200:]))
        gw = cu.get("astryx-gateway.service", b"").decode()
        check("the cog's: the gateway naming the registry, never a HOME, and the front",
              set(cu) >= {"astryx-gateway.service", "astryx-observatory.service"}
              and f"Environment=ASTRYX_COG_REGISTRY={etc}\n" in gw and "ASTRYX_HOME" not in gw, str(sorted(cu)))
        sets = [set(pu), set(lu), set(cu)]
        check("no unit file is in two sets", not (sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2]))

        print("\nR4 STEP 5, THE RESIDENTS' SERVERS")
        def sock(h):
            return subprocess.run([py, "src/astryx/orgs.py", "socket"], cwd=co, capture_output=True, text=True,
                                  env=fx.env(ASTRYX_HOME=str(h), ASTRYX_COG_REGISTRY=str(etc))).stdout.strip()
        check("the primary keeps the default socket; lab is -L ax-<lab>",
              (sock(co), sock(home)) == ("default", f"ax-{lab}"), str((sock(co), sock(home))))

        print("\nR5 THE DOUBLE SPAWN (a2 #60783): the primary's seats live on the default socket")
        def heal(regf):
            p = subprocess.run([py, "-c", HEAL, str(co)], cwd=co, capture_output=True, text=True, timeout=60,
                               env=fx.env(ASTRYX_HOME=str(co), ASTRYX_COG_REGISTRY=str(regf)))
            try:
                return json.loads(p.stdout.strip().splitlines()[-1])
            except Exception:  # noqa: BLE001
                return {"error": (p.stdout + p.stderr)[-400:]}
        seats = heal(etc).get("want") or []
        for s in seats:
            subprocess.run(["tmux", "-L", "default", "new-session", "-d", "-s", f"ax-{s}", "sleep 600"],
                           capture_output=True)
        w = heal(etc)
        check(f"precondition: the primary has seats, each alive on the default socket ({seats})",
              bool(seats) and w.get("have") == sorted(seats), str(w))
        check("with S1 (the registry as written): agent_heal plans NOTHING on our org", w.get("healed") == [], str(w))
        rev = json.loads(etc.read_text())
        for k in ("primary", "door"):                          # door is the primary's alone: S1 reverted drops both
            rev["orgs"][prim].pop(k, None)
        revf = fx.t / "reverted.json"
        revf.write_text(json.dumps(rev))
        v = heal(revf)
        check("S1 reverted (no primary): the server it asks is empty, and agent_heal plans EVERY seat a second time",
              v.get("have") == [] and sorted(v.get("healed") or []) == sorted(seats)[:4], str(v))

        print("\nR6 THE DRIFT GATES ON A REGISTRY HOST")
        trig = Path(os.environ.get("SERVICE_DEPLOY_DRIFT_SRC") or ESTATE / "triggers" / "seed" / "service_deploy_drift.py")
        if trig.exists():
            g = runpy.run_path(str(trig), run_name="sdd_rehearsal")
            g["ROOT"] = co
            ent = g["_entry_file"]
            want_main = (co / "observatory" / "api" / "main.py").resolve()
            pe = ent(unit_props(pu.get("astryx-observatory-org.service", b"").decode()))
            le = ent(unit_props(lo))
            check("service_deploy_drift: the primary's plain observatory resolves to its main.py (positive control)",
                  pe[0] == want_main, str(pe))
            check("...and lab's REAL @lab observatory (orgenv-prefixed) to the SAME main.py, never orgenv.py",
                  le[0] == want_main, str(le))
        else:
            print(f"  SKIP  service_deploy_drift: {trig} absent (gitignored seed body; a clone): NOT verified here")
        shim = fx.t / "shim"                  # doctor's login check is a model call: a stub answers it
        shim.mkdir(exist_ok=True)
        (shim / "claude").write_text("#!/bin/sh\necho ok\n")
        (shim / "claude").chmod(0o755)
        dpath = f"{shim}{os.pathsep}{os.environ.get('PATH', '')}"
        r = subprocess.run(["bash", "init.sh", "doctor"], cwd=co, capture_output=True, text=True, timeout=600,
                           env=fx.env(ASTRYX_HOME=str(co), ASTRYX_COG_REGISTRY=str(etc), PATH=dpath))
        check("`./init.sh doctor` in the cog serves the PRIMARY (S7): it runs (no exit 3)", r.returncode != 3
              and "refusing" not in r.stderr, f"rc {r.returncode} {r.stderr[-200:]}")
        r = subprocess.run(["bash", "init.sh", "doctor"], cwd=co, capture_output=True, text=True, timeout=180,
                           env=fx.env(ASTRYX_HOME=str(home), ASTRYX_COG_REGISTRY=str(etc), PATH=dpath))
        check("...and refuses lab (exit 3), naming lab's own vitals.sh and smoke.sh (S7b, lab's doctor, is a stated limit)",
              r.returncode == 3 and "vitals.sh" in r.stderr and "smoke.sh" in r.stderr, f"rc {r.returncode} {r.stderr[-200:]}")
    finally:
        kill_server("default")
        for h in HELD:
            h.close()
        stack.close()                 # fixture_db drops its database (and its stamp lets the reaper collect a kill's)
        fx.__exit__(None, None, None)
        shutil.rmtree(tdir, ignore_errors=True)
    print()
    if fails:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(verify_main(sys.argv[1:]) if sys.argv[1:2] == ["--verify-lab"] else main())
