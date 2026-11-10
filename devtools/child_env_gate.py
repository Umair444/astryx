#!/usr/bin/env python3
"""The child-env gate (plan-10224 child-env-gate; a3 #61402, seed #61404 / ruling #61406): no oracle hands a subprocess
an env that silently DROPS the parent's cog registry pin.

On a cog host (/etc/astryx/cog.json, live since 10-19 16:11) check.sh:51 and estate.gate()'s setdefault (dbe0d0e) pin
every gate's ASTRYX_COG_REGISTRY to a path naming no file. A child launched with an env built from scratch loses that
pin, reads the host's LIVE registry from a fake tree, and either refuses or looks for its org in the live estate. On
10-20 that was tool ledger, session strip and tool nudge ("0 rows") and spawn.sh --render ("no charter for 'member'"),
the last hidden on main behind the first's crash. Each fix is one call; this gate is the partition that keeps the next
one from hiding behind a crash, a SKIP, or a host that isn't a cog. GREEN MEANS PROVEN: a shape the gate can't decide
reads red, never green (a3 #61413).

Every `env=` handed to a subprocess spawner in tests/*.py is in exactly one bucket:
  GREEN inherit   the env starts from os.environ (os.environ, .copy(), dict(os.environ, …), {**os.environ, …},
                  `os.environ | {…}`, a `{k: v for k, v in os.environ.items() if …}` whose filter PROVABLY keeps the
                  registry, or a name whose every assignment is one of those and that is never popped/deleted/cleared
                  of the registry). Green BECAUSE THE PARENT CARRIES THE PIN: check.sh:51 and estate.gate() set it, and
                  an inheriting env passes it on. If that parent pin ever goes, this bucket stops being safe, and the
                  gate can't see it.
  GREEN helper    propagate.env_for_child(...): it carries the parent's pin (b3d04c5).
  GREEN own-reg   the env NAMES its own ASTRYX_COG_REGISTRY: a dict key, a keyword, the right side of `|`, or
                  `env[REGISTRY] = …` set earlier in the same block as the spawn. A literal under /etc (the host's
                  live registry) is never green, on any of those paths.
  (an env-builder is followed to its returns: a function by its name, a method through its receiver, `with
   OrgHomes(…) as fx` … `fx.env()`, in this file or in a tests/ module it imports the class or function from)
  GREEN child     the spawned program provably never imports astryx. A literal plain tool (psql, docker, curl, …) with
                  no repo path in a literal argument; an INTERPRETER (bash, sh, node, tmux) only with an all-literal
                  argv that names no repo path and runs no repo code; git only with a READ-ONLY subcommand from an
                  allowlist (a hook-running one, or an alias like the host's `ci`, is never plain); systemctl never
                  with a verb that starts something. npm/npx run package.json scripts, so they're never plain. AND its
                  env must provably carry only SAFE keys (PATH, HOME, LANG/LC_*, TMPDIR, TZ, …): a scratch env can
                  carry code into a plain program (BASH_ENV, NODE_OPTIONS, GIT_CONFIG_*, a $CMD its body expands; a3
                  #61422), so an env the gate can't see, or an unclassed key, is not plain. git's options before the
                  subcommand come from an allowlist too (--exec-path, --config-env and -c never).
  DECLARED        `# own-env: <why>` on the call's lines or the line above: a REAL reason a human wrote (the oracle
                  asserts its own env; the child provably reads no registry; …). The ONLY allowlist.
  RED             anything else: a scratch dict, a mixed or unresolved name, a builder it can't follow.

`inherit` also stops being green in a file that pops or deletes the PARENT's registry from os.environ (or clears it):
a3 #61422 R5/R6. A scrub that provably can't reach it (a GIT_* loop, a literal tuple of other keys) doesn't count.

It reads python by AST and under-reports by construction. STATED RESIDUALS (a3 #61413/#61422): a spawner it doesn't
recognise (os.exec*, pty.spawn: 0 in tests/ on 10-20); an env reaching a function through **kwargs; a registry arriving
inside a mapping the gate can't read (`e.update(over)`, an unseen `**spread`); an ALIAS of a copy that's scrubbed
(`f = e; del f[REGISTRY]`, R13); a helper that takes the env and pops the key (R14). The last two are
interprocedural. devtools/
branch_check.py and devtools/mutation_probe.py build child envs for check.sh itself and are out of domain
(mutation_probe pins the registry on its own). NON-OVERLAP: forge's gate_census class (r) (census-unpinned-spawn,
#61182) reports a SERVICE start in a gate whose files never pin; it names "a pin that a scratch-built env drops" as its
residual, and this gate is that residual at the call site.

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
REGISTRY = "ASTRYX_COG_REGISTRY"
# programs that never import astryx on their own; a repo path in a literal argument still disqualifies them
PLAIN = {"psql", "pg_dump", "pg_restore", "docker", "curl", "openssl", "ssh-keygen", "sleep", "true", "false", "cat",
         "echo", "ls", "grep", "sed", "awk", "tar", "chromium", "systemctl", "git"}
# programs that RUN what their arguments say: plain only when every argument is literal, names no repo path and runs
# no repo code (tmux's command strings and node's -e bodies included, a3 #61413)
INTERPRETERS = {"bash", "sh", "node", "tmux"}
# git subcommands that never run a hook or a configured command: an ALLOWLIST, so an alias (`git ci`) or a new
# subcommand is never plain (a3 #61413: fetch → gc --auto, clone → post-checkout, the host's alias.ci → pre-commit)
GIT_READONLY = ("archive", "rev-parse", "log", "show", "status", "diff", "ls-files", "ls-tree", "cat-file",
                "for-each-ref", "merge-base", "init", "hash-object", "rev-list", "symbolic-ref", "describe",
                "name-rev", "shortlog", "blame", "grep", "check-ignore", "var", "version")
# keys a `child` env may carry (a3 #61422): a plain program is only plain if its env can't carry code into it
# (BASH_ENV, NODE_OPTIONS, GIT_CONFIG_*, LD_PRELOAD, a $CMD its body expands). An ALLOWLIST: an unclassed key = not plain
SAFE_ENV = ("PATH", "HOME", "LANG", "LANGUAGE", "TMPDIR", "TZ", "TERM", "USER", "LOGNAME", "XDG_RUNTIME_DIR",
            "TMUX_TMPDIR", "NO_COLOR")
# git's GLOBAL options a plain git may carry before its subcommand (a3 #61422 R10/R11: --exec-path, --config-env and
# -c are never plain). The ones taking a separate argument are skipped with it
GIT_OPTS_ARG = ("-C", "--git-dir", "--work-tree")
GIT_OPTS = ("--no-pager", "-P", "--bare", "--no-optional-locks", "--literal-pathspecs", "--no-replace-objects",
            "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs")
# systemctl verbs that START something (a unit may run astryx): never provably plain
SYSTEMCTL_STARTS = ("start", "restart", "reload", "reload-or-restart", "try-restart", "enable", "isolate", "kill")
# a token that names a repo path: in ANY literal argument it makes the child not provably plain
PATH_HINT = re.compile(r"\.py\b|\.sh\b|\.mjs\b|\.js\b|scripts/|devtools/|src/|hooks/|channel/|init\.sh|\./")
# a token that may RUN repo code or read the env: checked in an interpreter's arguments
CODE_HINT = re.compile(r"python|astryx|orgs\b|venv|\$PY\b|spawn|process\.env|import|require|\$ROOT|\$REPO")
GREEN = ("inherit", "helper", "own-registry")


def _finding(rel, line, why):
    return {"file": rel, "line": line, "why": why}


def _declared(lines: list[str], node: ast.AST) -> bool:
    lo, hi = node.lineno - 1, getattr(node, "end_lineno", node.lineno)
    return any(0 < n <= len(lines) and DECLARE.search(lines[n - 1]) for n in range(lo, hi + 1))


def _bodies(p) -> list[list]:
    return [getattr(p, f) for f in ("body", "orelse", "finalbody") if isinstance(getattr(p, f, None), list)]


class _Scopes:
    """name -> the expressions assigned to it, per function and at module level; registry sets and mutations; builders."""

    def __init__(self, tree):
        self.module = tree
        self.parent = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                self.parent[id(c)] = n
        self.assigns: dict = {}
        self.reg_sets: dict = {}           # (scope, name) -> [(the Assign stmt, its value)] for `name[REGISTRY] = …`
        self.mutations: dict = {}          # (scope, name) -> [why] for a pop/del/clear/popitem that can drop the pin
        self.writes: dict = {}             # (scope, name) -> [key or None] written by `name[k] =` / update / setdefault
        self.funcs: dict = {}              # function name -> [(def, home)]: module-level and nested functions
        self.classes: dict = {}            # class name -> {method name: [(def, home)]}
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                meths = self.classes.setdefault(n.name, {})
                for b in n.body:
                    if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        meths.setdefault(b.name, []).append((b, self))
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and not isinstance(self.parent.get(id(n)), ast.ClassDef):
                self.funcs.setdefault(n.name, []).append((n, self))
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) \
                            and isinstance(t.slice, ast.Constant) and t.slice.value == REGISTRY:
                        self.reg_sets.setdefault((id(self.scope(n)), t.value.id), []).append((n, n.value))
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if isinstance(t, ast.Name):
                        self.assigns.setdefault((id(self.scope(n)), t.id), []).append(n.value)
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                for it in n.items:
                    if isinstance(it.optional_vars, ast.Name):
                        self.assigns.setdefault((id(self.scope(n)), it.optional_vars.id), []).append(it.context_expr)
            elif isinstance(n, (ast.For, ast.AsyncFor)) and isinstance(n.target, ast.Tuple) \
                    and isinstance(n.iter, (ast.Tuple, ast.List)):
                # `for who, e in ((a, fx.env(…)), (b, penv))`: each loop name sees its column of the literal rows
                for i, t in enumerate(n.target.elts):
                    if isinstance(t, ast.Name):
                        for row in n.iter.elts:
                            if isinstance(row, (ast.Tuple, ast.List)) and i < len(row.elts):
                                self.assigns.setdefault((id(self.scope(n)), t.id), []).append(row.elts[i])
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                self.assigns.setdefault((id(self.scope(n)), n.target.id), []).append(n)   # `env |= {...}`: judged
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                        self.writes.setdefault((id(self.scope(n)), t.value.id), []).append(
                            t.slice.value if isinstance(t.slice, ast.Constant) else None)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) \
                    and n.func.attr in ("update", "setdefault"):
                ks = [k.arg for k in n.keywords]
                if n.func.attr == "setdefault":
                    ks = [n.args[0].value if n.args and isinstance(n.args[0], ast.Constant) else None]
                for a in n.args if n.func.attr == "update" else ():
                    ks += [k.value if isinstance(k, ast.Constant) else None for k in a.keys] \
                        if isinstance(a, ast.Dict) else [None]
                self.writes.setdefault((id(self.scope(n)), n.func.value.id), []).extend(ks)
            # WRITES through update()/setdefault() (a3 #61422 R4), recorded with the subscript sets
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) \
                    and n.func.attr in ("update", "setdefault"):
                stmt = self.parent.get(id(n))
                vals = []
                if n.func.attr == "setdefault":
                    if n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == REGISTRY:
                        vals.append(n.args[1] if len(n.args) > 1 else ast.Constant(value=None))
                else:
                    vals += [k.value for k in n.keywords if k.arg == REGISTRY]
                    for a in n.args:
                        if isinstance(a, ast.Dict):
                            vals += [val for k, val in zip(a.keys, a.values)
                                     if isinstance(k, ast.Constant) and k.value == REGISTRY]
                    for k in n.keywords:
                        if k.arg is None and isinstance(k.value, ast.Dict):
                            vals += [val for kk, val in zip(k.value.keys, k.value.values)
                                     if isinstance(kk, ast.Constant) and kk.value == REGISTRY]
                for val in vals:
                    self.reg_sets.setdefault((id(self.scope(n)), n.func.value.id), []).append((stmt, val))
            # MUTATIONS (a3 #61413 B1–B3): a green name that loses the registry key is not green
            why = None
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name):
                m, tgt = n.func.attr, n.func.value.id
                if m in ("clear", "popitem"):
                    why = f"{tgt}.{m}()"
                elif m == "pop" and n.args and not _never_registry(n.args[0], self):
                    why = f"{tgt}.pop({ast.unparse(n.args[0])[:30]})"
                if why:
                    self.mutations.setdefault((id(self.scope(n)), tgt), []).append(why)
            if isinstance(n, ast.Delete):
                for t in n.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and not _never_registry(t.slice, self):
                        self.mutations.setdefault((id(self.scope(n)), t.value.id), []).append(
                            f"del {ast.unparse(t)[:40]}")

    def scope(self, n):
        p = self.parent.get(id(n))
        while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            p = self.parent.get(id(p))
        return p

    def _chain(self, at):
        """at's own scope, then each ENCLOSING one, then the module (None)."""
        s = self.scope(at)
        while s is not None:
            yield s
            s = self.scope(s)
        yield None

    def values(self, name: str, at) -> list:
        """The assignments the name sees from `at` (a lambda or nested def reads its outer function's names)."""
        for s in self._chain(at):
            got = self.assigns.get((id(s), name), [])
            if got:
                return got
        return []

    def mutated(self, name: str, at) -> list:
        for s in self._chain(at):
            if (id(s), name) in self.mutations:
                return self.mutations[(id(s), name)]
            if (id(s), name) in self.assigns:
                return []
        return []

    def key_writes(self, name: str, at) -> list:
        for s in self._chain(at):
            if (id(s), name) in self.writes:
                return self.writes[(id(s), name)]
            if (id(s), name) in self.assigns:
                return []
        return []

    def live_registry_write(self, name: str, at) -> bool:
        """Any write of a literal under /etc to name[REGISTRY] in its scope, dominating or not (a3 #61422 R4)."""
        for s in self._chain(at):
            sets = self.reg_sets.get((id(s), name), [])
            if sets:
                return any(_own_registry(val) != "own-registry" for _, val in sets)
        return False

    def registry_set_before(self, name: str, at):
        """The value of a `name[REGISTRY] = …` that DOMINATES `at`: a statement earlier in the same block as one of
        at's enclosing statements (a3 #61413 B16: a set inside an `if` doesn't cover the unconditional spawn)."""
        sets = []
        for s in self._chain(at):
            sets = self.reg_sets.get((id(s), name), [])
            if sets:
                break
        if not sets:
            return None
        cur = at
        while cur is not None:
            p = self.parent.get(id(cur))
            if p is None:
                break
            for body in _bodies(p):
                if cur in body:
                    i = body.index(cur)
                    for stmt, val in sets:
                        if stmt in body and body.index(stmt) < i:
                            return val
            cur = p
        return None


