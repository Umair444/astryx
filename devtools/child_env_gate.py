#!/usr/bin/env python3
"""The child-env gate (plan-10224 child-env-gate; a3 #61402, seed #61404 / ruling #61406): no oracle hands a subprocess
an env that silently DROPS the parent's cog registry pin.

On a cog host (/etc/astryx/cog.json, live since 10-19 16:11) check.sh:51 and estate.gate()'s setdefault (dbe0d0e) pin
every gate's ASTRYX_COG_REGISTRY to a path naming no file. A child launched with an env built from scratch loses that
pin, reads the host's LIVE registry from a fake tree, and either refuses or looks for its org in the live estate. On
10-20 that was tool ledger, session strip and tool nudge ("0 rows") and spawn.sh --render ("no charter for 'member'"),
the last hidden on main behind the first's crash. Each fix is one call; this gate is the partition that keeps the next
one from hiding behind a crash, a SKIP, or a host that isn't a cog.

Every `env=` handed to a subprocess spawner in tests/*.py is in exactly one bucket:
  GREEN inherit   the env starts from os.environ (os.environ, .copy(), dict(os.environ, …), {**os.environ, …}, or a
                  name whose EVERY assignment is one of those). Green BECAUSE THE PARENT CARRIES THE PIN: check.sh:51
                  and estate.gate() set it, and an inheriting env passes it on. If that parent pin ever goes, this
                  bucket stops being safe, and the gate can't see it.
  GREEN helper    propagate.env_for_child(...): it carries the parent's pin (b3d04c5).
  GREEN own-reg   the env NAMES its own ASTRYX_COG_REGISTRY (a dict key, a dict(...) keyword, or `env[...] = …` on
                  the name): it decided which cog its child sees instead of dropping the pin. A literal under /etc
                  (the host's live registry) is never green.
  (an env-builder defined in the same file, `def env(...)` / `fx.env(...)`, is followed to its returns: green when
   every return is green)
  GREEN child     the spawned program provably never imports astryx: an all-literal argv whose program is a plain tool
                  (git, node, tmux, psql, …) and no argument names a repo path, including inside a `bash -c` body. A
                  repo script is never green this way: spawn.sh is bash that calls orgs.py.
  DECLARED        `# own-env: <why>` on the call's lines or the line above: a REAL reason a human wrote (the oracle
                  asserts its own env; the child provably reads no registry; …). The ONLY allowlist.
  RED             anything else: a scratch dict, a mixed or unresolved name, an env-builder call (fx.env, sb.env).

It reads python by AST and under-reports by construction: a spawner it doesn't recognise, or an env passed through
**kwargs, is quiet. STATED RESIDUAL, out of domain: devtools/branch_check.py and devtools/mutation_probe.py build child
envs for check.sh itself (mutation_probe pins the registry on its own). NON-OVERLAP: forge's gate_census class (r)
(census-unpinned-spawn, #61182) reports a SERVICE start in a gate whose files never pin; it names "a pin that a
scratch-built env drops" as its residual, and this gate is that residual at the call site.

  venv/bin/python devtools/child_env_gate.py [--root <repo>]     # 0 clean · 1 findings, each named
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import warnings
from pathlib import Path

DECLARE = re.compile(r"#\s*own-env:\s*\S")
SPAWNERS = {"run", "Popen", "call", "check_call", "check_output", "create_subprocess_exec", "create_subprocess_shell"}
SPAWN_MODULES = {"subprocess", "asyncio"}
# programs that never import astryx on their own; a repo path anywhere in the argv still disqualifies them
PLAIN = {"git", "node", "npm", "npx", "tmux", "psql", "pg_dump", "pg_restore", "docker", "curl", "openssl", "ssh-keygen",
         "sleep", "true", "false", "cat", "echo", "ls", "grep", "sed", "awk", "tar", "chromium", "bash", "sh",
         "systemctl"}
# systemctl verbs that START something (a unit may run astryx): never provably plain
SYSTEMCTL_STARTS = {"start", "restart", "reload", "reload-or-restart", "try-restart", "enable", "isolate", "kill"}
SHELLS = {"bash", "sh"}
REGISTRY = "ASTRYX_COG_REGISTRY"
# a token that names a repo path: in ANY literal argument it makes the child not provably plain
PATH_HINT = re.compile(r"\.py\b|\.sh\b|\.mjs\b|scripts/|devtools/|src/|hooks/|init\.sh|\./")
# a token that may RUN repo code: checked in a shell's body only (a git ref or a unit named astryx-… is just data)
CODE_HINT = re.compile(r"python|astryx|orgs\b|venv|\$PY\b|spawn")


def _finding(rel, line, why):
    return {"file": rel, "line": line, "why": why}


def _declared(lines: list[str], node: ast.AST) -> bool:
    lo, hi = node.lineno - 1, getattr(node, "end_lineno", node.lineno)
    return any(0 < n <= len(lines) and DECLARE.search(lines[n - 1]) for n in range(lo, hi + 1))


class _Scopes:
    """name -> the expressions assigned to it, per function and at module level."""

    def __init__(self, tree):
        self.parent = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                self.parent[id(c)] = n
        self.assigns: dict = {}
        self.sets_registry: set = set()                                  # (scope, name) with `name[REGISTRY] = …`
        self.defs: dict = {}                     # function name -> [(its FunctionDef, the _Scopes it lives in)] (builders)
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.defs.setdefault(n.name, []).append((n, self))
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) \
                            and isinstance(t.slice, ast.Constant) and t.slice.value == REGISTRY:
                        self.sets_registry.add((id(self.scope(n)), t.value.id))
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if isinstance(t, ast.Name):
                        self.assigns.setdefault((id(self.scope(n)), t.id), []).append(n.value)
            elif isinstance(n, (ast.For, ast.AsyncFor)) and isinstance(n.target, ast.Tuple) \
                    and isinstance(n.iter, (ast.Tuple, ast.List)):
                # `for who, e in ((a, fx.env(…)), (b, penv))`: each loop name sees its column of the literal rows
                for i, t in enumerate(n.target.elts):
                    if isinstance(t, ast.Name):
                        for row in n.iter.elts:
                            if isinstance(row, (ast.Tuple, ast.List)) and i < len(row.elts):
                                self.assigns.setdefault((id(self.scope(n)), t.id), []).append(row.elts[i])
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                self.assigns.setdefault((id(self.scope(n)), n.target.id), []).append(n)   # `env |= {...}`: keeps its base
        self.module = tree

    def scope(self, n):
        p = self.parent.get(id(n))
        while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            p = self.parent.get(id(p))
        return p

    def values(self, name: str, at) -> list:
        """The assignments the name sees from `at`: its own scope, then each ENCLOSING one (a lambda or nested def
        reads its outer function's names), then the module."""
        s = self.scope(at)
        while s is not None:
            got = self.assigns.get((id(s), name), [])
            if got:
                return got
            s = self.scope(s)
        return self.assigns.get((id(None), name), [])


def _is_environ(n) -> bool:
    return ast.unparse(n) in ("os.environ", "environ")


def _callee(n: ast.Call) -> str:
    f = n.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


GREEN = ("inherit", "helper", "own-registry")


def _own_registry_value(v) -> bool:
    """A registry value the gate accepts as the env's own choice: anything but a literal under /etc (the live host's)."""
    return not (isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value.startswith("/etc"))


def _prefixes(call: ast.Call) -> list[str] | None:
    out = []
    for a in call.args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            out.append(a.value)
        elif isinstance(a, ast.Tuple) and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in a.elts):
            out += [e.value for e in a.elts]
        else:
            return None
    return out or None


