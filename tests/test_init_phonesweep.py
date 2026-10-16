#!/usr/bin/env python3
"""Oracle: init.sh's phonesweep node (plan-8675 S2 follow-up, seed #48593): the phone resume sweep installs itself, but
only where the org opted in to phones. The node's block runs in throwaway trees (tests/trigger_tree, with
src/astryx/core/trigger_names.py, which the node asks) against a fixture database.

  P1 ANDROID_ENABLED unset (or 0): the node reads green and installs nothing (an org without phones gets no trigger)
  P2 ANDROID_ENABLED=1, no install: the reconciler step (chk, act, chk) installs triggers/seed/phone_resume_sweep.py,
     a shim that imports the SHIPPED trigger, and the node then reads green
  P3 deferential: another agent already owns a phone_resume_sweep → nothing is added under seed
  P4 the node is in the reconciler's order, after android (so the SDK is there before its detector)
  P5 opted in by PROCESS ENV (android_setup.sh reads env first): the detector installs too (a4 #48950 note 1)
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
INIT = Path(os.environ.get("INIT_PHONESWEEP_SRC") or (REPO / "init.sh"))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


src = INIT.read_text()
# the node asks src/astryx/core/trigger_names.py (plan-9853), so it runs in a tree that has the helper, against a
# fixture database (a name is absent only if no row says otherwise)
STATE = re.search(r"^# >>> trigger state$.*?^# <<< trigger state$", src, re.S | re.M)
try:
    import trigger_tree
    from astryx.security.sqlguard.fixture import fixture_db, FixtureUnavailable
    _FX = fixture_db()
    DSN = _FX.__enter__()["dsn"]
except Exception as e:  # noqa: BLE001
    print(f"SKIP: no fixture database ({type(e).__name__}). Nothing was verified here.")
    sys.exit(77)
m = re.search(r"^# >>> phone sweep install.*?^# <<< phone sweep install$", src, re.S | re.M)
check("init.sh carries the phone-sweep block between its markers", bool(m))
if not m:
    print("FAIL")
    sys.exit(1)


def reconcile(d: Path, env_enabled: str | None = None) -> tuple[int, int]:
    """The reconciler's own step for one interior node: chk; if red, act; chk again. Returns (first chk, last chk).
    ANDROID_ENABLED in the process env is set by the ARM, never inherited from whoever runs this oracle."""
    script = ("say() { :; }\n" + STATE.group(0) + "\n" + m.group(0) +
              "\n_chk_phonesweep; a=$?\nif [ $a -ne 0 ]; then _act_phonesweep; fi\n_chk_phonesweep; b=$?\necho \"$a $b\"\n")
    env = {k: v for k, v in os.environ.items() if k != "ANDROID_ENABLED"}
    if env_enabled is not None:
        env["ANDROID_ENABLED"] = env_enabled
    r = subprocess.run(["bash", "-c", script], cwd=d, capture_output=True, text=True, timeout=120, env={**env, "ASTRYX_DSN": DSN})
    a, b = (r.stdout.strip().split() + ["?", "?"])[:2]
    return a, b


SHIM = Path("triggers/seed/phone_resume_sweep.py")
for label, env in (("unset", ""), ("0", "ANDROID_ENABLED=0\n")):
    with tempfile.TemporaryDirectory() as td:
        d = trigger_tree.build(Path(td))
        (d / ".env").write_text("ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/none\n" + env)
        a, b = reconcile(d)
        check(f"P1 ANDROID_ENABLED {label}: the node is green and installs nothing",
              a == "0" and b == "0" and not (d / SHIM).exists(), f"chk={a},{b} shim={(d / SHIM).exists()}")
with tempfile.TemporaryDirectory() as td:
    d = trigger_tree.build(Path(td))
    (d / ".env").write_text("ANDROID_ENABLED=1\n")
    a, b = reconcile(d)
    body = (d / SHIM).read_text() if (d / SHIM).exists() else ""
    check("P2 opted in: the node starts RED and the reconciler step installs the shim, then reads green",
          a != "0" and b == "0" and (d / SHIM).exists(), f"chk={a},{b}")
    check("P2 the shim imports the SHIPPED trigger (one writer)",
          "from astryx.pulse.shipped_triggers.phone_resume_sweep import phone_resume_sweep" in body, body[:120])
with tempfile.TemporaryDirectory() as td:            # opted in by PROCESS ENV, as android_setup.sh honours (env first)
    d = trigger_tree.build(Path(td))
    (d / ".env").write_text("ASTRYX_DSN=postgresql://nobody@127.0.0.1:1/none\n")
    a, b = reconcile(d, env_enabled="1")
    check("P5 opted in by process env (android_setup.sh's order): the detector installs too, never phones alone",
          a != "0" and b == "0" and (d / SHIM).exists(), f"chk={a},{b} shim={(d / SHIM).exists()}")
with tempfile.TemporaryDirectory() as td:
    d = trigger_tree.build(Path(td))
    (d / ".env").write_text("ANDROID_ENABLED=1\n")
    (d / "triggers" / "steward").mkdir(parents=True)
    (d / "triggers" / "steward" / "phone_resume_sweep.py").write_text(trigger_tree.shim("phone_resume_sweep"))
    a, b = reconcile(d)
    check("P3 deferential: another agent already owns it → green, nothing added under seed",
          a == "0" and not (d / SHIM).exists(), f"chk={a} shim={(d / SHIM).exists()}")
nodes = re.search(r"RECONCILE_NODES=\((.*?)\)", src, re.S)
order = re.findall(r'"([a-z]+)\|', nodes.group(1)) if nodes else []
check("P4 the node is in RECONCILE_NODES, after android", "phonesweep" in order and "android" in order
      and order.index("phonesweep") > order.index("android"), str(order[-6:]))

_FX.__exit__(None, None, None)
if fails:
    print(f"FAIL: {len(fails)}")
    sys.exit(1)
print("PASS: init.sh installs the phone resume sweep only where phones are opted in, deferentially")
