#!/usr/bin/env python3
"""Every server role a test plants is reapable after a KILLED run (a2 #62900, seed #62901).

A killed oracle skips its finally. A LOGIN NOSUPERUSER role it leaves behind reads every default-ACL database as CUT to
init.sh harden: astryx_cog's 8-arm red (#62806), minted by a test this time and attributed to nothing.

  CENSUS  (pure, no database) every `<conn>.execute(... CREATE ROLE ...)` in tests/*.py is found by AST, and its role
          name is resolved through the file's own bindings to a RENDERED name (a pid-shaped part renders as digits).
          The name must fullmatch _oracle_debris.TEST_ROLE, and the file must call reap() from _oracle_debris. Otherwise
          it must match its file's entry in ELSEWHERE, a reaper this oracle names, and the file must call reap(). A
          name the resolver can't render is RED, never a pass. A line that reads `execute(...CREATE ROLE` with no site
          found is RED too: the resolver missed a shape.
  SELF    the census run on synthetic sources: a matched site passes; an unmatched prefix, an unresolved name and a
          missing reap() call each go RED.
  LIVE    roles planted under a DEAD pid (rotate's with CONNECT on this database, pg_role_sync's with CONNECT on
          postgres, restore_drill's NOLOGIN) are all dropped by reap(). A live pid's is kept. One held by a grant inside
          a database still standing is kept, and reap() does not raise.
Sees only DB-API execute() sites: a role made by psql or a shell is invisible to it.
Exit 0 pass · 1 fail · 77 the census passed but no admin database was reachable for LIVE.
"""
import ast
import copy
import itertools
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
fails = []

# Roles whose reaper is NOT _oracle_debris's TEST_ROLE pass. These are declared here, not derived: each file reaps by
# its own rule, and the census still requires every one of its sites to match the pattern and the file to call reap().
ELSEWHERE = {
    "test_people_gate.py": (r"astryx_pgate_\d+_(?:res|clr|mem|inr|inc|priv|net)", "its own reap() at start, by NAME"),
    "test_social_age_design.py": (r"astryx_sadz_\d+_\w+", "its own reap() at start, by PFX"),
    "test_runscope.py": (r"bc_\d+x\d+", "_oracle_debris.reap's ledger and TEST_STAMP passes, or runscope.orphan_roles "
                                         "for a production-stamped dead orphan"),
}
PID = "4242"
PIDISH = re.compile(r"pid|epoch|time", re.I)


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def test_role_regex(src: str) -> re.Pattern:
    """_oracle_debris.TEST_ROLE, read from source (importing it needs psycopg, and the census runs without it)."""
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TEST_ROLE" for t in n.targets):
            return re.compile(ast.literal_eval(n.value.args[0]))
    raise LookupError("TEST_ROLE not found in tests/_oracle_debris.py")


class Unresolved(Exception):
    pass


