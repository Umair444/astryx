"""The shipped INFLUENCE NIGHTLY: keeps the influence graph (who relies on whom: influence_edge, influence_value)
computed, so the floor's influence view, the network map and `who_should_i_ask` have something to read.

WHY (owner 11-15: "influence graph is also not showing on floor … make sure it doesn't happen with people who clone
astryx"). src/astryx/influence/shell.py `compute` is the nightly job, and nothing scheduled it: a fresh org's influence
tables stayed empty for good and the floor drew nothing, with no error anywhere.

WHAT: hourly. When the newest compute is older than DUE_H and no run is in flight, launch `shell.py compute` detached
for the pulse's org (its own session, so the pulse's 30 s check cap never holds it; bounded by RUN_MAX_S through
`timeout`), logging to <estate>/var/runners/influence.log. A run older than RUN_GRACE_S that moved nothing FAILED: one
message to the trigger's agent with the log tail. A graph older than STALE_H: a message, re-nagged every RENAG_S and
re-armed by a fresh compute. The estate is the pulse's org (the checkout on one org, its HOME in a cog of several),
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
RUN_GRACE_S, RUN_MAX_S, RENAG_S = 30 * 60, 60 * 60, 12 * 3600


def _estate() -> Path:
    return paths.home() if orgs.multi() else REPO


def _launch(estate: Path) -> None:
    logd = estate / "var" / "runners"
    logd.mkdir(parents=True, exist_ok=True)
    log = open(logd / "influence.log", "ab")
    log.write(f"\n--- launch {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ---\n".encode())
    subprocess.Popen(["timeout", str(RUN_MAX_S), sys.executable, str(REPO / "src" / "astryx" / "influence" / "shell.py"), "compute"],
                     cwd=REPO, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     env={**os.environ, "ASTRYX_HOME": str(estate)}, start_new_session=True)


def decide(now: float, at: float, st: dict) -> tuple[str, str | None]:
    """PURE. ('launch' | 'wait', message or None) from the newest compute's time `at` (0: never) and the state."""
    started = float(st.get("started") or 0)
    if started and now - started > RUN_GRACE_S and at < started and not st.get("told_fail"):
        return "wait", "fail"
    act = "launch" if now - at > DUE_H * 3600 and (not started or now - started > RUN_GRACE_S) else "wait"
    if at and now - at > STALE_H * 3600 and now - float(st.get("nagged") or 0) > RENAG_S:
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
    act, say = decide(now, at, st)
    if act == "launch":
        _launch(_estate())
        st["started"], st["told_fail"] = now, False
    if at and now - at <= STALE_H * 3600:
        st["nagged"] = 0
    if say == "fail":
        st["told_fail"] = True
        log = _estate() / "var" / "runners" / "influence.log"
        tail = log.read_text(errors="replace")[-600:] if log.exists() else "(no log)"
        return f"influence compute started {int((now - float(st['started'])) / 60)} min ago and wrote nothing. Log tail:\n{tail}"
    if say == "stale":
        st["nagged"] = now
        return f"the influence graph is {int((now - at) / 3600)} h old: the floor's influence view is stale."
    return None
