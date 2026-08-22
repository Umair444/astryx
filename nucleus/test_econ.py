"""Oracle for nucleus/econ.py — the org's economic equations, proven against the REAL DB.

What must hold (each arm can ALONE go red):
  1. Conservation frame: thermo() returns phi >= 0, and heat_instant_phi <= phi — heat can
     never exceed flux (first law).
  2. A zero W is a MEASURED zero: G is a number (0.0) when phi and K exist, even with
     nothing shipped — None is reserved for unmeasurable denominators.
  3. Boundary law: value_flow() credits ONLY goals with done_at in-window — an unshipped
     goal's budget must never appear (anti-minting).
  4. K is frozen-definition and non-trivial: compressed < raw, both > 0.
  5. theil(): uniform shares → ~0; one-agent-takes-all → ~1; <2 shares → None (not 0 —
     a singleton has no inequality to measure).
  6. rollup() writes a row whose G/thermo agree with its own components (self-consistency
     of the archived artifact with the equations that made it).

Run: venv/bin/python nucleus/test_econ.py    (collected by check.sh)
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import psycopg  # noqa: E402

from nucleus import econ  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    with psycopg.connect(econ._dsn(), connect_timeout=5) as conn:
        now = datetime.now(timezone.utc)
        since = (now - timedelta(days=7)).isoformat()
        until = now.isoformat()

        t = econ.thermo(conn, since, until)
        check("phi >= 0 and is an int", isinstance(t["phi"], int) and t["phi"] >= 0)
        check("heat cannot exceed flux (first law)",
              t["heat_instant_phi"] <= t["phi"],
              f"heat={t['heat_instant_phi']} phi={t['phi']}")
        check("eta is None only when phi is 0",
              (t["eta"] is None) == (t["phi"] == 0))

        k = econ.k_bytes()
        check("K non-trivial: 0 < compressed < raw", 0 < k["compressed"] < k["raw"])

        # boundary law: a window in the far future has no shipped goals -> empty flow
        empty = econ.value_flow(conn, "2099-01-01", "2099-01-02")
        check("no value minted outside the boundary (future window empty)", empty == [])

        # theil arms
        check("theil uniform ~ 0", econ.theil([5, 5, 5, 5]) is not None
              and econ.theil([5, 5, 5, 5]) < 0.01)
        one_takes_all = econ.theil([100, 1e-9, 1e-9, 1e-9])
        check("theil one-takes-all ~ 1", one_takes_all is not None and one_takes_all > 0.9)
        check("theil singleton is None (no inequality to measure)",
              econ.theil([7]) is None)

        # trigger ROI: the demand half. roi must equal value - cost per row, value can
        # come ONLY from shipped funded goals (with none shipped in-window, every
        # value_reached is exactly 0 — the unpriced-market state market_decay guards on).
        roi = econ.trigger_roi(conn)
        check("trigger_roi returns rows", len(roi) > 0)
        check("roi == value_reached - cost on every row",
              all(int(r["roi"]) == int(r["value_reached"]) - int(r["cost"]) for r in roi))
        shipped = econ._one(conn, "SELECT count(*) FROM goals WHERE done_at > now() - "
                             "interval '30 days' AND budget_tokens > 0")
        if int(shipped[0]) == 0:
            check("unpriced market: all value_reached are 0 (nothing shipped in 30d)",
                  all(int(r["value_reached"]) == 0 for r in roi))
        else:
            check("priced market: total value_reached <= total shipped budgets",
                  sum(int(r["value_reached"]) for r in roi) <= int(econ._one(conn,
                      "SELECT coalesce(sum(budget_tokens),0) FROM goals WHERE done_at > "
                      "now() - interval '30 days'")[0]))

        # rollup self-consistency on yesterday (writes/updates one econ row)
        m = econ.rollup(conn)
        g, th, kk = m["G"], m["thermo"], m["K"]
        if th["phi"] and kk["compressed"]:
            expect = round(th["W"] / (th["phi"] * kk["compressed"]) * 1e9, 6)
            check("archived G equals its own components", g == expect,
                  f"G={g} expect={expect}")
            check("measured W=0 yields G=0.0, never None",
                  not (th["W"] == 0 and g is None))
        else:
            check("G is None exactly when a denominator is unmeasurable", g is None)
        row = conn.execute("SELECT metrics->'thermo'->>'phi' FROM econ ORDER BY day DESC "
                           "LIMIT 1").fetchone()
        check("econ row landed and carries thermo.phi", row is not None and row[0] is not None)

    print(f"\n{'FAILED (' + str(len(fails)) + '): ' + ', '.join(fails) if fails else 'all econ invariants hold'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
