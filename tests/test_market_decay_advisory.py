#!/usr/bin/env python3
"""Oracle for market_decay's FILE-BACKED → ADVISORY routing (triggers/steward/market_decay.py).

    venv/bin/python tests/test_market_decay_advisory.py    (also run by nucleus/check.sh)

THE GAP THIS PINS (2026-09-15). market_decay retired a trigger by setting triggers.enabled=false.
But a FILE-BACKED trigger (its check_src names an on-disk .py) is re-upserted enabled=true by
pulse.reconcile() every tick — so the kill only CHURNS (the ledger reads "retired" for a trigger
that never stops) — and market_decay is ITSELF file-backed, so the unconditional path made it
SELF-RETIRE. The fix routes file-backed candidates to ADVISORY (report the market verdict, route
the real remedy = remove the file or fund it; never flip enabled), reserving enabled=false for
DB-defined triggers where it durably sticks. The discriminator is check_src, which authoritatively
resolves the shared-runner-file case (run_backup -> org_runners.py::run_backup) a per-file check misses.

RED-FIRST: the pre-fix logic returned "retire" for a file-backed candidate (the self-retire/churn
bug). The load-bearing arm asserts the fixed _decide returns "advisory" there — a regression back to
unconditional retire fails it. Drives the PURE _decide/_is_file_backed, so no DB or clock needed.

Path-load the gitignored trigger body + skip-77 when absent (never static-import — fails deps.py's
clean-clone AST scan). Exit 0 pass · 1 fail · 77 could-not-run.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_SKIP = 77
fails = []

BODY = REPO / "triggers" / "steward" / "market_decay.py"
if not BODY.exists():
    print("SKIP: market_decay trigger absent (gitignored body, fresh clone) — nothing asserted.")
    sys.exit(EXIT_SKIP)
# REPO on sys.path so the path-loaded body's OWN first-party imports (from astryx import ...)
# resolve at exec time. This is a runtime sys.path insert, NOT a static `from triggers...`
# import node, so deps.py's clean-clone AST scan is unaffected (the whole point of path-load).
sys.path.insert(0, str(REPO))
try:
    _spec = importlib.util.spec_from_file_location("market_decay_under_test", BODY)
    m = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(m)
except Exception as e:  # noqa: BLE001 — absent/unimportable body => SKIP, not a false pass
    print(f"SKIP: market_decay not importable ({type(e).__name__}: {e}) — nothing asserted.")
    sys.exit(EXIT_SKIP)

dec = m._decide
fb = m._is_file_backed
FB_SRC = "triggers/steward/market_decay.py::market_decay"   # a real file-backed check_src


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


# ── _is_file_backed: the discriminator, incl the shared-runner-file gotcha ───────────────
check("per-trigger file is file-backed", fb(FB_SRC))
check("SHARED runner file is file-backed (org_runners.py gotcha — a per-file check misses this)",
      fb("triggers/steward/org_runners.py::run_backup"))
check("a SQL/DB-defined check is NOT file-backed", not fb("SELECT 1 FROM goals"))
check("a check_src naming a MISSING file is not file-backed", not fb("triggers/steward/nope.py::x"))
check("empty check_src is not file-backed", not fb(""))

# ── LOAD-BEARING RED-first: file-backed candidate -> ADVISORY, never the churn/self-retire ──
check("FILE-BACKED priced+unfunded -> ADVISORY (the fix; pre-fix returned 'retire' -> self-retire/churn)",
      dec(0, True, FB_SRC, True) == "advisory",
      "a market enabled=false on a file-backed trigger only churns back, and market_decay is "
      "itself file-backed so the old path self-retired it")

# ── controls: every other branch unchanged ──────────────────────────────────────────────
check("DB-defined priced+unfunded -> durable RETIRE", dec(0, True, "SELECT 1 FROM goals", True) == "retire")
check("premium>0 -> spare (funded, never retired)", dec(1_000_000, True, FB_SRC, True) == "spare")
check("W=0 window (no prices) -> report-only, never disable", dec(0, True, FB_SRC, False) == "report")
check("already enabled=false -> skip (a durable DB kill; don't re-announce)", dec(0, False, "SELECT 1", True) == "skip")

print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
print("market_decay routes file-backed->advisory (no churn/self-retire), DB-defined->durable retire")
sys.exit(0)
