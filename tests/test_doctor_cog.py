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
  K5 another org (ASTRYX_HOME naming it): exit 3 before any check, naming its vitals.sh and smoke.sh (S7b, a doctor
     for a non-primary org, is a stated limit: seed #61017)
  K6 no org resolves (no ASTRYX_HOME, no marker): exit 3, refusing
  K7 one org (no registry): the filter is the COG's only: an @-named stray in units/ is an orphan, as before

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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
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

        print("\nK5 ANOTHER ORG: REFUSED BEFORE ANY CHECK, ITS OWN TOOLS NAMED")
        rc, out, err = doctor(env(ASTRYX_HOME=str(A)))
        check("exit 3, naming vitals.sh and smoke.sh, and no check ran", rc == 3 and "vitals.sh" in err
              and "smoke.sh" in err and "✓" not in out and "✗" not in out, f"rc {rc} {err[-300:]}")

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
    finally:
        for s in ("default", f"ax-{fx.org['a']}"):
            kill_server(s)
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
