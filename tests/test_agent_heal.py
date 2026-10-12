#!/usr/bin/env python3
"""test_agent_heal — the shipped actuator behind agent_dark (owner 10-12: restarts smooth and automatic). Hermetic: the
roster, the live bodies and spawn.sh are stand-ins, so no real tmux session is touched."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from nucleus.shipped_triggers import agent_heal as H  # noqa: E402

fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        fails += 1


class World:
    def __init__(self, want, live, fail=()):
        self.want, self.live, self.fail, self.spawned = list(want), set(live), set(fail), []

    def spawn(self, name):
        self.spawned.append(name)
        if name in self.fail:
            return False, "spawn: something broke"
        self.live.add(name)
        return True, f"{name} resident"

    def kw(self):
        return {"want": lambda: self.want, "have": lambda: set(self.live), "do": self.spawn}


w = World(["a", "b", "c"], {"a", "b", "c"})
st = {}
arm("a healthy org: nothing spawned, nothing said", H.tick(st, 0, **w.kw()) is None and w.spawned == [])

w = World(["a", "b", "c"], {"a", "c"})
msg = H.tick({}, 0, **w.kw())
arm("a dead body is respawned, and said", w.spawned == ["b"] and "respawned 1" in msg and "b" in msg, (w.spawned, msg))

w = World(["a", "b", "c"], {"a", "c"})
w.live.discard("b")
arm("a LIVE body is never spawned", (H.tick({}, 0, **w.kw()) or "") and "a" not in w.spawned and "c" not in w.spawned, w.spawned)

w = World([f"r{i}" for i in range(10)], set())
st = {}
H.tick(st, 0, **w.kw())
first = len(w.spawned)
H.tick(st, 60, **w.kw())
H.tick(st, 120, **w.kw())
arm(f"a cold boot fills in at most {H.HEAL_PER_TICK} a tick, and finishes over a few ticks",
    first == H.HEAL_PER_TICK and set(w.spawned) == set(w.want) and len(w.spawned) == 10, (first, w.spawned))

w = World(["x"], set(), fail={"x"})
st, said = {}, []
for i in range(6):
    said.append(H.tick(st, i * 60, **w.kw()))
arm(f"a crash loop stops after {H.CRASH_MAX} attempts in the window", w.spawned == ["x"] * H.CRASH_MAX, w.spawned)
arm("…and is reported once when it starts, not every tick", sum(1 for m in said if m and "CRASH LOOP" in m) == 1, said)
arm("each failed attempt names why", all("could NOT respawn: x (spawn: something broke)" in m for m in said[:H.CRASH_MAX]), said)
H.tick(st, H.CRASH_WINDOW_S + 400, **w.kw())
arm("after the window passes, it tries again", len(w.spawned) == H.CRASH_MAX + 1, w.spawned)

w = World(["a"], set())
arm("tmux can't answer → blind: nothing is spawned (never double-spawn)",
    H.tick({}, 0, want=lambda: ["a"], have=lambda: None, do=w.spawn) is None and w.spawned == [])

st = {"attempts": {"gone": [0.0]}}
w = World(["a"], {"a"})
H.tick(st, H.CRASH_WINDOW_S + 1, **w.kw())
arm("old attempts are forgotten (state stays small)", "gone" not in st["attempts"], st)

import subprocess  # noqa: E402
real = subprocess.run
subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "no server running on /tmp/tmux-1000/default\n")
try:
    arm("no tmux server at all (a cold boot) is the EMPTY set, so everything is healed", H.bodies() == set())
finally:
    subprocess.run = real

print("ALL PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
