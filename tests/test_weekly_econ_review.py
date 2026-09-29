#!/usr/bin/env python3
"""Oracle for weekly_economic_review — the banker's ledger-reading review layer
(triggers/steward/weekly_economic_review.py). Concurred by seed 2026-09-18 (thread
t-weekly-econ-review, msg 19713).

    venv/bin/python tests/test_weekly_econ_review.py    (also run by nucleus/check.sh)

THE GAP THIS PINS. econ_rollup COMPUTES the P&L nightly (Φ/W/K/G, per-trigger roi, per-agent
pnl → the econ table); nothing READS it to surface the banker duties the charter names. This
trigger is that reader. It sits a LAYER ABOVE market_decay (which is the sole ACTUATOR): the
review only SURFACES.

THREE LAYERS, different safety profiles (seed's split 19713; LAYER 3 added 2026-09-20):
  LAYER 2 — uninsured constitutive guards at reconcile-risk. Threshold: a trigger in the
    banker's CONSTITUTIVE manifest that is enabled ∧ premium=0 ∧ roi<0 → flagged AT-RISK with a
    prepared premium proposal (amount + value case + who prices it), so pricing them (the
    banker's "first act after reconcile") is fast, not scrambled. A FUNDED (premium>0)
    constitutive trigger is insured and must NOT be flagged. This is the standing form of the
    four seed hand-funded this week (medic/night-review, market_decay, econ_rollup, run_backup).
  LAYER 1 — per-agent P&L distribution, FYI ONLY, EXPLICITLY attribution-blind labeled, with NO
    deprecate/merge/retire implication. Attribution v1 is structurally blind to coordination/
    guard/review value (0/232 night-reviews carry a goal_id; every guard seat reads net-negative
    BY CONSTRUCTION), so a net-negative flag false-positives on exactly the agents doing
    invisible-but-real work. The rungs need attribution v2 before the signal may route toward
    removal. The review may only DISTRIBUTE the number, never verb it.
  LAYER 3 — RETIRED (goal 4227 S1b, owner law 2026-09-29: no budgets). It flagged active goals with
    no funder (the pricing worklist that fed the hibernated 4061 gate); with budgets gone "unpriced"
    is not a defect. ARM 5 now pins the RETIREMENT: no goals query, no L3 function, no L3 line, and
    no stale "market_decay has teeth" claim in the header.

RED-FIRST load-bearing arms (a plausible WRONG implementation fails each):
  1. a FUNDED constitutive trigger is NOT at-risk — a naive "flag every roi<0" impl fails this.
  2. an UNINSURED constitutive trigger IS at-risk WITH a non-empty prepared proposal (premium>0
     suggestion + route) — a summary-only impl that forgets the proposal fails this.
  3. a NEW uninsured non-manifest trigger surfaces ONCE for triage; a previously-SEEN one does
     not (completeness guard closes the manifest's fail-open, without droning the known set).
  4. the LAYER-1 render carries no removal verb (deprecate/merge/retire/fire/kill) — pins seed's
     rung-gating as an output polarity invariant, the flattering direction nobody reports.
  5. (LAYER 3) a NULL-funder goal fires (silent-NULL = the 3909 case) but a '(deferred:...)'
     sentinel SELF-SUPPRESSES (shown, not alarmed) — mutation: an impl that doesn't recognize the
     sentinel alarms on it.
  6. (ctx.sql SURFACE) arms 1-5 exercise the PURE helpers and never touch ctx.sql — but the
     2026-09-21 live crash lived THERE (a literal % in a LIKE, parsed as a placeholder because
     pulse_run's Ctx.sql calls execute(query, params=()) — a non-None params makes psycopg scan
     for %-placeholders; the pure arms stayed green through it). This arm invokes the ENTRYPOINT
     through pulse_run's OWN Ctx (imported, NOT re-implemented — a stand-in with a different
     execute() arity is exactly what masked the 09-21 dry-run), so a %-mismatch / bad-column /
     arg-count regression in any of the three ctx.sql queries reddens at GATE time, not
     firing-and-crashing the following Monday. RED-first discriminator: a literal-% query RAISES
     under the runner's real call, the safe left(col,N)= form does not. Read-only (SELECTs only);
     no DB reachable (clean clone / no .env) → the SQL arm SKIPS without failing, the pure arms stand.

Path-load the gitignored trigger body + skip-77 when absent (never static-import — fails
deps.py's clean-clone AST scan). Exit 0 pass · 1 fail · 77 could-not-run.
"""
import ast
import importlib.util
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_SKIP = 77
fails = []

