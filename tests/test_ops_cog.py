#!/usr/bin/env python3
"""Oracle: the operator scripts in a cog (plan-11324 S3f S4, seed #60804/#60805): pause.sh, smoke.sh, refresh.sh and
skills/org-vitals/vitals.sh act on THIS org (scripts/org_here.sh: ASTRYX_HOME or the checkout's marker), never another.
One org: each as before.

A fake checkout runs the REAL scripts and orgs.py against a fixture registry (the primary `fxp`, its HOME the checkout;
`fxl`, a HOME of its own). sudo, systemctl, tmux, psql, curl, journalctl and git are logging STUBS on PATH, and
refresh's spawn.sh is a stub; the refresh arm runs in a private PID namespace (bwrap), so its channel-body count reads
only this oracle's own dummy servers, never a resident's /proc.

  O1 pause on, one org: var/org_pause.json in the checkout, astryx-pulse.timer stopped
  O2 pause on, lab: lab's estate holds the declaration, astryx-pulse@fxl.timer stopped, the checkout's var/ untouched
  O3 pause on, the primary: the checkout's var/, astryx-pulse.timer (its plain name)
  O4 smoke, lab: its residents' server (tmux -L ax-fxl), its .env's DSN, its backend at its registry port 28190
  O5 vitals, lab: its .env's DSN, its OWN backups (the primary's fresh dump is never read as lab's); the journal
     header says it covers every org
  O6 refresh, lab: kills on lab's server, and counts ONE channel body although the primary runs one of the same name
  O7 a cog with no org named: each refuses (exit 3)
  O8 the primary named by the checkout's .astryx MARKER (no ASTRYX_HOME): refresh's child (spawn.sh) is handed
     ASTRYX_HOME, the checkout, so it resolves the same org (org_here exports it)
Seams: OPS_PAUSE_SRC, OPS_SMOKE_SRC, OPS_REFRESH_SRC, OPS_VITALS_SRC, OPS_HERE_SRC (one mutant subject each:
tests/mutants_ops_cog_*.py), and OPS_SRC_DIR (a directory of copies, for a whole-set RED run).
Exit 0 pass · 1 fail · 77 (O6 needs bwrap+node).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRCD = Path(os.environ["OPS_SRC_DIR"]) if os.environ.get("OPS_SRC_DIR") else None
fails = []
not_run = False

STUB = """#!/usr/bin/env bash
echo "{name} $*" >> "$OPS_FX_LOG"
case "{name}" in
  psql) echo 0 ;;
esac
exit 0
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


SEAM = {"pause.sh": "OPS_PAUSE_SRC", "smoke.sh": "OPS_SMOKE_SRC", "refresh.sh": "OPS_REFRESH_SRC",
        "vitals.sh": "OPS_VITALS_SRC", "org_here.sh": "OPS_HERE_SRC"}


def src(rel):
    """The subject: its seam's mutant, else a copy from OPS_SRC_DIR, else this tree's."""
    name = Path(rel).name
    if os.environ.get(SEAM.get(name, "")):
        return Path(os.environ[SEAM[name]])
    if SRCD and (SRCD / name).exists():
        return SRCD / name
    return REPO / rel


