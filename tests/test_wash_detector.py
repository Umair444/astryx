#!/usr/bin/env python3
"""Oracle for nucleus/wash_detector.py — the v2 RING detector (goal 4227 S1b).

v1's wash_detector (in the retired pay_the_author.py) flagged SELF-DEALT author credit: an author
paid for calling their own tool on their own budgeted goal. In v2 there is no budget to pay and
tool GDP already discounts self-use (econ._v2_counted drops caller == author), so that cycle
cannot inflate anything. The cycle that CAN is a RING: agents calling each other's tools so every
(tool, caller) pair counts as someone else's demand. This oracle pins the migrated detector.

Every load-bearing arm names the WRONG detector it would catch:
  1. A↔B reciprocal use IS a ring.                         (a no-op detector fails)
  2. one-way use is NOT a ring.                            (a "flag any cross-use" detector fails)
  3. a 3-cycle A→B→C→A IS a ring, as ONE component.        (a pairwise A↔B-only detector fails)
  4. self-use is not a counted pair.                       (a detector reading raw rows, not the
                                                            GDP-counted set, over-counts)
  5. a non-demand-qualified call is not an edge.           (same: it isn't in GDP, so it can't
                                                            inflate it)
  6. an unresolved author ('unknown'/None) is not an edge. (an edge to 'unknown' would merge every
                                                            unattributed tool into one fake ring)
  7. the ring's GDP share is (counted pairs inside rings) / (all counted pairs), and those pairs
     are a SUBSET of what econ counts — one definition (econ._v2_counted), no drift.
  8. no budget-era identifier in the module (AST) — v2 path.
  9. LIVE: the CLI executes its SQL against the real substrate (rc 0), or SKIPs 77 without it.
Exit 0 pass · 1 fail.
"""
import ast
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from nucleus import econ  # noqa: E402

# WASH_SRC=<path> overrides the subject (mutation_probe sets it); default is the tracked module.
SUBJECT = Path(os.environ.get("WASH_SRC") or REPO / "nucleus" / "wash_detector.py")
_spec = importlib.util.spec_from_file_location("wash_detector_under_test", SUBJECT)
wd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wd)

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def R(rid, caller, author, dq=True):
    return (rid, caller, author, dq)


def members(rows):
    return sorted(sorted(r["agents"]) for r in wd.rings(rows)["rings"])


print("RING ARMS:")
check("1 A↔B reciprocal use is a ring",
      members([R("t:a", "b", "a"), R("t:b", "a", "b")]) == [["a", "b"]])
check("2 one-way use (B uses A's tool only) is NOT a ring",
      members([R("t:a", "b", "a"), R("t:a", "c", "a")]) == [])
check("3 a 3-cycle A→B→C→A is ONE ring of three (pairwise-only detection misses it)",
      members([R("t:b", "a", "b"), R("t:c", "b", "c"), R("t:a", "c", "a")]) == [["a", "b", "c"]])
_self = wd.rings([R("t:a", "a", "a"), R("t:a", "b", "a"), R("t:b", "a", "b")])
check("4 self-use is not counted: ring {a,b} holds 2 pairs of 2, A's call to its own tool is not one",
      _self["counted_pairs"] == 2 and _self["ring_pairs"] == 2, f"{_self}")
check("5 a non-demand-qualified call is not an edge (it is not in GDP)",
      members([R("t:a", "b", "a"), R("t:b", "a", "b", dq=False)]) == [])
check("6 unresolved authors are not edges ('unknown'/None never merge into a fake ring)",
      members([R("t:x", "a", "unknown"), R("t:y", "b", "unknown"),
               R("t:z", "unknown", "a"), R("t:w", "c", None)]) == [])

print("\nSHARE ARMS:")
rows = [R("t:a", "b", "a"), R("t:b", "a", "b"),        # ring {a,b}: 2 counted pairs
        R("t:a", "c", "a"), R("t:a", "d", "a"),        # honest one-way use: 2 counted pairs
        R("t:a", "b", "a")]                            # a repeat call: same pair, counted once
out = wd.rings(rows)
check("7 share = ring pairs / all counted pairs (2/4), repeats counted once",
      out["ring_pairs"] == 2 and out["counted_pairs"] == 4 and out["share"] == 0.5, f"{out}")
gdp = econ._v2_tool_gdp(rows)["value"]
check("7 counted_pairs equals econ's tool-GDP value on the same rows (one definition, no drift)",
      out["counted_pairs"] == gdp, f"wash={out['counted_pairs']} econ={gdp}")
check("7 an empty window is status NOT_EVALUATED with share None, never a measured 0",
      wd.rings([])["share"] is None and wd.rings([])["status"].startswith("NOT_EVALUATED"))

print("\nV2 PATH:")
_tree = ast.parse(SUBJECT.read_text())
names = {n.id for n in ast.walk(_tree) if isinstance(n, ast.Name)}
names |= {n.attr for n in ast.walk(_tree) if isinstance(n, ast.Attribute)}
bad = names & {"budget_tokens", "budget", "value_flow", "funded_by", "AUTHOR_SHARE"}
check("8 no budget-era identifier in the module (AST names/attributes)", not bad, f"found {bad}")

print("\nLIVE:")
rc = wd.main([])
check("9 the CLI runs against the substrate (rc 0) or SKIPs (77) — never errors", rc in (0, 77), f"rc={rc}")

print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
print("wash_detector: rings over GDP-counted edges (incl. 3-cycles), share on econ's own count, v2 path")
sys.exit(0)
