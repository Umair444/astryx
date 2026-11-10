"""Authored mutants for plan-12214's rules in src/astryx/pulse/pulse.py. venv/bin/python devtools/mutation_probe.py tests/mutants_trigger_pulse.py"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "pulse" / "pulse.py"
ORACLE = REPO / "tests" / "test_trigger_tool.py"
ENV = "PULSE_SRC"
TIMEOUT = 400

MUTANTS = {
    "a one-shot's clock moves at the claim (a crash loses the deadline)":
        ('                if t["once"] and t["kind"] == "heartbeat":     # its evaluation', '                if False:     # its evaluation'),
    "a one-shot isn't retired":
        ("""if once and not conn.execute("UPDATE triggers SET off_reason='fired', enabled=false WHERE id=%s \"""",
         """if once and not conn.execute("UPDATE triggers SET note=note WHERE id=%s \""""),
    "the double-fire guard is gone":
        ('"AND enabled RETURNING id", (t["id"],)', '"RETURNING id", (t["id"],)'),
    "the one-shot's retire reads off_reason, not enabled (a2 B4's trip)":
        ('"AND enabled RETURNING id", (t["id"],)', '"AND off_reason IS NULL RETURNING id", (t["id"],)'),
    "a fired one-shot's enabled is left on":
        ("SET off_reason='fired', enabled=false WHERE id=%s", "SET off_reason='fired' WHERE id=%s"),
    "storm leaves enabled on":
        ('SET off_reason=%s, enabled=false WHERE id=%s", (t["_off"]', 'SET off_reason=%s WHERE id=%s", (t["_off"]'),
    "bad_schedule leaves enabled on":
        ("SET off_reason='bad_schedule', enabled=false WHERE id=%s", "SET off_reason='bad_schedule' WHERE id=%s"),
    "the tombstone's retire leaves enabled on":
        ("SET off_reason='retired', enabled=false WHERE agent=%s", "SET off_reason='retired' WHERE agent=%s"),
    "reconcile's upsert leaves enabled behind its reason":
        ("off_reason = {_ON}, enabled = ({_ON}) IS NULL", "off_reason = {_ON}"),
    "normalize doesn't clear a re-enabled row's reason":
        ('    conn.execute("UPDATE triggers SET off_reason=NULL, off_why=NULL WHERE enabled AND off_reason IS NOT NULL")\n', ''),
    "normalize classes every off row unknown":
        ("CASE WHEN kind = 'python' THEN 'vanished' WHEN note ILIKE", "CASE WHEN false THEN 'vanished' WHEN false AND note ILIKE"),
    "normalize turns rows on":
        ("WHERE NOT enabled AND off_reason IS NULL\")", "WHERE NOT enabled AND off_reason IS NULL\"); conn.execute(\"UPDATE triggers SET enabled=true WHERE off_reason='unknown'\")"),
    "the tick never normalizes":
        ("        normalize(conn)\n        py_ok = reconcile(conn)", "        py_ok = reconcile(conn)"),
    "an unread wake swallows a deadline":
        ('                    elif once:                     # a one-shot', '                    elif False:                     # a one-shot'),
    "a swallowed wake's rows are recorded as told (F1h)":
        ('                        if not sent and "_swallowed" in t:', '                        if False:'),
    "storm doesn't turn the row off":
        ('                    if t.get("_off") and "_swallowed" in t:', '                    if False:'),
    "a failing check burns the one-shot":
        ('once = bool(t.get("once")) and bool(fired) and not failed', 'once = bool(t.get("once")) and bool(fired)'),
    "a kind this can't run stays silent (F1b)":
        ('    raise ValueError(f"unknown kind {kind!r}")', '    return None, state, []  #'),
    "a late deadline doesn't say so":
        ('        return body + _lateness(t), state, []', '        return body, state, []'),
    "a watch isn't read-only":
        ('        conn.execute("SET TRANSACTION READ ONLY")\n', ''),
    "a watch has no time bound":
        ('        conn.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")\n', ''),
    "the cap isn't said":
        ('return names, rows[:cap], len(rows) > cap', 'return names, rows[:cap], False'),
    "reconcile revives a held python row":
        ("WHEN triggers.off_reason IN ('vanished', 'retired') THEN NULL", "WHEN true THEN NULL"),
    "reconcile leaves a restored file's row off":
        ("WHEN triggers.off_reason IN ('vanished', 'retired') THEN NULL", "WHEN triggers.off_reason = 'retired' THEN NULL"),
    "reconcile never clears bad_schedule":
        ("WHEN triggers.off_reason = 'bad_schedule' AND triggers.schedule <> %(s)s THEN NULL", "WHEN false THEN NULL"),
    "reconcile clears bad_schedule on an unchanged decorator":
        ("AND triggers.schedule <> %(s)s THEN NULL", "THEN NULL"),
    "a vanished function's row stays on":
        ("""conn.execute("UPDATE triggers SET off_reason='vanished', enabled=false WHERE agent=%s AND name=%s",""",
         """conn.execute("UPDATE triggers SET note=note WHERE agent=%s AND name=%s","""),
    "a vanished function's enabled is left on":
        ("SET off_reason='vanished', enabled=false WHERE agent=%s", "SET off_reason='vanished' WHERE agent=%s"),
}
