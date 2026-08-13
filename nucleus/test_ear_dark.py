"""Oracle for GEMINI's ear_dark trigger.

The point of this file is the FAILING direction. A watcher that is merely quiet
proves nothing — silence is also what a broken check produces, and ear_dark's whole
job is to break the tie between "quiet family" and "broken ear". So every case here
that should fire is asserted to fire, with the reason it exists.

It lives in nucleus/, NOT beside the trigger: the pulse imports every triggers/*/*.py
as a trigger file, so a test parked there is discovered, executed on each reconcile,
and reported to its agent as a broken trigger. (Learned the loud way, 08-13.)

Run: venv/bin/python nucleus/test_ear_dark.py    (also wired into nucleus/check.sh)
"""
import json
import runpy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))            # astryx.py lives at the repo root

TRIGGER = REPO / "triggers" / "gemini" / "ear_dark.py"
if not TRIGGER.exists():
    # triggers/ is gitignored, so a fresh clone (CI) has no body to test. Skip LOUDLY
    # rather than pass — a green tick for a test that never ran is the lie this whole
    # file exists to prevent.
    print("SKIP: triggers/gemini/ear_dark.py not present (gitignored body, e.g. a CI "
          "clone). Nothing was verified here.")
    sys.exit(0)
runpy.run_path(str(TRIGGER), run_name="ear_dark_mod")
# run_path hands back a COPY of the namespace, so patching that dict would be a silent
# no-op and every case below would quietly test the live wacli instead. Patch the
# function's OWN globals — the namespace it actually resolves names in.
from astryx import _registry                                        # noqa: E402
ear_dark = next(t["fn"] for t in _registry if t["name"] == "ear_dark")
MOD = ear_dark.__globals__
# Capture the genuine helpers BEFORE any scenario stubs them. Grabbing these later
# hands back whichever stub ran last, and the filter cases below then assert against a
# constant instead of the real filter — they went green-then-red on exactly that.
PRISTINE = {k: MOD[k] for k in ("_route", "_store_latest_inbound",
                                "_wacli_running", "subprocess")}

NOW = datetime.now(timezone.utc)
CHAT = "120363429174873644@g.us"
fails = []


class Ctx:
    def __init__(self, wire_ts=None, state=None):
        self.state = state if state is not None else {}
        self._wire = wire_ts

    def sql(self, q, params=()):
        return [{"t": self._wire}]


def scenario(name, *, store, wire, state=None, route=(CHAT, ""), running=True,
             store_why="", status=None):
    """Drive the real function with a substituted world.

    status defaults to the honest reading of the other args: a reason string means the
    call did not complete (FLAKE), otherwise the reader vouches for its answer (OK).
    Pass it explicitly for DRIFT, or for a status this code has never heard of.
    """
    if status is None:
        status = MOD["FLAKE"] if store_why else MOD["OK"]
    MOD["_route"] = lambda: route
    MOD["_store_latest_inbound"] = lambda chat: (status, store, "MSGID1", store_why)
    MOD["_wacli_running"] = lambda: running
    ctx = Ctx(wire_ts=wire, state=dict(state or {}))
    fire = ear_dark(ctx)
    return fire, ctx.state


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


print("ear_dark oracle\n")

# --- the failing direction: it MUST fire ------------------------------------
print("must FIRE (a real drop is the thing my thread cannot show me):")

base = (NOW - timedelta(days=30)).isoformat()
fire, st = scenario("deaf", store=NOW, wire=NOW - timedelta(hours=6),
                    state={"baseline": base})
check("family spoke 6h ago, wire never got it -> FIRES",
      fire is not None and "DEAF" in fire, f"got {fire!r}")

fire, _ = scenario("never", store=NOW, wire=None, state={"baseline": base})
check("store has messages, wire has NONE ever -> FIRES",
      fire is not None and "DEAF" in fire, f"got {fire!r}")

fire, _ = scenario("route-off", store=NOW, wire=NOW,
                   route=(None, "my route exists but is DISABLED"))
check("my route disabled -> FIRES (deaf at the route)",
      fire is not None and "ROUTE" in fire, f"got {fire!r}")

fire, _ = scenario("wacli-down", store=None, wire=NOW, running=False,
                   store_why="No such container")
check("wacli-sync container down -> FIRES (deaf at the source)",
      fire is not None and "SOURCE" in fire, f"got {fire!r}")

# The detector's own blind spot, found 08-13 re-auditing this guard against the org's
# "a check cannot cover what it cannot OBSERVE" law. Proven RED first: before the fix
# every one of these returned the same value as a quiet family, so ear_dark filed its
# own blindness as health and would never have spoken again.
fire, _ = scenario("drift", store=None, wire=NOW, status=MOD["DRIFT"],
                   store_why="25 message(s) came back and NOT ONE carried a readable Timestamp")
