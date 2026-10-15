#!/usr/bin/env python3
"""review_live — run a BRANCH's code (an extract or worktree) against the LIVE tree, to measure live state.

    venv/bin/python devtools/review_live.py <extract> [--] <script.py | -m module> [args...]

WHY. Every module computes REPO as astryx.paths.repo_root(__file__): the FILE's own tree. A reviewer runs branch code
from a git-archive extract, so a census of live state measures the scratchpad copy and reads 0 (seed on plan-9139 S1d,
10-15: all 17 agents read UnknownLabel; a3 on S1e, 10-15: the transcript residual read 0 files where live had 82).

HOW. A child interpreter imports the EXTRACT's astryx.paths before anything else and rebinds repo_root: a root that IS
the extract answers the live repo, every other root (an oracle's fixture tree) is returned unchanged. Every module
imported after that binds the patched helper, so its REPO is live while its code is the branch's. cwd is the live repo.

THE CHILD'S ENV. ASTRYX_AGENT is removed, so nothing the measured code runs posts as a turn or a step under the
reviewer's name. PGOPTIONS gains `-c default_transaction_read_only=on`.
READ ONLY IS A GUARD AGAINST ACCIDENTS, NOT A BOUNDARY: any `SET default_transaction_read_only = off` (or a
`BEGIN READ WRITE`) in the measured code lifts it, and files are not guarded at all. This tool is for MEASUREMENT only;
never use it to apply a branch.
"""
import os
import runpy
import subprocess
import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parents[1]
READ_ONLY = "-c default_transaction_read_only=on"


def child_env(env=None) -> dict:
    """The measured child's environment: no agent identity, postgres sessions read-only by default."""
    e = dict(os.environ if env is None else env)
    e.pop("ASTRYX_AGENT", None)
    e["PGOPTIONS"] = f"{e.get('PGOPTIONS', '')} {READ_ONLY}".strip()
    return e


def boot(extract: Path, live: Path, rest: list) -> None:
    """In the child: patch repo_root FIRST, then run the target."""
    sys.path[:0] = [str(extract / "src"), str(extract)]
    import astryx.paths as P
    if not Path(P.__file__).resolve().is_relative_to(extract):
        raise SystemExit(f"review_live: astryx resolved outside the extract ({P.__file__})")
    orig = P.repo_root

    def repo_root(file=None, package=P.PACKAGE):
        r = orig(file, package)
        return live if Path(r).resolve() == extract else r

    P.repo_root = repo_root
    if rest[:1] == ["-m"]:
        sys.argv = rest[1:]
        runpy.run_module(rest[1], run_name="__main__", alter_sys=True)
    else:
        sys.argv = rest
        runpy.run_path(rest[0], run_name="__main__")


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if a[:1] == ["--boot"]:
        boot(Path(a[1]).resolve(), Path(a[2]).resolve(), a[3:])
        return 0
    if len(a) < 2 or a[0] in ("-h", "--help"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    extract = Path(a[0]).resolve()
    rest = a[2:] if a[1] == "--" else a[1:]
    if not (extract / "src" / "astryx").is_dir():
        print(f"review_live: {extract} has no src/astryx: not an astryx tree", file=sys.stderr)
        return 2
    if extract == LIVE:
        print("review_live: the extract IS the live repo; run the command directly", file=sys.stderr)
        return 2
    print(f"· review_live: code from {extract}, REPO → {LIVE}, postgres default READ ONLY (a guard, not a boundary)",
          file=sys.stderr)
    return subprocess.call([sys.executable, "-I", str(Path(__file__).resolve()), "--boot", str(extract), str(LIVE),
                            *rest], cwd=LIVE, env=child_env())


if __name__ == "__main__":
    raise SystemExit(main())
