#!/usr/bin/env python3
"""Oracle: the shipped influence nightly (src/astryx/pulse/shipped_triggers/influence_nightly.py) keeps the influence
graph computed on every org, so a fresh clone's floor draws it (owner 11-15).
  I1 DUE: never computed, or the newest compute older than DUE_H, launches; a fresh one does not
  I2 ONE AT A TIME: a run in flight (inside RUN_GRACE_S) is not launched again
  I3 FAILED: a run past RUN_GRACE_S that moved nothing is said once, and a new run may then start
  I4 STALE: a graph older than STALE_H is said, re-nagged only after RENAG_S
  I5 SHIPPED: the shim is the one source's text and imports the module; init.sh installs it (node, reconcile list,
     reinstall list); a cog org gets it (cog_add_org.COG_SHIMS); the module is a trigger with one name
Exit 0 · 1."""
import importlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))
fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {str(detail)[:300]}"))
    if not ok:
        fails.append(name)


N = importlib.import_module("astryx.pulse.shipped_triggers.influence_nightly")
H = 3600.0
now = 1_000_000_000.0
d = N.decide
arm("I1 never computed: launch, nothing said", d(now, 0, {}) == ("launch", None), d(now, 0, {}))
arm("I1 newest older than DUE_H: launch", d(now, now - (N.DUE_H + 1) * H, {})[0] == "launch")
arm("I1 a fresh graph: wait", d(now, now - H, {}) == ("wait", None))
arm("I2 a run in flight: not launched again", d(now, 0, {"started": now - 60})[0] == "wait")
arm("I2 a 45-minute run, nothing written yet: no failure, no launch (medic 12299)", d(now, 0, {"started": now - 45 * 60}) == ("wait", None))
arm("I2 the grace outlasts the run's own timeout", N.RUN_GRACE_S > N.RUN_MAX_S)
arm("I2 its pid alive past the grace: still in flight", d(now, 0, {"started": now - N.RUN_GRACE_S - 60}, alive=True) == ("wait", None))
arm("I2 a recycled pid long past the timeout is not a run in flight (medic 12301)", d(now, 0, {"started": now - N.RUN_MAX_S - N.RUN_GRACE_S - 60}, alive=True)[1] == "fail")
arm("I3 a run that ended and moved nothing: a failure, said", d(now, 0, {"started": now - N.RUN_GRACE_S - 1}) == ("wait", "fail"))
arm("I4 stale past STALE_H: said", d(now, now - (N.STALE_H + 1) * H, {"started": now - 60})[1] == "stale")
arm("I4 …re-nagged only after RENAG_S", d(now, now - (N.STALE_H + 1) * H, {"started": now - 60, "nagged": now - 60})[1] is None)
arm("I4 a run that wrote is not a failure", d(now, now - 60, {"started": now - N.RUN_GRACE_S - 1}) == ("wait", None))


# I3 THE LOOP (medic 12299): the trigger itself over simulated hours, every compute failing; then one landing
class Ctx:
    def __init__(self):
        self.state, self.at = {}, 0.0

    def sql(self, q, a=()):
        return [{"at": self.at}]


launches, said = [], []
N._launch = lambda estate: launches.append(N.time.time()) or 4242
N._alive = lambda pid: bool(launches) and N.time.time() - launches[-1] < 50 * 60   # each run lasts 50 minutes
N._estate = lambda: Path("/nonexistent")
clock = [now]
N.time.time = lambda: clock[0]
c = Ctx()
for hour in range(24 * 6):
    clock[0] = now + hour * H
    r = N.influence_nightly(c)
    if r:
        said.append((hour, r))
gaps = [round((b - a) / H) for a, b in zip(launches, launches[1:])]
arm("I3 always failing for six days: the relaunch gap doubles (2x, 4x DUE_H, to the next hourly tick), never hourly", len(gaps) >= 2 and all(w <= g <= w + 2 for g, w in zip(gaps, [N.DUE_H * 2, N.DUE_H * 4, N.DUE_H * 8])) and len(launches) <= 4, (gaps, len(launches)))
arm("I3 …and the agent hears of it at most every RENAG_S", all(b[0] - a[0] >= N.RENAG_S / H for a, b in zip(said, said[1:])) and 1 <= len(said) <= len(launches), [h for h, _ in said])
c.at = clock[0] + 10
clock[0] += H
N.influence_nightly(c)
arm("I3 a compute that lands clears the failures", not c.state.get("fails"), c.state)

S = importlib.import_module("astryx.pulse.shipped_triggers.shims")
arm("I5 the shim imports the module, and registers one name",
    "from astryx.pulse.shipped_triggers.influence_nightly import influence_nightly" in S.SHIMS["influence_nightly"]
    and S.NAMES["influence_nightly"] == ("influence_nightly",))
init = (REPO / "init.sh").read_text()
arm("I5 init.sh: its node writes the shim from the one source",
    re.search(r"_act_influence\(\) \{[^}]*shims write influence_nightly triggers/seed", init) is not None)
arm("I5 init.sh: the node is in the reconcile DAG and the reinstall list",
    '"influence|interior"' in init and '"influence_nightly|influence"' in init)
cog = (REPO / "devtools" / "cog_add_org.py").read_text()
arm("I5 a cog org gets it", re.search(r'COG_SHIMS = \([^)]*"influence_nightly"', cog) is not None)
arm("I5 the module's trigger is hourly and carries a note", callable(getattr(N, "influence_nightly", None)))

print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: the influence graph is computed on every org")
sys.exit(1 if fails else 0)
