"""Authored mutants for src/astryx/pulse/shipped_triggers/windows_idle_stop.py (plan-8675 C5, Windows on demand), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_windows_ondemand_stop.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/pulse/shipped_triggers/windows_idle_stop.py"
ORACLE = REPO / "tests" / "test_windows_ondemand.py"
ENV = "WIN_IDLE_SRC"
TIMEOUT = 300

MUTANTS = {
    "a VM it didn't start is taken for ours (a record fabricated for it, run identity included: a4 #48958)":
        ("    if rec is None:                                     # not started by an agent's open: never stopped here\n        state.clear()\n        return None\n",
         '    if rec is None:\n        rec = {"ts": 0.0, "started_at": hd.container_started_at(android.WINDOWS_CONTAINER)}\n'),
    'connections are ignored':
        ('    if n > 0:\n        state["busy"] = now\n        return None\n',
         ''),
    'the slot is freed when the stop is ISSUED, not when it lands':
        ('    state["stopping"] = now\n    return (f"stopping',
         '    state["stopping"] = now\n    android.free_slot("windows")\n    return (f"stopping'),
    "HANDS_WINDOWS_IDLE_S=0 doesn't disable":
        ('    if limit <= 0:\n        return None\n',
         ''),
    'the stop BLOCKS the tick (~100 s past the pulse budget)':
        ('    subprocess.Popen(["docker", "stop", "-t", "120", rec.get("container") or android.WINDOWS_CONTAINER],\n                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)',
         '    subprocess.run(["docker", "stop", "-t", "120", rec.get("container") or android.WINDOWS_CONTAINER],\n                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(4)'),
    "the record's run identity isn't compared (a restarted, owner-started run inherits it: a4 #49102)":
        ("    if live != rec.get(\"started_at\"):\n", "    if False:\n"),
}