def _filter_keeps_registry(cond) -> bool:
    """True when a comprehension's `if` provably KEEPS ASTRYX_COG_REGISTRY. Shapes it can judge:
    `k not in (lits)` / `k in (lits)` (an allowlist keeps only what it names), `k != lit` / `k == lit`,
    `[not] k.startswith(lits)`, and `and`/`or`/`not` over those. Anything else (a set the gate can't see, a call
    it doesn't know) can't be proven and reads as dropping it."""
    if isinstance(cond, ast.BoolOp):
        parts = [_filter_keeps_registry(v) for v in cond.values]
        return all(parts) if isinstance(cond.op, ast.And) else any(parts)
    if isinstance(cond, ast.UnaryOp) and isinstance(cond.op, ast.Not):
        inner = cond.operand
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "startswith":
            ps = _prefixes(inner)
            return ps is not None and not any(REGISTRY.startswith(p) for p in ps)
        return not _filter_keeps_registry(inner) if isinstance(inner, ast.Compare) else False
    if isinstance(cond, ast.Call) and isinstance(cond.func, ast.Attribute) and cond.func.attr == "startswith":
        ps = _prefixes(cond)
        return ps is not None and any(REGISTRY.startswith(p) for p in ps)
    if isinstance(cond, ast.Compare) and len(cond.ops) == 1:
        op, col = cond.ops[0], cond.comparators[0]
        if isinstance(op, (ast.In, ast.NotIn)):
            if not isinstance(col, (ast.Tuple, ast.List, ast.Set)) or \
                    not all(isinstance(e, ast.Constant) for e in col.elts):
                return False
            named = REGISTRY in {e.value for e in col.elts}
            return named if isinstance(op, ast.In) else not named
        if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(col, ast.Constant):
            return (col.value == REGISTRY) if isinstance(op, ast.Eq) else (col.value != REGISTRY)
    return False


