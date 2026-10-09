"""Authored mutants for nucleus/schema_parity.py (a1 #38264), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_schema_parity.py

Every destructive arm runs on the oracle's own fixture; the live arm only reads, in a read-only session.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "nucleus" / "schema_parity.py"
ORACLE = REPO / "tests" / "test_schema_parity.py"
ENV = "SCHEMA_PARITY_SRC"
TIMEOUT = 300
MUTANTS = {
    "P1 a missing column isn't seen (a1's masked IF-NOT-EXISTS add reads green)":
        ('            if c not in live[t]:\n                missing.append(', '            if False:\n                missing.append('),
    "P2 a hand-added column isn't judged":
        ('                extra.append(f"column {name}.{c} ({live[t][c]})")', '                pass'),
    "P3 types aren't compared":
        ('            elif live[t][c] != typ:', '            elif False:'),
    "P4 a missing TABLE isn't seen":
        ('            missing.append(f"table {name}")\n', ''),
    "P5 memgraph's module-owned DDL leaves the expected set (its drift reads live-only, never judged)":
        ('    return (memgraph.SCHEMA_SQL,)', '    return ()'),
    "P6 the live session isn't read-only":
        ('        c.execute("SET default_transaction_read_only = on")\n', ''),
    "P7 drift is reported but never fails (any difference reads green)":
        ('            "drift": bool(missing or extra or typed)}', '            "drift": False}'),
    "P8 a missing OBJECT isn't seen (a hand-dropped messages_notify silences the wire, parity green: a1 #38450)":
        ('    missing = sorted(f"{k} {n}" for k, names in expected.items() for n in names - live.get(k, set()))',
         '    missing = []'),
    "P9 object drift is computed but never fails the run":
        ('    out["drift"] = out["drift"] or o["drift"]', '    out["drift"] = out["drift"]'),
    "P10 internal (FK) triggers are judged (their OID-derived names differ per database: a false MISSING)":
        ("WHERE NOT t.tgisinternal AND n.nspname <> ALL(%s)", "WHERE n.nspname <> ALL(%s)"),
}