def _is_environ(n) -> bool:
    return ast.unparse(n) in ("os.environ", "environ")


def _callee(n: ast.Call) -> str:
    f = n.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _own_registry(v) -> str:
    """A registry value the gate accepts as the env's own choice: anything but a literal under /etc (the live host's)."""
    live = isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value.startswith("/etc")
    return "red:the host's live registry, by name" if live else "own-registry"


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


def _is_key(n, key: str) -> bool:
    return isinstance(n, ast.Name) and n.id == key


def _keeps(cond, key: str):
    """TRI-STATE (a3 #61413 B4/B5/B6): True when a comprehension's `if` provably KEEPS ASTRYX_COG_REGISTRY, False when
    it provably DROPS it, None when the gate can't decide. Shapes it decides, on the comprehension's OWN key name:
    `key not in (lits)` / `key in (lits)` (an allowlist keeps only what it names), `key != lit` / `key == lit`,
    `key.startswith(lits)`, and and/or/not over those. `not` negates only a DECIDED result; anything else is None."""
    if isinstance(cond, ast.BoolOp):
        parts = [_keeps(v, key) for v in cond.values]
        if isinstance(cond.op, ast.And):
            return False if False in parts else True if all(p is True for p in parts) else None
        return True if True in parts else False if all(p is False for p in parts) else None
    if isinstance(cond, ast.UnaryOp) and isinstance(cond.op, ast.Not):
        r = _keeps(cond.operand, key)
        return None if r is None else not r
    if isinstance(cond, ast.Call) and isinstance(cond.func, ast.Attribute) and cond.func.attr == "startswith" \
            and _is_key(cond.func.value, key):
        ps = _prefixes(cond)
        return None if ps is None else any(REGISTRY.startswith(p) for p in ps)
    if isinstance(cond, ast.Compare) and len(cond.ops) == 1 and _is_key(cond.left, key):
        op, col = cond.ops[0], cond.comparators[0]
        if isinstance(op, (ast.In, ast.NotIn)):
            if not isinstance(col, (ast.Tuple, ast.List, ast.Set)) or \
                    not all(isinstance(e, ast.Constant) for e in col.elts):
                return None                                              # a set the gate can't see
            named = REGISTRY in {e.value for e in col.elts}
            return named if isinstance(op, ast.In) else not named
        if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(col, ast.Constant):
            return (col.value == REGISTRY) if isinstance(op, ast.Eq) else (col.value != REGISTRY)
    return None


