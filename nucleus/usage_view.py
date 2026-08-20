#!/home/umair/astryx/venv/bin/python
"""The READ side of the usage panel: everything the observatory and tokenwatch need,
and NOTHING that opens the credential. Goal #2470.

THIS MODULE EXISTS BECAUSE OF BC-2 CLAUSE (2). The build-confirm is not "observatory
has no credential read" — it is that exactly ONE module estate-wide reads the credential
and that module is not reachable in the observatory's import graph. If the API imported
`usage_refresh` just to call a cache reader, the credential reader would be in the graph
and the assert would go red for a true reason. So the split is load-bearing, not tidiness:

    usage_refresh.py   opens ~/.claude/.credentials.json   NOT imported by observatory
    usage_view.py      opens var/ only                     imported by observatory

Everything here is derived from `var/`. The two files it reads are written by the
refresher and mean different things:

    usage_cache.json   the last SUCCESSFUL extraction. Numbers live here and nowhere
                       else, and it is written ONLY on a successful 200 + extraction.
    usage_status.json  what the refresher saw on its LAST RUN, success or not. Carries
                       no numbers, ever. It exists so this module can tell "no cache
                       because nobody is configured" from "no cache because the timer
                       never ran" WITHOUT opening the credential to find out.

Keeping numbers out of the status file is what lets the two coexist without the status
file quietly becoming a second, undated source of gauges.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "var" / "usage_cache.json"
STATUS = REPO / "var" / "usage_status.json"
REFRESH_INTERVAL_S = 300
STALE_AFTER_S = 3 * REFRESH_INTERVAL_S

# The states the panel can be in. Five from the design plus SHAPE_CHANGED (a3's sixth).
# NOT_CONFIGURED is the MODAL state across the population this ships to — most installs
# will never have run `claude` on the box the observatory serves from — so it is a normal
# operating state with a designed rendering, not an error.
FRESH, STALE, SHAPE_CHANGED = "fresh", "stale", "shape_changed"
NOT_CONFIGURED, UNREADABLE, UNPARSEABLE = "not_configured", "unreadable", "unparseable"
RENDERABLE = (FRESH, SHAPE_CHANGED)     # the only states whose numbers may be drawn


def _load(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def read_status() -> dict:
    s = _load(STATUS)
    return s if isinstance(s, dict) else {}


def read_cache() -> dict:
    """The panel's whole view of the world.

    THE PANEL NEVER RENDERS A NUMBER IT CANNOT DATE. Enforced here rather than in the
    template: any state outside RENDERABLE returns data=None, so a caller cannot draw a
    gauge it has no timestamp for even by accident.

    Freshness is CLOCK - fetched_at, never "did our last fetch fail". A dead, masked or
    never-enabled refresher emits no event at all; a stale 40% is worse than an empty
    dial because it is good news about the exact resource whose exhaustion this warns of.
    """
    st = read_status()
    c = _load(CACHE)

    if not isinstance(c, dict) or not c.get("fetched_at"):
        # No datable numbers exist. Report WHY from the refresher's own last run, which
        # is the only party placed to know, and fall back to a bare not-configured only
        # when even the status file is missing (the timer has never run).
        state = st.get("state") or NOT_CONFIGURED
        if state in (FRESH, SHAPE_CHANGED, STALE):
            state = STALE          # it claims success but left no datable cache
        return {"state": state, "data": None, "fetched_at": None, "age_s": None,
                "checked_at": st.get("checked_at"), "hint": st.get("hint"),
                "renderable": False}

    try:
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(c["fetched_at"])).total_seconds()
    except Exception:
        return {"state": UNPARSEABLE, "data": None, "fetched_at": None, "age_s": None,
                "renderable": False}

    state = c.get("state") or FRESH
    if state == FRESH and age > STALE_AFTER_S:
        state = STALE
    # A credential that has since gone away or been rejected must not leave a FRESH
    # reading standing just because the file on disk is young.
    if st.get("state") in (NOT_CONFIGURED, UNREADABLE, UNPARSEABLE):
        state = st["state"]
    elif st.get("state") == STALE and state == FRESH:
        state = STALE

    renderable = state in RENDERABLE
    return {
        "state": state,
        "renderable": renderable,
        "fetched_at": c["fetched_at"],
        "age_s": round(age, 1),
        "stale_after_s": STALE_AFTER_S,
        "refresh_interval_s": REFRESH_INTERVAL_S,
        "checked_at": st.get("checked_at"),
        "hint": st.get("hint"),
        "baseline_source": c.get("baseline_source"),
        "missing_structural_keys": c.get("missing_structural_keys") or [],
        # numbers ONLY when the state permits drawing them
        "data": c.get("data") if renderable else None,
    }


def authoritative_ceiling() -> dict | None:
    """What tokenwatch repoints its CEILING to when the endpoint is live.

    Returns None whenever the number cannot be dated, which is what keeps the inferred
    P90 ceiling authoritative in exactly the states where the authoritative instrument
    is blind. REPOINT, NOT DELETE: the caller keeps its own segmentation and swaps only
    the ceiling, so a NOT-CONFIGURED install behaves exactly as it did before this plan.
    """
    c = read_cache()
    if not c.get("renderable") or not c.get("data"):
        return None
    d = c["data"]
    if d.get("five_hour_utilization") is None:
        return None
    return {"five_hour_utilization": d["five_hour_utilization"],
            "five_hour_resets_at": d.get("five_hour_resets_at"),
            "seven_day_utilization": d.get("seven_day_utilization"),
            "fetched_at": c["fetched_at"], "age_s": c["age_s"]}


if __name__ == "__main__":
    print(json.dumps(read_cache(), indent=1))
