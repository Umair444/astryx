#!/usr/bin/env python3
"""Oracle for goal 11324 S1 (plan-11324 #57873, corrected by a2 #57895 / a4 #57896): the tool domain, and one id
per tool across the reorg AND the LEDGER_V bump.

`core` is a DOMAIN, never "resolved" (a3 HARD). The platform's servers are toolreg.CORE_SERVERS (the wire and
the door), read from toolreg and never re-typed in econ. Their calls leave tool GDP's denominator AND its value:
labelling them "resolved" would raise coverage with nothing fixed (econ: cov = min(qualified, 1 - unresolved)).

Arms:
  D1 CORE MARKED RESOLVED FAILS TO MOVE ANYTHING: core rows carrying a resolved author leave value and coverage
     exactly as if they were absent; marked 'unknown' they don't lower coverage either.
     Positive control: flipping an AGENT-authored row unknown → resolved DOES raise coverage.
  D2 THE SET IS TOOLREG'S: rebinding toolreg.CORE_SERVERS to ("astryx",) brings mcp:tools/* back into the
     domain (a literal re-typed in econ would not follow). Exact server match: mcp:toolsx/*, mcp:astryx2/* and
     script:src/astryx/* are agent-authored.
  D3 ONE DOMAIN FOR EVERY COUNT: the mirror and wash_detector's rings (both over econ._v2_counted) see no core
     pair; a window of only core calls is NOT_EVALUATED, never a measured 0. The domain is declared in the status.
  D4 VERSION: V2_VERSION moved past v2.1 (a v2.2 coverage isn't comparable with a v2.1 one) and passes its gate.
  T1 TRANSITION (executes, stamped fixture DB; a1): a LEDGER_V 1 call of script:nucleus/check.sh and a LEDGER_V 2
     call of script:devtools/check.sh (where it moved) are ONE id with ONE author, whether the author's Write
     was recorded at the old path or the new one; the two callers make two pairs of one tool, never two tools.
Seams: ECON_SRC (tests/mutants_econ_core_domain.py) and TOOLREG_SRC (tests/mutants_econ_core_domain_toolreg.py).
Exit 0 pass · 1 fail · 77 no DB (pure arms still asserted first).
"""
import contextlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
import importlib.util  # noqa: E402
_tr = os.environ.get("TOOLREG_SRC")   # mutation_probe's second seam: toolreg's canonical/authorship folds
if _tr:
    import astryx.core
    _tspec = importlib.util.spec_from_file_location("astryx.core.toolreg", _tr)
    _treg = importlib.util.module_from_spec(_tspec)
    sys.modules["astryx.core.toolreg"] = _treg     # econ imports it at call time: it gets this one
    _tspec.loader.exec_module(_treg)
    astryx.core.toolreg = _treg
_src = os.environ.get("ECON_SRC")   # mutation_probe's seam: the subject under test
if _src:
    _spec = importlib.util.spec_from_file_location("econ_under_test", _src)
    econ = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(econ)
else:
    from astryx.econ import econ  # noqa: E402
from astryx.core import toolreg  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def gdp(rows):
    g = econ._v2_tool_gdp(rows)
    return g["value"], g["coverage"]


# agent-authored rows: one resolved (steward's tool, used by forge), one unresolved (a pre-ledger file)
AGENT = [("script:devtools/fx_tool.sh", "forge", "steward", True),
         ("script:scripts/fx_old.sh", "forge", "unknown", True)]
CORE_PREFIXES = tuple(f"mcp:{s}/" for s in toolreg.CORE_SERVERS)   # re-derived here, never econ's own predicate
CORE_RESOLVED = [(f"mcp:{s}/fx_{i}", "forge", "seed", True) for s in toolreg.CORE_SERVERS for i in range(3)]
CORE_UNKNOWN = [(r, c, "unknown", q) for r, c, _, q in CORE_RESOLVED]

