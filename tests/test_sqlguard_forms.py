#!/usr/bin/env python3
"""Oracle: sqlguard's two site questions (plan-10107; a4 #50622 D1-D5, a2 #50628, a3 #50630 BC-1/BC-2).

A bare SQL verb ("insert", `attr == "delete"`) was read as an SQL site. The fix asks TWO questions, and every caller
says which: is_site(text, *, form) with NO default. form="statement" (a complete text) drops the verb alone;
form="head" (the head of a composed string, `"DELETE " + tbl`) is exactly the old predicate. A site predicate fails
OPEN, so this is judged by what the change DROPS.

  F  forms: statement drops "insert"/"  delete  "/"SELECT;" and keeps `select 1`, a CTE, `INSERT INTO …` and a1's 12
     function-call SELECTs (taken from the ledger); head keeps the bare verb; no form → TypeError; an unknown form
     → ValueError
  H  the head callers, through the inventory: `"DELETE " + tbl`, `"UPDATE " + t + " SET x=1"`, f"SELECT {cols}" stay
     UNRESOLVED, and a module-level `Q = "DELETE " + tbl` (inventory.py's top-level path) too; `x == "delete"` is
     nothing
  C  D2 + a3 BC-2, the CALL-SITE census over the repo and the estate: every call of normalize's is_site, in EVERY
     spelling (a direct import, `as` an alias, through a module alias), passes form=; the four known callers pass
     the forms D1 assigns; `form` is keyword-only with no default; no `_SITE.match`/`.search` outside normalize.py.
     Its blind spot, stated (a2 #50628 b): a call inside a STRING program (`python -c "…is_site(…)"`) is not seen
     here; it fails at runtime with the TypeError instead, which tests/test_sqlguard.py's literal now passes form= to.
     Fixtures prove the census sees an aliased call without form= and a `_SITE.match` elsewhere.
  G  G1, the census over the EXTRACTOR stream (repo + estate, in process): the site keys the old predicate found and
     the new one doesn't are ALL bare verbs; the head form changes nothing. COUNTS only (P1).
  L  G2: no ledger row is a vanished key (the shrink ran: 0 R-STALE absent), and the header's debt_rows is the row
     count. Hashed rows are covered: the vanished keys are compared in ledger-key space.
  D  D5 + a3 BC-1: a dropped bare-verb literal is SAFE only by its AST USE (a comparison operand; a member of the
     right side of in/not in or of a for-iterable; a dict key or value). Any other use (`q = "DELETE "; q += t`, a
     join() list, a wrapper's argument) needs a `*` row in that function, else RED naming it: fixtures both ways, and
     the census over the live inventory.
"""
import ast
import os
import re
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=SyntaxWarning)
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
# The census's axis is THIS repo, set, never inherited: inventory roots itself at its own file's grandparent, so a mutant
# copy in /tmp/tmpXXX would scan all of /tmp (measured: 7 of 8 inventory mutants timed out at 600 s, NOT PROBED).
os.environ["ASTRYX_SQLGUARD_ROOT"] = str(REPO)
fails = []


def want(label, cond, why=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{why}]" if why and not cond else ""))
    if not cond:
        fails.append(label)


import importlib.util  # noqa: E402

import astryx.security.sqlguard  # noqa: E402,F401


def _load(name, rel, env):
    spec = importlib.util.spec_from_file_location(f"astryx.security.sqlguard.{name}", os.environ.get(env) or REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"astryx.security.sqlguard.{name}"] = mod
    setattr(sys.modules["astryx.security.sqlguard"], name, mod)
    spec.loader.exec_module(mod)
    return mod


nz = _load("normalize", "src/astryx/security/sqlguard/normalize.py", "SQLGUARD_NORMALIZE_SRC")
inv = _load("inventory", "src/astryx/security/sqlguard/inventory.py", "SQLGUARD_INVENTORY_SRC")
from astryx.security.sqlguard import ledger, privacy  # noqa: E402

# the OLD predicate, re-derived here (never imported from the subject)
OLD = re.compile(r"^\s*(select|insert|update|delete|with|merge)\b(?!-)", re.I)
BARE = re.compile(r"^\s*(select|insert|update|delete|with|merge)\s*;?\s*$", re.I)

