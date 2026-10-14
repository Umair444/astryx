#!/usr/bin/env python3
"""astryx · people_move — move the relation DETAILS out of social_person into social_relation (people library 1a).

SEED'S ACT, NOT THE BUILDER'S (seed #36018): this is a data move on prod. The builder ships and proves it (the oracle
runs it on a fixture); seed runs it, once, and posts the receipt.

    venv/bin/python -m astryx.people.people_move            # DRY RUN: the receipt of what WOULD move; changes nothing
    venv/bin/python -m astryx.people.people_move --apply    # one transaction: copy, verify, NULL the source, commit
    venv/bin/python -m astryx.people.people_move --apply --keep-target    # a conflict keeps social_relation's value

Mapping: relation -> kind, who -> context, shape -> evidence, confidence -> confidence (closeness has no source).
A row moves if ANY of the four is non-NULL. A NULL source never erases a value already in social_relation.

CONFLICTS ARE NEVER RESOLVED SILENTLY (a2 B2, #36873). A cut-over writer (persona_llm, persona.apply_pg) may have
written social_relation for a key BEFORE the move, with a non-NULL value that DIFFERS from the source's. The
default REFUSES: the receipt counts `conflicts` (keys) and the move rolls back. `--keep-target` is the explicit,
named choice to keep the newer value: target wins on those fields, and the receipt counts what it `kept`. The dry
run always reports `conflicts`, so the choice is made before the act.

THE RECEIPT carries counts and digests, never values (they are the private tier being moved). `digest` is a sha256
over the moved (org, pid, relation, who, shape, confidence) tuples in key order, read from the SOURCE before the move;
`digest_after` is the same over social_relation's (org, pid, kind, context, evidence, confidence), masked to the
fields the source had, read inside the same transaction. Every non-NULL source field must have landed, or the
transaction rolls back; so on a first move into an empty table the two digests are EQUAL. `left` (social_person
rows still carrying any detail) must be 0 at commit.
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402

import hashlib
import json
import sys
from pathlib import Path

REPO = repo_root(__file__)
sys.path.insert(0, str(REPO))

DETAIL = ("relation", "who", "shape", "confidence")
ANY_DETAIL = " OR ".join(f"{c} IS NOT NULL" for c in DETAIL)
SRC_SQL = ("SELECT org, id, relation, who, shape, confidence FROM social_person "
           f"WHERE {ANY_DETAIL} ORDER BY org, id")
DST_SQL = ("SELECT r.org, r.pid, r.kind, r.context, r.evidence, r.confidence FROM social_relation r "
           "JOIN social_person p ON p.org = r.org AND p.id = r.pid "
           f"WHERE {' OR '.join('p.' + c + ' IS NOT NULL' for c in DETAIL)} ORDER BY r.org, r.pid")
UPSERT_SQL = ("INSERT INTO social_relation (org, pid, kind, context, evidence, confidence) "
              f"SELECT org, id, relation, who, shape, confidence FROM social_person WHERE {ANY_DETAIL} "
              "ON CONFLICT (org, pid) DO UPDATE SET kind = COALESCE(EXCLUDED.kind, social_relation.kind), "
              "context = COALESCE(EXCLUDED.context, social_relation.context), "
              "evidence = COALESCE(EXCLUDED.evidence, social_relation.evidence), "
              "confidence = COALESCE(EXCLUDED.confidence, social_relation.confidence), updated_at = now()")
# --keep-target: the existing value wins wherever there is one (conflicts were counted and named first).
UPSERT_KEEP_SQL = ("INSERT INTO social_relation (org, pid, kind, context, evidence, confidence) "
                   f"SELECT org, id, relation, who, shape, confidence FROM social_person WHERE {ANY_DETAIL} "
                   "ON CONFLICT (org, pid) DO UPDATE SET kind = COALESCE(social_relation.kind, EXCLUDED.kind), "
                   "context = COALESCE(social_relation.context, EXCLUDED.context), "
                   "evidence = COALESCE(social_relation.evidence, EXCLUDED.evidence), "
                   "confidence = COALESCE(social_relation.confidence, EXCLUDED.confidence), updated_at = now()")
CLEAR_SQL = f"UPDATE social_person SET relation = NULL, who = NULL, shape = NULL, confidence = NULL WHERE {ANY_DETAIL}"
LEFT_SQL = f"SELECT count(*) FROM social_person WHERE {ANY_DETAIL}"
COUNT_SQL = ("SELECT count(*), count(relation), count(who), count(shape), count(confidence) FROM social_person "
             f"WHERE {ANY_DETAIL}")


def _digest(rows) -> str:
    return hashlib.sha256(json.dumps([list(r) for r in rows], default=str).encode()).hexdigest()


def move(conn, apply: bool = False, keep_target: bool = False) -> dict:
    """`conn` is a psycopg connection (NOT autocommit) to the org database. Returns the receipt."""
    with conn.transaction():
        n, rel, who, shape, conf = conn.execute(COUNT_SQL).fetchone()
        src = conn.execute(SRC_SQL).fetchall()
        pre = {(r[0], r[1]): r for r in conn.execute(DST_SQL).fetchall()}     # what a cut-over writer left
        clash = {(r[0], r[1], i) for r in src if (r[0], r[1]) in pre
                 for i, (v, t) in enumerate(zip(r[2:], pre[(r[0], r[1])][2:]))
                 if v is not None and t is not None and v != t}
        rec = {"rows": n, "relation": rel, "who": who, "shape": shape, "confidence": conf,
               "digest": _digest(src)[:16], "conflicts": len({(o, p) for o, p, _ in clash}), "applied": False}
        if not apply:
            return rec
        if clash and not keep_target:             # raising inside the block rolls the whole move back
            raise RuntimeError(f"people_move: {rec['conflicts']} key(s) conflict (a cut-over writer ran first with a "
                               "different value); refused, rolled back. Re-run with --keep-target to keep those")
        conn.execute(UPSERT_KEEP_SQL if keep_target else UPSERT_SQL)
        dst = {(r[0], r[1]): r for r in conn.execute(DST_SQL).fetchall()}
        # Every NON-NULL source field must now be in social_relation, except a conflict --keep-target kept. A field
        # the source has NULL may hold a newer value a cut-over writer put there first, so it's masked, not compared.
        bad = sum(1 for r in src if (r[0], r[1]) not in dst
                  or any(v is not None and v != w and (r[0], r[1], i) not in clash
                         for i, (v, w) in enumerate(zip(r[2:], dst[(r[0], r[1])][2:]))))
        rec["kept"] = len(clash)
        rec["digest_after"] = _digest([tuple(v if s_ is not None else None for v, s_ in zip(dst[(r[0], r[1])], r))
                                       for r in src if (r[0], r[1]) in dst])[:16]
        if bad:                                   # raising inside the block rolls the whole move back
            raise RuntimeError(f"people_move: {bad} row(s) didn't land in social_relation, rolled back")
        conn.execute(CLEAR_SQL)
        rec["left"] = conn.execute(LEFT_SQL).fetchone()[0]
        if rec["left"]:
            raise RuntimeError(f"people_move: {rec['left']} row(s) still carry a detail, rolled back")
    rec["applied"] = True
    rec["social_relation"] = conn.execute("SELECT count(*) FROM social_relation").fetchone()[0]
    return rec


def main(argv) -> int:
    import psycopg
    from astryx.people import people
    dsn = people._dsn()
    if not dsn:
        print("people_move: no ASTRYX_DSN")
        return 1
    with psycopg.connect(dsn) as conn:
        rec = move(conn, apply="--apply" in argv, keep_target="--keep-target" in argv)
    print("people_move receipt: " + json.dumps(rec, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
