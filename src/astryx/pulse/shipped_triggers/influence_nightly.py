"""The shipped INFLUENCE NIGHTLY: keeps the influence graph (who relies on whom: influence_edge, influence_value)
computed, so the floor's influence view, the network map and `who_should_i_ask` have something to read.

WHY (owner 11-15: "influence graph is also not showing on floor … make sure it doesn't happen with people who clone
astryx"). src/astryx/influence/shell.py `compute` is the nightly job, and nothing scheduled it: a fresh org's influence
tables stayed empty for good and the floor drew nothing, with no error anywhere.

WHAT: hourly. When the newest compute is older than DUE_H and no run is in flight (its pid alive, or inside its
RUN_MAX_S bound), launch `shell.py compute` detached for the pulse's org (its own session, so the pulse's 30 s check
cap never holds it; killed by `timeout` at RUN_MAX_S), logging to <estate>/var/runners/influence.log. A run that ended
and moved nothing FAILED: the next launch waits DUE_H doubled per failure in a row (medic 12299: a compute that always
fails must not relaunch a heavy job hourly), and the agent hears of it at most every RENAG_S, until a compute lands.
A graph older than STALE_H: a message, re-nagged every RENAG_S and re-armed by a fresh compute. The estate is the pulse's org (the checkout on one org, its HOME in a cog of several),
handed to the job as ASTRYX_HOME.

Install (init.sh's influence node and devtools/cog_add_org.py do, from astryx.pulse.shipped_triggers.shims):
  from astryx.pulse.shipped_triggers.influence_nightly import influence_nightly  # noqa: F401
"""
from __future__ import annotations
# imported as a module only (a trigger shim imports it), never run by path: no sys.path preamble and no import inside a
# top-level conditional (org_backup.py says why)
from astryx.paths import repo_root
from astryx import orgs, paths

import os
import subprocess
import sys
import time
from pathlib import Path

from astryx import trigger

REPO = repo_root(__file__)
DUE_H, STALE_H = 20, 36
RUN_MAX_S, RENAG_S = 60 * 60, 12 * 3600
RUN_GRACE_S = RUN_MAX_S + 10 * 60          # a run is in flight until its timeout has surely fired (pid unknown)


def _estate() -> Path:
    return paths.home() if orgs.multi() else REPO


def _launch(estate: Path) -> int:
    logd = estate / "var" / "runners"
    logd.mkdir(parents=True, exist_ok=True)
    with open(logd / "influence.log", "ab") as log:      # the child keeps its own copy; the pulse leaks no handle
        log.write(f"\n--- launch {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ---\n".encode())
        log.flush()
        p = subprocess.Popen(["timeout", str(RUN_MAX_S), sys.executable, str(REPO / "src" / "astryx" / "influence" / "shell.py"), "compute"],
                             cwd=REPO, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                             env={**os.environ, "ASTRYX_HOME": str(estate)}, start_new_session=True)
    return p.pid


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def decide(now: float, at: float, st: dict, alive: bool = False) -> tuple[str, str | None]:
    """PURE. ('launch' | 'wait', 'fail' | 'stale' | None) from the newest compute's time `at` (0: never), the state and
    whether the last launch's process is still running. A run is in flight while `alive`, else until RUN_GRACE_S. A run
    that ended without writing is a failure: counted once (st['fails'] is the caller's to bump on 'fail'), and the next
    launch waits DUE_H x 2^fails. Told at most every RENAG_S."""
    started = float(st.get("started") or 0)
    in_flight = bool(started) and (alive or now - started < RUN_GRACE_S)
    fails = int(st.get("fails") or 0)
    if started and not in_flight and at < started and not st.get("counted"):
        say = "fail" if now - float(st.get("told") or 0) > RENAG_S else None
        return "wait", say or "count"
    wait_h = DUE_H * 2 ** fails
    last_try = max(at, started if fails else 0)
    act = "launch" if not in_flight and now - last_try > wait_h * 3600 else "wait"
    if at and now - at > STALE_H * 3600 and now - float(st.get("nagged") or 0) > RENAG_S and not fails:
        return act, "stale"
    return act, None


@trigger("23 * * * *",
         note="influence nightly: computes the influence graph (influence/shell.py compute) when the newest is 20 h "
              "old, so the floor's influence view stays current; says so when a run fails or the graph is 36 h stale.")
def influence_nightly(ctx):
    now = time.time()
    rows = ctx.sql("SELECT extract(epoch FROM max(computed_at))::float AS at FROM influence_edge WHERE scope = 'local'")
    at = float((rows[0] or {}).get("at") or 0) if rows else 0.0
    st = ctx.state
    if at and at >= float(st.get("started") or 0) and st.get("fails"):
        st["fails"], st["told"] = 0, 0                     # a compute landed: the failures are over
    act, say = decide(now, at, st, _alive(st.get("pid")))
    if say in ("fail", "count"):
        st["fails"], st["counted"] = int(st.get("fails") or 0) + 1, True
    if act == "launch":
        st["pid"], st["started"], st["counted"] = _launch(_estate()), now, False
    if at and now - at <= STALE_H * 3600:
        st["nagged"] = 0
    if say == "fail":
        st["told"] = now
        log = _estate() / "var" / "runners" / "influence.log"
        tail = log.read_text(errors="replace")[-600:] if log.exists() else "(no log)"
        return (f"influence compute wrote nothing ({st['fails']} failed run(s) in a row; the next try waits "
                f"{DUE_H * 2 ** st['fails']} h). Log tail:\n{tail}")
    if say == "stale":
        st["nagged"] = now
        return f"the influence graph is {int((now - at) / 3600)} h old: the floor's influence view is stale."
    return None
