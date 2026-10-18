#!/usr/bin/env python3
"""Oracle: scripts/deploy.sh in a cog (plan-11324 S3f S4, seed #60804/#60805). Each verb acts on THIS org's units only
(orgs.unit: the primary's plain names, another org's `@<key>`), only the primary restarts the shared database, and the
cog's gateway and front say a restart affects every org. One org: every verb as before.

A fake checkout runs the REAL deploy.sh, org_tmux.sh and orgs.py (src/ linked), against a fixture registry: the
primary `fxp` (its HOME is the checkout, marked) and `fxl` (a HOME of its own). sudo, systemctl, docker, curl, tmux
and npm are logging STUBS on PATH: no unit, db, server or build of the host is touched.

  D1 one org (no registry): api, bridge and gw restart astryx-observatory, astryx-whatsapp and astryx-gateway, as before
  D2 the primary in a cog: api is its backend astryx-observatory-org.service; bridge is astryx-whatsapp.service; front
     restarts the cog's astryx-observatory, asks /api/cog and says it affects every org; obs restarts both; gw says so
  D3 lab in a cog: api is astryx-observatory-org@fxl.service, bridge astryx-whatsapp@fxl.service; `restart` REFUSES
     (only the primary restarts the shared database: no docker call); `reload` refuses
  D4 units: the primary copies its plain files and never the cog's or lab's; lab only its @fxl files; --cog only the
     cog-scoped ones
  D5 a cog with no HOME carried and no marker: deploy.sh refuses (exit 3), nothing restarted
  D6 lab's `residents`: lab's pulse timer (astryx-pulse@fxl.timer) stopped and started, its backend at its registry
     port probed, nothing of the primary's touched
  D7 the primary's `restart --force`: the shared database (docker restart) and its own enabled units, never lab's
DEPLOY_SRC: a mutant scripts/deploy.sh (tests/mutants_deploy_cog.py). Exit 0 pass · 1 fail.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("DEPLOY_SRC") or REPO / "scripts" / "deploy.sh")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


STUB = """#!/usr/bin/env bash
echo "{name} $*" >> "$DEPLOY_FX_LOG"
case "{name} $1" in
  "systemctl list-unit-files") printf '%s enabled\\n' $DEPLOY_FX_ENABLED ;;
  "systemctl is-active") echo active ;;
  "docker ps") printf 'genesis-pg\\t127.0.0.1:5432->5432/tcp\\n' ;;
