#!/usr/bin/env python3
"""Oracle for weekly_economic_review — the banker's ledger-reading review layer
(triggers/steward/weekly_economic_review.py). Concurred by seed 2026-09-18 (thread
t-weekly-econ-review, msg 19713).

    venv/bin/python tests/test_weekly_econ_review.py    (also run by nucleus/check.sh)

THE GAP THIS PINS. econ_rollup COMPUTES the P&L nightly (Φ/W/K/G, per-trigger roi, per-agent
pnl → the econ table); nothing READS it to surface the banker duties the charter names. This
trigger is that reader. It sits a LAYER ABOVE market_decay (which is the sole ACTUATOR): the
review only SURFACES.

TWO LAYERS, different safety profiles (seed's split, 19713):
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

RED-FIRST load-bearing arms (a plausible WRONG implementation fails each):
  1. a FUNDED constitutive trigger is NOT at-risk — a naive "flag every roi<0" impl fails this.
  2. an UNINSURED constitutive trigger IS at-risk WITH a non-empty prepared proposal (premium>0
     suggestion + route) — a summary-only impl that forgets the proposal fails this.
  3. a NEW uninsured non-manifest trigger surfaces ONCE for triage; a previously-SEEN one does
     not (completeness guard closes the manifest's fail-open, without droning the known set).
  4. the LAYER-1 render carries no removal verb (deprecate/merge/retire/fire/kill) — pins seed's
     rung-gating as an output polarity invariant, the flattering direction nobody reports.

Path-load the gitignored trigger body + skip-77 when absent (never static-import — fails
deps.py's clean-clone AST scan). Exit 0 pass · 1 fail · 77 could-not-run.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_SKIP = 77
fails = []

BODY = REPO / "triggers" / "steward" / "weekly_economic_review.py"
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

print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
print("weekly_economic_review: layer-2 insures the constitutive set with prepared proposals, "
      "completeness guard closes the manifest, layer-1 is attribution-blind FYI with no removal verb")
sys.exit(0)
