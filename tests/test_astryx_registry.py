#!/usr/bin/env python3
"""Oracle: `import astryx` yields ONE module and ONE `_registry` on every import path (plan-10224 S1).

The pulse imports astryx every minute (src/astryx/pulse/pulse.py discover: `python -c "import astryx; runpy.run_path(<file>);
... astryx._registry"` with cwd = the org root), and a trigger file does `from astryx import trigger`. If the root
shim and the src/astryx package ever became two module objects, a decorator would append to one registry while the
pulse read the other, and every trigger would silently vanish. Each arm runs a fresh interpreter. Hermetic.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def py(prog, cwd, extra_path=(), flags=()):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "ASTRYX_HOME")}
    pre = "".join(f"import sys; sys.path.insert(0, {str(p)!r})\n" for p in reversed(extra_path))
    return subprocess.run([sys.executable, *flags, "-c", pre + prog], cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=60)


TRIG = 'from astryx import trigger\n\n\n@trigger("*/5 * * * *", note="t")\ndef zz_one(ctx):\n    return None\n'
PROBE = """
import json, runpy, sys
import astryx
runpy.run_path({f!r})
from astryx import _registry as r2, trigger as t2
import astryx.paths, astryx.config
m = sys.modules["astryx"]
print(json.dumps({{
  "file": astryx.__file__, "names": [t["name"] for t in astryx._registry],
  "same": r2 is astryx._registry and m is astryx and t2 is astryx.trigger,
  "paths": astryx.paths.__file__, "cfg_paths": astryx.config.paths is astryx.paths}}))
"""


def main():
    import json
    td = Path(tempfile.mkdtemp(prefix="astryx-reg-"))
    f = td / "t.py"
    f.write_text(TRIG)

    src = (REPO / "src" / "astryx" / "pulse" / "pulse.py").read_text()
    m = re.search(r'prog = \((.*?)\)\n', src, re.S)
    arm("pulse.discover still imports astryx and reads astryx._registry",
        bool(m) and "import astryx;" in m.group(1) and "astryx._registry" in m.group(1))
    # 1. the pulse's own path: cwd = org root, so the ROOT SHIM wins.
    prog = ("import json, sys, runpy; import astryx; "
            f"runpy.run_path({str(f)!r}); "
            "print(json.dumps([{k: t[k] for k in ('name','schedule','note')} "
            "for t in astryx._registry]))")
    r = py(prog, REPO)
    arm("pulse discover prog, cwd=root (shim): the trigger is registered",
        r.returncode == 0 and json.loads(r.stdout or "[]") == [{"name": "zz_one", "schedule": "*/5 * * * *",
                                                                "note": "t"}], r.stderr[-300:] or r.stdout)
    # 2. shim only
    r = py(PROBE.format(f=str(f)), REPO)
    d = json.loads(r.stdout) if r.returncode == 0 else {}
    arm("shim path: one module, one registry, submodules from src/astryx",
        d.get("file", "").endswith("astryx.py") and d.get("names") == ["zz_one"] and d.get("same")
        and d.get("paths", "").startswith(str(SRC / "astryx")) and d.get("cfg_paths"), r.stderr[-300:] or str(d))
    # 3. package only (what a pip install sees): cwd elsewhere, src on the path
    r = py(PROBE.format(f=str(f)), td, [SRC])
    d = json.loads(r.stdout) if r.returncode == 0 else {}
    arm("package path: one module, one registry",
        d.get("file", "") == str(SRC / "astryx" / "__init__.py") and d.get("names") == ["zz_one"] and d.get("same"),
        r.stderr[-300:] or str(d))
    # 4/5. BOTH on the path, either order: still one module and one registry
    for order, paths_ in (("shim first", [REPO, SRC]), ("package first", [SRC, REPO])):
        r = py(PROBE.format(f=str(f)), td, paths_)
        d = json.loads(r.stdout) if r.returncode == 0 else {}
        arm(f"both importable, {order}: one module, one registry", d.get("names") == ["zz_one"] and d.get("same"),
            r.stderr[-300:] or str(d))
    # 6. pulse_run's path: sys.path.insert(0, REPO) then runpy the file; the decorator lands in sys.modules' registry
    r = py(f"import runpy, sys; mod = runpy.run_path({str(f)!r}); import astryx; "
           "print(len(astryx._registry), mod['zz_one'] is astryx._registry[0]['fn'])", td, [REPO])
    arm("pulse_run path: the decorated fn is the registry's fn", r.stdout.strip() == "1 True", r.stderr[-300:])
    # 7. a tree holding ONLY the shim: mid-checkout (shim written, src/astryx/ not yet), or an old test fixture.
    #    The pulse's path must not need src/: triggers still register; only the submodules are unavailable.
    lone = td / "lone"
    lone.mkdir()
    shutil.copy(REPO / "astryx.py", lone / "astryx.py")
    r = py(prog, lone, flags=["-S"])                               # -S: no site-packages (an installed astryx)
    arm("shim with NO src/ anywhere: the pulse's discover prog still registers the trigger (B1)",
        r.returncode == 0 and [t["name"] for t in json.loads(r.stdout or "[]")] == ["zz_one"], r.stderr[-300:])
    r = py("import astryx.paths", lone, [lone], flags=["-S"])
    arm("...and only the submodules are missing (a plain ModuleNotFoundError)",
        r.returncode != 0 and "ModuleNotFoundError" in r.stderr, r.stderr[-300:])
    # 8. `python -m astryx` from the org root runs the CLI through the shim
    r = subprocess.run([sys.executable, "-m", "astryx", "version"], cwd=REPO, capture_output=True, text=True,
                       timeout=60)
    arm("`python -m astryx version` at the root runs the CLI", r.returncode == 0 and r.stdout.startswith("astryx "),
        r.stderr[-300:])
    # 9. the shim's copy of `_registry` and `trigger` is the package's, node for node (so they can't drift)
    import ast

    def defs(path):
        t = ast.parse(path.read_text())
        return {ast.unparse(n) for n in t.body
                if (isinstance(n, ast.FunctionDef) and n.name == "trigger")
                or (isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "_registry")}
    a_, b_ = defs(REPO / "astryx.py"), defs(SRC / "astryx" / "__init__.py")
    arm("the shim's _registry and trigger are identical to src/astryx/__init__.py's", len(a_) == 2 and a_ == b_,
        str(a_ ^ b_))
    shim = re.sub(r'""".*?"""', "", (REPO / "astryx.py").read_text(), flags=re.S)
    arm("the shim runs no exec/eval/compile/runpy/importlib (trigger_names reads it statically)",
        not re.search(r"\b(exec|eval|compile|runpy|importlib|__import__)\b", shim))
    shutil.rmtree(td, ignore_errors=True)
    print(f"\n{'FAIL' if fails else 'ALL PASS'}: astryx registry ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