def env_kind(v, sc: _Scopes, depth=0, busy=frozenset()) -> str:
    """'inherit' | 'helper' | 'own-registry' | 'red:<shape>' for the expression handed to env=. `busy` holds the
    builder defs and parameters being judged up the stack, so a helper that shares a name with what it calls
    (`def env(...): return fx.env(...)`) is judged by the OTHER definition, never by recursing into itself."""
    if depth > 12:
        return "red:too deep"
    if _is_environ(v):
        return "inherit"
    if isinstance(v, ast.Call):
        name = _callee(v)
        if name == "env_for_child":
            return "helper"
        reg = next((k.value for k in v.keywords if k.arg == REGISTRY), None)
        if reg is not None:                  # dict(…, ASTRYX_COG_REGISTRY=…) or a builder handed one explicitly
            return "own-registry" if _own_registry_value(reg) else "red:the host's live registry, by name"
        if name == "copy" and isinstance(v.func, ast.Attribute) and _is_environ(v.func.value):
            return "inherit"
        if name == "dict" and v.args and _is_environ(v.args[0]):
            return "inherit"
        if name == "dict" and v.args and isinstance(v.args[0], ast.Name):
            return env_kind(v.args[0], sc, depth + 1, busy)                    # dict(base, X=…) inherits what base does
        if name in sc.defs:                  # a builder defined here or in a tests/ module this file imports: its returns
            rets = [(r.value, home, d) for d, home in sc.defs[name] if id(d) not in busy for r in ast.walk(d)
                    if isinstance(r, ast.Return) and r.value]
            kinds = [env_kind(r, home, depth + 1, busy | {id(d)}) for r, home, d in rets]
            if kinds and all(k in GREEN for k in kinds):
                return "own-registry" if "own-registry" in kinds else "inherit"
        return f"red:an env-builder call {ast.unparse(v.func)}()"
    if isinstance(v, ast.Dict):
        reg = next((val for k, val in zip(v.keys, v.values) if isinstance(k, ast.Constant) and k.value == REGISTRY), None)
        if reg is not None:
            return "own-registry" if _own_registry_value(reg) else "red:the host's live registry, by name"
        bases = [val for k, val in zip(v.keys, v.values) if k is None]   # the `**x` unpacks
        if any(_is_environ(b) for b in bases):
            return "inherit"
        for b in bases:
            k = env_kind(b, sc, depth + 1, busy)
            if k in GREEN:
                return k
        return "red:a dict built from scratch"
    if isinstance(v, ast.DictComp) and len(v.generators) == 1:
        g = v.generators[0]
        it = g.iter
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and it.func.attr == "items" \
                and _is_environ(it.func.value):
            # {k: v for k, v in os.environ.items() if …}: a FILTERED copy keeps the pin unless the filter can drop it
            return "inherit" if all(_filter_keeps_registry(c) for c in g.ifs) else \
                "red:an os.environ copy whose filter can drop ASTRYX_COG_REGISTRY"
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and it.func.attr == "items" \
                and isinstance(it.func.value, ast.Name):
            base = env_kind(it.func.value, sc, depth + 1, busy)          # a filtered copy of a GREEN env
            if base in GREEN and all(_filter_keeps_registry(c) for c in g.ifs):
                return base
        return "red:a dict comprehension that doesn't copy a green env"
    if isinstance(v, ast.IfExp):                                         # `a if c else b`: green only if BOTH are
        kinds = {env_kind(v.body, sc, depth + 1, busy), env_kind(v.orelse, sc, depth + 1, busy)}
        if kinds <= set(GREEN):
            return "own-registry" if "own-registry" in kinds else "inherit" if "inherit" in kinds else "helper"
        return "red:a conditional env with a non-inheriting branch"
    if isinstance(v, ast.BinOp) and isinstance(v.op, ast.BitOr):        # `os.environ | {...}`, `base | {...}`
        return env_kind(v.left, sc, depth + 1, busy)
    if isinstance(v, ast.Name):
        if (id(sc.scope(v)), v.id) in sc.sets_registry or (id(None), v.id) in sc.sets_registry:
            return "own-registry"
        vals = sc.values(v.id, v)
        if not vals:
            return _param_kind(v, sc, depth, busy)
        kinds = set()
        for x in vals:
            kinds.add("inherit" if isinstance(x, ast.AugAssign) else env_kind(x, sc, depth + 1, busy))
        if kinds <= set(GREEN):
            return "own-registry" if "own-registry" in kinds else "inherit" if "inherit" in kinds else "helper"
        return f"red:the name {v.id!r} has a non-inheriting assignment"
    return f"red:a {type(v).__name__} the gate can't classify"


