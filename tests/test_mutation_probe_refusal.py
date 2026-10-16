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


def probe(td: Path, oracle_body: str, timeout: int = 20, mutants=None) -> tuple:
    (td / "subj.py").write_text("X = 1\n")
    (td / "oracle.py").write_text(oracle_body)
    m = mutants or {"M one": ("X = 1", "X = 2")}
    (td / "spec.py").write_text(
        f"SUBJECT = {str(td / 'subj.py')!r}\nORACLE = {str(td / 'oracle.py')!r}\nENV = 'FIX_SRC'\n"
        f"TIMEOUT = {timeout}\nMUTANTS = {m!r}\n")
    env = {k: v for k, v in os.environ.items() if k not in ("FIX_SRC", "ASTRYX_SQLGUARD_DIR")}
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
    rc, out = probe(d, "import sys, time\nprint('  FAIL  half-done-77 before the hang', flush=True)\n"
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

    d = t / "c1"; d.mkdir()
    rc, out = probe(d, "import os, sys\nsys.exit(0 if 'X = 1' in open(os.environ['FIX_SRC']).read() else 1)\n")
    check("C1 control: a passing baseline prints no tail block, and its mutant is CAUGHT",
          rc == 0 and not shown(out) and "CAUGHT" in out, out)

print(f"\n{'FAIL' if fails else 'PASS'}: mutation_probe refusal tail ({len(fails)} failing)")
sys.exit(1 if fails else 0)