check("wacli's shape drifted -> FIRES, is NOT filed as quiet",
      fire is not None and "CANNOT READ" in fire, f"got {fire!r}")

fire, _ = scenario("unknown-status", store=None, wire=NOW, status="something-new-upstream",
                   store_why="a status this code has never heard of")
check("an UNKNOWN reader status -> FIRES (detector unknown => WATCHED)",
      fire is not None and "CANNOT READ" in fire, f"got {fire!r}")

# --- the quiet direction: it MUST NOT fire ----------------------------------
print("\nmust STAY SILENT (a false alarm on my own family surface spends real credibility):")

fire, _ = scenario("quiet", store=NOW - timedelta(days=21), wire=NOW - timedelta(days=21),
                   state={"baseline": base})
check("three weeks of genuine quiet -> silent (the 08-12 case)", fire is None, f"got {fire!r}")

fire, _ = scenario("nobody", store=None, wire=NOW - timedelta(days=21),
                   state={"baseline": base})
check("nobody else has spoken at all -> silent", fire is None, f"got {fire!r}")

fire, _ = scenario("skew", store=NOW, wire=NOW - timedelta(minutes=20),
                   state={"baseline": base})
check("20 min sync/media lag inside grace -> silent", fire is None, f"got {fire!r}")

fire, st = scenario("cold", store=NOW, wire=NOW - timedelta(days=400), state={})
check("first tick on a fresh route baselines, does not indict history",
      fire is None and st.get("baseline"), f"got {fire!r}")

fire, _ = scenario("flake", store=None, wire=NOW, running=True,
                   store_why="context deadline exceeded")
check("wacli call flaked but container is UP -> silent (transient)",
      fire is None, f"got {fire!r}")

fire, _ = scenario("docker-mute", store=None, wire=NOW, running=None,
                   store_why="cannot connect to docker")
check("docker itself cannot answer -> silent, never a false alarm",
      fire is None, f"got {fire!r}")

# --- the standing-failure law ------------------------------------------------
print("\nguard-silence law (a receipt must not outlive the failure it guards):")

fire1, st1 = scenario("nag1", store=NOW, wire=NOW - timedelta(hours=6),
                      state={"baseline": base})
fire2, st2 = scenario("nag2", store=NOW, wire=NOW - timedelta(hours=6), state=st1)
check("second tick inside 12h -> suppressed", fire1 and fire2 is None, f"got {fire2!r}")

stale = dict(st1)
stale["warned"] = {"deaf": (NOW - timedelta(hours=13)).isoformat()}
fire3, _ = scenario("nag3", store=NOW, wire=NOW - timedelta(hours=6), state=stale)
check("still deaf after 12h -> RE-NAGS (does not dedup to silence)",
      fire3 is not None and "Re-nag" in fire3, f"got {fire3!r}")

recov = dict(st1)
fire4, st4 = scenario("recover", store=NOW, wire=NOW, state=recov)
check("ear comes back -> says so, and says READ THE THREAD",
      fire4 is not None and "BACK" in fire4 and "query_thread" in fire4, f"got {fire4!r}")
check("recovery clears the warned receipt",
      not (st4.get("warned") or {}).get("deaf"), f"got {st4!r}")

# --- the false alarms that would make it useless -----------------------------
print("\nthe three false alarms that would get this watcher (rightly) ignored:")

_real_store = PRISTINE["_store_latest_inbound"]      # the genuine filter, un-stubbed
_real_sub = PRISTINE["subprocess"]


def _fake_wacli(msgs):
    """Exercise the REAL filter, not a restatement of it: feed a wacli-shaped payload
    through the actual _store_latest_inbound by swapping only the subprocess call."""
    payload = json.dumps({"success": True, "data": {"messages": msgs}})

    class R:
        returncode = 0
        stdout = payload
        stderr = ""

    MOD["subprocess"] = type("S", (), {"run": staticmethod(lambda *a, **k: R())})
    try:
        return _real_store(CHAT)
    finally:
        MOD["subprocess"] = _real_sub


OK, DRIFT = MOD["OK"], MOD["DRIFT"]

owner_only = [{"FromMe": True, "Text": "assalam o alaikum", "Timestamp": "2026-08-13T10:00:00Z",
               "MsgID": "A"}]
st, dt, _, _ = _fake_wacli(owner_only)
check("Umair typing in his own family group -> not counted (bridge drops FromMe)",
      (st, dt) == (OK, None), f"got {st!r} {dt!r}")