class File:
    def __init__(self, name, src):
        self.name, self.src, self.tree = name, src, ast.parse(src)
        self.parent = {}
        for p in ast.walk(self.tree):
            for c in ast.iter_child_nodes(p):
                self.parent[c] = p

    def func_of(self, node):
        while node in self.parent:
            node = self.parent[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return self.tree

    def bindings(self, name, scope):
        """(lineno, value-node or ('param', fn)) for each binding of `name` directly in `scope` (nested defs excluded)."""
        out = []
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for a in scope.args.args + scope.args.kwonlyargs:
                if a.arg == name:
                    out.append((scope.lineno, ("param", scope)))
        stack = list(ast.iter_child_nodes(scope))
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            stack.extend(ast.iter_child_nodes(n))
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    out += [(n.lineno, v) for v in self._pair(t, n.value, name)]
            elif isinstance(n, ast.For):
                out += [(n.lineno, v) for v in self._for(n.target, n.iter, name)]
        return out

    @staticmethod
    def _pair(t, v, name):
        if isinstance(t, ast.Name) and t.id == name:
            return [v]
        if isinstance(t, ast.Tuple) and isinstance(v, ast.GeneratorExp):
            v = File._unroll(v) or v
        if isinstance(t, ast.Tuple) and isinstance(v, ast.Tuple) and len(t.elts) == len(v.elts):
            return [x for te, ve in zip(t.elts, v.elts) for x in File._pair(te, ve, name)]
        if isinstance(t, ast.Tuple) and any(isinstance(e, ast.Name) and e.id == name for e in t.elts):
            return [("opaque", v)]
        return []

    @staticmethod
    def _unroll(g):
        """`(f"…{s}…" for s in ("a", "b"))` as the tuple of its elements, or None for any other generator."""
        if len(g.generators) != 1 or g.generators[0].ifs:
            return None
        gen = g.generators[0]
        if not (isinstance(gen.target, ast.Name) and isinstance(gen.iter, (ast.Tuple, ast.List))):
            return None

        class Sub(ast.NodeTransformer):
            def __init__(self, item):
                self.item = item

            def visit_Name(self, n):
                return self.item if n.id == gen.target.id else n
        return ast.Tuple(elts=[Sub(item).visit(copy.deepcopy(g.elt)) for item in gen.iter.elts], ctx=ast.Load())

    @staticmethod
    def _for(t, it, name):
        if isinstance(t, ast.Name) and t.id == name:
            return list(it.elts) if isinstance(it, (ast.Tuple, ast.List)) else [("opaque", it)]
        return [("opaque", it)] if any(isinstance(e, ast.Name) and e.id == name for e in ast.walk(t)) else []

    def resolve_name(self, name, at):
        scope = self.func_of(at)
        while True:
            bs = sorted((b for b in self.bindings(name, scope) if b[0] <= at.lineno or scope is not self.func_of(at)),
                        key=lambda b: b[0])
            if bs:
                line = bs[-1][0]
                vals = [v for ln, v in bs if ln == line]        # one line can bind it to each element of a tuple loop
                out = []
                for v in vals:
                    if isinstance(v, tuple) and v[0] == "param":
                        out += self.resolve_param(name, v[1])
                    elif isinstance(v, tuple):
                        raise Unresolved(f"{name} is bound by {ast.unparse(v[1])[:60]!r}")
                    else:
                        out += self.render(v)
                return out
            if scope is self.tree:
                raise Unresolved(f"{name} has no binding")
            scope = self.func_of(scope)

    def resolve_param(self, name, fn):
        pos = [a.arg for a in fn.args.args].index(name) if name in [a.arg for a in fn.args.args] else None
        out, calls = [], 0
        for c in ast.walk(self.tree):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == fn.name:
                calls += 1
                arg = next((k.value for k in c.keywords if k.arg == name), None)
                if arg is None and pos is not None and pos < len(c.args):
                    arg = c.args[pos]
                if arg is None:
                    raise Unresolved(f"{fn.name}() call at line {c.lineno} passes no {name}")
                out += self.render(arg)
        if not calls:
            raise Unresolved(f"{name} is a parameter of {fn.name}(), which is never called here")
        return out

    def resolve_attr(self, node):
        base, attr = node.value, node.attr
        if not isinstance(base, ast.Name):
            raise Unresolved(f"attribute {ast.unparse(node)}")
        for n in ast.walk(self.tree):                   # a module imported under that name: read the constant from source
            if isinstance(n, ast.ImportFrom) and n.module:
                for a in n.names:
                    if (a.asname or a.name) == base.id:
                        return self.module_const(f"{n.module}.{a.name}", attr)
        if attr == "name":                              # a Path's .name: the last segment of `<dir> / <f-string>`
            v = self.resolve_value(base.id, node)
            if isinstance(v, ast.BinOp) and isinstance(v.op, ast.Div):
                return self.render(v.right)
        raise Unresolved(f"attribute {ast.unparse(node)}")

    def resolve_value(self, name, at):
        bs = sorted((b for b in self.bindings(name, self.func_of(at)) if b[0] <= at.lineno), key=lambda b: b[0])
        return bs[-1][1] if bs else None

    @staticmethod
    def module_const(mod, attr):
        for base in (REPO / "src", REPO):
            p = base / Path(*mod.split(".")).with_suffix(".py")
            if p.is_file():
                for n in ast.parse(p.read_text()).body:
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == attr for t in n.targets) \
                            and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                        return [n.value.value]
        raise Unresolved(f"{mod}.{attr} is not a string constant in source")

    def render(self, node):
        """Every string `node` can be, with a pid-shaped part as digits. Raises Unresolved, never guesses."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts.append([v.value])
                    continue
                try:
                    parts.append(self.render(v.value))
                except Unresolved:
                    if not PIDISH.search(ast.unparse(v.value)):
                        raise
                    parts.append([PID])
            return ["".join(p) for p in itertools.product(*parts)]
        if isinstance(node, ast.Name):
            return self.resolve_name(node.id, node)
        if isinstance(node, ast.Attribute):
            return self.resolve_attr(node)
        raise Unresolved(f"expression {ast.unparse(node)[:60]!r}")


def _sql_text(node):
    """The SQL text of a CREATE ROLE statement node, or None. Returns (text, name-expression or None)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, None
    if isinstance(node, ast.JoinedStr):
        first = node.values[0] if node.values else None
        nxt = node.values[1] if len(node.values) > 1 else None
        if isinstance(first, ast.Constant) and isinstance(nxt, ast.FormattedValue) and first.value.strip() == "CREATE ROLE":
            return first.value, nxt.value
        return (first.value, None) if isinstance(first, ast.Constant) else (None, None)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        inner = node.func.value
        if isinstance(inner, ast.Call) and inner.args:
            lead = inner.args[0]
            while isinstance(lead, ast.BinOp):
                lead = lead.left
            if isinstance(lead, ast.Constant) and isinstance(lead.value, str) and lead.value.startswith("CREATE ROLE {}"):
                arg = node.args[0] if node.args else None
                if isinstance(arg, ast.Call) and arg.args:          # sql.Identifier(X)
                    arg = arg.args[0]
                return lead.value, arg
    return None, None