# ── F: the forms ────────────────────────────────────────────────────────────────────────────────────────────────
# The AGE graph-DDL two are assembled at runtime: src/astryx/core/copies.py's writer scan reads a literal `<ddl>_graph(?` with
# an unresolvable argument as an UNCOUNTABLE graph writer (the derived-copy registry gate), and this file writes none.
_CG, _DG = "create" + "_graph", "drop" + "_graph"
A1_SELECTS = ["select 1", "select create_elabel(?, ?)", f"select {_CG}(?)", "select create_vlabel(?, ?)",
              "select current_user", f"select {_DG}(?, true)", "select has_database_privilege(?, ?, 'connect')",
              "select now()", "select obj_description(?, 'pg_class')", "select pg_notify('astryx_dag', ?)",
              "select to_regclass('public.utterances')", "select to_regclass('sqlguard_seen')"]
st = lambda t: nz.is_site(t, form="statement")  # noqa: E731
want("F1 statement: a bare verb is not a site (insert, '  delete  ', 'SELECT;', with, merge)",
     not any(st(t) for t in ("insert", "  delete  ", "SELECT;", "with", "MERGE", "update ;")))
want("F2 statement: real statements stay sites (select 1, a CTE, INSERT INTO …, MERGE INTO …)",
     all(st(t) for t in ("select 1", "with x as (select 1) select * from x", "INSERT INTO t VALUES (1)",
                         "MERGE INTO t USING s ON true", "SELECT*FROM t", "select(1)")))
want(f"F3 statement: a1's {len(A1_SELECTS)} function-call SELECTs (from the ledger) all stay sites",
     all(st(t) for t in A1_SELECTS), str([t for t in A1_SELECTS if not st(t)]))
want("F4 statement: the CLI argv control holds ('merge-base', 'update-index' are not sites)",
     not st("merge-base") and not st("update-index"))
want("F5 head: the verb alone may begin a composed query (insert, 'DELETE ', 'select;')",
     all(nz.is_site(t, form="head") for t in ("insert", "DELETE ", "select;", "with")))
try:
    nz.is_site("select 1")
    want("F6 no form → TypeError (a caller can't inherit one)", False, "it answered")
except TypeError:
    want("F6 no form → TypeError (a caller can't inherit one)", True)
try:
    nz.is_site("select 1", form="stmt")
    want("F6 ...an unknown form → ValueError", False, "it answered")
except ValueError:
    want("F6 ...an unknown form → ValueError", True)

# ── H + D: through the inventory, on fixture files ──────────────────────────────────────────────────────────────
FIX = '''
Q = "DELETE " + TBL
VERB = "insert"


def h_concat(cur, tbl):
    cur.execute("DELETE " + tbl)


def h_concat2(cur, t):
    cur.execute("UPDATE " + t + " SET x=1")


def h_fstring(cur, cols):
    cur.execute(f"SELECT {cols}")


def h_module(cur):
    cur.execute(Q)


def safe_cmp(x):
    return x == "delete"


def safe_in(head):
    return head in ("select", "with")


def safe_for(q):
    for verb in ("merge", "delete"):
        q = q.replace(verb, "")
    return [v for v in ("insert",) if v]


def safe_dict():
    return {"delete": 1, "k": "insert"}


def unsafe_augassign(cur, t):
    q = "DELETE "
    q += t
    cur.execute(q)


def unsafe_join(run, tbl):
    run(" ".join(["DELETE", tbl]))


def unsafe_wrapper(db, t):
    parts = ["UPDATE"]
    parts.append(t)
    db.go(" ".join(parts))


def unsafe_but_star(cur, t):
    q = "DELETE "
    cur.execute("UPDATE " + t)


def concat_resolved(cur):
    cur.execute(VERB + " INTO t VALUES (1)")


def concat_open(cur, tbl):
    cur.execute(VERB + " INTO " + tbl)


def wrap_const(w):
    w(VERB)
'''
with tempfile.TemporaryDirectory() as td:
    f = Path(td) / "fx.py"
    f.write_text(FIX)
    F = inv.inventory_file(f, "fx.py")
fn = lambda n: F.get(f"fx.py::{n}", {"sites": {}, "unresolved": []})  # noqa: E731
for n in ("h_concat", "h_concat2", "h_fstring", "h_module"):
    want(f"H {n}: a composed head stays UNRESOLVED (the head form, unchanged)", bool(fn(n)["unresolved"]), str(fn(n)))
