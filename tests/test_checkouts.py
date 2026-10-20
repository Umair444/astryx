#!/usr/bin/env python3
"""Oracle for astryx.paths' Checkouts: ONE "another checkout of this repo" predicate for every walker (seed #53453,
a4 #53469).

A fixture repo R holds a linked worktree (.claude/worktrees/agent-x), a FOREIGN nested repo (agentsrepo/, like agents/)
and a plain dir (pkg/):
  C1 in R: the worktree is another checkout and is pruned and recorded; the foreign repo and pkg are walked; R isn't one
  C2 holds_only_others: .claude/worktrees/ (only checkouts in it) yes; pkg/ no; an empty dir no
  C3 a `git archive` tree of R (no .git) holding a linked worktree: UNDECLARED it is UNKNOWN (prunes nothing, and its
     report SAYS so); DECLARED (ASTRYX_REPO_COMMON) the worktree is pruned and a foreign repo inside is still walked
  C4 the admin dir unreadable (branch_check's sandbox binds no live .git): the pointer's text still names R's repo; a
     pointer into ANOTHER repo's worktrees/ is not R's (control)
  C5 a real walker: copies' estate walk skips the worktree's files and keeps the foreign repo's
  C6 every walker asks this module: the four use Checkouts, and none keeps its own _common_dir
CHECKOUTS_SRC points at a mutant (tests/mutants_checkouts.py). Exit 0 pass · 1 fail.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location("checkouts_under_test",
                                              os.environ.get("CHECKOUTS_SRC") or REPO / "src/astryx/paths.py")
ck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ck)
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


GE = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != ck.CHECKOUT_SOURCE_ENV}


def git(*a, cwd=None):
    # own-env: git only, in this oracle's temp repos (GE scrubs GIT_* and the checkout-source key)
    subprocess.run(["git", *a], cwd=cwd, env=GE, capture_output=True, check=True)


def walk(co, root):
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = co.prune(dirpath, dirnames)
        seen |= {os.path.relpath(os.path.join(dirpath, f), root) for f in filenames}
    return seen


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    R = td / "R"
    (R / "pkg").mkdir(parents=True)
    (R / "pkg" / "a.py").write_text("x = 1\n")
    git("init", "-q", str(R))
    git("-C", str(R), "add", "-A")
    git("-C", str(R), "-c", "user.name=fx", "-c", "user.email=fx@example.invalid", "commit", "-qm", "fx")
    wt = R / ".claude" / "worktrees" / "agent-x"
    wt.parent.mkdir(parents=True)
    git("-C", str(R), "worktree", "add", "-q", "--detach", str(wt))
    foreign = R / "agentsrepo"
    foreign.mkdir()
    git("init", "-q", str(foreign))
    (foreign / "b.py").write_text("y = 2\n")
    (R / "empty").mkdir()

    print("C1: in a checkout, only ANOTHER CHECKOUT OF IT is pruned")
    co = ck.Checkouts(R, env={})
    check("R is a checkout (its source is known)", not co.unknown)
    check("the linked worktree is another checkout of R", co.is_other(wt))
    check("the FOREIGN nested repo is not (agents/ is its own repo)", not co.is_other(foreign))
    check("a plain dir is not", not co.is_other(R / "pkg"))
    check("R itself is not", not co.is_other(R))
    seen = walk(co, R)
    check("a walk keeps pkg/ and the foreign repo, and skips the worktree",
          "pkg/a.py" in seen and "agentsrepo/b.py" in seen and not any(s.startswith(".claude/worktrees") for s in seen),
          str(sorted(seen)))
    check("the pruned worktree is recorded for the walker's report", co.found == {".claude/worktrees/agent-x"}, str(co.found))

    print("C2: a dir holding only other checkouts")
    check(".claude/worktrees/ holds only other checkouts", co.holds_only_others(R / ".claude" / "worktrees"))
    check("pkg/ does not", not co.holds_only_others(R / "pkg"))
    check("an empty dir does not", not co.holds_only_others(R / "empty"))
    check(".claude/ holding only worktrees/<checkout> does (git lists that PARENT)", co.holds_only_others(R / ".claude"))
    (R / ".claude" / "settings.json").write_text("{}")
    check("...but not once it also holds a file (authored state) (control)", not co.holds_only_others(R / ".claude"))
    (R / ".claude" / "settings.json").unlink()

    print("C3: a git-archive tree (no .git), undeclared and declared")
    A = td / "A"
    A.mkdir()
    arch = subprocess.run(["git", "-C", str(R), "archive", "HEAD"], env=GE, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(A)], input=arch, check=True)
    awt = A / ".claude" / "worktrees" / "agent-y"
    awt.parent.mkdir(parents=True)
    git("-C", str(R), "worktree", "add", "-q", "--detach", str(awt))
    afor = A / "agentsrepo"
    afor.mkdir()
    git("init", "-q", str(afor))
    (afor / "b.py").write_text("y = 2\n")
    und = ck.Checkouts(A, env={})
    check("undeclared, the archive tree's source is UNKNOWN", und.unknown)
    check("...it prunes nothing (no guess)", not und.is_other(awt))
    check("...and its report SAYS so", "UNKNOWN" in und.report() and ck.CHECKOUT_SOURCE_ENV in und.report(), und.report())
    walk(und, A)
    check("...and a walk NAMES the nested checkout roots it couldn't classify (a walker then says NOT SEARCHED)",
          ".claude/worktrees/agent-y" in und.unclassified and "agentsrepo" in und.unclassified, str(und.unclassified))
    check("a KNOWN source leaves nothing unclassified (control)", not co.unclassified, str(co.unclassified))
    dec = ck.Checkouts(A, env={ck.CHECKOUT_SOURCE_ENV: str(ck.common_dir(R))})
    check("declared, the archive tree knows its source", not dec.unknown)
    check("...the linked worktree inside it is pruned", dec.is_other(awt))
    check("...and a foreign nested repo inside it is still walked", not dec.is_other(afor))

    print("C4: the admin dir unreadable (a sandbox): the pointer's text still names the repository")
    ghost = R / "ghost"
    ghost.mkdir()
    (ghost / ".git").write_text(f"gitdir: {R / '.git' / 'worktrees' / 'ghost-nonexistent'}\n")
    check("a pointer into R's worktrees/ (admin dir absent) reads as R's", co.is_other(ghost),
          str(ck.common_dir(ghost)))
    alien = R / "alien"
    alien.mkdir()
    (alien / ".git").write_text(f"gitdir: {td / 'other' / '.git' / 'worktrees' / 'x'}\n")
    check("a pointer into ANOTHER repo's worktrees/ is not R's (control)", not co.is_other(alien),
          str(ck.common_dir(alien)))
    shutil.rmtree(ghost)
    shutil.rmtree(alien)

    print("C5: a real walker (copies' estate walk) asks the predicate")
    from astryx.core import copies
    real = {str(p.relative_to(R)) for p in copies._estate_files(R)}
    check("copies keeps the foreign repo's files and skips the worktree's",
          "agentsrepo/b.py" in real and not any(s.startswith(".claude/worktrees") for s in real), str(sorted(real)))

print("C6: every walker asks THIS module")
WALKERS = ("src/astryx/security/sqlguard/inventory.py", "src/astryx/core/copies.py", "tests/test_econ_consumers.py",
           "tests/test_backup_inputs.py")
for w in WALKERS:
    t = (REPO / w).read_text()
    check(f"{w} uses the shared Checkouts", "Checkouts(" in t and "from astryx.paths import" in t)
own = [p for p in ("src", "devtools", "tests") for p in (REPO / p).rglob("*.py")
       if "def _common_dir" in p.read_text(errors="replace") and p.name != "test_checkouts.py"]
check("no file keeps its own _common_dir (a copy drifts)", not own, str(own))

print()
print("PASS: one predicate: another checkout of THIS repo is pruned, a foreign repo walked, the unknown said" if not fails
      else f"FAIL ({len(fails)}): " + "; ".join(fails))
sys.exit(1 if fails else 0)