def census(files: dict, test_role: re.Pattern) -> list:
    """[(file, line, ok, why)] for every CREATE ROLE site in `files` {name: source}."""
    out = []
    for fname, src in sorted(files.items()):
        try:
            f = File(fname, src)
        except SyntaxError as e:
            out.append((fname, e.lineno or 0, False, f"does not parse: {e.msg}"))
            continue
        imports_reap = any(isinstance(n, ast.ImportFrom) and n.module == "_oracle_debris"
                           and any(a.name == "reap" for a in n.names) for n in ast.walk(f.tree))
        calls_reap = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "reap"
                         for n in ast.walk(f.tree))
        found = set()
        for n in ast.walk(f.tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "execute" and n.args):
                continue
            text, expr = _sql_text(n.args[0])
            if not text or not text.lstrip().upper().startswith("CREATE ROLE"):
                continue
            found.add(n.lineno)
            try:
                if expr is None:
                    m = re.match(r"\s*CREATE ROLE\s+\"?([A-Za-z0-9_]+)", text, re.I)
                    if not m:
                        raise Unresolved("no name in the statement text")
                    names = [m.group(1)]
                else:
                    names = f.render(expr)
            except Unresolved as e:
                out.append((fname, n.lineno, False, f"UNRESOLVED: {e}"))
                continue
            other = ELSEWHERE.get(fname)
            for name in names:
                if test_role.fullmatch(name):
                    ok = imports_reap and calls_reap
                    why = f"{name} ~ TEST_ROLE" + ("" if ok else ", but the file never calls _oracle_debris.reap()")
                elif other and re.fullmatch(other[0], name):
                    ok = calls_reap
                    why = f"{name} ~ {other[1]}" + ("" if ok else ", but the file never calls reap()")
                else:
                    ok, why = False, f"{name} matches no reaper (TEST_ROLE{' or ' + other[0] if other else ''})"
                out.append((fname, n.lineno, ok, why))
        for i, line in enumerate(src.splitlines(), 1):    # a shape the AST pass missed is RED, not invisible
            if re.search(r"execute\(.*CREATE ROLE", line) and i not in found:
                out.append((fname, i, False, "an execute(...CREATE ROLE line no site was resolved for"))
    return out


print("census:")
files = {p.name: p.read_text() for p in sorted(TESTS.glob("*.py")) if p.name != Path(__file__).name}
TR = test_role_regex((TESTS / "_oracle_debris.py").read_text())
rows = census(files, TR)
for fname, line, ok, why in rows:
    check(f"tests/{fname}:{line}  {why}", ok)
check("the census found the role sites it must (rotate, pg_role_sync, restore_drill, init_harden)",
      {r[0] for r in rows} >= {"test_rotate_db_password.py", "test_pg_role_sync.py", "test_restore_drill.py",
                               "test_init_harden.py"}, str(sorted({r[0] for r in rows})))

print("self (synthetic sources):")
GOOD = 'import os\nfrom _oracle_debris import reap\nreap(c)\nn = f"astryx_fx_rot_{os.getpid()}"\nc.execute(f"CREATE ROLE {n} LOGIN")\n'
syn = {
    "good.py": GOOD,
    "prefix.py": GOOD.replace("astryx_fx_rot_", "astryx_fx_newthing_"),
    "unresolved.py": GOOD.replace('f"astryx_fx_rot_{os.getpid()}"', "make_name()"),
    "noreap.py": GOOD.replace("reap(c)\n", ""),
    "sqlfmt.py": 'from _oracle_debris import reap\nreap(a)\nfor r in ("x_1",):\n'
                 '    a.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(r)))\n',
}
# its own regex: these arms test the census, not TEST_ROLE (a red on main here would be a label, not a quantity)
got = {f: (ok, why) for f, _, ok, why in census(syn, re.compile(r"^astryx_fx_rot_(\d+)$"))}
check("a matched, reaped site passes", got.get("good.py", (False,))[0], str(got.get("good.py")))
check("an unmatched prefix goes RED, named", got.get("prefix.py", (True, ""))[0] is False
      and "astryx_fx_newthing_4242 matches no reaper" in got["prefix.py"][1], str(got.get("prefix.py")))
