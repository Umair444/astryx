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
        ('                elif m == "pop" and n.args and not (isinstance(n.args[0], ast.Constant) '
         'and n.args[0].value != REGISTRY):',
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
}
