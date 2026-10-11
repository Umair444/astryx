#!/usr/bin/env python3
"""Oracle for check.sh's per-gate wall clock (seed #45252, after a wedged chromium held a run open 3h36m, a4 #45241).

Drives the REAL run() by sourcing nucleus/check.sh with CHECK_LIB_ONLY=1 (as test_check_verdict does), with stub
gates and caps of a second or two:
  EXPIRY      a gate past its cap is ✗ TIMED OUT, counted FAILED (never a pass, never 77), and its pid is gone
  GROUP       a grandchild the gate forked dies with it, and so does one that IGNORES SIGTERM (the -k SIGKILL)
  OVERRIDE    `run --cap=<s>` caps one gate below the default
  PASSTHROUGH rc 0 → ✓, rc 3 → ✗ (not TIMED OUT), rc 77 → ○; a gate that exits 124 BY ITSELF is a plain ✗
  SQLGUARD    the expired gate's rc still lands in gates.tsv (the judge reads every gate's rc)
  SIGNAL      a TERM to check.sh itself kills the running gate's whole group (it used to orphan it)
Exit 0 pass · 1 fail.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "nucleus" / "check.sh"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def drive(body, env="", timeout=20):
    """A run that outlives `timeout` is reported as (TIMEOUT, -1): each arm then FAILS and the next arm still runs,
    so a RED control against an uncapped check.sh reds EVERY arm instead of crashing at the first (a4 #45258)."""
    script = f'CHECK_LIB_ONLY=1 source "{CHECK}"\nunset CHECK_LIB_ONLY\n{env}\n{body}\nverdict\n'
    t0 = time.monotonic()
    try:
        p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=timeout, cwd=REPO)
    except subprocess.TimeoutExpired:
        return "TIMEOUT: the driven run outlived the harness", -1, time.monotonic() - t0
    return p.stdout + p.stderr, p.returncode, time.monotonic() - t0


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    st = Path(f"/proc/{pid}/stat")
    return st.exists() and st.read_text().split(") ", 1)[-1][:1] != "Z"


