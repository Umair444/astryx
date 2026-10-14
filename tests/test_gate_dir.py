#!/usr/bin/env python3
"""Oracle for check.sh's per-gate dir (plan-10108 D1, a4 #50739; a1 BC-1 #50744; a3 BC-1(i) #50745).

Drives the REAL run() by sourcing devtools/check.sh with CHECK_LIB_ONLY=1 (test_check_gate_cap's seam), with stub
gates that report what they were handed:
  OWN       each gate gets its own TMPDIR ($G); two concurrent runs' gates get different ones; $G is gone after run()
  EXPORTS   XDG_CACHE_HOME=$G/cache and VITE_CACHE_DIR=$G/vite; XDG_RUNTIME_DIR is left the user's
  CAP       a gate killed by its cap still has its $G removed
  ESCAPED   a descendant in its OWN session (outside the group kill) still writing to $G is killed and $G removed;
            so is one that dropped TMPDIR but names $G in its argv (a chromium profile); a stranger is never touched
  SHORT     a >=100-byte TMPDIR is not inherited: the gate's TMPDIR is <=30 bytes, an AF_UNIX socket under it binds
            and the gate reaches its verdict; the root used is logged ONCE per run; a short TMPDIR IS inherited
CHECK_SH_SRC points at a mutant check.sh (tests/mutants_gate_dir.py). Exit 0 pass · 1 fail.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK = Path(os.environ.get("CHECK_SH_SRC") or REPO / "devtools" / "check.sh")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def drive(body, tmpdir, timeout=40, extra_env=None):
    """Source check.sh's library half under a CHOSEN TMPDIR (the axis is set, never inherited) and run `body`."""
    script = f'CHECK_LIB_ONLY=1 source "{CHECK}"\nunset CHECK_LIB_ONLY\n{body}\nverdict\n'
    env = {k: v for k, v in os.environ.items() if k not in ("TMPDIR", "CHECK_GATE_TIMES", "ASTRYX_SQLGUARD_DIR")}
    env.update({"TMPDIR": str(tmpdir), "XDG_RUNTIME_DIR": "/run/user/fixture-runtime"}, **(extra_env or {}))
    try:
        p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=timeout, cwd=REPO, env=env)
    except subprocess.TimeoutExpired:
        return "TIMEOUT: the driven run outlived the harness", -1
    return p.stdout + p.stderr, p.returncode


def field(out, key):
    for line in out.splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1]
    return None


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    st = Path(f"/proc/{pid}/stat")
    return st.exists() and st.read_text().split(") ", 1)[-1][:1] != "Z"


def pid_in(path, within=5.0):
    until = time.monotonic() + within
    while time.monotonic() < until:
        if path.exists() and path.read_text().strip():
            return int(path.read_text().split()[0])
        time.sleep(0.05)
    return None


REPORT = ('echo TMPDIR=$TMPDIR; echo XDG_CACHE_HOME=$XDG_CACHE_HOME; echo VITE_CACHE_DIR=$VITE_CACHE_DIR; '
          'echo XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR; echo hi > "$TMPDIR/owned"; test -f "$TMPDIR/owned"')

