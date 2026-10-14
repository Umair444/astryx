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


def repo_root(file: str | Path | None = None, package: Path = PACKAGE) -> Path:
    """The root of the tree a module lives in. Every moved module computes its REPO as `repo_root(__file__)` through
    this ONE helper (goal 10224 S4), never `Path(__file__).parents[n]`, so a move between subpackages can't silently
    re-point it. The root is the nearest ancestor of `file` holding src/astryx/ or the astryx.py shim: it is the
    FILE's tree, never the importing process's, so a module loaded by path from a throwaway tree (an oracle's fake
    repo) judges that tree, exactly as parents[n] did. No .git is required: a `git archive` tree (sqlguard rekey) and
    a HOME that `astryx init` materialized have the same shape. Without `file`: this package's own tree; a wheel
    install has none, and its root is HOME."""
    if file is not None:
        for a in Path(file).resolve().parents:
            if (a / "src" / "astryx").is_dir() or (a / "astryx.py").is_file():
                return a
    if package.parent.name == "src":
        return package.parent.parent
    return home()


def module_relpath(dotted: str, package: bool = False) -> str:
    """The repo-relative file a dotted module name lives in: `astryx.x.y` -> src/astryx/x/y.py, a name the S4 reorg
    moved (`nucleus.x`) -> where it moved, anything else 1:1 (`devtools.x` -> devtools/x.py). package=True names
    the package's __init__.py. The one answer for every scanner that turns an import or `-m` into a file."""
    try:
        from astryx._reorg import legacy_module
        dotted = legacy_module(dotted) or dotted
    except ImportError:
        pass
    rel = dotted.replace(".", "/") + ("/__init__.py" if package else ".py")
    return "src/" + rel if dotted == "astryx" or dotted.startswith("astryx.") else rel


def module_name(relpath: str) -> str:
    """The inverse: src/astryx/x/y.py -> astryx.x.y, a/b/__init__.py -> a.b, devtools/x.py -> devtools.x."""
    p = relpath[len("src/"):] if relpath.startswith("src/astryx/") else relpath
    p = p[:-len("/__init__.py")] if p.endswith("/__init__.py") else p[:-3] if p.endswith(".py") else p
    return p.replace("/", ".")


DATA = PACKAGE / "data"         # registries and manifests read by path (copies.json, deps.conf, ...)
SQL = PACKAGE / "sql"            # the declared schemas