def _never_registry(key, sc: "_Scopes") -> bool:
    """True when a deleted key provably isn't ASTRYX_COG_REGISTRY: another literal, or the target of a loop over
    `[k for k in os.environ if <filter>]` whose filter provably DROPS the registry (`k.startswith("GIT_")`: the GIT_*
    scrub of merge_ready/release_server)."""
    if isinstance(key, ast.Constant):
        return key.value != REGISTRY
    if not isinstance(key, ast.Name):
        return False
    p = sc.parent.get(id(key))
    while p is not None:
        if isinstance(p, (ast.For, ast.AsyncFor)) and isinstance(p.target, ast.Name) and p.target.id == key.id:
            it = p.iter
            lits = it if isinstance(it, (ast.Tuple, ast.List)) else None
            if isinstance(it, ast.Name):                                 # `for _v in LOCATORS:` a literal tuple
                vals = sc.values(it.id, it)
                lits = vals[0] if len(vals) == 1 and isinstance(vals[0], (ast.Tuple, ast.List)) else None
            if lits is not None:
                return all(isinstance(e, ast.Constant) and e.value != REGISTRY for e in lits.elts)
            if isinstance(it, ast.ListComp) and len(it.generators) == 1 and _is_environ(it.generators[0].iter) \
                    and isinstance(it.generators[0].target, ast.Name) and _is_key(it.elt, it.generators[0].target.id):
                k = it.generators[0].target.id
                return any(_keeps(c, k) is False for c in it.generators[0].ifs)
            return False
        p = sc.parent.get(id(p))
    return False