def _param_kind(v: ast.Name, sc: _Scopes, depth: int, busy) -> str:
    """A parameter of the enclosing function, judged by what EVERY call of that function in this module passes for it
    (positionally or by keyword). Unresolved, or a function with no call here, stays red."""
    fn = sc.scope(v)
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or id(fn) in busy:
        return f"red:the name {v.id!r} doesn't resolve here (a parameter?)"
    params = [a.arg for a in fn.args.args]
    kwonly = [a.arg for a in fn.args.kwonlyargs]
    if v.id not in params and v.id not in kwonly:
        return f"red:the name {v.id!r} doesn't resolve here"
    pos = params.index(v.id) if v.id in params else 10 ** 6             # keyword-only: never positional
    tree = sc.module
    calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == fn.name]
    if not calls:
        return f"red:the parameter {v.id!r} of {fn.name}() has no caller here"
    kinds = set()
    for c in calls:
        arg = next((k.value for k in c.keywords if k.arg == v.id), None)
        if arg is None and pos < len(c.args):
            arg = c.args[pos]
        if arg is None:
            return f"red:a call of {fn.name}() passes no {v.id!r}"
        kinds.add(env_kind(arg, sc, depth + 1, busy | {id(fn)}))
    if kinds <= set(GREEN):
        return "own-registry" if "own-registry" in kinds else "inherit" if "inherit" in kinds else "helper"
    return f"red:the parameter {v.id!r} of {fn.name}() is passed a non-inheriting env"


def _argv(call: ast.Call):
    """The argv as a list where each element is its literal string, or None when it's built at runtime."""
    if not call.args:
        return None
    a = call.args[0]
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        return a.value.split()
    if isinstance(a, (ast.List, ast.Tuple)):
        return [e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else None for e in a.elts]
    return None


