#!/usr/bin/env python3
"""Oracle: the INSTALLED pre-push hook is the one that was reviewed, and it can actually run.

    venv/bin/python nucleus/test_hook_integrity.py     (also run by nucleus/check.sh)

WHY (steward, msg 9585). `.git/hooks/pre-push` is a COPY of the tracked `hooks/pre-push`,
not a symlink, and until now NOTHING compared them. They agree today — I md5'd both — but a
gate whose installed copy can drift from its reviewed source is the systemd-symlink footgun
in a different costume: the reviewed artifact and the executed artifact are two writers of
one fact, with no reconciler. The hook's own header worries about exactly this class for
privacy_gate, which is the guarantee already riding on that copy.

This closes it for EVERY guarantee on the hook at once, which is why it is worth a
sub-second gate in check.sh rather than one assert per guard.

THE THREE WAYS THIS FILE'S SUBJECT FAILS, and the third is the one a checksum misses —
EXISTENCE IS NOT EXECUTION (abstractor-1's M4, 2026-08-14: a live `run` line wrapped in
`if false; then … fi` is a line that exists and a gate that never runs):
  * the installed copy is ABSENT      -> nothing gates the push. Skip loudly (77): a fresh
                                         clone or CI legitimately has no hook installed, and
                                         a hard fail there is what killed test_tier.py.
  * the installed copy DIFFERS        -> what runs is not what was reviewed. FAIL.
  * the installed copy is NOT EXECUTABLE -> git skips it silently. Byte-identical and inert:
                                         a checksum alone reports GREEN on a dead gate.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRACKED = REPO / "hooks" / "pre-push"
EXIT_SKIP = 77
fails = []


def digest(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        if detail:
            print(f"        {detail}")
        fails.append(name)


# The hooks DIRECTORY is configurable; resolve it rather than assuming .git/hooks, or this
# oracle checks a path git is not using and reports green about the wrong file.
try:
    top = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=REPO,
                         capture_output=True, text=True, timeout=10)
    hooks_dir = Path(top.stdout.strip() or ".git/hooks")
    if not hooks_dir.is_absolute():
        hooks_dir = REPO / hooks_dir
except Exception as exc:
    print(f"SKIP: git could not resolve the hooks path ({type(exc).__name__}). "
          f"Nothing was verified here.")
    sys.exit(EXIT_SKIP)

INSTALLED = hooks_dir / "pre-push"

if not TRACKED.exists():
    print(f"SKIP: {TRACKED.relative_to(REPO)} is not present. Nothing was verified here.")
    sys.exit(EXIT_SKIP)

if not INSTALLED.exists():
    # A fresh clone / CI runner has no hook installed. That is a real and expected state,
    # and it is NOT a pass: this run verified nothing about what gates a push here.
    print(f"SKIP: no hook installed at {INSTALLED} (a fresh clone or CI has none). "
          f"Nothing was verified here — on a dev machine this means NOTHING gates a push.")
    sys.exit(EXIT_SKIP)

print("the installed pre-push hook is the reviewed one, and can run:")
check("installed copy matches the tracked source byte for byte",
      digest(INSTALLED) == digest(TRACKED),
      f"tracked {digest(TRACKED)} != installed {digest(INSTALLED)} — what runs on push is "
      f"NOT what was reviewed. Re-copy hooks/pre-push over {INSTALLED}.")
check("installed copy is executable (git skips a non-executable hook SILENTLY)",
      os.access(INSTALLED, os.X_OK),
      f"{INSTALLED} is not executable — byte-identical and inert. chmod +x it.")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
