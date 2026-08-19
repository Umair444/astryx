"""Oracle for GEMINI's mouth_dark trigger.

The point of this file is the FAILING direction. mouth_dark's whole job is to break a
tie that nothing else in the org can break — between "my family got my reply" and "my
reply vanished and the row says delivered" — and both of those look like a quiet week
from inside my thread. A watcher that is merely quiet proves nothing, so every case
here that should fire is asserted to fire, with the reason it exists.

It lives in nucleus/, NOT beside the trigger: the pulse imports every triggers/*/*.py
as a trigger file, so a test parked there is discovered, executed on each reconcile,
and reported to its agent as a broken trigger. (Learned the loud way, 08-13.)

NO JID IN THIS FILE, in any form — not whole, not split. A split literal passes the
privacy gate's regex and remains the value to anyone reading the file; satisfying the
checker is not satisfying the property. Stubbed cases take a synthetic name; the one
live probe derives the real chat at use from the gitignored config the trigger itself
reads, and skips loudly when that is absent.

Run: venv/bin/python nucleus/test_mouth_dark.py
"""
import json
import runpy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

TRIGGER = REPO / "triggers" / "gemini" / "mouth_dark.py"
if not TRIGGER.exists():
    # triggers/ is gitignored, so a fresh clone (CI) has no body to test. Skip LOUDLY
    # rather than pass — a green tick for a test that never ran is the lie this whole
    # file exists to prevent.
    print("SKIP: triggers/gemini/mouth_dark.py not present (gitignored body, e.g. a CI "
          "clone). Nothing was verified here.")
    sys.exit(77)                       # 77 = SKIP; check.sh counts it UNVERIFIED
runpy.run_path(str(TRIGGER), run_name="mouth_dark_mod")
from astryx import _registry                                        # noqa: E402

mouth_dark = next(t["fn"] for t in _registry if t["name"] == "mouth_dark")
MOD = mouth_dark.__globals__           # patch the function's OWN globals, not a copy
PRISTINE = {k: MOD[k] for k in ("_route", "_store_sent_ids", "_wacli_running",
                                "_parse", "subprocess")}

NOW = datetime.now(timezone.utc)
CHAT = "stub-chat-not-a-jid"
INSTALLED = MOD["INSTALLED"]
GRACE_MIN, RENAG_H, BLIND_H, LOOKBACK_D = (MOD["GRACE_MIN"], MOD["RENAG_H"],
                                           MOD["BLIND_H"], MOD["LOOKBACK_D"])

fails, skips = [], []


def skip(why):
    print(f"  SKIP  {why}")
    skips.append(why)


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


def row(rid, *, age_h=6, mid="ID-A", ok="true", rendered="salaam", no_receipt=False):
    return {"id": rid, "ts": NOW - timedelta(hours=age_h), "mid": mid, "ok": ok,
            "rendered": rendered, "no_receipt": no_receipt}


class Ctx:
    """Applies the trigger's OWN floor/ceiling params to the stub rows.

    The window is enforced in SQL, which a stub bypasses — so instead of pretending to
    test the WHERE clause, this applies the bounds the trigger actually passes and
    records them, and a case below asserts those bounds directly. What is verified is
    the boundary the trigger computes; the SQL that consumes it is not exercised here,
    and that limit is stated rather than papered over.
    """

    def __init__(self, rows=(), state=None):
        self.state = dict(state or {})
        self._rows = list(rows)
        self.params = None

    def sql(self, q, params=()):
        self.params = params
        floor, ceiling = params[2], params[3]
        return [r for r in self._rows if floor <= r["ts"] <= ceiling]


def scenario(*, rows=(), store_ids=frozenset({"ID-A"}), state=None, route=(CHAT, ""),
             running=True, status=None, detail=""):
    if status is None:
        status = MOD["FLAKE"] if detail else MOD["OK"]
    MOD["_route"] = lambda: route
    MOD["_store_sent_ids"] = lambda chat, since: (status, set(store_ids), detail)
    MOD["_wacli_running"] = lambda: running
    ctx = Ctx(rows=rows, state=state)
    return mouth_dark(ctx), ctx


print("mouth_dark oracle\n")

