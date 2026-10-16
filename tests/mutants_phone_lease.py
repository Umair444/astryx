"""Authored mutants for src/astryx/hearing/ear_lease.py (plan-8675 S1), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_phone_lease.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src/astryx/hearing/ear_lease.py"
ORACLE = REPO / "tests" / "test_phone_facade.py"
ENV = "EAR_LEASE_SRC"
TIMEOUT = 120

MUTANTS = {
    'a live hold can be taken by anyone':
        ("(state = 'HELD' AND (holder = %s OR expires_at < now()))",
         "(state = 'HELD' AND (holder = %s OR true))"),
    'anyone can unhold':
        ("WHERE resource = %s AND state = 'HELD' AND holder = %s RETURNING",
         "WHERE resource = %s AND state = 'HELD' AND (holder = %s OR true) RETURNING"),
    'a microphone lease can be held':
        ('    if resource.startswith("ear:"):\n        raise ValueError',
         '    if False:\n        raise ValueError'),
    'renewal resets granted_at':
        ('CASE WHEN holder = %s AND state = \'HELD\' "\n        f"THEN granted_at',
         'CASE WHEN holder = %s AND false "\n        f"THEN granted_at'),
}
