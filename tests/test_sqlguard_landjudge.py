#!/usr/bin/env python3
"""Oracle for src/astryx/security/sqlguard/landjudge.py, the HERMETIC half (plan-11908 D6 + D7). No database: each arm
builds a throwaway git repo with a SQL-bearing subject, so the trigger, the move rule and the verdict run for real.
The replay of f46eb3e5 (the shipped case, which needs the fixture DB) is tests/test_sqlguard_landjudge_replay.py.

    venv/bin/python tests/test_sqlguard_landjudge.py

  J1 a range that touches only tests/ is not triggered, and builds no inventory
  J2 a .py change that moves no SQL is not triggered (inv(A) = inv(B))
  J3 a MOVE-ONLY range (the function renamed, same file, same SQL) passes, with no oracle run
  J4 a range that ADDS a site with no test_*.py oracle is REFUSED, naming the count
  J5 decide(): an introduced site below RESPONSIVE is REFUSED naming its key; RESPONSIVE passes; a ledger-listed one
     passes; an R-BLIND in a touched file is refused, elsewhere ignored; every line names what it certifies and not
  J6 inv(B) from the extract EQUALS the inventory of this checkout at the same sha, on tracked files
Exit 0 pass · 1 fail.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard import landjudge as lj  # noqa: E402

fails = []
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


def git(r, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=r, env=ENV,
                          capture_output=True, text=True, check=True).stdout.strip()


SUBJ = 'def {fn}(c, k):\n    return c.execute("SELECT id FROM goals WHERE id = %s", (k,)).fetchall()\n'
NEW = 'def added(c, k):\n    return c.execute("SELECT id FROM goals WHERE owner = %s", (k,)).fetchall()\n'


def repo(td, files_b, files_a=None):
    r = Path(td)
    git(r, "init", "-q")
    for rel, body in (files_a or {"subj/a.py": SUBJ.format(fn="f")}).items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(body)
    git(r, "add", "-A")
    git(r, "commit", "-qm", "a")
    a = git(r, "rev-parse", "HEAD")
    for rel, body in files_b.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(body)
    git(r, "add", "-A")
    git(r, "commit", "-qm", "b")
    return r, a, git(r, "rev-parse", "HEAD")


def judge(files_b, oracles=(), files_a=None):
    with tempfile.TemporaryDirectory() as td:
        r, a, b = repo(td, files_b, files_a)
        lines = []
        rc = lj.land_judge(a, b, r, list(oracles), log=lines.append)
        return rc, "\n".join(lines)


def main():
    rc, out = judge({"tests/test_x.py": "print(1)\n"})
    arm("J1 a tests/-only range is not triggered (no inventory built)", rc == 0 and "not triggered (no .py" in out, out)
    rc, out = judge({"subj/a.py": SUBJ.format(fn="f") + "\nX = 1\n"})
    arm("J2 a .py change that moves no SQL is not triggered (inv(A) = inv(B))", rc == 0 and "inv(A) = inv(B)" in out, out)
    rc, out = judge({"subj/a.py": SUBJ.format(fn="renamed")})
    arm("J3 a move-only range (renamed function, same SQL) passes with nothing to grade",
        rc == 0 and "only MOVED 1 site" in out and "NOT certified" in out, out)
    rc, out = judge({"subj/b.py": NEW})
    arm("J4 a range that adds a site and has no test_*.py oracle is REFUSED", rc == 1 and "adds 1 SQL site" in out, out)

    k_new, k_ok, k_led = "subj/b.py::added\x1fselect 1", "subj/b.py::fine\x1fselect 2", "subj/b.py::listed\x1fselect 3"
    sites = {k_new: {"rung": "EXECUTED"}, k_ok: {"rung": "RESPONSIVE"}, k_led: {"rung": "UNEXECUTED"}}
    blind = [{"frame": ["subj/b.py", "g", 3], "t": "select 9"}, {"frame": ["other/c.py", "h", 1], "t": "select 8"}]
    ref, ok = lj.decide({k_new, k_ok, k_led}, sites, {k_led: k_led}, {k_led}, blind, {"subj/b.py"})
    arm("J5 an introduced site below RESPONSIVE is REFUSED naming its key and rung",
        any("R-NEW-introduced subj/b.py::added :: select 1: EXECUTED" in x for x in ref), str(ref))
    arm("J5 a RESPONSIVE one and a ledger-listed one pass",
        any("subj/b.py::fine" in x and x.startswith("✓") for x in ok) and any("subj/b.py::listed" in x for x in ok), str(ok))
    arm("J5 an R-BLIND in a file the range touched is refused; one elsewhere is the timer's",
        sum(x.startswith("R-BLIND subj/b.py") for x in ref) == 1 and not any("other/c.py" in x for x in ref), str(ref))
    arm("J5 every verdict line names what it certifies and what it does not (D7)",
        all("certified:" in x for x in ref + ok) and all("NOT certified" in x for x in ref[:1] + ok), str(ref + ok))

    if not (REPO / ".git").exists():
        print("  ○ J6 not run: this tree has no .git (an extract), so it has no sha to extract")
    else:
        with tempfile.TemporaryDirectory() as td:
            sha = git(REPO, "rev-parse", "HEAD")
            ext = lj.inv_keys(lj.extract(REPO, sha, Path(td) / "x"), REPO)
            tracked = set(git(REPO, "ls-files").split())
            live = {k for k in lj.inv_keys(REPO, REPO) if k.split("::", 1)[0] in tracked}
            arm(f"J6 inv(HEAD) from the extract equals this checkout's inventory on tracked files ({len(ext)} sites)",
                ext == live and len(ext) > 100, f"extract-only {sorted(ext - live)[:3]} live-only {sorted(live - ext)[:3]}")

    print(("PASS: sqlguard land judge" if not fails else f"FAIL: {len(fails)} arm(s)") + " (0 failing)" * (not fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
