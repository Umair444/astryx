"""Authored mutants for tests/pilot_browser_test.mjs's listeners (plan-10108 D2/D3), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_gate_concurrency.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "tests/pilot_browser_test.mjs"
ORACLE = REPO / "tests" / "test_gate_concurrency.py"
ENV = "PILOT_SRC"
TIMEOUT = 900

MUTANTS = {
    "chromium back on the fixed CDP port 9334 (a2's squatter: it attaches to whoever holds it)":
        ("'--remote-debugging-port=0', `--user-data-dir=${prof}`", "'--remote-debugging-port=9334', `--user-data-dir=${prof}`"),
    "vite back on a fixed --port 5181 --strictPort (the second of two gates can't start)":
        ("['--host', '127.0.0.1'], { cwd: WEB,", "['--port', '5181', '--strictPort', '--host', '127.0.0.1'], { cwd: WEB,"),
    "vite's cache back on the shared default (VITE_CACHE_DIR not handed to it)":
        ("    env: { ...process.env, VITE_CACHE_DIR: cache } })",
         "    env: Object.fromEntries(Object.entries(process.env).filter(([k]) => k !== 'VITE_CACHE_DIR')) })"),
}
