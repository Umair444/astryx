#!/usr/bin/env python3
"""Guard + oracle: no COMMITTED .py statically imports a gitignored `triggers.` module.

THE RECURRING TRAP (seen 3× on 2026-09-14 — deps.py's own comment, test_usage_poll,
test_owner_queue_age). An oracle for a trigger naturally wants to import it:

    from triggers.steward.owner_queue_age import _age_uncommitted   # WRONG in a committed file

But `triggers/` is gitignored, so in a fresh clone (the pushed-tree gate, CI) it is EMPTY —
and deps.py stops recognizing `triggers` as a first-party package (it keys first-party on a
dir HAVING .py on disk). So the import reads as an UNMANIFESTED THIRD-PARTY dep → the
`dep manifest covers all imports` gate FAILS the push, with an error that points at the
manifest, not at the real cause. (And at runtime the module is absent → the test crashes
instead of skipping.) A try/except around the import does NOT help: deps.py is a STATIC AST
scan; the guard has to be on the LOAD MECHANISM.

THE FIX this guard points at: load the gitignored body BY PATH and SKIP-77 when absent —

    import importlib.util
    BODY = REPO / "triggers" / "steward" / "owner_queue_age.py"
    if not BODY.exists(): print("SKIP: ..."); sys.exit(77)
    spec = importlib.util.spec_from_file_location("m", BODY); m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

— the precedent is tests/test_spawn_drift.py. This guard is STATIC (scans committed source,
needs no gitignored body), so it runs identically on a live host and in a bare clone.
"""
import ast
import subprocess
import sys
import warnings
from pathlib import Path

# some committed files carry invalid-escape regexes; parsing them emits SyntaxWarning that is
# not this guard's business (and would clutter the gate output) — silence it, keep real errors.
warnings.filterwarnings("ignore", category=SyntaxWarning)

REPO = Path(__file__).resolve().parents[1]
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def offending_imports(source: str) -> list:
    """Static imports whose ROOT module is `triggers` — the exact shape that fails the
    clean-clone deps gate. A path-load (importlib on a file path) carries no such import and
    is invisible here, which is the whole point: it flags the broken pattern, not the fix."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []                       # unparseable is some other gate's business
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.level == 0 and (n.module or "").split(".")[0] == "triggers":
            hits.append(f"from {n.module} import ...")
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] == "triggers":
                    hits.append(f"import {a.name}")
    return hits


# ── RED controls: the scan must FIRE on the broken shape and stay silent on the fix ──
_BAD = "from triggers.seed.usage_poll import STALE_S\nimport triggers.steward.owner_queue_age\n"
_GOOD = ("import importlib.util\n"
         "spec = importlib.util.spec_from_file_location('m', REPO/'triggers/seed/x.py')\n")
check("RED-control: a static `from triggers.`/`import triggers.` IS flagged (both forms)",
      len(offending_imports(_BAD)) == 2)
check("RED-control: a path-load (spec_from_file_location) is NOT flagged", offending_imports(_GOOD) == [])

# ── the live sweep: every git-tracked .py ──
tracked = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO,
                         capture_output=True, text=True).stdout.split()
offenders = {}
for rel in tracked:
    try:
        src = (REPO / rel).read_text()
    except Exception:
        continue
    hits = offending_imports(src)
    if hits:
        offenders[rel] = hits

check(f"no committed .py statically imports a gitignored triggers module ({len(tracked)} scanned)",
      not offenders,
      detail="; ".join(f"{f}: {v}" for f, v in offenders.items()))

if not tracked:
    # git absent / not a repo → we verified NOTHING about the estate, only the RED controls
    print("SKIP: `git ls-files` returned nothing — cannot sweep the committed estate.")
    sys.exit(77)

print()
if fails:
    print(f"FAIL — {len(fails)}: " + "; ".join(fails))
    sys.exit(1)
print(f"PASS — no committed .py static-imports a gitignored triggers module ({len(tracked)} files); "
      "path-load + skip-77 is the pattern (test_spawn_drift)")