want("H `x == \"delete\"` is nothing: no site, no unresolved, no bare-use flag (the goal's case)",
     "fx.py::safe_cmp" not in F, str(F.get("fx.py::safe_cmp")))
for n in ("safe_in", "safe_for", "safe_dict"):
    want(f"D {n}: a bare verb whose USE is safe is dropped quietly", f"fx.py::{n}" not in F, str(F.get(f"fx.py::{n}")))


def d5_red(functions):
    """D5's census: a function holding a bare verb used unsafely, with no `*` (unresolved) row."""
    return sorted(k for k, v in functions.items() if v.get("bare_unsafe") and not v["unresolved"])


red = d5_red(F)
for n in ("unsafe_augassign", "unsafe_join", "unsafe_wrapper"):
    want(f"D {n}: a bare verb used as a value (no `*` row) → RED, named", f"fx.py::{n}" in red, str(red))
want("D concat_resolved: a const verb in a `+` chain that resolves is that chain's site, not a lone flag (a4 #52387 (a))",
     "insert into t values (1)" in fn("concat_resolved")["sites"] and not fn("concat_resolved").get("bare_unsafe"),
     str(fn("concat_resolved")))
for n in ("concat_open", "wrap_const"):
    want(f"D {n}: ...but where nothing else records it, the const verb's own flag stands → RED", f"fx.py::{n}" in red,
         str(fn(n)))
want("D unsafe_but_star: the same use WITH a `*` row is covered (not RED)", "fx.py::unsafe_but_star" not in red,
     str(fn("unsafe_but_star")))

# ── C: the call-site census (D2, a3 BC-2) ───────────────────────────────────────────────────────────────────────
NAMES = {"is_site", "_SITE"}
# both spellings: the canonical package and the S4 compat stub (one module object, aliased; either import reaches is_site)
PKGS = {"astryx.security.sqlguard", "nucleus.sqlguard"}
MODS = {p + ".normalize" for p in PKGS}