def _comp_keeps(v: ast.DictComp) -> bool:
    """A comprehension that emits `k: v` UNCHANGED over a mapping's items() and whose every filter provably keeps the
    registry (a3 #61413 B6: the filter must test the comprehension's own key)."""
    g = v.generators[0]
    if not (isinstance(g.target, ast.Tuple) and len(g.target.elts) == 2
            and all(isinstance(e, ast.Name) for e in g.target.elts)):
        return False
    k, val = g.target.elts[0].id, g.target.elts[1].id
    if not (_is_key(v.key, k) and _is_key(v.value, val)):
        return False
    return all(_keeps(c, k) is True for c in g.ifs)


def _fold(pairs: list, sc: "_Scopes", depth: int, busy) -> str | None:
    """A dict built from (key, value) entries IN ORDER, `None` keys being `**spreads` (a3 #61422 R1/R2): the LAST writer
    of ASTRYX_COG_REGISTRY wins. A literal key or a literal-dict spread decides it (/etc never green); a spread that's
    green (an inheriting or own-registry env) carries its pin; an unseen spread that isn't green changes nothing the gate
    can see (STATED RESIDUAL: a registry arriving inside a mapping the gate can't read). None when nothing gave a pin."""
    state = None
    for k, val in pairs:
        if k is None:
            if isinstance(val, ast.Dict):
                inner = _fold(list(zip(val.keys, val.values)), sc, depth, busy)
                if inner is not None:
                    state = inner
                continue
            kind = env_kind(val, sc, depth + 1, busy)
            if kind in GREEN or kind.startswith("red:the host's live registry"):
                state = kind
        elif isinstance(k, ast.Constant) and k.value == REGISTRY:
            state = _own_registry(val)
    return state if state is None or state in GREEN else state


