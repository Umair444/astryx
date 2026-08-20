#!/home/umair/astryx/venv/bin/python
"""Is MIN_QUIET_H a calibrated floor or an unmeasured hope? (goal #2457)

    venv/bin/python nucleus/esc_latency.py [--days 30] [--floor 6]

THE CLAIM UNDER TEST, stated so it can be wrong. `wedge_watch.MIN_QUIET_H = 6` buys
SILENCE: an agent quiet for less than six hours is not alarmed on. Every floor that buys
silence rests on an empirical claim — HERE, that a wedge self-heals inside N — and that
claim had exactly one measurement behind it (a1, msg 12341): the 2026-08-19 latch did NOT
self-heal, it was cleared by a human at 3.2h, and it was STALE (account quota had already
returned while two seats stayed dark). It would have alarmed at 6.1h.

ONE INCIDENT IS A DATA POINT, NOT A CALIBRATION, and the wrong response to it is to retune
the constant until that incident would have been caught — an n=1 fit dressed as tuning.
This tool exists so the number is falsifiable instead: it derives EVERY quiet episode in
the window from the same observables the guard uses, and reports the distribution the
floor is a bet against. It deliberately recommends nothing.

THE DISTINCTION THE FLOOR RESTS ON IS NOT IN THE SUBSTRATE, AND THIS TOOL SAYS SO RATHER
THAN GUESSING IT. The floor's claim is "a wedge SELF-HEALS inside N", so evaluating it needs
self-heal told apart from human intervention. The first version of this file inferred that
from a `boot` step ending the gap. That is WRONG and I caught it against an episode I lived
through: seed's 87.9h gap — the 2026-08-15 org-wide outage, which a human ended — closes
with an ordinary `tool` step and no boot at all, because spawn.sh is RESUME-FIRST and a
resumed session writes no boot. Measured: 99 boot steps in 30 days against 13,700 tool
steps. So "no boot" pools genuine self-heals together with every human rescue, and reading
it as SELF-HEALED would have put a four-day outage in the column that argues the floor is
too LOW — an inverted conclusion drawn from a confident-looking number.

What is reported instead is what the rows can carry: duration, and whether a FRESH PROCESS
(boot) or a RESUMED one closed the episode, with the second named UNKNOWN CAUSE. One of the
two falsifiers below is therefore evaluable here and the other is not, and that is stated
rather than papered over. Episodes with wakes delivered into them are the guard's actual
subject; the rest are ordinary idleness and are reported separately.

WHAT WOULD FALSIFY THE FLOOR, named in advance so the answer cannot be fitted to the data:
  * TOO HIGH if a material share of subject episodes outlive the floor — every hour past it
    is alarm the org had earned and did not get. EVALUABLE HERE: duration is in the rows.
  * TOO LOW if a material share SELF-HEALED after the floor — they would have become alarms
    about a condition about to fix itself, which is the false-alarm budget the floor buys.
    NOT EVALUABLE HERE, and no number is offered for it: self-heal is exactly the fact the
    substrate does not record. Answering it needs a new observation at the moment a gap
    ends (who or what resumed the session), not a cleverer query over these tables.
One is reported. The other is named as unmeasured, which is the honest state of it.
"""
import argparse
import statistics
import sys
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _dsn():
    for line in (REPO / ".env").read_text().splitlines():
        if line.startswith("ASTRYX_DSN="):
            return line.split("=", 1)[1].strip()
    return None


def episodes(cur, days: int):
    """Every gap between consecutive steps, per agent, with what happened around it."""
    cur.execute(
        "SELECT agent, ts, kind FROM steps "
        "WHERE ts > now() - make_interval(days => %s) ORDER BY agent, ts", (days,))
    rows = cur.fetchall()
    out = []
    prev_agent = prev_ts = None
    for agent, ts, kind in rows:
        if agent == prev_agent and prev_ts is not None:
            gap_h = (ts - prev_ts).total_seconds() / 3600.0
            if gap_h > 0.5:                       # sub-30-minute gaps are not episodes
                out.append({"agent": agent, "start": prev_ts, "end": ts,
                            "hours": gap_h, "ended_with": kind})
        prev_agent, prev_ts = agent, ts
    return out


