"""Authored mutants for nucleus/sqlguard/fixture.py's reaper, oracle tests/test_fixture_reaper.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_fixture_reaper.py

The reaper DROPs databases WITH (FORCE), so its battery lives in the tree, not in a message (a3 #39195). Most mutants
make it MORE aggressive. SAFE BY CONSTRUCTION (seed #34899): the oracle's live arms run under a PRIVATE prefix
(astryx_fx_rptest<pid>_), so an aggressive mutant can only ever see databases the oracle itself made.
Not here, because EQUIVALENT: `keep=` ignored (a3 M7). fixture_db reaps BEFORE its CREATE, so its own name is
never listed.
THE BOUNDARY of that construction (a3 #39299): it protects every mutant that judges WITHIN reap()'s candidate set.
It does NOT protect a mutant that removes or widens reap()'s own `starts_with(datname, PREFIX)` filter. That one
would see every astryx_fx_* on the shared server. Don't add such a mutant here without a different construction:
a throwaway cluster, or a check of the candidate set against a planted allowlist BEFORE any DROP.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "nucleus" / "sqlguard" / "fixture.py"
ORACLE = REPO / "tests" / "test_fixture_reaper.py"
ENV = "SQLGUARD_FIXTURE_SRC"
TIMEOUT = 300
MUTANTS = {
    "R1 another pid namespace or host is judged (a bwrap run's pid read as a host pid)":
        ('    if not st["pidns"] or st["pidns"] != pidns or st["host"] != host:',
         '    if False:'),
    "R2 an unknowable pidns on BOTH sides is judged (a3 M3: two /proc-less sandboxes)":
        ('    if not st["pidns"] or st["pidns"] != pidns or st["host"] != host:',
         '    if st["pidns"] != pidns or st["host"] != host:'),
    "R3 the NAME is trusted: an unstamped DB is reaped when its tail pid looks dead":
        ('        return "keep", f"no owner stamp (name tail pid {name_pid(name)}, never trusted)"',
         '        p = name_pid(name)\n        return ("keep", "x") if p is None or alive(p) else ("reap", "name")'),
    "R4 pid reuse fails OPEN: PermissionError (another owner's live process) reads dead":
        ('    except (PermissionError, OverflowError, ValueError):\n        return True',
         '    except (PermissionError, OverflowError, ValueError):\n        return False'),
    "R5 reap() drops on KEEP (the verdict is inverted at the actuator)":
        ('        if act == "reap":\n            try:',
         '        if act == "keep":\n            try:'),
    "R6 no reap at fixture_db entry (the leak stays)":
        ('    reap(admin, keep=name)  ',
         '    pass  '),
    "R7 no owner stamp written (nothing is ever reapable)":
        ("            admin.execute(f'COMMENT ON DATABASE \"{name}\" IS \\'{owner_stamp()}\\'')",
         "            pass"),
}
