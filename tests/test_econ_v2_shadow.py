"""Oracle for goal-4227 S0 (econ side): the v2 SHADOW at econ.metrics->'v2'.

S0 is INSTRUMENT-ONLY: v2 is computed and archived beside v1, and nothing reads it yet
(the readers cut over at S2). So this oracle proves two things at once: the v2 records are
honest, and adding them changed NO v1 behaviour. Each arm can ALONE go red:

  1. SHAPE (I1): metrics['v2'] carries a version, and EVERY record under it is exactly
     {value, version, coverage, status}. coverage is None or in [0,1]; status is from the
     declared vocabulary. A record without coverage cannot be displayed honestly (S2 law).
  2. NO v1 BEHAVIOUR CHANGE: compute()'s v1 keys are exactly what they were, thermo is
     byte-identical to a direct thermo() call, and G still uses v1 W. market_decay's
     metrics->'thermo'->>'W' read path and econ_standing's `priced` see v1 unchanged, so
     neither actuator arms early (the ordering a1's F1 needs: S1b before S2).
  3. NO BUDGETS IN v2 (owner law, 2026-09-29): the v2 code path references no budget-era
     identifier (budget_tokens / funded_by / spent_tokens), checked on the SOURCE by AST,
     and v2.W re-derived independently from turns reproduces the record exactly.
  4. EFFORT SIDE IS THE BOUNDARY LAW IN EFFORT UNITS: v2.W = billable tokens on turns of
     goals that SHIPPED in-window AND went through plan quorum (approve rows on
     plan-<id>). Q = flux - W. coverage = goal-attributed flux / flux.
  5. TOOL GDP DEGRADES HONESTLY (I1): with no ledger rows (steps.meta has no registry_id)
     the record is value=None, coverage=0, status NOT_EVALUATED, never a measured 0.0.
     With ledger rows, the pure function evaluates it (demand-qualified distinct callers,
     self-use discounted, compression=1 declared). Both branches are driven through the
     pure core with fabricated rows, so the arm holds whichever branch the live DB is on.

Run: venv/bin/python tests/test_econ_v2_shadow.py    (collected by check.sh)
"""
import ast
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import psycopg  # noqa: E402

    from nucleus import econ  # noqa: E402
except ImportError as exc:
    print(f"SKIP: {exc} — no venv (fresh clone); the v2 oracle needs the org runtime")
    sys.exit(77)

fails = []
RECORD_KEYS = {"value", "version", "coverage", "status"}
STATUSES = {"OK", "PARTIAL", "VACUOUS", "NOT_EVALUATED"}
BUDGET_ERA = {"budget_tokens", "funded_by", "spent_tokens"}
V1_KEYS = {"thermo", "K", "G", "final_heat", "pnl", "theil_burn",
           "productivity", "trigger_roi", "integrity"}


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def _v2_source_names():
    """(fns, leaked) — the v2 code path is every function named v2*/_v2* PLUS every
    module-level constant named V2*/_V2* (SQL fragments like _V2_DEMAND live there).
    A budget leak hides INSIDE a SQL string, where it is a SUBSTRING, never an exact token:
    the first version of this probe intersected exact strings and a mutant that added
    `g.budget_tokens` to v2's SQL SURVIVED it. So identifiers are matched exactly and every
    string literal (incl. f-string parts) is searched by substring."""
    tree = ast.parse((REPO / "nucleus" / "econ.py").read_text())
    roots = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and (n.name.startswith("v2") or n.name.startswith("_v2"))]
    fns = list(roots)
    roots += [n for n in tree.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id.upper().startswith(("V2", "_V2"))
                      for t in n.targets)]
    idents, strings = set(), []
    for root in roots:
        for node in ast.walk(root):
            if isinstance(node, ast.Name):
                idents.add(node.id)
            elif isinstance(node, ast.Attribute):
                idents.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.append(node.value)
    leaked = (idents & BUDGET_ERA) | {b for b in BUDGET_ERA if any(b in s for s in strings)}
    return fns, leaked


