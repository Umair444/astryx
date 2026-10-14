"""The org's runtime tree: where init.sh and its scripts live, and how a wheel install gets one.

init.sh works in its own directory (it cd's there), so the org runs where its tree is:
  - a dev checkout whose HOME is the checkout: the checkout IS the tree, nothing is copied;
  - otherwise HOME gets a copy of the tree: from the wheel's package data (astryx/_data/tree), or, in a
    dev checkout pointed at another HOME, from the checkout's git-tracked files. Both are filtered by the
    one allowlist in astryx/_data/manifest.py. Copying overwrites CODE files only; nothing in the tree is
    org data (.env, local.md, homes/ ... are never in it), so an upgrade can't clobber the org.
"""
from __future__ import annotations

import os
import subprocess
from importlib import resources
from pathlib import Path

from astryx import paths
from astryx._data import manifest


def packaged_tree() -> Path | None:
    try:
        t = resources.files("astryx._data") / "tree"
    except (ModuleNotFoundError, TypeError):
        return None
    p = Path(str(t))
    return p if (p / "init.sh").is_file() else None


def org_root(home: Path) -> Path | None:
    """The directory init.sh runs in for this HOME, if one exists yet."""
    return home if (home / "init.sh").is_file() else None


def source_files() -> tuple[str, list[tuple[str, Path]]]:
    """(where from, [(relpath, abs source)]) for the tree a HOME should hold."""
    pk = packaged_tree()
    if pk is not None:
        files = [(str(p.relative_to(pk)), p) for p in sorted(pk.rglob("*")) if p.is_file()]
        # the root shim (astryx.py) needs src/astryx beside it: the wheel ships it once, as the package itself
        pkg = paths.PACKAGE
        files += [(f"src/astryx/{p.relative_to(pkg)}", p) for p in sorted(pkg.rglob("*"))
                  if p.is_file() and pk not in p.parents]
        return "wheel", [(r, p) for r, p in files if manifest.wanted(r)]
    root = paths.checkout_root()
    if root is not None:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
        rels = [r for r in out.decode().split("\0") if r and manifest.wanted(r)]
        return "checkout", [(r, root / r) for r in rels if (root / r).is_file() and not (root / r).is_symlink()]
    return "none", []


def _executable(p: Path) -> bool:
    if p.suffix == ".sh":
        return True
    try:
        with open(p, "rb") as f:
            return f.read(2) == b"#!"
    except OSError:
        return False


def materialize(home: Path) -> dict:
    """Copy the tree into HOME. Returns counts; never touches a file outside the tree's list."""
    where, files = source_files()
    if not files:
        raise RuntimeError("no runtime tree to install from (not a built wheel, not a git checkout)")
    home.mkdir(parents=True, exist_ok=True)
    n = {"source": where, "new": 0, "updated": 0, "same": 0}
    for rel, src in files:
        dst = home / rel
        data = src.read_bytes()
        if dst.is_file() and not dst.is_symlink():
            if dst.read_bytes() == data:
                n["same"] += 1
                continue
            n["updated"] += 1
        else:
            n["new"] += 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".astryx-new")
        tmp.write_bytes(data)
        os.chmod(tmp, 0o755 if _executable(src) else 0o644)
        os.replace(tmp, dst)
    link = home / "astryx"                                      # the repo's relative dispatcher link
    if not link.exists() and not link.is_symlink():
        os.symlink("init.sh", link)
    return n


def write_marker(home: Path, version: str) -> None:
    (home / paths.MARKER).write_text(f"astryx home\nversion={version}\n")


