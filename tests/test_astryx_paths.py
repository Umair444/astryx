#!/usr/bin/env python3
"""Oracle: astryx.paths resolves HOME by its four rungs, in order (plan-10224 S1).

  1 env ASTRYX_HOME  2 a `.astryx` FILE walking up from cwd, stopping at the first git root  3 a checkout root  4 ~/.astryx

Each rung is driven through resolve_home's injectable inputs over temp trees, and each is shown to LOSE to the rung
above it. Hermetic: no database, no network.
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = os.environ.get("PATHS_SRC")       # the mutation probe hands a mutant copy of paths.py here
if SRC:
    spec = importlib.util.spec_from_file_location("paths_under_test", SRC)
    paths = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(paths)
else:
    sys.path.insert(0, str(REPO / "src"))
    from astryx import paths  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    t = Path(tempfile.mkdtemp(prefix="astryx-paths-")).resolve()
    user = t / "user"
    user.mkdir()
    # a fake checkout: <co>/src/astryx with .git and init.sh at <co>
    co = t / "co"
    pkg = co / "src" / "astryx"
    pkg.mkdir(parents=True)
    (co / ".git").write_text("gitdir: elsewhere\n")              # a worktree's .git is a FILE
    (co / "init.sh").write_text("#!/bin/sh\n")
    wheel_pkg = t / "site-packages" / "astryx"
    wheel_pkg.mkdir(parents=True)
    plain = t / "plain" / "deep" / "er"
    plain.mkdir(parents=True)

    arm("checkout_root: src/astryx under a .git + init.sh root", paths.checkout_root(pkg) == co)
    arm("checkout_root: a site-packages install is not a checkout", paths.checkout_root(wheel_pkg) is None)

    h, why = paths.resolve_home(env={}, cwd=plain, package=wheel_pkg, user_home=user)
    arm("rung 4 default: ~/.astryx", (h, why) == (user / ".astryx", "default"), f"{h} {why}")

    h, why = paths.resolve_home(env={}, cwd=plain, package=pkg, user_home=user)
    arm("rung 3 checkout beats the default", (h, why) == (co, "checkout"), f"{h} {why}")

    org = t / "plain"
    (org / ".astryx").write_text("astryx home\n")
    h, why = paths.resolve_home(env={}, cwd=plain, package=pkg, user_home=user)
    arm("rung 2 marker FILE found walking up, beats the checkout", (h, why) == (org, "marker"), f"{h} {why}")
    (org / ".astryx").unlink()

    (org / "local.md").write_text("law\n")
    (org / ".env").write_text("A=1\n")
    h, why = paths.resolve_home(env={}, cwd=plain, package=pkg, user_home=user)
    arm("local.md + .env is NOT a home (only the explicit .astryx marker counts)", (h, why) == (co, "checkout"),
        f"{h} {why}")

    # B2: a worktree nested inside the live org's tree, the org's .astryx ABOVE it
    live = t / "live"
    (live / ".git").mkdir(parents=True)
    (live / ".astryx").write_text("astryx home\n")
    wt = live / ".claude" / "worktrees" / "agent-x"
    wpkg = wt / "src" / "astryx"
    wpkg.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: ../../.git/worktrees/agent-x\n")
    (wt / "init.sh").write_text("#!/bin/sh\n")
    (wt / "nucleus").mkdir()
    for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
        (wt / _d).mkdir(parents=True, exist_ok=True)
    h, why = paths.resolve_home(env={}, cwd=wt / "nucleus", package=wpkg, user_home=user)
    arm("a nested worktree under a home's .astryx resolves to the WORKTREE (checkout rung), never the parent",
        (h, why) == (wt, "checkout"), f"{h} {why}")
    h, why = paths.resolve_home(env={}, cwd=wt, package=wheel_pkg, user_home=user)
    arm("...from a wheel install with cwd in that worktree, the walk stops at its .git (default, not the parent)",
        (h, why) == (user / ".astryx", "default"), f"{h} {why}")
    h, why = paths.resolve_home(env={}, cwd=live / ".claude", package=wheel_pkg, user_home=user)
    arm("a git root's OWN .astryx is still found (checked before the walk stops)", (h, why) == (live, "marker"),
        f"{h} {why}")
    (wt / ".astryx").write_text("astryx home\n")
    h, why = paths.resolve_home(env={}, cwd=wt / "nucleus", package=wpkg, user_home=user)
    arm("a worktree that marks ITSELF a home is found by the marker rung", (h, why) == (wt, "marker"), f"{h} {why}")

    h, why = paths.resolve_home(env={"ASTRYX_HOME": str(t / "x" / ".." / "elsewhere")}, cwd=plain, package=wheel_pkg,
                                user_home=user)
    arm("rung 1: a WHEEL install takes ASTRYX_HOME over everything (and normalises it)",
        (h, why) == (t / "elsewhere", "env"), f"{h} {why}")
    h, why = paths.resolve_home(env={"ASTRYX_HOME": str(co / "src" / "..")}, cwd=plain, package=pkg, user_home=user)
    arm("rung 1: a checkout takes ASTRYX_HOME when it names that checkout itself", (h, why) == (co, "env"),
        f"{h} {why}")
    # a2 #52637: the units and resident shells carry the LIVE home; a worktree run from one must not resolve to it
    h, why = paths.resolve_home(env={"ASTRYX_HOME": str(live)}, cwd=plain, package=pkg, user_home=user)
    arm("rung 1: a DIFFERENT checkout skips an inherited ASTRYX_HOME (a worktree in a live shell is itself, not live)",
        (h, why) == (co, "checkout"), f"{h} {why}")
    h, why = paths.resolve_home(env={"ASTRYX_HOME": str(live)}, cwd=wt / "nucleus", package=pkg, user_home=user)
    arm("  ...and falls through to the marker rung when the cwd is marked", (h, why) == (wt, "marker"), f"{h} {why}")
    h, why = paths.resolve_home(env={"ASTRYX_HOME": ""}, cwd=plain, package=pkg, user_home=user)
    arm("an EMPTY ASTRYX_HOME falls through", why == "checkout", why)

    # ~/.astryx is a DIRECTORY (the default home): walking up from ~ must not take it for a marker
    (user / ".astryx").mkdir()
    h, why = paths.resolve_home(env={}, cwd=user, package=wheel_pkg, user_home=user)
    arm("a .astryx DIRECTORY is not a marker", (h, why) == (user / ".astryx", "default"), f"{h} {why}")

    if not SRC:      # these read where the module FILE lives; a mutant copy lives in a temp dir
        arm("this checkout resolves as a checkout", paths.checkout_root() == REPO, str(paths.checkout_root()))
        h, why = paths.resolve_home(env={})
        arm("THIS checkout (a worktree nested in the live org) resolves HOME to itself, never the live org",
            h == REPO and why in ("checkout", "marker"), f"{h} {why}")
    print(f"\n{'FAIL' if fails else 'ALL PASS'}: astryx paths ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