def _ddl(name):
    """`CREATE TABLE IF NOT EXISTS <name> (...);` from schema.sql, COMMENT-AWARE: turns and
    steps carry `--` comments containing ');' (e.g. '-- FK to turns(id);'), which the naive
    first-');' extractor cuts mid-definition. Scan line by line on the code part only."""
    lines = (REPO / "nucleus" / "schema.sql").read_text().splitlines()
    start = next(i for i, l in enumerate(lines)
                 if l.startswith(f"CREATE TABLE IF NOT EXISTS {name} ("))
    out = []
    for l in lines[start:]:
        code = l.split("--", 1)[0].rstrip()
        out.append(code)
        if code.endswith(");"):
            return "\n".join(out)
    raise ValueError(f"unterminated DDL for {name}")


def demand_arm(dsn):
    import os
    import json as _json
    sch = f"t_v2d_{os.getpid()}"
    c = psycopg.connect(dsn, autocommit=True)
    try:
        c.execute(f"DROP SCHEMA IF EXISTS {sch} CASCADE")
        c.execute(f"CREATE SCHEMA {sch}")
        c.execute(f"SET search_path TO {sch}")   # SCH ONLY — never public
        for t in ("messages", "turns", "steps"):
            c.execute(_ddl(t))
        # case -> (from_agent, from_org or None=use the schema DEFAULT, goal_id, expect)
        cases = {
            "peer":  ("abstractor-1", None, None, False),   # intra-org peer: the gaming vector
            "owner": ("owner", None, None, True),
            "pulse": ("pulse", None, None, True),
            "human": ("someone", "whatsapp", None, True),   # channel row carries from_org
            "fed":   ("seed", "fedtest-x", None, True),     # a federated peer org
            "goal":  (None, None, 7, True),                 # no message; the turn served a goal
        }
        for name, (frm, org, gid, _) in cases.items():
            mid = None
            if frm:
                if org is None:
                    mid = c.execute("INSERT INTO messages (from_agent, to_agent, body) "
                                    "VALUES (%s,'caller','x') RETURNING id", (frm,)).fetchone()[0]
                else:
                    mid = c.execute("INSERT INTO messages (from_agent, from_org, to_agent, body) "
                                    "VALUES (%s,%s,'caller','x') RETURNING id", (frm, org)).fetchone()[0]
            tid = c.execute("INSERT INTO turns (agent, input_msg_id, goal_id) VALUES "
                            "('caller-'||%s, %s, %s) RETURNING id", (name, mid, gid)).fetchone()[0]
            c.execute("INSERT INTO steps (agent, kind, content, meta, turn_id) VALUES "
                      "('caller-'||%s, 'tool', 'call', %s::jsonb, %s)",
                      (name, _json.dumps({"registry_id": f"mcp:t/{name}"}), tid))
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        try:
            rows, _ = econ._v2_tool_rows(c, since, until)
            got = {rid.split("/")[-1]: dq for rid, _c, _a, dq in rows}
            err = ""
        except Exception as e:  # a SQL regression surfaces here, at gate time
            got, err = {}, f"{type(e).__name__}: {e}"
        check("demand reader EXECUTES against the real schema (no SQL error)", not err, err)
        for name, (_f, _o, _g, expect) in cases.items():
            check(f"demand[{name}] = {expect}", got.get(name) is expect, f"got {got.get(name)!r}")
        pub = c.execute("SELECT count(*) FROM public.steps WHERE content='call' "
                        "AND meta->>'registry_id' LIKE 'mcp:t/%%'").fetchone()[0]
        check("CONTAINMENT: no fixture row leaked to public.steps", pub == 0)
    finally:
        c.execute(f"DROP SCHEMA IF EXISTS {sch} CASCADE")
        c.close()


