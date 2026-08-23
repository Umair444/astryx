"""Authored mutants for triggers/seed/service_deploy_drift.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_service_deploy_drift.py

WHY THIS FILE EXISTS RATHER THAN A LINE IN A COMMIT MESSAGE. The oracle's commit claims ten
mutants killed. That claim was produced by a throwaway script in a scratch directory, so as
written it was unreproducible by anyone but me on the night I ran it — a remedy asserted
rather than demonstrated, which is the defect the oracle itself exists to catch one level
down. Authored here, the claim is a command.

THE LIST IS THE JUDGEMENT. Each entry is a way this guard could plausibly be wrong, and
most are ways a guard of this shape HAS been wrong somewhere in this org: a ladder that
flattens into warn-once, a dedup that swallows a late joiner, a detector that downgrades
blindness to silence, a comparison anchored on the wrong clock.

TWO OF THESE ARE THE DESIGN, NOT DECORATION. M7 (directory-shaped closure) and M10 (mtime
instead of committed state) are the two implementations any reasonable person would reach
for first, and each convicts a service that is perfectly healthy — M10 is precisely seed's
constraint (a), the false red that would fire on every evening of shared-tree work. The
oracle carries both as inline counterexample arms as well, because a guard proven only
quiet on healthy input is indistinguishable from a guard that is simply quiet.

M8 IS KEPT FOR A REASON WORTH MORE THAN THE MUTANT. On the first sweep it died on a
TypeError inside scan() — a crash, not the parser assertion built for it — so the arm that
names the property was never exercised and the receipt claimed more than it had earned. The
oracle's parser block was reordered to run first so this dies on its own arm. A mutant
killed by an accident is the CAUGHT ≠ GUARDED trap; keep the mutant that exposed it.

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list — every mutant being caught
means the authored risks are probed and nothing more.
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = Path(os.environ.get("SERVICE_DEPLOY_DRIFT_SRC",
                              REPO / "triggers" / "seed" / "service_deploy_drift.py"))
ORACLE = REPO / "tests" / "test_service_deploy_drift.py"
ENV = "SERVICE_DEPLOY_DRIFT_SRC"

MUTANTS = {
    # The open ladder collapsed. A standing staleness then announces once and is silent
    # forever after — the exact way session_refresh let p1 degrade unobserved for 59h.
    "M1 rung ladder flattened to a constant":
        ("return max(0, int(age_h)).bit_length()", "return 1"),

    # The arrival sentinel inverted. A first sighting compares against a rung nothing can
    # exceed, so a service that is stale the day this guard is installed never announces.
    # Deliberately NO baseline-on-first-run for the same reason: baselining would have
    # adopted the 08-19 outage's four stale services as normal.
    "M2 arrival sentinel inverted (-1 -> 99)":
        ("if reported.get(unit, -1) < rung:", "if reported.get(unit, 99) < rung:"),

    # last_ok stamped before the blindness branch. The blind clock resets on every failed
    # scan, so BLIND_H is never reached and a permanently unreadable systemd is absorbed
    # forever as a transient — the guard goes quiet in exactly the state it must shout in.
    "M3 last_ok stamped even while blind":
        ("    if verdict is DRIFT:",
         '    ctx.state["last_ok"] = now.isoformat()\n    if verdict is DRIFT:'),

    # Oneshots dropped instead of listed. The population stops being auditable from the
    # alarm, so a unit that vanished from judgement for ANY reason reads as one that passed.
    "M4 oneshots silently dropped, not listed NOT JUDGED":
        ("            unjudged.append((unit, f\"{props.get('Type', '?')}/"
         "{props.get('ActiveState', '?')}\"))",
         "            pass"),

    # A closure git has never seen read as healthy. That is the fail-OPEN direction on the
    # unknown case: a detector's unknown must resolve to WATCHED, never to clear.
    "M5 un-committed closure read as healthy":
        ("        if newest is None:\n            unjudged.append((unit, why))\n"
         "            continue",
         "        if newest is None:\n            continue"),

    # Blindness downgraded to silence. "I cannot see whether the services are current" and
    # "every service is current" become the same output, which is the whole reason this
    # guard has a third verdict.
    "M6 DRIFT returns None — blindness reads as an all-clear":
        ('        blind = f"', "        return None\n        blind = f\""),

    # THE DESIGN, HALF ONE. gateway and geoloc share WorkingDirectory=bridges and neither
    # imports bridges/common.py; a directory-shaped root convicts both over a file neither
    # holds. This is the first implementation anyone reaches for.
    "M7 closure widened to the entry DIRECTORY":
        ("        files, degraded = _closure(entry, wd)",
         '        files, degraded = {p for p in entry.parent.glob("*.py")}, ""'),

    # An unparseable start time defaulting to now() instead of None. Every unit then looks
    # freshly started and nothing is ever stale. Kept for HOW it died the first time: on a
    # crash rather than on the parser arm — see the docstring.
    "M8 unparseable timestamp defaults to now()":
        ("    except ValueError:\n        return None\n    return naive.astimezone()",
         "    except ValueError:\n        return datetime.now()\n    return naive.astimezone()"),

    # The grace floor blown out past any real staleness. A threshold mutant, because the
    # oracle's grace fixtures are derived FROM GRACE_MIN and would follow it anywhere; what
    # kills this is the absolute 8h-gap arm, which is why that arm is written in world
    # units and not in multiples of the constant.
    "M9 GRACE_MIN blown out to 999999 minutes":
        ("GRACE_MIN = 60", "GRACE_MIN = 999999"),

    # THE DESIGN, HALF TWO, and seed's constraint (a) stated as code: staleness claimed
    # from file mtime rather than committed state. Convicts on any uncommitted edit, so the
    # guard reds through every evening of shared-tree work until people stop reading it.
    "M10 mtime instead of committed state (accuses a WIP edit)":
        ('rc, out, err = _run(["git", "-C", str(ROOT), "log", "-1", "--format=%ct", "--"] + rel)',
         'import os as _o; return (datetime.fromtimestamp('
         'max(_o.stat(p).st_mtime for p in paths), tz=timezone.utc), "") if paths else (None, "x")\n'
         '    rc, out, err = _run(["git", "-C", str(ROOT), "log", "-1", "--format=%ct", "--"] + rel)'),
}