def _merge(kinds: set) -> str | None:
    if kinds and kinds <= set(GREEN):
        return "own-registry" if "own-registry" in kinds else "inherit" if "inherit" in kinds else "helper"
    return None


def _class_of(e, sc: "_Scopes", depth: int):
    """The class an expression provably builds: `C(...)`, or `C(...).__enter__()` when C.__enter__ returns self, or a
    name/parameter every binding of which is one of those for one class C known here."""
    if depth > 12 or e is None:
        return None
    if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id in sc.classes:
        return e.func.id                                                 # C(...), `with C(...) as fx`
    if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) and e.func.attr == "__enter__" \
            and isinstance(e.func.value, ast.Call) and isinstance(e.func.value.func, ast.Name) \
            and _returns_self(sc.classes.get(e.func.value.func.id, {}).get("__enter__", [])):
        return e.func.value.func.id                                      # C(...).__enter__(), when it returns self
    if isinstance(e, ast.Name):
        return _receiver_class(e, sc, depth + 1)
    return None


def _receiver_class(recv, sc: "_Scopes", depth: int):
    """`fx` in `fx.env()` → the class it was built from (_class_of on every binding, or on what every caller here
    passes when it's a parameter, `arms(fx)`), when all agree on one class known here."""
    if not isinstance(recv, ast.Name) or depth > 12:
        return None
    vals = sc.values(recv.id, recv)
    if not vals:
        fn = sc.scope(recv)
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return None
        params = [a.arg for a in fn.args.args]
        if recv.id not in params:
            return None
        pos = params.index(recv.id)
        vals = []
        for c in ast.walk(sc.module):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == fn.name:
                vals.append(next((k.value for k in c.keywords if k.arg == recv.id),
                                 c.args[pos] if pos < len(c.args) else None))
        if not vals:
            return None
    got = {_class_of(v, sc, depth + 1) for v in vals}
    return got.pop() if len(got) == 1 and None not in got else None


