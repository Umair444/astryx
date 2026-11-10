#!/usr/bin/env python3
"""Oracle: the restore's ROW-COUNT gates, in scripts/restore_verify.sh and scripts/restore_drill.sh (seed #61553). DB-free:
each block between its markers runs in bash with q_live / q_scratch / psql as functions answering per table (MISSING:
the table does not exist, so the count is empty), and the verdict is the block's own `fail` and its lines.

  V1 an EMPTY table whose live table is empty too (a new org's goals): ✓ "restored, empty", no failure
  V2 0 rows restored while live holds rows: ✗ truncated/corrupt (the primary's guard, not weakened)
  V3 a table that did not restore at all: ✗, even where live is empty
  V4 the ordinary case, rows restored against live rows: ✓; and the live counts are handed on (LIVE_COUNTS)
  V5 ...to the drill restore_verify runs (its restore_drill.sh line carries RESTORE_LIVE_COUNTS)
  D1 the drill handed live counts: an empty table whose live table is empty: ✓ "restored, empty"
  D2 ...0 rows while live holds rows: ✗
  D3 run ALONE (no counts handed in): 0 rows fails, as it always did
  D4 a table that did not restore: ✗ whatever live says
  D5 rows restored: ✓
Seams: RESTORE_VERIFY_SRC, RESTORE_DRILL_SRC (mutant copies: tests/mutants_restore_verify_counts.py and\ntests/mutants_restore_drill_counts.py). Exit 0 · 1.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY = Path(os.environ.get("RESTORE_VERIFY_SRC") or REPO / "scripts" / "restore_verify.sh")
DRILL = Path(os.environ.get("RESTORE_DRILL_SRC") or REPO / "scripts" / "restore_drill.sh")
fails = []
TABLES = ("steps", "messages", "goals", "triggers")


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def block(path, marker):
    m = re.search(rf"^# >>> {marker}$.*?^# <<< {marker}$", path.read_text(), re.S | re.M)
    return m.group(0) if m else None


# each answer function reads the table name from the loop's $t and the per-table value from <PREFIX>_<table>
ANSWER = ('_ans() { local v; eval "v=\\${$1_$t-}"; [ "$v" = MISSING ] || echo "$v"; }\n'
          'q_live() { _ans LIVE; }\nq_scratch() { _ans SCR; }\npsql() { _ans DRILL; }\n')


def run(code, **vals):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LIVE_", "SCR_", "DRILL_", "RESTORE_"))}
    env.update({k: str(v) for k, v in vals.items()})
    r = subprocess.run(["bash", "-c", ANSWER + code + '\necho "FAIL=$fail"\necho "COUNTS=${LIVE_COUNTS:-}"'],
                       capture_output=True, text=True, timeout=60, env=env)
    out = r.stdout + r.stderr
    f = re.search(r"^FAIL=(\d*)$", out, re.M)
    c = re.search(r"^COUNTS=(.*)$", out, re.M)
    return (f.group(1) if f else "?"), out, (c.group(1).strip() if c else "")


def rows(prefix, **over):
    v = {f"{prefix}_{t}": 5 for t in TABLES}
    v.update({f"{prefix}_{t}": n for t, n in over.items()})
    return v


def line(out, t):
    return next((ln for ln in out.splitlines() if f" {t}" in ln and ("✓" in ln or "✗" in ln)), "")


V, D = block(VERIFY, "verify row counts"), block(DRILL, "drill row counts")
check("restore_verify.sh and restore_drill.sh carry their row-count blocks between markers", bool(V and D))
if not (V and D):
    sys.exit(1)

print("restore_verify's counts")
f, out, _ = run(V, **rows("LIVE", goals=0), **rows("SCR", goals=0))
check("V1 goals empty, live empty too: ✓ restored, empty; no failure", f == "0" and "restored, empty" in line(out, "goals")
      and "✗" not in out, out[-400:])
f, out, _ = run(V, **rows("LIVE", goals=3), **rows("SCR", goals=0))
check("V2 0 rows while live has 3: ✗ truncated/corrupt", f == "1" and "✗" in line(out, "goals")
      and "truncated" in line(out, "goals"), out[-400:])
f, out, _ = run(V, **rows("LIVE", goals=0), **rows("SCR", goals="MISSING"))
check("V3 goals did not restore (live empty): ✗ not restorable", f == "1" and "did NOT restore" in line(out, "goals"),
      out[-400:])
f, out, counts = run(V, **rows("LIVE", goals=0, messages=7), **rows("SCR", goals=0, messages=3))
check("V4 rows against rows: ✓; and the live counts are handed on", f == "0" and "restored 3 rows" in line(out, "messages")
      and counts.split() == ["steps=5", "messages=7", "goals=0", "triggers=5"], f"{counts!r} {out[-300:]}")

check("V5 restore_verify hands its live counts to the drill it runs (RESTORE_LIVE_COUNTS on the restore_drill.sh line)",
      bool(re.search(r'^RESTORE_LIVE_COUNTS="\$LIVE_COUNTS" .*scripts/restore_drill\.sh', VERIFY.read_text(), re.M)))

print("\nrestore_drill's counts")
handed = "steps=5 messages=7 goals=0 triggers=5"
f, out, _ = run("fail=0\n" + D, RESTORE_LIVE_COUNTS=handed, **rows("DRILL", goals=0))
check("D1 handed live counts, goals empty with live empty: ✓ restored, empty", f == "0"
      and "restored, empty" in line(out, "goals") and "✗" not in out, out[-400:])
f, out, _ = run("fail=0\n" + D, RESTORE_LIVE_COUNTS="steps=5 messages=7 goals=3 triggers=5", **rows("DRILL", goals=0))
check("D2 0 rows while live has 3: ✗", f == "1" and "✗" in line(out, "goals"), out[-400:])
f, out, _ = run("fail=0\n" + D, **rows("DRILL", goals=0))
check("D3 run ALONE (no counts handed in): 0 rows fails, as it always did", f == "1" and "✗" in line(out, "goals"),
      out[-400:])
f, out, _ = run("fail=0\n" + D, RESTORE_LIVE_COUNTS=handed, **rows("DRILL", goals="MISSING"))
check("D4 goals did not restore (live empty): ✗", f == "1" and "✗" in line(out, "goals"), out[-400:])
f, out, _ = run("fail=0\n" + D, RESTORE_LIVE_COUNTS=handed, **rows("DRILL"))
check("D5 rows restored: ✓, no failure", f == "0" and "restored 5 rows" in line(out, "goals"), out[-400:])

print()
print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
      "ALL PASS: an empty table restores as empty only where live is empty; a missing or truncated one fails")
sys.exit(1 if fails else 0)
