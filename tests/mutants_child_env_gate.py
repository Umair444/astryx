"""Authored mutants for devtools/child_env_gate.py (plan-10224 child-env-gate), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_child_env_gate.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools/child_env_gate.py"
ORACLE = REPO / "tests" / "test_child_env_gate.py"
ENV = "CHILD_ENV_GATE_SRC"
TIMEOUT = 300

MUTANTS = {
    "C1 an exemption needs no reason (`# own-env:` alone declares)":
        ('DECLARE = re.compile(r"#\\s*own-env:\\s*\\S")', 'DECLARE = re.compile(r"#\\s*own-env:")'),
    "C2 a declaration anywhere above reaches the call (the window widened)":
        ('    lo, hi = node.lineno - 1, getattr(node, "end_lineno", node.lineno)',
         '    lo, hi = node.lineno - 3, getattr(node, "end_lineno", node.lineno)'),
    "C3 an interpreter's arguments are never read for repo code (bash -c / tmux / node -e read plain)":
        ("        return all(x is not None for x in rest) and not any(PATH_HINT.search(x) or CODE_HINT.search(x) "
         "for x in rest)",
         "        return all(x is not None for x in rest)"),
    "C4 a runtime interpreter argument is trusted (B9: node on a runtime path reads plain)":
        ("        return all(x is not None for x in rest) and not any(",
         "        return True and not any(x is not None and "),
    "C5 git's allowlist goes: any subcommand is plain (B12 fetch, B13 clone, B15 the `ci` alias)":
        ("        return sub in GIT_READONLY", "        return True"),
    "C6 systemctl start reads plain":
        ("        return not any(x in SYSTEMCTL_STARTS for x in rest if x is not None)", "        return True"),
    "C7 tri-state lost: `not` turns an UNKNOWN into PROVEN (B4, B5)":
        ("        return None if r is None else not r", "        return not r"),
    "C8 the filter's left side isn't checked to be the key (B6: k[:6] reads as k)":
        ("    if isinstance(cond, ast.Compare) and len(cond.ops) == 1 and _is_key(cond.left, key):",
         "    if isinstance(cond, ast.Compare) and len(cond.ops) == 1:"),
    "C9 the host's live registry counts as the env's own (on every path)":
        ('    live = isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value.startswith("/etc")',
         "    live = False"),
    "C10 `|` judges only its left side (B7: `os.environ | {REGISTRY: '/etc/…'}` reads inherit)":
        ("            if reg is not None:\n                return _own_registry(reg)\n"
         "            return env_kind(v.left, sc, depth + 1, busy)",
         "            return env_kind(v.left, sc, depth + 1, busy)"),
    "C11 a registry set anywhere in scope counts, dominating or not (B16)":
        ("                        if stmt in body and body.index(stmt) < i:", "                        if True:"),
    "C12 a pop of the registry is ignored (B1)":
        ('                elif m == "pop" and n.args and not _never_registry(n.args[0], self):',
         '                elif m == "pop" and False:'),
    "C13 a del of the registry is ignored (B2, B3)":
        ("            if isinstance(n, ast.Delete):", "            if False:"),
    "C14 npm is a plain tool again (B11: package.json scripts run repo code)":
        ('PLAIN = {"psql", ', 'PLAIN = {"npm", "psql", '),
    "C15 an unparseable file reads as no sites (they vanish)":
        ('        return [{**_finding(rel, 1, "the file doesn\'t parse, so none of its subprocess envs can be judged"),\n'
         '                 "bucket": "red"}]',
         "        return []"),
    "C16 __enter__ is trusted to return self without checking (any C().__enter__() is a C)":
        ('            and _returns_self(sc.classes.get(e.func.value.func.id, {}).get("__enter__", [])):',
         "            and True:"),
    "C17 a receiver is judged by its FIRST binding (two classes collapse to one)":
        ("    got = {_class_of(v, sc, depth + 1) for v in vals}",
         "    got = {_class_of(vals[0], sc, depth + 1)}"),
    "C18 imported classes are never read (OrgHomes.env is invisible)":
        ("            if a.name in other.classes:", "            if False:"),
    "C19 a sibling module's every builder comes in, imported or not (B14: keyed by bare name)":
        ("            if a.name in other.funcs:\n                sc.funcs.setdefault(local, []).extend(other.funcs[a.name])",
         "            for fn_, ds_ in other.funcs.items():\n                sc.funcs.setdefault(fn_, []).extend(ds_)"),
    "C20 a plain program's env isn't checked (R7–R9, R12: BASH_ENV, NODE_OPTIONS, GIT_CONFIG_* ride in)":
        ("    if env is not None and not (sc is not None and env_keys_safe(env, sc)):",
         "    if False:"),
    "C21 any key counts as safe":
        ("        return None not in v.keys and all(isinstance(k, ast.Constant) and _safe_key(k.value) for k in v.keys)",
         "        return None not in v.keys"),
    "C22 git's unknown global options pass (R10 --exec-path, R11 --config-env)":
        ("            else:\n                return False\n        sub = rest[i] if i < len(rest) else None",
         "            else:\n                i += 1\n        sub = rest[i] if i < len(rest) else None"),
    "C23 a ** spread never decides the key (R1/R2: the /etc literal inside it is missed)":
        ('            if kind in GREEN or kind.startswith("red:the host\'s live registry"):',
         "            if kind in GREEN:"),
    "C24 the FIRST writer wins, not the last (R2's control)":
        ("            state = _own_registry(val)", "            state = state or _own_registry(val)"),
    "C25 update()/setdefault() writes of the registry are never recorded (R4)":
        ("                for val in vals:\n                    self.reg_sets.setdefault(",
         "                for val in ():\n                    self.reg_sets.setdefault("),
    "C26 a live registry written to a name is ignored (R4: the dominance check alone decides)":
        ("        if live:\n            return \"red:the host's live registry, written to the name\"",
         "        if False:\n            return \"red:the host's live registry, written to the name\""),
    "C27 the PARENT's registry popped or deleted never matters (R5/R6)":
        ('        if cuts_parent and kind == "inherit":', '        if False:'),
    "C28 a loop over ANY literal tuple is trusted, the registry in it or not":
        ("                return all(isinstance(e, ast.Constant) and e.value != REGISTRY for e in lits.elts)",
         "                return True"),
    "C29 a GIT_* scrub loop is distrusted (merge_ready's shape reads red: a false positive)":
        ("                return any(_keeps(c, k) is False for c in it.generators[0].ifs)", "                return False"),
}
