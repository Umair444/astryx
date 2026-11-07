"""Authored mutants for src/astryx/pulse/trigger_tool.py (plan-12214). venv/bin/python devtools/mutation_probe.py tests/mutants_trigger_tool.py"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "pulse" / "trigger_tool.py"
ORACLE = REPO / "tests" / "test_trigger_tool.py"
ENV = "TOOL_SRC"
TIMEOUT = 400

MUTANTS = {
    "a one-field set loses the check (F1a)":
        ('sql = a.get("sql") if a.get("sql") else (row["check_src"] if row else None)', 'sql = a.get("sql")'),
    "a note edit moves the clock":
        ('next_fire = at or (_now() if check_changed or clock_changed else row["next_fire"])', 'next_fire = at or _now()'),
    "a note edit wipes the watch's memory":
        ('state = {} if state_reset else (row["state"] if row else {})', 'state = {}'),
    "a changed check keeps its memory":
        ('state = {} if state_reset else (row["state"] if row else {})', 'state = (row["state"] if row else {})'),
    "a changed `on` keeps its memory":
        ('state_reset = check_changed or (row and a.get("on") and a["on"] != row["watch"])', 'state_reset = check_changed'),
    "a note edit revives a fired row":
        ('(reason == "fired" and (check_changed or clock_changed))', '(reason == "fired")'),
    "a set never re-arms a fired row":
        ('(reason == "fired" and (check_changed or clock_changed))', 'False'),
    "kind can change":
        ('    if row and row["kind"] != kind:', '    if False:'),
    "once and renag go together":
        ('    if a.get("once") and a.get("renag") not in (None, ""):', '    if False:'),
    "at takes a past time":
        ("    if at <= _now():", "    if False:"),
    "at with sql is accepted":
        ('    if a.get("at") and a.get("sql"):', '    if False:'),
    "churn isn't told at set":
        ('    return _echo(_row(conn, agent, name), count) + warn', '    return _echo(_row(conn, agent, name), count)'),
    "no warning that a stuck row goes quiet":
        ('"no renag: a row still present fires once, and a stuck row then goes quiet. Pass renag to re-fire it"', '""'),
    "a query failure isn't taught":
        ('A watch takes one read-only SELECT, VALUES or "', 'This can\'t "'),
    "a python write drops a function unasked":
        ('        if unnamed:\n', '        if False:\n'),
    "a bad file is written anyway":
        ('            raise Refuse(f"this file doesn\'t load, so nothing was written: {found}', '            print(f"this file doesn\'t load, so nothing was written: {found}'),
    "the temp file is left behind":
        ('        tmp.unlink(missing_ok=True)\n', '        pass\n'),
    "validation runs from another directory":
        ('tmp = directory / f".{name}.{os.getpid()}.tmp"', 'tmp = directory.parent / f".{name}.{os.getpid()}.tmp"'),
    "the temp file matches the pulse's glob":
        ('tmp = directory / f".{name}.{os.getpid()}.tmp"', 'tmp = directory / f"{name}_{os.getpid()}_tmp.py"'),
    "a path name gets through":
        ('    if not NAME.match(name) or not AGENT.match(agent):\n        raise Refuse(f"name={a.get(\'name\')!r}', '    if False:\n        raise Refuse(f"name={a.get(\'name\')!r}'),
    "a tombstone survives a set":
        ('    _tomb_clear(agent, names)\n', ''),
    "enable overrides the stand-down":
        ('    if r in fixes:\n', '    if False:\n'),
    "retire ends a stand-down":
        ('    if t["off_reason"] == "standdown":\n        raise Refuse', '    if False:\n        raise Refuse'),
    "retire leaves no tombstone":
        ('        tomb.write_text(f"{_now().isoformat()} retired by the trigger tool\\n")\n', '        pass\n'),
    "enable leaves the tombstone":
        ('    if t["kind"] == "python":\n        _tomb_clear(agent, [t["name"]])\n', ''),
    "enable keeps storm's count":
        ('state = {k: v for k, v in (t["state"] or {}).items() if k != "churn"}', 'state = t["state"] or {}'),
    "show hides a shed deadline":
        ('        lines.append("due, waiting on quota pressure")\n', '        pass\n'),
    "another agent's row is yours":
        ('"SELECT * FROM triggers WHERE agent=%s AND name=%s", (agent, name))', '"SELECT * FROM triggers WHERE %s<>\'\' AND name=%s", (agent, name))'),
    "test on python runs it unasked":
        ('        if a.get("run"):\n', '        if True:\n'),
    "the template is missing from the refusal":
        ('A trigger file looks like:\\n{TEMPLATE}")\n        for t', 'A trigger file looks like nothing")\n        for t'),
}