def _returns_self(defs) -> bool:
    rets = [r.value for d, _ in defs for r in ast.walk(d) if isinstance(r, ast.Return)]
    return bool(rets) and all(isinstance(r, ast.Name) and r.id == "self" for r in rets)


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
        if reg is not None and name != "dict":   # a builder handed the registry explicitly: that value decides
            return _own_registry(reg)
        if name == "copy" and isinstance(v.func, ast.Attribute) and _is_environ(v.func.value):
            return "inherit"
        if name == "dict" and isinstance(v.func, ast.Name):                # dict(base, X=…, **{…}): base, then keys
            pairs = [(None, v.args[0])] if v.args else []
            pairs += [(ast.Constant(value=k.arg) if k.arg else None, k.value) for k in v.keywords]
            return _fold(pairs, sc, depth, busy) or "red:a dict() built from scratch"
        defs = []
        if isinstance(v.func, ast.Name):
            defs = sc.funcs.get(v.func.id, [])
        elif isinstance(v.func, ast.Attribute):
            c = _receiver_class(v.func.value, sc, depth + 1)
            if c is not None:
                defs = sc.classes[c].get(v.func.attr, [])
        rets = [(r.value, home, d) for d, home in defs if id(d) not in busy for r in ast.walk(d)
                if isinstance(r, ast.Return) and r.value]
        kind = _merge({env_kind(r, home, depth + 1, busy | {id(d)}) for r, home, d in rets})
        return kind or f"red:an env-builder call {ast.unparse(v.func)}() the gate can't follow"
    if isinstance(v, ast.Dict):
        return _fold(list(zip(v.keys, v.values)), sc, depth, busy) or "red:a dict built from scratch"
    if isinstance(v, ast.DictComp) and len(v.generators) == 1:
        it = v.generators[0].iter
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and it.func.attr == "items" \
                and _comp_keeps(v):
            base = env_kind(it.func.value, sc, depth + 1, busy)
            if base in GREEN:
                return base
        return "red:a comprehension the gate can't prove keeps ASTRYX_COG_REGISTRY"
    if isinstance(v, ast.IfExp):                                         # `a if c else b`: green only if BOTH are
        kind = _merge({env_kind(v.body, sc, depth + 1, busy), env_kind(v.orelse, sc, depth + 1, busy)})
        return kind or "red:a conditional env with a non-inheriting branch"
    if isinstance(v, ast.BinOp) and isinstance(v.op, ast.BitOr):        # `base | {...}`: the RIGHT side wins a key
        right = v.right
        if isinstance(right, ast.Dict) and None not in right.keys:
            reg = next((val for k, val in zip(right.keys, right.values)
                        if isinstance(k, ast.Constant) and k.value == REGISTRY), None)
            if reg is not None:
                return _own_registry(reg)
            return env_kind(v.left, sc, depth + 1, busy)
        return "red:a `|` whose right side the gate can't see"
    if isinstance(v, ast.Name):
        cut = sc.mutated(v.id, v)
        if cut:
            return f"red:the name {v.id!r} can lose the registry ({cut[0]})"
        live = sc.live_registry_write(v.id, v)
        if live:
            return "red:the host's live registry, written to the name"
        reg = sc.registry_set_before(v.id, v)
        if reg is not None:
            return _own_registry(reg)
        vals = sc.values(v.id, v)
        if not vals:
            return _param_kind(v, sc, depth, busy)
        kinds = set()
        for x in vals:
            if isinstance(x, ast.AugAssign):
                # `env |= {...}`: a literal dict that names the registry decides it; one that doesn't is neutral (the
                # name keeps what its other assignments are); anything else can't be seen
                r = x.value
                if isinstance(x.op, ast.BitOr) and isinstance(r, ast.Dict) and None not in r.keys:
                    reg = next((val for k, val in zip(r.keys, r.values)
                                if isinstance(k, ast.Constant) and k.value == REGISTRY), None)
                    if reg is not None:
                        kinds.add(_own_registry(reg))
                else:
                    kinds.add("red:an augmented assignment the gate can't see")
            else:
                kinds.add(env_kind(x, sc, depth + 1, busy))
        live = next((k for k in kinds if k.startswith("red:the host's live registry")), None)
        if live:
            return live                      # kept as-is, so a `**spread` of this name still decides the key
        return _merge(kinds) or f"red:the name {v.id!r} has a non-inheriting assignment"
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
    calls = [c for c in ast.walk(sc.module) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
             and c.func.id == fn.name]
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
    return _merge(kinds) or f"red:the parameter {v.id!r} of {fn.name}() is passed a non-inheriting env"


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


