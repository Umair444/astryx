#!/usr/bin/env python3
"""astryx · is trigger N installed? (plan-9853 D1/D3, the one helper; a4 #49108 with a1/a2/a3's binding conditions)

The question is about the PULSE'S REGISTRATION SEMANTICS. src/astryx/pulse/pulse.py discover() runs each triggers/<agent>/*.py
in a subprocess and registers the WHOLE astryx._registry, which every @trigger decorator EXECUTED while the file ran
appends to (by fn.__name__). So a file registers its own top-level @trigger defs AND those of every in-repo module it
imports at top level, transitively: `from M import N` registers all of M's triggers, an alias registers the def's name,
`import M` registers them too, and `from pkg import submodule` imports the submodule (a2 R2).

This is a STATIC model of that: it reads, never executes (a2 G2). Every construct it does not positively understand
makes the file BLIND, and a blind file can hide any name, so a name that would otherwise read ABSENT reads DEFERRED
(a1 BC-1: an under-read is a duplicate install, the defect this exists to stop; deferral is the safe direction):
  - an import, or a decorated def, inside any top-level compound statement (if/try/with/for/while/class/match)
  - a decorator on a top-level def that isn't `trigger(...)` from `from astryx import trigger`, or `astryx.trigger(...)`
    from `import astryx` (an alias, an attribute chain, a call result, any other decorator)
  - the trigger function used other than as a decorator; exec/eval/compile/runpy/importlib/__import__ at top level;
    any top-level sys.path use EXCEPT the idiom it models: `sys.path.insert(i, <a path built from __file__>)`, alone
    or under `if <that path> not in sys.path:` (its directory is searched FIRST for every later import, as at runtime:
    src/astryx/hands/android.py puts mcp/phone there)
  - an in-repo-looking import that doesn't resolve, a relative import, or a star-import from an unresolvable module
  - a file that doesn't parse: its own `def N` lines count (textually), and it is blind for everything else
`if __name__ == "__main__":` (no else) is skipped: under discover it never runs (runpy names the file <run_path>).
tests/test_trigger_names.py checks the model against discover() itself (parity) over the fixtures and the live corpus.

STATES of (N, target agent), in this order:
  installed  some triggers/<a>/*.py's closure has N, and (a, N) has no tombstone   (global: any agent's copy counts)
  retired    triggers/<target>/.retired/N exists (trigger_rm's tombstone; per TARGET agent, a3 BC-1)
  deferred   N might exist where this can't see: a blind file; a LEGACY python row for N with no file and no tombstone
             (a removal, a departed agent or a lossy restore: indistinguishable, so the owner chooses: `trigger_rm N`
             or `init.sh --reinstall N`); or the triggers table can't be read
  absent     none of the above: init.sh installs it

CLI (init.sh and doctor call this; nothing else re-implements the question):
  python -m astryx.core.trigger_names state N [--target seed]   → prints "<state> <detail>"; exit 0/1/2/3 =
                                                                installed/retired/absent/deferred
  python -m astryx.core.trigger_names names FILE                → the names FILE registers, as JSON (rc 3 if blind)
Import-safe with no .env (a4 #49617): the DSN is ASTRYX_DSN, else .env's line if there is one, else none.
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402
from astryx import config, paths  # noqa: E402

import ast
import importlib.machinery
import json
import os
import re
import sys
from pathlib import Path

REPO = repo_root(__file__)
STATES = {"installed": 0, "retired": 1, "absent": 2, "deferred": 3}
_DYNAMIC = {"exec", "eval", "compile", "runpy", "importlib", "__import__"}
_COMPOUND = (ast.If, ast.Try, ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While, ast.ClassDef, ast.Match)
if hasattr(ast, "TryStar"):
    _COMPOUND += (ast.TryStar,)


class Read:
    """What one file registers: names, and why it's blind (empty = fully understood)."""

    def __init__(self):
        self.names: set[str] = set()
        self.blind: list[str] = []


# ── resolution: where would `import a.b.c` come from, run as the pulse runs it ──────────────────────────────────────
# The pulse runs a file with cwd = REPO first on sys.path. A `sys.path.insert(i, <a path built from __file__>)` executed
# along the way puts its directory in FRONT (and it stays for every later import in that process), so the walk carries
# the roots in execution order: Walk.roots, newest insert first, then the repo.
class Walk:
    def __init__(self, repo: Path):
        self.repo = repo
        self.front: list[Path] = []
        self.seen: set[Path] = set()

    def roots(self) -> list[Path]:
        return self.front + [self.repo]


