#!/usr/bin/env python3
"""Oracle: the pre-push hook BEHAVES the way it was reviewed to behave.

    venv/bin/python tests/test_pre_push_contract.py     (also run by nucleus/check.sh)

WHY THIS EXISTS BESIDE test_hook_integrity.py, WHICH ALREADY GUARDS THIS FILE.
That oracle proves the INSTALLED copy is byte-identical to the TRACKED source and
executable. Both facts are about the hook's conformance TO ITSELF: edit the tracked file
to drop a gate, re-run init.sh, and integrity stays green forever while the push window
covers nothing. A checksum cannot tell a reviewed hook from a gutted one — it only tells
you the two copies agree. This file is the INDEPENDENT declaration of what the hook must
DO, so the pair covers both halves: integrity says "what runs is what was reviewed", this
says "what was reviewed does the job".

HERMETIC. Every case builds a throwaway git repo, drops the REAL tracked hook body into
it, and puts STUBS at nucleus/privacy_gate.sh and nucleus/pushed_tree_check.sh that log
their argv and exit on demand. Nothing here clones, pushes, or touches the live repo, and
the whole file runs in well under a second — the reason it can sit in check.sh at all.

That stub placement also proves something a static scan can only guess at: the hook really
does invoke THOSE TWO PATHS. abstractor-4's reachability gate false-accused
pushed_tree_check.sh minutes after it was wired (2026-08-16), because the invocation is a
quoted, variable-prefixed command word that its parser did not recognise as a command
position. A parser has to model every spelling of "run this"; a stub that gets called has
to model none.

THE CONTRACT, each line a way this hook has been or could be silently wrong:
  * a red privacy gate BLOCKS, and the expensive gate never runs (cheapest, highest
    stakes, first — and a fail-fast that stops paying 7s once the push is already dead)
  * the shas checked are the ones on STDIN, not HEAD. A hook that checks the wrong commit
    is indistinguishable, in its output, from one that works
  * ...even if a gate ahead of it eats stdin. The refs are captured before any child runs
  * a branch DELETION has no tree; an empty stdin (run by hand) means HEAD
  * exit 77 from the tree check WARNS AND ALLOWS (steward's ruling, 2026-08-16): fail-safe
    polarity for a detector whose subject is the environment. A missing /tmp must never
    stop the org pushing, and a gate that blocks on it trains people to --no-verify
  * a red tree check BLOCKS, and every pushed sha is checked even after one goes red
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRACKED = Path(os.environ.get("PRE_PUSH_SRC") or (REPO / "hooks" / "pre-push"))
EXIT_SKIP = 77
ZERO = "0" * 40
SHA_A = "a" * 40
SHA_B = "b" * 40
fails = []

STUB_PRIVACY = """#!/bin/sh
echo "privacy" >> "$STUB_LOG"
[ -n "${STUB_PRIVACY_SLURP:-}" ] && cat > /dev/null
exit ${STUB_PRIVACY_RC:-0}
"""

# Per-sha exit codes come from a file rather than the environment so a case can make one
# sha red and another green in the same run — the "does it keep checking after a red one"
# assertion needs exactly that.
STUB_TREE = """#!/bin/sh
echo "tree $1" >> "$STUB_LOG"
rc="${STUB_TREE_RC:-0}"
if [ -f "$STUB_RCMAP" ]; then
  while read -r s r; do
    [ "$s" = "$1" ] && rc="$r"
  done < "$STUB_RCMAP"
fi
exit "$rc"
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        if detail:
            print(f"        {detail}")
        fails.append(name)