with tempfile.TemporaryDirectory(prefix="gd-", dir="/tmp") as base:
    base = Path(base)
    short = base / "s"
    short.mkdir()

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
    body = f"run 'c' bash -c 'echo TMPDIR=$TMPDIR; sleep 1'"
    procs = [subprocess.Popen(["bash", "-c", f'CHECK_LIB_ONLY=1 source "{CHECK}"\nunset CHECK_LIB_ONLY\n{body}\nverdict\n'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=REPO,
                              env={**{k: v for k, v in os.environ.items() if k != "TMPDIR"}, "TMPDIR": str(short)})
             for _ in range(2)]
    seen = [field(p.communicate(timeout=30)[0], "TMPDIR") for p in procs]
    check("two concurrent runs' gates see different dirs", None not in seen and seen[0] != seen[1], str(seen))

    print("CAP: a gate killed by its cap still has its dir removed")
    out, rc = drive("run --cap=1 'slow' bash -c 'echo TMPDIR=$TMPDIR; echo x > \"$TMPDIR/f\"; sleep 30'", short)
    g = field(out, "TMPDIR")
    check("the gate TIMED OUT", "TIMED OUT" in out, out[-300:])
    check("its dir is gone", g is not None and not Path(g).exists(), str(g))

    print("ESCAPED: cleanup by own $G reaches a descendant outside the gate's process group")
    pidf, pidf2 = base / "esc.pid", base / "argv.pid"
    stranger_dir = short / "stranger"   # under the SAME root: a kill by shared prefix would reach it
    stranger_dir.mkdir()
    stranger = subprocess.Popen(["sleep", "60"], env={"PATH": os.environ["PATH"], "TMPDIR": str(stranger_dir)},
                                start_new_session=True)
    gate = base / "esc.sh"
    gate.write_text(
        "echo TMPDIR=$TMPDIR\n"
        f"setsid bash -c 'echo $$ > {pidf}; while :; do date > \"$TMPDIR/w\"; sleep 0.1; done' &\n"
        f"setsid env -u TMPDIR G=\"$TMPDIR\" bash -c 'echo $$ > {pidf2}; exec -a \"fakechrome --user-data-dir=$G/prof\" sleep 60' &\n"
        "sleep 1\nexit 0\n")
    out, rc = drive(f"run 'esc' bash {gate}", short)
    g = field(out, "TMPDIR")
    p1, p2 = pid_in(pidf), pid_in(pidf2)
    time.sleep(0.3)
    check("the gate passed", "✓ esc" in out, out[-300:])
    check("a writer in its own session, carrying TMPDIR=$G, is killed", p1 is not None and not alive(p1), str(p1))
    check("one that dropped TMPDIR but names $G in its argv is killed", p2 is not None and not alive(p2), str(p2))
    check("the gate's dir is gone (no writer recreated it)", g is not None and not Path(g).exists(), str(g))
    check("a stranger with ANOTHER TMPDIR under the same root is untouched", alive(stranger.pid))
    check("no 'outlived' note", "outlived its cleanup" not in out, out[-300:])
    for p in (p1, p2):
        if p and alive(p):
            os.kill(p, signal.SIGKILL)
    stranger.kill()
    stranger.wait()

    print("SHORT (a1 BC-1): a long TMPDIR is not inherited; a socket under the gate's dir still binds")
    long_tmp = base / ("L" * 120)
    long_tmp.mkdir()
    sock_gate = base / "sock.py"
    sock_gate.write_text("import os, socket\nprint('TMPDIR=' + os.environ['TMPDIR'])\ns = socket.socket(socket.AF_UNIX)\n"
                         "p = os.path.join(os.environ['TMPDIR'], 'x' * 60, 'srv.sock')\nos.makedirs(os.path.dirname(p))\n"
                         "s.bind(p)\nprint('BOUND', len(p))\n")
    out, rc = drive(f"run 'sock' python3 {sock_gate}", long_tmp)
    g = field(out, "TMPDIR") or ""
    check(f"the TMPDIR is >=100 bytes ({len(str(long_tmp))})", len(str(long_tmp)) >= 100)
    check("the gate's TMPDIR is <=30 bytes", 0 < len(g) <= 30, f"{len(g)}: {g}")
    check("an AF_UNIX socket under it binds, and the gate reaches its verdict", "BOUND" in out and "✓ sock" in out,
          out[-400:])
    check("the run logs that it rooted at /tmp, and why", "rooted at /tmp, not the" in out and "AF_UNIX" in out,
          out[:300])

print()
print("PASS: every gate gets its own short dir, and nothing of it outlives the gate" if not fails
      else f"FAIL ({len(fails)}): " + "; ".join(fails))
sys.exit(1 if fails else 0)
