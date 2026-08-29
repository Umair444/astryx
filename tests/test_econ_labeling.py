#!/usr/bin/env python3
"""Labeling-parity oracle for the 3499 economy-integrity CORE — the honest-posture half.

3499 ships ATTRIBUTION, not prevention, so the load-bearing deliverable is that no W-bearing
surface CLAIMS more than attribution buys. Every place that defines or exposes W must say, in
words, that the boundary is forgeable by a genesis superuser (attribution-grade, not
tamper-proof), name funded_by as the funder-attribution, and point at 3499 for the deferred
prevention — and the whole W-bearing SET (a1's build-critical note: not done_at alone) must be
named, because a reader who thinks done_at is the only forgeable surface is exactly wrong.

This is a drift guard: it fails RED if a surface loses its honest label, if the removed pure
overclaim ("cannot be backdated") ever returns, or if a new W surface ships unlabeled. Pure
stdlib, no DB. Run by check.sh.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
fails: list[str] = []


def want(label, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        fails.append(label)


def read(rel):
    p = REPO / rel
    if not p.exists():
        print(f"SKIP: {rel} absent")
        sys.exit(77)
    return p.read_text()


schema = read("nucleus/schema.sql").lower()
econ = read("nucleus/econ.py").lower()
org = read("mcp/org/server.py").lower()

# ── every W-bearing surface carries the honest attribution-grade label + points at 3499 ──
for name, src in (("schema.sql goals.done_at", schema), ("econ.py W", econ),
                  ("economy() glossary", org)):
    want(f"{name}: labeled ATTRIBUTION-grade", "attribution" in src)
    want(f"{name}: points at goal 3499 for the deferred prevention", "3499" in src)
    want(f"{name}: names the forge (superuser/forge-able, not tamper-proof)",
         "superuser" in src or "forge" in src)

# ── funded_by named as the funder-attribution mechanism where W is defined/exposed ──
want("econ.py names funded_by as the funder-attribution", "funded_by" in econ)
want("economy() names funded_by as the funder-attribution", "funded_by" in org)

# ── the WHOLE W-bearing set is named, not done_at alone (a1's build-critical requirement) ──
def names_whole_set(src):
    return all(t in src for t in ("done_at", "turns.agent", "quorum")) and \
        ("econ.metrics" in src or "rollup" in src or "econ table" in src)


want("the whole W-bearing set is enumerated on at least one surface "
     "(done_at + econ rollup + turns.agent + messages/quorum)",
     names_whole_set(econ) or names_whole_set(org))

# ── the removed pure overclaim must never return (RED-able against the pre-fix schema) ──
want("schema.sql no longer claims done_at 'cannot be backdated' (the pure overclaim)",
     "cannot be backdated" not in schema)
want("econ.py does not assert 'nothing internal can mint it' as a bare guarantee "
     "(only as the stated GOAL)", "nothing internal can mint it" not in econ or "the goal" in econ)

print()
if fails:
    print(f"test_econ_labeling: {len(fails)} FAIL — {fails}")
    sys.exit(1)
print("test_econ_labeling: ALL PASS — every W-bearing surface labeled attribution-grade, whole set named")
sys.exit(0)