print("D1 CORE MARKED RESOLVED MOVES NOTHING:")
base = gdp(AGENT)
check("fixture: the agent-authored domain alone is PARTIAL-shaped (2 pairs, 1 of 2 authors resolved: coverage 0.5)",
      base == (2, 0.5), str(base))
check("core rows marked RESOLVED leave value AND coverage exactly as without them",
      gdp(AGENT + CORE_RESOLVED) == base, f"{gdp(AGENT + CORE_RESOLVED)} vs {base}")
check("core rows marked UNKNOWN don't lower coverage either (outside the domain both ways)",
      gdp(AGENT + CORE_UNKNOWN) == base, f"{gdp(AGENT + CORE_UNKNOWN)} vs {base}")
fixed = [AGENT[0], ("script:scripts/fx_old.sh", "forge", "memory", True)]
check("positive control: an AGENT-authored row resolved unknown → memory DOES raise coverage (0.5 → 1.0)",
      gdp(fixed) == (2, 1.0), str(gdp(fixed)))
check("...and core rows beside the fixed domain still add nothing", gdp(fixed + CORE_RESOLVED) == (2, 1.0),
      str(gdp(fixed + CORE_RESOLVED)))

print("\nD2 THE SET IS TOOLREG'S, MATCHED EXACTLY:")
check("toolreg.CORE_SERVERS is the wire and the door", tuple(toolreg.CORE_SERVERS) == ("astryx", "tools"),
      str(toolreg.CORE_SERVERS))
door = [("mcp:tools/fx_run", "forge", "seed", True)]
saved = toolreg.CORE_SERVERS
try:
    toolreg.CORE_SERVERS = ("astryx",)
    narrowed = gdp(AGENT + door)
finally:
    toolreg.CORE_SERVERS = saved
check("rebinding toolreg.CORE_SERVERS to ('astryx',) brings mcp:tools/* into the domain (econ reads the set, "
      "it doesn't re-type it)", narrowed == (3, round(1 - 1 / 3, 4)) and gdp(AGENT + door) == base,
      f"narrowed {narrowed}, restored {gdp(AGENT + door)}")
for rid in ("mcp:toolsx/fx", "mcp:astryx2/fx", "script:src/astryx/fx_core.py", "mcp:xastryx/fx"):
    check(f"{rid} is agent-authored (exact server match, not a prefix)",
          gdp(AGENT + [(rid, "forge", "seed", True)]) == (3, round(1 - 1 / 3, 4)),
          str(gdp(AGENT + [(rid, "forge", "seed", True)])))

print("\nD3 ONE DOMAIN FOR EVERY COUNT:")
counted = econ._v2_counted(AGENT + CORE_RESOLVED)
check("_v2_counted (the value's and wash_detector's edges) holds no core pair",
      not any(r.startswith(CORE_PREFIXES) for r, _, _ in counted) and len(counted) == 2, str(counted))
g = econ._v2_tool_gdp(AGENT + CORE_RESOLVED)
mir = econ._v2_mirror(AGENT + CORE_RESOLVED, g)
check("the mirror gives the core rows' author no entry", "seed" not in (mir["value"] or {}), str(mir["value"]))
from astryx.econ import wash_detector  # noqa: E402
ring = [("mcp:astryx/fx_a", "forge", "seed", True), ("script:devtools/fx_s.sh", "seed", "forge", True)]
check("a forge↔seed 'ring' that exists only through a core call is no ring",
      wash_detector.rings(AGENT + ring)["ring_pairs"] == 0, str(wash_detector.rings(AGENT + ring)))
only = econ._v2_tool_gdp(CORE_RESOLVED)
check("a window of only core calls is NOT_EVALUATED (value None), never a measured 0",
      only["value"] is None and only["status"].startswith("NOT_EVALUATED"), str(only))
check("the domain is declared in a PARTIAL status", g["status"].startswith("PARTIAL")
      and "core servers excluded" in g["status"], g["status"])
