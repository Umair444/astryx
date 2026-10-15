#!/usr/bin/env python3
"""astryx · eager annotations: a name an import-time annotation uses before Python has bound it.

THE FAMILY (seed 10-15, CI run 38752675715). On Python 3.14 annotations are LAZY: they are evaluated only when
something asks for them. On 3.12 and 3.13 (requires-python is >=3.12, and CI runs 3.12) a def's parameter and return
annotations, and a class body's `x: T`, are evaluated when the def or class statement RUNS, which for module-level
and class-level code means at import. So a name that doesn't exist yet at that moment is a NameError that kills the
whole module on 3.12 and is invisible on the 3.14 host. observatory/api/main.py lost MemoryProposal that way.

test_undefined_names (pyflakes) catches a name that is bound NOWHERE. It cannot catch the spellings where the name IS
bound somewhere, just not in time (each measured: pyflakes rc 0, 3.12 NameError, 3.14 silent):
  later         the binding comes after the annotation: a later class, an assignment, a `for`/`with` target, a
                walrus, a `type X = …`, a match capture; and the commonest, a class naming itself inside its own
                body, since a class's name is bound only when its body has finished
  class scope   a method or `x: T` naming a class attribute assigned further down the same class body
  check-only    the name is bound only on a branch that never runs: `if TYPE_CHECKING:` or the else of
                `if not TYPE_CHECKING:`
This scan reports all of them.

WHY THE WALK IS GENERIC (a2 #55539). The first version listed the statement kinds it descended into and the kinds that
bind a name, by hand. A kind it didn't list failed OPEN: a def inside a module-level `with`, `for`, `while` or `match`
was never read, and a `for`/`with`/walrus/`type`/match binding read as "bound nowhere", which is pyflakes' job, and
pyflakes passes it. 11 such fixtures were green. Now statements() descends every statement-list field of every node
except a def or class (a new statement kind is walked by construction), and a statement binds every Name it stores in
its own header, plus the def/class/import/type/capture names.

DOMAIN, stated as part of the claim:
- files without `from __future__ import annotations` (that import makes every annotation lazy on every version);
- annotations evaluated at IMPORT: those of defs that run at module level or in a class body at any nesting (inside
  a with/for/while/match/try/if as well), and module/class-level `x: T`. A def nested in another def evaluates its
  annotations when the outer one runs, which is not the import path, so those are out of scope;
- bare Name nodes, resolved the way 3.12 resolves a class body: the class's own earlier bindings, then the module's.
  A string annotation is lazy everywhere. A name bound nowhere is pyflakes' finding, not this one.
A compound statement binds its header's names when the header runs; any other statement binds when it ends.
Known false positive, in the loud direction: a class attribute bound late whose name the module bound earlier.

    venv/bin/python devtools/eager_annotations.py [file …]     (default: every tracked .py)
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import sys
import warnings
from pathlib import Path

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _check_polarity(test: ast.expr) -> bool | None:
    """True for `if TYPE_CHECKING:`, False for `if not TYPE_CHECKING:`, None for any other test."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _check_polarity(test.operand)
        return None if inner is None else not inner
    if (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or \
            (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"):
        return True
    return None


def _compound(n: ast.stmt) -> bool:
    return any(isinstance(v, list) and v and isinstance(v[0], (ast.stmt, ast.excepthandler, ast.match_case))
               for _, v in ast.iter_fields(n))


def statements(body: list, check_only: bool = False):
    """(statement, never-runs?) for every statement executed in this scope: every statement-list field of every node
    is descended, except the bodies of a def or class, which are scopes of their own."""
    for n in body:
        yield n, check_only
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        pol = _check_polarity(n.test) if isinstance(n, ast.If) else None
        for field, value in ast.iter_fields(n):
            if not isinstance(value, list):
                continue
            branch = check_only or (pol is True and field == "body") or (pol is False and field == "orelse")
            for item in value:
                if isinstance(item, ast.stmt):
                    yield from statements([item], branch)
                elif isinstance(item, (ast.excepthandler, ast.match_case)):
                    yield from statements(item.body, branch)


def _stored(node: ast.AST, out: list) -> None:
    """Every name `node` binds in the enclosing scope. A def, class or lambda is a scope of its own; a
    comprehension's targets are its own scope too, though a walrus inside one binds outside."""
    if isinstance(node, _SCOPES):
        return
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        out.append((node.id, node.end_lineno))
    elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
        out.append((node.name, node.end_lineno))
    elif isinstance(node, ast.MatchMapping) and node.rest:
        out.append((node.rest, node.end_lineno))
    elif isinstance(node, ast.ExceptHandler) and node.name:
        out.append((node.name, node.lineno))
    for field, value in ast.iter_fields(node):
        if isinstance(node, ast.comprehension) and field == "target":
            continue
        for item in (value if isinstance(value, list) else [value]):
            if isinstance(item, ast.stmt):
                continue                                           # a nested statement binds on its own visit
            if isinstance(item, ast.match_case):
                _stored(item.pattern, out)
                if item.guard is not None:
                    _stored(item.guard, out)
            elif isinstance(item, ast.excepthandler):
                _stored(item, out)
            elif isinstance(item, ast.AST):
                _stored(item, out)


def _binds(n: ast.stmt) -> list:
    """(name, the line it is bound AFTER) for what statement `n` itself binds."""
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [(n.name, n.end_lineno)]
    if isinstance(n, (ast.Import, ast.ImportFrom)):
        return [((a.asname or a.name).split(".")[0], n.end_lineno) for a in n.names if a.name != "*"]
    if type(n).__name__ == "TypeAlias":
        return [(n.name.id, n.end_lineno)]
    if isinstance(n, ast.AnnAssign) and n.value is None:
        return []                                                  # `x: T` alone binds nothing
    found: list = []
    _stored(n, found)
    if _compound(n):
        return found                                               # bound when the header runs
    return [(name, n.end_lineno) for name, _ in found]             # bound when the statement ends


def _table(body: list) -> tuple[dict, set]:
    """name -> the earliest line it is bound after at runtime, and the names bound only on a never-run branch."""
    runtime: dict = {}
    never: set = set()
    for n, check_only in statements(body):
        for name, line in _binds(n):
            if check_only:
                never.add(name)
            elif name not in runtime or line < runtime[name]:
                runtime[name] = line
    return runtime, never


def _annotations(body: list, scopes: list, out: list) -> None:
    """(annotation, scope chain) for every annotation evaluated when this body runs at import."""
    for n, check_only in statements(body):
        if check_only:
            continue
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
                if arg.annotation is not None:
                    out.append((arg.annotation, scopes))
            if n.returns is not None:
                out.append((n.returns, scopes))
        elif isinstance(n, ast.ClassDef):
            _annotations(n.body, [_table(n.body), scopes[-1]], out)   # 3.12: own class body, then the module
        elif isinstance(n, ast.AnnAssign):
            out.append((n.annotation, scopes))


def scan_source(src: str | bytes, label: str = "<src>") -> list[str]:
    """Findings for one module, as `label:line: message`. An unparseable file is a finding, never a pass."""
    try:
        with warnings.catch_warnings():                # other files' invalid escapes are not this gate's finding
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(src)
    except SyntaxError as e:
        return [f"{label}:{e.lineno}: does not parse ({e.msg})"]
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names):
            return []
    anns: list = []
    _annotations(tree.body, [_table(tree.body)], anns)
    found = []
    for ann, scopes in anns:
        for x in ast.walk(ann):
            if not isinstance(x, ast.Name) or hasattr(builtins, x.id):
                continue
            if any(x.id in rt and rt[x.id] < x.lineno for rt, _ in scopes):
                continue                                   # bound in time in a scope this annotation can see
            later = [rt[x.id] for rt, _ in scopes if x.id in rt]
            if later:
                found.append(f"{label}:{x.lineno}: '{x.id}' is used in an import-time annotation before it is bound "
                             f"(line {min(later)}); a NameError on Python 3.12/3.13")
            elif any(x.id in never for _, never in scopes):
                found.append(f"{label}:{x.lineno}: '{x.id}' is bound only on a branch that never runs (TYPE_CHECKING) "
                             f"but used in an import-time annotation; a NameError on Python 3.12/3.13")
    return found


def tracked(repo: Path) -> list[Path]:
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "*.py"], capture_output=True, text=True,
                         check=True).stdout
    return [repo / f for f in out.split("\0") if f]


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    files = [Path(f) for f in sys.argv[1:]] or tracked(repo)
    found = [hit for f in files for hit in scan_source(f.read_bytes(), str(f))]
    for hit in found:
        print(f"  ✗ {hit}")
    print(f"{'FAIL' if found else 'PASS'}: {len(found)} import-time annotation(s) naming an unbound name, "
          f"in {len(files)} file(s)")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
