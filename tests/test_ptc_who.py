"""devtools/pushed_tree_check.sh's red epilogue, WHO LAST TOUCHED EACH FAILING GATE (a4 10-25).

It names, for each gate in check.sh's OWN FAILED block, the script its `run` line names and that script's last commit
on the ref. Hermetic: a throwaway repo whose devtools/check.sh is a stub printing check.sh's shapes, copied from its
printer (verdict(): leading echo, FAILED (n): + "  ✗ " items, UNVERIFIED, echo, the sqlguard settle line, check:).
Arms:
  W1  a gate's own "FAILED (1):" / "  ✗ " lines are never listed (only check.sh's trailing block: a1 #62905)
  W2  a label's script is the first PATH word of its run line (tests/…), with its last commit on the ref
  W3  a `-m a.b.c` run line maps to src/a/b/c.py
  W4  a label holding a `"` (check.sh source writes \\") still finds its run line
  W5  check.sh's OWN suffix on a FAILED entry (" (TIMED OUT after Ns)", check.sh's run()) still maps, also when the
      label itself ends in "(…)" (a1 #62937)
  W6  a parser that can't answer prints one line saying so; the list never silently vanishes (a1 #62937)
  W7  a parser that answers (rc 0) but warns on stderr: the warning is never listed as a gate (a4 residue of #62937)
  C1  control: a green stub prints no WHO block
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = os.environ.get("PTC_SRC") or str(REPO / "devtools" / "pushed_tree_check.sh")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail[-1500:]}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


ENV = {**{k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "ASTRYX_", "PG")) and not k.endswith("_DSN")},
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
       "ASTRYX_COG_REGISTRY": "/nonexistent/cog.json"}   # the pin the ASTRYX_ filter dropped: a registry naming no file
CHECK = r'''#!/usr/bin/env bash
# the gates' own output first: a gate that prints check.sh's exact shapes about ITS subject
echo 'FAILED (1):'
echo '  ✗ a gate injected this'
cat <<'GATES' >/dev/null
run "alpha: the first gate" "$PY" tests/test_alpha.py
run "beta: a module gate" "$PY" -m astryx.beta.gate "$D"
run "gamma: says \"hi\"" bash tests/test_gamma.sh
run "delta: a slow gate (plan-1 S2)" "$PY" tests/test_delta.py
GATES
[ -f GREEN ] && { echo; echo; echo 'check: ALL CODE INVARIANTS PASS (3 gates verified)'; exit 0; }
echo
echo 'FAILED (4):'
echo '  ✗ alpha: the first gate'
echo '  ✗ beta: a module gate'
echo '  ✗ gamma: says "hi"'
echo '  ✗ delta: a slow gate (plan-1 S2) (TIMED OUT after 600s)'
echo
echo 'sqlguard traces kept (red verdict): /tmp/sqlguard.X'
echo 'check: FAILURES above — a committed invariant regressed'
exit 1
'''


def main():
    with tempfile.TemporaryDirectory(prefix="ptc-who-") as t:
        r = Path(t) / "r"

        def git(*a):
            return subprocess.run(["git", *a], cwd=r, env=ENV, capture_output=True, text=True, check=True).stdout.strip()

        (r / "devtools").mkdir(parents=True)
        (r / "tests").mkdir()
        (r / "src" / "astryx" / "beta").mkdir(parents=True)
        (r / "devtools" / "check.sh").write_text(CHECK)
        (r / "devtools" / "check_verdict.py").write_text((REPO / "devtools" / "check_verdict.py").read_text())
        git("init", "-q", "-b", "main")
        git("add", "."); git("commit", "-qm", "base")
        for f, msg in (("tests/test_alpha.py", "alpha lands"), ("src/astryx/beta/gate.py", "beta lands"),
                       ("tests/test_gamma.sh", "gamma lands"), ("tests/test_delta.py", "delta lands")):
            (r / f).write_text("x\n"); git("add", f); git("commit", "-qm", msg)
        last = {m: git("log", "-1", "--format=%h", "--", f) for f, m in (("tests/test_alpha.py", "a"),
                                                                       ("src/astryx/beta/gate.py", "b"),
                                                                       ("tests/test_gamma.sh", "g"),
                                                                       ("tests/test_delta.py", "d"))}

        def ptc():
            p = subprocess.run(["bash", SRC, "HEAD"], cwd=r, env={**ENV, "PY": sys.executable}, capture_output=True,
                               text=True, timeout=120)
            return p.returncode, p.stdout + p.stderr

        rc, out = ptc()
        who = out.split("WHO LAST TOUCHED", 1)[1] if "WHO LAST TOUCHED" in out else ""
        check("red: the WHO block is printed", rc == 1 and bool(who), out)
        check("W1 a gate's own ✗ line is never listed", "a gate injected this" not in who, who)
        check("W2 a tests/ run line maps to its script and its last commit on the ref",
              "      tests/test_alpha.py" in who and f"{last['a']}  t  alpha lands" in who, who)
        check("W3 a `-m a.b.c` run line maps to src/a/b/c.py",
              "      src/astryx/beta/gate.py" in who and f"{last['b']}  t  beta lands" in who, who)
        check('W4 a label holding " finds its run line (source writes \\")',
              "      tests/test_gamma.sh" in who and f"{last['g']}  t  gamma lands" in who, who)
        check("W5 an entry with check.sh's TIMED OUT suffix, on a label ending in (…), maps to its script",
              "      tests/test_delta.py" in who and f"{last['d']}  t  delta lands" in who, who)
        check("no gate reads 'could not map'", "could not map" not in who, who)
        good = (r / "devtools" / "check_verdict.py").read_text()
        (r / "devtools" / "check_verdict.py").write_text("raise SystemExit('parser broke')\n")   # the pusher's copy
        rc, out = ptc()
        check("W6 a parser that can't answer is SAID (one line, its rc), never a silently missing list",
              rc == 1 and "could not read the FAILED block (check_verdict.py rc 1): parser broke" in out, out)
        (r / "devtools" / "check_verdict.py").write_text(   # a parser that answers rc 0 AND warns on stderr
            "import sys; print('SomeWarning: noise on stderr', file=sys.stderr)\n" + good)
        rc, out = ptc()
        who = out.split("WHO LAST TOUCHED", 1)[1] if "WHO LAST TOUCHED" in out else ""
        check("W7 a parser's stderr on rc 0 is never listed as a failing gate",
              rc == 1 and "SomeWarning" not in who and "      tests/test_alpha.py" in who, who)
        (r / "devtools" / "check_verdict.py").write_text(good)
        (r / "GREEN").write_text(""); git("add", "GREEN"); git("commit", "-qm", "green")
        rc, out = ptc()
        check("C1 control: a green run prints no WHO block", rc == 0 and "WHO LAST TOUCHED" not in out, out)
    print(f"\n{'FAIL' if fails else 'PASS'}: pushed_tree_check WHO block ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
