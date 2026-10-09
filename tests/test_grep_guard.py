#!/usr/bin/env python3
"""Oracle for nucleus/grep_guard.py: a recursive plain grep rooted ABOVE a .gitignore is denied; everything that
runs the real binary, or that searches a subdirectory, is allowed. Hermetic: it builds its own tree in a tmpdir
(a .gitignore at the top, an ignored dir, a tracked dir), never reads the estate.

GRADE of what it proves: the guard's DECISION on command shapes. That plain grep is the function and the others
are the real binary is measured in the guard's docstring, not re-measured here (a shell function is the
harness's, not this tree's).
Exit 0 pass · 1 fail.
"""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
SRC = os.environ.get("GREP_GUARD_SRC")
if SRC:                                                 # mutation_probe hands a mutant copy here
    import importlib.util
    _s = importlib.util.spec_from_file_location("grep_guard_under_test", SRC)
    G = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(G)
else:
    from nucleus import grep_guard as G

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


with tempfile.TemporaryDirectory() as td:
    top = Path(td) / "parent"
    root = top / "repo"
    (root / "memory").mkdir(parents=True)
    (root / "nucleus").mkdir()
    (root / ".gitignore").write_text("memory/\n")
    R, P, cwd_sub = str(root), str(top), str(root / "nucleus")

    deny = {
        "recursive from the repo root (path)": (f"grep -rl kg {R}", "/"),
        "recursive from '.' with cwd = the repo root": ("grep -rn kg .", R),
        "no path at all (ugrep searches '.')": ("grep -rl kg", R),
        "cd ROOT && grep -r (cwd tracked through the command)": (f"cd {R} && grep -rIl 'kg\\.claim' .", "/"),
        "-R and --recursive spellings": (f"grep -R kg {R}; grep --recursive kg {R}", "/"),
        "a combined flag cluster (-nrI)": (f"grep -nrI kg {R}", "/"),
        "an env assignment before grep": (f"LC_ALL=C grep -rl kg {R}", "/"),
        "inside a pipeline": (f"echo x | grep -rl kg {R} | head", "/"),
        "-e names the pattern, so the first operand is a ROOT": (f"grep -r -e kg {R}", "/"),
        "a parent of the repo (a .gitignore one level down)": (f"grep -rl kg {P}", "/"),
        "\\grep still runs the FUNCTION (a backslash stops aliases, not functions)": (f"\\grep -rl kg {R}", "/"),
        "after `;` and a newline": (f"true;\ngrep -rl kg {R}", "/"),
    }
    for name, (cmd, cwd) in deny.items():
        r = G.decide(cmd, cwd)
        check(f"DENY  {name}", bool(r) and "command grep" in r and "estate_grep.sh" in r, repr(r))

    allow = {
        "command grep -r (the real binary)": (f"command grep -rl kg {R}", "/"),
        "/usr/bin/grep -r": (f"/usr/bin/grep -rl kg {R}", "/"),
        "timeout … grep -r (timeout execs the binary)": (f"timeout 60 grep -rl kg {R}", "/"),
        "xargs grep (the binary)": (f"ls | xargs grep -l kg", R),
        "non-recursive grep of a file at the root": (f"grep -n kg {R}/x.txt", "/"),
        "non-recursive grep naming the BLIND root dir itself (only -r makes it blind)": (f"grep -n kg {R}", "/"),
        "recursive, rooted in a subdirectory (not blind: measured)": (f"grep -rl kg {cwd_sub}", "/"),
        "recursive from '.' inside a subdirectory": ("grep -rl kg .", cwd_sub),
        "recursive INTO the ignored dir itself (not blind: measured)": (f"grep -rl kg {R}/memory", "/"),
        "the word grep as an argument, not a command": (f"echo grep -r {R}", "/"),
        "a pattern that looks like a flag after -e": (f"grep -e -r kg {cwd_sub}/x", "/"),
        "unparseable quoting → ALLOW (polarity)": ("grep -rl 'unterminated", R),
        "a root that doesn't exist → ALLOW": ("grep -rl kg /nonexistent/path", "/"),
        "empty command": ("", R),
    }
    for name, (cmd, cwd) in allow.items():
        r = G.decide(cmd, cwd)
        check(f"ALLOW {name}", r is None, repr(r))

    # the --exclude-dir=… form never makes it safe: ugrep still reads the .gitignore
    r = G.decide(f"grep -rl --exclude-dir=node_modules kg {R}", "/")
    check("DENY  --exclude-dir doesn't change the .gitignore blindness", bool(r), repr(r))

# the hook wiring: step.py's wrapper turns an exception into ALLOW plus a named error
sys.path.insert(0, str(REPO / "hooks"))
import importlib.util  # noqa: E402
_h = importlib.util.spec_from_file_location("step_under_test", REPO / "hooks" / "step.py")
step = importlib.util.module_from_spec(_h)
_h.loader.exec_module(step)
real = G.decide


def boom(*a, **k):
    raise RuntimeError("injected")


import nucleus.grep_guard as live  # noqa: E402
orig = live.decide
live.decide = boom
try:
    d, err = step.grep_guard("grep -rl x /", "/")
    check("HOOK an exception inside decide → ALLOW with a named error", d is None and err and "unevaluable" in err,
          repr((d, err)))
finally:
    live.decide = orig

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
