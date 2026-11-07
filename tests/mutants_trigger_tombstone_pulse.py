"""Authored mutants for src/astryx/pulse/pulse.py (plan-9853 D2, the trigger tombstone), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_trigger_tombstone_pulse.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/pulse/pulse.py"
ORACLE = REPO / "tests" / "test_trigger_tombstone.py"
ENV = "PULSE_SRC"
TIMEOUT = 300

MUTANTS = {
    "the pulse ignores the tombstone (a python retire is undone within a minute)":
        ('            if tomb.exists():\n'
         '                conn.execute("UPDATE triggers SET off_reason=\'retired\', enabled=false WHERE agent=%s AND name=%s "\n'
         '                             "AND kind=\'python\'",\n'
         '                             (agent, t["name"]))\n'
         '                retired_notice(conn, agent, t["name"], f.name, tomb)\n'
         '                seen.add((agent, t["name"]))\n'
         '                continue\n',
         ''),
    "any agent's tombstone retires the name everywhere (not per target agent)":
        ('            tomb = ESTATE / "triggers" / agent / ".retired" / t["name"]\n',
         '            tomb = next((d / ".retired" / t["name"] for d in (ESTATE / "triggers").iterdir()\n'
         '                         if (d / ".retired" / t["name"]).exists()), ESTATE / "triggers" / agent / ".retired" / t["name"])\n'),
    'a held-off name is never said (the re-create miss is silent again)':
        ('                retired_notice(conn, agent, t["name"], f.name, tomb)\n',
         ''),
    'said every minute once delivered (only the pending-coalesce left)':
        ('"AND ts >= %s LIMIT 1", (agent, f"[trigger {key}]%", since)).fetchone():',
         '"AND ts >= %s LIMIT 0", (agent, f"[trigger {key}]%", since)).fetchone():'),
    "said once EVER (a fresh retire earns no notice)":
        ('"AND ts >= %s LIMIT 1", (agent, f"[trigger {key}]%", since)).fetchone():',
         '"AND ts >= %s - interval \'100 years\' LIMIT 1", (agent, f"[trigger {key}]%", since)).fetchone():'),
    }
