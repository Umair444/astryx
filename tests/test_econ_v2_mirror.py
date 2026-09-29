#!/usr/bin/env python3
"""Oracle for goal 4227 S2 — reads cut over to v2 behind a VERSION GATE; the [econ] mirror.

S2 per the approved design (#21236, with a1 #21233 edge c, a2 #21234 G1, a3 #21235 H2):
  - every reader takes a v2 record only at or above V2_MIN (the version gate, seed's ruling
    #21337): rows archived under v2.0 carry S0's tautological demand predicate (fixed in
    e36a66c) and the named-in-command over-count (fixed in acfc1ea), so they are never read;
  - tool GDP counts only ledger rows stamped with meta.v (forge #21604): an unstamped row is
    from before the call semantics were versioned;
  - the [econ] line is a SOFT ACTUATOR (it shapes what an agent does next without anyone reading
    it first). It mirrors the reader's OWN tools only: usage by OTHER agents, precomputed by the
    nightly rollup into v2.mirror, one row read per wake. Never a cross-agent rank, never a
    signed net, never another agent's name; "not evaluated" when the input is degenerate;
  - v1 is frozen and labeled budget-era wherever it is still shown.

Arms (RED on pre-S2 main: no V2_MIN / v2_view / _v2_mirror / econ_mirror, econ_line ignores
its input, the ledger read has no meta.v filter, econ_standing still ranks agents):
  1. VERSION GATE — v2_view returns None for a missing, garbage or v2.0 record; a record at
     V2_MIN or above passes; V2_VERSION itself passes its own gate.
  2. MIRROR (pure) — per-author, self-scoped: own tools used by OTHERS on demand; self-use,
     unqualified calls and unresolved authors never enter; a record names no other agent.
  3. LINE — None, a v1 standing dict, or a v2.0 record → the neutral token (a1's S1a arms stay
     true); NOT_EVALUATED → "not evaluated"; evaluated → the reader's own counts, an as-of day,
     the usage-GDP label; NEVER "rank", "net", a negative number, or another agent's name.
  4. NO RANK MACHINERY — econ_standing (the per-agent cross-agent rank) is gone.
  5. LEDGER FILTER (executes against a hermetic temp schema) — a row with meta.v is counted,
     an otherwise identical row without it is not.
  6. READER (executes) — econ_mirror reads the NEWEST econ row's v2 only; when that row is
     v2.0 the line is neutral even though an older row is v2.1 (no reaching back).
  7. WIRING — economy() and the observatory API go through v2_view and label v1 "budget-era"
     (AST: the call is made, the label is an executable string).
Exit 0 pass · 1 fail · 77 no DB (pure arms still asserted first).
"""
import ast
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
# ECON_SRC=<path> overrides the subject (mutation_probe sets it); default is the tracked module.
import importlib.util  # noqa: E402
_src = os.environ.get("ECON_SRC")
if _src:
    _spec = importlib.util.spec_from_file_location("econ_under_test", _src)
    econ = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(econ)
else:
    from nucleus import econ  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def has(name):
    ok = hasattr(econ, name)
    check(f"econ.{name} exists", ok)
    return ok


NEUTRAL = "[econ] between ships · no standing verdict"
AGENTS = ("forge", "seed", "abstractor-1", "canopus", "steward")

# ── 1. VERSION GATE ──────────────────────────────────────────────────────────────────────
print("1. VERSION GATE:")
if has("v2_view") and has("V2_MIN"):
    rec = lambda v: {"version": v, "W": {"value": 1}}  # noqa: E731
    for label, v2 in (("missing", None), ("no version", {"W": {}}), ("garbage", rec("banana")),
                      ("v2.0 (S0 tautology + over-count era)", rec("v2.0")), ("v1-shaped", rec("v1"))):
        check(f"v2_view rejects {label}", econ.v2_view({"v2": v2} if v2 is not None else {}) is None)
    check("v2_view accepts V2_VERSION (the writer passes its own gate)",
          econ.v2_view({"v2": rec(econ.V2_VERSION)}) is not None, econ.V2_VERSION)
    check("v2_view accepts a later minor (v2.9) — the gate is >=, not ==",
          econ.v2_view({"v2": rec("v2.9")}) is not None)
    check("V2_VERSION was bumped past v2.0", econ.V2_VERSION != "v2.0", econ.V2_VERSION)

