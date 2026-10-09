"""Authored mutants for nucleus/privilege_census.py (people library 1a), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_privilege_census.py

Hermetic (a temp tree), except C8, whose arm reads catalogs only. One per way a census misleads 1b: over-matching invents blockers,
under-matching hides them, a wrong surface or DSN source sends the switch to the wrong place.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "privilege_census.py"
ORACLE = REPO / "tests" / "test_privilege_census.py"
ENV = "PRIVILEGE_CENSUS_SRC"

MUTANTS = {
    "C1 dml needs no FROM (prose 'SELECT' counts as a statement)":
        (r'"dml": ("a GRANT on the table", r"\b(SELECT\b.+\bFROM|', r'"dml": ("a GRANT on the table", r"\b(SELECT\b|'),
    "C2 a ROLE grant counts as an object grant":
        (r'r"\b(GRANT\s+(SELECT|INSERT|UPDATE|DELETE|ALL|USAGE|CONNECT|"', r'r"\b(GRANT\s+(\w+|"'),
    "C3 client COPY reads as superuser":
        (r"\bCOPY\b.+\b(TO|FROM)\s+(PROGRAM|')", r"\bCOPY\b.+\b(TO|FROM)\s+"),
    "C4 the .env-file read is never seen":
        ("    return {\"classes\": dict(hits), \"dsn_env\": bool(ENV_RE.search(text)), \"dsn_file\": bool(FILE_RE.search(text))}",
         "    return {\"classes\": dict(hits), \"dsn_env\": bool(ENV_RE.search(text)), \"dsn_file\": False}"),
    "C5 venv is walked (a dependency's CREATE EXTENSION reads as ours)":
        ('SKIP_DIRS = {"venv", ".venv",', 'SKIP_DIRS = {".venv",'),
    "C6 triggers/ reads as a resident surface":
        ('    ("triggers/", "pulse triggers (service)", "service"),', '    ("triggers/", "pulse triggers (service)", "resident"),'),
    "C8 the live half's session isn't read-only":
        ('        c.execute("SET default_transaction_read_only = on")\n', ''),
    "C7 superuser misses LOAD":
        (r"""r"(\bCREATE EXTENSION\b|\bLOAD\s+'|""", r"""r"(\bCREATE EXTENSION\b|"""),
}
