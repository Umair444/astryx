#!/usr/bin/env python3
"""Oracle: the registry door's find() ranks the tool a question is ABOUT (toolreg, goal 4227 S4).

    venv/bin/python tests/test_toolreg_find.py         (also run by nucleus/check.sh)
    TOOLREG_SRC=<path> …                               (the subject; mutation_probe sets it)

steward's report (#25795): "is the org healthy" returned list_models and dag_list, and not the
org-vitals skill whose header says "health". Two defects: SUBSTRING matching, where "is" hit
"list" and one-way containment meant "healthy" never matched "health", and no weighting, so
"org", which is in most descriptions, counted as much as "health", which is in one.

A FIXTURE registry, so the verdict doesn't move as the live one grows. entries() is patched,
which lets the same oracle run against the pre-fix find() and prove it RED.

  F1 steward's case: "is the org healthy" returns ONLY the health tool
  F2 inflection: "healthy" finds "health"; a 4+ character prefix matches either way
  F3 whole tokens: a short word never matches INSIDE another ("ist" is not in "list")
  F4 a stopword-only question returns nothing
  F5 rarity: a common word ranks below a rare one ("org dag" puts the DAG tool first)
  F7 a TIE goes to the tool whose own ID holds the words, not to one whose description merely
     mentions them, even when the mentioner sorts first alphabetically (abstractor-4: "list
     models" put imagegen/generate above imagegen/list_models)
  F6 a match on common words alone is dropped when a far stronger match exists, but a query of
     only that common word still returns its matches
"""
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("TOOLREG_SRC") or REPO / "nucleus" / "toolreg.py")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


spec = importlib.util.spec_from_file_location("toolreg_find_under_test", SRC)
toolreg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(toolreg)


def E(i, d):
    return {"id": i, "kind": "script", "description": d}


# "org" and "astryx" are COMMON here, as in the live registry: 12 fillers carry both.
POOL = [
    E("script:skills/vitals.sh", "astryx · org vitals — one read-only health pass"),
    E("mcp:compose/dag_list", "List the org's composite DAGs"),
    E("mcp:imagegen/list_models", "Image models visible to the org's key"),
    E("script:nucleus/rung.py", "astryx · org rung ladder"),
] + [E(f"script:nucleus/filler{i}.py", f"astryx · org utility number {i}") for i in range(12)]
toolreg.entries = lambda: POOL


def ids(q, limit=10):
    return [e["id"] for e in toolreg.find(q, limit)]


got = ids("is the org healthy")
check("F1 'is the org healthy' → ONLY the health tool", got == ["script:skills/vitals.sh"], str(got))

got = ids("healthy")
check("F2 'healthy' finds the tool described as 'health'", got == ["script:skills/vitals.sh"], str(got))
got = ids("heal")
check("F2 a 4-char prefix matches ('heal' → 'health')", got == ["script:skills/vitals.sh"], str(got))

got = ids("ist")
check("F3 a short word never matches inside another ('ist' is not in 'list')", got == [], str(got))
got = ids("run")
check("F3 under 4 chars it's exact tokens only ('run' is not 'rung')", got == [], str(got))

got = ids("is the a of what how")
check("F4 a stopword-only question returns nothing", got == [], str(got))

got = ids("org dag")
check("F5 the rare word leads: 'org dag' puts the DAG tool first",
      bool(got) and got[0] == "mcp:compose/dag_list", str(got))

got = ids("org health", limit=50)
check("F6 common-word-only matches are dropped when a far stronger match exists",
      got == ["script:skills/vitals.sh"], str(got))
got = ids("org", limit=50)
check("F6 ...but a query of ONLY the common word still returns its matches",
      len(got) == 16, f"{len(got)} results")

# F7: identical scores (both descriptions carry both words once). "aaa…" sorts first alphabetically.
TIE = [E("mcp:img/aaa_generate", "make images; returns a list of model ids"),
       E("mcp:img/list_models", "which image model ids are visible")] + \
      [E(f"script:nucleus/pad{i}.py", "astryx utility") for i in range(10)]
toolreg.entries = lambda: TIE
got = ids("list models")
check("F7 a tie goes to the tool whose ID holds the words, not a description mention",
      bool(got) and got[0] == "mcp:img/list_models", str(got))
toolreg.entries = lambda: POOL

if fails:
    print(f"\nFAIL: {len(fails)} find() invariant(s) broken")
    sys.exit(1)
print("\nPASS: find() ranks the tool a question is about")
