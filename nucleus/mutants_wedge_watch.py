"""Authored mutants for triggers/seed/wedge_watch.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py nucleus/mutants_wedge_watch.py

THE LIST IS THE JUDGEMENT, WHICH IS WHY IT IS AUTHORED AND NOT GENERATED. Each entry is a
way this classifier could plausibly be wrong — most of them are ways it HAS been wrong, on
this file, in the last twenty-four hours. A generic mutator would emit mostly equivalent
mutants and drown that signal; this list is reviewable precisely because someone had to
claim each entry is a real risk.

Two of these (M4, M3) went uncaught when the recovered-branch assertions were first
written, and finding that is what produced the tool. Keep them: a mutant that once slipped
through is the most valuable kind, because it documents a hole that actually existed rather
than one somebody imagined.

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list. Every mutant being caught
means the authored risks are probed and nothing more — see the probe's docstring on why it
may never report an assertion as vacuous.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "triggers" / "seed" / "wedge_watch.py"
ORACLE = REPO / "nucleus" / "test_wedge_watch.py"
ENV = "WEDGE_WATCH_SRC"

MUTANTS = {
    # The pre-fix two-state classifier. Every recovered outage silently becomes a
    # bookkeeping gap, and the alarm affirmatively says "they were working" of an agent
    # that was down 32h. (steward, msg 4236.)
    "M1 rate gate disabled (pre-fix two-state)":
        ("WORKING_RATE = 1.0", "WORKING_RATE = 0.0"),

    # Span measured from now rather than across the drop run. Inflates every span, so a
    # short run can clear the min-span floor purely by being old.
    "M2 span measured from NOW, not across the run":
        ('span_h = max(0.001, (r["newest"] - r["oldest"]).total_seconds() / 3600.0)',
         'span_h = max(0.001, (now - r["oldest"]).total_seconds() / 3600.0)'),

    # The discriminator reading the wrong marker. steps_after is >0 for BOTH a recovered
    # outage and a working agent, so this cannot separate them — it was the original bug.
    "M3 rate uses steps_AFTER instead of steps_inside":
        ('rate = (r.get("steps_inside") or 0) / span_h',
         'rate = (r.get("steps_after") or 0) / span_h'),

    # Drop the minimum-span floor. This one SURVIVED the first version of the recovered
    # assertions, because the fixture aimed at it was excluded by the rate gate before the
    # floor was ever consulted — a fixture excluded by the wrong clause tests the wrong
    # clause. Kept as the standing regression for that mistake.
    "M4 minimum-span floor removed":
        ("if rate < WORKING_RATE and span_h >= min_quiet_h:",
         "if rate < WORKING_RATE:"),

    # Fall-through: a row could be filed in two lists at once.
    "M5 no `continue` — a row can be double-filed":
        ('                gaps.append((agent, r["drops"]))\n            continue\n',
         '                gaps.append((agent, r["drops"]))\n'),

    # A single dropped wake becomes a state. This is the false-positive wall the guard's
    # timidity was bought with.
    "M6 min_drops ignored — one dropped wake is a state":
        ('if r["drops"] < min_drops:', "if False:"),

    # Alarm on agents with no body, which is agent_dark's subject and a different remedy
    # (spawn, not kill-then-spawn). Two guards shouting different fixes at one incident.
    "M7 body check dropped — alarms on dead agents too":
        ("if agent not in bodies:", "if False:"),

    # The wedged branch, which the first mutant set never probed at all — every mutant
    # above targets the steps_after>0 path, so 11 of 21 assertions looked unprobed purely
    # because nothing tested their branch. Added to close that bias in the SET, not in
    # the oracle.
    "M8 wedged threshold inverted":
        ("if quiet_h >= min_quiet_h:", "if quiet_h <= min_quiet_h:"),

    "M9 wedged branch never fires":
        ("            wedged.append((agent, r[\"drops\"], quiet_h))",
         "            pass"),

    # A never-stepped agent (last_step IS NULL) treated as quiet-forever rather than
    # skipped — would alarm on an agent that has no step history at all.
    "M10 null last_step no longer skipped":
        ("        if last is None:\n            continue",
         "        if last is None:\n            pass"),
}