def _safe_key(k) -> bool:
    return isinstance(k, str) and (k in SAFE_ENV or k.startswith("LC_"))


def env_keys_safe(v, sc: "_Scopes", depth=0) -> bool:
    """True when the env provably carries ONLY safe keys (a3 #61422): a literal dict with no spreads, or a name every
    assignment of which is one, written only with safe keys. Anything the gate can't see is not safe."""
    if depth > 8:
        return False
    if isinstance(v, ast.Dict):
        return None not in v.keys and all(isinstance(k, ast.Constant) and _safe_key(k.value) for k in v.keys)
    if isinstance(v, ast.Name):
        vals = sc.values(v.id, v)
        if not vals or any(isinstance(x, ast.AugAssign) for x in vals):
            return False
        if any(k is None or not _safe_key(k) for k in sc.key_writes(v.id, v)):
            return False
        return all(env_keys_safe(x, sc, depth + 1) for x in vals)
    return False


def plain_child(call: ast.Call, sc: "_Scopes | None" = None) -> bool:
    """True when the spawned program provably never imports astryx (seed #61406 bucket 2; a3 #61413, #61422): the
    program is plain by its argv AND its env carries only safe keys (a scratch env can't smuggle code in)."""
    env = next((k.value for k in call.keywords if k.arg == "env"), None)
    if env is not None and not (sc is not None and env_keys_safe(env, sc)):
        return False
    argv = _argv(call)
    if not argv or argv[0] is None:
        return False
    prog = argv[0].rsplit("/", 1)[-1]
    rest = argv[1:]
    if prog in INTERPRETERS:
        return all(x is not None for x in rest) and not any(PATH_HINT.search(x) or CODE_HINT.search(x) for x in rest)
    if prog not in PLAIN:
        return False
    if any(x is not None and PATH_HINT.search(x) for x in rest):
        return False
    if prog == "systemctl":
        return not any(x in SYSTEMCTL_STARTS for x in rest if x is not None)
    if prog == "git":
        # git's own options before the subcommand, from an ALLOWLIST (`-C <path>` skipped with its argument); an
        # unknown option, or an argument built at runtime before the subcommand, means it isn't provably plain
        i = 0
        while i < len(rest) and rest[i] is not None and rest[i].startswith("-"):
            o = rest[i]
            if o in GIT_OPTS_ARG:
                i += 2
            elif o in GIT_OPTS or any(o.startswith(x + "=") for x in ("--git-dir", "--work-tree")):
                i += 1
            else:
                return False
        sub = rest[i] if i < len(rest) else None
        return sub in GIT_READONLY
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


