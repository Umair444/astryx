#!/usr/bin/env python3
"""plan-11324 S3c (#58435, a3 #3): the components that iterate the cog's registry are DECLARED, and only the design's
cog-scoped set may open more than one org's DSN or key.

  S1 every tracked file (tests/ excluded; src/astryx/orgs.py is the registry itself) whose executable text iterates the
     registry (python `orgs.load(`, node `registry(`, the gateway's `cog()`) is declared in tests/cog_scope.json
  S2 every declared file still iterates it (no stale entry)
  S3 every `cog` role is in the design's declared cog-scoped set, written HERE from #58435's text (never read from
     the data file it judges): {bridges/gateway.py, observatory/api/main.py, init.sh, devtools/org_apply.py,
     devtools/org_parity.py}
  S4 RED controls: a planted bridges/fxcog.py calling orgs.load() is accused; a `cog` role outside the set is accused

STATED LIMITS: a file that iterates the registry by reading the JSON itself (json.load of the registry path) or through
an alias of orgs.load is not seen; the `resolver` role's "opens nothing" is the declaration's claim, read in review.
Seam: COG_SCOPE_SRC (a mutant cog_scope.json). Exit 0 · 1.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "devtools"))
from org_census import code_lines  # noqa: E402

DESIGN_COG = {"bridges/gateway.py", "observatory/api/main.py", "init.sh", "devtools/org_apply.py",
              "devtools/org_parity.py"}
ITER = re.compile(r"\borgs\.load\(|(?<![\w.])registry\(|(?<![\w.])cog\(\)")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def iterating(root: Path, extra: dict | None = None) -> dict:
    files = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True).stdout.split()
    out = {}
    for f in files + list(extra or {}):
        p = root / f
        if f.startswith("tests/") or f == "src/astryx/orgs.py" or not p.is_file():
            continue
        if p.suffix not in (".py", ".sh", ".mjs", ".js", ".ts", ".cjs"):
            continue
        hits = [n for n, code, _ in code_lines(p) if ITER.search(code)]
        if hits:
            out[f] = hits
    return out


def outside(decl: dict) -> list:
    return sorted(f for f, d in decl.items() if d.get("role") == "cog" and f not in DESIGN_COG)


def main():
    decl = json.loads(Path(os.environ.get("COG_SCOPE_SRC") or REPO / "tests" / "cog_scope.json").read_text())["files"]
    found = iterating(REPO)
    print("S1 EVERY REGISTRY ITERATOR IS DECLARED")
    check("every file that iterates the registry is in tests/cog_scope.json", not set(found) - set(decl),
          str({f: found[f] for f in set(found) - set(decl)}))
    print("\nS2 NO STALE DECLARATION")
    check("every declared file still iterates it", not set(decl) - set(found), str(sorted(set(decl) - set(found))))
    print("\nS3 ONLY THE DESIGN'S COG-SCOPED SET OPENS EVERY ORG")
    check("every `cog` role is in {gateway, observatory, init/apply/parity}", not outside(decl), str(outside(decl)))
    check("roles are resolver|cog", all(d.get("role") in ("resolver", "cog") for d in decl.values()),
          str({f: d.get("role") for f, d in decl.items()}))
    print("\nS4 RED CONTROLS")
    planted = REPO / "bridges" / "fxcog_planted.py"
    try:
        planted.write_text("from astryx import orgs\nfor o in orgs.load():\n    pass\n")
        got = iterating(REPO, {"bridges/fxcog_planted.py": 1})
    finally:
        planted.unlink(missing_ok=True)
    check("a planted bridges/fxcog_planted.py iterating orgs.load() is found (and undeclared)",
          "bridges/fxcog_planted.py" in got and "bridges/fxcog_planted.py" not in decl, str(sorted(got)))
    check("a `cog` role for bridges/whatsapp.py is accused", outside({**decl, "bridges/whatsapp.py": {"role": "cog"}})
          == ["bridges/whatsapp.py"])
    return 1 if fails else 0


if __name__ == "__main__":
    rc = main()
    print()
    print(f"FAILED ({len(fails)}): " + "; ".join(fails) if rc else
          "cog scope: every registry iterator is declared; only the design's cog-scoped set opens every org")
    sys.exit(rc)