# --- MUST FIRE: the failures nothing else in the org can see -----------------
print("must FIRE:")

fire, _ = scenario(rows=[row(101, mid="ID-GONE")], store_ids={"ID-A"})
check("claimed id absent from WhatsApp's own store -> FIRES",
      fire and "NEVER GOT" in fire and "101" in fire, f"got {fire!r}")

fire, _ = scenario(rows=[row(102, no_receipt=True, mid=None)])
check("delivered with NO receipt at all -> FIRES",
      fire and "WITHOUT PROOF" in fire, f"got {fire!r}")

fire, _ = scenario(rows=[row(103, ok="false")])
check("status=delivered but receipt ok=false -> FIRES",
      fire and "WITHOUT PROOF" in fire, f"got {fire!r}")

fire, _ = scenario(rows=[row(104, mid=None, rendered="")])
check("poll/attachment-only path (no message_id, no text) -> FIRES and names it",
      fire and "WITHOUT PROOF" in fire and "poll" in fire, f"got {fire!r}")

fire, _ = scenario(rows=[row(105, mid=None, rendered="hello")])
check("text claimed delivered with no provider id -> FIRES",
      fire and "WITHOUT PROOF" in fire, f"got {fire!r}")

fire, _ = scenario(status=MOD["DRIFT"], detail="MsgID renamed")
check("store unreadable (DRIFT) -> FIRES rather than reading as all-clear",
      fire and "CANNOT READ" in fire, f"got {fire!r}")

fire, _ = scenario(detail="timeout", running=False)
check("wacli container down -> FIRES immediately",
      fire and "CANNOT SEE" in fire and "NOT RUNNING" in fire, f"got {fire!r}")

fire, _ = scenario(detail="timeout", running=True,
                   state={"last_ok": (NOW - timedelta(hours=BLIND_H + 1)).isoformat()})
check(f"flake persisting past {BLIND_H}h -> stops being transient, FIRES",
      fire and "CANNOT SEE" in fire, f"got {fire!r}")

fire, _ = scenario(route=(None, "my route carries no chat JID"))
check("route unidentifiable -> FIRES, and says the CHECK cannot run (not that I am mute)",
      fire and "CANNOT RUN" in fire and "does NOT mean" in fire, f"got {fire!r}")

# --- amnesia polarity: forgetting must make it LOUDER, never quieter ---------
print("\namnesia polarity (a lost ctx.state may only ever over-warn):")

fire, _ = scenario(detail="timeout", running=True, state={})
check("flake with NO remembered last_ok -> falls back to INSTALLED and FIRES",
      fire and "CANNOT SEE" in fire, f"got {fire!r}")

fire, _ = scenario(rows=[row(106, mid="ID-GONE")], state={})
check("a real drop with an empty state -> FIRES (throttle cannot suppress what it forgot)",
      fire and "NEVER GOT" in fire, f"got {fire!r}")

# --- MUST NOT FIRE: the quiet that is genuinely quiet ------------------------
print("\nmust STAY SILENT:")

fire, _ = scenario(rows=[row(107, mid="ID-A")], store_ids={"ID-A"})
check("every claimed id present in the store -> silent", fire is None, f"got {fire!r}")

fire, _ = scenario(rows=[])
check("no outbound rows in the window -> silent", fire is None, f"got {fire!r}")

fire, _ = scenario(rows=[row(108, mid="ID-A")], store_ids={"ID-A", "ID-OWNER-TYPED"})
check("store holds FromMe ids my wire never claimed (Umair typing himself) -> silent",
      fire is None, f"got {fire!r}")

fire, _ = scenario(rows=[row(109, age_h=0, mid="ID-GONE")])
check(f"a send younger than the {GRACE_MIN}min grace -> not yet evidence, silent",
      fire is None, f"got {fire!r}")

age_h = (NOW - INSTALLED).total_seconds() / 3600 + 24
fire, _ = scenario(rows=[row(110, age_h=age_h, mid="ID-GONE")])
check("a row predating INSTALLED -> never indicted (the pre-receipt 07-22 sends)",
      fire is None, f"got {fire!r}")

