#!/usr/bin/env python3
"""NUCLEUS · oracle for the clock watchdog pair — nucleus/pulse_watch.py (outside the
pulse) and triggers/scout/clock_stamp.py (inside it).

WHAT THIS PAIR CLAIMS, and therefore what has to be falsifiable here: that if the org's
clock stops, someone is told; and that if the TELLER stops, someone is told about that.
Every assertion below exists because a specific way of writing this guard would look
correct, pass a casual read, and report a healthy org while nothing was watching.

TWO OF THESE ARE REGRESSIONS FOR DEFECTS THAT WERE ACTUALLY IN THE FILE, both caught by
running it against real substrate rather than by reading it:

  §1b  `systemctl show` answers rc=0 for a unit systemd has NEVER HEARD OF, printing
       ActiveState=inactive. The first version read that as CLOCK_STOPPED — a false RED
       with a remedy that cannot work, and the exact shape a rename or a drift between
       the constant and the deployed unit name would take. LoadState is the only field
       that separates "not armed" from "not there".

  §5b  The guard reported HEALTHY off a stamp that MY OWN by-hand test run had written.
       Freshness alone cannot distinguish a deployed watchdog from a human grading one,
       and the by-hand case is the likelier state of the two: a unit written and never
       enabled is exactly where astryx-check.timer has sat since it was generated.

NOT A COMPLETENESS CLAIM. The mutant set in nucleus/mutants_pulse_watch.py bounds what
these assertions are known to kill; run it with nucleus/mutation_probe.py.
"""
import json
import runpy
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# THE PROBE CHANNEL, not a user-facing override: nucleus/mutation_probe.py sets this to a
# mutated copy of the subject and re-runs this oracle, so every assertion below has to be
# falsifiable by an edit to the real file rather than merely true of it. Loaded by path
# (runpy) instead of `import pulse_watch` for exactly that reason — an import would bind
# the pristine module no matter what the probe wrote.
import os                                    # noqa: E402
import types                                 # noqa: E402

SUBJECT = Path(os.environ.get("PULSE_WATCH_SRC", REPO / "nucleus" / "pulse_watch.py"))
pw = types.SimpleNamespace(**runpy.run_path(str(SUBJECT), run_name="_oracle"))

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(f"{name} {detail}")


def sd_ts(dt: datetime) -> str:
    """systemd's own LastTriggerUSec rendering, which is what the parser must survive:
    'Thu 2026-08-20 06:38:00 PKT' — local wall clock with an abbreviation %Z cannot
    round-trip. Built from a real local-time datetime so the fixture speaks the host's
    language rather than the test author's."""
    return dt.astimezone().strftime("%a %Y-%m-%d %H:%M:%S %Z")


def timer(load="loaded", active="active", last=None, unitfile="enabled") -> dict:
    d = {"LoadState": load, "ActiveState": active, "UnitFileState": unitfile}
    if last is not None:
        d["LastTriggerUSec"] = sd_ts(last)
    return d


