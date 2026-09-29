#!/usr/bin/env python3
"""O6 — the economy's CONSUMER SET is derived, and every consumer is typed by effect (goal 4227).

plan-4227 #21236 V1 grepped a HAND-KEPT identifier list to find everything that reads economic
value, and O6 was to pin the result. a2/a4's build condition (#21249): a hand-kept list wears a
derivation's face — `m["v2"]["mirror"]` matched none of its patterns. So the identifier set is
DERIVED FROM THE AUTHORITIES, every time this runs:
  (i)   nucleus/econ.py's public functions (AST) — read via `econ.<name>`, and ANY import from
        nucleus.econ makes a file a consumer (private helpers included: they are still econ);
  (ii)  the top-level keys econ.compute() and econ.v2() RETURN (AST) — i.e. every key written
        under econ.metrics and under metrics.v2 — matched as SQL `->'k'` / `->>'k'` and as
        Python `x["k"]` / `x.get("k")`. A key S2 adds to v2 joins the set with no edit here;
  (iii) the value columns of goals/econ from nucleus/schema.sql (CREATE TABLE + ALTER ... ADD
        COLUMN), matched in executable SQL strings (docstrings excluded, uppercase keywords).
(iii) cannot be derived: which column is "value" is a judgement. So it is GRADED "coverage over
the declared column list", and made COMPLETE instead: every goals/econ column must be declared
VALUE or NON-VALUE with a reason, so a new column turns this RED until someone classifies it.

The derived consumer set must EQUAL the typed MANIFEST (I2: effect type + rest state + stage).
A new, unseen consumer turns it RED. And no entry may be typed `hard`: after S1a/S1b the
value-keyed hard actuators (market_decay's retire, shed's roi rung) are gone — I4/O3 closure.

THE SCAN DOMAIN IS DERIVED TOO (a2, S1b review #21603): every .py under the repo minus
{venv, node_modules, homes, tests, .git} and test_/mutants_ files — not a root list, so a consumer
landing in a NEW top-level dir (bridges/, harness/, …) is seen. Gitignored code (triggers/,
memory/graph, sensors — decided by `git check-ignore`) is absent in a worktree or fresh clone:
a manifest row whose file is ABSENT and gitignored is UNVERIFIED, and the run exits 77 AFTER the
tracked asserts — a skip, never a pass. Run it in the live tree for the whole set.

Exit 0 pass · 1 fail · 77 tracked half passed, gitignored half unverifiable here.
"""
import ast
import re
import subprocess
import sys
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXCLUDE_DIRS = {"venv", "node_modules", "homes", "tests", ".git"}
AUTHORITY = "nucleus/econ.py"

# ── (iii) goals/econ columns: DECLARED, but complete (every column classified) ──────────────
VALUE_COLS = {
    "budget_tokens": "the v1 price of a goal (retired as a writer at S3, read-only, no DROP)",
    "spent_tokens": "v1 burn against the budget",
    "funded_by": "v1 mint attribution (3499)",
    "metrics": "the econ row itself: every value number lives in this jsonb",
}
NON_VALUE_COLS = {
    "id": "key", "ts": "row time", "title": "text", "parent_id": "tree", "owner": "who",
    "state": "lifecycle", "scope_note": "text",
    "epoch_hours": "progress-law cadence, not a quantity of value",
    "last_progress": "lagging liveness stamp", "dead_epochs": "progress-law counter",
    "done_at": "lifecycle stamp (W keys on it, but reading it is not reading a value)",
    "day": "econ key", "computed_at": "econ row time",
}

# ── the typed manifest (I2) ─────────────────────────────────────────────────────────────────
# type: hard (acts on value by writing/skipping) | soft (shapes behaviour: a line an agent reads)
#       | detector | reporter | writer.   rest: the declared state when its input is VACUOUS.
MANIFEST = {
    "hooks/usage.py": {"type": "soft", "rest": "[econ] neutral token (disarmed, S1a)",
                       "stage": "S2 mirrors v2, self-scoped"},
    "mcp/org/server.py": {"type": "reporter", "rest": "economy() shows v1, labeled budget-era",
                          "stage": "S2 reads v2; S3 propose_goal stops writing budgets"},
    "observatory/api/main.py": {"type": "reporter", "rest": "v1 frozen, labeled budget-era",
                                "stage": "S2"},
    "memory/graph/ingest.py": {"type": "reporter", "rest": "ingests v1 budget as history",
                               "stage": "S2"},
    "nucleus/wash_detector.py": {"type": "detector", "rest": "NOT_EVALUATED share on no calls",
                                 "stage": "migrated S1b (v2 rings, report-only)"},
    "triggers/steward/econ_rollup.py": {"type": "writer", "rest": "archives what compute() returns",
                                        "stage": "unchanged (runs the authority)"},
    "triggers/steward/market_decay.py": {"type": "detector", "rest": "reports rent, no retire verb",
                                         "stage": "S1b (was hard); S2 re-keys roi"},
    "triggers/steward/weekly_economic_review.py": {"type": "detector",
                                                   "rest": "L2 surfaces, L3 retired",
                                                   "stage": "S1b; S2 re-keys L2's roi"},
}
TYPES = {"hard", "soft", "detector", "reporter", "writer"}

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