fire, _ = scenario(rows=[row(111, age_h=24 * (LOOKBACK_D + 5), mid="ID-GONE")])
check(f"a row older than the {LOOKBACK_D}d lookback -> outside the window, silent",
      fire is None, f"got {fire!r}")

fire, _ = scenario(detail="connection reset", running=True,
                   state={"last_ok": (NOW - timedelta(minutes=20)).isoformat()})
check("a genuine transient with a fresh last_ok -> swallowed, silence stays interpretable",
      fire is None, f"got {fire!r}")

# --- dedup: throttles a standing condition, never a NEW one ------------------
print("\ndedup on the offending SET, not on 'is anything wrong':")

fire, ctx = scenario(rows=[row(112, mid="ID-GONE")], state={})
check("first sighting fires", fire is not None, f"got {fire!r}")
carried = ctx.state
fire2, ctx2 = scenario(rows=[row(112, mid="ID-GONE")], state=carried)
check(f"same row again inside {RENAG_H}h -> throttled", fire2 is None, f"got {fire2!r}")
fire3, _ = scenario(rows=[row(112, mid="ID-GONE"), row(113, mid="ID-GONE2")],
                    state=ctx2.state)
check("a NEW dropped reply does NOT hide behind the older one's throttle",
      fire3 is not None and "113" in fire3, f"got {fire3!r}")

aged = {"warned": {k: (NOW - timedelta(hours=RENAG_H + 1)).isoformat()
                   for k in carried["warned"]}}
fire4, _ = scenario(rows=[row(112, mid="ID-GONE")], state=aged)
check(f"past {RENAG_H}h the standing condition re-nags", fire4 is not None, f"got {fire4!r}")

# --- positive evidence of observation ---------------------------------------
print("\nstate must carry positive evidence of the last real observation:")

_, ctx = scenario(rows=[row(114, mid="ID-A")], store_ids={"ID-A"})
check("a successful read stamps last_ok", bool(ctx.state.get("last_ok")),
      f"state={ctx.state!r}")
_, ctx = scenario(detail="timeout", running=True,
                  state={"last_ok": (NOW - timedelta(minutes=20)).isoformat()})
check("a FAILED read does not stamp last_ok (silence must not vouch for itself)",
      (NOW - MOD["_parse"](ctx.state["last_ok"])).total_seconds() > 600,
      f"state={ctx.state!r}")

# --- the window bounds the SQL is handed ------------------------------------
print("\nthe bounds passed to SQL (the WHERE clause itself is not exercised here):")

_, ctx = scenario(rows=[row(115, mid="ID-A")], store_ids={"ID-A"})
floor, ceiling = ctx.params[2], ctx.params[3]
check("floor is max(INSTALLED, now-lookback)",
      abs((floor - max(INSTALLED, NOW - timedelta(days=LOOKBACK_D))).total_seconds()) < 120,
      f"floor={floor}")
check(f"ceiling is now-{GRACE_MIN}min",
      abs((ceiling - (NOW - timedelta(minutes=GRACE_MIN))).total_seconds()) < 120,
      f"ceiling={ceiling}")
check("the thread queried is my wa: thread", ctx.params[1] == f"wa:{CHAT}",
      f"params={ctx.params!r}")

# --- the reader itself: a broken source must never read as an empty store ----
# This is the arm that matters most. _store_sent_ids returning (OK, set()) on a mangled
# reply would indict the bridge for every message I ever sent — a renamed field turning
# a healthy mouth into a fleet of phantom drops — so every mangling below must classify
# as DRIFT or FLAKE, never OK.
print("\nthe reader classifies a mangled source as UNKNOWN, never as an empty store:")

_store_sent_ids = PRISTINE["_store_sent_ids"]


class FakeProc:
    def __init__(self, out="", err="", rc=0):
        self.stdout, self.stderr, self.returncode = out, err, rc


def reader(out="", err="", rc=0):
    MOD["subprocess"] = type("S", (), {"run": staticmethod(
        lambda *a, **k: FakeProc(out, err, rc))})()
    try:
        return _store_sent_ids(CHAT, NOW - timedelta(days=1))
    finally:
        MOD["subprocess"] = PRISTINE["subprocess"]


