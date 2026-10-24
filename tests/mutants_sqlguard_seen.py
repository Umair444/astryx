"""Authored mutants for enforce's read-only seen-set (plan-11908 D5, a3 BC-1 #62652), tree form, run by
devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_sqlguard_seen.py
"""
EN = "src/astryx/security/sqlguard/enforce.py"
ORACLE = "tests/test_sqlguard_seen.py"
MUTANTS = {
    "S1 enforce() defaults to writing the seen set":
        (EN, "def enforce(trace_dir, ledger=None, dsn=None, rep=None, write_seen=False):",
             "def enforce(trace_dir, ledger=None, dsn=None, rep=None, write_seen=True):"),
    "S2 enforce() reads the timer's flag from the env itself":
        (EN, "    ledger = ledger if ledger is not None else load_ledger()\n    # The ledger's covering",
             "    write_seen = write_seen or os.environ.get(\"ASTRYX_SQLGUARD_WRITE_SEEN\") == \"1\"\n"
             "    ledger = ledger if ledger is not None else load_ledger()\n    # The ledger's covering"),
    "S3 the read-only _clock still writes":
        (EN, "    if not write:\n        return {k: (f, r)", "    if False:\n        return {k: (f, r)"),
    "S4 a read-only run doesn't name the omission":
        (EN, "    if not write_seen:                  # D5", "    if False:                  # D5"),
    "S5 a read-only run masks a RED as rc 77":
        (EN, "    rc = 77 if hard else (1 if red else (77 if not_searched else 0))",
             "    rc = 77 if not_searched else (1 if red else 0)"),
}