# ── derivation from the authorities ─────────────────────────────────────────────────────────
def derive_identifiers(econ_src: str, schema_src: str):
    tree = ast.parse(econ_src)
    pub = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
    keys = set()
    for fn in ("compute", "v2"):
        f = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn), None)
        if f is None:
            raise SystemExit(f"FAIL: authority lost {fn}() — cannot derive the metrics keys")
        for r in ast.walk(f):
            if isinstance(r, ast.Return) and isinstance(r.value, ast.Dict):
                keys |= {k.value for k in r.value.keys if isinstance(k, ast.Constant)}
    cols = set()
    for t in ("goals", "econ"):
        m = re.search(rf"CREATE TABLE IF NOT EXISTS {t} \((.*?)\n\);", schema_src, re.S)
        if not m:
            raise SystemExit(f"FAIL: schema.sql lost the {t} table — cannot derive its columns")
        for line in m.group(1).splitlines():
            c = re.match(r"\s*([a-z_]+)\s+\w", line)
            if c and not line.strip().startswith("--"):
                cols.add(c.group(1))
        cols |= set(re.findall(rf"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS (\w+)", schema_src))
    return pub, keys, cols


def _docstring_ids(tree):
    return {id(b[0].value) for b in [getattr(n, "body", None) for n in ast.walk(tree)]
            if isinstance(b, list) and b and isinstance(b[0], ast.Expr)
            and isinstance(b[0].value, ast.Constant)}


_SQL = re.compile(r"\b(SELECT|UPDATE|INSERT|FROM|WHERE|SET)\b")   # uppercase: SQL, not prose


def reads(src: str, pub, keys, value_cols) -> list[str]:
    """Every reason `src` is an economy consumer (empty = not one)."""
    try:
        with warnings.catch_warnings():       # a scanned file's own invalid escapes are not ours
            warnings.simplefilter("ignore")
            tree = ast.parse(src)
    except SyntaxError as e:
        return [f"UNPARSEABLE:{e.lineno}"]   # a file the scan cannot read is flagged, not skipped
    docs, why = _docstring_ids(tree), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "nucleus.econ":
            why.add("import nucleus.econ")
        elif isinstance(n, ast.ImportFrom) and n.module == "nucleus" \
                and any(a.name == "econ" for a in n.names):
            why.add("import nucleus.econ")
        elif isinstance(n, ast.Import) and any(a.name == "nucleus.econ" for a in n.names):
            why.add("import nucleus.econ")
        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) \
                and n.value.id == "econ" and n.attr in pub:
            why.add(f"econ.{n.attr}")
        elif isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) \
                and n.slice.value in keys:
            why.add(f'[{n.slice.value!r}]')
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" \
                and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value in keys:
            why.add(f".get({n.args[0].value!r})")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            s = n.value
            why |= {f"->{k}" for k in re.findall(r"->>?\s*'(\w+)'", s) if k in keys}
            if _SQL.search(s):
                why |= {f"col {c}" for c in value_cols if re.search(rf"\b{c}\b", s)}
    return sorted(why)


def _ignored(rel: str) -> bool:
    return subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", rel]).returncode == 0


pub, keys, cols = derive_identifiers((REPO / AUTHORITY).read_text(),
                                     (REPO / "nucleus" / "schema.sql").read_text())

print("DERIVATION (from the authorities, not a list):")
print(f"        {len(pub)} public econ functions · metrics keys {sorted(keys)} · "
      f"{len(cols)} goals/econ columns")
check("(iii) every goals/econ column is classified VALUE or NON-VALUE (a new column is RED)",
      cols == set(VALUE_COLS) | set(NON_VALUE_COLS),
      f"unclassified={sorted(cols - set(VALUE_COLS) - set(NON_VALUE_COLS))} "
      f"stale={sorted((set(VALUE_COLS) | set(NON_VALUE_COLS)) - cols)}")
check("(iii) VALUE and NON-VALUE are disjoint", not (set(VALUE_COLS) & set(NON_VALUE_COLS)))

