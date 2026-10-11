#!/usr/bin/env python3
"""Oracle for nucleus/review_range.sh: a review range's base is the MERGE-BASE and its head is the BRANCH, both read
from git (a4 night-review 10-12). Hermetic: a throwaway repo where main moves past the fork, so the three 10-11
errors (the merged-ONTO sha as base, a base older than the fork, a typed head that doesn't resolve) each have an arm.

    venv/bin/python tests/test_review_range.py      (REVIEW_RANGE_SRC: mutation_probe's channel)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("REVIEW_RANGE_SRC") or (REPO / "nucleus" / "review_range.sh"))
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def main():
    t = Path(tempfile.mkdtemp(prefix="review-range-"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def git(*a):
        return subprocess.run(["git", *a], cwd=t, env=env, capture_output=True, text=True, check=True).stdout.strip()

    def rr(*a):
        p = subprocess.run(["bash", str(SRC), *a], cwd=t, env=env, capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout

    git("init", "-q", "-b", "main")
    for i in (1, 2):
        (t / f"m{i}").write_text(str(i)); git("add", "."); git("commit", "-qm", f"m{i}")
    old = git("rev-parse", "HEAD~1")
    fork = git("rev-parse", "HEAD")
    git("checkout", "-qb", "feat")
    for i in (1, 2):
        (t / f"f{i}").write_text(str(i)); git("add", "."); git("commit", "-qm", f"f{i}")
    head, prev = git("rev-parse", "HEAD"), git("rev-parse", "HEAD~1")
    git("checkout", "-q", "main")
    (t / "m3").write_text("3"); git("add", "."); git("commit", "-qm", "m3")                # main moves past the fork
    tip = git("rev-parse", "HEAD")

    rc, out = rr("feat")
    check("derive: base is the MERGE-BASE (the fork), never main's tip, and head is the branch",
          rc == 0 and out.splitlines()[0] == f"feat {fork[:12]}..{head[:12]}" and tip[:12] not in out.splitlines()[0], out)
    check("…with the range's own counts (2 commits, 2 files), not main's", "2 commit(s), 2 file(s)" in out, out)
    rc, out = rr("--check", "feat", f"{fork[:12]}..{head[:12]}")
    check("--check: the derived range passes (rc 0)", rc == 0 and "✓" in out, out)
    rc, out = rr("--check", "feat", f"{fork[:7]}...{head[:7]}")
    check("--check: short prefixes and the three-dot form resolve to the same endpoints", rc == 0, out)
    rc, out = rr("--check", "feat", f"{tip[:12]}..{head[:12]}")
    check("--check: the merged-ONTO sha (main's tip) as base is refused, naming the merge-base (a4 #45772)",
          rc == 1 and fork[:12] in out and "merge-base" in out, out)
    rc, out = rr("--check", "feat", f"{old[:12]}..{head[:12]}")
    check("--check: a base OLDER than the fork (other merges would ride inside) is refused", rc == 1 and fork[:12] in out, out)
    rc, out = rr("--check", "feat", f"{fork[:12]}..6d0e9d0")
    check("--check: a head that doesn't resolve is refused, named (forge #48190)", rc == 1 and "doesn't resolve" in out, out)
    rc, out = rr("--check", "feat", f"{fork[:12]}..{prev[:12]}")
    check("--check: a head that is NOT the branch's (a stale tip) is refused", rc == 1 and head[:12] in out, out)
    rc, out = rr("no-such-branch")
    check("an unknown branch exits 2, naming it", rc == 2 and "no-such-branch" in out, out)
    rc, out = rr("--check", "feat", "abc")
    check("a non-range argument exits 2", rc == 2 and "not a range" in out, out)

    print(f"\n{'FAIL' if fails else 'PASS'}: review_range ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
