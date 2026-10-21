#!/usr/bin/env python3
"""Oracle for a cog-safe `./init.sh doctor` (plan-11324 S3f S7; seed #61003, ruling #61017).

    venv/bin/python tests/test_doctor_cog.py      (also run by devtools/check.sh)

`./init.sh doctor first` is the first line of every breakage path, so the PRIMARY must keep it the day a cog forms.
doctor reads this checkout's estate (.env, local.md, backups/, units/, its residents); the primary's HOME IS the
checkout, so on a registry host doctor serves the primary (ASTRYX_HOME naming it, or the checkout's .astryx marker)
and only the primary. Against the REAL init.sh, in an estate-free fixture checkout whose units/ holds what a cog's
three renders write there (the primary's, another org's @<org> files, the cog's gateway and front):

  K1 the primary, by ASTRYX_HOME: doctor RUNS (no refusal), and its units-drift judges ONLY the primary's units:
     "no drift", and no other org's file, nor the cog's, is called an orphan (the footgun test_doctor_units_drift
     pins: an orphan line is a "regenerate would delete it" line; seed #61017 (a))
  K2 the primary, by the checkout's .astryx marker (no ASTRYX_HOME, the owner's own shell): the same
  K3 positive control: a stray plain unit of the primary's own in units/ IS still its orphan (the filter scopes, it
     never blinds)
  K4 its seat check asks the primary's server (orgs.tmux, the named default socket), never an inherited $TMUX's:
     run from another org's pane (TMUX naming that org's server, where an `ax-seed` lives), the primary's seed is
     "not resident"; alive on the primary's server, "alive" (seed #61017 (b); a2 #60794's class)
  K5 another org (ASTRYX_HOME naming it; S7b, goal 10224): doctor RUNS and reads ITS estate, its HOME: its .env (the
     checkout has none: its DSN is probed, never ".env missing"), its local.md and backups/ (the checkout's present
     ones are not its: removed from its HOME, "local.md missing" and "NO database backup"; given, "exists" and "fresh"),
     its units (its @<org> files only, no drift; the primary's plain files and the cog's never its orphans) and its
     server (-L ax-<org>: "not resident" while only the primary's ax-seed lives; alive on its own, "alive"); its
     remedy names ITS reconcile (cog_add_org --reconcile <key>), the primary's stays ./init.sh's
  K6 no org resolves (no ASTRYX_HOME, no marker): exit 3, refusing
  K7 one org (no registry): the filter is the COG's only: an @-named stray in units/ is an orphan, and an @-named
     unit systemd knows is undeclared, as before
  K8 (iii) "undeclared", the units SYSTEMD knows, is scoped as the disk side is: the primary's names its own plain stray
     and never another org's @ unit nor the cog's gateway and front (the 10-20 live false RED: forge #61494 (1));
     another org's names its own @<org> stray and never the primary's, the cog's, or a third org's. systemctl is a PATH
     shim whose list-unit-files answers a fixed list (every other verb is the host's, read-only), so no arm depends on
     what this host has installed
  K10 content drift (10224 UDRIFT): a unit on both sides whose BODY differs from its render is named STALE (the ✓ no-drift
      line withheld), with that org's own render as the remedy; another org's stale unit is never this one's
  K11 each org under its own federation name (10224 NAMES): distinct → ✓; the primary taking the other org's name (in
      another case) → ✗ naming the name and both orgs; a .env line not UTF-8 → still ✓, and ⚠ naming its file:line (ENVREAD)
  K9 the cog's primary from a checkout that isn't its HOME: exit 3 before any check (its estate reads are checkout-
     relative by identity)

`claude` is a PATH shim (doctor's login check would otherwise be a model call per run); tmux is private
(org_home_fixture.private_tmux). Seams: ORG_HOME_INIT_SRC (org_home_fixture writes the mutant over the fixture
checkout's init.sh). Exit 0 · 1 · 77 (no tmux, no systemd, no fixture).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from org_home_fixture import FixtureUnavailable, OrgHomes, kill_server, private_tmux  # noqa: E402

fails = []


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


def main():
    if not shutil.which("tmux"):
        print("SKIP (77): no tmux")
        return 77
    if not Path("/run/systemd/system").is_dir():
        print("SKIP (77): no systemd: doctor's units block is unreachable here")
        return 77
    tdir = private_tmux()
    try:
        fx = OrgHomes().__enter__()
    except FixtureUnavailable as e:
        shutil.rmtree(tdir, ignore_errors=True)
        print(f"SKIP (77): {e}")
        return 77
    try:
        co, A = fx.co, fx.home["a"]
        pid = os.getpid()
        prim, other = f"fxprim{pid}", fx.org["a"]
        reg = json.loads(fx.reg.read_text())
        reg["orgs"] = {prim: {"home": str(co), "db": f"fxorg_prim_{pid}", "primary": True, "door": True,
                              "ports": {"astryx-canvas": free_port(), "astryx-observatory-org": free_port()}},
                       other: reg["orgs"][other]}
        cog = fx.t / "cog.json"
        cog.write_text(json.dumps(reg))
        shim = fx.t / "shim"
        shim.mkdir()
        (shim / "claude").write_text("#!/bin/sh\necho ok\n")
        (shim / "claude").chmod(0o755)
        known = [f"astryx-fxoff.service", f"astryx-fxoff@{other}.service", f"astryx-canvas@{other}.service",
                 "astryx-fxzz@fxelse.service", "astryx-gateway.service", "astryx-observatory.service"]
        (shim / "systemctl").write_text("#!/bin/sh\n[ \"$1\" = list-unit-files ] && { printf '%s enabled\\n' "
                                        + " ".join(known) + "; exit 0; }\n"
                                        f"exec {shutil.which('systemctl') or '/usr/bin/systemctl'} \"$@\"\n")
        (shim / "systemctl").chmod(0o755)
        path = f"{shim}{os.pathsep}{os.environ.get('PATH', '')}"

        def env(**over):
            return fx.env(ASTRYX_COG_REGISTRY=str(cog), PATH=path, **over)

        units = co / "units"
        shutil.rmtree(units, ignore_errors=True)
        for who, e in (("the primary", env(ASTRYX_HOME=str(co))), (other, env(ASTRYX_HOME=str(A))), ("the cog", env())):
            r = subprocess.run(["bash", "init.sh", "units"], cwd=co, capture_output=True, text=True, timeout=180,
                               env={**e, "UNITS_DIR": str(units)})
            if r.returncode:
                check(f"setup: {who}'s units render into units/", False, r.stderr[-300:])
                return 1
        names = sorted(p.name for p in units.iterdir())
        foreign = [n for n in names if "@" in n] + [n for n in ("astryx-gateway.service", "astryx-observatory.service")
                                                    if n in names]
        check("setup: units/ holds the three renders (another org's @ files, the cog's gateway and front)",
              any("@" in n for n in names) and "astryx-gateway.service" in names, str(names))

        def doctor(e):
            r = subprocess.run(["bash", "init.sh", "doctor"], cwd=co, capture_output=True, text=True, timeout=600, env=e)
            return r.returncode, r.stdout, r.stderr

        def drift_lines(out):
            return [ln for ln in out.splitlines() if "units/" in ln or "orphan" in ln or "missing (derived" in ln]

        print("K1 THE PRIMARY, BY ASTRYX_HOME")
        rc, out, err = doctor(env(ASTRYX_HOME=str(co)))
        dl = drift_lines(out)
        check("doctor runs (no exit 3, no refusal)", rc != 3 and "refusing" not in err, f"rc {rc} {err[-300:]}")
        check("its units-drift: the primary's units, no drift", any("no drift" in ln for ln in dl), "\n".join(dl))
        bl = next((ln for ln in out.splitlines() if "NO database backup" in ln), "")
        check("its backup remedy is the one-org line, byte for byte (run ./scripts/backup.sh; the timer)",
              bl.endswith("(run ./scripts/backup.sh; enable astryx-backup.timer)") and "--reconcile" not in bl, bl)
        named = [n for n in foreign if any(n in ln for ln in dl)]
        check("...and no other org's file, nor the cog's, is named an orphan (none would be 'deleted')", not named,
              str(named))

        print("\nK2 THE PRIMARY, BY THE CHECKOUT'S .astryx MARKER (the owner's own shell, no ASTRYX_HOME)")
        (co / ".astryx").write_text("")
        try:
            rc, out, err = doctor(env())
            dl = drift_lines(out)
            check("doctor runs, no drift, no foreign orphan", rc != 3 and any("no drift" in ln for ln in dl)
                  and not [n for n in foreign if any(n in ln for ln in dl)], f"rc {rc} {err[-200:]} {dl}")
        finally:
            (co / ".astryx").unlink()

        print("\nK3 POSITIVE CONTROL: THE PRIMARY'S OWN STRAY IS STILL ITS ORPHAN")
        stray = units / "astryx-fxstray.service"
        stray.write_text("[Unit]\nDescription=a stray the generator never emits\n")
        try:
            rc, out, err = doctor(env(ASTRYX_HOME=str(co)))
            check("astryx-fxstray.service is named an orphan", any("orphan" in ln and "astryx-fxstray.service" in ln
                                                                    for ln in out.splitlines()), "\n".join(drift_lines(out)))
        finally:
            stray.unlink()

        print("\nK10 CONTENT DRIFT (10224 UDRIFT): A UNIT WHOSE NAME MATCHES BUT WHOSE BODY IS STALE")
        prim_files = [n for n in names if "@" not in n and n not in ("astryx-gateway.service", "astryx-observatory.service")]
        oth_files = [n for n in names if f"@{other}." in n]
        for who, e, f, notf in (("the primary", env(ASTRYX_HOME=str(co)), prim_files[0], oth_files[0]),
                                (other, env(ASTRYX_HOME=str(A)), oth_files[0], prim_files[0])):
            body = (units / f).read_bytes()
            (units / f).write_bytes(body + b"# a stale line the render no longer emits\n")
            try:
                rc, out, err = doctor(e)
                lines = out.splitlines()
                stale = [ln for ln in lines if "stale (the name matches" in ln]
                head = next((ln for ln in lines if "content is STALE" in ln), "")
                check(f"{who}: its unit {f} with a stale body is named STALE, and the ✓ no-drift line is withheld",
                      any(f in ln for ln in stale) and not any("no drift" in ln for ln in lines), "\n".join(stale) or out[-300:])
                check(f"...{who}'s remedy is ITS render" + (" (ASTRYX_HOME=<its HOME> ./init.sh units)" if who != "the primary"
                                                             else " (./init.sh units, no foreign HOME)"),
                      (f"ASTRYX_HOME={A} ./init.sh units" in head) if who != "the primary"
                      else ("./init.sh units" in head and "ASTRYX_HOME=" not in head), head)
            finally:
                (units / f).write_bytes(body)
            (units / notf).write_bytes((units / notf).read_bytes() + b"# another org's stale line\n")
            try:
                rc, out, err = doctor(e)
                check(f"...and another org's stale unit ({notf}) is not {who}'s to name: no drift",
                      any("no drift" in ln for ln in out.splitlines()) and "content is STALE" not in out, out[-300:])
            finally:
                (units / notf).write_bytes((units / notf).read_bytes().replace(b"# another org's stale line\n", b""))

        print("\nK4 ITS SEAT CHECK ASKS THE PRIMARY'S SERVER, NEVER AN INHERITED $TMUX's")
        osock = f"ax-{other}"
        subprocess.run(["tmux", "-L", osock, "new-session", "-d", "-s", "ax-seed", "sleep 600"], capture_output=True)
        tpath = Path(os.environ["TMUX_TMPDIR"]) / f"tmux-{os.getuid()}" / osock
        pane_env = env(ASTRYX_HOME=str(co), TMUX=f"{tpath},1,0")      # doctor run from the other org's pane
        rc, out, err = doctor(pane_env)
        check("from another org's pane (its ax-seed alive there): the primary's seed is NOT resident",
              "seed not resident" in out and "seed resident alive" not in out, f"rc {rc} {err[-200:]}")
        subprocess.run(["tmux", "-L", "default", "new-session", "-d", "-s", "ax-seed", "sleep 600"], capture_output=True)
        rc, out, err = doctor(pane_env)
        check("alive on the primary's server: 'seed resident alive'", "seed resident alive" in out, f"rc {rc}")

        print("\nK5 ANOTHER ORG (S7b): doctor RUNS, reading ITS estate (its HOME), its units, its server")
        mine_not = [n for n in names if "@" not in n]           # the primary's plain files and the cog's: never its
        (co / "local.md").write_text("# the checkout's own law: another org's doctor must not read it\n")
        (co / "backups").mkdir(exist_ok=True)
        (co / "backups" / "astryx-fxprim.dump").write_text("")
        (co / "backups" / ".last-restore-ok").write_text("FAILED 2026-10-20\n")
        route = json.dumps([{"agent": "fxnobody", "enabled": True}])
        (co / "bridges" / "routes-discord.json").write_text(route)   # the checkout's channel: not the other org's
        aenv = (A / ".env").read_text()
        (A / ".env").write_text(aenv + "ASTRYX_DOCKER_HOST_IP=10.250.250.250\n")
        subprocess.run(["tmux", "-L", osock, "kill-session", "-t", "=ax-seed"], capture_output=True)

        def deps_line(out):
            return next((ln for ln in out.splitlines() if "python deps" in ln), "")
        try:
            rc, out, err = doctor(env(ASTRYX_HOME=str(A)))
            dl = drift_lines(out)
            check("doctor runs (no exit 3, no refusal)", rc != 3 and "refusing" not in err, f"rc {rc} {err[-300:]}")
            check("its .env is read: its DSN is probed (the checkout has none: '.env missing' would be the checkout's)",
                  ("postgres reachable" in out or "postgres unreachable" in out) and ".env missing" not in out,
                  "\n".join(ln for ln in out.splitlines() if "postgres" in ln or ".env" in ln))
            check("its local.md exists (its HOME's)", "local.md exists" in out)
            check("its backups/: none (the checkout's fresh dump is not its)",
                  "NO database backup" in out and "backup fresh" not in out)
            bl = next((ln for ln in out.splitlines() if "NO database backup" in ln), "")
            check("...and its remedy is ITS reconcile (cog_add_org --reconcile <its key>, a dump now under its HOME), "
                  "never ./init.sh", f"cog_add_org.py --reconcile {other}" in bl and f"ASTRYX_HOME={A}" in bl
                  and "./init.sh" not in bl and "./scripts/backup.sh" not in bl, bl)
            check("its units: its @ files only, no drift", any("no drift" in ln for ln in dl), "\n".join(dl))
            named = [n for n in mine_not if any(n in ln for ln in dl)]
            check("...and no file of the primary's nor the cog's is named its orphan", not named, str(named))
            check("its server: only the primary's ax-seed lives, so its seed is NOT resident",
                  "seed not resident" in out and "seed resident alive" not in out)
            check("its routes: the checkout's route to an unknown agent is not its", "UNKNOWN agents" not in out)
            check("its dep groups: the checkout's discord channel adds none", "discord" not in deps_line(out),
                  deps_line(out))
            check("its .env's ASTRYX_DOCKER_HOST_IP is the docker host address", "10.250.250.250" in out)
            (A / "local.md").rename(A / "local.md.fxoff")
            (A / "backups").mkdir(exist_ok=True)
            (A / "backups" / "astryx-fxother.dump").write_text("")
            (A / "bridges").mkdir(exist_ok=True)
            (A / "bridges" / "routes-discord.json").write_text(route)
            subprocess.run(["tmux", "-L", osock, "new-session", "-d", "-s", "ax-seed", "sleep 600"], capture_output=True)
            rc, out, err = doctor(env(ASTRYX_HOME=str(A)))
            check("positive control: its local.md gone, 'local.md missing' (the checkout's is present)",
                  "local.md missing" in out and "local.md exists" not in out)
            check("...its own fresh dump: 'database backup fresh'", "database backup fresh" in out)
            check("...its seed alive on ITS server: 'seed resident alive'", "seed resident alive" in out)
            check("...its dump never restore-verified (the checkout's FAILED stamp is not its)",
                  "never restore-verified" in out and "restore-verify FAILED" not in out)
            check("...its own route to an unknown agent IS named", "UNKNOWN agents" in out)
            check("...and its own discord channel adds the group", "discord" in deps_line(out), deps_line(out))
        finally:
            (A / ".env").write_text(aenv)
            shutil.rmtree(A / "bridges", ignore_errors=True)
            (co / "bridges" / "routes-discord.json").unlink(missing_ok=True)
            if (A / "local.md.fxoff").exists():
                (A / "local.md.fxoff").rename(A / "local.md")
            shutil.rmtree(A / "backups", ignore_errors=True)
            shutil.rmtree(co / "backups", ignore_errors=True)
            (co / "local.md").unlink(missing_ok=True)

        print("\nK6 NO ORG RESOLVES")
        rc, out, err = doctor(env())
        check("exit 3, refusing", rc == 3 and "refusing" in err, f"rc {rc} {err[-300:]}")

        print("\nK7 ONE ORG (NO REGISTRY): THE FILTER IS THE COG'S ONLY")
        shutil.rmtree(units)
        r = subprocess.run(["bash", "init.sh", "units"], cwd=co, capture_output=True, text=True, timeout=180,
                           env={**fx.env(ASTRYX_COG_REGISTRY=str(fx.t / "none" / "cog.json"), PATH=path),
                                "UNITS_DIR": str(units)})
        (units / "astryx-canvas@fxstray.service").write_text("[Unit]\nDescription=an @-named stray\n")
        rc, out, err = doctor(fx.env(ASTRYX_COG_REGISTRY=str(fx.t / "none" / "cog.json"), PATH=path))
        check("an @-named stray is an orphan on one org, as before", r.returncode == 0 and any(
            "orphan" in ln and "astryx-canvas@fxstray.service" in ln for ln in out.splitlines()),
            "\n".join(drift_lines(out)))
        und = next((ln for ln in out.splitlines() if "undeclared" in ln), "")
        check("...and (iii) on one org: an @-named unit systemd knows is undeclared, as before (no cog scoping)",
              f"astryx-fxoff@{other}.service" in und and "astryx-fxzz@fxelse.service" in und, und)

        print("\nK8 (iii) UNDECLARED, THE UNITS SYSTEMD KNOWS: EACH ORG JUDGES ITS OWN")
        rc_p, out_p, _ = doctor(env(ASTRYX_HOME=str(co)))
        rc_o, out_o, _ = doctor(env(ASTRYX_HOME=str(A)))

        def undeclared(out):
            return next((ln for ln in out.splitlines() if "undeclared" in ln), "")
        up, uo = undeclared(out_p), undeclared(out_o)
        check("the primary: its own plain stray is undeclared (positive control)", "astryx-fxoff.service" in up, up)
        check("...and no other org's @ unit, nor the cog's gateway or front", not [n for n in known[1:] if n in up], up)
        check("another org: its own @ stray is undeclared (positive control)", f"astryx-fxoff@{other}.service" in uo, uo)
        check("...and not the primary's, the cog's, nor a third org's (nor its own derived canvas)",
              not [n for n in known if n != f"astryx-fxoff@{other}.service" and n in uo], uo)

        print("\nK11 EACH ORG UNDER ITS OWN FEDERATION NAME (10224 NAMES)")
        aname = next(ln.split("=", 1)[1] for ln in (A / ".env").read_text().splitlines() if ln.startswith("ASTRYX_ORG="))
        rc, out, err = doctor(env(ASTRYX_HOME=str(co)))
        check("distinct names (the primary's checkout names none): ✓ every org has its own federation name",
              "every org of the cog has its own federation name" in out and "SHARE a federation name" not in out,
              out[-300:])
        (co / ".env").write_text(f"ASTRYX_ORG={aname.upper()}\n")   # the OTHER org's name, in another case
        try:
            rc, out, err = doctor(env(ASTRYX_HOME=str(co)))
            check("the primary takes the other org's name (another case): ✗ SHARE a federation name, naming both orgs",
                  "SHARE a federation name" in out and any(aname in ln and prim in ln and other in ln
                                                           for ln in out.splitlines()), out[-400:])
        finally:
            (co / ".env").unlink()
        (co / ".env").write_bytes(b"NOTE=\xff\xfe fx-PLANTED-77a1\n")   # not UTF-8 (10224 ENVREAD): skipped, said
        try:
            rc, out, err = doctor(env(ASTRYX_HOME=str(co)))
            check("a .env line that is not UTF-8: still ✓ (never blinded), and ⚠ naming its file:line, never its value",
                  "every org of the cog has its own federation name" in out and "not UTF-8 (every reader skips it" in out
                  and f"{co / '.env'}:1: not UTF-8" in out and "fx-PLANTED-77a1" not in out,
                  " | ".join(ln.strip() for ln in out.splitlines() if "federation name" in ln or "UTF-8" in ln))
        finally:
            (co / ".env").unlink()

        print("\nK9 THE PRIMARY FROM ANOTHER CHECKOUT: REFUSED (its estate is the checkout it runs from)")
        reg2 = json.loads(cog.read_text())
        reg2["orgs"][prim]["primary"] = reg2["orgs"][prim]["door"] = False
        reg2["orgs"][other].update(primary=True, door=True)
        cog2 = fx.t / "cog2.json"
        cog2.write_text(json.dumps(reg2))
        rc, out, err = doctor(fx.env(ASTRYX_COG_REGISTRY=str(cog2), PATH=path, ASTRYX_HOME=str(A)))
        check("exit 3 before any check, naming it the cog's primary", rc == 3 and "primary" in err and "✓" not in out,
              f"rc {rc} {err[-300:]}")
    finally:
        for s in ("default", f"ax-{fx.org['a']}"):
            kill_server(s)
        for h in HELD:
            h.close()
        fx.__exit__(None, None, None)
        shutil.rmtree(tdir, ignore_errors=True)
    print()
    if fails:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
