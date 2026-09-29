#!/usr/bin/env python3
"""Oracle: a push from a LINKED WORKTREE cannot reach the shared .git through the hook.

    venv/bin/python tests/test_git_env_isolation.py              (the oracle, check.sh)
    venv/bin/python tests/test_git_env_isolation.py --tripwire   (the standing tripwire, check.sh)

THE INCIDENT (2026-09-30, 23:24Z, memory msg 28057). In a linked worktree git exports
GIT_DIR=<repo>/.git/worktrees/<wt> to hooks. hooks/pre-push -> pushed_tree_check.sh ->
check.sh inherited it, so every child addressed the SHARED repo instead of its own:
  * a test's `git init <tmp>` re-initialized the shared repo, and init with GIT_DIR set and no
    work tree writes core.bare=true into the common .git/config. That broke git for every
    agent until seed restored it.
  * pushed_tree_check's own `git -C "$TREE" checkout` detached the pusher's worktree instead
    of the clone, so even the "real clone" was not isolated.
A push from the MAIN tree does not export a GIT_DIR that points elsewhere, which is why this
stayed hidden until the cherry-pick-onto-origin/main PR flow moved pushes into worktrees.

THE FIX lives in nucleus/pushed_tree_check.sh: it unsets the repo-locating GIT_* variables
right after REPO is computed, so the clone, the checkout, check.sh and every test below it
locate their own repository.

HERMETIC. Every arm builds a throwaway repo (a bare remote, a main tree, a linked worktree),
commits the REAL tracked hooks/pre-push and the REAL nucleus/pushed_tree_check.sh into it,
and stubs privacy_gate.sh and check.sh. The stub check.sh does what a test did in the
incident: `git init` in a temp dir. Nothing here touches the live repo, and this process
scrubs its own GIT_* first, because check.sh can itself run under a worktree hook.

THE ARMS:
  RED      the script with the unset line removed, pushed from the worktree: the shared
           config goes bare or the worktree detaches. This proves the oracle can see the bug.
  GREEN    the real script, pushed from the worktree: config not bare, worktree on its branch.
  CONTROL  the unfixed script, pushed from the MAIN tree: not bare. Only worktree pushes trip.
  TRIPWIRE the --tripwire reader flags a throwaway repo set bare, and passes one that is not.

--tripwire: this repo's COMMON config must not say core.bare=true. It is cheap and standing,
so any other path that flips the bit is caught on the next check.sh run. Exit 77 when this
checkout is not a git repo (an archive export): there is nothing to read, and that is not a pass.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "pre-push"
SCRIPT = REPO / "nucleus" / "pushed_tree_check.sh"
UNSET = "unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX GIT_COMMON_DIR"
# The repo-locating variables. Scrubbed from THIS process first: under a worktree hook they
# would point the throwaway repos' git calls at the shared .git, which is the incident itself.
LOCATORS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")
for _v in LOCATORS:
    os.environ.pop(_v, None)

STUB_PRIVACY = "#!/bin/sh\nexit 0\n"
# What a test did in the incident: `git init` in a fresh temp dir, trusting cwd to pick the repo.
STUB_CHECK = '#!/bin/sh\nd=$(mktemp -d)\ngit init -q "$d"\nrm -rf "$d"\nexit 0\n'

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        if detail:
            print(f"        {detail}")
        fails.append(name)


def git(*args, cwd, env=None, check_rc=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env,
                       timeout=60)
    if check_rc and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


def is_bare(common_config: Path) -> bool:
    """The tripwire's reader: does this config file say core.bare=true?"""
    r = subprocess.run(["git", "config", "--file", str(common_config), "--bool", "core.bare"],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip() == "true"


def build(td: Path, script_body: str) -> tuple:
    """A bare remote, a main tree carrying the real hook + the given script, and a linked
    worktree on branch `br`. Returns (main, wt, env)."""
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", TMPDIR=str(td))
    main, wt, remote = td / "main", td / "wt", td / "remote.git"
    git("init", "-q", "--bare", str(remote), cwd=td, env=env)
    git("init", "-q", "-b", "main", str(main), cwd=td, env=env)
    (main / "hooks").mkdir()
    (main / "nucleus").mkdir()
    shutil.copy(HOOK, main / "hooks" / "pre-push")
    for rel, body in (("nucleus/pushed_tree_check.sh", script_body),
                      ("nucleus/privacy_gate.sh", STUB_PRIVACY),
                      ("nucleus/check.sh", STUB_CHECK)):
        (main / rel).write_text(body)
        (main / rel).chmod(0o755)
    git("add", "-A", cwd=main, env=env)
    git("commit", "-q", "-m", "fixture", cwd=main, env=env)
    git("remote", "add", "origin", str(remote), cwd=main, env=env)
    shutil.copy(HOOK, main / ".git" / "hooks" / "pre-push")
    (main / ".git" / "hooks" / "pre-push").chmod(0o755)
    git("worktree", "add", "-q", "-b", "br", str(wt), cwd=main, env=env)
    return main, wt, env


def push_from(where: Path, env: dict) -> tuple:
    """Push `where`'s HEAD branch; return (config went bare?, worktree still on `br`?)."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=where, env=env).stdout.strip()
    git("push", "-q", "origin", branch, cwd=where, env=env, check_rc=False)
    main = where if (where / ".git").is_dir() else where.parent / "main"
    bare = is_bare(main / ".git" / "config")
    wt = where.parent / "wt"
    on_branch = git("symbolic-ref", "-q", "HEAD", cwd=wt, env=env,
                    check_rc=False).stdout.strip() == "refs/heads/br"
    return bare, on_branch


def tripwire() -> int:
    r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       cwd=REPO, capture_output=True, text=True, timeout=30)
    if r.returncode:
        print("core.bare tripwire: not a git checkout — VERIFIED NOTHING")
        return 77
    cfg = Path(r.stdout.strip()) / "config"
    if is_bare(cfg):
        print(f"core.bare tripwire: FAIL — {cfg} says core.bare=true. Every agent's git is broken.")
        print("  Restore: git config --file <that path> core.bare false. Then find the writer:")
        print("  a git call that inherited a foreign GIT_DIR (see tests/test_git_env_isolation.py).")
        return 1
    print(f"core.bare tripwire: PASS — the common config is not bare")
    return 0


def main() -> int:
    if not (HOOK.is_file() and SCRIPT.is_file()):
        print("SKIP: hooks/pre-push or nucleus/pushed_tree_check.sh absent — VERIFIED NOTHING")
        return 77
    real = SCRIPT.read_text()
    check("the real script carries the GIT_* unset line", UNSET in real)
    unfixed = real.replace(UNSET + "\n", "")

    with tempfile.TemporaryDirectory() as td:
        main_, wt, env = build(Path(td), unfixed)
        bare, on_branch = push_from(wt, env)
        check("RED: unfixed script, worktree push -> shared config bare or worktree detached",
              bare or not on_branch, f"bare={bare} on_branch={on_branch}")

    with tempfile.TemporaryDirectory() as td:
        main_, wt, env = build(Path(td), real)
        bare, on_branch = push_from(wt, env)
        check("GREEN: real script, worktree push -> not bare, worktree still on its branch",
              not bare and on_branch, f"bare={bare} on_branch={on_branch}")

    with tempfile.TemporaryDirectory() as td:
        main_, wt, env = build(Path(td), unfixed)
        bare, _ = push_from(main_, env)
        check("CONTROL: unfixed script, MAIN-tree push -> not bare", not bare, f"bare={bare}")

    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        r = Path(td) / "r"
        git("init", "-q", str(r), cwd=td, env=env)
        cfg = r / ".git" / "config"
        clean = is_bare(cfg)
        git("config", "--file", str(cfg), "core.bare", "true", cwd=td, env=env)
        check("TRIPWIRE: flags a bare common config, passes a clean one",
              is_bare(cfg) and not clean, f"clean={clean}")

    print(f"\n{'PASS' if not fails else f'FAILED ({len(fails)})'}: git env isolation")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(tripwire() if "--tripwire" in sys.argv[1:] else main())
