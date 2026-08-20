#!/usr/bin/env python3
"""astryx · pulse_watch — the one guard that cannot live in the pulse.

WHAT IT WATCHES: the org's clock itself. Every trigger in this org — all 60-odd of
them, every agent's watchers — is evaluated by nucleus/pulse.py, run once a minute by
astryx-pulse.timer. When that clock stops, EVERY guard in the org goes silent at once,
and on every surface the org has, that silence is indistinguishable from health:
`triggers.last_eval` simply stops moving and nothing reads it. There is no alarm whose
absence is suspicious, because the thing that would raise it is the thing that died.

WHY IT IS NOT A TRIGGER. A watcher of the pulse that runs IN the pulse proves nothing:
its silence has the same two causes as the condition it watches. So this runs from its
own systemd timer (astryx-pulse-watch.timer, every 5m) and writes a STAMP; the cheap
half — triggers/scout/clock_stamp.py — reads the stamp from inside the pulse. The split
is the point, and it is abstractor-2's, copied deliberately from nucleus/check_watch.sh:
a stamp cannot be deafened by the thing it records. If THIS script stops running, the
stamp goes stale and the trigger says so; if the PULSE stops, this script says so. Each
half is the other's independent reader, and neither can be silenced alone.

THE MEASUREMENT, because a floor that buys silence is an empirical claim and mine had
better be measured rather than chosen (scout, 2026-08-20, from this host's journal —
42,291 pulse ticks over exactly 30 days, 2026-07-21 → 2026-08-20):

    gaps > 60s ..... 4        the whole population of non-nominal gaps
      6.60h   2026-07-23 04:50 -> 11:26     host down (boot at 11:18)
      8.31h   2026-07-26 05:17 -> 13:35     host down (boot at 13:35)
     17.1m    2026-08-20 00:04 -> 00:21     LIVE HOST: `systemctl stop astryx-pulse.timer`
      2.2m    2026-07-27 12:42 -> 12:44     the largest gap with no human act behind it

    So on a LIVE host the pulse has never drifted past 129s on its own, and the only
    multi-minute stoppage in 30 days was a deliberate admin act. FLOOR_S = 600 is 4.6x
    the worst spontaneous gap: it would have fired exactly once in 30 days, on the real
    event, and never falsely. The two hour-scale gaps were host-down, when nothing
    inside could have spoken at all — those are the RECOVERY REPORT's business, below.

THE RISK IS NOT THE STOP, IT IS THE STOP NOBODY UNDOES. `systemctl stop` (as opposed to
disable) survives until someone types `start` or the host reboots. On 2026-08-20 the
clock was stopped for 17 minutes for maintenance and restarted by hand. Had the operator
wedged in that window — which is precisely what the org lived through for 88 hours,
2026-08-15 → 08-19 — the clock would still be stopped, every guard would still be
silent, and the only thing that would ever have restarted it is a reboot.

WHAT IT CONCLUDES, AND FROM WHAT. Every verdict here is derived from a value that was
OBSERVED, never from something not happening — a check that concludes "safe" because an
alarm did not arrive can be manufactured by breaking the machinery, while a check that
reads a number has to have the number produced for it. The three observables:

  A. systemd, the clock's arming:  ActiveState + LastTriggerUSec of astryx-pulse.timer.
     Says whether the timer is armed and when it last fired. Readable unprivileged.
  B. systemd, the tick's outcome:  Result of astryx-pulse.service.
  C. the database, the tick's WORK: max(last_eval) over enabled triggers. A timer can
     fire perfectly while every tick dies — that is exactly what happened on 2026-07-26
     13:39-13:42 (postgres refusing connections; the timer's own record stayed spotless).

A and C are independent and cover different halves: A cannot see a barren tick, C cannot
tell a stopped clock from an empty trigger table. Neither alone is the guard.

WHO READS THE ALARM, AND DOES THE READER SURVIVE THE CONDITION. The rung ladder is built
around that question, not around severity:
  * rung 1 (age > FLOOR_S) -> seed. He holds passwordless sudo and `systemctl start` is
    a one-liner; while the pulse is down the agents and their ears are untouched, so a
    wire row still reaches him. This is the cheap fix and it costs the owner nothing.
  * rung 2 (age > OWNER_ESC_S) -> the OWNER, un-threaded, which bridges/whatsapp.py
    delivers to his phone (listen() on to_agent='owner', a long-running systemd service
    outside both the pulse's and every agent's failure domain). This rung exists because
    of the case rung 1 cannot serve: seed dark. Half an hour of a stopped clock with no
    one having restarted it means either he did not read it or he cannot, and the second
    is the 88-hour case. DISCHARGED 2026-08-20 (forge, plan-2457 msg 13041, citing 12554),
    and worth stating precisely because the transfer is narrower than it looks: what was
    proven end to end is the DOORBELL FALLBACK, not a route. An un-threaded owner-bound row
    takes `routes()[from_agent] or routes()[HOME_AGENT]`, and neither `pulse` nor
    `pulse-watch` has a route of its own (verified: the only routed agents are canopus,
    gemini, seed), so both land on the identical HOME_AGENT branch — the proof transfers
    because the code path is literally the same one, not because anyone tested this sender.
    Two conditions carry it, and if either changes the discharge lapses: (i) as of 9a38f86
    the fallback is pinned to HOME_AGENT BY NAME rather than positionally, so reordering
    routes-whatsapp.json can no longer silently move it; (ii) the moment anyone gives
    `pulse-watch` a route of its own, this rung stops using the proven fallback and takes
    an untested per-sender branch. Rung 1 remains the load-bearing one regardless.
  * re-nag: an open ladder (bit_length), never warn-once. A stopped clock is a CONDITION,
    not an event, and a condition that dedups to silence is the failure this org keeps
    re-learning. Sentinel for "never reported" is -1, deliberately NOT 0, so the lowest
    real rung stays reachable — a first rung that collides with the never-seen default is
    a guard that cannot announce the ARRIVAL of the thing it exists to catch.

THE RECOVERY REPORT is the half nothing else in this org can produce, and it works for
the windows where no live alarm was ever possible. This script's OWN gap is evidence: if
the previous stamp is older than the watchdog's own cadence allows, then the watchdog was
not running either — host down, or its timer stopped — and the org was blind for that
whole window with no record anywhere that it happened. The 6.6h and 8.3h outages above
were never reported to anyone. On the first healthy run after such a gap, this says how
long the org was blind and how many evaluations collapsed, once, then goes quiet.

BOUNDARIES, stated rather than discovered later:
  * postgres unreachable -> this cannot read C and cannot write ANY alarm. Nothing inside
    the org can, in that state; the wire is the only actuator anyone here has. It records
    BLIND_DB to the stamp (a local file, no DB needed) and exits nonzero, so the window is
    reported retroactively on recovery and systemd carries a failed unit in the meantime.
  * host down -> no live alarm is possible from inside the host, by construction. Covered
    only by the recovery report. An external reader is the real answer and is not built.
  * this script's own timer never enabled -> the stamp is never written, and
    triggers/scout/clock_stamp.py is red from the first tick. That is the failure mode
    astryx-check.timer is sitting in today (disabled, LastTriggerUSec empty since it was
    generated), which is exactly why the pulse-side reader is not optional.

Run by hand any time, read-only unless it decides to fire: venv/bin/python nucleus/pulse_watch.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAMP = Path(os.environ.get("PULSE_WATCH_STAMP", REPO / "var" / "pulse_watch.json"))

# --- calibrated constants; every one of them cites the measurement in the docstring ---
FLOOR_S = int(os.environ.get("PULSE_WATCH_FLOOR_S", 600))     # 4.6x the worst spontaneous gap
OWNER_ESC_S = int(os.environ.get("PULSE_WATCH_OWNER_S", 1800))  # rung 2: seed had 20m and didn't
CADENCE_MULT = 4          # floor must also clear 4 evaluation cadences of the fastest trigger
WATCH_PERIOD_S = int(os.environ.get("PULSE_WATCH_PERIOD_S", 300))   # this script's own timer
SELF_GAP_S = WATCH_PERIOD_S * 3   # our own gap past this = we were not running = blind window
NEVER = -1                # sentinel; NOT 0, so rung 0 stays a reachable, announceable arrival

# TEST SEAMS. Every one defaults to the production value, so the deployed behaviour is
# byte-identical to having no seam; what they buy is that this guard can be pointed at
# REAL substrate in a state the live clock is not in (an inactive unit that actually
# exists on this host) instead of being graded only against a fixture of my own making.
UNIT = os.environ.get("PULSE_WATCH_UNIT", "astryx-pulse-watch.service")  # OUR own unit
TIMER = os.environ.get("PULSE_WATCH_TIMER", "astryx-pulse.timer")
SERVICE = os.environ.get("PULSE_WATCH_SERVICE", "astryx-pulse.service")
ACTOR = os.environ.get("PULSE_WATCH_ACTOR", "seed")   # who can `systemctl start`


def dsn() -> str:
    return next(l.split("=", 1)[1].strip()
                for l in (REPO / ".env").read_text().splitlines()
                if l.startswith("ASTRYX_DSN="))


def now() -> datetime:
    return datetime.now(timezone.utc)


def provenance() -> str:
    """systemd or hand — decided by the cgroup this process is ACTUALLY in.

    THE STAMP MUST SAY WHO WROTE IT, and I learned that twice on this one build. First:
    I ran this script by hand to grade it, which wrote a fresh stamp, which made
    triggers/scout/clock_stamp.py read HEALTHY while the unit was not deployed at all —
    the guard reporting green off evidence my own testing manufactured.

    Then the fix was wrong in a way I could not have guessed and steward had already paid
    for (msg 12935, transferred unprompted from his own check_stamp). I derived provenance
    from INVOCATION_ID, which systemd sets for a unit AND EVERY CHILD INHERITS. Every
    resident body on this host runs inside astryx-residents.service, so my hand-typed run
    from a resident shell stamped itself `by=systemd` and set last_systemd_run —
    CERTIFYING AN AUTOMATION THAT DID NOT EXIST, and silencing the loudest arm of the
    reader, the one carrying the sudo line that would have deployed it. Reproduced live
    2026-08-20 01:49: INVOCATION_ID=36a83c8f… present in my own shell's environ.

    An inherited marker names an ANCESTOR, not the actor. /proc/self/cgroup names the unit
    the process is in — for this shell, `0::/system.slice/astryx-residents.service`, which
    is exactly the wrong answer that the environment variable could not distinguish. So the
    predicate is membership in the EXPECTED unit, not the mere presence of a marker.

    Unreadable or mismatched resolves to "hand", deliberately: that is the direction where
    the guard nags about automation it cannot see rather than vouching for automation that
    is absent.
    """
    try:
        cg = Path(os.environ.get("PULSE_WATCH_CGROUP", "/proc/self/cgroup")).read_text()
    except Exception:
        return "hand"
    return "systemd" if UNIT in cg else "hand"


# ------------------------------------------------------------------ observable A + B
def systemd(unit: str, props: list[str]) -> dict[str, str]:
    """systemctl show, unprivileged. Missing/blank values stay ABSENT from the dict —
    never defaulted — so the caller must decide what unknown means instead of silently
    inheriting a benign-looking zero."""
    try:
        r = subprocess.run(["systemctl", "show", unit] + [f"-p{p}" for p in props],
                           capture_output=True, text=True, timeout=15)
    except Exception:
        return {}
    if r.returncode != 0:
        return {}
    out = {}
    for line in r.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                out[k] = v.strip()
    return out


def parse_stamp_ts(v: str) -> datetime | None:
    """systemd prints 'Thu 2026-08-20 06:38:00 PKT' — local wall clock with a tz ABBREV
    that %Z cannot round-trip. Parse the naive part and attach the host's own offset,
    which is what the abbreviation meant."""
    try:
        body = " ".join(v.split()[1:4])           # drop weekday, drop tz token
        naive = datetime.strptime(body[:19], "%Y-%m-%d %H:%M:%S")
        return naive.astimezone()                  # host local tz -> aware
    except Exception:
        return None


# ------------------------------------------------------------------ observable C
def db_state() -> tuple[datetime | None, int, float | None, str | None]:
    """(newest last_eval, enabled trigger count, fastest cadence in seconds, error)."""
    try:
        import psycopg
        from croniter import croniter
        with psycopg.connect(dsn(), autocommit=True, connect_timeout=10) as conn:
            rows = conn.execute(
                "SELECT schedule, last_eval FROM triggers WHERE enabled").fetchall()
    except Exception as e:
        return None, 0, None, str(e)[:200]
    if not rows:
        return None, 0, None, None
    newest = max((r[1] for r in rows if r[1]), default=None)
    base = datetime.now().astimezone()
    fastest = None
    for sched, _ in rows:
        try:
            c = croniter(sched, base)
            a = c.get_next(datetime); b = c.get_next(datetime)
            gap = (b - a).total_seconds()
        except Exception:
            continue
        if gap > 0 and (fastest is None or gap < fastest):
            fastest = gap
    return newest, len(rows), fastest, None


# ------------------------------------------------------------------ the verdict
def verdict(t: dict, s: dict, newest, n_trig: int, fastest, db_err) -> tuple[str, str, float]:
    """(code, human sentence, age in seconds the ladder is keyed on).

    Order matters: the loudest UNKNOWN comes first. A detector that cannot see must
    read as WATCHED, never as OK — the fail-safe polarity this org settled on."""
    if db_err:
        return "BLIND_DB", f"cannot reach postgres to read the trigger table: {db_err}", 0.0
    # BLINDNESS BEFORE STATE, and LoadState is the only field that can tell them apart.
    # `systemctl show` answers rc=0 for a unit systemd has NEVER HEARD OF and prints
    # ActiveState=inactive for it — a value manufactured by the default, not observed of
    # anything. Reading that as "the clock is stopped" is a false RED with a remedy that
    # cannot work (`systemctl start` a unit that isn't there), and it is exactly how a
    # rename or a drift between this constant and the deployed unit name would present.
    # Caught 2026-08-20 by running this guard against a deliberately absent unit; it had
    # already been written, reviewed by me, and would have shipped. LoadState=loaded is a
    # fact about a real unit, so unknown reads as BLIND — loud — and never as a verdict.
    if not t:
        return "BLIND_SYSTEMD", (f"`systemctl show {TIMER}` returned nothing — this host's "
                                 "systemd cannot be read, so the clock's arming is unknown"), 0.0
    load = t.get("LoadState", "")
    if load != "loaded":
        return "BLIND_SYSTEMD", (
            f"systemd reports {TIMER} as LoadState={load or 'unreadable'} — the unit this "
            f"guard was pointed at does not exist on this host (renamed? never installed?). "
            f"The clock's state is UNKNOWN, not stopped: do not read this as a diagnosis"), 0.0
    if n_trig == 0:
        return "TRIGGERS_EMPTY", ("the pulse is running but NO trigger is enabled — every "
                                  "guard in the org is switched off at the table"), 0.0

    active = t.get("ActiveState", "")
    last_fire = parse_stamp_ts(t.get("LastTriggerUSec", ""))
    floor = max(FLOOR_S, CADENCE_MULT * (fastest or 0))
    clock_age = (now() - last_fire).total_seconds() if last_fire else None
    eval_age = (now() - newest).total_seconds() if newest else None

    if active != "active":
        onboot = t.get("UnitFileState", "")
        return "CLOCK_STOPPED", (
            f"{TIMER} is {active or 'unreadable'} (unit file {onboot or 'unknown'}) — the "
            f"org's clock is NOT ARMED and will not restart itself"
            + ("; it is DISABLED, so a reboot will not bring it back either. "
               if onboot == "disabled" else ". ")
            + "Last tick "
            + (f"{clock_age/60:.0f} min ago." if clock_age is not None else "unknown.")
            + f" Remedy: sudo systemctl start {TIMER}"), (clock_age or floor + 1)

    if clock_age is None:
        return "CLOCK_NEVER", (f"{TIMER} is active but has NEVER fired (LastTriggerUSec is "
                               "empty) — armed and mute"), floor + 1
    if clock_age > floor:
        return "CLOCK_STALE", (
            f"{TIMER} says active but its last tick was {clock_age/60:.0f} min ago "
            f"(floor {floor/60:.0f} min) — armed, not firing"), clock_age
    if eval_age is None:
        return "EVAL_NEVER", ("the clock is ticking but no enabled trigger has ever been "
                              "evaluated — ticks are reaching nothing"), floor + 1
    if eval_age > floor:
        return "TICK_BARREN", (
            f"the clock is ticking ({clock_age/60:.0f} min ago) but the newest trigger "
            f"evaluation is {eval_age/60:.0f} min old (floor {floor/60:.0f} min) — every "
            f"tick is dying before it does any work. Service result: "
            f"{s.get('Result', 'unreadable')}. Check: journalctl -u {SERVICE} -n 20"), eval_age

    return "OK", (f"clock armed, last tick {clock_age:.0f}s ago, newest evaluation "
                  f"{eval_age:.0f}s ago, {n_trig} triggers enabled"), 0.0


# ------------------------------------------------------------------ actuation
def wire(rows: list[tuple[str, str]]) -> None:
    """Write alarm rows. Best-effort by design: if this fails the DB is down, which is
    the one state where nothing in this org can speak at all."""
    if not rows:
        return
    try:
        import psycopg
        with psycopg.connect(dsn(), autocommit=True, connect_timeout=10) as conn:
            for to, body in rows:
                conn.execute(
                    "INSERT INTO messages (from_agent, to_agent, intent, body) "
                    "VALUES ('pulse-watch', %s, 'trigger', %s)", (to, body[:3000]))
    except Exception as e:
        print(f"pulse_watch: alarm write failed: {e}", file=sys.stderr)


def load() -> dict:
    try:
        return json.loads(STAMP.read_text())
    except Exception:
        return {}


def save(d: dict) -> None:
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    tmp = STAMP.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True))
    tmp.replace(STAMP)                      # atomic: a reader never sees a half stamp


def band(age_s: float, floor: float) -> int:
    """Open ladder. rung 0 is the ARRIVAL and must be reachable — see NEVER = -1."""
    if age_s < floor:
        return NEVER
    return int(max(1, age_s // floor)).bit_length() - 1


def main() -> int:
    prev = load()
    t = systemd(TIMER, ["LoadState", "ActiveState", "UnitFileState",
                        "LastTriggerUSec", "NextElapseUSecRealtime"])
    s = systemd(SERVICE, ["Result", "ExecMainExitTimestamp"])
    newest, n_trig, fastest, db_err = db_state()
    code, sentence, age = verdict(t, s, newest, n_trig, fastest, db_err)
    floor = max(FLOOR_S, CADENCE_MULT * (fastest or 0))
    ts = now()

    # Carried forward across by-hand runs: the newest timer-driven run we have ever seen.
    # A human grading this script must not be able to make the deployment look alive.
    sd_run = ts.isoformat() if provenance() == "systemd" else prev.get("last_systemd_run")

    out: list[tuple[str, str]] = []

    # --- 1. the recovery report: OUR OWN gap is the evidence the org was blind ---
    # This is the only reader of a window in which nothing inside the host could speak.
    last_run = prev.get("last_run")
    if last_run:
        try:
            gap = (ts - datetime.fromisoformat(last_run)).total_seconds()
        except Exception:
            gap = 0.0
        if gap > SELF_GAP_S:
            out.append((ACTOR, (
                f"[pulse-watch] BLIND WINDOW, retroactive — nothing was watching the org's "
                f"clock for {gap/3600:.1f}h ({last_run} -> {ts.isoformat(timespec='seconds')}). "
                f"This watchdog itself was not running, so the host was down or its timer was "
                f"stopped; either way EVERY trigger in the org was unevaluated or collapsed to "
                f"a single catch-up tick for that whole window, and no other surface records "
                f"that it happened. {n_trig} triggers enabled. Clock is healthy now"
                f" ({sentence})." if code == "OK" else
                f"[pulse-watch] BLIND WINDOW of {gap/3600:.1f}h, and the clock is STILL "
                f"unhealthy: {sentence}")))

    # --- 2. the live alarm ---
    if code == "OK":
        if prev.get("since"):
            out.append((ACTOR, (
                f"[pulse-watch] RECOVERED — {prev.get('code')} cleared. The clock was "
                f"unhealthy from {prev['since']} to {ts.isoformat(timespec='seconds')}; "
                f"every guard in the org was silent for that window and its silence meant "
                f"nothing. Now: {sentence}")))
        state = {"last_run": ts.isoformat(), "by": provenance(), "code": code,
                 "note": sentence, "since": None, "rung": NEVER, "owner_rung": NEVER,
                 "last_systemd_run": sd_run}
    else:
        since = prev.get("since") if prev.get("code") == code else None
        since = since or ts.isoformat()
        try:
            standing = (ts - datetime.fromisoformat(since)).total_seconds()
        except Exception:
            standing = 0.0
        # BLIND_* and TRIGGERS_EMPTY carry no meaningful clock age; the ladder runs on how
        # long WE have been saying it, which is the honest clock for an unknown.
        keyed = age if age else standing
        rung = band(max(keyed, standing), floor)
        prev_rung = prev.get("rung", NEVER) if prev.get("code") == code else NEVER
        prev_owner = prev.get("owner_rung", NEVER) if prev.get("code") == code else NEVER
        owner_rung = band(max(keyed, standing), OWNER_ESC_S)

        if rung > prev_rung:
            out.append((ACTOR, (
                f"[pulse-watch] {code} — {sentence}\n"
                f"Standing {standing/60:.0f} min. While this holds, EVERY trigger in the org "
                f"is unevaluated and every guard's silence proves nothing. I am outside the "
                f"pulse on my own timer, which is why you are hearing this at all.")))
        if owner_rung > prev_owner and code in ("CLOCK_STOPPED", "CLOCK_STALE",
                                                "CLOCK_NEVER", "TICK_BARREN"):
            out.append(("owner", (
                f"ASTRYX: the org's clock has been stopped for {standing/60:.0f} minutes and "
                f"no one has restarted it. Every automated check in the org is silent, and "
                f"that silence currently means nothing.\n\n{sentence}\n\n"
                f"One line fixes it: sudo systemctl start {TIMER}")))
        state = {"last_run": ts.isoformat(), "by": provenance(), "code": code,
                 "note": sentence, "since": since, "rung": max(rung, prev_rung),
                 "owner_rung": max(owner_rung, prev_owner),
                 "last_systemd_run": sd_run}

    save(state)
    wire(out)
    print(f"{code}: {sentence}" + (f"  [{len(out)} alarm(s)]" if out else ""))
    return 1 if code.startswith("BLIND") else 0


if __name__ == "__main__":
    sys.exit(main())
