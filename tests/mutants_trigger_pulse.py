"""Authored mutants for plan-12214's rules in src/astryx/pulse/pulse.py. venv/bin/python devtools/mutation_probe.py tests/mutants_trigger_pulse.py"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "pulse" / "pulse.py"
ORACLE = REPO / "tests" / "test_trigger_tool.py"
ENV = "PULSE_SRC"
TIMEOUT = 400

MUTANTS = {
    "this code ticks on a lagging database":
        ('        if not schema_ready(conn):\n', '        if False:\n'),
    "a lagging database is journal-only":
        ('            say(CANARY_TO, "[trigger schema pending]', '            (lambda *a, **k: 0)(CANARY_TO, "[trigger schema pending]'),
    "a one-shot's clock moves at the claim (a crash loses the deadline)":
        ('                if t["once"] and t["kind"] == "heartbeat":     # its evaluation', '                if False:     # its evaluation'),
    "a one-shot isn't retired":
        ("""if once and not conn.execute("UPDATE triggers SET off_reason='fired' WHERE id=%s AND off_reason IS NULL \"""",
         """if once and not conn.execute("UPDATE triggers SET note=note WHERE id=%s AND off_reason IS NULL \""""),
    "the double-fire guard is gone":
        ("WHERE id=%s AND off_reason IS NULL \"\n", "WHERE id=%s \"\n"),
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
        ("""conn.execute("UPDATE triggers SET off_reason='vanished' WHERE agent=%s AND name=%s",""",
         """conn.execute("UPDATE triggers SET note=note WHERE agent=%s AND name=%s","""),
}
