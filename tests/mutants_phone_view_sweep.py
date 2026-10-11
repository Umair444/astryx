"""Authored mutants for nucleus/shipped_triggers/phone_resume_sweep.py (plan-8675 S2), run by nucleus/mutation_probe.py:

    venv/bin/python nucleus/mutation_probe.py tests/mutants_phone_view_sweep.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "nucleus/shipped_triggers/phone_resume_sweep.py"
ORACLE = REPO / "tests" / "test_phone_view.py"
ENV = "SWEEP_SRC"
TIMEOUT = 180

MUTANTS = {
    'every resume is flagged, near an act or not':
        ('            if near:\n',
         '            if True:\n'),
    'the watermark never advances (a flag repeats every sweep)':
        ('    state["through"] = max(through, ready)\n',
         ''),
    'only acts BEFORE the resume count':
        ('abs(a_ts - ts) <= WINDOW_S',
         '0 <= ts - a_ts <= WINDOW_S'),
    'a resume is judged before its +60 s window passes':
        ('ready = now - WINDOW_S',
         'ready = now'),
}