def census(tree: ast.AST, rel: str):
    """(calls, problems): every is_site call in any spelling, as (line, form or None, first arg source)."""
    direct, modal, calls, problems = {}, set(), [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in MODS:
            for a in n.names:
                if a.name in NAMES:
                    direct[a.asname or a.name] = a.name
        elif isinstance(n, ast.ImportFrom) and n.module in PKGS:
            modal |= {a.asname or a.name for a in n.names if a.name == "normalize"}
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name in MODS:
                    modal.add(a.asname or a.name)
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f, target = n.func, None
        if isinstance(f, ast.Name) and f.id in direct:
            target = direct[f.id]
        elif isinstance(f, ast.Attribute) and ast.unparse(f.value) in modal and f.attr in NAMES:
            target = f.attr
        elif isinstance(f, ast.Attribute) and f.attr in ("match", "search", "fullmatch") \
                and isinstance(f.value, ast.Name) and f.value.id in direct and direct[f.value.id] == "_SITE":
            target = "_SITE." + f.attr
        elif (isinstance(f, ast.Attribute) and f.attr in ("match", "search", "fullmatch")
              and isinstance(f.value, ast.Attribute) and f.value.attr == "_SITE"
              and ast.unparse(f.value.value) in modal):
            target = "_SITE." + f.attr
        if target is None:
            continue
        if target.startswith("_SITE"):
            problems.append(f"{rel}:{n.lineno}: {target} bypasses the form")
            continue
        form = next((k.value for k in n.keywords if k.arg == "form"), None)
        val = form.value if isinstance(form, ast.Constant) else (None if form is None else "<dynamic>")
        calls.append((n.lineno, val, ast.unparse(n.args[0]) if n.args else ""))
        if form is None:
            problems.append(f"{rel}:{n.lineno}: is_site called without form=")
    return calls, problems


cfix = '''from astryx.security.sqlguard.normalize import is_site as looks_like, _SITE
from nucleus.sqlguard import normalize as N
import astryx.security.sqlguard.normalize as NZ
a = looks_like("x")
b = N.is_site("y")
c = NZ.is_site("z", form="head")
d = _SITE.match("w")
e = N._SITE.search("v")
'''
_, cp = census(ast.parse(cfix), "fixture")
want("C0 the census sees every spelling: an alias and a module alias without form=, and _SITE.match/.search",
     len(cp) == 4 and sum("without form" in p for p in cp) == 2 and sum("bypasses" in p for p in cp) == 2, str(cp))
SKIP = {"venv", ".venv", "node_modules", "homes", ".git", "__pycache__", "var"}
problems, seen, by_file = [], 0, {}


def _git_common(d):
    """(toplevel, common dir) by ASKING git (the subject reads the .git files itself), or None."""
    r = subprocess.run(["git", "-C", str(d), "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir"],
                       capture_output=True, text=True, env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
    if r.returncode != 0:
        return None
    top, common = r.stdout.split("\n")[:2]
    return Path(top).resolve(), Path(common).resolve()


def _py(root):
    """Every .py under root, FOLLOWING symlinked dirs (a merge_check tree links the estate in), never descending into
    another checkout of THIS repository (the estate's .claude/worktrees/, 10-14)."""
    mine = (_git_common(root) or (None, None))[1]
    for d, dirs, files in os.walk(root, followlinks=True):
        keep = []
        for x in dirs:
            if x in SKIP:
                continue
            if (Path(d) / x / ".git").exists():
                g = _git_common(Path(d) / x)
                if g and g[0] == (Path(d) / x).resolve() and g[1] == mine:
                    continue
            keep.append(x)
        dirs[:] = keep
        yield from (Path(d) / f for f in files if f.endswith(".py"))


# N: another checkout of this repo is pruned and declared; a nested repo that ISN'T this one is still walked
with tempfile.TemporaryDirectory() as td:
    ge = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    g = lambda *a, cwd=td: subprocess.run(["git", *a], cwd=cwd, env=ge, capture_output=True, check=True)
    root = Path(td) / "repo"
    (root / "pkg").mkdir(parents=True)
    g("init", "-q", str(root))
    (root / "pkg" / "a.py").write_text("def f(c):\n    c.execute('select 1 from t')\n")
    g("-C", str(root), "add", "-A"); g("-C", str(root), "-c", "user.name=fx", "-c", "user.email=fx@example.invalid",
                                       "commit", "-qm", "fx")
    (root / ".claude" / "worktrees").mkdir(parents=True)
    g("-C", str(root), "worktree", "add", "-q", "--detach", str(root / ".claude" / "worktrees" / "agent-x"))
    other = root / "agentsrepo"
    other.mkdir()
    g("init", "-q", str(other))
    (other / "b.py").write_text("def h(c):\n    c.execute('select 2 from u')\n")
    saved = inv.REPO
    inv.REPO = root.resolve()
    inv.OTHER_CHECKOUTS.clear()
    try:
        got = {str(p.relative_to(inv.REPO)) for p in inv._py_files(include_tests=False)}
        declared = sorted(inv.OTHER_CHECKOUTS)
    finally:
        inv.REPO = saved
        inv.OTHER_CHECKOUTS.clear()
    mine_c = {str(p.relative_to(root)) for p in _py(root)}
    want("N1 the inventory skips another checkout of this repo and DECLARES it",
         "pkg/a.py" in got and not any(s.startswith(".claude") for s in got)
         and declared == [os.path.join(".claude", "worktrees", "agent-x")], f"{sorted(got)} {declared}")
    want("N2 ...but a nested repo that ISN'T this one is still walked (agents/ is its own repo)",
         "agentsrepo/b.py" in got, str(sorted(got)))
    want("N3 the census re-derives the same walk by asking git", mine_c == got, f"{sorted(mine_c)} vs {sorted(got)}")


# the subjects under the probe: the census reads a mutant through its seam, never the repo's copy
SEAMS = {"src/astryx/security/sqlguard/normalize.py": "SQLGUARD_NORMALIZE_SRC", "src/astryx/security/sqlguard/inventory.py": "SQLGUARD_INVENTORY_SRC",
         "src/astryx/security/sqlguard/judge.py": "SQLGUARD_JUDGE_SRC"}
for p in _py(REPO):
    rel = str(p.relative_to(REPO))
    try:
        tree = ast.parse(Path(os.environ.get(SEAMS.get(rel, ""), "") or p).read_text(errors="replace"))
    except SyntaxError:
        continue
    calls, probs = census(tree, privacy.label(rel) if hasattr(privacy, "label") else rel)
    if rel == "src/astryx/security/sqlguard/normalize.py":
        probs = [x for x in probs if "bypasses" not in x]          # normalize owns _SITE
    seen += len(calls)
    problems += probs
    if calls:
        by_file[rel] = sorted((form, arg) for _, form, arg in calls)
want(f"C1 every is_site call in the repo and estate passes form= ({seen} calls), and nothing matches _SITE "
     f"outside normalize.py", not problems, "; ".join(problems[:4]))
want("C2 the five callers pass D1's forms: inventory module-constant + composed-string heads, its statement caller and the "
     "resolved-concat check (a4 (a)); judge statement",
     by_file.get("src/astryx/security/sqlguard/inventory.py") == sorted([("head", "_head(st.value)"), ("head", "_head(n)"),
                                                            ("statement", "text"), ("statement", "text")])
     and by_file.get("src/astryx/security/sqlguard/judge.py") == [("statement", "r['t']")],
     f"{by_file.get('src/astryx/security/sqlguard/inventory.py')} {by_file.get('src/astryx/security/sqlguard/judge.py')}")
sig = next((n for n in ast.walk(ast.parse(Path(nz.__file__).read_text()))
            if isinstance(n, ast.FunctionDef) and n.name == "is_site"), None)
kw = {a.arg: d for a, d in zip(sig.args.kwonlyargs, sig.args.kw_defaults)} if sig else {}
want("C3 is_site's `form` is keyword-only with NO default", "form" in kw and kw["form"] is None, str(kw))

# ── G + L: the extractor-stream census, and the ledger ──────────────────────────────────────────────────────────
real = inv.is_site
inv.is_site = lambda t, *, form: bool(OLD.match(t or ""))
old_rep = inv.build()
inv.is_site = real
new_rep = inv.build()


def keys(rep):
    return {ledger.ledger_key(f"{fn}\x1f{t}") for fn, v in rep["functions"].items() for t in v["sites"]}


gone = keys(old_rep) - keys(new_rep)
added = keys(new_rep) - keys(old_rep)
texts = {f"{fn}\x1f{t}": t for fn, v in old_rep["functions"].items() for t in v["sites"]}
gone_texts = [texts[k] for k in texts if ledger.ledger_key(k) in gone]
print(f"  ..  G1 census: {len(keys(old_rep))} site keys before, {len(keys(new_rep))} after; "
      f"{len(gone)} dropped ({sum(k.startswith('sha256:') for k in gone)} hashed)")
want("G1 every site key the change drops is a bare verb, and it adds none", gone_texts and
     all(BARE.match(t) for t in gone_texts) and not added, f"non-bare dropped: {sum(not BARE.match(t) for t in gone_texts)}")
head_old = {fn: v["unresolved"] for fn, v in old_rep["functions"].items() if v["unresolved"]}
head_new = {fn: v["unresolved"] for fn, v in new_rep["functions"].items() if v["unresolved"]}
want("G1 the head form changes nothing: the same functions carry the same `*` rows", head_old == head_new,
     f"{len(head_old)} vs {len(head_new)}")
import json  # noqa: E402
doc = json.loads((REPO / "src/astryx/security/sqlguard/ledger.json").read_text())
left = [k for k in doc["rows"] if k in gone]
want("L1 no ledger row is a dropped bare-verb key (the shrink ran: 0 R-STALE absent), hashed rows included",
     not left, f"{len(left)} left")
want("L1 ...and the header's debt_rows is the row count", doc["header"]["debt_rows"] == len(doc["rows"]),
     f"{doc['header']['debt_rows']} vs {len(doc['rows'])}")
red = d5_red(new_rep["functions"])
want("D5 the live inventory: no function holds a bare verb used unsafely without a `*` row",
     not red, str([privacy.label(k) if hasattr(privacy, "label") else k for k in red][:5]))

if fails:
    print(f"FAIL: {len(fails)} arm(s)")
    sys.exit(1)
print("PASS: sqlguard asks two site questions, every caller names its form, and the change drops only bare verbs "
      "(each by a safe use, or covered by a `*` row)")