def _root_of(top: str, w: Walk) -> Path | None:
    """The root `top` imports from, or None if it isn't local (stdlib, site-packages). A module or regular package wins
    in path order; a bare directory (a namespace portion) loses to a module or regular package anywhere else."""
    for r in w.roots():
        if (r / f"{top}.py").is_file() or (r / top / "__init__.py").is_file():
            return r
    for r in w.roots():
        if (r / top).is_dir():
            local = {str(x.resolve()) for x in w.roots()}
            others = [q for q in sys.path if q and str(Path(q).resolve()) not in local]
            spec = importlib.machinery.PathFinder.find_spec(top, others)
            return r if spec is None or spec.origin is None else None
    return None


def _module_files(dotted: str, root: Path) -> list[Path] | None:
    """The files `import dotted` executes under `root`, parents first (each package's __init__.py, then the module),
    or None if it doesn't resolve there."""
    parts, out, d = dotted.split("."), [], root
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        if (d / p).is_dir() and ((d / p / "__init__.py").is_file() or not (d / f"{p}.py").is_file()):
            if (d / p / "__init__.py").is_file():
                out.append(d / p / "__init__.py")
            d = d / p
            if last:
                return out
        elif (d / f"{p}.py").is_file():
            out.append(d / f"{p}.py")
            return out if last else None                 # a module has no submodules
        else:
            return None
    return out


def _is_submodule(dotted: str, name: str, root: Path) -> bool:
    return any((b / f"{name}.py").is_file() or (b / name).is_dir()
               for b in (root.joinpath(*dotted.split(".")), root.joinpath("src", *dotted.split("."))))


def _static_path(node: ast.AST, env: dict, file: Path) -> Path | None:
    """A path expression built from __file__, evaluated statically: Path(__file__)[.resolve()|.absolute()], .parent,
    .parents[k], / "literal", str(...), and names bound to such at top level. Anything else → None."""
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.Call) and not node.keywords:
        f = node.func
        if isinstance(f, ast.Name) and f.id in ("Path", "str") and len(node.args) == 1:
            a = node.args[0]
            if f.id == "Path" and isinstance(a, ast.Name) and a.id == "__file__":
                return file
            return _static_path(a, env, file)
        if isinstance(f, ast.Attribute) and f.attr in ("resolve", "absolute") and not node.args:
            return _static_path(f.value, env, file)
        return None
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        b = _static_path(node.value, env, file)
        return b.parent if b else None
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents"
            and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int)):
        b = _static_path(node.value.value, env, file)
        try:
            return b.parents[node.slice.value] if b else None
        except IndexError:
            return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and isinstance(node.right, ast.Constant) \
            and isinstance(node.right.value, str):
        b = _static_path(node.left, env, file)
        return b / node.right.value if b else None
    return None


def _is_sys_path(n: ast.AST) -> bool:
    return isinstance(n, ast.Attribute) and n.attr == "path" and isinstance(n.value, ast.Name) and n.value.id == "sys"


def _path_inserts(s: ast.stmt, env: dict, file: Path) -> list[Path] | None:
    """The directories a top-level statement puts on sys.path, if it is the understood idiom:
    `sys.path.insert(i, <static path>)`, alone or under `if <static path> not in sys.path:` (no else). None if not."""
    def insert(st):
        if (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Attribute)
                and st.value.func.attr == list.insert.__name__   # not the bare literal: sqlguard reads a string
                and _is_sys_path(st.value.func.value)            # starting INSERT as an SQL site
                and len(st.value.args) == 2 and not st.value.keywords):
            return _static_path(st.value.args[1], env, file)
        return None
    one = insert(s)
    if one is not None:
        return [one]
    if (isinstance(s, ast.If) and not s.orelse and isinstance(s.test, ast.Compare) and len(s.test.ops) == 1
            and isinstance(s.test.ops[0], ast.NotIn) and _is_sys_path(s.test.comparators[0])
            and _static_path(s.test.left, env, file) is not None):
        got = [insert(b) for b in s.body]
        return got if got and all(g is not None for g in got) else None
    return None


def _main_guard(s: ast.stmt) -> bool:
    """`if __name__ == "__main__":` with no else. Under discover it never runs: runpy.run_path names the file
    "<run_path>", and an imported module is never __main__."""
    t = getattr(s, "test", None)
    return (isinstance(s, ast.If) and not s.orelse and isinstance(t, ast.Compare) and len(t.ops) == 1
            and isinstance(t.ops[0], ast.Eq) and isinstance(t.left, ast.Name) and t.left.id == "__name__"
            and isinstance(t.comparators[0], ast.Constant) and t.comparators[0].value == "__main__")


# ── the walk ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _uses(node: ast.AST, pred) -> bool:
    """Does `node` contain a node satisfying pred, not counting the bodies of defs/lambdas (they don't run at import)?
    A def's decorators and defaults DO run, so they're walked."""
    stack = [node]
    while stack:
        n = stack.pop()
        if pred(n):
            return True
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(n.decorator_list)
            stack.extend(d for d in n.args.defaults + n.args.kw_defaults if d is not None)
            continue
        if isinstance(n, ast.Lambda):
            continue
        stack.extend(ast.iter_child_nodes(n))
    return False