ok_st = econ._v2_tool_gdp(fixed)["status"]
check("...and in an OK one", ok_st.startswith("OK") and "core servers excluded" in ok_st, ok_st)
check("the record keeps the I1 shape (no fifth key)", set(g) == {"value", "version", "coverage", "status"},
      str(set(g)))

print("\nD4 VERSION:")
check("V2_VERSION moved past v2.1", econ._v2_ver(econ.V2_VERSION) > (2, 1), econ.V2_VERSION)
check("...and passes its own read gate", econ.v2_view({"v2": {"version": econ.V2_VERSION}}) is not None)


def sql_arms():
    try:
        import psycopg
        from astryx.econ.econ import _dsn
        live = psycopg.connect(_dsn(), autocommit=True, connect_timeout=5)
    except Exception as e:  # noqa: BLE001
        print(f"  SKIP  SQL arms — no DB ({type(e).__name__})")
        return False
    from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db
    stack = contextlib.ExitStack()
    try:
        try:
            fx = stack.enter_context(fixture_db())
        except FixtureUnavailable as e:
            check("the SQL arms have a fixture database", False, str(e))
            return True
        c = stack.enter_context(psycopg.connect(fx["dsn"], autocommit=True, connect_timeout=5))
        print("\nT1 TRANSITION (pre-bump and post-bump rows of one MOVED tool):")
        old, new = "script:nucleus/check.sh", "script:devtools/check.sh"
        check("fixture: nucleus/check.sh is a MOVED key, to devtools/check.sh",
              toolreg.canonical(old) == new, toolreg.canonical(old))
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        for where, wrote in (("the OLD path", old), ("the NEW path", new)):
            c.execute("DELETE FROM steps")
            tid = c.execute("INSERT INTO turns (agent, goal_id) VALUES ('fx-a', 7) RETURNING id").fetchone()[0]
            c.execute("INSERT INTO steps (agent, kind, content, meta) VALUES ('fx-author','tool','Write: fixture',%s::jsonb)",
                      (json.dumps({"edits": wrote, "v": 1}),))
            for caller, rid, v in (("fx-a", old, 1), ("fx-b", new, 2)):
                c.execute("INSERT INTO steps (agent, kind, content, meta, turn_id) VALUES (%s,'tool','call',%s::jsonb,%s)",
                          (caller, json.dumps({"registry_id": rid, "v": v}), tid))
            try:
                rows, ok = econ._v2_tool_rows(c, since, until)
                err = ""
            except Exception as e:  # noqa: BLE001
                rows, ok, err = [], False, f"{type(e).__name__}: {e}"
            check(f"[{where}] the ledger read executes against the real DDL", not err and ok, err)
            check(f"[{where}] a v1 row and a v2 row of one moved tool are ONE id",
                  {r[0] for r in rows} == {new} and len(rows) == 2, str(rows))
            check(f"[{where}] ...with ONE author, the agent whose Write came first",
                  {r[2] for r in rows} == {"fx-author"}, str(rows))
            g = econ._v2_tool_gdp(rows)
            check(f"[{where}] two callers of one tool = 2 pairs, coverage 1.0 (history doesn't split)",
                  (g["value"], g["coverage"]) == (2, 1.0), str(g))
        pub = live.execute("SELECT count(*) FROM steps WHERE agent IN ('fx-a','fx-b','fx-author')").fetchone()[0]
        check("CONTAINMENT: no fixture row leaked to the live database", pub == 0, str(pub))
        return True
    finally:
        stack.close()
        live.close()


ran = sql_arms()
print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
if not ran:
    print("SKIP (77): pure arms passed; the transition arm needs the org DB")
    sys.exit(77)
print("econ core domain: core servers are outside value and coverage (toolreg's set), one moved tool is one id "
      "with one author across the LEDGER_V bump")
sys.exit(0)
