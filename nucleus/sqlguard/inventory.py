#!/usr/bin/env python3
"""The STATIC half of sqlguard: which SQL sites exist, found by CONTENT and never by sink name (plan-4243 T1).

    venv/bin/python -m nucleus.sqlguard.inventory          # summary
    venv/bin/python -m nucleus.sqlguard.inventory --json   # the full inventory

A site is a string whose first keyword is SELECT/INSERT/UPDATE/DELETE/WITH/MERGE. It is OWNED by the function
it appears in, keyed `relpath::qualname`, with the qualname built exactly as CPython's `co_qualname` builds it
(`Class.method`, `outer.<locals>.inner`), so a runtime frame and a static site meet on the same key.

A function also owns:
  * a module-level SQL constant it references by NAME (`cur.execute(SQL)`);
  * an f-string whose every hole is a module-level string constant, resolved to its runtime text (#3's
    `{_V2_DEMAND}` is this shape).
Anything whose runtime text can't be derived statically is recorded as UNRESOLVED on its function: an f-string
with a runtime hole, `.format()`, `%`-formatting, or psycopg.sql composition. The judge then attributes at
FUNCTION level and flags it FALLBACK (#21516 R3).

The roots are DERIVED: every .py under the repo, walking the FILESYSTEM and not git, because triggers/ is
gitignored. Excluded: tests/ (oracles, not subjects), venv/, node_modules/, homes/, caches, and EXCLUDED_ROOTS
(declared with a reason and printed every run). A file that
won't parse is reported, and the judge treats a non-zero count as NOT SEARCHED.
"""
import ast
import json
import os
import sys
from pathlib import Path

from nucleus.sqlguard.normalize import is_site, is_write, norm

REPO = Path(os.environ.get("ASTRYX_SQLGUARD_ROOT") or Path(__file__).resolve().parents[2]).resolve()
SKIP_DIRS = {"venv", ".venv", "node_modules", "homes", ".git", "__pycache__", "dist", "build"}
# Top-level roots that hold no subject code, each with its reason. Unlike SKIP_DIRS they're DECLARED: printed on
# every answer, and an unknown directory is still walked (so omission fails loud, as R-NEW). Code that ever RUNS
# from an excluded root still surfaces at runtime as R-BLIND (the shim sees SQL the inventory doesn't know).
EXCLUDED_ROOTS = {
    "var": "runtime state (gitignored): logs, runner state, charter backups, deploy bundles. A bundle's .py is a "
           "SNAPSHOT of code that lives in triggers/ or a one-shot migration; nothing imports or schedules var/ "
           "(09-29: var/s1c-bundle read as 43 R-NEW duplicates)",
}
# The shim is the instrument itself: its catalog reads run under its own recursion guard, so it cannot
# observe them. That's the ONE declared exemption, printed with every answer. Nothing else is exempt.
EXEMPT = {"nucleus/sqlguard/shim/sitecustomize.py"}


def _py_files(include_tests: bool):
    for dirpath, dirnames, filenames in os.walk(REPO, followlinks=True):
        rel = os.path.relpath(dirpath, REPO)
        top = rel.split(os.sep)[0]
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and not (rel == "." and d == "tests" and not include_tests)
                       and not (rel == "." and d in EXCLUDED_ROOTS)]
        if top in SKIP_DIRS:
            continue
        for f in filenames:
            if f.endswith(".py"):
                yield Path(dirpath) / f


def _docstring_ids(tree) -> set:
    """ids of docstring Constant nodes (module/class/function first statement), which are prose, not SQL."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def _resolve(node, consts):
    """The runtime text of a string expression, or None if it can't be derived statically."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _resolve(node.left, consts), _resolve(node.right, consts)
        return a + b if a is not None and b is not None else None
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue) and v.conversion == -1 and v.format_spec is None \
                    and isinstance(v.value, ast.Name) and v.value.id in consts:
                parts.append(consts[v.value.id])
            else:
                return None
        return "".join(parts)
    return None