# ── the scanner can SEE every form (a silent scanner would pass the equality vacuously) ─────
print("\nSCANNER SEES EVERY FORM (fixtures):")
V = set(VALUE_COLS)
for label, src, want in [
    ("SQL ->>", "q = \"SELECT metrics->'v2'->>'W' FROM econ\"", True),
    ("the #21249 miss: m['v2']['mirror']", "x = m['v2']['mirror']", True),
    (".get('trigger_roi')", "x = m.get('trigger_roi')", True),
    ("import from nucleus.econ", "from nucleus.econ import _v2_counted", True),
    ("from nucleus import econ", "from nucleus import econ", True),
    ("econ.<public fn>", "y = econ.thermo(c, a, b)", True),
    ("value column in executable SQL", "q = 'SELECT budget_tokens FROM goals'", True),
    ("CONTROL value column in a DOCSTRING only", '"""SELECT budget_tokens FROM goals"""\nx = 1', False),
    ("CONTROL value column in prose (no SQL keyword)", "s = 'the budget_tokens are retired'", False),
    ("CONTROL an unrelated file", "import os\nprint(os.getcwd())", False),
]:
    got = bool(reads(src, pub, keys, V))
    check(f"{label} → {'consumer' if want else 'not a consumer'}", got == want, f"reads={reads(src, pub, keys, V)}")

# a key the authority STARTS writing joins the set with no edit here (derivation, not a list)
_econ_plus = (REPO / AUTHORITY).read_text().replace(
    '"tool_gdp": _v2_tool_gdp(rows, V2_VERSION, auth_ok),',
    '"tool_gdp": _v2_tool_gdp(rows, V2_VERSION, auth_ok),\n        "mirror_probe": None,', 1)
_, keys_plus, _ = derive_identifiers(_econ_plus, (REPO / "nucleus" / "schema.sql").read_text())
check("a NEW key written into v2 is derived automatically (x['mirror_probe'] becomes a consumer)",
      "mirror_probe" in keys_plus and bool(reads("x = m['mirror_probe']", pub, keys_plus, V)))

# ── the live set equals the manifest ────────────────────────────────────────────────────────
print("\nCONSUMER SET = TYPED MANIFEST:")
def scan(repo: Path, pub, keys, value_cols) -> dict:
    """{relpath: reasons} over every .py under `repo` outside EXCLUDE_DIRS (the derived domain)."""
    out = {}
    for p in sorted(repo.rglob("*.py")):
        rel = p.relative_to(repo)
        if set(rel.parts[:-1]) & EXCLUDE_DIRS or str(rel) == AUTHORITY \
                or p.name.startswith(("test_", "mutants_")):
            continue
        why = reads(p.read_text(errors="replace"), pub, keys, value_cols)
        if why:
            out[str(rel)] = why
    return out


import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as _d:
    (Path(_d) / "brandnew_dir").mkdir()
    (Path(_d) / "brandnew_dir" / "reader.py").write_text("x = m['v2']['W']\n")
    (Path(_d) / "venv").mkdir()
    (Path(_d) / "venv" / "lib.py").write_text("x = m['v2']['W']\n")
    _fx = scan(Path(_d), pub, keys, V)
check("the scan DOMAIN is derived: a consumer in a NEW top-level dir is found; venv/ is not scanned",
      set(_fx) == {"brandnew_dir/reader.py"}, f"found={sorted(_fx)}")

derived = scan(REPO, pub, keys, V)
unverified = sorted(k for k in MANIFEST if not (REPO / k).exists() and _ignored(k))
expected = set(MANIFEST) - set(unverified)
new = sorted(set(derived) - expected)
gone = sorted(expected - set(derived))
check("every derived consumer is in the manifest (a new, unseen consumer is RED — type it)",
      not new, "; ".join(f"{f} reads {derived[f]}" for f in new))
check("every manifest entry is still a consumer (a stale entry is RED — remove it)", not gone,
      f"{gone}")
check("every entry is typed by effect with a declared rest state (I2)",
      all(v.get("type") in TYPES and v.get("rest") for v in MANIFEST.values()))
hard = sorted(k for k, v in MANIFEST.items() if v["type"] == "hard")
check("NO value-keyed HARD actuator remains (market_decay retire + shed roi rung gone: I4/O3)",
      not hard, f"hard={hard}")
for f in sorted(derived):
    print(f"        {f:44} {MANIFEST.get(f, {}).get('type', '?'):9} {', '.join(derived[f])[:70]}")

print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
if unverified:
    print(f"SKIP (77): tracked half PASSED; gitignored manifest row(s) {unverified} are absent "
          f"here, so UNVERIFIED — run in the live tree.")
    sys.exit(77)
print(f"econ consumers: {len(derived)} derived = typed manifest; no value-keyed hard actuator")
sys.exit(0)
