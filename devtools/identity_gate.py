#!/usr/bin/env python3
"""astryx · identity gate: which astryx does this tree's interpreter import? (plan-10224 D1, the CODE half)

A review runs a branch's tests in a worktree with the live venv's python. That is safe today: nothing
installs astryx into the venv, and a process started at the tree root imports the tree's own src/astryx
through the root astryx.py shim. The first install changes it silently. An editable install's .pth, or a
PyPI copy, puts SOME astryx on every interpreter's path, and a process that doesn't put the tree root
first (a script run from tests/, a console script) imports THAT copy, so a review passes code it never
ran. Reproduced in the plan (a1 #51497 F2); owed before any `pip install -e` (#51679 B3); found built
nowhere and armed by nothing (a2 #52637). This gate is the tripwire, so the trip needs no one to remember.

Two readings that fail differently, plus the assertion that they agree:
  outside   `$PY -I` from a scratch cwd: only what is INSTALLED (no cwd entry, no PYTHONPATH)
  inside    `$PY -c` from the tree root: what the pulse and every `-m` gate get (the root shim)
PASS when inside is this tree's src/astryx/paths.py and outside is absent (nothing installed) or that
same file. Anything else is RED and names both paths. Run from the tree root:
    venv/bin/python devtools/identity_gate.py

THE INSTALLER'S RIDER (a2 #53072, binding on whoever first runs `pip install -e` into a venv worktrees
share): as built, the only satisfiable state is "nothing installed". D1's remedy for runners (export
PYTHONPATH=<tree>/src) does NOT clear this gate, because OUTSIDE is -I and judges presence, and INSIDE runs
where the shim always wins. That fails closed on purpose, so never make it green by softening a reading.
At the trip, add the RUNNER-SHAPED reading as the decisive one:
- a probe SCRIPT under <tree>/tests/ (sys.path[0] = tests/, not the tree root);
- run in the env check.sh exports, with the PYTHONPATH=<tree>/src export added there;
- RED iff it imports anything but <tree>/src/astryx/paths.py.
OUTSIDE then becomes an informational line naming the shadow.
Arms: installed + no export -> RED; installed + export -> PASS. Mutant: judge OUTSIDE's presence alone ->
the remedied case reads RED. Without an install the alternative is a per-tree venv.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE = "import astryx.paths as p; print(p.__file__)"
ABSENT = "No module named 'astryx'"


def resolve(py: str, cwd: Path, isolated: bool, sites: tuple = (), nosite: bool = False) -> tuple[str, str]:
    """('path', file) | ('absent', '') | ('error', stderr tail). `sites`/`nosite` exist for the oracle's
    fixtures: -S drops the real site-packages and each fixture dir is added as a site (its .pth files run)."""
    prog = PROBE
    if sites:
        prog = "import site, sys\nfor d in sys.argv[1:]: site.addsitedir(d)\n" + PROBE
    argv = [py] + (["-I"] if isolated else []) + (["-S"] if nosite else []) + ["-c", prog, *map(str, sites)]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}   # inside: the shim, never an inherited path
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=60, env=env)
    if r.returncode == 0 and r.stdout.strip():
        return "path", r.stdout.strip().splitlines()[-1]
    err = (r.stderr.strip().splitlines() or [f"exit {r.returncode}"])[-1]
    if err.endswith(ABSENT) and "ModuleNotFoundError" in err:
        return "absent", ""
    return "error", err[-300:]


def verdict(tree: Path, outside: tuple[str, str], inside: tuple[str, str]) -> list[str]:
    """Every problem, empty when this tree imports only itself."""
    own = (tree / "src" / "astryx" / "paths.py").resolve()
    probs = []
    if inside[0] != "path":
        probs.append(f"from the tree root, astryx.paths does not import ({inside[0]}: {inside[1]})")
    elif Path(inside[1]).resolve() != own:
        probs.append(f"from the tree root, astryx.paths is {inside[1]}, not this tree's {own}")
    if outside[0] == "error":
        probs.append(f"the installed astryx is broken: {outside[1]}")
    elif outside[0] == "path" and Path(outside[1]).resolve() != own:
        probs.append(f"an INSTALLED astryx shadows this tree: {outside[1]} (this tree is {own}); a process "
                     f"that doesn't start at the tree root runs that copy, not the code under review")
    return probs


def check(tree: Path, py: str, sites: tuple = (), nosite: bool = False) -> tuple[list[str], tuple, tuple]:
    with tempfile.TemporaryDirectory(prefix="identity-gate-") as scratch:
        outside = resolve(py, Path(scratch), isolated=True, sites=sites, nosite=nosite)
    inside = resolve(py, tree, isolated=False, sites=sites, nosite=nosite)
    return verdict(tree, outside, inside), outside, inside


def main() -> int:
    tree = Path(sys.argv[1] if len(sys.argv) > 1 else os.getcwd()).resolve()
    probs, outside, inside = check(tree, sys.executable)
    print(f"  inside  (tree root, the shim): {inside[1] or inside[0]}")
    print(f"  outside (-I, scratch cwd):     {outside[1] if outside[0] == 'path' else outside[0]}")
    for p in probs:
        print(f"  ✗ {p}")
    if probs:
        return 1
    print(f"  ✓ {tree} imports only its own astryx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