reaction = [{"FromMe": False, "ReactionToID": "X", "ReactionEmoji": "👍", "Text": "",
             "Timestamp": "2026-08-13T10:00:00Z", "MsgID": "B"}]
st, dt, _, _ = _fake_wacli(reaction)
check("a thumbs-up reaction -> not counted", (st, dt) == (OK, None), f"got {st!r} {dt!r}")

system_evt = [{"FromMe": False, "Text": "", "MediaType": "",
               "Timestamp": "2026-08-13T10:00:00Z", "MsgID": "C"}]
st, dt, _, _ = _fake_wacli(system_evt)
check("a group system event (join/subject) -> not counted",
      (st, dt) == (OK, None), f"got {st!r} {dt!r}")

real_msg = [{"FromMe": False, "Text": "beta kahan ho", "Timestamp": "2026-08-13T10:00:00Z",
             "MsgID": "D"}]
st, dt, mid, _ = _fake_wacli(real_msg)
check("an actual message from Mama -> COUNTED",
      st == OK and dt is not None and mid == "D", f"got {st!r} {dt!r}")

media_only = [{"FromMe": False, "Text": "", "MediaType": "image",
               "Timestamp": "2026-08-13T10:00:00Z", "MsgID": "E"}]
st, dt, _, _ = _fake_wacli(media_only)
check("a photo with no caption -> COUNTED", st == OK and dt is not None, f"got {st!r} {dt!r}")

# --- the reader must know when it can no longer read -------------------------
print("\nshape drift must NOT masquerade as quiet (each of these was silent before 08-13):")

st, _, _, _ = _fake_wacli([{"from_me": False, "text": "beta kahan ho",
                            "timestamp": "2026-08-13T10:00:00Z", "id": "D"}])
check("upstream renames every field to snake_case -> DRIFT", st == DRIFT, f"got {st!r}")

st, _, _, _ = _fake_wacli([{"FromMe": False, "Text": "beta kahan ho",
                            "SentAt": "2026-08-13T10:00:00Z", "MsgID": "D"}])
check("only the timestamp key is renamed -> DRIFT", st == DRIFT, f"got {st!r}")

st, _, _, _ = _fake_wacli([{"FromMe": False, "Text": "beta kahan ho",
                            "Timestamp": 1786000000, "MsgID": "D"}])
check("timestamp becomes an epoch int -> DRIFT", st == DRIFT, f"got {st!r}")

st, _, _, _ = _fake_wacli([])
check("an empty window is a real answer, NOT drift", st == OK, f"got {st!r}")

st, _, _, _ = _fake_wacli(owner_only + reaction + system_evt)
check("a window of only-filtered-out messages is quiet, NOT drift",
      st == OK, f"got {st!r}")

# --- and the fixtures above must match what wacli ACTUALLY emits -------------
# Everything above this line is conformance-to-SELF: I hand-wrote those fixtures from my
# own reading of wacli, so the parser and the test agree with each other and would go on
# agreeing after upstream changed. This case is the only one that pins either to reality.
print("\nlive shape (the fixtures are my reading of wacli; this asks wacli):")

_probe = PRISTINE["subprocess"].run
try:
    _r = _probe(MOD["WACLI"] + ["messages", "list", "--chat", CHAT, "--limit", "3", "--json"],
                capture_output=True, text=True, timeout=25)
    _live = json.loads(_r.stdout) if _r.returncode == 0 else None
except Exception:
    _live = None

if _live is None:
    print("  SKIP  wacli unreachable here — the live shape was NOT verified this run")
else:
    _msgs = _live.get("data") if isinstance(_live, dict) else _live
    if isinstance(_msgs, dict):
        _msgs = _msgs.get("messages")
    check("wacli's real reply still parses as a message list",
          isinstance(_msgs, list), f"got {type(_msgs).__name__}")
    if isinstance(_msgs, list) and _msgs:
        _keys = set(_msgs[0])
        # Only the fields the filter actually branches on. MediaType/ReactionToID are
        # absent on a plain text message, so their absence here proves nothing.
        for _f in ("Timestamp", "FromMe", "MsgID", "Text"):
            check(f"live message still carries `{_f}`", _f in _keys,
                  f"keys are {sorted(_keys)[:12]}")
        _st, _, _, _detail = PRISTINE["_store_latest_inbound"](CHAT)
        check("the REAL reader understands the REAL store today",
              _st in (OK,), f"got {_st!r}: {_detail}")
    elif isinstance(_msgs, list):
        print("  SKIP  live store returned an empty window — nothing to shape-check")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all green"))
sys.exit(1 if fails else 0)