# ── 2. MIRROR (pure) ─────────────────────────────────────────────────────────────────────
print("\n2. MIRROR:")
if has("_v2_mirror"):
    rows = [("t:f1", "seed", "forge", True), ("t:f1", "canopus", "forge", True),
            ("t:f2", "seed", "forge", True), ("t:f1", "seed", "forge", True),   # repeat
            ("t:f1", "forge", "forge", True),                                   # self-use
            ("t:f3", "seed", "forge", False),                                   # unqualified
            ("t:s1", "forge", "seed", True),
            ("t:u", "seed", "unknown", True), ("t:n", "seed", None, True)]      # unresolved
    gdp = econ._v2_tool_gdp(rows)
    mir = econ._v2_mirror(rows, gdp)
    by = (mir or {}).get("value") or {}
    check("mirror is an I1 record {value, version, coverage, status}",
          isinstance(mir, dict) and set(mir) == {"value", "version", "coverage", "status"}, str(mir))
    check("forge: 2 own tools used by 2 other agents over 3 pairs (self-use, unqualified, repeat out)",
          by.get("forge") == {"tools": 2, "callers": 2, "pairs": 3}, str(by.get("forge")))
    check("seed: 1 tool used by 1 other agent", by.get("seed") == {"tools": 1, "callers": 1, "pairs": 1},
          str(by.get("seed")))
    check("unresolved authors never get a mirror ('unknown'/None are not agents)",
          "unknown" not in by and None not in by, str(sorted(map(str, by))))
    check("a record names NO agent (self-scoped: counts only)",
          not any(a in json.dumps(r) for r in by.values() for a in AGENTS), str(by))
    check("mirror carries tool_gdp's status/coverage (PARTIAL here — unresolved authors counted)",
          (mir or {}).get("status", "").startswith("PARTIAL") and mir.get("coverage") == gdp["coverage"])
    dead = econ._v2_mirror([], econ._v2_tool_gdp([]))
    check("no ledger → mirror NOT_EVALUATED, value None (never an empty 'nobody used your tools')",
          dead.get("value") is None and dead.get("status", "").startswith("NOT_EVALUATED"), str(dead))

# ── 3. LINE ──────────────────────────────────────────────────────────────────────────────
print("\n3. LINE (soft actuator):")
line = econ.econ_line
v1_standing = {"day": "2026-09-29", "priced": True, "n": 9, "present": True, "net": -12345, "rank": 7}


def rec_for(version, status, mine, cov=0.8):
    return {"day": "2026-09-30", "version": version, "status": status, "coverage": cov, "mine": mine}


for label, inp in (("None", None), ("a v1 standing dict (a1's S1a fixture)", v1_standing),
                   ("a v2.0 record", rec_for("v2.0", "OK: x", {"tools": 3, "callers": 2, "pairs": 4}))):
    check(f"{label} → the neutral token", line(inp) == NEUTRAL, line(inp))
ne = line(rec_for(econ.V2_VERSION, "NOT_EVALUATED: ledger absent", None, 0))
check("NOT_EVALUATED → an explicit 'not evaluated' token", "not evaluated" in ne, ne)
ok = line(rec_for(econ.V2_VERSION, "OK: usage-GDP", {"tools": 3, "callers": 2, "pairs": 4}))
check("evaluated → the reader's own counts (3 tools, 2 other agents)",
      "3" in ok and "2" in ok and "usage-GDP" in ok, ok)
check("evaluated → carries its as-of day", "2026-09-30" in ok, ok)
none = line(rec_for(econ.V2_VERSION, "OK: usage-GDP", None))
check("evaluated, no own tool used → says so (a measurement, not silence)", "no tool of yours" in none,
      none)
part = line(rec_for(econ.V2_VERSION, "PARTIAL: authors unresolved", {"tools": 1, "callers": 1, "pairs": 1}))
check("PARTIAL is shown as PARTIAL", "PARTIAL" in part, part)
for label, s in (("OK", ok), ("none", none), ("PARTIAL", part), ("NOT_EVALUATED", ne)):
    check(f"{label} line: no rank, no net, no negative number, no other agent's name",
          "rank" not in s.lower() and "net" not in s.lower().replace("network", "")
          and not re.search(r"(?<![\d-])-\s?\d", s)
          and not any(a in s for a in AGENTS), s)   # the minus lookbehind skips dates

# ── 4. NO RANK MACHINERY ─────────────────────────────────────────────────────────────────
print("\n4. NO RANK MACHINERY:")
check("econ_standing (the cross-agent rank) is gone", not hasattr(econ, "econ_standing"))

# ── 7. WIRING (static) ───────────────────────────────────────────────────────────────────
print("\n7. WIRING:")
for rel in ("mcp/org/server.py", "observatory/api/main.py"):
    tree = ast.parse((REPO / rel).read_text())
    calls = any(isinstance(n, ast.Call) and (getattr(n.func, "attr", None) == "v2_view"
                                             or getattr(n.func, "id", None) == "v2_view")
                for n in ast.walk(tree))
    label = any(isinstance(n, ast.Constant) and isinstance(n.value, str) and "budget-era" in n.value
                for n in ast.walk(tree))
    check(f"{rel} reads v2 through v2_view (the gate)", calls)
    check(f"{rel} labels v1 'budget-era' in an executable string", label)
