"""Authored mutants for src/astryx/pulse/trigger_tool.py (plan-12214), part 1 of 2. The 35 were one file until it ran 809-1100s
against land's 900s per-test cap (seed #65247); each half now lands at the default. venv/bin/python devtools/mutation_probe.py tests/mutants_trigger_tool.py"""
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
}