def wakes_into(cur, ep):
    """Wakes DELIVERED during the episode and never consumed — the guard's subject.
    A gap with no wake in it is an agent with nothing to do, not a wedge."""
    cur.execute(
        "SELECT count(*) FROM messages m WHERE m.to_agent = %s AND m.status = 'delivered' "
        "AND m.ts > %s AND m.ts < %s "
        "AND NOT EXISTS (SELECT 1 FROM turns t WHERE t.input_msg_id = m.id)",
        (ep["agent"], ep["start"], ep["end"]))
    return cur.fetchone()[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--floor", type=float, default=6.0, help="MIN_QUIET_H under test")
    a = ap.parse_args()

    dsn = _dsn()
    if not dsn:
        print("no ASTRYX_DSN — cannot measure"); return 77
    import psycopg
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        eps = episodes(cur, a.days)
        for e in eps:
            e["wakes"] = wakes_into(cur, e)

    subjects = [e for e in eps if e["wakes"] > 0]
    if not subjects:
        print(f"no quiet episode carried an unconsumed wake in {a.days}d — "
              f"nothing to calibrate against."); return 77

    fresh = [e for e in subjects if e["ended_with"] == "boot"]
    resumed = [e for e in subjects if e["ended_with"] != "boot"]   # CAUSE UNKNOWN
    over = [e for e in subjects if e["hours"] >= a.floor]

    print(f"escalation-latency calibration · {a.days}d · floor under test = {a.floor}h\n")
    print(f"  quiet episodes (>30m):                    {len(eps)}")
    print(f"  …carrying an unconsumed wake (SUBJECTS):  {len(subjects)}")
    print(f"  …closed by a FRESH process (boot):        {len(fresh)}")
    print(f"  …closed by a RESUMED session (cause UNKNOWN — self-heal and human")
    print(f"     rescue are indistinguishable here):    {len(resumed)}")
    print(f"  …longer than the floor:                   {len(over)}\n")

    hrs = sorted(e["hours"] for e in subjects)
    print(f"  subject duration  min {hrs[0]:.1f}h · median {statistics.median(hrs):.1f}h "
          f"· max {hrs[-1]:.1f}h")

    # THE ONE FALSIFIER THIS SUBSTRATE CAN ANSWER.
    print(f"\n  FLOOR TOO HIGH?  subject episodes that outlived the floor: "
          f"{len(over)}/{len(subjects)}")
    for e in sorted(over, key=lambda x: -x["hours"])[:5]:
        print(f"      {e['agent']:<14} {e['hours']:6.1f}h  — {e['hours']-a.floor:.1f}h of it "
              f"past the floor, before the guard was allowed to speak")
    print(f"\n  FLOOR TOO LOW?   NOT EVALUABLE. Deciding it needs self-heal told apart from")
    print(f"                   human rescue, and the substrate does not record which ended")
    print(f"                   a gap: spawn.sh is resume-first, so a rescued agent writes no")
    print(f"                   boot. The 87.9h org outage of 2026-08-15 closes with an")
    print(f"                   ordinary tool step. No number is offered for this side.")

    # n=1 refusal, in the tool rather than in the reader's discipline.
    print()
    if len(subjects) < 10:
        print(f"  N = {len(subjects)}. TOO FEW TO RETUNE ANYTHING. This is a data point, not a\n"
              f"  calibration — the incident that prompted this tool was n=1 and the whole\n"
              f"  point is not to fit a constant to it. Re-run as episodes accumulate.")
    else:
        print(f"  N = {len(subjects)} subject episodes — enough to argue from, and the floor\n"
              f"  was set against n=1. But only ONE of the two falsifiers is answered above;\n"
              f"  moving the floor on the evaluable half alone trades a measured miss for an\n"
              f"  UNMEASURED false-alarm cost. This tool reports and does not recommend.")
    print("\n  CEILING: a gap with no unconsumed wake in it is idleness, not a wedge, and is\n"
          "  excluded. 'Closed by a fresh process' is a fact about the process, never about\n"
          "  whether a human was needed — that fact is not in these tables at all.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
