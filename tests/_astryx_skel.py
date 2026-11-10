"""Fake-tree helper for oracles that build a throwaway repo (goal 10224 S4): lay down what `import astryx.<sub>.<mod>`
needs there, the root shim plus the package's spine, and copy the named modules at their real paths.

    from _astryx_skel import skeleton
    skeleton(tmp, "src/astryx/pulse/pulse_run.py", "src/astryx/sql/schema.sql")

Every listed file is copied with its parent packages' __init__.py; the spine (astryx.py, src/astryx/__init__.py,
_version, paths, config, _reorg) always comes along. Paths are repo-relative; a directory copies whole.
"""
import os
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPINE = ("astryx.py", "src/astryx/__init__.py", "src/astryx/_version.py", "src/astryx/paths.py",
         "src/astryx/config.py", "src/astryx/_reorg.py", "src/astryx/orgs.py")   # orgs: paths/config ask it (S3a)


def _copy(rel: str, dst: Path, repo: Path):
    src, out = repo / rel, dst / rel
    if not src.exists():
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, out, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    else:
        shutil.copy2(src, out)


def mirror(dst: Path, copy: tuple = (), skip: tuple = (), repo: Path = REPO) -> Path:
    """A temp repo that runs THIS checkout's code from its own root: every src/astryx file and devtools/scripts entry
    SYMLINKED, the nucleus/ stubs COPIED (a stub finds its root from its own real path, so a symlinked stub would
    lead back to the real checkout). `copy`: repo-relative files to copy instead of link (a subject a copy of which
    must judge the temp tree). `skip`: files left out (the oracle writes its own subject there)."""
    dst = Path(dst)
    shutil.copy2(repo / "astryx.py", dst / "astryx.py")
    for top in ("src/astryx", "devtools", "scripts", "nucleus"):
        base = repo / top
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            rel = str(p.relative_to(repo))
            if "__pycache__" in p.parts or rel in skip or p.is_dir():
                continue
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists() or out.is_symlink():
                continue
            if p.is_symlink():                               # a data stub: keep it relative, as in the repo
                out.symlink_to(os.readlink(p))
            elif top == "nucleus" or rel in copy:
                shutil.copy2(p, out)
            else:
                out.symlink_to(p)
    return dst


def skeleton(dst: Path, *rels: str, repo: Path = REPO) -> Path:
    dst = Path(dst)
    for rel in SPINE + rels:
        _copy(rel, dst, repo)
        parts = rel.split("/")
        for k in range(2, len(parts)):                 # every enclosing package under src/astryx
            init = "/".join(parts[:k]) + "/__init__.py"
            if init.startswith("src/astryx/") or init.startswith("devtools/"):
                _copy(init, dst, repo)
    return dst