def _import_siblings(sc: _Scopes, tests_dir: Path | None, cache: dict) -> None:
    """Builders from the tests/ modules this file from-imports, keyed by the IMPORTED NAME (a3 #61413 B14): `from
    org_home_fixture import OrgHomes` brings the class OrgHomes and its methods, judged in THEIR module's scope; a
    function brings itself. Nothing else of that module is visible here."""
    if tests_dir is None:
        return
    for n in ast.walk(sc.module):
        if not (isinstance(n, ast.ImportFrom) and n.module and not n.level):
            continue
        f = tests_dir / f"{n.module}.py"
        if not f.is_file():
            continue
        if f not in cache:
            t = _parse(f.read_text(errors="replace"))
            cache[f] = _Scopes(t) if t is not None else None
        other = cache[f]
        if other is None:
            continue
        for a in n.names:
            local = a.asname or a.name
            if a.name in other.classes:
                sc.classes.setdefault(local, {})
                for m, ds in other.classes[a.name].items():
                    sc.classes[local].setdefault(m, []).extend(ds)
            if a.name in other.funcs:
                sc.funcs.setdefault(local, []).extend(other.funcs[a.name])


def classify_text(text: str, rel: str, tests_dir: Path | None = None, cache: dict | None = None) -> list[dict]:
    """Every spawner env= site with its bucket: inherit | helper | own-registry | child | declared | red."""
    tree = _parse(text)
    if tree is None:                       # a file the gate can't read is never "no sites": its sites would vanish
        return [{**_finding(rel, 1, "the file doesn't parse, so none of its subprocess envs can be judged"),
                 "bucket": "red"}]
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
    _import_siblings(sc, tests_dir, {} if cache is None else cache)
    # a3 #61422 R5/R6: `inherit` is green only because the PARENT carries the pin; a file that pops or deletes it from
    # os.environ (or clears os.environ) can hand that loss on, so none of its inherit sites is green
    cuts_parent = any(
        (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and _is_environ(n.func.value)
         and (n.func.attr in ("clear", "popitem") or (n.func.attr == "pop" and n.args
                                                       and not _never_registry(n.args[0], sc))))
        or (isinstance(n, ast.Delete) and any(isinstance(t, ast.Subscript) and _is_environ(t.value)
                                              and not _never_registry(t.slice, sc) for t in n.targets))
        for n in ast.walk(tree))
    out = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and _spawner(n, aliases, bare)):
            continue
        env = next((k.value for k in n.keywords if k.arg == "env"), None)
        if env is None:
            continue                                                     # no env= inherits the parent's
        kind = env_kind(env, sc)
        if cuts_parent and kind == "inherit":
            kind = "red:this file pops or deletes the PARENT's registry (os.environ), so inheriting carries no pin"
        bucket = kind if kind in GREEN else "child" if plain_child(n, sc) else "declared" if _declared(lines, n) \
            else "red"
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
