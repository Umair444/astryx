#!/usr/bin/env python3
"""Oracle: `spawn.sh --which-cli` names the harness binary a spawn would launch, with no side effect (steward 10-21).

On the 10-21 18:00Z boot six residents died in their panes on `bash: claude: command not found`. The first claude on
the tmux PATH was omarchy's ~/.local/bin/claude, a bootstrap WRAPPER (`mise use -g claude && exec mise x claude …`)
that fails before mise is ready, and spawn.sh typed the bare name. spawn.sh now resolves the binary the way it resolves
NODE: ASTRYX_CLI, else `mise which claude`, else mise's install path, else the first claude on PATH that is not the
wrapper; and it refuses loudly when none resolves.

HERMETIC. HOME is a temp tree and PATH holds only a stub bin (realpath and dirname linked in, plus the case's own mise
and claude stubs), so the host's real mise and claude are never consulted.

  C1 the wrapper first on PATH and a working mise: mise's binary, never the wrapper
  C2 mise fails (its boot): mise's install path
  C3 no mise, no install, the wrapper first and a real claude later on PATH: the real one
  C4 only the wrapper: rc 1, refused loudly, nothing printed on stdout
  C5 ASTRYX_CLI is honoured as given
  C6 spawn.sh's launch line types the RESOLVED binary, never the bare name
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPAWN = Path(os.environ.get("SPAWN_SRC") or REPO / "scripts" / "spawn.sh")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  ({detail})"))
    fails += 0 if ok else 1


def exe(p: Path, body: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(0o755)
    return p


def run(tmp: Path, mise=None, install=False, later_real=False, cli=None):
    home, stub = tmp / "home", tmp / "bin"
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(stub, ignore_errors=True)
    for tool in ("realpath", "dirname"):
        stub.mkdir(parents=True, exist_ok=True)
        (stub / tool).symlink_to(shutil.which(tool))
    wrapper = exe(home / ".local" / "bin" / "claude", "echo wrapper-ran; exit 7")
    real = exe(tmp / "real" / "claude", "echo real")
    path = [str(home / ".local" / "bin"), str(stub)]
    if mise == "ok":
        exe(stub / "mise", f'[ "$1" = which ] && [ "$2" = claude ] && echo "{real}" && exit 0; exit 3')
    elif mise == "fail":
        exe(stub / "mise", "exit 1")
    if install:
        exe(home / ".local" / "share" / "mise" / "installs" / "claude" / "latest" / "claude", "echo installed")
    if later_real:
        path.append(str(real.parent))
    env = {"HOME": str(home), "PATH": ":".join(path)}
    if cli:
        env["ASTRYX_CLI"] = cli
    r = subprocess.run(["/bin/bash", str(SPAWN), "--which-cli"], capture_output=True, text=True, env=env, timeout=30)
    return r.returncode, r.stdout.strip(), r.stderr.strip(), wrapper, real, home


def main():
    with tempfile.TemporaryDirectory(prefix="spawn-cli-") as td:
        t = Path(td)
        rc, out, err, wrapper, real, home = run(t, mise="ok")
        check("C1 the wrapper first on PATH and a working mise: mise's binary", rc == 0 and out == str(real), (rc, out, err))
        rc, out, err, wrapper, real, home = run(t, mise="fail", install=True)
        inst = home / ".local" / "share" / "mise" / "installs" / "claude" / "latest" / "claude"
        check("C2 mise fails (its boot): mise's install path", rc == 0 and out == str(inst), (rc, out, err))
        rc, out, err, wrapper, real, home = run(t, later_real=True)
        check("C3 the wrapper first, a real claude later on PATH: the real one", rc == 0 and out == str(real), (rc, out, err))
        rc, out, err, wrapper, real, home = run(t)
        check("C4 only the wrapper: refused (rc 1), loudly, nothing on stdout",
              rc == 1 and out == "" and "ASTRYX_CLI" in err and "wrapper-ran" not in out + err, (rc, out, err))
        rc, out, err, *_ = run(t, mise="ok", cli="/opt/fork/claude-like")
        check("C5 ASTRYX_CLI is honoured as given", rc == 0 and out == "/opt/fork/claude-like", (rc, out, err))
    src = SPAWN.read_text()
    launch = [ln for ln in src.splitlines() if ln.lstrip().startswith("tmux send-keys") and "--strict-mcp-config" in ln]
    check("C6 the launch line types the RESOLVED binary, never the bare name",
          len(launch) == 1 and '"$CLI ' in launch[0] and "resolve_cli ||" in src and "CLI=${ASTRYX_CLI:-claude}" not in src,
          launch)
    print("ALL PASS" if not fails else f"FAIL ({fails})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
