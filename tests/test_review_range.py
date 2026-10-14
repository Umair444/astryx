#!/usr/bin/env python3
"""Oracle for devtools/review_range.sh: a review range's base is the MERGE-BASE and its head is the BRANCH, both read
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
SRC = Path(os.environ.get("REVIEW_RANGE_SRC") or (REPO / "devtools" / "review_range.sh"))
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

    # ---- the REORG note (a3 night-review 10-15, seed #52734). A reorg that leaves stubs at old paths: the anchor is the
    # commit that ADDED devtools/reorg/map.tsv, reached through a --no-ff merge as on the live main (c80fcbe in ec70478).
    pre_main = git("rev-parse", "main")
    git("checkout", "-qb", "pre")                                         # cut BEFORE the reorg, edits the old paths
    (t / "nucleus" / "sub").mkdir(parents=True)
    (t / "nucleus" / "a.py").write_text("a"); (t / "nucleus" / "sub" / "x.py").write_text("x"); (t / "nucleus" / "sub" / "y.py").write_text("y"); (t / "kept.py").write_text("k")
    git("add", "."); git("commit", "-qm", "pre-reorg edits")
    git("checkout", "-q", "main"); git("checkout", "-qb", "reorg")
    (t / "devtools" / "reorg").mkdir(parents=True)
    (t / "devtools" / "reorg" / "map.tsv").write_text(
        "# old<TAB>new<TAB>module\nnucleus/a.py\tsrc/a.py\ta\nnucleus/sub/\tsrc/sub/\t-\n"
        "nucleus/sub/y.py\tsrc/other/y.py\ty\n")                      # an exact row under the directory row
    git("add", "."); git("commit", "-qm", "reorg map")
    adder = git("rev-parse", "HEAD")
    git("checkout", "-q", "main"); git("merge", "-q", "--no-ff", "-m", "merge reorg", "reorg")
    merge = git("rev-parse", "HEAD")
    git("checkout", "-qb", "atmerge")                                     # cut AT the merge: has the new layout
    (t / "src").mkdir(); (t / "src" / "a.py").write_text("a2"); git("add", "."); git("commit", "-qm", "post edit")
    git("checkout", "-q", "main"); (t / "m4").write_text("4"); git("add", "."); git("commit", "-qm", "later fix")

    rc, out = rr("pre")
    check("reorg: a branch cut before the reorg is told to rebase, naming the commit that added the map",
          rc == 0 and "predates the reorg" in out and adder[:12] in out, out)
    check("reorg: each edit at an old path is listed with its new path, a directory row by prefix (sub/x.py), "
          "and an unmapped file is not", "nucleus/a.py  ->  src/a.py" in out and "nucleus/sub/x.py  ->  src/sub/x.py" in out
          and "kept.py" not in out and "3 file(s) edited at pre-reorg paths" in out, out)
    check("reorg: an exact row beats the directory row it sits under (y.py goes to its OWN target)",
          "nucleus/sub/y.py  ->  src/other/y.py" in out and "src/sub/y.py" not in out, out)
    rc, out = rr("atmerge")
    check("reorg: a branch cut AT the reorg merge reads clean (no rebase ask, none edited)",
          rc == 0 and "predates" not in out and "reorg paths: none edited" in out, out)
    rc, out = rr("--check", "pre", f"{pre_main[:12]}..{git('rev-parse', 'pre')[:12]}")
    check("reorg: the note never changes --check's rc (a correct range stays rc 0)", rc == 0 and "✓" in out
          and "predates" in out, out)
    rc, out = rr("pre", pre_main)
    check("reorg: against a base ref with no map (before any reorg) the note is silent", rc == 0 and "REORG" not in out
          and "reorg paths" not in out, out)
    assert merge

    print(f"\n{'FAIL' if fails else 'PASS'}: review_range ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
