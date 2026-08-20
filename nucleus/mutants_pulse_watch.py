"""Authored mutants for nucleus/pulse_watch.py — run by mutation_probe.

    venv/bin/python nucleus/mutation_probe.py nucleus/mutants_pulse_watch.py

THE LIST IS THE JUDGEMENT. Each entry is a way this guard could plausibly be written
wrong or quietly undone, and the two at the top are not hypothetical: M1 is the file as
I actually wrote it before running it against a unit that does not exist, and M2 is the
sentinel collision that made my own spawn_code_drift's lowest rung structurally
unreachable for its whole life (measured 2026-08-15).

M7 SURVIVED THE FIRST RUN OF THIS SET, and that is why it is worth keeping. The oracle's
§5 drives the pulse-side reader with FIXTURE stamps, so nothing there could notice
pulse_watch lying about its own provenance — the probe found a hole no assertion covered,
in the exact mechanism I had added an hour earlier to stop the guard being fooled by my
own by-hand runs. Closed by §5g, which asserts on provenance() directly.

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "pulse_watch.py"
ORACLE = REPO / "nucleus" / "test_pulse_watch.py"
ENV = "PULSE_WATCH_SRC"

MUTANTS = {
    # THE PRE-FIX FILE. `systemctl show` answers rc=0 for a unit systemd has never heard
    # of and prints ActiveState=inactive, so without LoadState an absent unit is reported
    # as a stopped clock: a false RED whose remedy cannot work.
    "M1 no LoadState gate — an absent unit reads as a stopped clock (pre-fix)":
        ('    load = t.get("LoadState", "")\n    if load != "loaded":',
         '    load = t.get("LoadState", "")\n    if False:'),

    # The defect that cost spawn_code_drift its arrival band for its entire life: the
    # "never reported" sentinel colliding with the lowest real rung, so rung 0 can never
    # be greater than the default and the guard's FIRST word is the one it cannot say.
    "M2 sentinel collides with rung 0 (NEVER = 0)":
        ("NEVER = -1                # sentinel; NOT 0, so rung 0 stays a reachable, announceable arrival",
         "NEVER = 0                 # sentinel; NOT 0, so rung 0 stays a reachable, announceable arrival"),

    # Blindness reading as health — the polarity this whole family exists to refuse.
    "M3 unreachable postgres reports OK":
        ('        return "BLIND_DB", f"cannot reach postgres',
         '        return "OK", f"cannot reach postgres'),

    # A fixed floor accuses an org whose fastest guard runs hourly every ten minutes.
    "M4 floor stops deriving from the org's own cadence":
        ("    floor = max(FLOOR_S, CADENCE_MULT * (fastest or 0))\n    clock_age",
         "    floor = FLOOR_S\n    clock_age"),

    # The timer-only guard: looks complete, and is blind to the one failure that actually
    # happened on this host (2026-07-26, ticks firing perfectly into a refused database).
    "M5 barren ticks unreachable — trusts the timer alone":
        ("    if eval_age > floor:", "    if False:"),

    # Wakes the owner's phone the moment the condition arrives, spending the one channel
    # that has to still work on the day it matters.
    "M6 owner escalation collapses onto the seed floor":
        ('OWNER_ESC_S = int(os.environ.get("PULSE_WATCH_OWNER_S", 1800))',
         'OWNER_ESC_S = int(os.environ.get("PULSE_WATCH_OWNER_S", 600))'),

    # A hand run that claims to be a timer run makes an undeployed watchdog look
    # deployed to its own reader. Uncaught until §5g existed.
    "M7 provenance always claims systemd":
        ('    return "systemd" if UNIT in cg else "hand"',
         '    return "systemd"'),

    # THE LIVE DEFECT, kept as a standing regression. INVOCATION_ID is inherited by every
    # child of a unit, and every resident body on this host is one — so this version of the
    # line stamps a hand-typed run as automated and silences the deployment alarm. It read
    # as obviously correct for an hour and would have shipped.
    "M8 provenance from the INHERITED marker (the 2026-08-20 defect)":
        ('    return "systemd" if UNIT in cg else "hand"',
         '    return "systemd" if os.environ.get("INVOCATION_ID") else "hand"'),

    # Polarity: an unreadable cgroup must nag about automation it cannot see, never vouch
    # for automation that is absent.
    "M9 unreadable provenance vouches for the timer":
        ('    except Exception:\n        return "hand"\n    return "systemd" if UNIT in cg',
         '    except Exception:\n        return "systemd"\n    return "systemd" if UNIT in cg'),
}