BODY = Path(os.environ.get("WEEKLY_ECON_SRC", REPO / "triggers" / "steward" / "weekly_economic_review.py"))
if not BODY.exists():
    print("SKIP: weekly_economic_review trigger absent (gitignored body, fresh clone) — nothing asserted.")
    sys.exit(EXIT_SKIP)
# REPO on sys.path so the path-loaded body's OWN first-party imports (from astryx import ...)
# resolve at exec time — a runtime insert, NOT a static import node, so deps.py's clean-clone
# AST scan is unaffected (the whole point of path-load; see test_market_decay_advisory).
sys.path.insert(0, str(REPO))
try:
    _spec = importlib.util.spec_from_file_location("weekly_econ_review_under_test", BODY)
    m = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(m)
except Exception as e:  # noqa: BLE001 — absent/unimportable body => SKIP, not a false pass
    print(f"SKIP: weekly_economic_review not importable ({type(e).__name__}: {e}) — nothing asserted.")
    sys.exit(EXIT_SKIP)


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


# The manifest must be non-empty and every entry must carry a real proposal (amount + route +
# why) — a proposal with no amount is not "prepared".
MAN = m.CONSTITUTIVE
check("CONSTITUTIVE manifest is non-empty", len(MAN) > 0)
for key, spec in MAN.items():
    check(f"manifest[{key[0]}/{key[1]}] carries premium>0 + route + why",
          int(spec.get("premium", 0)) > 0 and bool(spec.get("route")) and bool(spec.get("why")),
          f"got {spec!r}")

# Pick a real manifest key to build fixtures around, so the test tracks the live manifest.
K = next(iter(MAN))                          # some (agent, name) the banker declared constitutive
NON = ("nobody", "not_a_real_trigger")       # guaranteed NOT in the manifest


def layer2(roi_by_key, tstate):
    return m.assess_layer2(roi_by_key, tstate, MAN)


# ── ARM 1 (load-bearing): FUNDED constitutive trigger is INSURED, never at-risk ──────────
res = layer2({K: -5_000_000}, {K: {"premium": 1_000_000, "enabled": True}})
check("ARM1 funded constitutive trigger is NOT at-risk (a naive 'flag every roi<0' fails this)",
      K not in {r["key"] for r in res["at_risk"]},
      f"at_risk={[r['key'] for r in res['at_risk']]}")
check("ARM1 funded constitutive trigger IS reported insured",
      K in res.get("insured", []))

# ── ARM 2 (load-bearing): UNINSURED constitutive trigger IS at-risk WITH a prepared proposal ─
res = layer2({K: -5_000_000}, {K: {"premium": 0, "enabled": True}})
hit = next((r for r in res["at_risk"] if r["key"] == K), None)
check("ARM2 uninsured constitutive trigger IS flagged at-risk", hit is not None)
check("ARM2 at-risk entry carries a PREPARED proposal (premium>0 + route + why)",
      bool(hit) and int(hit["proposal"]["premium"]) > 0
      and bool(hit["proposal"]["route"]) and bool(hit["proposal"]["why"]),
      f"entry={hit!r}")
check("ARM2 the proposed premium matches the banker's manifest declaration",
      bool(hit) and hit["proposal"]["premium"] == MAN[K]["premium"])

# control: a positive-roi uninsured constitutive trigger is NOT at-risk (roi<0 is the risk gate)
res = layer2({K: 5_000_000}, {K: {"premium": 0, "enabled": True}})
check("CONTROL constitutive trigger with roi>=0 is NOT at-risk (roi<0 is the reconcile-risk gate)",
      K not in {r["key"] for r in res["at_risk"]})

# control: a DISABLED uninsured constitutive trigger is NOT at-risk (already off; nothing to insure)
res = layer2({K: -5_000_000}, {K: {"premium": 0, "enabled": False}})
check("CONTROL disabled trigger is NOT at-risk", K not in {r["key"] for r in res["at_risk"]})

