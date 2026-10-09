"""Authored mutants for nucleus/people_move.py (people library 1a), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_people_move.py

The move runs only inside the oracle's fixture database, so no mutant can reach prod's social tables.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "people_move.py"
ORACLE = REPO / "tests" / "test_people_gate.py"
ENV = "PEOPLE_MOVE_SRC"
TIMEOUT = 300

MUTANTS = {
    "V1 the source is never cleared (the details stay on the network surface)":
        ('        conn.execute(CLEAR_SQL)\n', ''),
    "V2 shape isn't copied (evidence is lost in the move)":
        ('f"SELECT org, id, relation, who, shape, confidence FROM social_person WHERE {ANY_DETAIL} "',
         'f"SELECT org, id, relation, who, NULL, confidence FROM social_person WHERE {ANY_DETAIL} "'),
    "V3 the landing check is disabled (a move that doesn't land commits anyway)":
        ('        if bad:                                   # raising', '        if False:                                 # raising'),
    "V4 a dry run applies":
        ('        if not apply:\n            return rec\n', ''),
    "V5 a NULL source overwrites a value already in social_relation":
        ('kind = COALESCE(EXCLUDED.kind, social_relation.kind)', 'kind = EXCLUDED.kind'),
    "V6 the move ignores `who` in its row filter (a who-only row is never moved)":
        ('DETAIL = ("relation", "who", "shape", "confidence")', 'DETAIL = ("relation", "shape", "confidence")'),
}
