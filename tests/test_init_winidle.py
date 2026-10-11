#!/usr/bin/env python3
"""Oracle: init.sh's winidle node (plan-8675 C5): the Windows idle stop installs itself only where this host HAS a
Windows container. The node's block runs in throwaway trees (tests/trigger_tree, with
nucleus/trigger_names.py, which the node asks) against a fixture database, with a fake `docker` first on PATH.

  I1 no Windows container (docker inspect fails): green, nothing installed
  I2 a Windows container exists: the reconciler step installs triggers/seed/windows_idle_stop.py, a shim importing
     the SHIPPED trigger, then reads green; WINDOWS_CONTAINER names the container it looks for
  I3 deferential: another agent already owns a windows_idle_stop → nothing added under seed
  I4 the node is in RECONCILE_NODES
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
INIT = Path(os.environ.get("INIT_WINIDLE_SRC") or (REPO / "init.sh"))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


src = INIT.read_text()
# the node asks nucleus/trigger_names.py (plan-9853), so it runs in a tree that has the helper, against a
# fixture database (a name is absent only if no row says otherwise)
STATE = re.search(r"^# >>> trigger state$.*?^# <<< trigger state$", src, re.S | re.M)
try:
    import trigger_tree
    from nucleus.sqlguard.fixture import fixture_db, FixtureUnavailable
    _FX = fixture_db()
    DSN = _FX.__enter__()["dsn"]
except Exception as e:  # noqa: BLE001
    print(f"SKIP: no fixture database ({type(e).__name__}). Nothing was verified here.")
    sys.exit(77)
m = re.search(r"^# >>> windows idle install.*?^# <<< windows idle install$", src, re.S | re.M)
check("init.sh carries the windows-idle block between its markers", bool(m))
if not m:
    sys.exit(1)
SHIM = Path("triggers/seed/windows_idle_stop.py")


def reconcile(d: Path, exists: set[str], container: str | None = None):
    """chk; if red, act; chk again, with a fake docker whose `inspect <name>` succeeds only for names in `exists`."""
    bin_ = d / "bin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "docker").write_text("#!/bin/sh\n[ \"$1\" = inspect ] || exit 1\ncase \" " + " ".join(exists) +
                                 " \" in *\" $2 \"*) exit 0;; esac\nexit 1\n")
    (bin_ / "docker").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "WINDOWS_CONTAINER"}
    env["PATH"] = f"{bin_}:{env.get('PATH', '/usr/bin:/bin')}"
    if container:
        env["WINDOWS_CONTAINER"] = container
    script = ("say() { :; }\n" + STATE.group(0) + "\n" + m.group(0) +
              "\n_chk_winidle; a=$?\nif [ $a -ne 0 ]; then _act_winidle; fi\n_chk_winidle; b=$?\necho \"$a $b\"\n")
    r = subprocess.run(["bash", "-c", script], cwd=d, capture_output=True, text=True, timeout=120, env={**env, "ASTRYX_DSN": DSN})
    return (r.stdout.strip().split() + ["?", "?"])[:2]


with tempfile.TemporaryDirectory() as td:
    d = trigger_tree.build(Path(td))
    a, b = reconcile(d, set())
    check("I1 no Windows container: green, nothing installed", a == "0" and b == "0" and not (d / SHIM).exists(),
          f"chk={a},{b}")
with tempfile.TemporaryDirectory() as td:
    d = trigger_tree.build(Path(td))
    a, b = reconcile(d, {"windows"})
    body = (d / SHIM).read_text() if (d / SHIM).exists() else ""
    check("I2 a Windows container: starts RED, the reconciler installs the shim, then green",
          a != "0" and b == "0" and (d / SHIM).exists(), f"chk={a},{b}")
    check("I2 the shim imports the SHIPPED trigger",
          "from nucleus.shipped_triggers.windows_idle_stop import windows_idle_stop" in body, body[:100])
with tempfile.TemporaryDirectory() as td:
    d = trigger_tree.build(Path(td))
    a, b = reconcile(d, {"win11"}, container="win11")
    check("I2 WINDOWS_CONTAINER names the container it looks for", a != "0" and (d / SHIM).exists(), f"chk={a}")
with tempfile.TemporaryDirectory() as td:
    d = trigger_tree.build(Path(td))
    (d / "triggers" / "steward").mkdir(parents=True)
    (d / "triggers" / "steward" / "windows_idle_stop.py").write_text(trigger_tree.shim("windows_idle_stop"))
    a, b = reconcile(d, {"windows"})
    check("I3 deferential: an existing owner → green, nothing under seed", a == "0" and not (d / SHIM).exists(),
          f"chk={a}")
nodes = re.search(r"RECONCILE_NODES=\((.*?)\)", src, re.S)
order = re.findall(r'"([a-z]+)\|', nodes.group(1)) if nodes else []
check("I4 the node is in RECONCILE_NODES", "winidle" in order, str(order[-6:]))

_FX.__exit__(None, None, None)
if fails:
    print(f"FAIL: {len(fails)}")
    sys.exit(1)
print("PASS: init.sh installs the Windows idle stop only where a Windows container exists, deferentially")