def main():
    try:
        dsn = econ._dsn()
    except Exception:
        print("SKIP: no .env in this tree (fresh clone) — the v2 oracle needs the live org DB")
        return 77
    try:
        conn = psycopg.connect(dsn, connect_timeout=5)
    except Exception as exc:
        print(f"SKIP: org DB unreachable ({type(exc).__name__}) — cannot observe the substrate")
        return 77

    # a real, complete window with traffic: yesterday UTC
    day = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    since = f"{day}T00:00:00+00:00"
    until = (datetime.fromisoformat(since) + timedelta(days=1)).isoformat()

    with conn:
        m = econ.compute(conn, since, until)

        # ── 1. SHAPE ────────────────────────────────────────────────────────────────
        v2 = m.get("v2")
        check("v2 shadow present under metrics['v2']", isinstance(v2, dict))
        if not isinstance(v2, dict):
            return 1
        check("v2 carries a schema version", isinstance(v2.get("version"), str) and v2["version"])
        recs = {k: r for k, r in v2.items() if k != "version"}
        check("v2 has records (W, Q, G, tool_gdp)", {"W", "Q", "G", "tool_gdp"} <= set(recs),
              str(sorted(recs)))
        for k, r in recs.items():
            check(f"v2.{k} is exactly {{value,version,coverage,status}}",
                  isinstance(r, dict) and set(r) == RECORD_KEYS, str(r))
            if isinstance(r, dict) and set(r) == RECORD_KEYS:
                cov = r["coverage"]
                check(f"v2.{k}.coverage is None or in [0,1]",
                      cov is None or (isinstance(cov, (int, float)) and 0 <= cov <= 1), str(cov))
                check(f"v2.{k}.status in the declared vocabulary",
                      str(r["status"]).split(":")[0] in STATUSES, str(r["status"]))
                check(f"v2.{k}.version matches v2", r["version"] == v2["version"])

        # ── 2. NO v1 BEHAVIOUR CHANGE ──────────────────────────────────────────────
        check("compute() v1 keys unchanged (only 'v2' added)",
              set(m) == V1_KEYS | {"v2"}, str(sorted(set(m) ^ (V1_KEYS | {"v2"}))))
        t = econ.thermo(conn, since, until)
        check("thermo is identical to a direct thermo() call (v2 did not touch v1)",
              m["thermo"] == t)
        k = m["K"]
        g_v1 = (round(t["W"] / (t["phi"] * k["compressed"]) * 1e9, 6)
                if t["phi"] and k["compressed"] else None)
        check("G is still the v1 formula over v1 W", m["G"] == g_v1, f"{m['G']} vs {g_v1}")

        # ── 3. NO BUDGETS IN v2 ────────────────────────────────────────────────────
        fns, leaked = _v2_source_names()
        check("v2 code path exists in econ.py (functions named v2*/_v2*)", bool(fns))
        check("v2 code path references NO budget-era identifier", not leaked, str(sorted(leaked)))

        # ── 4. EFFORT SIDE, re-derived independently ───────────────────────────────
        bill = econ.BILL
        flux = conn.execute(f"SELECT coalesce(sum({bill}),0)::bigint, "
                            f"coalesce(sum({bill}) FILTER (WHERE goal_id IS NOT NULL),0)::bigint "
                            f"FROM turns WHERE ended_at >= %s AND ended_at < %s",
                            (since, until)).fetchone()
        phi, phi_goal = int(flux[0]), int(flux[1])
        w_indep = int(conn.execute(f"""
            SELECT coalesce(sum({bill}),0)::bigint FROM turns t JOIN goals g ON g.id=t.goal_id
            WHERE g.done_at >= %s AND g.done_at < %s
              AND EXISTS (SELECT 1 FROM messages m
                          WHERE m.thread = 'plan-'||g.id AND m.intent='approve')""",
            (since, until)).fetchone()[0])
        check("v2.W = billable tokens on turns of quorum goals shipped in-window",
              v2["W"]["value"] == w_indep, f"{v2['W']['value']} vs {w_indep}")
        check("v2.Q = flux - W", v2["Q"]["value"] == phi - w_indep,
              f"{v2['Q']['value']} vs {phi - w_indep}")
        exp_cov = round(phi_goal / phi, 4) if phi else None
        check("v2.W.coverage = goal-attributed flux / flux", v2["W"]["coverage"] == exp_cov,
              f"{v2['W']['coverage']} vs {exp_cov}")

        # DISCRIMINATING WINDOWS. Yesterday usually ships nothing (W=0 under the right AND a
        # wrong derivation), so arm 4 alone could pass a mutant. Re-run it on the done-day
        # of (a) the newest quorum-shipped goal, where W must be > 0, and (b) the newest
        # goal shipped WITHOUT plan quorum, where the quorum filter must actually exclude
        # spend. Each window is chosen so right and wrong implementations DISAGREE.
        def _day_window(ts):
            d = ts.astimezone(timezone.utc).date().isoformat()
            s = f"{d}T00:00:00+00:00"
            return s, (datetime.fromisoformat(s) + timedelta(days=1)).isoformat()

        def _w(s, u, quorum):
            filt = ("AND EXISTS (SELECT 1 FROM messages m WHERE m.thread='plan-'||g.id "
                    "AND m.intent='approve')") if quorum else ""
            return int(conn.execute(f"""
                SELECT coalesce(sum({bill}),0)::bigint FROM turns t JOIN goals g ON g.id=t.goal_id
                WHERE g.done_at >= %s AND g.done_at < %s {filt}""", (s, u)).fetchone()[0])

        q_goal = conn.execute("""SELECT g.done_at FROM goals g WHERE g.done_at IS NOT NULL
            AND EXISTS (SELECT 1 FROM messages m WHERE m.thread='plan-'||g.id AND m.intent='approve')
            AND EXISTS (SELECT 1 FROM turns t WHERE t.goal_id=g.id)
            ORDER BY g.done_at DESC LIMIT 1""").fetchone()
        nq_goal = conn.execute("""SELECT g.done_at FROM goals g WHERE g.done_at IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.thread='plan-'||g.id AND m.intent='approve')
            AND EXISTS (SELECT 1 FROM turns t WHERE t.goal_id=g.id)
            ORDER BY g.done_at DESC LIMIT 1""").fetchone()
        check("a quorum-shipped goal with turns exists (discriminating window available)",
              q_goal is not None)
        if q_goal:
            s, u = _day_window(q_goal[0])
            wv = econ.v2(conn, s, u, k)["W"]["value"]
            check("on a quorum-ship day, v2.W > 0 and equals the independent derivation",
                  wv > 0 and wv == _w(s, u, True), f"{wv} vs {_w(s, u, True)} ({s[:10]})")
        if nq_goal:  # absent is not a failure — the org may have no non-quorum ship
            s, u = _day_window(nq_goal[0])
            wv = econ.v2(conn, s, u, k)["W"]["value"]
            check("on a NON-quorum-ship day, the quorum filter excludes that goal's spend",
                  wv == _w(s, u, True) and wv < _w(s, u, False),
                  f"v2={wv} quorum={_w(s, u, True)} unfiltered={_w(s, u, False)} ({s[:10]})")

    # ── 5. TOOL GDP degrade + evaluate, through the pure core ──────────────────────
    ver = v2["version"]
    empty = econ._v2_tool_gdp([], ver)
    check("tool_gdp with NO ledger rows is NOT_EVALUATED, value None, coverage 0",
          empty["value"] is None and empty["coverage"] == 0
          and str(empty["status"]).startswith("NOT_EVALUATED"), str(empty))
    rows = [  # (registry_id, caller, author, demand_qualified)
        ("tool-a", "p1", "forge", True),
        ("tool-a", "p2", "forge", True),
        ("tool-a", "p2", "forge", True),    # same caller twice → counts once (distinct callers)
        ("tool-a", "forge", "forge", True),  # author self-use → discounted
        ("tool-a", "p3", "forge", False),    # no real demand → not counted
        ("tool-b", "seed", None, True),      # author unknown → counted, never self-discounted
    ]
    live = econ._v2_tool_gdp(rows, ver)
    check("tool_gdp EVALUATES with ledger rows (OK or PARTIAL, never NOT_EVALUATED)",
          str(live["status"]).split(":")[0] in ("OK", "PARTIAL") and live["value"] is not None,
          str(live))
    unauth = econ._v2_tool_gdp(rows, ver, authorship_ok=False)
    check("tool_gdp with rows but NO authorship is NOT_EVALUATED (never an un-discounted number)",
          unauth["value"] is None and str(unauth["status"]).startswith("NOT_EVALUATED"), str(unauth))
    check("tool_gdp = distinct demand-qualified non-author callers, compression=1",
          live["value"] == 3, f"{live['value']} (expect tool-a:p1,p2 + tool-b:seed = 3)")
    check("tool_gdp coverage = demand-qualified share of calls", live["coverage"] == round(5 / 6, 4),
          str(live["coverage"]))

    # ── 5b. PARTIAL when authorship is unresolved (a2 #21324, honesty fix) ─────────
    check("tool_gdp with an 'unknown'/None author counted is PARTIAL, not OK",
          str(live["status"]).split(":")[0] == "PARTIAL", str(live))
    # DISCRIMINATING fixture: demand share 3/4 but author-resolved share 2/4, so min() and
    # a demand-only coverage DISAGREE (the 6-row fixture above has both at 5/6 — it cannot).
    mix = econ._v2_tool_gdp([("a", "p1", "forge", True), ("a", "p2", None, True),
                             ("a", "p3", "unknown", True), ("a", "p4", "forge", False)], ver)
    check("tool_gdp coverage = min(demand share, author-resolved share)",
          mix["coverage"] == 0.5, f"{mix['coverage']} (demand 0.75, resolved 0.5)")
    resolved = [r for r in rows if r[2] not in (None, "unknown")]
    full = econ._v2_tool_gdp(resolved, ver)
    check("tool_gdp with every counted author resolved is OK",
          str(full["status"]).split(":")[0] == "OK", str(full))
    unk = econ._v2_tool_gdp([("t", "p1", "unknown", True)], ver)
    check("the literal toolreg sentinel 'unknown' is treated as unresolved (PARTIAL)",
          str(unk["status"]).split(":")[0] == "PARTIAL", str(unk))

    # ── 6. Q IS A DAILY TRANSFER, conserved over windows (a2 #21324 note) ─────────
    conn = psycopg.connect(dsn, connect_timeout=5)   # psycopg3 `with conn:` CLOSED the first
    with conn:
        d1 = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()
        a0 = f"{d1}T00:00:00+00:00"
        a1 = (datetime.fromisoformat(a0) + timedelta(days=1)).isoformat()
        a2 = (datetime.fromisoformat(a0) + timedelta(days=2)).isoformat()
        va, vb, vab = (econ.v2(conn, a0, a1, k), econ.v2(conn, a1, a2, k), econ.v2(conn, a0, a2, k))
        check("W is additive over adjacent windows", va["W"]["value"] + vb["W"]["value"] == vab["W"]["value"])
        check("Q is conserved over adjacent windows (sum of daily Q = Q of the union)",
              va["Q"]["value"] + vb["Q"]["value"] == vab["Q"]["value"])
        check("Q's record SAYS it can be negative (no S2 reader may assume Q>=0)",
              "may be <0" in str(va["Q"]["status"]), str(va["Q"]["status"]))

    conn.close()

    # ── 7. THE DEMAND PREDICATE, EXECUTED (a2 #21324 blocker) ──────────────────────
    # Arm 5 fed the pure core PRE-COMPUTED booleans, so _V2_DEMAND's SQL never ran — and it
    # was a tautology (messages.from_org DEFAULTS to 'local', so `IS NOT NULL` qualified every
    # peer message). The 3rd instance of the ctx.sql-blindness class. Here the reader runs
    # for real against a HERMETIC temp schema built from schema.sql's own DDL (so the
    # load-bearing DEFAULT 'local' is the real one), search_path SCH-only (the 3833 scar).
    demand_arm(dsn)

    print()
    print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails
          else "econ v2 shadow: I1 records, v1 untouched, no budgets, effort re-derived, tool GDP degrades honestly")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
