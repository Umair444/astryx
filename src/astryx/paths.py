"""CODE vs HOME (plan-10224 S1).

CODE is where this package's code lives. HOME is the org's data root (.env, local.md, homes/, var/ ...),
resolved in this order, first hit wins:

  1. env       ASTRYX_HOME
  2. marker    a `.astryx` FILE, walking up from cwd, but never past the first directory holding `.git`
  3. checkout  CODE is a git checkout (an editable / dev install): its root
  4. default   ~/.astryx

Only the explicit marker counts (not local.md + .env): a worktree nested inside the live org's tree
(.claude/worktrees/<x>/) walked up into the LIVE org. The walk stops at a git root for the same reason: a checkout
is its own org unless it says otherwise, so a nested worktree falls through to the checkout rung (itself), never to
a home above it. `.astryx` must be a file: the default HOME is itself a directory named ~/.astryx, and a walk up
from ~ must not mistake it for a marker. In a dev checkout HOME == the checkout, so nothing changes for the org
that runs from one.
"""
from __future__ import annotations

import os
from pathlib import Path

MARKER = ".astryx"
PACKAGE = Path(__file__).resolve().parent              # .../src/astryx, or site-packages/astryx


def checkout_root(package: Path = PACKAGE) -> Path | None:
    """The git checkout this package was loaded from (src/astryx -> <root>), or None for a wheel install.
    A worktree's .git is a FILE, so existence, not is_dir()."""
    root = package.parent.parent
    if package.parent.name == "src" and (root / ".git").exists() and (root / "init.sh").is_file():
        return root
    return None


def is_home(d: Path) -> bool:
    return (d / MARKER).is_file()


def find_marker(start: Path | None = None) -> Path | None:
    """The nearest directory with a `.astryx` file, walking up from `start`; the walk ends at the first git root
    (`.git` file or dir), checked after that directory's own marker."""
    d = Path(start or Path.cwd()).resolve()
    for p in (d, *d.parents):
        if is_home(p):
            return p
        if (p / ".git").exists():
            return None
    return None


def resolve_home(env: dict | None = None, cwd: Path | None = None, package: Path = PACKAGE,
                 user_home: Path | None = None) -> tuple[Path, str]:
    """(HOME, which rung found it). Every input is injectable so each rung is testable."""
    env = os.environ if env is None else env
    if env.get("ASTRYX_HOME"):
        return Path(env["ASTRYX_HOME"]).expanduser().resolve(), "env"
    m = find_marker(cwd)
    if m is not None:
        return m, "marker"
    root = checkout_root(package)
    if root is not None:
        return root, "checkout"
    return (Path(user_home) if user_home else Path.home()) / ".astryx", "default"


def home() -> Path:
    return resolve_home()[0]


def code() -> Path:
    """The package directory."""
    return PACKAGE
