#!/usr/bin/env python3
"""astryx · eager annotations: a name an import-time annotation uses before Python has bound it.

THE FAMILY (seed 10-15, CI run 38752675715). On Python 3.14 annotations are LAZY: they are evaluated only when
something asks for them. On 3.12 and 3.13 (requires-python is >=3.12, and CI runs 3.12) a def's parameter and return
annotations, and a class body's `x: T`, are evaluated when the def or class statement RUNS, which for module-level
and class-level code means at import. So a name that doesn't exist yet at that moment is a NameError that kills the
whole module on 3.12 and is invisible on the 3.14 host. observatory/api/main.py lost MemoryProposal that way.

test_undefined_names (pyflakes) catches a name that is bound NOWHERE. It cannot catch the two spellings where the
name IS bound somewhere, just not in time (measured: pyflakes rc 0 on both, 3.12 NameError on both):
  later         the binding comes after the annotation: `def f(p: Later)` above `class Later`, and the commonest
                one, a class naming itself inside its own body (`class Node: def f(self) -> Node`), since a class's
                name is bound only when its body has finished
  check-only    the name is imported only under `if TYPE_CHECKING:`, which never runs
This scan reports both.

DOMAIN, stated as part of the claim:
- files without `from __future__ import annotations` (that import makes every annotation lazy on every version);
- annotations evaluated at IMPORT: those of module-level defs, of class bodies at any nesting and of their methods,
  and module/class-level `x: T`. A def nested in another def evaluates its annotations when the outer one runs, which
  is not the import path, so those are out of scope;
- bare Name nodes resolved against MODULE-level bindings. A string annotation is lazy everywhere, and a name bound in
  a class scope is never compared against the module, so neither is read as a forward reference.
A binding counts from the END of its statement (a def or class name exists only once the statement completes).

    venv/bin/python devtools/eager_annotations.py [file …]     (default: every tracked .py)
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import sys
import warnings
from pathlib import Path


def _is_check_only(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or \
           (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")


def _bindings(body: list, runtime: dict, check_only: dict, in_check: bool = False) -> None:
    """Module-level names -> the line they are bound AFTER. Names bound only under `if TYPE_CHECKING:` go apart."""
    for n in body:
        names: list[str] = []
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [n.name]
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names = [(a.asname or a.name).split(".")[0] for a in n.names]
        elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            if isinstance(n, ast.AnnAssign) and n.value is None:
                continue                                       # `x: T` alone binds nothing
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            names = [x.id for t in targets for x in ast.walk(t) if isinstance(x, ast.Name)]
        elif isinstance(n, ast.If):
            _bindings(n.body, runtime, check_only, in_check or _is_check_only(n.test))
            _bindings(n.orelse, runtime, check_only, in_check)
            continue
        elif isinstance(n, ast.Try) or type(n).__name__ == "TryStar":
            for b in [n.body, n.orelse, n.finalbody] + [h.body for h in n.handlers]:
                _bindings(b, runtime, check_only, in_check)
            continue
        elif isinstance(n, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
            _bindings(n.body, runtime, check_only, in_check)
            continue
        for nm in names:
            (check_only if in_check else runtime).setdefault(nm, n.end_lineno)


def _eager(body: list, out: list) -> None:
    """Every annotation expression evaluated when this body runs at import."""
    for n in body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
                if arg.annotation is not None:
                    out.append(arg.annotation)
            if n.returns is not None:
                out.append(n.returns)
        elif isinstance(n, ast.ClassDef):
            _eager(n.body, out)
        elif isinstance(n, ast.AnnAssign):
            out.append(n.annotation)
        elif isinstance(n, ast.If):
            if not _is_check_only(n.test):
                _eager(n.body, out)
            _eager(n.orelse, out)
        elif isinstance(n, ast.Try) or type(n).__name__ == "TryStar":
            for b in [n.body, n.orelse, n.finalbody] + [h.body for h in n.handlers]:
                _eager(b, out)


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
    runtime: dict = {}
    check_only: dict = {}
    _bindings(tree.body, runtime, check_only)
    anns: list = []
    _eager(tree.body, anns)
    found = []
    for ann in anns:
        for x in ast.walk(ann):
            if not isinstance(x, ast.Name) or hasattr(builtins, x.id):
                continue
            bound = runtime.get(x.id)
            if bound is not None and bound >= x.lineno:
                found.append(f"{label}:{x.lineno}: '{x.id}' is used in an import-time annotation before it is bound "
                             f"(line {bound}); a NameError on Python 3.12/3.13")
            elif bound is None and x.id in check_only:
                found.append(f"{label}:{x.lineno}: '{x.id}' is imported only under TYPE_CHECKING but used in an "
                             f"import-time annotation; a NameError on Python 3.12/3.13")
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
