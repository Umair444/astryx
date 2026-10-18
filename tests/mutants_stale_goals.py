"""Authored mutants for triggers/steward/stale_goals.py — run by devtools/mutation_probe.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_stale_goals.py

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
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)

# STALE_GOALS_STAGED: a staged copy of the gitignored body, probed before apply_receipt applies it
SUBJECT = Path(os.environ.get("STALE_GOALS_STAGED") or ESTATE / "triggers" / "steward" / "stale_goals.py")
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
        ('"WHERE g.state <> ALL(%s) "', '"WHERE g.state = ANY(ARRAY[\'active\',\'proposed\']) AND %s IS NOT NULL "'),

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
    "G1 a merge on main is not evidence (the term dropped from greatest())":
        ('coalesce(ev.last_evidence, g.ts), "\n        "                                    coalesce(mg.merged, g.ts)) AS since) e "',
         'coalesce(ev.last_evidence, g.ts)) AS since) e "'),
    "G2 a word-glued token credits an id (xplan-7777)":
        ('MERGE_RX = _re.compile(r"(?<![\\w-])(?:plan|goal)', 'MERGE_RX = _re.compile(r"(?:plan|goal)'),
    "G3 git unreadable is silent (the flag no longer says the term was unavailable)":
        ('    nogit = "" if log is not None else', '    nogit = "" if True else'),
    "G4 the FIRST commit seen wins, not the latest":
        ("            if gid not in out or t > out[gid]:", "            if gid not in out:"),
    "G5 git_log reads every branch (unreviewed side-branch commits credit a goal; a2 T2)":
        ('"log", "main", f"--since', '"log", "--all", f"--since'),
    "G6 git unreadable reads as an EMPTY log (silent), not None (a2 T3)":
        ("        return p.stdout if p.returncode == 0 else None", "        return p.stdout if p.returncode == 0 else \"\""),
    "G7 the default root is one level too high (a2 T4)":
        ("        repo = str(repo or _Path(__file__).resolve().parents[2])", "        repo = str(repo or _Path(__file__).resolve().parents[3])"),
    "G8 a future-dated commit reads fresh until then (no clamp to now())":
        ('"    SELECT CASE WHEN max(m.t) > now() THEN now() ELSE max(m.t) END AS merged "', '"    SELECT max(m.t) AS merged "'),
    "G9 the clamp is least(), which IGNORES NULLs: a goal with no merges reads now(), every goal fresh":
        ('"    SELECT CASE WHEN max(m.t) > now() THEN now() ELSE max(m.t) END AS merged "',
         '"    SELECT least(max(m.t), now()) AS merged "'),
    "W1 a workflow goal is nagged here too (the same silence told twice, to two recipients; seed #60111)":
        ('"WHERE g.state <> ALL(%s) "\n        "AND NOT EXISTS', '"WHERE g.state <> ALL(%s) "\n        "AND true OR NOT EXISTS'),
    "W2 ANY revision decides, not the latest (an old rev's live task keeps a finished workflow silent forever)":
        ('"                              ORDER BY w.rev DESC LIMIT 1) lw "', '"                              ) lw "'),
    "W3 a dropped task counts as open (a workflow whose rest is done never returns: shipped-and-unclosed unseen)":
        ("WHERE coalesce(t->'done' <> 'true'::jsonb, true) AND coalesce(t->'dropped' <> 'true'::jsonb, true)) \"",
         "WHERE coalesce(t->'done' <> 'true'::jsonb, true)) \""),
    "W4 a plan-less open task stands the goal down (watched by nobody; a1 #60185 G-1)":
        ('"  AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements', '"  AND true OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements'),
    "W5 done is cast ::boolean (a body with done \"x\" raises for EVERY goal; G-2)":
        ("WHERE coalesce(t->'done' <> 'true'::jsonb, true) AND coalesce(t->'dropped' <> 'true'::jsonb, true)) \"",
         "WHERE NOT coalesce((t->>'done')::boolean, false) AND coalesce(t->'dropped' <> 'true'::jsonb, true)) \""),
    "W6 a non-array tasks errors (jsonb_array_elements on an object)":
        ("jsonb_array_elements(CASE WHEN jsonb_typeof(lw.body->'tasks') = 'array' THEN lw.body->'tasks' ELSE '[]' END) t \"\n        \"                WHERE coalesce(t->'done' <> 'true'::jsonb, true) AND coalesce(t->'dropped' <> 'true'::jsonb, true)) \"",
         "jsonb_array_elements(lw.body->'tasks') t \"\n        \"                WHERE coalesce(t->'done' <> 'true'::jsonb, true) AND coalesce(t->'dropped' <> 'true'::jsonb, true)) \""),
}
