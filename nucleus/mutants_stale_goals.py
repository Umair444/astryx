"""Authored mutants for triggers/steward/stale_goals.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py nucleus/mutants_stale_goals.py

THE LIST IS THE JUDGEMENT. Every entry below is a way THIS guard has already failed, or
the way its siblings have — restored one line at a time to ask whether the new oracle
would notice. M1 is the crash that produced the oracle in the first place, and it is the
only one where the guard fails LOUDLY; every other mutation here makes the metabolism
patrol quieter while it keeps returning cleanly, which is the direction that costs weeks.

NOT A CLAIM OF COMPLETENESS: coverage is bounded by this list, and the probe reports
CAUGHT or NOT PROBED, never "vacuous". The subject is gitignored (`triggers/`), so in a
clean checkout this file names an estate the repo deliberately does not carry —
nucleus/test_mutants_wellformed.py classifies that rather than assuming it.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "triggers" / "steward" / "stale_goals.py"
ORACLE = REPO / "nucleus" / "test_stale_goals.py"
ENV = "STALE_GOALS_SRC"

MUTANTS = {
    # The live crash, restored: `extract(epoch ...)` is numeric -> decimal.Decimal, and
    # Decimal / float raises. The epoch path (Decimal // int) survives it, which is why
    # this hid for weeks in a branch no goal had reached yet.
    "M1 the Decimal age is not coerced (the four-tick production crash)":
        ('        age_s = float(g["age_s"] or 0)', '        age_s = g["age_s"] or 0'),

    # The ceiling that let goal 15 sit fourteen days after one escalation: with a cap, the
    # WORST state is the only one that can never re-nag, and severity is inverted.
    "M2 the decay ladder is capped, so the worst goals go silent first":
        ("        level = 0 if dead < 1 else dead.bit_length()",
         "        level = 0 if dead < 1 else min(dead.bit_length(), 2)"),

    # The positive allowlist over a free-text column with no CHECK constraint: a typo'd or
    # newly-invented state exits the patrol entirely instead of arriving loud.
    "M3 the state filter becomes a positive allowlist (unknown states vanish)":
        ('"WHERE g.state <> ALL(%s)", (list(TERMINAL),))',
         '"WHERE g.state = ANY(%s)", (["active", "proposed"],))'),

    # Recovery no longer re-arms: the stored level is the high-water mark rather than the
    # current one, so a goal that heals and relapses is deduped against its own history.
    "M4 the dedup level never falls, so a relapse is swallowed":
        ("        next_levels[gid] = level",
         "        next_levels[gid] = max(level, reported.get(gid, 0))"),

    # The stranded ladder degraded to flag-once-ever — the shape that predates the band and
    # the reason a 'proposed' goal could disappear from the patrol after a single mention.
    "M5 a stranded goal is flagged once, ever":
        ("                if band > stranded.get(gid, -1):",
         "                if gid not in stranded:"),

    # Both dedup sets accumulate goals that have left the board, so a goal that goes
    # terminal and later returns to play inherits a dead receipt instead of a full ladder.
    "M6 dedup state is never healed for goals that left the board":
        ('    ctx.state["levels"] = {k: v for k, v in next_levels.items() if k in live}',
         '    ctx.state["levels"] = {**reported, **next_levels}'),
}
