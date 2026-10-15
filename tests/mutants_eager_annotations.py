"""Mutants for devtools/eager_annotations.py (oracle: tests/test_eager_annotations.py). Hermetic.

    venv/bin/python devtools/mutation_probe.py tests/mutants_eager_annotations.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "devtools" / "eager_annotations.py"
ORACLE = REPO / "tests" / "test_eager_annotations.py"
ENV = "EAGER_ANN_SRC"
MUTANTS = {
    "E1 a name counts as bound from its statement's FIRST line (a class naming itself escapes)":
        ("(check_only if in_check else runtime).setdefault(nm, n.end_lineno)",
         "(check_only if in_check else runtime).setdefault(nm, n.lineno)"),
    "E2 bound-at-the-same-line reads as in time (the self-reference on a class's last line escapes)":
        ("if bound is not None and bound >= x.lineno:", "if bound is not None and bound > x.lineno:"),
    "E3 a TYPE_CHECKING import counts as a runtime binding":
        ("_bindings(n.body, runtime, check_only, in_check or _is_check_only(n.test))",
         "_bindings(n.body, runtime, check_only, in_check)"),
    "E4 class bodies are not walked (methods and `x: T` in a class escape)":
        ("        elif isinstance(n, ast.ClassDef):\n            _eager(n.body, out)\n",
         "        elif isinstance(n, ast.ClassDef):\n            pass\n"),
    "E5 the __future__ import is ignored (every lazy file is accused)":
        ('if isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names):',
         "if False:"),
    "E6 keyword-only parameters are not read":
        ("for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:",
         "for arg in a.posonlyargs + a.args + [x for x in (a.vararg, a.kwarg) if x]:"),
    "E7 an unparseable file reads as clean":
        ('        return [f"{label}:{e.lineno}: does not parse ({e.msg})"]', "        return []"),
}
