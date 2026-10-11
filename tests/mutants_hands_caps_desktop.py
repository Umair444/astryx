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
    "a refusal doesn't move `last` (a3 #47653 F1: a hammering loop is metered, not stopped)":
        ('        st["last"] = max(now, st.get("last", now))                  # a refusal is activity too (F1)\n        if why:\n            save(st)\n            raise Capped(why)\n',
         '        if why:\n            raise Capped(why)\n        st["last"] = max(now, st.get("last", now))\n'),
    'a refused charge is counted anyway':
        ('        if why:\n            save(st)\n            raise Capped(why)\n',
         '        if why:\n            st["steps"] += n\n            save(st)\n            raise Capped(why)\n'),
    'a multi-step charge only checks one step':
        ('if st["steps"] + n > c["steps"]:',
         'if st["steps"] + 1 > c["steps"]:'),
    'no wall-time cap':
        ('        elif now - st["start"] > c["wall_s"]:\n',
         '        elif False:\n'),
    'no daily cap':
        ('        elif st.get("day_steps", 0) + n > c["day_steps"]:\n',
         '        elif False:\n'),
    'a session reset also resets the day':
        ('            st = {**st, "start": now, "last": now, "steps": 0}\n',
         '            st = {"start": now, "last": now, "steps": 0}\n'),
    'a clock stepped back suspends the wall clock':
        ('        if now < st["start"]:',
         '        if False:'),
    'idle never resets a session':
        ('        elif now - st.get("last", st["start"]) > c["idle_s"]:',
         '        elif False:'),
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
