#!/usr/bin/env python3
"""review_live — run a BRANCH's code (an extract or worktree) against the LIVE tree, to measure live state.

    venv/bin/python devtools/review_live.py <extract> [--] <script.py | -m module> [args...]

WHY. Every module under src/astryx computes REPO as astryx.paths.repo_root(__file__): the FILE's own tree. A reviewer runs branch code
from a git-archive extract, so a census of live state measures the scratchpad copy and reads 0 (seed on plan-9139 S1d,
10-15: all 17 agents read UnknownLabel; a3 on S1e, 10-15: the transcript residual read 0 files where live had 82).

HOW. A child interpreter imports the EXTRACT's astryx.paths before anything else and rebinds repo_root: a root that IS
the extract answers the live repo, every other root (an oracle's fixture tree) is returned unchanged. Every module
imported after that binds the patched helper, so its REPO is live while its code is the branch's. cwd is the live repo.
"Live" is the tree THIS file sits in; run from a worktree's copy, that worktree is "live" (a warning is printed when
it holds no triggers/, the live host's mark).

THE CHILD'S ENV. ASTRYX_AGENT is removed, so nothing the measured code runs posts as a turn or a step under the
reviewer's name. Postgres sessions default to read-only two ways, because one driver ignores the other (a4 #56228):
  PGOPTIONS gains `-c default_transaction_read_only=on`   libpq (psycopg) and any DSN built from PG* parts
  ASTRYX_DSN gains options='-c default_transaction_read_only=on'   asyncpg, which ignores PGOPTIONS; it is taken from
      the environment or the live .env, and a DSN that already carries options= is refused rather than merged.
READ ONLY IS A GUARD AGAINST ACCIDENTS, NOT A BOUNDARY: any `SET default_transaction_read_only = off` (or a
`BEGIN READ WRITE`) in the measured code lifts it, and files are not guarded at all. This tool is for MEASUREMENT only;
never use it to apply a branch.

NOT COVERED (declared, a4 #56228): a python SUBPROCESS the measured code spawns is a fresh interpreter without the
patch, so its REPO is the extract again; code that reads the DSN from .env while ignoring ASTRYX_DSN in the env gets
only the PGOPTIONS guard (asyncpg there: none); modules outside src/astryx that compute REPO from Path(__file__)
(observatory/api/room.py, devtools/eager_annotations.py, devtools/gate_census.py on 4050129) stay extract-bound.
"""
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

LIVE = Path(__file__).resolve().parents[1]
READ_ONLY = "-c default_transaction_read_only=on"


class Refused(Exception):
    pass


def read_only_dsn(dsn: str) -> str:
    """`dsn` with the read-only session option in it, URI or key=value. A DSN that already sets options= is refused:
    merging another tool's options is a guess, and a guess here is a write to prod."""
    if re.match(r"postgres(ql)?://", dsn):
        u = urlsplit(dsn)
        q = parse_qsl(u.query, keep_blank_values=True)
        if any(k == "options" for k, _ in q):
            raise Refused("the DSN already carries options=; set read-only by hand")
        return urlunsplit(u._replace(query=urlencode(q + [("options", READ_ONLY)], quote_via=quote)))
    if re.search(r"(^|\s)options\s*=", dsn):
        raise Refused("the DSN already carries options=; set read-only by hand")
    return f"{dsn} options='{READ_ONLY}'"


def _live_dsn(env: dict, live: Path):
    """env's ASTRYX_DSN, else the live tree's .env line, through the ONE resolver (plan-11324 S3a); None if neither."""
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))        # this tree's src/, in THIS (parent) process only; the child boots its own
    from astryx import config
    try:
        return config.dsn(live / ".env", environ=env)
    except (LookupError, OSError):
        return None


_SRC = Path(__file__).resolve().parents[1] / "src"


def child_env(env=None, live: Path = LIVE) -> dict:
    """The measured child's environment: no agent identity, postgres sessions read-only by default (both drivers)."""
    e = dict(os.environ if env is None else env)
    e.pop("ASTRYX_AGENT", None)
    e["PGOPTIONS"] = f"{e.get('PGOPTIONS', '')} {READ_ONLY}".strip()
    dsn = _live_dsn(e, live)
    if dsn:
        e["ASTRYX_DSN"] = read_only_dsn(dsn)
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
    if not (LIVE / "triggers").is_dir():   # org-home: LIVE is the live repo by name (the review's subject)
        print(f"review_live: WARNING {LIVE} holds no triggers/: it is not the live host's tree", file=sys.stderr)
    try:
        env = child_env()
    except Refused as e:
        print(f"review_live: {e}", file=sys.stderr)
        return 2
    print(f"· review_live: code from {extract}, REPO → {LIVE}, postgres default READ ONLY (a guard, not a boundary)",
          file=sys.stderr)
    return subprocess.call([sys.executable, "-I", str(Path(__file__).resolve()), "--boot", str(extract), str(LIVE),
                            *rest], cwd=LIVE, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
