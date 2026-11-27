"""devtools/pushed_tree_check.sh's PTC_BASELINE mode: a red INHERITED from the baseline doesn't block, a NEW one does.

A PR branch cut from a red base inherits that base's reds, so the pre-push gate refused every PR branch for gates it
never touched (medic, 11-13). With PTC_BASELINE=<ref> named at push time, the same check runs on the baseline and only
a gate red on the pushed ref and green on the baseline keeps it red. Hermetic: a throwaway repo whose devtools/check.sh
is a stub printing check.sh's FAILED shapes, failing one gate per RED_<gate> file in the tree.
  B1  inherited only: the branch's one red is red on the baseline too → allowed (rc 0), said so
  B2  a NEW red (green on the baseline) → still RED (rc 1), named; the inherited one is not listed as new
  B3  no PTC_BASELINE → unchanged: the inherited red still blocks (the mode is opt-in)
  B4  a baseline that can't be checked (no such ref → 77) → still RED (fail-closed)
  B5  a baseline whose verdict can't be parsed → still RED (fail-closed)
  B6  the baseline is the pushed ref itself → still RED (seed #11604: else every red reads "inherited")
  B7  the baseline is a red ref that is NOT an ancestor of the pushed one → still RED
  B8  a remote-tracking baseline name (origin/main) is checked as THIS repo resolves it, not as the clone does
      (inside the clone `origin/main` is this repo's main: a red main there made a new red read "inherited")
  C1  control: a green ref never runs the baseline
Run: venv/bin/python tests/test_ptc_baseline.py   (also wired into devtools/check.sh)
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


ENV = {**{k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "ASTRYX_", "PG", "PTC_"))
          and not k.endswith("_DSN")},
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
       "ASTRYX_COG_REGISTRY": "/nonexistent/cog.json"}
CHECK = r'''#!/usr/bin/env bash
reds=$(ls RED_* 2>/dev/null | sed 's/^RED_//')
[ -z "$reds" ] && { echo; echo 'check: ALL CODE INVARIANTS PASS (2 gates verified)'; exit 0; }
echo
echo "FAILED ($(wc -w <<<"$reds")):"
for g in $reds; do echo "  ✗ $g: a gate"; done
echo
echo 'check: FAILURES above — a committed invariant regressed'
exit 1
'''


def main():
    with tempfile.TemporaryDirectory(prefix="ptc-base-") as t:
        r = Path(t) / "r"

        def git(*a):
            return subprocess.run(["git", *a], cwd=r, env=ENV, capture_output=True, text=True, check=True).stdout.strip()

        (r / "devtools").mkdir(parents=True)
        (r / "devtools" / "check.sh").write_text(CHECK)
        (r / "devtools" / "check_verdict.py").write_text((REPO / "devtools" / "check_verdict.py").read_text())
        (r / "RED_alpha").write_text("")
        git("init", "-q", "-b", "main")
        git("add", "."); git("commit", "-qm", "base: alpha is red")
        git("tag", "base")
        (r / "fix.txt").write_text("a fix\n"); git("add", "fix.txt"); git("commit", "-qm", "a fix touching no gate")
        git("tag", "inherits")
        (r / "RED_beta").write_text(""); git("add", "RED_beta"); git("commit", "-qm", "breaks beta")
        git("tag", "breaks")

        def ptc(ref, baseline=None):
            env = {**ENV, "PY": sys.executable, **({"PTC_BASELINE": baseline} if baseline is not None else {})}
            p = subprocess.run(["bash", SRC, ref], cwd=r, env=env, capture_output=True, text=True, timeout=120)
            return p.returncode, p.stdout + p.stderr

        rc, out = ptc("inherits", "base")
        check("B1 an inherited red only: allowed (rc 0) and said so", rc == 0 and "inherited, none new" in out, out)
        rc, out = ptc("breaks", "base")
        new = out.split("NEW reds", 1)[1] if "NEW reds" in out else ""
        check("B2 a NEW red stays RED and is named; the inherited one is not called new",
              rc == 1 and "beta: a gate" in new and "alpha: a gate" not in new, out)
        rc, out = ptc("inherits")
        check("B3 no PTC_BASELINE: the inherited red still blocks (opt-in)", rc == 1 and "PTC_BASELINE" not in out, out)
        rc, out = ptc("inherits", "no-such-ref")
        check("B4 a baseline that can't be checked: still RED", rc == 1 and "still RED" in out, out)
        good = (r / "devtools" / "check_verdict.py").read_text()
        (r / "devtools" / "check_verdict.py").write_text("raise SystemExit('parser broke')\n")
        rc, out = ptc("inherits", "base")
        check("B5 a baseline verdict that can't be parsed: still RED", rc == 1 and "inherited, none new" not in out, out)
        (r / "devtools" / "check_verdict.py").write_text(good)
        rc, out = ptc("breaks", "breaks")
        check("B6 the baseline is the pushed ref itself: still RED", rc == 1 and "not a strict ancestor" in out, out)
        git("checkout", "-q", "-b", "side", "base"); (r / "RED_beta").write_text(""); (r / "RED_gamma").write_text("")
        git("add", "."); git("commit", "-qm", "an unrelated ref, red on more")
        rc, out = ptc("breaks", "side")
        check("B7 a red ref that is not an ancestor: still RED", rc == 1 and "not a strict ancestor" in out, out)
        git("update-ref", "refs/remotes/origin/main", git("rev-parse", "base"))   # origin/main = base HERE
        git("branch", "-f", "main", "side")                                    # …while this repo's main is red on more
        rc, out = ptc("breaks", "origin/main")
        check("B8 origin/main is the baseline THIS repo means (base), not the clone's (its main): a new red stays RED",
              rc == 1 and "NEW reds" in out and "beta: a gate" in out.split("NEW reds", 1)[1], out)
        rc, out = ptc("inherits", "base")
        check("B1' an allowed push names the gates it did NOT re-verify",
              rc == 0 and "NOT re-verified" in out and "alpha: a gate" in out.split("NOT re-verified", 1)[1], out)
        git("checkout", "-q", "base"); git("rm", "-q", "RED_alpha"); git("commit", "-qm", "green")
        rc, out = ptc("HEAD", "base")
        check("C1 control: a green ref never runs the baseline", rc == 0 and "checking the baseline" not in out, out)
    print(f"\n{'FAIL' if fails else 'PASS'}: pushed_tree_check PTC_BASELINE ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