esac
exit 0
"""


def main():
    t = Path(tempfile.mkdtemp(prefix="deploycog-")).resolve()
    try:
        root, lab, bin_ = t / "co", t / "lab", t / "bin"
        for d in (root / "scripts", root / "units", root / "observatory" / "web", root / "venv" / "bin", lab / "agents", bin_):
            d.mkdir(parents=True)
        shutil.copy(SRC, root / "scripts" / "deploy.sh")
        for f in ("org_tmux.sh", "docker_host_ip.sh"):
            shutil.copy(REPO / "scripts" / f, root / "scripts" / f)
        (root / "src").symlink_to(REPO / "src")
        # the real interpreter for deploy.sh's every python call, BUT ears() (`python -`, its stdin script reads each
        # live channel server's /proc environ): stubbed, so no process of the host is ever read (test_deploy_restart's way)
        (root / "venv" / "bin" / "python").write_text(f'#!/usr/bin/env bash\n[ "${{1:-}}" = - ] && {{ cat >/dev/null; '
                                                      f'exit 0; }}\nexec "{sys.executable}" "$@"\n')
        (root / "venv" / "bin" / "python").chmod(0o755)
        (root / ".env").write_text("ASTRYX_DSN=postgresql://fx@127.0.0.1:5432/fxdeploy_p\n")
        (lab / ".env").write_text("ASTRYX_DSN=postgresql://fx@127.0.0.1:5432/fxdeploy_l\n")
        (lab / ".astryx").write_text("")
        # sudo LOGS, and runs a command only when it is one of THIS oracle's stubs (systemctl): a real one (cp into
        # /etc/systemd/system, anything else) is recorded and never executed
        (bin_ / "sudo").write_text('#!/usr/bin/env bash\necho "sudo $*" >> "$DEPLOY_FX_LOG"\n'
                                   f'[ -x "{bin_}/$1" ] && exec "{bin_}/$1" "${{@:2}}"\nexit 0\n')
        for name in ("systemctl", "docker", "curl", "tmux", "npm", "psql"):
            (bin_ / name).write_text(STUB.replace("{name}", name))
        for f in bin_.iterdir():
            f.chmod(0o755)
        reg = t / "cog.json"
        reg.write_text(json.dumps({"orgs": {
            "fxp": {"home": str(root), "db": "fxdeploy_p", "primary": True, "door": True,
                    "ports": {"astryx-observatory-org": 18190, "astryx-canvas": 18091, "astryx-whatsapp": 18477}},
            "fxl": {"home": str(lab), "db": "fxdeploy_l",
                    "ports": {"astryx-observatory-org": 28190, "astryx-canvas": 28091, "astryx-whatsapp": 28477}}}}))
        log = t / "log"
        base = {"PATH": f"{bin_}:{os.environ['PATH']}", "HOME": str(t), "DEPLOY_FX_LOG": str(log), "TMPDIR": str(t),
                "DEPLOY_FX_ENABLED": "astryx-whatsapp.service astryx-gateway.service astryx-observatory.service "
                                     "astryx-observatory-org.service astryx-whatsapp@fxl.service "
                                     "astryx-observatory-org@fxl.service astryx-pulse.timer astryx-pulse@fxl.timer"}

        def run(*verb, **env):
            log.write_text("")
            e = {**base, **{k: v for k, v in env.items() if v is not None}}
            p = subprocess.run(["bash", str(root / "scripts" / "deploy.sh"), *verb], env=e, cwd=str(t), capture_output=True,
                               text=True, timeout=120)
            calls = log.read_text().splitlines()
            return p, [c[len("systemctl restart "):] for c in calls if c.startswith("systemctl restart ")], calls

        one = {"ASTRYX_COG_REGISTRY": str(t / "no-registry.json")}
        cogp = {"ASTRYX_COG_REGISTRY": str(reg), "ASTRYX_HOME": str(root)}
        cogl = {"ASTRYX_COG_REGISTRY": str(reg), "ASTRYX_HOME": str(lab)}

        print("D1 ONE ORG: AS BEFORE")
        for verb, unit in (("api", "astryx-observatory"), ("bridge", "astryx-whatsapp"), ("gw", "astryx-gateway")):
            p, r, _ = run(verb, **one)
            check(f"`deploy.sh {verb}` restarts exactly {unit}", p.returncode == 0 and r == [unit],
                  f"rc {p.returncode} {r} {(p.stdout + p.stderr)[-200:]}")
        p, r, _ = run("gw", **one)
        check("...and on one org no 'affects every org' line", "affects every org" not in p.stdout, p.stdout[-200:])

        print("\nD2 THE PRIMARY IN A COG")
        p, r, _ = run("api", **cogp)
        check("api: its backend astryx-observatory-org.service (plain), never the front", p.returncode == 0
              and r == ["astryx-observatory-org.service"], f"rc {p.returncode} {r} {(p.stdout + p.stderr)[-300:]}")
        p, r, _ = run("bridge", **cogp)
        check("bridge: astryx-whatsapp.service", p.returncode == 0 and r == ["astryx-whatsapp.service"], f"{r}")
        p, r, calls = run("front", **cogp)
        check("front: the cog's astryx-observatory, health-verified on /api/cog, 'affects every org in the cog'",
              p.returncode == 0 and r == ["astryx-observatory"] and any("curl" in c and "/api/cog" in c for c in calls)
              and "affects every org in the cog" in p.stdout, f"rc {p.returncode} {r} {p.stdout[-300:]}")
        p, r, _ = run("obs", **cogp)
        check("obs: builds, then its backend AND the front (the front serves the shared dist)", p.returncode == 0
              and r == ["astryx-observatory-org.service", "astryx-observatory"], f"rc {p.returncode} {r}")
        p, r, _ = run("gw", **cogp)
        check("gw: the cog's gateway, and it says so", p.returncode == 0 and r == ["astryx-gateway"]
              and "affects every org in the cog" in p.stdout, f"{r} {p.stdout[-200:]}")

        print("\nD3 LAB IN A COG")
        p, r, _ = run("api", **cogl)
        check("api: astryx-observatory-org@fxl.service", p.returncode == 0 and r == ["astryx-observatory-org@fxl.service"],
              f"rc {p.returncode} {r} {(p.stdout + p.stderr)[-300:]}")
        p, r, _ = run("bridge", **cogl)
        check("bridge: astryx-whatsapp@fxl.service", r == ["astryx-whatsapp@fxl.service"], f"{r}")
        p, r, calls = run("restart", **cogl)
        check("restart: REFUSED, only the primary restarts the shared database; no docker call, nothing restarted",
              p.returncode != 0 and "only the cog's primary org restarts the shared database" in p.stdout
              and not any(c.startswith("docker") for c in calls) and not r, f"rc {p.returncode} {r} {p.stdout[-300:]}")
        p, r, _ = run("reload", **cogl)
        check("reload: refused in a cog (a bridge found by name and fixed port)", p.returncode != 0 and not r,
              f"rc {p.returncode} {(p.stdout + p.stderr)[-200:]}")

        print("\nD4 units: EACH ORG'S OWN FILES")
        for n in ("astryx-whatsapp.service", "astryx-pulse.timer", "astryx-observatory-org.service",
                  "astryx-observatory.service", "astryx-gateway.service", "astryx-whatsapp@fxl.service",
                  "astryx-pulse@fxl.timer"):
            (root / "units" / n).write_text(f"# {n}\n")

        def copied(calls):
            c = [x for x in calls if x.startswith("sudo cp ")]
            return sorted(Path(a).name for a in c[0].split()[2:-1]) if c else []
        _, _, calls = run("units", **cogp)
        check("the primary: its plain files, never the cog's (front, gateway) or lab's",
              copied(calls) == ["astryx-observatory-org.service", "astryx-pulse.timer", "astryx-whatsapp.service"],
              str(copied(calls)))
        _, _, calls = run("units", **cogl)
        check("lab: only its @fxl files", copied(calls) == ["astryx-pulse@fxl.timer", "astryx-whatsapp@fxl.service"],
              str(copied(calls)))
        _, _, calls = run("units", "--cog", **cogp)
        check("--cog: only the cog-scoped files", copied(calls) == ["astryx-gateway.service", "astryx-observatory.service"],
              str(copied(calls)))

        print("\nD5 A COG WITH NO ORG NAMED")
        p, r, _ = run("api", ASTRYX_COG_REGISTRY=str(reg))
        check("no ASTRYX_HOME, no marker under cwd: exit 3, nothing restarted", p.returncode == 3 and not r
              and "refusing" in p.stderr, f"rc {p.returncode} {r} {p.stderr[-200:]}")

        print("\nD6 LAB'S RESIDENTS: LAB'S OWN PULSE AND BACKEND")
        p, r, calls = run("residents", **cogl)
        stops = [c for c in calls if c.startswith("systemctl stop") or c.startswith("systemctl start")]
        probes = [c for c in calls if c.startswith("curl")]
        check("lab's pulse timer astryx-pulse@fxl.timer stopped and started, never the primary's",
              stops == ["systemctl stop astryx-pulse@fxl.timer", "systemctl start astryx-pulse@fxl.timer"]
              or (len(stops) >= 2 and all("astryx-pulse@fxl.timer" in c for c in stops)), str(stops))
        check("its backend probed at its registry port 28190 (never :8090, the front)",
              any("localhost:28190/api/overview" in c for c in probes) and not any(":8090/api/overview" in c for c in probes),
              str(probes))
        check("nothing of the primary's restarted", not any("@" not in u for u in r), str(r))

        print("\nD7 THE PRIMARY'S restart: ITS OWN UNITS AND THE DATABASE, NEVER LAB'S")
        p, r, calls = run("restart", "--force", **cogp)
        check("the primary restarts the shared database (docker restart)", any(c.startswith("docker restart") for c in calls),
              str([c for c in calls if c.startswith("docker")]))
        check("...and its own enabled units, never an @fxl one", r and not any("@" in u for u in r)
              and "astryx-whatsapp.service" in r, str(r))
    finally:
        shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    main()
    print()
    print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
          "deploy.sh in a cog: each org's own units; only the primary touches the database; the cog's say so")
    sys.exit(1 if fails else 0)
