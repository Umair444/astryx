#!/usr/bin/env python3
"""Oracle for devtools/merge_check.sh (a4 night-review 10-10): the merged-tree chain resolves its base ONCE, refuses a
conflict instead of checking a wrong tree, and removes the transient links it placed.

Hermetic: a temp git repo carrying a copy of the script, with MERGE_CHECK_CHECK / MERGE_CHECK_PTC stubs that RECORD
what they ran on. The stub check MOVES `main` mid-run (today's failure: a twice-read ref made the control a different
tree than the merge's base), so the control must still run on the ORIGINAL sha.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("MERGE_CHECK_SRC") or (REPO / "devtools" / "merge_check.sh"))   # mutation_probe's channel
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True, check=True).stdout.strip()


def main():
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        r = t / "repo"
        (r / "nucleus").mkdir(parents=True)
        for _d in ("devtools", "scripts", "src/astryx/contrib", "src/astryx/core", "src/astryx/data", "src/astryx/econ", "src/astryx/federation", "src/astryx/hands", "src/astryx/hearing", "src/astryx/memory", "src/astryx/people", "src/astryx/pg", "src/astryx/pulse", "src/astryx/pulse/shipped_triggers", "src/astryx/security", "src/astryx/security/sqlguard", "src/astryx/security/sqlguard/shim", "src/astryx/sql"):  # goal 10224 S4: the moved tree's dirs
            (r / _d).mkdir(parents=True, exist_ok=True)
        git(t, "init", "-q", "-b", "main", str(r))
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            git(r, "config", k, v)
        shutil.copy(SRC, r / "devtools" / "merge_check.sh")
        (r / "f.txt").write_text("base\n")
        (r / ".gitignore").write_text(".env\nagents/secret/\n")
        (r / "agents").mkdir()
        (r / "agents" / "tracked.md").write_text("tracked\n")              # a TRACKED dir…
        git(r, "add", "-A")
        git(r, "commit", "-qm", "base")
        (r / ".env").write_text("ASTRYX_DSN=x\n")                           # a live-estate file to link
        (r / ".git" / "info" / "exclude").write_text("**/.claude/worktrees/\n")   # as on live: ignored only here
        (r / ".claude" / "worktrees" / "agent-z").mkdir(parents=True)          # .claude/ holds ONLY a worktree (fresh
        (r / ".claude" / "worktrees" / "agent-z" / "x.py").write_text("other branch\n")   # install): git lists both
        (r / ".git" / "info" / "exclude").write_text("**/.claude/worktrees/\n*.log\n")
        (r / ".claude" / "\u00fc.log").write_text("estate\n")                  # a2 #54105: quoted without -z
        (r / "agents" / "secret").mkdir()                                  # …holding a GITIGNORED subdir (a1 #40418)
        (r / "agents" / "secret" / "charter.md").write_text("roster\n")
        (r / "agents" / "secret" / "empty").mkdir()                         # an EMPTY estate dir still exists there
        git(r, "checkout", "-qb", "feat")
        (r / "g.txt").write_text("feature\n")
        git(r, "add", "g.txt")
        git(r, "commit", "-qm", "feat")
        git(r, "checkout", "-q", "main")
        git(r, "checkout", "-qb", "clash")
        (r / "f.txt").write_text("clash\n")
        git(r, "commit", "-qam", "clash")
        git(r, "checkout", "-q", "main")
        (r / "f.txt").write_text("main moved\n")
        git(r, "commit", "-qam", "main moves")
        base0 = git(r, "rev-parse", "main")
        rec = t / "rec.log"
        # the stub check: records the cwd's link state AND MOVES main (a concurrent merge landing mid-run)
        stub_check = (f"sh -c 'test -L .env && echo LINKED >> {rec}; "
                      f"test -e .claude/worktrees/agent-z/x.py && echo WTLINKED >> {rec}; "
                      f"test -e .claude/\u00fc.log && echo UNILINKED >> {rec}; "
                      f"test -f agents/secret/charter.md && echo SUBLINKED >> {rec}; "
                      f"echo written >> agents/secret/charter.md; "
                      f"echo scratch > agents/secret/run_made.txt; "
                      f"echo other > {r}/agents/secret/concurrent_new.txt; "
                      f"test -d agents/secret/empty && echo EMPTYDIR >> {rec}; "
                      f"python3 -c \"import pathlib,sys; sys.exit(not any(pathlib.Path(\\\"agents\\\").rglob(\\\"charter.md\\\")))\" "
                      f"&& echo RGLOB >> {rec}; "
                      f"git -C {r} commit -q --allow-empty -m concurrent; "
                      # a NESTED check's verdict first (an oracle that runs check.sh prints one), then the real one
                      f"echo \"FAILED (1):\"; echo \"  ✗ nested decoy\"; echo; echo \"check: nested\"; echo \"  ✓ later gate\"; "
                      f"echo; echo \"FAILED (1):\"; echo \"  ✗ a gate\"; "
                      f"echo \"UNVERIFIED (1) — this run did NOT check these\"; echo \"  ○ a dark gate\"; echo; "
                      f"echo \"check: FAILURES above\"'")
        stub_ptc = f"sh -c 'echo PTC $0 >> {rec}'"
        # HERMETIC: a caller's own MERGE_CHECK_* settings never reach the runs under test (forge #48470: an outer
        # MERGE_CHECK_FULL=0 skipped every inner full check, and this oracle read RED inside a merge_check only)
        base_env = {k: v for k, v in os.environ.items() if not k.startswith("MERGE_CHECK_")}
        env = {**base_env, "MERGE_CHECK_CHECK": stub_check, "MERGE_CHECK_PTC": stub_ptc,
               "TMPDIR": str(t)}                       # scratch trees die with the temp dir, even a mutant's leaked ones
        p = subprocess.run(["bash", str(r / "devtools" / "merge_check.sh"), "feat"], cwd=r, env=env,
                           capture_output=True, text=True, timeout=120)
        log = rec.read_text() if rec.exists() else ""
        merged = next((ln.split("merged=")[1].strip() for ln in p.stdout.splitlines() if "merged=" in ln), "")
        check("a clean merge runs: exit 0, and it reports the base, the branch and the merged sha",
              p.returncode == 0 and f"base main={base0}" in p.stdout and merged, p.stdout[-400:] + p.stderr[-200:])
        parents = git(r, "rev-list", "--parents", "-n1", merged).split()[1:] if merged else []
        check("the merged commit's FIRST parent is the base read at the start", parents[:1] == [base0], str(parents))
        moved = git(r, "rev-parse", "main")
        check("BASE READ ONCE: main moved mid-run, yet the control ran on the ORIGINAL sha, never the moved one",
              moved != base0 and f"PTC {base0}" in log and f"PTC {moved}" not in log, log)
        check("…and the merged tree's pushed check ran on the merged sha", merged and f"PTC {merged}" in log, log)
        check("the full check ran with the live estate LINKED in", "LINKED" in log, log)
        check("another checkout under .claude/worktrees/ is NEVER linked in, even when it is all .claude/ holds "
              "(steward #53465)", "WTLINKED" not in log, log)
        check("…while a NON-ASCII estate file beside it IS linked, under its real name (a2 #54105: ls-files -z)",
              "UNILINKED" in log, log)
        check("a1 #40418: a GITIGNORED subdir inside a TRACKED dir is linked per entry, and the gate reads it",
              "SUBLINKED" in log, log)
        check("painter #42999: a WALKER sees inside a gitignored DIRECTORY (Python rglob skips a linked dir: link per file)",
              "RGLOB" in log, log)
        check("…and an EMPTY estate directory exists in the scratch tree too", "EMPTYDIR" in log, log)
        check("…and a file the run CREATES there stays in the scratch tree, never the live estate",
              not (r / "agents" / "secret" / "run_made.txt").exists())
        check("a1 R2: a write the run made THROUGH a linked file reaches LIVE and is NAMED in the report",
              "LIVE WRITES" in p.stdout and "charter.md" in p.stdout
              and "written" in (r / "agents" / "secret" / "charter.md").read_text(), p.stdout[-400:])
        check("a1 #43404: a CONCURRENT writer's NEW file in a live estate dir is listed too (the scan walks the estate, not the links)",
              "concurrent_new.txt" in p.stdout, p.stdout[-400:])
        check("…and NOT attributed to the run: the estate has concurrent writers, a mtime can't tell them apart (a4 10-10)",
              "NOT ATTRIBUTED" in p.stdout, p.stdout[-400:])
        trees = [ln for ln in git(r, "worktree", "list").splitlines() if "merge-check." in ln]
        check("…and the scratch worktree (with its links) is gone afterwards", trees == [], str(trees))
        check("the merged tree's FAILED set is printed", "✗ a gate" in p.stdout, p.stdout[-300:])
        check("a1 night-review 10-16: …and its UNVERIFIED set, a gate that verified NOTHING about this merge (it was cut, "
              "so an all-skip run printed exactly what a clean run printed)", "○ a dark gate" in p.stdout, p.stdout[-300:])
        check("…and check.sh's own `check:` verdict line", "check: FAILURES above" in p.stdout, p.stdout[-300:])
        check("…from the LAST verdict only: a nested check's block in the same log is never quoted as this merge's",
              "nested decoy" not in p.stdout and "check: nested" not in p.stdout, p.stdout[-300:])
        rec.unlink(missing_ok=True)
        p = subprocess.run(["bash", str(r / "devtools" / "merge_check.sh"), "clash"], cwd=r, env=env,
                           capture_output=True, text=True, timeout=120)
        log = rec.read_text() if rec.exists() else ""
        check("A CONFLICT IS A REFUSAL: exit 2, the conflicting path named, and NO check or pushed check ran",
              p.returncode == 2 and "CONFLICTS" in p.stdout and "f.txt" in p.stdout and log == "",
              f"rc={p.returncode} {p.stdout[-200:]} log={log!r}")
        p = subprocess.run(["bash", str(r / "devtools" / "merge_check.sh"), "no-such-branch"], cwd=r, env=env,
                           capture_output=True, text=True, timeout=60)
        check("an unknown branch exits 2, naming it", p.returncode == 2 and "no-such-branch" in p.stdout, p.stdout)
        # a check that never reaches its verdict (timed out, crashed) is NAMED, never an empty report that reads as clean
        p = subprocess.run(["bash", str(r / "devtools" / "merge_check.sh"), "feat"], cwd=r,
                           env={**env, "MERGE_CHECK_CHECK": "sh -c 'echo \"  ✓ a gate\"; echo partial output'"},
                           capture_output=True, text=True, timeout=120)
        check("a log with NO `check:` verdict says NO VERDICT (it used to print nothing, as a clean run does)",
              "NO VERDICT" in p.stdout, p.stdout[-300:])
        # AN INTERRUPT CLEANS UP (a4 10-10: a stopped run left 38 live links in /tmp). TERM goes to the SCRIPT only, mid-check,
        # with the check sleeping: a foreground child would defer the trap until it ended.
        rec.unlink(missing_ok=True)
        done = t / "check_finished"
        slow = (f"sh -c 'test -L .env && echo LINKED >> {rec}; pwd >> {rec}; sleep 4; touch {done}'")
        q = subprocess.Popen(["bash", str(r / "devtools" / "merge_check.sh"), "feat"], cwd=r,
                             env={**env, "MERGE_CHECK_CHECK": slow}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        import time
        for _ in range(200):
            if rec.exists() and "LINKED" in rec.read_text():
                break
            time.sleep(0.1)
        wt = Path(rec.read_text().splitlines()[-1]) if rec.exists() and len(rec.read_text().splitlines()) > 1 else None
        q.terminate()
        try:
            out, _ = q.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            q.kill(); out = "(still running 15s after TERM: the trap waited on the check)"
        time.sleep(1)
        check("AN INTERRUPT CLEANS UP: TERM mid-check exits 130 promptly and says so",
              q.returncode == 130 and "INTERRUPTED" in out, f"rc={q.returncode} {out[-300:]}")
        check("…the links are gone and the scratch tree is removed",
              wt is not None and not wt.exists() and "merge-check." not in git(r, "worktree", "list"), f"{wt} {git(r, 'worktree', 'list')}")
        time.sleep(6)                                                    # past the stub's own 4s: a live check would have finished
        check("…and the check itself was stopped, not left running against live links", not done.exists())
        # A SIGKILLed run can't clean up: the next run NAMES its tree and leaves it alone (it may be a run in progress)
        orphan = t / "merge-check.orphan" / "tree"
        git(r, "worktree", "add", "-q", "--detach", str(orphan), "main")
        (orphan / ".env").symlink_to(r / ".env")
        p = subprocess.run(["bash", str(r / "devtools" / "merge_check.sh"), "feat"], cwd=r, env={**env, "MERGE_CHECK_FULL": "0"},
                           capture_output=True, text=True, timeout=60)
        check("an orphaned scratch tree holding live links is NAMED, and not touched",
              "ORPHAN?" in p.stdout and str(orphan) in p.stdout and (orphan / ".env").is_symlink(), p.stdout[-300:])
        # NOT HANDED DOWN: what merge_check runs (the full check, pushed_tree_check) sees none of its MERGE_CHECK_* settings,
        # or a nested merge_check (test_merge_check inside the check) inherits them (forge #48470)
        seen = t / "seen_env"
        probe = f"sh -c 'env | grep -c ^MERGE_CHECK_ >> {seen}; true'"
        subprocess.run(["bash", str(r / "devtools" / "merge_check.sh"), "feat"], cwd=r, capture_output=True, text=True, timeout=120,
                       env={**env, "MERGE_CHECK_CHECK": probe, "MERGE_CHECK_PTC": probe, "MERGE_CHECK_CANARY": "x"})
        counts = seen.read_text().split() if seen.exists() else []
        check("its MERGE_CHECK_* settings are NOT handed to the full check or pushed_tree_check (a nested run inherits none)",
              len(counts) == 3 and set(counts) == {"0"}, str(counts))
    # ONE definition: the script's exclude list must equal the ledger's (no second hand-kept copy drifting)
    import re as _re
    sys.path.insert(0, str(REPO))
    from astryx.security.sqlguard.ledger import ESTATE_EXCLUDE
    mm = _re.search(r'ESTATE_EXCLUDE="([^"]*)"', SRC.read_text())
    check("the script's ESTATE_EXCLUDE equals src/astryx/security/sqlguard/ledger.py's (parity, not a second list)",
          bool(mm) and set(mm.group(1).split()) == set(ESTATE_EXCLUDE), f"{mm.group(1) if mm else None} vs {ESTATE_EXCLUDE}")
    # Other checkouts are never estate (steward #53465, forge #53471): a subagent worktree under .claude/worktrees/ is
    # ignored only through .git/info/exclude, and that is exactly what made git report it as estate.
    import subprocess as _sp
    import tempfile as _tf
    from astryx.security.sqlguard.ledger import estate_paths
    with _tf.TemporaryDirectory() as td:
        r = Path(td)
        _sp.run(["git", "init", "-q", str(r)], check=True)
        (r / ".git" / "info" / "exclude").write_text("**/.claude/worktrees/\n*.ign\nsp ace/\n")
        for f in (".claude/worktrees/agent-x/src/mod.py", "sub/.claude/worktrees/agent-y/a.py", "keep.ign",
                  "P/\u00fc.ign", "P/sp ace/x"):
            (r / f).parent.mkdir(parents=True, exist_ok=True)
            (r / f).write_text("x\n")
        ep = estate_paths(r)
    check("estate: another checkout under .claude/worktrees/ (top-level or nested) is never estate; a sibling ignored "
          "file still is", "keep.ign" in ep and not [e for e in ep if ".claude" in e], str(ep))
    check("estate: a NON-ASCII ignored file under a dropped parent survives under its REAL name, never git's quoted "
          "form (a2 #54105: -z)", "P/\u00fc.ign" in ep and "P/sp ace/" in ep and not [e for e in ep if e.startswith('"')],
          str(ep))
    print(f"\n{'FAIL' if fails else 'PASS'}: merge_check ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