# ── ARM 2b: a manifest entry with a STANDING no-fund ruling is NOT a price-me candidate ──────
# (seed's session_refresh ruling, 19796: warn-only, no actuator → earns no premium; kept in the
# manifest so it is never mis-surfaced as new-unclassified, but routed OUT of at_risk.)
RULED = next((k for k, s in MAN.items() if s.get("ruled_unfunded")), None)
if RULED is not None:
    res = layer2({RULED: -5_000_000}, {RULED: {"premium": 0, "enabled": True}})
    check("ARM2b a ruled-unfunded manifest entry is NOT at-risk even at premium=0 ∧ roi<0",
          RULED not in {r["key"] for r in res["at_risk"]})
    check("ARM2b a ruled-unfunded entry IS reported in the ruled_unfunded bucket (not lost)",
          RULED in {r["key"] for r in res.get("ruled_unfunded", [])})
    check("ARM2b a ruled-unfunded entry is NOT treated as unclassified (stays a known row)",
          RULED not in m.new_unclassified({RULED}, MAN, seen=set()))

# ── ARM 3 (load-bearing): completeness — a NEW uninsured non-manifest trigger surfaces ONCE ──
uninsured = {NON}
fresh = m.new_unclassified(uninsured, MAN, seen=set())
check("ARM3 a NEW uninsured non-manifest trigger surfaces for triage (manifest can't fail open)",
      NON in fresh)
already = m.new_unclassified(uninsured, MAN, seen={NON})
check("ARM3 a previously-SEEN uninsured trigger does NOT re-surface (no drone on the known set)",
      NON not in already)
# a manifest trigger is never 'unclassified' even if somehow in the uninsured set
check("ARM3 a manifest trigger is never surfaced as unclassified",
      K not in m.new_unclassified({K}, MAN, seen=set()))

# ── ARM 4 (load-bearing): layer-1 is attribution-blind FYI, NO removal verb ──────────────
pnl = [{"agent": "seed", "burned": 8_000_000, "value_earned": 0, "net": -8_000_000, "turns": 14},
       {"agent": "steward", "burned": 2_000_000, "value_earned": 0, "net": -2_000_000, "turns": 11}]
line = m.render_layer1(pnl)
low = line.lower()
check("ARM4 layer-1 render is EXPLICITLY labeled attribution-blind",
      "attribution" in low and "blind" in low, f"render={line!r}")
FORBIDDEN = ("deprecate", "merge", "retire", " fire ", "kill", "remove the agent")
hit_verb = [v for v in FORBIDDEN if v in low]
check("ARM4 layer-1 render carries NO removal verb (seed's rung-gating; FYI-only)",
      not hit_verb, f"forbidden verbs present: {hit_verb}")

# ── ARM 5 (goal 4227 S1b): LAYER 3 is RETIRED, explicitly — not left running on dead columns ───────
# RED on the pre-S1b body: it defines assess_unfunded_goals and issues a goals/funded_by query. The
# construction half reads the body's executable strings (AST, docstrings excluded), so a comment or
# history note naming L3 does not trip it; a re-added query does.
check("ARM5 the LAYER-3 pricing function is gone (assess_unfunded_goals)",
      not hasattr(m, "assess_unfunded_goals"))
_tree = ast.parse(BODY.read_text())
_docs = {id(b[0].value) for b in [getattr(n, "body", None) for n in ast.walk(_tree)]
         if isinstance(b, list) and b and isinstance(b[0], ast.Expr)
         and isinstance(b[0].value, ast.Constant)}
_budget_era = sorted({n.lineno for n in ast.walk(_tree)
                      if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in _docs
                      and re.search(r"\bFROM\s+goals\b|funded_by|budget_tokens|LAYER-3|has teeth|PRICED",
                                    n.value)})
check("ARM5 no executable string reads goals/funded_by/budget_tokens or renders L3 / 'market PRICED' "
      "/ 'has teeth' (market_decay no longer retires)", not _budget_era, f"at lines {_budget_era}")

