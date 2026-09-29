#!/usr/bin/env python3
"""Oracle for market_decay's ROUTING (triggers/steward/market_decay.py) — O3, goal 4227 S1b.

    venv/bin/python tests/test_market_decay_advisory.py    (also run by nucleus/check.sh)

THE LAW THIS PINS (owner, 2026-09-29): no budgets, nothing enforced, NO trigger killing —
measure rent only. market_decay was the org's sole economic actuator: it set enabled=false on
DB-defined triggers with roi<0 ×3d ∧ premium=0 once W>0. Its roi is priced in budget_tokens,
so under v2 every trigger that fired would read roi<0 and the verb would retire the DB-defined
majority (plan-4227 F1, oracle O3: W>0 ∧ roi<0 ∧ premium=0 → NO enabled=false write).

TWO ARMS, deliberately of different kinds:
  1. BEHAVIOUR — _decide over the WHOLE input grid never yields a retire outcome.
  2. CONSTRUCTION — the body's executable strings (AST, not text: comments may say "UPDATE")
     contain no UPDATE/INSERT/DELETE. A behaviour arm only covers the routes _decide has; the
     construction arm catches a write re-added OUTSIDE _decide.
The end-to-end O3 arm (the entrypoint against a hermetic schema with W>0) lives in
tests/test_market_decay_sql_surface.py.

(History: until S1b this file pinned the 2026-09-15 FILE-BACKED→ADVISORY routing that stopped
market_decay self-retiring. With no retire verb at all, that distinction has nothing left to
route.)

MARKET_DECAY_SRC overrides the subject (the gitignored staging protocol, plan-4227 #21337:
review runs against the staged body). Path-load + skip-77 when absent (never static-import —
fails deps.py's clean-clone AST scan). Exit 0 pass · 1 fail · 77 could-not-run.
"""
import ast
import importlib.util
import itertools
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_SKIP = 77
fails = []

BODY = Path(os.environ.get("MARKET_DECAY_SRC", REPO / "triggers" / "steward" / "market_decay.py"))
if not BODY.exists():
    print("SKIP: market_decay trigger absent (gitignored body, fresh clone) — nothing asserted.")
    sys.exit(EXIT_SKIP)
sys.path.insert(0, str(REPO))
try:
    _spec = importlib.util.spec_from_file_location("market_decay_under_test", BODY)
    m = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(m)
except Exception as e:  # noqa: BLE001 — absent/unimportable body => SKIP, not a false pass
    print(f"SKIP: market_decay not importable ({type(e).__name__}: {e}) — nothing asserted.")
    sys.exit(EXIT_SKIP)


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


# ── 1. BEHAVIOUR: no input yields a retire ─────────────────────────────────────────────
# _decide's arity changed in S1b (priced/check_src no longer route anything); drive whatever
# arity it has with a grid over the values that used to reach "retire".
nargs = m._decide.__code__.co_argcount
grid = {"premium": (0, None, 1_000_000), "enabled": (True, False),
        "check_src": ("SELECT 1 FROM goals", "triggers/steward/market_decay.py::market_decay", ""),
        "priced": (True, False), "repo": (REPO,)}
names = m._decide.__code__.co_varnames[:nargs]
outs = {m._decide(*combo) for combo in itertools.product(*(grid.get(n, (None,)) for n in names))}
check("O3 _decide over the full grid (incl. W>0 ∧ roi<0 ∧ premium=0 ∧ DB-defined) never returns 'retire'",
      "retire" not in outs, f"outcomes={sorted(outs)}")
check("an unfunded enabled trigger is REPORTED (rent is measured, not dropped)",
      m._decide(*[{"premium": 0, "enabled": True}.get(n, grid.get(n, (None,))[0]) for n in names]) == "report")
check("premium>0 → spare", m._decide(*[{"premium": 1, "enabled": True}.get(n, grid.get(n, (None,))[0])
                                         for n in names]) == "spare")

# ── 2. CONSTRUCTION: no write statement anywhere in the body's executable strings ──────
tree = ast.parse(BODY.read_text())
_docs = {id(b[0].value) for b in [getattr(n, "body", None) for n in ast.walk(tree)]
         if isinstance(b, list) and b and isinstance(b[0], ast.Expr)
         and isinstance(b[0].value, ast.Constant)}
_WRITE = re.compile(r"\bUPDATE\s+\w+\s+SET\b|\bINSERT\s+INTO\b|\bDELETE\s+FROM\b", re.I)
writes = sorted(n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in _docs and _WRITE.search(n.value))
check("O3 by construction: no UPDATE/INSERT/DELETE string in the body (the retire verb and its "
      "wire notice are gone, not just unreached)", not writes, f"write strings at {writes}")

print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
print("market_decay reports rent and has no retire verb (O3: behaviour + construction)")
sys.exit(0)