check("an unresolved name goes RED as UNRESOLVED", got.get("unresolved.py", (True, ""))[0] is False
      and got["unresolved.py"][1].startswith("UNRESOLVED"), str(got.get("unresolved.py")))
check("a TEST_ROLE site whose file never calls reap() goes RED", got.get("noreap.py", (True, ""))[0] is False
      and "never calls" in got["noreap.py"][1], str(got.get("noreap.py")))
check("a sql.SQL(...).format(sql.Identifier(<loop var>)) site resolves through the loop (x_1 matches nothing: RED)",
      got.get("sqlfmt.py", (True, ""))[0] is False and "x_1 matches no reaper" in got["sqlfmt.py"][1],
      str(got.get("sqlfmt.py")))

print("live:")
try:
    sys.path[:0] = [str(REPO), str(TESTS)]
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from astryx.security.sqlguard.fixture import fixture_db, live_dsn
    adm = psycopg.connect(live_dsn(), autocommit=True, connect_timeout=5)
    if not adm.execute("SELECT rolcreaterole OR rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:
        raise PermissionError("this role can't CREATE ROLE")
    from _oracle_debris import reap
except Exception as e:                                                 # noqa: BLE001
    print(f"  SKIP  live: {type(e).__name__}: {e}")
    print(f"\n{'FAIL: ' + str(len(fails)) + ' arm(s)' if fails else 'SKIP (partial): the census passed, LIVE ran nothing'}")
    sys.exit(1 if fails else 77)

reap(adm)                                   # this oracle plants roles too: a killed run's are reaped here
p = subprocess.Popen(["true"]); p.wait()
p2 = subprocess.Popen(["true"]); p2.wait()
here = adm.execute("SELECT current_database()").fetchone()[0]
dead = {f"astryx_fx_rot_{p.pid}": here, f"astryx_fx_rot_sync_{p.pid}": "postgres", f"astryx_fx_drill_{p.pid}": None}
live_one = f"astryx_fx_rot_{os.getpid()}"
held = f"astryx_fx_drill_{p2.pid}"          # held by a grant inside a fixture DB: fixture.reap owns a killed run's
mine = [*dead, live_one, held]
try:
    for r, db in dead.items():
        adm.execute(sql.SQL("CREATE ROLE {} " + ("LOGIN PASSWORD {}" if db else "NOLOGIN")).format(
            sql.Identifier(r), *([sql.Literal(os.urandom(12).hex())] if db else [])))
        if db:
            adm.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db), sql.Identifier(r)))
    adm.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(live_one)))
    adm.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(held)))
    with fixture_db() as fx:
        with psycopg.connect(make_conninfo(live_dsn(), dbname=fx["dbname"]), autocommit=True) as h:
            h.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(held)))
        try:
            got, err = reap(adm), None
        except Exception as e:                                          # noqa: BLE001
            got, err = [], f"{type(e).__name__}: {e}"
        exists = {r for (r,) in adm.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (mine,)).fetchall()}
    check("reap() does not raise on a role a standing database's grant still holds", err is None, err or "")
    for r, db in dead.items():
        check(f"a dead run's {r.rsplit('_', 1)[0]}_<pid> ({'CONNECT on ' + db if db else 'NOLOGIN'}) is reaped",
              r not in exists and r in got, f"exists={r in exists} reaped={r in got}")
    check("a LIVE pid's role is kept", live_one in exists and live_one not in got)
    check("a dead pid's role held by a grant inside a standing database is KEPT, not reported reaped",
          held in exists and held not in got, f"exists={held in exists} reaped={held in got}")
finally:
    for r in mine:
        if adm.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (r,)).fetchone():
            for (d,) in adm.execute("SELECT DISTINCT d.datname FROM pg_database d, aclexplode(d.datacl) a JOIN pg_roles "
                                    "g ON g.oid = a.grantee WHERE g.rolname = %s", (r,)).fetchall():
                adm.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(sql.Identifier(d), sql.Identifier(r)))
            adm.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(r)))
    left = adm.execute("SELECT count(*) FROM pg_roles WHERE rolname = ANY(%s)", (mine,)).fetchone()[0]
check("teardown: every planted role is gone (the fixture DB dropped itself)", left == 0, f"left={left}")

print(f"\n{'FAIL: ' + str(len(fails)) + ' arm(s)' if fails else 'ALL PASS'}")
sys.exit(1 if fails else 0)