def plain_child(call: ast.Call) -> bool:
    """True when the spawned program provably never imports astryx (seed #61406 bucket 2): its program is a literal
    plain tool, no literal argument names a repo path, and a SHELL's whole argv is literal (its body is visible, and a
    body naming a repo path, `bash -c "… spawn.sh …"`, is never plain). For a non-shell tool a runtime argument is
    data (a path git reads), so it's allowed; git's literal subcommand must not be one that runs hooks."""
    argv = _argv(call)
    if not argv or argv[0] is None:
        return False
    prog = argv[0].rsplit("/", 1)[-1]
    if prog not in PLAIN:
        return False
    rest = argv[1:]
    if prog in SHELLS and any(x is None for x in rest):
        return False
    if any(x is not None and PATH_HINT.search(x) for x in rest):
        return False
    if prog in SHELLS and any(CODE_HINT.search(x) for x in rest):
        return False
    if prog == "systemctl" and any(x in SYSTEMCTL_STARTS for x in rest if x is not None):
        return False
    if prog == "git":
        lits = [x for x in rest if x is not None]
        sub = next((x for x in lits if not x.startswith("-")), None)    # `-C <path>` and other options skipped
        # subcommands that can run a repository's hooks (core.hooksPath may point into this repo): never plain. The
        # tuple stays inline, the right side of `in`: "merge" is also a SQL verb, and sqlguard's site forms (D5) read a
        # bare verb as safe only by that USE
        if sub is None or "-c" in lits or any(x in ("commit", "push", "merge", "rebase", "am", "checkout", "switch",
                                                    "pull", "worktree", "cherry-pick", "revert", "gc") for x in lits):
            return False
    return True


def _spawner(call: ast.Call, aliases: set[str], bare: set[str]) -> bool:
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in SPAWNERS:
        return isinstance(f.value, ast.Name) and f.value.id in aliases
    return isinstance(f, ast.Name) and f.id in bare


def _parse(text: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        try:
            return ast.parse(text)
        except SyntaxError:
            return None


def _sibling_defs(tree, tests_dir: Path | None, cache: dict) -> dict:
    """Builders defined in the tests/ modules this file from-imports (org_home_fixture's OrgHomes.env), judged in THEIR
    module's scope: a fixture helper that sets its own registry is green wherever it's called."""
    out: dict = {}
    if tests_dir is None:
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and not n.level:
            f = tests_dir / f"{n.module}.py"
            if not f.is_file():
                continue
            if f not in cache:
                t = _parse(f.read_text(errors="replace"))
                cache[f] = _Scopes(t) if t is not None else None
            if cache[f] is not None:
                for k, v in cache[f].defs.items():
                    out.setdefault(k, []).extend(v)
    return out


def classify_text(text: str, rel: str, tests_dir: Path | None = None, cache: dict | None = None) -> list[dict]:
    """Every spawner env= site with its bucket: inherit | helper | own-registry | child | declared | red."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
    lines = text.splitlines()
    aliases, bare = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name in SPAWN_MODULES:
                    aliases.add(a.asname or a.name)
        elif isinstance(n, ast.ImportFrom) and n.module in SPAWN_MODULES:
            for a in n.names:
                if a.name in SPAWNERS:
                    bare.add(a.asname or a.name)
    sc = _Scopes(tree)
    for k, v in _sibling_defs(tree, tests_dir, {} if cache is None else cache).items():
        sc.defs.setdefault(k, []).extend(v)
    out = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and _spawner(n, aliases, bare)):
            continue
        env = next((k.value for k in n.keywords if k.arg == "env"), None)
        if env is None:
            continue                                                     # no env= inherits the parent's
        kind = env_kind(env, sc)
        bucket = kind if kind in GREEN else "child" if plain_child(n) else "declared" if _declared(lines, n) else "red"
        out.append({**_finding(rel, n.lineno, kind.split(":", 1)[1] if bucket == "red" else bucket), "bucket": bucket})
    return out


def scan_text(text: str, rel: str, tests_dir: Path | None = None, cache: dict | None = None) -> list[dict]:
    """The RED sites only (the gate's findings)."""
    return [f for f in classify_text(text, rel, tests_dir, cache) if f["bucket"] == "red"]


def census(root: Path) -> list[dict]:
    out, cache = [], {}
    for p in sorted((root / "tests").glob("*.py")):
        out += classify_text(p.read_text(errors="replace"), p.relative_to(root).as_posix(), root / "tests", cache)
    return out


def scan(root: Path) -> list[dict]:
    return [f for f in census(root) if f["bucket"] == "red"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    a = ap.parse_args(argv)
    found = scan(Path(a.root))
    for f in found:
        print(f"  {f['file']}:{f['line']}  {f['why']}: route it through propagate.env_for_child, or say why it "
              f"needs its own env (`# own-env: <why>`)")
    print(f"child-env gate: {len(found)} finding(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