def _read_module(dotted: str, w: Walk, out: Read, blind, s) -> Path | None:
    """Read every file `import dotted` executes; its root, or None (and blind) if it's local-looking but unresolved.
    Not local at all (stdlib, site-packages) → Ellipsis: nothing to read."""
    try:
        from astryx._reorg import legacy_module      # goal 10224 S4: a moved nucleus.* is read where it lives
        dotted = legacy_module(dotted) or dotted
    except ImportError:
        pass
    root = _root_of(dotted.split(".")[0], w)
    if root is None:
        return ...
    files = _module_files(dotted, root)
    if files is None and dotted.split(".")[0] == "astryx" and (root / "src" / "astryx" / "__init__.py").is_file():
        files = _module_files(dotted, root / "src")    # the root shim's __path__ is src/astryx/
    if files is None:
        blind(f"`{dotted}` doesn't resolve under {root}", s)
        return None
    for f in files:
        _read(f, w, out)
    return root


def _read(path: Path, w: Walk, out: Read):
    path = path.resolve()
    if path in w.seen:
        return
    w.seen.add(path)
    rel = str(path.relative_to(w.repo)) if path.is_relative_to(w.repo) else str(path)
    try:
        src = path.read_text()
    except (OSError, ValueError) as e:
        out.blind.append(f"{rel}: unreadable ({type(e).__name__})")
        return
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError) as e:              # F2: its own defs, textually; blind for everything else
        out.names |= set(re.findall(r"^def\s+([A-Za-z_]\w*)\s*\(", src, re.M))
        out.blind.append(f"{rel}: doesn't parse ({type(e).__name__})")
        return
    trig = {"trigger": False, "astryx": False}           # how the trigger decorator is bound in THIS file
    env: dict[str, Path] = {}                            # top-level names bound to a static path (REPO = Path(__file__)…)

    def blind(why, node):
        out.blind.append(f"{rel}:{getattr(node, 'lineno', '?')}: {why}")

    for s in tree.body:
        if _main_guard(s):                               # never runs under discover: imported, or run as <run_path>
            continue
        ins = _path_inserts(s, env, path)
        if ins is not None:                              # the understood sys.path idiom: its roots go in FRONT
            for d in ins:
                w.front.insert(0, d.resolve())
            continue
        if isinstance(s, _COMPOUND):
            if _uses(s, lambda n: isinstance(n, (ast.Import, ast.ImportFrom))
                     or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.decorator_list)):
                blind(f"an import or decorated def inside a top-level {type(s).__name__.lower()}", s)
        if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
            v = _static_path(s.value, env, path)
            if v is not None:
                env[s.targets[0].id] = v
            else:
                env.pop(s.targets[0].id, None)
        if isinstance(s, ast.Import):
            for a in s.names:
                if a.name == "astryx":
                    if a.asname:
                        blind("`import astryx as …` (an alias of the trigger module)", s)
                    else:
                        trig["astryx"] = True
                _read_module(a.name, w, out, blind, s)
            continue
        if isinstance(s, ast.ImportFrom):
            if s.level:
                blind("a relative import", s)
                continue
            mod = s.module or ""
            if mod == "astryx":
                for a in s.names:
                    if a.name == "trigger":
                        if a.asname:
                            blind("`from astryx import trigger as …` (an alias of the decorator)", s)
                        else:
                            trig["trigger"] = True
                    elif a.name == "*":
                        blind("`from astryx import *`", s)
            root = _read_module(mod, w, out, blind, s)
            if root is None and any(a.name == "*" for a in s.names):
                blind(f"a star-import from `{mod}`, which doesn't resolve", s)
            if isinstance(root, Path):
                for a in s.names:                        # `from pkg import submodule` imports the submodule (a2 R2)
                    if a.name != "*" and _is_submodule(mod, a.name, root):
                        _read_module(f"{mod}.{a.name}", w, out, blind, s)
            continue
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in s.decorator_list:
                plain = (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "trigger"
                         and trig["trigger"])
                dotted = (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "trigger"
                          and isinstance(d.func.value, ast.Name) and d.func.value.id == "astryx" and trig["astryx"])
                if plain or dotted:
                    out.names.add(s.name)
                else:
                    blind(f"`@{ast.unparse(d)}` on {s.name} isn't the trigger decorator as imported", s)
        # anything else that runs at import: the trigger used other than as a decorator, a dynamic import or exec, or
        # a sys.path use other than the idiom above (the imports after it may resolve where this can't see)
        rest = s
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rest = ast.Module(body=[], type_ignores=[])  # its decorators were judged above; its body doesn't run
            for d in s.decorator_list:
                if isinstance(d, ast.Call):
                    rest.body.extend(ast.Expr(a) for a in d.args + [k.value for k in d.keywords])
        if _uses(rest, lambda n: isinstance(n, ast.Name) and n.id in _DYNAMIC):
            blind("exec/eval/compile/runpy/importlib/__import__ at top level", s)
        if _uses(rest, lambda n: (isinstance(n, ast.Name) and n.id == "trigger" and trig["trigger"])
                 or (isinstance(n, ast.Attribute) and n.attr == "trigger")):
            blind("the trigger decorator used other than as a decorator", s)
        if _uses(rest, _is_sys_path):
            blind("a top-level sys.path use other than `sys.path.insert(i, <a path from __file__>)`", s)


