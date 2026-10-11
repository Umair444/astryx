#!/usr/bin/env python3
"""Oracle: Hands' per-agent STEP and WALL-TIME caps (plan-7862, seed's binding item #38260, built per #44137).

    venv/bin/python tests/test_hands_caps.py        (also run by nucleus/check.sh; no desktop needed)

  C1 STEP: N charges pass, the (N+1)th refuses naming the STEP cap, and a refused charge is never counted
  C2 a multi-step charge (a `do` script) that would cross the cap is refused WHOLE, not run up to it
  C3 WALL: inside the wall cap a charge passes; past it, it refuses naming the WALL-TIME cap
  C4 IDLE: after a gap longer than the idle window the agent gets a fresh session (a paused agent is back), while a
     loop that never idles stays capped (control: a gap just under the window does NOT reset)
  C5 PER AGENT: one agent at its cap doesn't touch another agent's hands (a pool desk is shared; keying by desktop
     would stop the other agent)
  C6 an unreadable count fails CLOSED (refuses), never reads as a fresh session; caps-reset clears it
  C7 ATOMIC: 20 processes race one charge each against a cap of 10: exactly 10 pass
  C8 the caps store is never listed as a desktop (status() shows desktops only)
  C9 the hands server charges BEFORE it touches a desktop (a capped look/act never reaches one), charges a `do` its
     steps up front, and doesn't charge `done`
"""
import json
import multiprocessing as mp
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE = tempfile.mkdtemp(prefix="hands-caps-oracle-")
os.environ["ASTRYX_HANDS_STATE"] = STATE                  # the axis, set explicitly, before the import
os.environ["HANDS_STEP_CAP"] = "3"
os.environ["HANDS_WALL_CAP_S"] = "60"
os.environ["HANDS_CAP_IDLE_S"] = "600"
sys.path.insert(0, str(REPO))
import importlib.util  # noqa: E402
_s = importlib.util.spec_from_file_location("hands_desktop", os.environ.get("HANDS_DESKTOP_SRC")
                                            or REPO / "nucleus/hands_desktop.py")
hd = importlib.util.module_from_spec(_s)
sys.modules["nucleus.hands_desktop"] = hd
_s.loader.exec_module(hd)
import nucleus  # noqa: E402
nucleus.hands_desktop = hd                                  # the server imports THIS module (a mutant, under the probe)

fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


def refused(agent, n=1, now=None):
    try:
        hd.charge(agent, n, now=now)
        return None
    except hd.Capped as e:
        return str(e)


T0 = 1_000_000.0
# ── C1 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
for i in range(3):
    want(f"C1 charge {i + 1} of 3 passes", refused("zz-a", now=T0 + i) is None)
r = refused("zz-a", now=T0 + 3)
want("C1 the 4th refuses, naming the STEP cap", r is not None and "STEP cap" in r, str(r))
want("C1 the refused charge wasn't counted (still 3)", (hd.session("zz-a") or {}).get("steps") == 3,
     str(hd.session("zz-a")))
# ── C2 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
hd.caps_reset("zz-b")
refused("zz-b", 2, now=T0)
r = refused("zz-b", 2, now=T0 + 1)
want("C2 a 2-step charge at 2 of 3 is refused WHOLE", r is not None and (hd.session("zz-b") or {}).get("steps") == 2,
     f"{r} {hd.session('zz-b')}")
want("C2 ...while a 1-step charge still fits", refused("zz-b", 1, now=T0 + 2) is None)
# ── C3 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
refused("zz-c", now=T0)
want("C3 inside the wall cap a charge passes", refused("zz-c", now=T0 + 59) is None)
r = refused("zz-c", now=T0 + 61)
want("C3 past it, it refuses naming the WALL-TIME cap", r is not None and "WALL-TIME" in r, str(r))
# ── C4 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
last = (hd.session("zz-a") or {}).get("last", T0 + 2)
want("C4 a gap just UNDER the idle window doesn't reset a capped agent (control)",
     refused("zz-a", now=last + 599) is not None)
