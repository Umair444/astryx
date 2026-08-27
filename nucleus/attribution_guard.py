#!/usr/bin/env python3
"""attribution_guard — economy-boundary integrity for pay-the-author (goal 3408, guard-first).

Baum's conservation law (economy.md): value enters ONLY at the boundary — a funded goal
shipped with evidence — and the total credited can never exceed the budgets that shipped.
Without this, wash-trading and self-dealing evolve. This guard enforces it on the attribution
surface (econ.value_flow, and the pay-the-author extension that will ride the same join),
BEFORE the wiring lands, so the wiring is built against a RED-first-proven invariant.

THE INVARIANT, derived from the substrate (econ.py:132-149), not asserted:
value_flow apportions each shipped goal's budget over its turns by billable spend via the
ONE boundary join `turns.goal_id → goals(done_at, budget>0)`, crediting turns.agent. The
per-row share `budget*cost/total` is INTEGER division, so attribution systematically
UNDER-credits by at most one token per (goal,agent) credit row and can NEVER mint. Hence:

    0  <=  Σ shipped_budgets − Σ value_earned  <=  n_credit_rows      (truncation-bounded)

- Σ value_earned > Σ budgets  → MINTING / double-credit (the wash-trading failure). Hard red.
- shortfall > n_credit_rows   → a ROUTING HOLE: credit is reaching agents through something
  OTHER than the boundary join (e.g. the dead steps.goal_id, all-NULL → credits nothing →
  shortfall = the whole budget). Red. So both boundary violations fall out of conservation.

turns.agent is a forgeable INSERT (an agent can INSERT a turns row claiming agent='Y'), so
this guard does NOT try to PREVENT self-dealing by construction — that's undecidable here;
WASH is DETECTED (the cycle-zeroing detector, a separate enforcement piece). What this guard
guarantees is the conservation ceiling: no attribution path, forged or honest, can mint value
above the shipped budgets.

check_conservation() is PURE (feed it any rows) so the oracle proves it RED without a DB;
run() wires it to the live econ.value_flow. CLI: python nucleus/attribution_guard.py.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:                 # run-as-script: put the repo root on the path
    sys.path.insert(0, str(REPO))             # so `import nucleus.econ` resolves standalone


@dataclass(frozen=True)
class Violation:
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.detail}"


def check_conservation(value_rows: list[dict], shipped_budget_total: int,
                       n_credit_rows: int) -> list[Violation]:
    """The pure invariant. value_rows is value_flow's output ({agent, value_earned, ...})."""
    out: list[Violation] = []
    earned = sum(int(r.get("value_earned") or 0) for r in value_rows)
    budgets = int(shipped_budget_total or 0)
    shortfall = budgets - earned

    if earned > budgets:
        out.append(Violation("MINT",
            f"attribution credited {earned} > {budgets} shipped budget — value minted above the "
            f"boundary ({earned - budgets} over). No path may create W the boundary did not."))
    elif shortfall > max(n_credit_rows, 0):
        out.append(Violation("ROUTING-HOLE",
            f"shortfall {shortfall} exceeds the truncation bound {n_credit_rows} — credit is "
            f"reaching agents through something OTHER than turns.goal_id→shipped (e.g. the dead "
            f"steps.goal_id credits nothing). Attribution must ride the ONE boundary join."))
    return out


# ── live wiring ──────────────────────────────────────────────────────────────────────
def _budgets_and_rows(conn, since, until) -> tuple[int, int]:
    """(Σ shipped-goal budgets in window, n distinct (goal,agent) credit rows) — the two
    numbers the truncation bound needs, from the SAME boundary the attribution uses."""
    from nucleus.econ import BILL, _one, _all  # local import: guard is importable sans DB
    b = _one(conn, """
        SELECT coalesce(sum(budget_tokens),0)::bigint FROM goals
        WHERE done_at >= %s AND done_at < %s AND budget_tokens > 0""", (since, until))
    rows = _all(conn, f"""
        SELECT count(*)::int AS n FROM (
          SELECT t.goal_id, t.agent
          FROM turns t JOIN goals g ON g.id = t.goal_id
          WHERE g.done_at >= %s AND g.done_at < %s AND g.budget_tokens > 0
          GROUP BY 1, 2) x""", (since, until))
    return int(b[0]), int(rows[0]["n"] if rows else 0)


def run(conn, since, until) -> list[Violation]:
    from nucleus.econ import value_flow
    value_rows = value_flow(conn, since, until)
    budgets, n_credit_rows = _budgets_and_rows(conn, since, until)
    return check_conservation(value_rows, budgets, n_credit_rows)


def _dsn() -> str | None:
    import os
    if os.environ.get("ASTRYX_DSN"):
        return os.environ["ASTRYX_DSN"].strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ASTRYX_DSN="):
                return line[len("ASTRYX_DSN="):].strip().strip('"').strip("'")
    return None


def main(argv: list[str]) -> int:
    # A guard that cannot read its substrate SKIPs (77), never falsely passes; the oracle
    # carries the RED-first proof. (econ's window fns take a caller-supplied conn — no _connect.)
    try:
        import psycopg
    except Exception as e:                                          # noqa: BLE001
        print(f"SKIP: attribution_guard needs the org runtime (psycopg: {e}).")
        return 77
    dsn = _dsn()
    if not dsn:
        print("SKIP: no ASTRYX_DSN (env or .env) — no econ substrate to check.")
        return 77
    from datetime import datetime, timezone
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    until = datetime.now(timezone.utc)
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            vs = run(conn, since, until)
    except Exception as e:                                         # noqa: BLE001
        print(f"SKIP: could not reach the econ substrate ({type(e).__name__}: {e}).")
        return 77
    if vs:
        print("attribution_guard: CONSERVATION BROKEN — attribution is not boundary-bounded:")
        for v in vs:
            print(f"  ✗ {v}")
        return 1
    print("attribution_guard: OK — Σ credited ≤ Σ shipped budgets, shortfall within truncation "
          "(value enters only at the boundary; nothing minted).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