def run_hook(stdin_text, privacy_rc=0, tree_rc=0, rcmap=None, slurp=False):
    """Run the tracked hook against stubbed gates. Returns (rc, stdout, [calls])."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True,
                       capture_output=True, timeout=30)
        (tmp / "nucleus").mkdir()
        for name, body in (("privacy_gate.sh", STUB_PRIVACY),
                           ("pushed_tree_check.sh", STUB_TREE)):
            p = tmp / "nucleus" / name
            p.write_text(body)
            p.chmod(0o755)
        hook = tmp / "pre-push"
        hook.write_text(TRACKED.read_text())
        log = tmp / "calls.log"
        rcmap_path = tmp / "rcmap"
        if rcmap:
            rcmap_path.write_text("".join(f"{s} {r}\n" for s, r in rcmap.items()))
        env = dict(os.environ,
                   STUB_LOG=str(log), STUB_RCMAP=str(rcmap_path),
                   STUB_PRIVACY_RC=str(privacy_rc), STUB_TREE_RC=str(tree_rc))
        if slurp:
            env["STUB_PRIVACY_SLURP"] = "1"
        proc = subprocess.run(["sh", str(hook), "origin", "git@example.invalid:x.git"],
                              cwd=tmp, input=stdin_text, text=True,
                              capture_output=True, timeout=60, env=env)
        calls = log.read_text().split("\n") if log.exists() else []
        return proc.returncode, proc.stdout + proc.stderr, [c for c in calls if c]


def line(sha, ref="refs/heads/main"):
    return f"{ref} {sha} {ref} {ZERO}\n"


if not TRACKED.exists():
    print(f"SKIP: {TRACKED} is not present. Nothing was verified here.")
    sys.exit(EXIT_SKIP)
if not (REPO / ".git").exists() and "PRE_PUSH_SRC" not in os.environ:
    print("SKIP: not a git checkout. Nothing was verified here.")
    sys.exit(EXIT_SKIP)

print("the pre-push hook does what it was reviewed to do:")

rc, out, calls = run_hook(line(SHA_A))
check("a clean push exits 0 and runs both gates",
      rc == 0 and calls == ["privacy", f"tree {SHA_A}"], f"rc={rc} calls={calls}")

check("the sha checked is the one being PUSHED, not HEAD",
      calls == ["privacy", f"tree {SHA_A}"] and "HEAD" not in " ".join(calls),
      f"calls={calls}")

rc, out, calls = run_hook(line(SHA_A), privacy_rc=1)
check("a red privacy gate BLOCKS the push",
      rc != 0, f"rc={rc} — a personal-tier leak would have been pushed")
check("a red privacy gate short-circuits: the expensive gate never runs",
      calls == ["privacy"], f"calls={calls}")

rc, out, calls = run_hook(line(SHA_A), tree_rc=1)
check("a red pushed-tree check BLOCKS the push",
      rc != 0, f"rc={rc} — a tree that is red on every other machine would have gone out")

rc, out, calls = run_hook(line(SHA_A), tree_rc=77)
check("exit 77 (VERIFIED NOTHING) ALLOWS the push — fail-safe polarity",
      rc == 0, f"rc={rc} — a missing temp dir must not be able to stop the org pushing")
check("...and says so out loud, naming the sha it proved nothing about",
      "77" in out and SHA_A in out, f"out={out.strip()!r}")

rc, out, calls = run_hook(line(SHA_A) + line(SHA_B, "refs/heads/other"),
                          rcmap={SHA_A: 1, SHA_B: 0})
check("every pushed sha is checked even after one goes red",
      calls == ["privacy", f"tree {SHA_A}", f"tree {SHA_B}"], f"calls={calls}")
check("...and the push still BLOCKS",
      rc != 0, f"rc={rc}")

rc, out, calls = run_hook(line(SHA_A) + line(SHA_A, "refs/heads/dup"))
check("the same sha pushed to two refs is checked once",
      calls == ["privacy", f"tree {SHA_A}"], f"calls={calls}")

rc, out, calls = run_hook(line(ZERO))
check("a branch DELETION has no tree, so nothing is checked (and the push proceeds)",
      rc == 0 and calls == ["privacy"], f"rc={rc} calls={calls}")

rc, out, calls = run_hook("")
check("nothing on stdin = run by hand -> HEAD",
      calls == ["privacy", "tree HEAD"], f"calls={calls}")

# The hardening. Before 2026-08-16 the hook read stdin AFTER calling privacy_gate.sh, so a
# gate that consumed stdin would leave the loop with nothing to read; the hook would fall
# back to HEAD and report a healthy, entirely irrelevant check. Nothing in the output would
# differ. This is the assertion that fails on the old body.
rc, out, calls = run_hook(line(SHA_A), slurp=True)
check("a gate that eats stdin cannot repoint what gets checked",
      calls == ["privacy", f"tree {SHA_A}"],
      f"calls={calls} — the ref list was consumed upstream and the check silently "
      f"retargeted; a push would report green about a commit nobody is pushing")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
