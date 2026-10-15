"""Mutants for devtools/eager_annotations.py (oracle: tests/test_eager_annotations.py). Hermetic.

    venv/bin/python devtools/mutation_probe.py tests/mutants_eager_annotations.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "devtools" / "eager_annotations.py"
ORACLE = REPO / "tests" / "test_eager_annotations.py"
ENV = "EAGER_ANN_SRC"
MUTANTS = {
    "E1 a def/class name counts as bound from its FIRST line (a class naming itself escapes)":
        ("        return [(n.name, n.end_lineno)]", "        return [(n.name, n.lineno)]"),
    "E2 bound-on-the-same-line reads as in time (the self-reference on a class's last line escapes)":
        ("if any(x.id in rt and rt[x.id] < x.lineno for rt, _ in scopes):",
         "if any(x.id in rt and rt[x.id] <= x.lineno for rt, _ in scopes):"),
    "E3 TYPE_CHECKING is not recognised (a never-run import counts as a binding... nowhere)":
        ("        return True\n    return None", "        return None\n    return None"),
    "E4 class bodies are not walked (methods and `x: T` in a class escape)":
        ("            _annotations(n.body, [_table(n.body), scopes[-1]], out)", "            pass"),
    "E5 the __future__ import is ignored (every lazy file is accused)":
        ('if isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names):',
         "if False:"),
    "E6 keyword-only parameters are not read":
        ("for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:",
         "for arg in a.posonlyargs + a.args + [x for x in (a.vararg, a.kwarg) if x]:"),
    "E7 an unparseable file reads as clean":
        ('        return [f"{label}:{e.lineno}: does not parse ({e.msg})"]', "        return []"),
    "E8 the walk is a hand list again: only `body` fields are descended (else/case bodies escape)":
        ("            if not isinstance(value, list):\n                continue\n            branch",
         "            if field != \"body\" or not isinstance(value, list):\n                continue\n            branch"),
    "E9 a compound statement's header binds nothing (for/with/match targets read as bound nowhere)":
        ("        return found                                               # bound when the header runs",
         "        return []"),
    "E10 the class scope is skipped (a late class attribute reads as bound nowhere)":
        ("            _annotations(n.body, [_table(n.body), scopes[-1]], out)",
         "            _annotations(n.body, [scopes[-1]], out)"),
    "E11 `if not TYPE_CHECKING:` is not inverted (its never-run else reads as live)":
        ("        return None if inner is None else not inner", "        return None"),
    "E12 a comprehension's target counts as a module binding (hides a later class)":
        ('        if isinstance(node, ast.comprehension) and field == "target":\n            continue',
         '        if False:\n            continue'),
    "E13 a compound statement binds when it ENDS (a for target used in its own body is accused)":
        ("    if _compound(n):\n        return found", "    if False:\n        return found"),
}