def names(path: Path | str, repo: Path | None = None) -> Read:
    """What the pulse registers from `path`: its closure's @trigger names, and the reasons it's blind (if any)."""
    out = Read()
    _read(Path(path), Walk((repo or REPO).resolve()), out)
    return out


# ── the row side: read ONLY to tell a legacy row-only name, restricted to kind='python' (a2 G3) ──────────────────
def _dsn(repo: Path) -> str | None:
    # this module's own tree reads the ORG's .env (its estate: the HOME in a cog of several orgs); another tree, its own
    env = (paths.estate(__file__) if Path(repo).resolve() == REPO.resolve() else Path(repo)) / ".env"
    try:
        return config.dsn(env)
    except (LookupError, OSError):
        return None


def _python_rows(name: str, repo: Path) -> list[str] | None:
    """Agents with a python row for `name`, or None if the table can't be read."""
    dsn = _dsn(repo)
    if not dsn:
        return None
    try:
        import psycopg
        with psycopg.connect(dsn, connect_timeout=5) as c:
            return [r[0] for r in c.execute("SELECT agent FROM triggers WHERE kind='python' AND name=%s",
                                            (name,)).fetchall()]
    except Exception:
        return None


def state(name: str, target: str = "seed", repo: Path | None = None) -> tuple[str, str]:
    """(state, detail) for trigger `name`, whose shipped installer targets `target`."""
    repo = (repo or REPO).resolve()
    # the triggers the PULSE registers are its ESTATE's (pulse.py: paths.estate(__file__) / "triggers"): this module's own
    # tree reads the ORG's (its HOME in a cog of several orgs; on one org, this tree), the rule _dsn uses. Imports still
    # resolve against the CODE tree (Walk(repo)). Another tree, its own (S7b: a cog org's doctor read the primary's).
    try:
        root = (paths.estate(__file__) if repo == REPO.resolve() else repo) / "triggers"
    except paths.NoHome as e:                  # a cog of several orgs and no HOME carried: whose triggers is unknown
        return "deferred", f"no org HOME is carried here, so whose triggers/ this asks is unknown: set ASTRYX_HOME ({e})"
    retired = lambda a: (root / a / ".retired" / name).exists()   # noqa: E731
    blind, defined_by = [], []
    for f in sorted(root.glob("*/*.py")):
        r = names(f, repo)
        agent = f.parent.name
        if name in r.names:
            defined_by.append(agent)
            if not retired(agent):
                return "installed", f"triggers/{agent}/{f.name}"
        if r.blind:
            blind.append(r.blind[0])
    if retired(target):
        return "retired", f"triggers/{target}/.retired/{name} (trigger_rm's tombstone)"
    if blind:                                       # global scope: one unreadable file defers EVERY absent install,
        return "deferred", (f"{len(blind)} trigger file(s) this can't read statically, so {name} may be defined "
                            f"there: {'; '.join(blind[:3])}. Exit: fix or move that file (or "
                            f"`./init.sh --reinstall {name}` to install it anyway)")   # so name the way out (a4 #50070)
    rows = _python_rows(name, repo)
    if rows is None:
        return "deferred", "the triggers table can't be read, so a legacy row for it can't be ruled out"
    legacy = sorted({a for a in rows if a not in defined_by and not retired(a)})
    if legacy:
        return "deferred", (f"LEGACY: a python row for {name} under {', '.join(legacy)} with no file defining it and "
                            f"no tombstone (a removal, a departed agent or a lossy restore). Choose: "
                            f"`trigger_rm {name}` to retire it, or `./init.sh --reinstall {name}` to install it")
    return "absent", "no file defines it, no tombstone, no row"


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "state":
        target = argv[argv.index("--target") + 1] if "--target" in argv else "seed"
        s, detail = state(argv[1], target)
        print(f"{s} {detail}")
        return STATES[s]
    if len(argv) == 2 and argv[0] == "names":
        r = names(Path(argv[1]).resolve())
        print(json.dumps(sorted(r.names)))
        for b in r.blind:
            print(f"blind: {b}", file=sys.stderr)
        return 3 if r.blind else 0
    print("usage: python -m astryx.core.trigger_names state N [--target AGENT] | names FILE", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
