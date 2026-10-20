#!/usr/bin/env python3
"""Oracle: init.sh's orgbackup node (seed #61526): a fresh one-org install gets its backup scheduled, deferentially.
The node's block runs in throwaway trees (tests/trigger_tree, with src/astryx/core/trigger_names.py, which the node
asks) against a fixture database.

  B1 nothing defines run_backup or run_restore_verify: RED, the reconciler installs triggers/seed/org_backup.py, the
     one source's text (shims.py), then reads green
  B2 deferential on EITHER name: another agent owns only run_backup (the org's own backup) → green, nothing under
     seed; owns only run_restore_verify → the same (one name owned is never given a second)
  B3 a seed-retired run_backup (trigger_rm's tombstone) stays retired: green, nothing installed
  B4 the node is in RECONCILE_NODES, after agentheal; TRIGGER_NODES maps BOTH names to it (doctor and --reinstall)
Seams: INIT_ORGBACKUP_SRC (a mutant init.sh, tests/mutants_init_orgbackup.py). Exit 0 · 1 · 77 (no fixture DB).
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "src"))
INIT = Path(os.environ.get("INIT_ORGBACKUP_SRC") or (REPO / "init.sh"))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


src = INIT.read_text()
STATE = re.search(r"^# >>> trigger state$.*?^# <<< trigger state$", src, re.S | re.M)
try:
    import trigger_tree
    from astryx.security.sqlguard.fixture import fixture_db
    _FX = fixture_db()
    DSN = _FX.__enter__()["dsn"]
except Exception as e:  # noqa: BLE001
    print(f"SKIP: no fixture database ({type(e).__name__}). Nothing was verified here.")
    sys.exit(77)
from astryx.pulse.shipped_triggers import shims  # noqa: E402
m = re.search(r"^# >>> org backup install$.*?^# <<< org backup install$", src, re.S | re.M)
check("init.sh carries the org-backup block between its markers", bool(m and STATE))
if not (m and STATE):
    sys.exit(1)
SHIM = Path("triggers/seed/org_backup.py")
TRIG = 'from astryx import trigger\n\n\n@trigger("*/5 * * * *", note="x")\ndef {}(ctx):\n    return None\n'


def reconcile(d: Path):
    """chk; if red, act; chk again (init.sh's reconciler step for one node)."""
    script = ("say() { :; }\n" + STATE.group(0) + "\n" + m.group(0) +
              "\n_chk_orgbackup; a=$?\nif [ $a -ne 0 ]; then _act_orgbackup; fi\n_chk_orgbackup; b=$?\necho \"$a $b\"\n")
    env = {k: v for k, v in os.environ.items() if k != "ASTRYX_DSN"}
    r = subprocess.run(["bash", "-c", script], cwd=d, capture_output=True, text=True, timeout=180,
                       env={**env, "ASTRYX_DSN": DSN})
    return (r.stdout.strip().split() + ["?", "?"])[:2], r.stderr[-300:]


with tempfile.TemporaryDirectory() as td:
    d = trigger_tree.build(Path(td))
    (a, b), err = reconcile(d)
    body = (d / SHIM).read_text() if (d / SHIM).exists() else ""
    check("B1 nothing defines either name: starts RED, the reconciler installs the shim, then green",
          a != "0" and b == "0" and (d / SHIM).exists(), f"chk={a},{b} {err}")
    check("B1 ...the shim is the one source's text (shims.py)", body == shims.SHIMS["org_backup"], body[:120])
for owned in ("run_backup", "run_restore_verify"):
    with tempfile.TemporaryDirectory() as td:
        d = trigger_tree.build(Path(td))
        (d / "triggers" / "steward").mkdir(parents=True)
        (d / "triggers" / "steward" / "own.py").write_text(TRIG.format(owned))
        (a, b), err = reconcile(d)
        check(f"B2 another agent owns only {owned}: green, nothing under seed (never a second)",
              a == "0" and not (d / SHIM).exists(), f"chk={a} {err}")
with tempfile.TemporaryDirectory() as td:
    d = trigger_tree.build(Path(td))
    (d / "triggers" / "seed" / ".retired").mkdir(parents=True)
    (d / "triggers" / "seed" / ".retired" / "run_backup").write_text("retired by trigger_rm\n")
    (a, b), err = reconcile(d)
    check("B3 seed's run_backup retired: stays retired (green, nothing installed)", a == "0" and not (d / SHIM).exists(),
          f"chk={a} {err}")
nodes = re.search(r"RECONCILE_NODES=\((.*?)\)", src, re.S)
order = re.findall(r'"([a-z]+)\|', nodes.group(1)) if nodes else []
check("B4 orgbackup is in RECONCILE_NODES, after agentheal", "orgbackup" in order and "agentheal" in order
      and order.index("orgbackup") > order.index("agentheal"), str(order[-7:]))
tn = re.search(r"^TRIGGER_NODES=\((.*?)\)", src, re.S | re.M)
pairs = dict(e.split("|") for e in re.findall(r'"([a-z_]+\|[a-z]+)"', tn.group(1))) if tn else {}
check("B4 TRIGGER_NODES maps BOTH run_backup and run_restore_verify to it (doctor's lines, --reinstall)",
      pairs.get("run_backup") == "orgbackup" and pairs.get("run_restore_verify") == "orgbackup", str(pairs))

_FX.__exit__(None, None, None)
if fails:
    print(f"FAIL: {len(fails)}")
    sys.exit(1)
print("PASS: init.sh schedules a one-org backup only when no agent owns either name")
