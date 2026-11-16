#!/usr/bin/env python3
"""Oracle: the org's tiredness (src/astryx/econ/energy.py) is a forecast with no threshold in it.

    venv/bin/python tests/test_energy.py

Pure arms on the arithmetic, then a fixture database (this tree's schema.sql; fixture rows only) for what is learned.
  E1 THE FEELING IS NEED OVER WHAT IS LEFT: the same gauge reads rested before a quiet night and tired before a busy day
  E2 A RESET CLOSE BY MAKES A NEARLY FULL WEEK'S REMAINDER SPARE; the same gauge a week from its reset is spoken for
  E3 RUNNING OUT is named with its hour; a window that isn't running is a whole new one
  E4 NO SWITCH: ease() is smooth and strictly falling in tiredness, strictly rising in payback, 1 when rested
  E5 UNKNOWN IS NOT RESTED: no gauge or no learned rate gives no feeling
  E6 LEARNED FROM THE ORG'S OWN HISTORY: the hourly profile leaves self-started thinking out; the rate is gauge points per token
  E10 a vault login's limits are its own reading; the org's feeling never reads it
  E7 the per-prompt line states the reading with no verdict word, and an agent's own heavier-than-usual turn, as facts
  E8 ONE NOTICE PER DOUBLING PER TURN: parallel calls, a tail that slides back and climbs again, a new turn (medic 12281)
Exit 0 · 1 · 77 (no database).
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_energy", REPO, deps=("psycopg",), env=False)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402
from astryx.econ import energy as E  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {str(detail)[:300]}"))
    if not ok:
        fails.append(name)


NOW = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)          # 18:00 UTC
HOURLY = [100_000.0] * 24
for h in range(4, 14):
    HOURLY[h] = 2_000_000.0                                      # the org's day: 04:00-14:00 UTC; the rest is night
RATE = 3e-6                                                      # a million tokens moves the gauge 3 points
iso = lambda d: d.isoformat()

print("E1 need over what is left")
night = E.window(60, iso(NOW + timedelta(hours=5)), 5, RATE, HOURLY, NOW)
day = E.window(60, iso(NOW.replace(hour=5) + timedelta(hours=5)), 5, RATE, HOURLY, NOW.replace(hour=5))
arm("E1 60% used before five quiet hours: rested, most of what is left is spare", night["tired"] < 0.1 and night["spare"] > 35, night)
arm("E1 the same 60% before five busy hours: it needs more than is left", day["tired"] > 0.7, day)

print("E2 a reset close by")
wk = 5e-7
soon = E.window(26, iso(NOW + timedelta(hours=14)), 168, wk, HOURLY, NOW)
far = E.window(26, iso(NOW + timedelta(days=6)), 168, wk, HOURLY, NOW)
arm("E2 26% used and the week resets in 14 hours: nearly all of the rest goes unused", soon["tired"] < 0.2 and soon["spare"] > 60, soon)
arm("E2 26% used with six days to go: the same remainder is mostly spoken for", far["tired"] > 3 * soon["tired"], (soon, far))

print("E3 running out; a window not running")
dry = E.window(95, iso(NOW.replace(hour=4) + timedelta(hours=5)), 5, RATE, HOURLY, NOW.replace(hour=4))
arm("E3 it runs out before the reset: tired past 1, and the hour is named, before the reset",
    dry["tired"] > 1 and dry["dry_at"] and E._when(dry["dry_at"]) < E._when(dry["resets_at"]), dry)
gone = E.window(95, iso(NOW - timedelta(hours=1)), 5, RATE, HOURLY, NOW)
arm("E3 a reset already past: a whole new window, nothing used", gone["left"] == 100 and gone["tired"] < 0.1, gone)

print("E4 no switch")
ts = [i / 50 for i in range(0, 151)]
es = [E.ease(t) for t in ts]
arm("E4 rested keeps all of its pull", E.ease(0) == 1.0)
arm("E4 strictly falling, and never by a jump (no step over 7% between neighbours 0.02 apart)",
    all(a > b and a - b < 0.07 for a, b in zip(es, es[1:])), max(a - b for a, b in zip(es, es[1:])))
arm("E4 what gives energy back keeps its pull: rising in payback at every tiredness",
    all(E.ease(t, 0) < E.ease(t, 1) < E.ease(t, 10) for t in ts[1:]))

print("E5 unknown is not rested")
arm("E5 no gauge reading: no feeling", E.window(None, None, 5, RATE, HOURLY, NOW) is None)
arm("E5 no learned rate: no feeling", E.window(50, None, 5, None, HOURLY, NOW) is None)

print("E9 the pulse's hold reads the 5-hour window only (medic 12383)")
from astryx.pulse import pulse as P  # noqa: E402
fresh_week = E.window(0, iso(NOW + timedelta(days=7)), 168, 1e-6, [6.7e5] * 24, NOW)        # the usual week needs ~112%
easy_h5 = E.window(12, iso(NOW + timedelta(hours=4)), 5, RATE, HOURLY, NOW)
arm("E9 a fresh week whose usual pace needs 112%, the 5 hours at 12%: tired by the week, and nothing held",
    fresh_week["tired"] > 1 and P.held_now({"known": True, "windows": {"h5": easy_h5, "d7": fresh_week}}) is False, (fresh_week["tired"], easy_h5["tired"]))
hot_h5 = E.window(95, iso(NOW.replace(hour=6) + timedelta(hours=2)), 5, RATE, HOURLY, NOW.replace(hour=6))
arm("E9 the 5 hours at 95% with 2 h to go and a pace needing more than is left: held",
    hot_h5["need"] > 5 and P.held_now({"known": True, "windows": {"h5": hot_h5}}) is True, hot_h5)
arm("E9 unknown, or no 5-hour reading: nothing held (unknown delivers)",
    P.held_now({"known": False}) is None and P.held_now({"known": True, "windows": {"d7": fresh_week}}) is None)

print("E7 the line")
f = {"known": True, "say": "rested · the week: 74% left", "fact": "the week: 74% left"}
p = {"usual": {"a": 100_000.0}, "rate": {"d7": 5e-7}}
arm("E7 a turn at 4x the usual is said, with its share of the week", "4× your usual" in E.line(f, E.mine(p, "a", 400_000)) and "0.2% of the week" in E.mine(p, "a", 400_000),
    E.line(f, E.mine(p, "a", 400_000)))
arm("E7 the prompt line carries the reading and no verdict word", E.line(f) == "[energy] the week: 74% left", E.line(f))
arm("E7 a usual turn says nothing of itself; an unknown feeling prints nothing", E.mine(p, "a", 90_000) == "" and E.line({"known": False}) == "")


print("E8 one notice per doubling per turn")
import tempfile
with tempfile.TemporaryDirectory() as said:
    arm("E8 felt: the doubling is felt on the call that passes it, not again on the next", [E.felt(t, b, 100) for t, b in ((150, 100), (210, 150), (390, 210), (410, 390), (900, 790), (900, 810))] == [0, 2, 0, 4, 8, 0])
    arm("E8 two hook runs on one transcript state (a parallel batch): one notice", [E.claim(said, 4), E.claim(said, 4)] == [True, False])
    arm("E8 the tail slid back under 4× and climbed again, or reads a lower multiple: no second notice", [E.claim(said, 4), E.claim(said, 2)] == [False, False])
    arm("E8 the next doubling of the same turn is said", E.claim(said, 8) is True)
    E.rest(said)
    arm("E8 after the turn's end, a new turn's 2× is said", E.claim(said, 2) is True)
arm("E8 a directory that isn't there claims nothing (fail closed: no notice)", E.claim("/nonexistent/astryx-effort", 2) is False)


def main():
    import psycopg
    with fixture_db() as d, psycopg.connect(d["url"], autocommit=True) as c:
        print("E6 learned from the org's own history")
        E._t = lambda: 'public."t_energy_pace"'
        mid = c.execute("INSERT INTO messages (from_agent, from_org, to_agent, intent, thread, body) VALUES ('pulse','local','a','drive','mind','x') RETURNING id").fetchone()[0]

        def turn(h_ago, tok, pct, msg=None):
            c.execute("""INSERT INTO turns (agent, started_at, ended_at, tokens_in, tokens_out, input_msg_id, usage_snapshot)
                         VALUES ('a', now() - make_interval(hours => %s), now() - make_interval(hours => %s), 0, %s, %s,
                                 jsonb_build_object('state', 'fresh', 'fetched_at', (now() - make_interval(hours => %s))::text, 'data', jsonb_build_object('seven_day_utilization', %s::numeric, 'five_hour_utilization', %s::numeric,
                                   'seven_day_resets_at', (now() + interval '2 days')::text, 'five_hour_resets_at', (now() + interval '2 hours')::text)))""",
                      (h_ago, h_ago, tok, msg, h_ago, pct, pct * 2))
        turn(30, 1_000_000, 10); turn(29, 1_000_000, 11); turn(28, 2_000_000, 13); turn(27, 5_000_000, 13, mid)
        p = E.learn(c)
        arm("E6 the week's rate: 3 points over the 9M tokens of the span", abs(p["rate"]["d7"] - 3 / 9e6) < 1e-9, p["rate"])
        arm("E6 the 5-hour rate is learned by itself (6 points)", abs(p["rate"]["h5"] - 6 / 9e6) < 1e-9, p["rate"])
        arm("E6 the profile leaves the self-started think out (4M counted, not 9M)", abs(sum(p["hourly"]) * min(14, 30 / 24) - 4e6) < 1e3, sum(p["hourly"]))
        arm("E6 a think's usual cost is the measured one", p["think"] == 5_000_000, p["think"])
        got = E.pace(c)
        arm("E6 kept in one row and read back", got and got["rate"] == p["rate"])
        arm("E5 a reading a day old says nothing of now: unknown, not rested", E.feel(c, relearn_after_h=None)["known"] is False)
        # 11-16: an evening's 98% read before the window reset held every pulse wake for nine hours. A reading whose
        # reset has passed is a fresh window, so the pulse's hold (pulse.pressure reads this feeling) lets wakes go
        c.execute("""INSERT INTO turns (agent, started_at, ended_at, tokens_in, tokens_out, usage_snapshot) VALUES ('a', now() - interval '3 hours',
                     now() - interval '3 hours', 0, 1, jsonb_build_object('state', 'fresh', 'fetched_at', (now() - interval '3 hours')::text,
                     'data', jsonb_build_object('five_hour_utilization', 98, 'seven_day_utilization', 13,
                     'five_hour_resets_at', (now() - interval '2 hours')::text, 'seven_day_resets_at', (now() + interval '2 days')::text)))""")
        # E10 PER LOGIN (owner 11-16): a vault login's reading is its own; the org's feeling never reads it
        c.execute("""INSERT INTO turns (agent, started_at, ended_at, tokens_in, tokens_out, usage_snapshot) VALUES ('b', now(), now(), 0, 1,
                     jsonb_build_object('state', 'fresh', 'fetched_at', now()::text, 'credential', 'Second',
                       'data', jsonb_build_object('five_hour_utilization', 91, 'seven_day_utilization', 50,
                       'five_hour_resets_at', (now() + interval '1 hour')::text, 'seven_day_resets_at', (now() + interval '2 days')::text)))""")
        own = E.feel(c, relearn_after_h=None, credential="Second")
        org = E.feel(c, relearn_after_h=None)
        arm("E10 a vault login feels its own reading (91% of its 5 hours); the org's feeling never reads it",
            own.get("known") and own["windows"]["h5"]["used"] == 91 and org.get("known") and org["windows"]["h5"]["used"] == 0, (own.get("windows"), org.get("windows")))
        arm("E10 a login with no reading of its own is unknown, never the org's", E.feel(c, relearn_after_h=None, credential="Nobody").get("known") is False)
        import tempfile as _tf
        from astryx.core import vault as _V
        from astryx.pulse import pulse as P0
        with _tf.TemporaryDirectory() as est:
            est = Path(est)
            (est / "runtime.json").write_text('{"b": {"credential": "Second"}, "z": {"credential": "Third"}}')
            _V.save(est, {"Second": _V.entry("Second", "claude"), "Third": _V.entry("Third", "claude")})
            (est / ".env").write_text("ASTRYX_CRED_SECOND=sk-ant-oat01-" + "x" * 30 + "\nASTRYX_CRED_THIRD=sk-ant-oat01-" + "y" * 30 + "\n")
            ln_b, keep_b = E.prompt_line(c, "b", est)
            ln_z, keep_z = E.prompt_line(c, "z", est)
            arm("E10 the prompt line of an agent on a login reads that login (its own reading)", ln_b.startswith("[energy] ") and "50% left" in ln_b and not keep_b, ln_b)
            arm("E10 …a login with no reading says so, with no percentage, and hides the org's gauges (medic 12481)",
                ln_z == "[energy] Third: no reading of this login's limits yet" and not keep_z and "%" not in ln_z, (ln_z, keep_z))
            # E11 the pulse's reading per agent (energy.by_agent): every login read once, up front; an agent feels its own
            calls, real = [], E.feel
            E.feel = lambda *a, **k: (calls.append(k.get("credential")), real(*a, **k))[1]
            try:
                of = E.by_agent(c, est, relearn_after_h=None)
                n0 = len(calls)
                fb, fz, fa, fb2 = of("b"), of("z"), of("a"), of("b")
            finally:
                E.feel = real
            arm("E11 by_agent: b feels Second (91%), z's login is unknown, a feels the org's",
                fb.get("known") and fb["windows"]["h5"]["used"] == 91 and fz.get("known") is False
                and fa.get("known") and fa["windows"]["h5"]["used"] == 0, (fb.get("windows"), fz, fa.get("windows")))
            arm("E11 …each login read once, all of them before any question (no SQL after: the pulse asks inside its claim)",
                sorted(calls, key=str) == sorted([None, "Second", "Third"], key=str) and len(calls) == n0, calls)
            arm("E11 the pulse judges b by Second, a by the org, z (no reading) as unknown, which delivers",
                P0.held_now(fb) is P0.held_now(own) and P0.held_now(fa) is P0.held_now(org) and P0.held_now(fz) is None,
                (P0.held_now(fb), P0.held_now(own), P0.held_now(fa), P0.held_now(org)))
        from astryx.pulse import pulse as P
        fr = E.feel(c, relearn_after_h=None)
        arm("E6 98% read before its 5-hour reset, the reset now past: a fresh window, and the pulse holds nothing",
            fr.get("known") and fr["windows"]["h5"]["used"] == 0 and P.pressure(c)(None) is False, (fr.get("windows"), P.pressure(c)(None)))
        turn(0, 100_000, 14)
        fl = E.feel(c, relearn_after_h=None)
        arm("E6 feel: known, the tighter window binds, a word and a sentence",
            fl.get("known") and fl["binding"] in ("h5", "d7") and fl["say"] == f"{fl['word']} · {fl['fact']}" and fl["tired"] == max(w["tired"] for w in fl["windows"].values()), fl.get("say"))


try:
    main()
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    fails.append(f"crashed: {type(e).__name__}")
print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: tiredness is a forecast, and nothing switches on it")
sys.exit(1 if fails else 0)
