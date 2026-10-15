#!/usr/bin/env python3
"""Oracle: devtools/eager_annotations.py, the import-time annotations pyflakes can't see (a name bound somewhere, just
not yet). It is the blind spot of test_undefined_names' family: a lazy 3.14 annotation hiding a 3.12 import crash.

Two instruments on one question, and an arm that requires them to agree:
  STATIC   each fixture's expected verdict from the scanner (A1-A12)
  RUNTIME  each fixture run under a real pre-3.14 interpreter: flagged <=> NameError (A13). That arm is what proves the
           scanner's idea of "import-time" is Python's. It uses this interpreter on CI (3.12), else PY312, else
           `uv python find 3.12`, and is UNVERIFIED (a SKIP line) where none exists.
  LIVE     the tracked tree has no finding (A14)
Mutants: tests/mutants_eager_annotations.py.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = Path(os.environ.get("EAGER_ANN_SRC", REPO / "devtools" / "eager_annotations.py"))
_spec = importlib.util.spec_from_file_location("eager_annotations_under_test", SUBJECT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
scan_source, tracked = _mod.scan_source, _mod.tracked

# name -> (source, flagged?). Every flagged fixture is a NameError at import on 3.12; every clean one imports.
FIXTURES = {
    "A1 a parameter names a class defined later":
        ("def f(p: Later) -> None:\n    pass\n\n\nclass Later:\n    pass\n", True),
    "A2 a class names itself in its last line (bound only when the body ends)":
        ("class Node:\n    x = 1\n    def child(self) -> Node: ...\n", True),
    "A3 a class-body `x: T` names a later class":
        ("class A:\n    y: Later2\n\n\nclass Later2:\n    pass\n", True),
    "A4 a name imported only under TYPE_CHECKING, used eagerly":
        ("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from decimal import Decimal\n\n\n"
         "def f(x: Decimal) -> None:\n    pass\n", True),
    "A5 a method of one class names a LATER module class":
        ("class A:\n    def m(self, b: B) -> None:\n        pass\n\n\nclass B:\n    pass\n", True),
    "A6 a keyword-only parameter names a later class":
        ("def f(*, k: Later3) -> None:\n    pass\n\n\nclass Later3:\n    pass\n", True),
    "A7 `from __future__ import annotations` makes it lazy: clean":
        ("from __future__ import annotations\n\n\ndef f(p: Later) -> None:\n    pass\n\n\nclass Later:\n    pass\n",
         False),
    "A8 a string annotation is lazy everywhere: clean":
        ("def f(p: 'Later') -> None:\n    pass\n\n\nclass Later:\n    pass\n", False),
    "A9 bound before use: clean":
        ("class Early:\n    pass\n\n\ndef f(p: Early) -> Early:\n    return p\n", False),
    "A10 a def nested in a def is not on the import path: clean":
        ("def outer():\n    def inner(p: Later) -> None:\n        pass\n    return inner\n\n\nclass Later:\n    pass\n",
         False),
    "A11 a TYPE_CHECKING import used only in a string annotation: clean":
        ("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from decimal import Decimal\n\n\n"
         "def f(x: 'Decimal') -> None:\n    pass\n", False),
}

fails = 0


def arm(name, ok, detail=""):
    global fails
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f" :: {detail}"))
    fails += 0 if ok else 1


for name, (src, flagged) in FIXTURES.items():
    got = scan_source(src, "<fixture>")
    arm(f"{name} -> {'flagged' if flagged else 'clean'}", bool(got) == flagged, got)

got = scan_source("def f(:\n", "<broken>")
arm("A12 a file that doesn't parse is a finding, never a pass", len(got) == 1 and "does not parse" in got[0], got)


def pre314():
    if sys.version_info < (3, 14):
        return sys.executable
    if os.environ.get("PY312"):
        return os.environ["PY312"]
    if shutil.which("uv"):
        r = subprocess.run(["uv", "python", "find", "3.12"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


py = pre314()
if py is None:
    print("SKIP A13 runtime agreement: no pre-3.14 interpreter here (set PY312). The scanner's verdicts were not "
          "checked against Python's.")
else:
    disagree = []
    with tempfile.TemporaryDirectory(prefix="eager-ann-") as d:
        for i, (name, (src, flagged)) in enumerate(FIXTURES.items()):
            f = Path(d) / f"fx{i}.py"
            f.write_text(src)
            r = subprocess.run([py, "-I", str(f)], capture_output=True, text=True, timeout=30)
            name_error = r.returncode != 0 and "NameError" in r.stderr
            if r.returncode != 0 and not name_error:
                disagree.append(f"{name}: crashed otherwise ({r.stderr.strip().splitlines()[-1:]})")
            elif name_error != flagged:
                disagree.append(f"{name}: scanner says {'flagged' if flagged else 'clean'}, Python "
                                f"{'NameErrors' if name_error else 'imports it'}")
    ver = subprocess.run([py, "-c", "import sys; print(sys.version.split()[0])"], capture_output=True, text=True)
    arm(f"A13 RUNTIME agreement on {ver.stdout.strip()}: every flagged fixture NameErrors, every clean one imports",
        not disagree, disagree)

live = [hit for f in tracked(REPO) for hit in scan_source(f.read_bytes(), str(f.relative_to(REPO)))]
arm(f"A14 LIVE: no import-time annotation in the tracked tree names an unbound name", not live, live[:10])

if fails:
    print(f"FAILED: eager annotations ({fails} failing)")
    sys.exit(1)
print("ALL PASS: eager annotations (0 failing)")
