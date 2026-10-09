"""Authored mutants for triggers/steward/stale_goals.py — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_stale_goals.py

THE LIST IS THE JUDGEMENT. Every entry below is a way THIS guard has already failed, or
the way its siblings have — restored one line at a time to ask whether the new oracle
would notice. M1 is the crash that produced the oracle in the first place, and it is the
only one where the guard fails LOUDLY; every other mutation here makes the metabolism
patrol quieter while it keeps returning cleanly, which is the direction that costs weeks.

NOT A CLAIM OF COMPLETENESS: coverage is bounded by this list, and the probe reports
CAUGHT or NOT PROBED, never "vacuous". The subject is gitignored (`triggers/`), so in a
clean checkout this file names an estate the repo deliberately does not carry —
tests/test_mutants_wellformed.py classifies that rather than assuming it.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "triggers" / "steward" / "stale_goals.py"
ORACLE = REPO / "tests" / "test_stale_goals.py"
ENV = "STALE_GOALS_SRC"

MUTANTS = {
    # The live crash, restored: `extract(epoch ...)` is numeric -> decimal.Decimal, and
    # Decimal / float raises. The epoch path (Decimal // int) survives it, which is why
    # this hid for weeks in a branch no goal had reached yet.
    "M1 the Decimal age is not coerced (the four-tick production crash)":
        # re-anchored 2026-10-09 (running-time age): the coercion now sits inside the discount;
        # dropping it makes Decimal - float raise — the same production crash this mutant pins
        ('        age_s = max(0.0, float(g["age_s"] or 0) - dark_s)   # RUNNING time, not wall time',
         '        age_s = max(0.0, (g["age_s"] or 0) - dark_s)   # RUNNING time, not wall time'),

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

    # RUNNING TIME (2026-10-09, host off 8.75d → six false "9 dead epochs"). The discount
    # dropped: wall-clock decay is back, and an outage reads as neglect again.
    "D1 host-down time is not discounted (wall-clock decay returns)":
        ('        age_s = max(0.0, float(g["age_s"] or 0) - dark_s)   # RUNNING time, not wall time',
         '        age_s = float(g["age_s"] or 0)   # RUNNING time, not wall time'),

    # The threshold dropped: every inter-message gap reads as darkness, so a quiet-but-UP
    # org (gaps up to the 4h heartbeat) is discounted too — the quiet direction.
    "D2 every gap counts as darkness (the DARK_GAP threshold is lost)":
        ("WHERE ts - prev > interval '{DARK_GAP}'", "WHERE ts - prev > interval '0 seconds'"),

    # Darkness from BEFORE the goal's last evidence is subtracted too, so a goal that shipped
    # after an outage is credited with time it never spent waiting.
    "D3 darkness before the last evidence is discounted":
        ("SELECT sum(extract(epoch from (dk.b - greatest(dk.a, e.since)))) AS dark_s",
         "SELECT sum(extract(epoch from (dk.b - dk.a))) AS dark_s"),

    # Both dedup sets accumulate goals that have left the board, so a goal that goes
    # terminal and later returns to play inherits a dead receipt instead of a full ladder.
    "M6 dedup state is never healed for goals that left the board":
        ('    ctx.state["levels"] = {k: v for k, v in next_levels.items() if k in live}',
         '    ctx.state["levels"] = {**reported, **next_levels}'),
}