def pid_in(path):
    for _ in range(50):
        if path.exists() and path.read_text().strip():
            return int(path.read_text().split()[0])
        time.sleep(0.1)
    return None


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    caps = "GATE_CAP=2; GATE_KILL_AFTER=1"

    print("expiry:")
    out, rc, dt = drive(f'run "slow" bash -c \'echo $$ > {td}/slow; sleep 30\'', caps)
    pid = pid_in(td / "slow")
    check("a gate past its cap is ✗ TIMED OUT, named with its cap", "slow — TIMED OUT after 2s" in out, out[-300:])
    check("…counted as a FAILURE (verdict rc 1, in the FAILED set), never a pass or a skip",
          rc == 1 and "slow (TIMED OUT after 2s)" in out and "VERIFIED NOTHING" not in out, f"rc {rc}")
    check("…the run moved on at the cap, not at the gate's 30s", dt < 12, f"{dt:.1f}s")
    check("…and the gate's process is gone", pid is not None and not alive(pid), f"pid {pid}")

    print("group:")
    out, rc, _ = drive(f'run "fork" bash -c \'(sleep 60 & echo $! > {td}/gc; wait) ; wait\'', caps)
    gc = pid_in(td / "gc")
    check("a GRANDCHILD the gate forked dies with the gate's group", gc is not None and not alive(gc), f"gc {gc}")
    out, rc, _ = drive(f'run "stubborn" bash -c \'trap "" TERM; (trap "" TERM; sleep 60 & echo $! > {td}/st; wait); '
                       f'wait\'', caps)
    time.sleep(1.5)
    st = pid_in(td / "st")
    check("a descendant that IGNORES SIGTERM is SIGKILLed after the grace (-k)", st is not None and not alive(st),
          f"pid {st}")

    print("override:")
    out, rc, dt = drive('run --cap=1 "capped" sleep 20', "GATE_CAP=600; GATE_KILL_AFTER=1")
    check("`run --cap=1` caps that gate below a 600s default", "capped — TIMED OUT after 1s" in out and dt < 10,
          f"{dt:.1f}s {out[-200:]}")

    out, rc, _ = drive('run --cap=1.5 "frac" true', caps)
    check("a non-integer cap is refused, named, and counted FAILED (the wall judge is whole seconds)",
          "frac — bad cap" in out and rc == 1, out[-200:])

    print("passthrough:")
    out, rc, _ = drive('run "ok" true\nrun "bad" bash -c "exit 3"\nrun "skipper" bash -c "exit 77"\n'
                       'run "self124" bash -c "exit 124"', caps)
    check("rc 0 → ✓", "✓ ok" in out)
    check("rc 3 → ✗, and not called TIMED OUT", "✗ bad" in out and "bad — TIMED OUT" not in out)
    check("rc 77 → ○ VERIFIED NOTHING", "○ skipper — VERIFIED NOTHING" in out)
    check("a gate that exits 124 ITSELF, well inside its cap, is a plain ✗ (the wall is the judge, not the code)",
          "✗ self124" in out and "self124 — TIMED OUT" not in out, out[-300:])

    print("sqlguard:")
    sg = td / "sg"
    sg.mkdir()
    out, rc, _ = drive('run "slow2" sleep 30', f'{caps}; export ASTRYX_SQLGUARD_DIR={sg}')
    rows = (sg / "gates.tsv").read_text().splitlines() if (sg / "gates.tsv").exists() else []
    check("the expired gate's rc is written to gates.tsv like any gate's", any(r.startswith("slow2\t") for r in rows),
          str(rows))

    print("signal:")
    script = (f'CHECK_LIB_ONLY=1 source "{CHECK}"\nunset CHECK_LIB_ONLY\nGATE_CAP=600\n'
              f'run "long" bash -c \'echo $$ > {td}/long; (sleep 90 & echo $! > {td}/longgc; wait); wait\'\nverdict\n')
    p = subprocess.Popen(["bash", "-c", script], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    g, ggc = pid_in(td / "long"), pid_in(td / "longgc")
    p.send_signal(signal.SIGTERM)
    p.wait(timeout=20)
    time.sleep(1)
    check("a TERM to check.sh kills its running gate AND the gate's grandchild (no orphan)",
          g is not None and ggc is not None and not alive(g) and not alive(ggc), f"gate {g} gc {ggc}")
    check("…and check.sh itself exits 143", p.returncode == 143, f"rc {p.returncode}")

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    print("race (a TERM in the first milliseconds of a gate):")
    import random
    survivors, tries = 0, 40
    for i in range(tries):
        pf = td / f"r{i}"
        script = (f'CHECK_LIB_ONLY=1 source "{CHECK}"\nunset CHECK_LIB_ONLY\nGATE_CAP=600\n'
                  f'run "race" bash -c \'echo $$ > {pf}; sleep 60\'\nverdict\n')
        p = subprocess.Popen(["bash", "-c", script], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.03 + random.uniform(0.001, 0.009))   # past bash + source startup, into run()'s fork window
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
        time.sleep(0.3)
        g = int(pf.read_text().split()[0]) if pf.exists() and pf.read_text().strip() else None
        if g is not None and alive(g):
            survivors += 1
            os.kill(g, signal.SIGKILL)
    # A TIMING arm can't be the RED (a4 #45394: it passed with the fix reverted): REPORTED, never asserted. The two
    # deterministic arms below pin each window instead.
    print(f"  INFO  smoke: {tries} TERMs in a gate's first milliseconds left {survivors} surviving gate(s)")

    print("reap (deterministic, one arm per window):")

    def reap_case(setup):
        script = (f'CHECK_LIB_ONLY=1 source "{CHECK}"\nunset CHECK_LIB_ONLY\n{setup}\n'
                  f'echo $victim > {td}/victim\n_gate_reap\nsleep 0.5\n'
                  f'kill -0 $victim 2>/dev/null && echo ALIVE || echo DEAD\nkill -9 $victim 2>/dev/null; true\n')
        p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, cwd=REPO)
        return p.stdout.strip().splitlines()[-1:] == ["DEAD"], p.stdout[-200:] + p.stderr[-200:]

    ok, det = reap_case('sleep 300 & victim=$!; GATE_PGID=$victim')
    check("window 1: GATE_PGID names a process that is NOT a group leader (the group isn't formed) → still killed",
          ok, det)
    ok, det = reap_case('sleep 300 & victim=$!; GATE_PGID=""')
    check("window 2: the gate was forked but GATE_PGID is still EMPTY → killed via the shell's jobs", ok, det)

print(f"\n{'FAIL: ' + str(len(fails)) + ' arm(s)' if fails else 'ALL PASS'}")
sys.exit(1 if fails else 0)