GOOD = json.dumps({"success": True, "error": None, "data": {"fts": True, "messages": [
    {"MsgID": "ID-A", "Timestamp": "2026-08-15T10:00:00Z", "FromMe": True, "Text": "hi"}]}})

st, ids, _d = reader(out=GOOD)
check("the real wacli shape parses to the id set", st == MOD["OK"] and ids == {"ID-A"},
      f"got {st} {ids}")

for name, kwargs, want in [
    ("renamed join key (MsgID -> msg_id)",
     dict(out=GOOD.replace("MsgID", "msg_id")), MOD["DRIFT"]),
    ("not JSON at all", dict(out="<html>gateway</html>"), MOD["DRIFT"]),
    ("envelope reshaped (no message list)",
     dict(out=json.dumps({"success": True, "data": {"chats": []}})), MOD["DRIFT"]),
    ("wacli rejects the flags this guard was written against",
     dict(err="unknown flag: --from-me\nUsage:\n  wacli messages list", rc=1), MOD["DRIFT"]),
    ("success:false in the envelope",
     dict(out=json.dumps({"success": False, "error": "store locked", "data": None})),
     MOD["FLAKE"]),
    ("nonzero exit, ordinary error", dict(err="database is locked", rc=1), MOD["FLAKE"]),
]:
    st, ids, _d = reader(**kwargs)
    check(f"{name} -> {want}", st == want and not ids, f"got {st} ids={ids}")

st, ids, _d = reader(out=json.dumps({"success": True, "data": {"messages": []}}))
check("a genuinely empty window IS a real answer -> OK, empty",
      st == MOD["OK"] and ids == set(), f"got {st} {ids}")

# REGRESSION, and the bytes are wacli's own rather than my guess at them. The first cut
# of this file asserted the empty window as `"messages": []`, which is what I ASSUMED an
# empty result looks like; the live tool emits a Go nil slice as `null`, and the live
# probe below never caught it because its 30-day window was not empty. The trigger's
# first real evaluation under the pulse fired DRIFT at me within a minute. That is the
# safe polarity working exactly as designed — a detector that cannot read its source
# said so instead of reporting health — but the underlying error is the one this whole
# file exists to prevent: a fixture that encodes my belief about a source rather than
# the source. Verified RED against the pre-fix reader before the fix landed.
st, ids, _d = reader(out='{"success":true,"data":{"fts":true,"messages":null},"error":null}')
check("wacli's REAL empty-window bytes (messages:null) -> OK, empty, not DRIFT",
      st == MOD["OK"] and ids == set(), f"got {st} {ids}")

st, ids, _d = reader(out=json.dumps({"success": True, "data": {"fts": True}}))
check("messages key ABSENT (not null) is still DRIFT — absence is a shape change",
      st == MOD["DRIFT"], f"got {st} {ids}")

# --- live shape: pin the parser to what wacli ACTUALLY emits today -----------
print("\nlive shape (the only case that can catch upstream drifting under me):")
MOD["subprocess"] = PRISTINE["subprocess"]
try:
    live_chat, why = PRISTINE["_route"]()
except Exception as exc:
    live_chat, why = None, f"{type(exc).__name__}"
if not live_chat:
    skip(f"no live route available ({why}) — the parser was NOT checked against real wacli")
else:
    st, ids, detail = _store_sent_ids(live_chat, NOW - timedelta(days=LOOKBACK_D))
    if st == MOD["FLAKE"]:
        skip(f"wacli did not answer ({detail}) — parser NOT checked against real output")
    else:
        check("real wacli output is readable by this parser (not DRIFT)",
              st == MOD["OK"], f"got {st}: {detail}")
        check("real output yields a set of ids (join key present in live data)",
              isinstance(ids, set), f"got {type(ids).__name__}")

MOD.update(PRISTINE)

print()
if fails:
    print(f"FAILED {len(fails)}: " + ", ".join(fails))
    sys.exit(1)
if skips:
    # A SKIP is not a PASS. The verdict may not out-claim what actually ran.
    print(f"PASSED, with {len(skips)} case(s) UNVERIFIED (not run):")
    for s in skips:
        print(f"  - {s}")
    sys.exit(77)
print("all green — every arm verified, including the live wacli shape")