def main():
    global not_run
    t = Path(tempfile.mkdtemp(prefix="opscog-")).resolve()
    try:
        root, lab, bin_ = t / "co", t / "lab", t / "bin"
        for d in (root / "scripts", root / "skills" / "org-vitals", root / "venv" / "bin", root / "var",
                  lab / "agents", lab / "homes" / "fxag", bin_):
            d.mkdir(parents=True)
        for rel in ("scripts/pause.sh", "scripts/smoke.sh", "scripts/refresh.sh", "scripts/org_here.sh",
                    "skills/org-vitals/vitals.sh"):
            shutil.copy(src(rel), root / rel)
        shutil.copy(REPO / "scripts" / "org_tmux.sh", root / "scripts" / "org_tmux.sh")
        (root / "scripts" / "spawn.sh").write_text('#!/usr/bin/env bash\necho "spawn $* home=${ASTRYX_HOME:-}" >> "$OPS_FX_LOG"\n'
                                                   'echo "$1 resident (tmux:ax-$1, boot=fresh)"\n')
        (root / "scripts" / "spawn.sh").chmod(0o755)
        (root / "src").symlink_to(REPO / "src")
        (root / "venv" / "bin" / "python").write_text(f'#!/usr/bin/env bash\nexec "{sys.executable}" "$@"\n')
        (root / "venv" / "bin" / "python").chmod(0o755)
        (root / ".env").write_text("ASTRYX_DSN=postgresql://fx@127.0.0.1:5432/fxops_p\n")
        (lab / ".env").write_text("ASTRYX_DSN=postgresql://fx@127.0.0.1:5432/fxops_l\n")
        (lab / "agents" / "fxag.md").write_text("# fxag\nA fixture resident of lab.\n")
        (bin_ / "sudo").write_text('#!/usr/bin/env bash\necho "sudo $*" >> "$OPS_FX_LOG"\n'
                                   f'[ -x "{bin_}/$1" ] && exec "{bin_}/$1" "${{@:2}}"\nexit 0\n')
        for name in ("systemctl", "tmux", "psql", "curl", "journalctl", "git"):
            (bin_ / name).write_text(STUB.replace("{name}", name))
        for f in bin_.iterdir():
            f.chmod(0o755)
        reg = t / "cog.json"
        reg.write_text(json.dumps({"orgs": {
            "fxp": {"home": str(root), "db": "fxops_p", "primary": True,
                    "ports": {"astryx-observatory-org": 18190, "astryx-canvas": 18091}},
            "fxl": {"home": str(lab), "db": "fxops_l",
                    "ports": {"astryx-observatory-org": 28190, "astryx-canvas": 28091}}}}))
        log = t / "log"
        base = {"PATH": f"{bin_}:{os.environ['PATH']}", "HOME": str(t), "OPS_FX_LOG": str(log), "TMPDIR": str(t)}

        def run(rel, *args, **env):
            log.write_text("")
            e = {**base, **{k: v for k, v in env.items() if v is not None}}
            p = subprocess.run(["bash", str(root / rel), *args], env=e, cwd=str(root), capture_output=True, text=True,
                               timeout=120)
            return p, log.read_text().splitlines()

        one = {"ASTRYX_COG_REGISTRY": str(t / "no-registry.json")}
        cogp = {"ASTRYX_COG_REGISTRY": str(reg), "ASTRYX_HOME": str(root)}
        cogl = {"ASTRYX_COG_REGISTRY": str(reg), "ASTRYX_HOME": str(lab)}

        print("O1 PAUSE, ONE ORG: AS BEFORE")
        p, calls = run("scripts/pause.sh", "on", "fx reason", **one)
        check("the checkout's var/org_pause.json, astryx-pulse.timer stopped", p.returncode == 0
              and (root / "var" / "org_pause.json").exists() and "systemctl stop astryx-pulse.timer" in calls,
              f"rc {p.returncode} {calls} {(p.stdout + p.stderr)[-200:]}")
        (root / "var" / "org_pause.json").unlink(missing_ok=True)

        print("\nO2 PAUSE, LAB: ITS OWN ESTATE AND TIMER")
        p, calls = run("scripts/pause.sh", "on", "fx reason", **cogl)
        check("lab's estate holds the declaration, astryx-pulse@fxl.timer stopped, the checkout's var/ untouched",
              p.returncode == 0 and (lab / "var" / "org_pause.json").exists()
              and not (root / "var" / "org_pause.json").exists()
              and "systemctl stop astryx-pulse@fxl.timer" in calls, f"rc {p.returncode} {calls} {(p.stdout + p.stderr)[-300:]}")

        print("\nO3 PAUSE, THE PRIMARY: ITS PLAIN TIMER")
        p, calls = run("scripts/pause.sh", "on", "fx reason", **cogp)
        check("the checkout's var/, astryx-pulse.timer", p.returncode == 0 and (root / "var" / "org_pause.json").exists()
              and "systemctl stop astryx-pulse.timer" in calls, f"rc {p.returncode} {calls}")

        print("\nO4 SMOKE, LAB")
        p, calls = run("scripts/smoke.sh", **cogl)
        check("lab's residents' server (-L ax-fxl)", any(c.startswith("tmux -L ax-fxl has-session") for c in calls),
              str([c for c in calls if c.startswith("tmux")]))
        check("lab's .env's DSN (fxops_l), never the primary's", any("psql" in c and "fxops_l" in c for c in calls)
              and not any("fxops_p" in c for c in calls), str([c for c in calls if c.startswith("psql")][:3]))
        check("lab's backend at its registry port 28190, never :8090 (the front)",
              any("curl" in c and "localhost:28190/api/overview" in c for c in calls)
              and not any(":8090/" in c for c in calls), str([c for c in calls if c.startswith("curl")]))

        print("\nO5 VITALS, LAB")
        (root / "backups").mkdir(exist_ok=True)          # the PRIMARY holds a fresh dump and restore stamp; lab holds none
        (root / "backups" / "astryx-20991231.dump").write_text("fx")
        (root / "backups" / ".last-restore-ok").write_text("fx")
        p, calls = run("skills/org-vitals/vitals.sh", **cogl)
        check("lab's backups are LAB's: no dump and no restore stamp, never the primary's fresh ones (a2 #60858 R-1)",
              "NO .dump in backups/" in p.stdout and "NO .last-restore-ok stamp" in p.stdout
              and "astryx-20991231.dump" not in p.stdout, p.stdout[-400:])
        check("lab's .env's DSN (fxops_l), never the primary's", any("psql" in c and "fxops_l" in c for c in calls)
              and not any("fxops_p" in c for c in calls), str([c for c in calls if c.startswith("psql")][:3]))
        check("the journal header says it covers every org", "the units of EVERY org" in p.stdout, p.stdout[-300:])

        print("\nO6 REFRESH, LAB: ITS SERVER, ITS ONE BODY (a private pid namespace)")
        bwrap, node = shutil.which("bwrap"), shutil.which("node")
        if not (bwrap and node):
            print(f"  NOT RUN  O6 needs bwrap and node (bwrap={bwrap}, node={node})")
            not_run = True
        else:
            (t / "channel").mkdir()
            (t / "channel" / "server.mjs").write_text("setTimeout(() => {}, 600000)\n")
            script = f"""
ASTRYX_AGENT=fxag ASTRYX_HOME={lab} "{node}" "{t}/channel/server.mjs" &
ASTRYX_AGENT=fxag ASTRYX_HOME={root} "{node}" "{t}/channel/server.mjs" &
sleep 1
bash "{root}/scripts/refresh.sh" fxag; echo "RC=$?"
kill %1 %2
"""
            log.write_text("")
            r = subprocess.run([bwrap, "--dev-bind", "/", "/", "--unshare-pid", "--proc", "/proc", "--die-with-parent",
                                "--chdir", str(root), "bash", "-c", script], capture_output=True, text=True, timeout=180,
                               env={**base, **cogl})
            calls = log.read_text().splitlines()
            check("kills on lab's server (tmux -L ax-fxl kill-session)", any(c.startswith("tmux -L ax-fxl kill-session")
                  for c in calls), str([c for c in calls if c.startswith("tmux")]))
            check("counts exactly ONE channel body for fxag, though the primary runs one of the same name: clean, rc 0",
                  "channel bodies for fxag: 1 (want 1)" in r.stdout and "RC=0" in r.stdout, (r.stdout + r.stderr)[-400:])

        print("\nO8 THE PRIMARY BY ITS MARKER: ITS CHILDREN ARE HANDED ITS HOME")
        if not bwrap:
            print("  NOT RUN  O8 needs bwrap (refresh counts channel bodies by /proc)")
            not_run = True
        else:
            (root / ".astryx").write_text("")
            (root / "agents").mkdir(exist_ok=True)
            (root / "agents" / "fxag.md").write_text("# fxag\nA fixture resident of the primary.\n")
            (root / "homes" / "fxag").mkdir(parents=True, exist_ok=True)
            log.write_text("")
            r = subprocess.run([bwrap, "--dev-bind", "/", "/", "--unshare-pid", "--proc", "/proc", "--die-with-parent",
                                "--chdir", str(root), "bash", str(root / "scripts" / "refresh.sh"), "fxag"],
                               capture_output=True, text=True, timeout=180,
                               env={**base, "ASTRYX_COG_REGISTRY": str(reg)})
            sp = [c for c in log.read_text().splitlines() if c.startswith("spawn ")]
            check("refresh's spawn.sh ran with ASTRYX_HOME = the checkout (the marker's org, exported to children)",
                  sp == [f"spawn fxag home={root}"], f"{sp} {(r.stdout + r.stderr)[-300:]}")
            (root / ".astryx").unlink()

        print("\nO7 A COG WITH NO ORG NAMED")
        for rel in ("scripts/pause.sh", "scripts/smoke.sh", "scripts/refresh.sh", "skills/org-vitals/vitals.sh"):
            p, _ = run(rel, *(["status"] if "pause" in rel else ["fxag"] if "refresh" in rel else []),
                       ASTRYX_COG_REGISTRY=str(reg))
            check(f"{rel}: exit 3, refusing", p.returncode == 3 and "refusing" in p.stderr,
                  f"rc {p.returncode} {p.stderr[-200:]}")
    finally:
        shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    main()
    if not_run and not fails:
        print("\nNOT RUN (77): O6 could not run here; every other arm passed")
        sys.exit(77)
    print()
    print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
          "the operator scripts in a cog: each acts on its own org's estate, timer, server and bodies")
    sys.exit(1 if fails else 0)
