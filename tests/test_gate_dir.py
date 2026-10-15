#!/usr/bin/env python3
"""Oracle for check.sh's per-gate dir (plan-10108 D1, a4 #50739; a1 BC-1 #50744; a3 BC-1(i) #50745).

Drives the REAL run() by sourcing devtools/check.sh with CHECK_LIB_ONLY=1 (test_check_gate_cap's seam), with stub
gates that report what they were handed:
  OWN       each gate gets its own TMPDIR ($G); two concurrent runs' gates get different ones; $G is gone after run()
  EXPORTS   XDG_CACHE_HOME=$G/cache and VITE_CACHE_DIR=$G/vite; XDG_RUNTIME_DIR is left the user's
  CAP       a gate killed by its cap still has its $G removed
  ESCAPED   a descendant in its OWN session (outside the group kill) still writing to $G is killed and $G removed;
            so is one that dropped TMPDIR but names $G in its argv (a chromium profile); a stranger under the SAME root,
            and a host-like process with TMPDIR elsewhere under /tmp, both survive
  SHORT     a >=100-byte TMPDIR is not inherited: the gate's TMPDIR is <=30 bytes, an AF_UNIX socket under it binds
            and the gate reaches its verdict; the root used is logged ONCE per run; a short TMPDIR IS inherited

THE KILL RULE IS CONTAINED (a4 #54116). Every run() this oracle drives runs in its own PID NAMESPACE (bwrap
--unshare-pid --proc /proc), where /proc lists only the oracle's own processes. So no cleanup rule, the subject's or a
mutant's, can reach a process outside it: a mutant that kills by the shared root /tmp (mutants_gate_dir.py) once
SIGKILLed the probe running it and could have reached any resident's command. Liveness is judged INSIDE the namespace
(its pids mean nothing outside). Without bwrap the real subject still runs (its rule is safe), but a MUTANT
(CHECK_SH_SRC set) refuses: exit 77, never a host-wide kill.
CHECK_SH_SRC points at a mutant check.sh (tests/mutants_gate_dir.py). Exit 0 pass · 1 fail · 77 not run.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK = Path(os.environ.get("CHECK_SH_SRC") or REPO / "devtools" / "check.sh")
BWRAP = shutil.which("bwrap")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


if BWRAP:
    probe = subprocess.run([BWRAP, "--dev-bind", "/", "/", "--unshare-pid", "--proc", "/proc", "--die-with-parent",
                            "true"], capture_output=True)
    if probe.returncode != 0:
        BWRAP = None
if not BWRAP and os.environ.get("CHECK_SH_SRC"):
    print("SKIP: a MUTANT check.sh's kill rule runs only inside a pid namespace, and bwrap can't make one here")
    sys.exit(77)
JAIL = [BWRAP, "--dev-bind", "/", "/", "--unshare-pid", "--proc", "/proc", "--die-with-parent", "--chdir", str(REPO)] \
    if BWRAP else []


def script(body):
    return f'CHECK_LIB_ONLY=1 source "{CHECK}"\nunset CHECK_LIB_ONLY\n{body}\nverdict\n'


def env_for(tmpdir):
    """The axis is SET, never inherited: a chosen TMPDIR, a fixture runtime dir."""
    env = {k: v for k, v in os.environ.items() if k not in ("TMPDIR", "CHECK_GATE_TIMES", "ASTRYX_SQLGUARD_DIR")}
    env.update({"TMPDIR": str(tmpdir), "XDG_RUNTIME_DIR": "/run/user/fixture-runtime"})
    return env


def drive(body, tmpdir, timeout=40):
    try:
        p = subprocess.run(JAIL + ["bash", "-c", script(body)], capture_output=True, text=True, timeout=timeout,
                           cwd=REPO, env=env_for(tmpdir))
    except subprocess.TimeoutExpired:
        return "TIMEOUT: the driven run outlived the harness", -1
    return p.stdout + p.stderr, p.returncode


def field(out, key):
    for line in out.splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1]
    return None


# judged INSIDE the namespace: prints `<name>=ALIVE|DEAD` for a pid read from a file, or from a variable
LIVE = ('state() { if kill -0 "$2" 2>/dev/null && [ "$(cut -d" " -f3 /proc/$2/stat 2>/dev/null)" != Z ]; '
        'then echo "$1=ALIVE"; else echo "$1=DEAD"; fi; }\n')
REPORT = ('echo TMPDIR=$TMPDIR; echo XDG_CACHE_HOME=$XDG_CACHE_HOME; echo VITE_CACHE_DIR=$VITE_CACHE_DIR; '
          'echo XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR; echo hi > "$TMPDIR/owned"; test -f "$TMPDIR/owned"')

with tempfile.TemporaryDirectory(prefix="gd-", dir="/tmp") as base:
    base = Path(base)
    short = base / "s"
    short.mkdir()
    print(f"  (every driven run() is in its own pid namespace: {'bwrap' if JAIL else 'NONE: bwrap absent, real subject only'})")

    print("OWN + EXPORTS: a gate is handed its own dir, and nothing of it outlives the gate")
    out, rc = drive(f"run 'a' bash -c '{REPORT}'\nrun 'b' bash -c '{REPORT}'", short)
    gates = [ln.split("=", 1)[1] for ln in out.splitlines() if ln.startswith("TMPDIR=")]
    check("each gate ran and passed", rc == 0 and out.count("✓") == 2, out[-400:])
    check("each gate's TMPDIR is its own fresh dir under the root (two gates, two dirs)",
          len(gates) == 2 and gates[0] != gates[1] and all(Path(g).parent == short and Path(g).name.startswith("g.")
                                                            for g in gates), str(gates))
    check("after run(), the gate's dir is gone", gates and not any(Path(g).exists() for g in gates), str(gates))
    g = field(out, "TMPDIR") or "?"
    check("XDG_CACHE_HOME is $G/cache (a3 BC-1 i)", field(out, "XDG_CACHE_HOME") == f"{g}/cache", out[:300])
    check("VITE_CACHE_DIR is $G/vite (D2)", field(out, "VITE_CACHE_DIR") == f"{g}/vite", out[:300])
    check("XDG_RUNTIME_DIR stays the caller's", field(out, "XDG_RUNTIME_DIR") == "/run/user/fixture-runtime", out[:300])
    check("the root is logged once per run, naming TMPDIR as inherited",
          out.count("each gate gets its own TMPDIR") == 1 and f"under {short}," in out and "rooted at TMPDIR" in out,
          out[:300])

    print("CONCURRENT: two check.sh runs at once never share a gate dir")
    body = "run 'c' bash -c 'echo TMPDIR=$TMPDIR; sleep 1'"
    procs = [subprocess.Popen(JAIL + ["bash", "-c", script(body)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, cwd=REPO, env=env_for(short)) for _ in range(2)]
    seen = [field(p.communicate(timeout=30)[0], "TMPDIR") for p in procs]
    check("two concurrent runs' gates see different dirs", None not in seen and seen[0] != seen[1], str(seen))

    print("CAP: a gate killed by its cap still has its dir removed")
    out, rc = drive("run --cap=1 'slow' bash -c 'echo TMPDIR=$TMPDIR; echo x > \"$TMPDIR/f\"; sleep 30'", short)
    g = field(out, "TMPDIR")
    check("the gate TIMED OUT", "TIMED OUT" in out, out[-300:])
    check("its dir is gone", g is not None and not Path(g).exists(), str(g))

    print("ESCAPED: cleanup by own $G reaches a descendant outside the gate's process group, and nothing else")
    pidf, pidf2 = base / "esc.pid", base / "argv.pid"
    (short / "stranger").mkdir()
    elsewhere = Path(tempfile.mkdtemp(prefix="gd-elsewhere-", dir="/tmp"))
    gate = base / "esc.sh"
    gate.write_text(
        "echo TMPDIR=$TMPDIR\n"
        f"setsid bash -c 'echo $$ > {pidf}; while :; do date > \"$TMPDIR/w\"; sleep 0.1; done' &\n"
        f"setsid env -u TMPDIR G=\"$TMPDIR\" bash -c 'echo $$ > {pidf2}; exec -a \"fakechrome --user-data-dir=$G/prof\" sleep 60' &\n"
        "sleep 1\nexit 0\n")
    body = (LIVE
            + f"TMPDIR={short / 'stranger'} setsid sleep 60 & SP=$!\n"      # under the SAME root as the gates
            + f"TMPDIR={elsewhere} setsid sleep 60 & HP=$!\n"               # host-like: TMPDIR elsewhere under /tmp
            + f"run 'esc' bash {gate}\nsleep 0.3\n"
            + f"state escaped $(cat {pidf}); state argvheld $(cat {pidf2}); state stranger $SP; state hostlike $HP\n"
            + "kill -9 $SP $HP 2>/dev/null\n")
    out, rc = drive(body, short)
    g = field(out, "TMPDIR")
    check("the gate passed", "✓ esc" in out, out[-300:])
    check("a writer in its own session, carrying TMPDIR=$G, is killed", field(out, "escaped") == "DEAD", out[-300:])
    check("one that dropped TMPDIR but names $G in its argv is killed", field(out, "argvheld") == "DEAD", out[-300:])
    check("the gate's dir is gone (no writer recreated it)", g is not None and not Path(g).exists(), str(g))
    check("a stranger with ANOTHER TMPDIR under the same root survives", field(out, "stranger") == "ALIVE", out[-300:])
    check("a host-like process with TMPDIR elsewhere under /tmp survives", field(out, "hostlike") == "ALIVE", out[-300:])
    check("no 'outlived' note", "outlived its cleanup" not in out, out[-300:])
    shutil.rmtree(elsewhere, ignore_errors=True)

    print("SHORT (a1 BC-1): a long TMPDIR is not inherited; a socket under the gate's dir still binds")
    long_tmp = base / ("L" * 120)
    long_tmp.mkdir()
    sock_gate = base / "sock.py"
    sock_gate.write_text("import os, socket\nprint('TMPDIR=' + os.environ['TMPDIR'])\ns = socket.socket(socket.AF_UNIX)\n"
                         "p = os.path.join(os.environ['TMPDIR'], 'x' * 60, 'srv.sock')\nos.makedirs(os.path.dirname(p))\n"
                         "s.bind(p)\nprint('BOUND', len(p))\n")
    elsewhere = Path(tempfile.mkdtemp(prefix="gd-elsewhere-", dir="/tmp"))
    body = (LIVE + f"TMPDIR={elsewhere} setsid sleep 60 & HP=$!\n"
            + f"run 'sock' python3 {sock_gate}\nsleep 0.2\nstate hostlike $HP\nkill -9 $HP 2>/dev/null\n")
    out, rc = drive(body, long_tmp)
    g = field(out, "TMPDIR") or ""
    check(f"the TMPDIR is >=100 bytes ({len(str(long_tmp))})", len(str(long_tmp)) >= 100)
    check("the gate's TMPDIR is <=30 bytes", 0 < len(g) <= 30, f"{len(g)}: {g}")
    check("an AF_UNIX socket under it binds, and the gate reaches its verdict", "BOUND" in out and "✓ sock" in out,
          out[-400:])
    check("the run logs that it rooted at /tmp, and why", "rooted at /tmp, not the" in out and "AF_UNIX" in out,
          out[:300])
    check("with the root at /tmp, a host-like process elsewhere under /tmp survives the cleanup",
          field(out, "hostlike") == "ALIVE", out[-300:])
    shutil.rmtree(elsewhere, ignore_errors=True)

print()
print("PASS: every gate gets its own short dir, and nothing of it outlives the gate" if not fails
      else f"FAIL ({len(fails)}): " + "; ".join(fails))
sys.exit(1 if fails else 0)
