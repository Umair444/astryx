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

# ── arm two: a DEAF body (alive, no ear, rows pending, pane idle) ─────────────────────────────────────────────────
# pane shapes measured on live residents 10-12 (text masked): idle = "✻ … done H:MM AM" above an empty prompt; a turn
# in flight shows a spinner and "esc to interrupt" in the footer
IDLE = ("  some output\n✻ Cogitated for 15s · done 9:41 AM\n\n ☂ status\n" + "─" * 80 + "\n❯\xa0\n" + "─" * 80
        + "\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n")
BUSY = ("  some output\n· Transfiguring… (55s · ↓ 3.9k tokens)\n" + "─" * 80 + "\n❯ \n" + "─" * 80
        + "\n  ⏵⏵ bypass permissions on (shift+tab to cycle) · esc to interrupt\n")
arm("idle(): a finished turn above an empty prompt is IDLE", H.idle(IDLE))
arm("idle(): a turn in flight is NOT idle", not H.idle(BUSY))
arm("idle(): a turn in flight under the LAST turn's \"done\" line is NOT idle (esc to interrupt decides)",
    not H.idle("✻ Cogitated for 15s · done 9:41 AM\n> the next message\n" + BUSY))
arm("idle(): text typed at the prompt is NOT idle", not H.idle(IDLE.replace("❯\xa0", "❯ half a sentence")))
arm("idle(): a boot dialog is NOT idle", not H.idle(IDLE.replace("❯\xa0", "❯ 1. Yes, I accept")))
arm("idle(): an empty prompt with no finished turn above it is NOT idle", not H.idle(IDLE.replace("done 9:41", "x")))
arm("idle(): an empty / unreadable pane is NOT idle", not H.idle(""))


class Deaf:
    """One resident 'x' (plus 'y', healthy). log records the order of acts."""
    def __init__(self, ears=None, pending=None, text=IDLE, age=3600, cut_ok=True, spawn_ok=True):
        self.ears = {"y": 1} if ears is None else ears
        self.pending = {"x": (6, 2400)} if pending is None else pending
        self.text, self.age, self.cut_ok, self.spawn_ok, self.log = text, age, cut_ok, spawn_ok, []

    def look(self, name):
        return None if self.text is None else (self.text, self.age)

    def keep(self, name, text, now):
        self.log.append(("save", name, text))
        return Path(f"/fake/homes/{name}/deaf.pane")

    def cut(self, name):
        self.log.append(("kill", name))
        return self.cut_ok

    def do(self, name):
        self.log.append(("spawn", name))
        return (True, f"{name} resident (boot=resumed)") if self.spawn_ok else (False, "spawn: broke")

    def kw(self):
        return {"want": lambda: ["x", "y"], "have": lambda: {"x", "y"}, "do": self.do,
                "deaf_kw": {"listen": lambda: dict(self.ears), "late": lambda: dict(self.pending), "look": self.look,
                            "cut": self.cut, "keep": self.keep}}


acts = lambda d: [a[0] for a in d.log]  # noqa: E731

d = Deaf(ears={"x": 1, "y": 1})
arm("a LIVE ear, rows pending → silent, nothing cut", H.tick({}, 0, **d.kw()) is None and d.log == [], d.log)
d = Deaf(pending={})
arm("a dead ear with NOTHING pending (idle, not deaf) → silent", H.tick({}, 0, **d.kw()) is None and d.log == [], d.log)
d = Deaf()
st = {}
m = H.tick(st, 0, **d.kw()) or ""
arm("deaf + pending + idle → pane SAVED first, then kill, then spawn", acts(d) == ["save", "kill", "spawn"]
    and d.log[0][2] == IDLE, d.log)
arm("…and said, with the pending count and where the pane went", "restarted 1 DEAF" in m and "6 pending, oldest 40 min"
    in m and "/fake/homes/x/deaf.pane" in m, m)
d.ears, d.pending = {"x": 1, "y": 1}, {}
m = H.tick(st, 60, **d.kw()) or ""
arm("verified next tick: one ear, the aged pending drained", "x after restart: 1 ear(s), aged pending 6 -> 0" in m
    and "NOT healed" not in m and acts(d) == ["save", "kill", "spawn"], m)

d = Deaf(text=BUSY)
st, said = {}, []
for i in range(3):
    said.append(H.tick(st, i * 60, **d.kw()))
