#!/home/umair/astryx/venv/bin/python
"""Gates for nucleus/wake_marker.py — the ONE definition of "was this wake consumed".

Exit 0 pass · 1 fail · 77 a gate could not run.

WHAT IS ACTUALLY AT RISK HERE. This module exists to collapse three copies of a predicate
into one writer, so the failure it must prevent is a FOURTH copy appearing inside itself:
the SQL and the pure-python `is_consumed()` are two renderings of one decision, and nothing
but a test makes them agree. So the load-bearing gate crosses them against REAL ROWS —
every row's SQL verdict compared to the python verdict on the same evidence — rather than
against a fixture, because a fixture encodes my belief about the source and these two
renderings would happily share my belief while both being wrong about the table.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nucleus import wake_marker as wm       # noqa: E402

FAIL, SKIP = [], []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def skip(name, why):
    print(f"  SKIP  {name}  — {why}")
    SKIP.append(f"{name} ({why})")


def main():
    print("wake_marker — the one definition (goal #2457)\n")

    # ── structure ────────────────────────────────────────────────────────────────────
    check("every named marker has a clause", set(wm.CLAUSES) >=
          set(wm.TURN_MARKERS) | set(wm.CROSS_MARKERS))
    check("the facility's cross uses TWO INDEPENDENTLY-WRITTEN markers, not one table",
          any(m in ("opener", "contained") for m in wm.CROSS_MARKERS)
          and "stepped" in wm.CROSS_MARKERS,
          f"{wm.CROSS_MARKERS} reads only turns")
    try:
        wm.consumed_expr(markers=("nonsense",))
        check("an unknown marker is refused, not silently dropped", False,
              "no ValueError raised")
    except ValueError:
        check("an unknown marker is refused, not silently dropped", True)

    # A DROPPED expression must be the exact complement of CONSUMED. If these ever drift
    # the estate gets a set that is neither, and both callers read it as authoritative.
    check("dropped_expr is the exact complement of consumed_expr",
          wm.dropped_expr("m") == "NOT " + wm.consumed_expr("m"))

    # ── the pure decision, driven over its whole polarity table ──────────────────────
    check("no evidence at all -> NOT consumed",
          wm.is_consumed() is False)
    for mk in wm.TURN_MARKERS:
        check(f"'{mk}' alone is sufficient evidence of consumption",
              wm.is_consumed(**{mk: True}) is True)
    # THE ONE THAT MATTERS FOR THE FACILITY: a step is evidence only when the caller asked
    # for the step marker. A turn-only caller must not silently start counting steps.
    check("a step does NOT count for a turn-only caller (markers are a contract)",
          wm.is_consumed(stepped=True, markers=wm.TURN_MARKERS) is False)
    check("a step DOES count for the facility's cross",
          wm.is_consumed(stepped=True, markers=wm.CROSS_MARKERS) is True)

    # ── SQL vs PYTHON, crossed on real rows ─────────────────────────────────────────
    try:
        from nucleus import wake_audit as wa
        import psycopg
        dsn = wa.dsn()
    except Exception as e:
        skip("SQL and python agree on live rows", f"no DB access ({type(e).__name__})")
        return verdict()

    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            # Pull each clause's truth SEPARATELY, then let each rendering decide from the
            # same evidence. That is what makes this a cross and not a tautology: if we
            # asked SQL for the verdict and python for the verdict off different inputs,
            # agreement would prove nothing about either.
            sql = f"""
                SELECT m.id,
                       {wm.CLAUSES['opener'].format(a='m', bound='')}      AS opener,
                       {wm.CLAUSES['contained'].format(a='m', bound='')}   AS contained,
                       {wm.CLAUSES['later_turn'].format(a='m', bound='')}  AS later_turn,
                       {wm.CLAUSES['stepped'].format(a='m', bound='')}     AS stepped,
                       {wm.consumed_expr('m', wm.TURN_MARKERS)}            AS sql_turn,
                       {wm.consumed_expr('m', wm.CROSS_MARKERS)}           AS sql_cross
                  FROM messages m
                 WHERE m.status = 'delivered' AND m.to_org = 'local'
                   AND m.ts > now() - interval '7 days'
                 ORDER BY m.id DESC LIMIT 400
            """
            rows = conn.execute(sql).fetchall()
    except Exception as e:
        skip("SQL and python agree on live rows", f"query failed ({type(e).__name__})")
        return verdict()

    if not rows:
        skip("SQL and python agree on live rows", "no delivered rows in the window")
        return verdict()

    dis_turn = dis_cross = 0
    for _id, op, co, lt, st, s_turn, s_cross in rows:
        if wm.is_consumed(op, co, lt, st, wm.TURN_MARKERS) != s_turn:
            dis_turn += 1
        if wm.is_consumed(op, co, lt, st, wm.CROSS_MARKERS) != s_cross:
            dis_cross += 1
    check(f"SQL and python agree on all {len(rows)} live rows (turn-only)", dis_turn == 0,
          f"{dis_turn} disagreements")
    check(f"SQL and python agree on all {len(rows)} live rows (facility cross)",
          dis_cross == 0, f"{dis_cross} disagreements")

    # POSITIVE CONTROL: the sample must actually EXERCISE both verdicts, or "they agree"
    # is what two renderings that always say False would also produce.
    seen_true = sum(1 for r in rows if r[5])
    seen_false = len(rows) - seen_true
    check("the live sample exercises BOTH verdicts (agreement is not vacuous)",
          seen_true > 0 and seen_false > 0, f"{seen_true} consumed / {seen_false} not")

    return verdict()


def verdict():
    print()
    if FAIL:
        print(f"FAILED ({len(FAIL)}): " + "; ".join(FAIL))
        return 1
    if SKIP:
        print(f"NOT RUN ({len(SKIP)}): " + "; ".join(SKIP))
        print("a gate that observed nothing is not a pass — exit 77")
        return 77
    print("the one definition holds: SQL and python agree, markers are a contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
