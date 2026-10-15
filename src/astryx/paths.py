"""CODE vs HOME (plan-10224 S1).

CODE is where this package's code lives. HOME is the org's data root (.env, local.md, homes/, var/ ...),
resolved in this order, first hit wins:

  1. env       ASTRYX_HOME, unless this code is a DIFFERENT checkout (then the env names a foreign org: skip it)
  2. marker    a `.astryx` FILE, walking up from cwd, but never past the first directory holding `.git`
  3. checkout  CODE is a git checkout (an editable / dev install): its root
  4. default   ~/.astryx

Only the explicit marker counts (not local.md + .env): a worktree nested inside the live org's tree
(.claude/worktrees/<x>/) walked up into the LIVE org. The walk stops at a git root for the same reason: a checkout
is its own org unless it says otherwise, so a nested worktree falls through to the checkout rung (itself), never to
a home above it. `.astryx` must be a file: the default HOME is itself a directory named ~/.astryx, and a walk up
from ~ must not mistake it for a marker. In a dev checkout HOME == the checkout, so nothing changes for the org
that runs from one.

Rung 1 is not unconditional (a2 #52637, plan-10224 BC-A): the generated units and every resident shell carry the LIVE
ASTRYX_HOME, so a worktree run from such a shell would otherwise resolve to the live org, which is the leak a worktree
with the live .env linked showed on 10-14 (it ran live trigger bodies). A wheel install has no checkout, and there the
env is the only authority; a checkout honours it only when it names that checkout itself. So an operator running
`astryx <verb>` from a worktree acts on the worktree; the live org is `cd` into it.
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
    root = checkout_root(package)
    if env.get("ASTRYX_HOME"):
        h = Path(env["ASTRYX_HOME"]).expanduser().resolve()
        if root is None or root.resolve() == h:
            return h, "env"
    m = find_marker(cwd)
    if m is not None:
        return m, "marker"
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


# ── ANOTHER CHECKOUT OF THIS REPOSITORY? (seed #53453, a4 #53469) ──────────────────────────────────────────────
# It lives here, beside repo_root, because every throwaway tree an oracle builds carries paths.py (the skeleton's
# spine): a walker anywhere (sqlguard's inventory included) can ask it without a new dependency.
# Is this directory ANOTHER CHECKOUT OF THIS REPOSITORY? One answer for every walker (seed #53453, a4 #53469).
#
# A linked worktree inside the tree (Claude's .claude/worktrees/*, a resident's .worktrees/*, a wt-* at the root) is
# another branch's copy, not this tree's code. A walker that descends into it reads stale copies as subjects: sqlguard
# saw 6457 site keys instead of 465 (10-14), and the econ consumer set, the derived-copy registry and the backup census
# each went RED on every branch while one existed (seed #53453). Every walker asks THIS module, so no fourth copy drifts.
#
# The test is the git COMMON dir: a subdirectory whose .git resolves to the same common dir as the tree's source is a
# checkout of the same repository. A nested repo that ISN'T this one (agents/, the identity tree, its own repo) is NOT
# pruned: a blanket "has a .git" rule would silently drop it from every scanner (a4 #53469, constraint 1).
#
# The tree under check is not always a checkout. branch_check's side trees are `git archive` output, with NO .git, so the
# tree's own common dir is None and an undeclared walk would prune NOTHING (a4 #53469: the 85 R-NEW). Whoever builds such
# a tree DECLARES its source in ASTRYX_REPO_COMMON (branch_check does). Undeclared and no .git: the answer is UNKNOWN, and
# the walker says so; it never silently prunes nothing.

CHECKOUT_SOURCE_ENV = "ASTRYX_REPO_COMMON"


def common_dir(d) -> Path | None:
    """The git COMMON dir a checkout rooted at `d` belongs to (None if `d` isn't a checkout root). A linked worktree's
    .git is a `gitdir:` file whose admin dir names its common dir in `commondir`."""
    g = Path(d) / ".git"
    try:
        if g.is_dir():
            return g.resolve()
        if g.is_file():
            admin = Path(g.read_text().split("gitdir:", 1)[1].strip())
            admin = admin if admin.is_absolute() else (Path(d) / admin)
            cd = admin / "commondir"
            if cd.is_file():
                return (admin / cd.read_text().strip()).resolve()
            # the admin dir isn't readable here (branch_check's sandbox binds no live .git): a linked worktree's admin
            # dir is <common>/worktrees/<name> by git's own layout, so the pointer's TEXT still names its repository
            if admin.parent.name == "worktrees":
                return admin.parent.parent.resolve()
            return admin.resolve()
    except (OSError, IndexError):
        return None
    return None


class Checkouts:
    """The other checkouts of the repository `root` was made from, found while walking it.

        co = Checkouts(root)
        for dirpath, dirnames, _ in os.walk(root):
            dirnames[:] = co.prune(dirpath, dirnames)
        co.found     # the pruned ones, repo-relative, for the walker's report
        co.unknown   # True: the source can't be told (no .git, nothing declared) -- say so
    """

    def __init__(self, root, env=None):
        self.root = Path(root).resolve()
        env = os.environ if env is None else env
        own = common_dir(self.root)
        declared = env.get(CHECKOUT_SOURCE_ENV)
        self.mine = {c for c in (own, Path(declared).resolve() if declared else None) if c is not None}
        self.unknown = not self.mine
        self.found: set[str] = set()
        self.unclassified: set[str] = set()   # nested checkout roots met while UNKNOWN: walked, and named, never silent

    def is_other(self, d) -> bool:
        d = Path(d)
        if self.unknown or d.resolve() == self.root:
            return False
        return common_dir(d) in self.mine

    def prune(self, dirpath, dirnames) -> list:
        """`dirnames` without the other checkouts among them (each recorded in .found)."""
        keep = []
        for name in dirnames:
            full = Path(dirpath) / name
            if self.is_other(full):
                self.found.add(os.path.relpath(full, self.root))
            else:
                if self.unknown and (full / ".git").exists():
                    self.unclassified.add(os.path.relpath(full, self.root))
                keep.append(name)
        return keep

    def holds_only_others(self, d, depth: int = 4) -> bool:
        """True for a directory that IS another checkout, or whose every entry is one or itself holds only such, as
        `.claude/` holding only `worktrees/<checkouts>` (git lists that PARENT when everything below it is ignored)."""
        d = Path(d)
        if self.is_other(d):
            return True
        if depth <= 0:
            return False
        try:
            entries = list(d.iterdir())
        except OSError:
            return False
        return bool(entries) and all(e.is_dir() and not e.is_symlink() and self.holds_only_others(e, depth - 1)
                                     for e in entries)

    def report(self) -> str:
        if self.unknown:
            return (f"other checkouts: UNKNOWN (the tree has no .git and {CHECKOUT_SOURCE_ENV} is unset): a linked worktree inside "
                    "it would be walked as subject code")
        return f"other checkouts pruned: {sorted(self.found) or 'none'}"