# ── ARM 6 (load-bearing): the ctx.sql SURFACE parses & executes under pulse_run's REAL call ──────
# Arms 1-4 never touch ctx.sql; the 09-21 crash did. Import pulse_run's OWN Ctx (execute(query,
# params=()) — the exact call whose %-parse crashed) rather than re-implement it: a stand-in with a
# different execute() arity is precisely what let the 09-21 dry-run pass while the pulse crashed.
# No DB / no .env (clean clone) → SKIP the SQL arm, keep the pure arms green.
try:
    _pr_spec = importlib.util.spec_from_file_location(
        "pulse_run_under_test", REPO / "nucleus" / "pulse_run.py")
    _pr = importlib.util.module_from_spec(_pr_spec)
    _pr_spec.loader.exec_module(_pr)      # reads .env for DSN at import — raises on a clean clone
    RunnerCtx = _pr.Ctx
except Exception as e:  # noqa: BLE001 — no runner/DSN/psycopg ⇒ skip the SQL arm, pure arms stand
    print(f"  SKIP  ARM6 ctx.sql surface — pulse_run/DSN unavailable ({type(e).__name__}: {e})")
    RunnerCtx = None

if RunnerCtx is not None:
    class RecordingCtx(RunnerCtx):       # faithful execute(query, params); records what was issued
        def __init__(self, state):
            super().__init__(state)
            self.queries = []
        def sql(self, query, params=()):
            self.queries.append(query)
            return super().sql(query, params)

    # (a) the live entrypoint parses & executes every query it reaches, end to end, no raise
    ctx = RecordingCtx({})
    try:
        out = m.weekly_economic_review(ctx)
        ran_ok, err = True, ""
    except Exception as e:  # noqa: BLE001 — a ctx.sql-surface regression surfaces HERE, at gate
        ran_ok, err, out = False, f"{type(e).__name__}: {e}", None
    check("ARM6a entrypoint runs end-to-end through pulse_run.Ctx — the ctx.sql surface parses & "
          "executes under the runner's real execute(query, params) signature", ran_ok, err)
    check("ARM6a entrypoint returns a review string or None (never a stray type)",
          out is None or isinstance(out, str), f"returned {type(out).__name__}")
    check("ARM6a reached at least the econ ledger query", len(ctx.queries) >= 1,
          f"queries issued: {len(ctx.queries)}")
    if out is not None:      # econ had a row ⇒ the entrypoint flowed through BOTH ctx.sql calls
        check("ARM6a with a populated ledger, both ctx.sql surfaces (econ, triggers) were parsed & "
              "executed — none silently skipped", len(ctx.queries) == 2,
              f"queries issued: {len(ctx.queries)}")

    # (b) RED-first discriminator: the SAME runner call RAISES on the literal-% form that crashed
    # 09-21 and does NOT raise on the safe left(col,N)= form. (The L3 query that needed it retired
    # in S1b; the arm stays as EXECUTOR insurance for any future prefix-matching query.) Proves the arm can
    # OBSERVE a %-regression — and that pulse_run.Ctx still passes params (drop params ⇒ no %-parse ⇒
    # this class stops being caught; this control reddens if the runner is ever "optimized" that way).
    ctx2 = RunnerCtx({})
    def _raises(q):
        try:
            ctx2.sql(q)      # params defaults to () — the runner's real call surface
            return False
        except Exception:
            return True
    check("ARM6b MUTANT: a literal-% query (LIKE '(deferred:%') RAISES under the runner's call — "
          "the arm can observe the 09-21 crash class", _raises("SELECT 1 AS x WHERE 'z' LIKE '(deferred:%'"))
    check("ARM6b CONTROL: the safe left(col,N)='prefix' form does NOT raise (the 09-21 fix shape)",
          not _raises("SELECT 1 AS x WHERE left('z',10)='(deferred:'"))
    for _c in (ctx, ctx2):
        try:
            if _c._conn is not None:
                _c._conn.close()
        except Exception:
            pass

print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
print("weekly_economic_review: L2 insures the constitutive trigger set with prepared proposals, "
      "completeness guard closes the manifest, L3 is retired (no budgets), "
      "L1 is attribution-blind FYI with no removal verb")
sys.exit(0)
