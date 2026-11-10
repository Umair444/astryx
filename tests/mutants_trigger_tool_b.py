"""Authored mutants for src/astryx/pulse/trigger_tool.py (plan-12214), part 2 of 2. The 35 were one file until it ran 809-1100s
against land's 900s per-test cap (seed #65247); each half now lands at the default. venv/bin/python devtools/mutation_probe.py tests/mutants_trigger_tool_b.py"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "pulse" / "trigger_tool.py"
ORACLE = REPO / "tests" / "test_trigger_tool.py"
ENV = "TOOL_SRC"
TIMEOUT = 400

MUTANTS = {
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
    "set leaves enabled behind its reason":
        ("off_reason=EXCLUDED.off_reason, enabled=EXCLUDED.enabled,", "off_reason=EXCLUDED.off_reason,"),
    "disable leaves enabled on":
        ("SET off_reason='held', off_why=%s, enabled=false WHERE", "SET off_reason='held', off_why=%s WHERE"),
    "retire leaves enabled on":
        ("SET off_reason='retired', off_why=%s, enabled=false WHERE", "SET off_reason='retired', off_why=%s WHERE"),
    "enable leaves enabled off":
        ("SET off_reason=NULL, off_why=NULL, enabled=true, state=%s", "SET off_reason=NULL, off_why=NULL, state=%s"),
    "the tool trusts a stale reason over `enabled`":
        ('    t["off_reason"] = None if t["enabled"] else (t["off_reason"] or "unknown")\n', ''),
}