hook = (REPO / "hooks" / "usage.py").read_text()
check("hooks/usage.py renders the mirror (econ_mirror → econ_line)",
      "econ_mirror" in hook and "econ_line" in hook)


# ── 5/6. SQL arms against a hermetic temp schema ─────────────────────────────────────────
def _ddl(name):
    text = (REPO / "nucleus" / "schema.sql").read_text()
    i = text.index(f"CREATE TABLE IF NOT EXISTS {name} (")
    return text[i:text.index("\n);", i) + 3]


def sql_arms():
    try:
        import psycopg
        from nucleus.econ import _dsn    # the REPO's .env — a path-loaded subject lives elsewhere
        dsn = _dsn()
        c = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    except Exception as e:  # noqa: BLE001
        print(f"  SKIP  SQL arms — no DB ({type(e).__name__})")
        return False
    sch = f"t_v2m_{os.getpid()}"
    try:
        c.execute(f"DROP SCHEMA IF EXISTS {sch} CASCADE")
        c.execute(f"CREATE SCHEMA {sch}")
        c.execute(f"SET search_path TO {sch}")      # SCH ONLY — never public
        for t in ("messages", "turns", "steps", "econ"):
            c.execute(_ddl(t))
        print("\n5. LEDGER FILTER:")
        tid = c.execute("INSERT INTO turns (agent, goal_id) VALUES ('caller', 7) RETURNING id").fetchone()[0]
        for rid, meta in (("mcp:t/stamped", {"registry_id": "mcp:t/stamped", "v": 1}),
                          ("mcp:t/unstamped", {"registry_id": "mcp:t/unstamped"})):
            c.execute("INSERT INTO steps (agent, kind, content, meta, turn_id) VALUES "
                      "('caller','tool','call',%s::jsonb,%s)", (json.dumps(meta), tid))
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        try:
            rows, _ = econ._v2_tool_rows(c, since, until)
            got, err = {r[0] for r in rows}, ""
        except Exception as e:  # noqa: BLE001
            got, err = set(), f"{type(e).__name__}: {e}"
        check("the ledger read executes against the real DDL", not err, err)
        check("a meta.v-stamped call is counted", "mcp:t/stamped" in got, str(got))
        check("an UNSTAMPED call is not (pre-versioning call semantics)", "mcp:t/unstamped" not in got,
              str(got))

        print("\n6. READER:")
        if hasattr(econ, "econ_mirror"):
            good = {"version": econ.V2_VERSION, "mirror": {"value": {"steward": {"tools": 1, "callers": 1,
                    "pairs": 1}}, "version": econ.V2_VERSION, "coverage": 1, "status": "OK: x"}}
            old = {"version": "v2.0", "mirror": good["mirror"]}
            c.execute("INSERT INTO econ (day, metrics) VALUES ('2026-09-01', %s::jsonb), "
                      "('2026-09-02', %s::jsonb)", (json.dumps({"v2": good}), json.dumps({"v2": old})))
            try:
                st, err = econ.econ_mirror(c, "steward"), ""
            except Exception as e:  # noqa: BLE001
                st, err = None, f"{type(e).__name__}: {e}"
            check("econ_mirror executes against the real DDL", not err, err)
            check("newest row is v2.0 → the line is NEUTRAL (the gate holds; no reaching back to "
                  "an older v2.1 row)", econ.econ_line(st) == NEUTRAL, f"{st} → {econ.econ_line(st)}")
            c.execute("INSERT INTO econ (day, metrics) VALUES ('2026-09-03', %s::jsonb)",
                      (json.dumps({"v2": good}),))
            st = econ.econ_mirror(c, "steward")
            check("newest row at V2_MIN+ → the reader's own mirror, as-of that day",
                  (st or {}).get("mine") == {"tools": 1, "callers": 1, "pairs": 1}
                  and (st or {}).get("day") == "2026-09-03", str(st))
        pub = c.execute("SELECT count(*) FROM public.steps WHERE meta->>'registry_id' LIKE 'mcp:t/%%'"
                        ).fetchone()[0]
        check("CONTAINMENT: no fixture row leaked to public", pub == 0)
        return True
    finally:
        c.execute(f"DROP SCHEMA IF EXISTS {sch} CASCADE")
        c.close()


ran = sql_arms()
print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
if not ran:
    print("SKIP (77): pure arms passed; the SQL arms need the org DB")
    sys.exit(77)
print("econ v2 S2: reads gated at V2_MIN, ledger filtered on meta.v, [econ] mirrors only your own "
      "tools — no rank, no net, no one else's name")
sys.exit(0)
