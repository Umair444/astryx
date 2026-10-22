#!/usr/bin/env python3
"""Oracle: devtools/probe_all.sh's REFUSED block keeps the probe's own refusal HEADER, not only its last lines.

    PROBE_ALL_SRC=<path> …   (the subject; default devtools/probe_all.sh)

WHY. On 10-22 the smoke family (mutants_check_coverage) REFUSED once at load ~11 and never again in four runs. The probe
says WHICH refusal on its first line: "REFUSING: … did not finish within Ns" (a timeout) vs "REFUSING: … does not pass"
(a red baseline) vs "WIRING FAULT:". probe_all printed `tail -3` of the probe's output, and the probe prints the
oracle's own lines after that header, so the three lines kept were the oracle's ✓ arms and the discriminator was cut
off: the cause stayed undetermined between load and a real red (a1 #62229, a4 #62230).

Hermetic: each arm builds a stub tree in a temp dir: the subject at devtools/probe_all.sh (it cd's to its own
parent), a STUB devtools/mutation_probe.py that prints a scripted header then N oracle lines then exits with a scripted
rc, and tests/mutants_*.py specs for the glob. The real probe never runs.
  A1  a refusal whose header is followed by more than 3 oracle lines still shows the header (RED on `tail -3`)
  A2  …and still shows the oracle's LAST line (the header is added, the tail is not traded for it)
  A3  a WIRING FAULT header is kept the same way
  A4  the shown block is bounded: 200 oracle lines don't all reach the log
  A5  a refused set still exits 1 and names the spec under REFUSED:
  A6  a refusal with NO header line (a crash) still shows its tail, and only once
  A7  --smoke runs the named family only
  A8  a header already inside the last lines is shown once, not twice
  C1  control: a probe that exits 0 prints the ✓ line and no refusal block, rc 0
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("PROBE_ALL_SRC") or REPO / "devtools" / "probe_all.sh")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail[-400:]}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


STUB = '''import sys
spec = sys.argv[1]
plan = {plan!r}
header, n, rc = plan.get(spec.rsplit("/", 1)[-1], ("", 0, 0))
if header:
    print(header)
for i in range(n):
    print(f"    |   \\u2713 oracle-arm-{{i}}")
if n:
    print("    |   LAST-ORACLE-LINE")
sys.exit(rc)
'''


def run(td: Path, plan: dict, specs, args=()) -> tuple:
    (td / "devtools").mkdir(parents=True)
    (td / "tests").mkdir()
    shutil.copy2(SUBJECT, td / "devtools" / "probe_all.sh")
    (td / "devtools" / "mutation_probe.py").write_text(STUB.format(plan=plan))
    for s in specs:
        (td / "tests" / s).write_text("MUTANTS = {}\n")
    env = {k: v for k, v in os.environ.items() if k != "PY"}
    env["PY"] = "python3"
    r = subprocess.run(["bash", str(td / "devtools" / "probe_all.sh"), *args], capture_output=True, text=True,
                       timeout=60, env=env, cwd=td)
    return r.returncode, r.stdout + r.stderr


with tempfile.TemporaryDirectory() as t:
    t = Path(t)

    hdr = "REFUSING: oracle-x.py did not finish within 120s against the unmutated subject. Declare a larger TIMEOUT"
    rc, out = run(t / "a1", {"mutants_a.py": (hdr, 12, 1)}, ["mutants_a.py"])
    check("A1 a refusal followed by 12 oracle lines still shows its REFUSING header", "did not finish within 120s" in out,
          out)
    check("A2 …and still shows the oracle's last line", "LAST-ORACLE-LINE" in out, out)
    check("A5 a refused set exits 1 and is named under REFUSED:",
          rc == 1 and any(ln.startswith("REFUSED:") and "mutants_a.py" in ln for ln in out.splitlines()), out)

    rc, out = run(t / "a3", {"mutants_w.py": ("WIRING FAULT: oracle-w.py PASSED against a syntactically destroyed copy",
                                              9, 1)}, ["mutants_w.py"])
    check("A3 a WIRING FAULT header is kept the same way", "WIRING FAULT: oracle-w.py" in out and "LAST-ORACLE-LINE" in out,
          out)

    rc, out = run(t / "a4", {"mutants_b.py": ("REFUSING: oracle-b.py does not pass against the unmutated subject", 200, 1)},
                  ["mutants_b.py"])
    shown = sum("oracle-arm-" in ln for ln in out.splitlines())
    check("A4 the shown block is bounded (200 oracle lines, at most 20 reach the log)", shown <= 20, f"{shown} shown")
    check("A4 …with the header still there", "does not pass against the unmutated subject" in out, out)

    rc, out = run(t / "a6", {"mutants_c.py": ("", 6, 1)}, ["mutants_c.py"])
    check("A6 a refusal with no header still shows its tail, once",
          rc == 1 and out.count("LAST-ORACLE-LINE") == 1, out)

    rc, out = run(t / "a8", {"mutants_d.py": ("REFUSING: oracle-d.py does not pass (short)", 1, 1)}, ["mutants_d.py"])
    check("A8 a header already inside the last lines is shown once, not twice",
          out.count("REFUSING: oracle-d.py does not pass (short)") == 1, out)

    rc, out = run(t / "a7",{"mutants_check_coverage.py": ("", 0, 0), "mutants_zz.py": ("REFUSING: never run", 0, 1)},
                  ["mutants_check_coverage.py", "mutants_zz.py"], ["--smoke"])
    check("A7 --smoke runs the named family only", rc == 0 and "never run" not in out and "1 authored" in out, out)

    rc, out = run(t / "c1", {"mutants_ok.py": ("", 0, 0)}, ["mutants_ok.py"])
    check("C1 control: a passing probe gives its ✓ line, no REFUSED block, rc 0",
          rc == 0 and "mutants_ok.py" in out and "REFUSED" not in out, out)

print(f"{'PASS' if not fails else 'FAIL'}: probe_all refusal block ({len(fails)} failing)")
raise SystemExit(1 if fails else 0)
