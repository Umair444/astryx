#!/usr/bin/env python3
"""Oracle: when devtools/mutation_probe.py REFUSES (its baseline oracle fails or times out against the unmutated
subject), it prints the oracle's OWN failing lines, so the refusal names its arm (a4 night 10-16; memory #57741: the
parity baseline went red once at load 7.79 and the probe's bare "exit 1" left it unattributable for good).

    MUTATION_PROBE_SRC=<path> …   (the subject; default devtools/mutation_probe.py)

Hermetic: each arm writes a tiny subject, oracle and spec into a temp dir and runs the probe on it as a subprocess.
  R1  a baseline that FAILS: REFUSING, and its failing line is shown even when 60 lines of noise follow it
  R2  a baseline that TIMES OUT: "did not finish", and what it printed before the kill is shown
  R3  a baseline that prints nothing: the refusal says so, never an empty block
  R4  the shown block is capped (≤ REFUSAL_TAIL lines)
  R5  a line that IS a failure beats lines that only mention a keyword (no crowd-out at the cap)
  R6  a subject that can't load from the mutant location REFUSES (the relocated baseline), never grades a no-op CAUGHT
  R7  a same-size mutant right after the baseline is CAUGHT: no cached bytecode of the previous copy stands in for it
  C1  control: a passing baseline prints no tail block, and its mutant is CAUGHT
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("MUTATION_PROBE_SRC") or REPO / "devtools" / "mutation_probe.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail[-400:]}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def probe(td: Path, oracle_body: str, timeout: int = 20, mutants=None, subject: str = "X = 1\n") -> tuple:
    (td / "subj.py").write_text(subject)
    (td / "oracle.py").write_text(oracle_body)
    m = mutants or {"M one": ("X = 1", "X = 2")}
    (td / "spec.py").write_text(
        f"SUBJECT = {str(td / 'subj.py')!r}\nORACLE = {str(td / 'oracle.py')!r}\nENV = 'FIX_SRC'\n"
        f"TIMEOUT = {timeout}\nMUTANTS = {m!r}\n")
    # PYTHONUNBUFFERED out too: an outer mutation_probe sets it for ITS oracle (this file), and inherited here it would
    # make the subject's own setting unobservable (mutant T6 read NOT PROBED until this line)
    env = {k: v for k, v in os.environ.items() if k not in ("FIX_SRC", "ASTRYX_SQLGUARD_DIR", "PYTHONUNBUFFERED",
                                                         "PYTHONDONTWRITEBYTECODE")}
    # the subject finds `astryx` by its OWN path (dirname(dirname(file))), and mutation_probe writes each mutant into a
    # temp dir: without this every mutant of the probe would die at import and read CAUGHT vacuously
    env["PYTHONPATH"] = str(REPO / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    r = subprocess.run([sys.executable, str(SUBJECT), str(td / "spec.py")], capture_output=True, text=True,
                       timeout=120, env=env, cwd=td)
    return r.returncode, r.stdout + r.stderr


def shown(out: str) -> list:
    return [ln for ln in out.splitlines() if ln.startswith("    | ")]


with tempfile.TemporaryDirectory() as t:
    t = Path(t)

    d = t / "r1"; d.mkdir()
    noise = "".join(f"print('  ok    noise line {i}')\n" for i in range(60))
    rc, out = probe(d, "print('  PASS  an early arm')\nprint('  FAIL  arm-zeta-42 the arm that broke')\n"
                       + noise + "raise SystemExit(1)\n")
    check("R1 a failing baseline REFUSES (rc 1)", rc == 1 and "REFUSING" in out, out)
    check("R1 …and shows the oracle's failing line, though 60 lines of noise follow it",
          any("arm-zeta-42" in ln for ln in shown(out)), out)

    d = t / "r2"; d.mkdir()
    # NO flush: a real oracle's check() doesn't flush, and a kill discards a block-buffered pipe (a3 #57897 R-1)
    rc, out = probe(d, "import sys, time\nprint('  FAIL  half-done-77 before the hang')\n"
                       "time.sleep(30)\n", timeout=2)
    check("R2 a baseline that times out REFUSES with 'did not finish'", rc == 1 and "did not finish" in out, out)
    check("R2 …and shows what it printed before the kill", any("half-done-77" in ln for ln in shown(out)), out)

    d = t / "r3"; d.mkdir()
    rc, out = probe(d, "raise SystemExit(1)\n")
    check("R3 a silent failing baseline says it printed nothing", rc == 1 and "(it printed nothing)" in out, out)

    d = t / "r4"; d.mkdir()
    many = "".join(f"print('  FAIL  arm {i}')\n" for i in range(80))
    rc, out = probe(d, many + "raise SystemExit(1)\n")
    n = len(shown(out))
    check("R4 the shown block is capped (1..25 lines)", 1 <= n <= 25, f"{n} lines")

    d = t / "r5"; d.mkdir()
    crowd = "".join(f"print('  PASS  label {i} says OperationalError maps to retry')\n" for i in range(30))
    rc, out = probe(d, crowd + "print('  FAIL  real-broken-arm-7')\nprint('FAIL: 1 failing')\nraise SystemExit(1)\n")
    check("R5 a real FAIL is shown even after 30 PASS lines that merely MENTION a keyword (no crowd-out)",
          any("real-broken-arm-7" in ln for ln in shown(out)), out)

    d = t / "r6"; d.mkdir()
    # a subject that reads a file BESIDE itself loads in place and dies at the mutant location: every mutant, a no-op
    # one too, would read CAUGHT (a4 #60129: main.py's paths.estate(__file__) raised NoHome for a tempdir copy)
    (d / "beside.txt").write_text("ok\n")
    rc, out = probe(d, "import os, sys\nsrc = open(os.environ['FIX_SRC']).read()\n"
                       "exec(compile(src, os.environ['FIX_SRC'], 'exec'), {'__file__': os.environ['FIX_SRC']})\n",
                    mutants={"N0 a no-op": ("X = 1", "X = 1 ")},
                    subject="import os\nopen(os.path.join(os.path.dirname(__file__), 'beside.txt')).read()\nX = 1\n")
    check("R6 an unmutated copy that can't load at the mutant location REFUSES (rc 1), never grades a no-op CAUGHT",
          rc == 1 and "REFUSING" in out and not any(ln.lstrip().startswith("CAUGHT") for ln in out.splitlines()), out)

    d = t / "r7"; d.mkdir()
    # an oracle that IMPORTS its subject reads a cached .pyc when the next copy has the same SIZE and lands in the same
    # mtime second at the same path: the mutant below ran as the unmutated copy and read NOT PROBED (memory #60378, D1)
    # the oracle PINS the copy's mtime first, so "the same second" is certain, not a race (2 of 3 runs RED without it)
    rc, out = probe(d, "import importlib.util, os, sys\nos.utime(os.environ['FIX_SRC'], (1e9, 1e9))\n"
                       "s = importlib.util.spec_from_file_location('subj', os.environ['FIX_SRC'])\n"
                       "m = importlib.util.module_from_spec(s)\ns.loader.exec_module(m)\nsys.exit(0 if m.X == 1 else 1)\n",
                    mutants={"M same size": ("X = 1", "X = 2")})
    check("R7 a SAME-SIZE mutant right after the baseline is CAUGHT (no stale bytecode stands in for it)",
          rc == 0 and any(ln.lstrip().startswith("CAUGHT") for ln in out.splitlines()), out)

    d = t / "c1"; d.mkdir()
    rc, out = probe(d, "import os, sys\nsys.exit(0 if 'X = 1' in open(os.environ['FIX_SRC']).read() else 1)\n")
    check("C1 control: a passing baseline prints no tail block, and its mutant is CAUGHT",
          rc == 0 and not shown(out) and "CAUGHT" in out, out)

print(f"\n{'FAIL' if fails else 'PASS'}: mutation_probe refusal tail ({len(fails)} failing)")
sys.exit(1 if fails else 0)
