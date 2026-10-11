"""astryx · the Windows VM's idle stop (plan-8675 C5, a4 #42255 / #48958; SHIPPED REFERENCE; one writer).

The Windows VM runs on demand: an agent opening its viewer starts it (nucleus/hands_desktop.windows_up, which holds the
vm-slot). This stops it again when nobody has been connected for HANDS_WINDOWS_IDLE_S (default 900; 0 disables), and
frees the vm-slot so the phone can run.

ONLY a run that windows_up STARTED (its record, hands_desktop.WINDOWS_STARTED) is ever stopped. A VM the owner started,
or one already running when an agent opened it, is never stopped here: "no connection" means nobody is WATCHING, not
that nothing is RUNNING (an install, a download, a render), and the stop is a hard kill (S0, measured: the guest
ignores ACPI and dockur kills qemu after ~100 s).

Pulse budget: the stop takes ~100 s, so a tick only ISSUES it (detached) and returns; a later tick, seeing the container
stopped, frees the slot and clears the record. The phone can't take the slot while Windows still holds its RAM.

Install:
  printf 'from nucleus.shipped_triggers.windows_idle_stop import windows_idle_stop  # noqa: F401\\n' \\
      > triggers/seed/windows_idle_stop.py
"""
from __future__ import annotations

import json
import os
import subprocess
import time

from astryx import trigger
from nucleus import android, hands_desktop as hd


def idle_s() -> int:
    try:
        return int(os.environ.get("HANDS_WINDOWS_IDLE_S") or android._env_file().get("HANDS_WINDOWS_IDLE_S") or 900)
    except ValueError:
        return 900


def connections() -> int:
    """Established connections to the VM's viewer or RDP port on this host (its watchers)."""
    r = subprocess.run(["ss", "-Htn", "state", "established", f"( sport = :{hd.WINDOWS_PORT} or sport = :3389 )"],
                       capture_output=True, text=True, timeout=10)
    return len([ln for ln in r.stdout.splitlines() if ln.strip()]) if r.returncode == 0 else 1   # unknown → busy


def started_record() -> dict | None:
    try:
        rec = json.loads(hd.WINDOWS_STARTED.read_text())
        return rec if isinstance(rec.get("ts"), (int, float)) else None
    except (OSError, ValueError, AttributeError):
        return None


def tick(state: dict, now: float | None = None, conns=None) -> str | None:
    now = time.time() if now is None else now
    rec = started_record()
    if rec is None:                                     # not started by an agent's open: never stopped here
        state.clear()
        return None
    if not android.windows_running():                   # stopped (by us, or anyone): give the slot back
        android.free_slot("windows")
        hd.WINDOWS_STARTED.unlink(missing_ok=True)
        was = state.pop("stopping", None)
        state.clear()
        return ("the Windows VM is stopped and its slot is free (it had been idle)" if was else None)
    if state.get("stopping"):                           # a stop is under way: wait for it
        return None
    limit = idle_s()
    if limit <= 0:
        return None
    n = connections() if conns is None else conns()
    if n > 0:
        state["busy"] = now
        return None
    last = max(float(rec["ts"]), float(state.get("busy", 0)))
    if now - last < limit:
        return None
    subprocess.Popen(["docker", "stop", "-t", "120", rec.get("container") or android.WINDOWS_CONTAINER],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    state["stopping"] = now
    return (f"stopping the Windows VM: an agent started it and nobody has been connected for {limit // 60} minutes "
            f"(this is a hard stop: the guest ignores shutdown requests, ~100 s)")


@trigger("*/5 * * * *", note="windows: stop an agent-started Windows VM that nobody has used for HANDS_WINDOWS_IDLE_S")
def windows_idle_stop(ctx):
    return tick(ctx.state)
