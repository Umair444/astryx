"""The shipped IDLE USAGE READING: reads a login's limits when no turn has (medic 12485).

WHY (11-16): the limits are read only at the end of a turn (hooks/step.py's usage_snapshot), so an idle org has no
reading. The 00:55 wake was held nine hours by an evening's 98%, because nothing read the morning's reset; and an idle
vault login has no reading at all, so its agents never feel their own limits. Nothing watched for the silence either.

WHAT: every 5 minutes. For each login (the org's own, credential NULL, and every vault login with a value), the newest
fresh reading and the newest attempt of any state, from usage_readings (turns ∪ usage_polls). A login is due when its
fresh reading is older than FRESH_S and its last attempt older than RETRY_S, so a failure waits RETRY_S and a busy day,
read by its turns, costs nothing here. The stalest due login is read, ONE per evaluation (snapshot(timeout=4)), so the
check's 30 s cap holds however many logins there are. Whatever comes back is a usage_polls row, failed states too: an
expired login or a dead endpoint is a row, never silence (login_expired_watch can key on them per credential).

LIVENESS: when no reading of any state, by either writer, has landed in SILENT_S, the agent hears it, again every
RENAG_S while it lasts; a landed reading re-arms it.

Install (init.sh's usageidle node and devtools/cog_add_org.py do, from astryx.pulse.shipped_triggers.shims):
  from astryx.pulse.shipped_triggers.usage_idle import usage_idle  # noqa: F401
"""
from __future__ import annotations
# imported as a module only (a trigger shim imports it), never run by path: no sys.path preamble and no import inside a
# top-level conditional (org_backup.py says why)
from astryx.paths import repo_root
from astryx import orgs, paths

import time
from datetime import datetime, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

from astryx import trigger
from astryx.core import usage_refresh, vault

REPO = repo_root(__file__)
FRESH_S, RETRY_S = 60 * 60, 15 * 60
SILENT_S, RENAG_S = 3 * 3600, 3 * 3600


def _estate() -> Path:
    return paths.home() if orgs.multi() else REPO


def due(now: float, seen: dict, logins: list) -> str | None | bool:
    """PURE. Which login to read now: its name, None for the org's own, or False for none. `seen` is
    {credential: (fresh_at, last_at)} in epoch seconds (0: never); `logins` the credentials there are. The stalest due
    one wins, a never-read one first."""
    late = [(seen.get(c, (0, 0))[0], c) for c in logins
            if now - seen.get(c, (0, 0))[0] > FRESH_S and now - seen.get(c, (0, 0))[1] > RETRY_S]
    return min(late, key=lambda x: x[0])[1] if late else False


@trigger("*/5 * * * *",
         note="idle usage reading: reads a login's limits (the org's own and each vault login's) when no turn has in an "
              "hour, so the energy of an idle org or login is never a stale number; says so when no reading has "
              "landed in 3 h.")
def usage_idle(ctx):
    now = time.time()
    rows = ctx.sql("SELECT credential, extract(epoch FROM max(fetched_at) FILTER (WHERE state = 'fresh'))::float AS fresh, "
                   "extract(epoch FROM max(fetched_at))::float AS last FROM usage_readings GROUP BY credential")
    seen = {r["credential"]: (r["fresh"] or 0.0, r["last"] or 0.0) for r in rows}
    tokens = {n: t for n, t in vault.logins(_estate()) if t}      # a login with no value is never read (as the org's)
    pick = due(now, seen, [None, *sorted(tokens)])
    if pick is not False:
        snap = usage_refresh.snapshot(timeout=4, token=tokens[pick], credential=pick) if pick \
            else usage_refresh.snapshot(timeout=4)
        snap = snap or {"fetched_at": datetime.now(timezone.utc).isoformat(), "state": "unavailable"}   # no host login
        ctx.sql("INSERT INTO usage_polls (state, snapshot) VALUES (%s, %s)", (snap["state"], Jsonb(snap)))
    # liveness reads the table again, never this evaluation's own belief that it wrote
    last = float((ctx.sql("SELECT extract(epoch FROM max(fetched_at))::float AS last FROM usage_readings") or [{}])[0].get("last") or 0)
    st = ctx.state
    if now - last <= SILENT_S:
        st["nagged"] = 0
        return None
    if now - float(st.get("nagged") or 0) <= RENAG_S:
        return None
    st["nagged"] = now
    since = f"in {int((now - last) / 3600)} h" if last else "ever"
    return (f"no usage reading has landed {since}: the [energy] line and the pulse's hold read a stale number or none. "
            f"usage_polls and turns carry the attempts; check the pulse's python checks and the usage endpoint.")