want("C4 after a gap LONGER than the idle window the agent has a fresh session",
     refused("zz-a", now=last + 601) is None and (hd.session("zz-a") or {}).get("steps") == 1, str(hd.session("zz-a")))
# ── C5 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
for i in range(3):
    refused("zz-d", now=T0 + i)
want("C5 zz-d is at its cap", refused("zz-d", now=T0 + 3) is not None)
want("C5 ...and zz-e, on the same machine, is untouched", refused("zz-e", now=T0 + 3) is None)
# ── C6 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
(hd.CAPS_DIR / "zz-f.json").write_text("{not json")
r = refused("zz-f", now=T0)
want("C6 an unreadable count refuses (fails closed), never a fresh session", r is not None, str(r))
hd.caps_reset("zz-f")
want("C6 caps-reset clears it", refused("zz-f", now=T0) is None)
# ── C7 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
os.environ["HANDS_STEP_CAP"] = "10"


def _race(q):
    try:
        hd.charge("zz-race")
        q.put(1)
    except hd.Capped:
        q.put(0)


q = mp.get_context("fork").Queue()
ps = [mp.get_context("fork").Process(target=_race, args=(q,)) for _ in range(20)]
for p in ps:
    p.start()
for p in ps:
    p.join(30)
won = sum(q.get(timeout=5) for _ in ps)
want("C7 20 racing processes against a cap of 10: exactly 10 pass", won == 10, f"{won} passed")
os.environ["HANDS_STEP_CAP"] = "3"
# ── C8 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
names = [d.get("agent") for d in hd.status()]
want("C8 the caps store is never listed as a desktop", ".caps" not in names and not any(
     str(n).startswith(".") for n in names), str(names))
# ── C9 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def c9():
    """The server's wiring: it needs the MCP SDK (a committed-only tree under a bare python3 lacks it)."""
    global reached
    os.environ["ASTRYX_AGENT"] = "zz-srv"
    _v = importlib.util.spec_from_file_location("hands_server", os.environ.get("HANDS_SERVER_SRC")
                                                or REPO / "mcp/hands/server.py")
    srv = importlib.util.module_from_spec(_v)
    _v.loader.exec_module(srv)
    reached = []

    def fake_ready(screen):
        reached.append(screen)
        raise hd.HandsError("reached-desktop")

    srv._ready = fake_ready
    hd.caps_reset("zz-srv")
    out = srv.look("background")
    want("C9 an uncapped look reaches the desktop (positive control)", reached == ["background"] and
         "reached-desktop" in str(out), str(out))
    srv.act("click", "background", 1, 1)
    srv.act("click", "background", 1, 1)
    reached.clear()
    out = srv.look("background")
    want("C9 at the cap (3 calls made), look refuses CAPPED and never reaches a desktop",
         str(out[0]).startswith("CAPPED") and not reached, f"{out} reached={reached}")
    reached.clear()
    out = srv.act("click", "background", 1, 1)
    want("C9 ...and so does act", str(out[0]).startswith("CAPPED") and not reached, f"{out} reached={reached}")
    hd.caps_reset("zz-srv")
    reached.clear()
    out = srv.act("do", "background", text="key a; key b; key c; key d")
    want("C9 a 4-step `do` against a cap of 3 is refused UP FRONT, never reaching a desktop",
         str(out[0]).startswith("CAPPED") and not reached, f"{out} reached={reached}")
    want("C9 `done` isn't charged", str(srv.act("done", "background")[0]).startswith("released")
         and (hd.session("zz-srv") or {}).get("steps", 0) == 0, str(hd.session("zz-srv")))


try:
    import mcp.server.fastmcp  # noqa: F401
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False
    print("  UNVERIFIED C9 (the server's wiring): the MCP SDK isn't importable here (no venv); C1–C8 still ran")
if HAVE_MCP:
    c9()

if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
if not HAVE_MCP:
    print("NOT VERIFIED: C9 (no MCP SDK here; C1–C8 passed)")
    sys.exit(77)
print("PASS: hands caps (step, wall, idle reset, per agent, fail-closed, atomic, wired before any desktop)")
