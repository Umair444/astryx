"""Authored mutants for nucleus/hands_desktop.py (plan-7862 Hands caps), run by nucleus/mutation_probe.py:

    venv/bin/python nucleus/mutation_probe.py tests/mutants_hands_caps_desktop.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "nucleus/hands_desktop.py"
ORACLE = REPO / "tests" / "test_hands_caps.py"
ENV = "HANDS_DESKTOP_SRC"
TIMEOUT = 120

MUTANTS = {
    'a refused charge is counted anyway':
        ('        if st["steps"] + n > c["steps"]:\n            raise Capped(',
         '        if st["steps"] + n > c["steps"]:\n            st["steps"] += n\n            f.write_text(json.dumps(st))\n            raise Capped('),
    'a multi-step charge only checks one step':
        ('if st["steps"] + n > c["steps"]:',
         'if st["steps"] + 1 > c["steps"]:'),
    'no wall-time cap':
        ('        if now - st["start"] > c["wall_s"]:\n',
         '        if False:\n'),
    'idle never resets a session':
        ('        if st is None or now - st.get("last", st["start"]) > c["idle_s"]:\n',
         '        if st is None:\n'),
    'idle is measured from the session START, not the last action':
        ('now - st.get("last", st["start"]) > c["idle_s"]',
         'now - st["start"] > c["idle_s"]'),
    'an unreadable count is a fresh session':
        ('        except (OSError, ValueError, AssertionError):\n            # an unreadable count',
         '        except (OSError, ValueError, AssertionError):\n            st = None\n        if False:\n            # an unreadable count'),
    'no lock':
        ('    with open(CAPS_DIR / f"{_name(agent)}.lock", "w") as lk:\n        fcntl.flock(lk, fcntl.LOCK_EX)\n',
         '    with open(CAPS_DIR / f"{_name(agent)}.lock", "w") as lk:\n        pass\n'),
    'one count for every agent':
        ('f = CAPS_DIR / f"{_name(agent)}.json"',
         'f = CAPS_DIR / "all.json"'),
}
