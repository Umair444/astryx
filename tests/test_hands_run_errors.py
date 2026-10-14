#!/usr/bin/env python3
"""Oracle: a Hands tool that FAILS says how (seed #50593, canopus #50568). On 10-12 the background desk's captures
returned "hands error: grim failed: " with nothing after it: grim had died by SIGBUS (rc -7, empty stderr; its
shared-memory frame couldn't be backed while the host was over its commit limit). A signal death leaves stderr
empty, so the error must carry the exit code or the signal, always.

  E1 THE SYMPTOM'S PATH: fingerprint() (look's capture) with a grim that dies by SIGBUS → the HandsError names
     grim, SIGBUS and what it means (on main: "grim failed: " and nothing else, RED)
  E2 a SIGKILL names the signal and the OOM hint; an unhinted signal is still named
  E3 a non-zero exit WITH stderr carries both; E4 WITHOUT stderr says "exit N, no stderr"
  E5 success returns stdout unchanged (control)
No sway needed: the tool and its env are stand-ins.
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


spec = importlib.util.spec_from_file_location("hands_desktop_under_test",
                                              os.environ.get("HANDS_DESKTOP_SRC") or REPO / "nucleus/hands_desktop.py")
hd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hd)
BIN = Path(tempfile.mkdtemp(prefix="hands-run-oracle-"))
hd._env = lambda agent: {**os.environ, "PATH": f"{BIN}:{os.environ.get('PATH', '/usr/bin:/bin')}"}


def tool(name, body):
    f = BIN / name
    f.write_text("#!/bin/sh\n" + body + "\n")
    f.chmod(0o755)


def err_of(fn):
    try:
        fn()
    except hd.HandsError as e:
        return str(e)
    return None


tool("grim", "kill -BUS $$")
e = err_of(lambda: hd.fingerprint("desk-oracle"))
want("E1 look's capture with a grim killed by SIGBUS: the error names grim, SIGBUS and what it means",
     bool(e) and e.startswith("grim failed:") and "SIGBUS" in e and "shared-memory" in e and "no stderr" in e, repr(e))
tool("t", "kill -KILL $$")
e = err_of(lambda: hd._run("desk-oracle", ["t"]))
want("E2 a SIGKILL names the signal and the OOM hint", bool(e) and "SIGKILL" in e and "OOM" in e, repr(e))
tool("t", "kill -USR1 $$")
e = err_of(lambda: hd._run("desk-oracle", ["t"]))
want("E2 ...an unhinted signal is still named", bool(e) and "killed by SIGUSR1" in e, repr(e))
tool("t", "echo boom >&2; exit 3")
e = err_of(lambda: hd._run("desk-oracle", ["t"]))
want("E3 exit 3 with stderr → both", e == "t failed: exit 3: boom", repr(e))
tool("t", "exit 1")
e = err_of(lambda: hd._run("desk-oracle", ["t"]))
want("E4 exit 1 with no stderr → says so", e == "t failed: exit 1, no stderr", repr(e))
tool("t", "printf ok")
want("E5 success returns stdout (control)", hd._run("desk-oracle", ["t"]) == b"ok")

import shutil  # noqa: E402
shutil.rmtree(BIN, ignore_errors=True)
if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
print("PASS: a failed Hands tool says its exit code or signal (and what a SIGBUS/SIGKILL means), never an empty error")