def _head(node):
    """The leading literal text of a string expression, used to decide whether an UNRESOLVED one is SQL."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) for v in node.values if isinstance(v, ast.Constant))
    if isinstance(node, ast.BinOp):
        return _head(node.left) or ""
    return ""


_XCONSTS = {}


def _imported_consts(tree, rel):
    """String constants imported from a REPO module (`from nucleus.x import FRAG`), resolved from that module's
    own constants, so a query built as `LITERAL + FRAG` resolves exactly instead of silently dropping out."""
    out = {}
    for st in tree.body:
        if isinstance(st, ast.ImportFrom) and st.module and not st.level:
            src = REPO / (st.module.replace(".", "/") + ".py")
            if not src.is_file():
                continue
            key = str(src)
            if key not in _XCONSTS:
                _XCONSTS[key] = {}                     # recursion guard for import cycles
                try:
                    _XCONSTS[key] = _module_consts(ast.parse(src.read_text(errors="replace")))
                except SyntaxError:
                    pass
            for a in st.names:
                if a.name in _XCONSTS[key]:
                    out[a.asname or a.name] = _XCONSTS[key][a.name]
    return out


def _consts_of(src):
    key = str(src)
    if key not in _XCONSTS:
        _XCONSTS[key] = {}                             # recursion guard for import cycles
        try:
            _XCONSTS[key] = _module_consts(ast.parse(src.read_text(errors="replace")))
        except SyntaxError:
            pass
    return _XCONSTS[key]


def _module_aliases(tree):
    """alias -> constants of a REPO module bound as a module object, at ANY depth (imports are often local):
    `import nucleus.escalation as esc`, `from nucleus import escalation as esc`. So `esc.SQL` resolves."""
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                src = REPO / (a.name.replace(".", "/") + ".py")
                if a.asname and src.is_file():
                    out[a.asname] = _consts_of(src)
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            for a in n.names:
                src = REPO / (n.module.replace(".", "/") + "/" + a.name + ".py")
                if src.is_file():
                    out[a.asname or a.name] = _consts_of(src)
    return out


def _module_consts(tree, seed=None):
    consts, changed = dict(seed or {}), True
    while changed:                                     # fixpoint: constants may build on earlier ones
        changed = False
        for st in tree.body:
            tgt = val = None
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                tgt, val = st.targets[0].id, st.value
            elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.value is not None:
                tgt, val = st.target.id, st.value
            if tgt and tgt not in consts:
                r = _resolve(val, consts)
                if r is not None:
                    consts[tgt] = r
                    changed = True
    return consts


_STRINGY = (ast.Constant, ast.JoinedStr, ast.BinOp)


def _own_nodes(fn):
    """Nodes that belong to fn itself, excluding nested function/class bodies (they have their own qualname)."""
    stack = list(fn.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


def inventory_file(path: Path, rel: str):
    tree = ast.parse(path.read_text(errors="replace"), filename=rel)
    consts = _module_consts(tree, _imported_consts(tree, rel))
    aliases = _module_aliases(tree)
    # A module constant that LOOKS like SQL but still can't be resolved: a function referencing it is
    # SQL-bearing at FUNCTION level (FALLBACK). It's never silently dropped, which was reverse agreement's
    # first real catch.
    unresolved_consts = set()
    for st in tree.body:
        if isinstance(st, (ast.Assign, ast.AnnAssign)) and st.value is not None:
            tg = st.targets[0] if isinstance(st, ast.Assign) else st.target
            if isinstance(tg, ast.Name) and tg.id not in consts and is_site(_head(st.value)):
                unresolved_consts.add(tg.id)
    docs = _docstring_ids(tree)
    parent = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parent[id(c)] = n
    functions = {}

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qn = prefix + child.name
                functions[f"{rel}::{qn}"] = _collect(child)
                visit(child, qn + ".<locals>.")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            elif isinstance(child, ast.Lambda):
                # co_qualname of a lambda is `<prefix><lambda>`; several in one scope share it, so merge.
                got = _collect(ast.Module(body=[ast.Expr(child.body)], type_ignores=[]))
                cur = functions.setdefault(f"{rel}::{prefix}<lambda>", {"sites": {}, "unresolved": []})
                cur["sites"].update(got["sites"])
                cur["unresolved"] = sorted(set(cur["unresolved"]) | set(got["unresolved"]))
                visit(child, prefix + "<lambda>.<locals>.")
            else:
                visit(child, prefix)

    def _collect(fn, skip=frozenset()):
        sites, unresolved = {}, []
        for n in _own_nodes(fn):
            if id(n) in docs or id(n) in skip:
                continue
            p = parent.get(id(n))
            # only MAXIMAL string expressions: a part of an f-string or a concatenation is handled by its parent
            if isinstance(n, _STRINGY) and isinstance(p, (ast.JoinedStr, ast.BinOp)) \
                    and not (isinstance(p, ast.BinOp) and not isinstance(p.op, ast.Add)):
                continue
            if isinstance(n, ast.FormattedValue):
                continue
            # `"... {x}".format(...)`, `"... %s" % x`, and sql.SQL("...") are composed at runtime
            composed = (isinstance(p, ast.Attribute) and p.attr == "format") \
                or (isinstance(p, ast.BinOp) and isinstance(p.op, ast.Mod) and p.left is n) \
                or (isinstance(p, ast.Call) and getattr(p.func, "attr", getattr(p.func, "id", "")) == "SQL")
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in unresolved_consts:
                unresolved.append(getattr(n, "lineno", 0))
                continue
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in aliases \
                    and n.attr in aliases[n.value.id]:
                text = aliases[n.value.id][n.attr]         # esc.ORG_SILENCE_EPISODES_SQL
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in consts:
                text = consts[n.id]
            elif isinstance(n, (ast.Constant, ast.JoinedStr)) or (isinstance(n, ast.BinOp)
                                                                   and isinstance(n.op, ast.Add)):
                text = None if composed else _resolve(n, consts)
                if text is None:
                    if is_site(_head(n)):
                        unresolved.append(getattr(n, "lineno", 0))
                    continue
            else:
                continue
            if is_site(text):
                sites.setdefault(norm(text), {"line": getattr(n, "lineno", 0), "write": is_write(text)})
        return {"sites": sites, "unresolved": sorted(set(unresolved))}

    visit(tree, "")
    # Module-level code executes under co_qualname "<module>". Its INLINE SQL is a site, but a module-level
    # DEFINITION (`SQL = "SELECT ..."`) is not an execution: it is owned by whichever function references it,
    # and counting it here would be permanent false debt.
    defs = {id(st.value) for st in tree.body if isinstance(st, (ast.Assign, ast.AnnAssign)) and st.value}
    mod = ast.Module(body=[st for st in tree.body if not isinstance(
        st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))], type_ignores=[])
    m = _collect(mod, skip=defs)
    functions[f"{rel}::<module>"] = m
    return {k: v for k, v in functions.items() if v["sites"] or v["unresolved"]}


def reads_schema_sql(path: Path) -> bool:
    """EX1: a file whose CODE holds a string naming schema.sql. Docstrings and comments are prose, not reads."""
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return False
    docs = _docstring_ids(tree)
    return any(isinstance(n, ast.Constant) and isinstance(n.value, str) and "schema.sql" in n.value
               and id(n) not in docs for n in ast.walk(tree))


APPLIER = "nucleus/sqlguard/fixture.py"
NOT_READERS = {APPLIER, "nucleus/sqlguard/inventory.py"}   # they NAME the file; neither builds a fixture from it


def build() -> dict:
    functions, unparseable = {}, []
    for p in _py_files(include_tests=False):
        rel = str(p.relative_to(REPO))
        if rel in EXEMPT:
            continue
        try:
            functions.update(inventory_file(p, rel))
        except SyntaxError:
            unparseable.append(rel)
    # ORACLE literals: the same inventory over tests/, kept apart. Tests are never subjects, but the judge
    # needs their literals for TEXT PROVENANCE: an oracle's own probe routed through a production helper
    # (Ctx.sql) is identified by the literal that produced it, not by guessing from frame position.
    oracle = {}
    for p in _py_files(include_tests=True):
        rel = str(p.relative_to(REPO))
        if rel.startswith("tests" + os.sep):
            try:
                oracle.update(inventory_file(p, rel))
            except SyntaxError:
                pass
    extractors = sorted(str(p.relative_to(REPO)) for p in _py_files(include_tests=True)
                        if str(p.relative_to(REPO)) not in NOT_READERS and reads_schema_sql(p))
    # triggers/ is gitignored: a clone or worktree without it has NOT SEARCHED the class's home. That's never clean.
    return {"functions": functions, "oracle": oracle, "unparseable": sorted(unparseable), "extractors": extractors,
            "exempt": sorted(EXEMPT), "excluded": sorted(EXCLUDED_ROOTS), "triggers_absent": not (REPO / "triggers").is_dir(), "root": str(REPO)}


if __name__ == "__main__":
    inv = build()
    if "--json" in sys.argv:
        print(json.dumps(inv, indent=1, sort_keys=True))
    else:
        fns = inv["functions"]
        nsites = sum(len(v["sites"]) for v in fns.values())
        nunres = sum(1 for v in fns.values() if v["unresolved"])
        print(f"sqlguard inventory: {len(fns)} SQL-bearing functions, {nsites} resolved sites, "
              f"{nunres} functions with unresolved (runtime-composed) sites; "
              f"unparseable={len(inv['unparseable'])}; schema.sql readers={len(inv['extractors'])}; "
              f"exempt={inv['exempt']}")