def utc(minutes_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


# ------------------------------------------------------------------ §1 blindness first
print("\n§1  a detector that cannot see must read as WATCHED, never as OK")

code, _, _ = pw.verdict({}, {}, utc(0), 5, 60.0, None)
check("§1a  unreadable systemd -> BLIND_SYSTEMD", code == "BLIND_SYSTEMD", code)

code, sent, _ = pw.verdict(timer(load="not-found", active="inactive", unitfile=""),
                           {}, utc(0), 5, 60.0, None)
check("§1b  a unit systemd never heard of -> BLIND_SYSTEMD, NOT a diagnosis",
      code == "BLIND_SYSTEMD", code)
check("§1b' ...and it says the state is UNKNOWN rather than stopped",
      "UNKNOWN" in sent and "stopped" in sent.lower(), sent[:80])

code, _, _ = pw.verdict(timer(last=utc(0)), {}, None, 0, None, "connection refused")
check("§1c  postgres unreachable -> BLIND_DB even with a perfect-looking timer",
      code == "BLIND_DB", code)

code, _, _ = pw.verdict(timer(last=utc(0)), {}, utc(0), 0, None, None)
check("§1d  clock ticking but ZERO triggers enabled -> TRIGGERS_EMPTY, not OK",
      code == "TRIGGERS_EMPTY", code)

# ------------------------------------------------------------------ §2 the real states
print("\n§2  each verdict is concluded from an OBSERVED value, and they do not collapse")

code, sent, _ = pw.verdict(timer(active="inactive", unitfile="disabled", last=utc(30)),
                           {}, utc(0), 5, 60.0, None)
check("§2a  loaded + inactive -> CLOCK_STOPPED", code == "CLOCK_STOPPED", code)
check("§2a' ...and a DISABLED unit file says a reboot will not fix it",
      "reboot" in sent.lower(), sent[:80])

code, _, _ = pw.verdict(timer(last=utc(60)), {}, utc(0), 5, 60.0, None)
check("§2b  armed but not firing -> CLOCK_STALE", code == "CLOCK_STALE", code)

code, sent, _ = pw.verdict(timer(last=utc(0)), {}, utc(60), 5, 60.0, None)
check("§2c  clock fine, evaluations frozen -> TICK_BARREN (the 2026-07-26 db-refused class)",
      code == "TICK_BARREN", code)
check("§2c' ...and TICK_BARREN is unreachable from the timer alone",
      "evaluation" in sent, sent[:80])

code, _, _ = pw.verdict(timer(last=utc(0)), {}, utc(0), 71, 120.0, None)
check("§2d  everything fresh -> OK", code == "OK", code)

# THE FLOOR IS A DERIVED QUANTITY, not a constant: it must also clear CADENCE_MULT
# evaluation cadences of the org's FASTEST trigger, so an org whose quickest guard runs
# every 6 hours is not accused every 10 minutes.
code, _, _ = pw.verdict(timer(last=utc(0)), {}, utc(45), 5, 3600.0, None)
check("§2e  floor stretches to the org's own cadence (45m eval age, hourly fastest -> OK)",
      code == "OK", code)

# ------------------------------------------------------------------ §3 the ladder
print("\n§3  the ladder announces the ARRIVAL, and the sentinel does not eat rung 0")

check("§3a  below the floor is NEVER (-1), not rung 0", pw.band(599, 600) == pw.NEVER,
      str(pw.band(599, 600)))
check("§3b  AT the floor is rung 0 — reachable, and strictly greater than the sentinel",
      pw.band(600, 600) == 0 and 0 > pw.NEVER, str(pw.band(600, 600)))
check("§3c  the sentinel is NOT 0 (a first rung colliding with 'never seen' cannot fire)",
      pw.NEVER != 0, str(pw.NEVER))
rungs = [pw.band(600 * m, 600) for m in (1, 2, 4, 8, 16)]
check("§3d  open ladder, strictly widening", rungs == [0, 1, 2, 3, 4], str(rungs))

# ------------------------------------------------------------------ §4 who gets woken
print("\n§4  the owner is the reader of LAST resort, and the order is not reversible")

check("§4a  the owner rung is silent while seed's rung has only just armed",
      pw.band(pw.FLOOR_S, pw.OWNER_ESC_S) == pw.NEVER,
      str(pw.band(pw.FLOOR_S, pw.OWNER_ESC_S)))
check("§4b  ...and arms once the condition has stood past the escalation floor",
      pw.band(pw.OWNER_ESC_S, pw.OWNER_ESC_S) == 0)
check("§4c  escalation floor is strictly above the seed floor",
      pw.OWNER_ESC_S > pw.FLOOR_S, f"{pw.OWNER_ESC_S} vs {pw.FLOOR_S}")

# ------------------------------------------------------------------ §5 the pulse-side half
print("\n§5  the stamp reader: a hand-written stamp is not a deployment")

TRIG = REPO / "triggers" / "scout" / "clock_stamp.py"


class Ctx:
    def __init__(self, state=None):
        self.state = dict(state or {})


def run_trigger(stamp_path: Path, state=None):
    """Loaded the way the pulse loads it (runpy.run_path), then patched THROUGH THE
    FUNCTION'S OWN __globals__.

    run_path returns a COPY of the namespace it executed in; the function it hands back
    still closes over the original dict. Assigning into the returned dict therefore
    patches nothing and the call reads the LIVE var/pulse_watch.json — which is how the
    first version of this oracle ran its entire §5 against production data, with two
    assertions passing for the wrong reason. It was caught only by §5a', which asserts
    the alarm text names the path we meant to point at. That is the third time I have
    stubbed a binding the callee does not read; the habit that catches it is not care,
    it is an assertion that the substitution took."""
    mod = runpy.run_path(str(TRIG))
    fn = mod["clock_stamp"]
    fn.__globals__["STAMP"] = stamp_path
    assert fn.__globals__["STAMP"] == stamp_path
    ctx = Ctx(state)
    return fn(ctx), ctx.state


with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    missing = tmp / "absent.json"

    fire, st = run_trigger(missing)
    check("§5a  no stamp at all -> fires on the FIRST evaluation (rung 0), no grace period",
          bool(fire) and "NOT DEPLOYED" in fire and st.get("missing_rung") == 0, str(fire)[:60])
    check("§5a' ...and the alarm names the temp path it was actually pointed at, so this "
          "test is exercising the patch rather than the live file",
          "absent.json" in fire or str(missing) in fire, fire[:80])
    fire2, _ = run_trigger(missing, st)
    check("§5a\" ...and does not re-nag on the very next tick (rung already spent)",
          fire2 is None, str(fire2)[:60])

    hand = tmp / "hand.json"
    hand.write_text(json.dumps({"last_run": datetime.now(timezone.utc).isoformat(),
                                "by": "hand", "code": "OK", "note": "fine"}))
    fire, st = run_trigger(hand)
    check("§5b  a FRESH stamp with no systemd run behind it is still NOT DEPLOYED",
          bool(fire) and "NOT DEPLOYED" in fire, str(fire)[:60])
    check("§5b' ...and says why, so nobody reads it as the clock being broken",
          "hand" in (fire or "").lower(), (fire or "")[:80])

    live = tmp / "live.json"
    now_iso = datetime.now(timezone.utc).isoformat()
    live.write_text(json.dumps({"last_run": now_iso, "by": "systemd", "code": "OK",
                                "note": "fine", "last_systemd_run": now_iso}))
    fire, st = run_trigger(live)
    check("§5c  a fresh SYSTEMD stamp is silent", fire is None, str(fire)[:60])
    check("§5c' ...and records positive evidence that it looked (a skip is not a pass)",
          "last_ok" in st and st["last_ok"].get("stamp_by") == "systemd", json.dumps(st)[:80])

    stale = tmp / "stale.json"
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    stale.write_text(json.dumps({"last_run": datetime.now(timezone.utc).isoformat(),
                                 "by": "hand", "code": "OK", "note": "fine",
                                 "last_systemd_run": old}))
    fire, st = run_trigger(stale)
    check("§5d  a stamp kept fresh BY HAND over a dead timer is still STALE — the clock "
          "this reader runs on cannot be advanced by a human",
          bool(fire) and "STALE" in fire, str(fire)[:60])

    corrupt = tmp / "corrupt.json"
    corrupt.write_text("{not json at all")
    raised = False
    try:
        run_trigger(corrupt)
    except Exception:
        raised = True
    check("§5e  an unparseable stamp RAISES (the pulse's loud path), never returns silence",
          raised)

    noky = tmp / "nokey.json"
    noky.write_text(json.dumps({"code": "OK"}))
    raised = False
    try:
        run_trigger(noky)
    except Exception:
        raised = True
    check("§5f  a stamp whose format drifted out from under this reader RAISES", raised)

print("\n§5g provenance: the stamp must say who wrote it")

# The gap mutation_probe found in the first version of this file (M7 survived): every §5
# case above drives the reader with FIXTURE stamps, so nothing could notice pulse_watch
# lying about who invoked it — and a hand run claiming to be a timer run makes an
# undeployed watchdog look deployed to its own reader. systemd exports INVOCATION_ID into
# every service it starts and nothing else does, so this is an observed fact about the
# invoker, not an inference from timing.
# Regression for a defect that reproduced LIVE on this host (2026-08-20 01:49): the first
# fix read INVOCATION_ID, which systemd sets for a unit and EVERY CHILD INHERITS. Every
# resident body here runs inside astryx-residents.service, so a hand-typed run stamped
# itself `by=systemd` and CERTIFIED AN AUTOMATION THAT DID NOT EXIST — silencing the one
# arm carrying the sudo line that would have deployed it. An inherited marker names an
# ancestor, not the actor. (steward, msg 12935, from his own check_stamp; verified here
# before accepting it — INVOCATION_ID was in fact present in this session's environ.)
with tempfile.TemporaryDirectory() as td:
    cg = Path(td) / "cgroup"

    cg.write_text("0::/system.slice/astryx-pulse-watch.service\n")
    os.environ["PULSE_WATCH_CGROUP"] = str(cg)
    check("§5g  cgroup names OUR unit -> 'systemd'", pw.provenance() == "systemd", pw.provenance())

    cg.write_text("0::/system.slice/astryx-residents.service\n")
    os.environ["INVOCATION_ID"] = "36a83c8fd3a447bfa0491bfe8b2d3623"   # the real inherited one
    check("§5g' a resident shell that INHERITED a systemd marker is still 'hand'",
          pw.provenance() == "hand", pw.provenance())

    os.environ["PULSE_WATCH_CGROUP"] = str(Path(td) / "absent")
    check("§5g\" an unreadable cgroup resolves to 'hand' (nag about absent automation, "
          "never vouch for it)", pw.provenance() == "hand", pw.provenance())
    os.environ.pop("PULSE_WATCH_CGROUP", None)
    os.environ.pop("INVOCATION_ID", None)

# ------------------------------------------------------------------ §6 the pairing itself
print("\n§6  the two halves are not in one failure domain")

src_watch = (REPO / "nucleus" / "pulse_watch.py").read_text()
src_trig = TRIG.read_text()
check("§6a  the watchdog is NOT a trigger (a watcher of the pulse must not run in it)",
      "from astryx import trigger" not in src_watch and "@trigger" not in src_watch)
check("§6b  a unit exists that invokes it, so it is not by-hand-only",
      any("pulse_watch.py" in p.read_text()
          for p in (REPO / "units").glob("*.service")),
      "no unit ExecStart names nucleus/pulse_watch.py")
check("§6c  init.sh regenerates that unit, so a fresh org gets the watchdog too",
      "astryx-pulse-watch.timer" in (REPO / "init.sh").read_text())
check("§6d  the pulse-side reader keys on the SYSTEMD run, not merely on freshness",
      "last_systemd_run" in src_trig)

print()
if FAILS:
    print(f"FAIL: {len(FAILS)} assertion(s)")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("PASS: clock watchdog pair")