arm("a BUSY pane is NEVER killed (seed's required arm)", d.log == [], d.log)
arm("…it's reported once, with the evidence, not every tick", sum(1 for m in said if m and "mid-turn, NOT killed" in m)
    == 1 and "x (6 pending, oldest 40 min)" in (said[0] or ""), said)
d.text = IDLE
H.tick(st, 240, **d.kw())
arm("…and re-checked every tick: once its turn finishes, it's restarted", acts(d) == ["save", "kill", "spawn"], d.log)

d = Deaf(age=60)
arm(f"a session younger than {H.DEAF_GRACE_S}s (still bringing its ear up) is left alone",
    H.tick({}, 0, **d.kw()) is None and d.log == [], d.log)
d = Deaf(text=None)
arm("no body at all is arm one's case: arm two cuts nothing", H.tick({}, 0, **d.kw()) is None and d.log == [], d.log)
for blind in ("listen", "late"):
    d = Deaf()
    kw = d.kw()
    kw["deaf_kw"][blind] = lambda: None
    arm(f"{blind}() can't answer → blind: nothing is cut", H.tick({}, 0, **kw) is None and d.log == [], d.log)

d = Deaf()
st, said = {}, []
for i in range(6):                                     # 6 × 301 s stays inside CRASH_WINDOW_S
    said.append(H.tick(st, i * (H.DEAF_GRACE_S + 1), **d.kw()))
arm(f"deaf on EVERY start: restarted {H.CRASH_MAX} times, then left alone", acts(d).count("kill") == H.CRASH_MAX, d.log)
arm("…each restart is followed by a NOT-healed verdict", sum(1 for m in said if m and "NOT healed" in m)
    == H.CRASH_MAX, said)
arm("…and the crash loop is reported once", sum(1 for m in said if m and "CRASH LOOP" in m and "x" in m) == 1, said)
d = Deaf()
st = {}
H.tick(st, 0, **d.kw())
H.tick(st, 60, **d.kw())
arm(f"within {H.DEAF_GRACE_S}s of its restart it is not cut again (its ear is still booting)",
    acts(d).count("kill") == 1, d.log)

d = Deaf(cut_ok=False)
m = H.tick({}, 0, **d.kw()) or ""
arm("kill-session fails → no spawn, said, the pane still saved", acts(d) == ["save", "kill"] and "kill-session failed"
    in m and "deaf.pane" in m, (d.log, m))
d = Deaf(spawn_ok=False)
m = H.tick({}, 0, **d.kw()) or ""
arm("spawn fails after the kill → said loudly", "killed, then spawn failed: spawn: broke" in m, m)

w, d = World([f"r{i}" for i in range(H.HEAL_PER_TICK)] + ["x"], {"x"}), Deaf()
kw = d.kw()
kw.update(w.kw())
kw["want"] = lambda: w.want
H.tick({}, 0, **kw)
arm("one budget a tick: arm one's spawns use it up before arm two cuts", "kill" not in acts(d)
    and len(w.spawned) == H.HEAL_PER_TICK, (w.spawned, d.log))

import os  # noqa: E402
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as proc:
    def proc_pid(pid, argv, env):
        Path(proc, pid).mkdir()
        Path(proc, pid, "cmdline").write_bytes(b"\0".join(argv) + b"\0")
        Path(proc, pid, "environ").write_bytes(b"\0".join(env) + b"\0")
    proc_pid("11", [b"node", b"/r/channel/server.mjs"], [b"HOME=/h", b"ASTRYX_AGENT=forge"])
    proc_pid("12", [b"node", b"/r/channel/server.mjs", b"seed"], [b"ASTRYX_AGENT=steward"])   # argv says seed
    proc_pid("13", [b"bash", b"-c", b"ASTRYX_AGENT=seed node channel/server.mjs.bak"], [b"ASTRYX_AGENT=seed"])
    proc_pid("14", [b"node", b"/r/channel/server.mjs"], [b"ASTRYX_AGENT=forge"])
    Path(proc, "self").mkdir()
    got = H.ears(proc)
arm("ears(): counted by ENVIRON identity; 'seed' in another ear's argv, or a non-ear naming seed, is no seed ear",
    got == {"forge": 2, "steward": 1}, got)

print("ALL PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
