#!/usr/bin/env python3
"""Oracle for src/astryx/pulse/shipped_triggers/pr_review.py's branch fallback (steward 10-20): a medic/* branch is
open review work only while main lacks its PATCH, never by sha. seed lands by replaying a branch onto main (new shas),
so rev-list counted every landed branch as "N commits ahead" forever: on 10-20 the queue read 7 open and all were
landed. Hermetic: a throwaway git repo, gh made to fail so the fallback runs. Exit 0 pass · 1 fail · 77 no git.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = Path(os.environ.get("PR_REVIEW_SRC") or REPO / "src" / "astryx" / "pulse" / "shipped_triggers" / "pr_review.py")
if not shutil.which("git"):
    print("SKIP: no git")
    sys.exit(77)
sys.path.insert(0, str(REPO / "src"))
spec = importlib.util.spec_from_file_location("pr_review_fx", SUBJECT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

fails = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + ("" if cond else f"  — {detail}"))
    if not cond:
        fails.append(label)


GE = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
GE.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
          GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
td = Path(tempfile.mkdtemp(prefix="prr-"))
try:
    def git(*a):
        return subprocess.run(["git", *a], cwd=td, env=GE, capture_output=True, text=True, check=True).stdout

    def commit(name, text):
        (td / name).write_text(text)
        git("add", name)
        git("commit", "-q", "-m", name)
        return git("rev-parse", "HEAD").strip()

    git("init", "-q", "-b", "main")
    commit("base", "0\n")
    git("checkout", "-q", "-b", "medic/landed")
    landed = commit("a", "a\n")
    git("checkout", "-q", "main")
    commit("other", "o\n")                       # main moves on, so the replay gets a NEW sha
    git("cherry-pick", landed)             # seed's land: the same patch, replayed
    git("checkout", "-q", "-b", "medic/open", "main")
    commit("b", "b\n")
    git("checkout", "-q", "-b", "medic/half", "main")
    commit("c", "c\n")
    half_left = commit("d", "d\n")
    git("checkout", "-q", "main")
    git("cherry-pick", "medic/half~1")     # one of medic/half's two commits lands
    git("checkout", "-q", "main")

    real_run = m._run
    m.REPO = td
    m._run = lambda cmd, timeout=15: None if cmd[0] == "gh" else real_run(cmd, timeout)
    items = m._open_items()
    m._run = real_run
    joined = " | ".join(items or [])
    check("a replayed (landed) branch is NOT open review work, though rev-list still counts it ahead",
          "medic/landed" not in joined and git("rev-list", "--count", "main..medic/landed").strip() == "1", joined)
    check("a branch with an unlanded commit IS listed, counted by patch", "branch medic/open (1 commits not on main" in
          joined, joined)
    check("a partly landed branch counts only what's left (1 of 2)", "branch medic/half (1 commits not on main" in joined,
          joined)
    check("the fixture is what it claims (medic/half's tip is the unlanded commit)", bool(half_left))
finally:
    shutil.rmtree(td, ignore_errors=True)

print(f"\n{'FAIL' if fails else 'PASS'}: pr_review counts a branch's open work by patch ({len(fails)} failing)")
sys.exit(1 if fails else 0)
