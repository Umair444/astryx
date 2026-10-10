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
     of the archived artifact with the equations that made it) — into a stamped FIXTURE
     database seeded with one billable turn; the live econ table must be untouched (containment).

Run: venv/bin/python tests/test_econ.py    (collected by check.sh)
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import psycopg  # noqa: E402

    from nucleus import econ  # noqa: E402
except ImportError as exc:
    # a bare clone/CI runs the system python (no venv): the oracle cannot even load its
    # instruments, let alone observe the substrate — SKIP, same law as the missing .env
    print(f"SKIP: {exc} — this tree has no venv (fresh clone); the econ oracle needs the org runtime")
    sys.exit(77)

fails = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    # CLONE-SKIP (house law: a SKIP is not a PASS, and not a FAIL): this oracle's substrate
    # is the live org DB, reached via the gitignored .env. In a fresh clone (CI, the push
    # gate) neither exists — the gate cannot OBSERVE what it covers, so it names itself
    # SKIPPED at 77 rather than red (which would block every normal clone) or green
    # (which would vouch for nothing).
    try:
        dsn = econ._dsn()
    except Exception:
        print("SKIP: no .env in this tree (fresh clone) — the econ oracle needs the live org DB")
        return 77
    try:
        probe = psycopg.connect(dsn, connect_timeout=5)
    except Exception as exc:
        print(f"SKIP: org DB unreachable ({type(exc).__name__}) — cannot observe the substrate")
        return 77
    probe.close()
    with psycopg.connect(dsn, connect_timeout=5) as conn:
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

        # rollup self-consistency on yesterday, archived into a stamped FIXTURE database
        # (nucleus/sqlguard/fixture.py: schema.sql applied whole), never the live one. Until goal
        # 4227 S2 this upserted PRODUCTION econ with whatever code ran the suite (steward did exactly
        # that on 09-29); S2 moved it to a temp schema on the live DB, and the 4227 close tripped
        # R-EXTRACT on that schema's own CREATE TABLE. The fixture is seeded with ONE billable turn
        # yesterday and no shipped goal, so both value arms run every time instead of riding
        # whatever the live substrate holds: phi > 0 with W = 0 must archive G = 0.0, and G must
        # equal its own components.
        import json
        from nucleus.sqlguard.fixture import FixtureUnavailable, fixture_db
        live_before = conn.execute("SELECT computed_at FROM public.econ ORDER BY day DESC "
                                   "LIMIT 1").fetchone()
        yday = now.date() - timedelta(days=1)
        ended = datetime(yday.year, yday.month, yday.day, 12, tzinfo=timezone.utc)
        try:
            with fixture_db() as fx, psycopg.connect(fx["dsn"], connect_timeout=5) as fc:
                fc.execute("INSERT INTO turns (agent, ended_at, raw_payload) VALUES ('fx-agent', %s, %s::jsonb)",
                           (ended, json.dumps({"usage": {"billable_equiv_in": 1000}})))
                fc.commit()
                m = econ.rollup(fc)
                g, th, kk = m["G"], m["thermo"], m["K"]
                check("the seeded fixture day is MEASURED (phi = the one turn's 1000, K compressed > 0)",
                      th["phi"] == 1000 and kk["compressed"] > 0, f"phi={th['phi']} K={kk.get('compressed')}")
                if th["phi"] and kk["compressed"]:
                    expect = round(th["W"] / (th["phi"] * kk["compressed"]) * 1e9, 6)
                    check("archived G equals its own components", g == expect,
                          f"G={g} expect={expect}")
                    check("measured W=0 yields G=0.0, never None", th["W"] == 0 and g == 0.0,
                          f"W={th['W']} G={g}")
                row = fc.execute("SELECT metrics->'thermo'->>'phi' FROM econ ORDER BY day "
                                 "DESC LIMIT 1").fetchone()
                check("econ row landed (fixture table) and carries thermo.phi",
                      row is not None and row[0] is not None)
                bf = fc.execute("SELECT metrics->'built_from' FROM econ ORDER BY day DESC "
                                "LIMIT 1").fetchone()
                bf = bf[0] if bf else None
                check("the archived row carries its provenance (built_from: sha + dirty, detection-grade)",
                      isinstance(bf, dict) and bool(bf.get("sha")) and isinstance(bf.get("dirty"), bool),
                      str(bf))
        except FixtureUnavailable as e:
            check("the rollup arm has a fixture database", False, str(e))
        live_after = conn.execute("SELECT computed_at FROM public.econ ORDER BY day DESC "
                                  "LIMIT 1").fetchone()
        check("CONTAINMENT: the live econ table was not written by this oracle",
              live_before == live_after, f"{live_before} -> {live_after}")

        # goal 4227 S2: the cross-agent rank (econ_standing) is gone; the [econ] line is the
        # self-scoped v2 mirror, pinned by tests/test_econ_v2_mirror.py.
        check("no cross-agent rank function remains (econ_standing retired at S2)",
              not hasattr(econ, "econ_standing"))

    print(f"\n{'FAILED (' + str(len(fails)) + '): ' + ', '.join(fails) if fails else 'all econ invariants hold'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
