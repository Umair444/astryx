"""Oracle for devtools/referral_guard.sh (plan-19's CI guard: the maintainer referral stays OPT-IN and STATIC).

The guard runs under `set -o pipefail`, and two of its checks piped a producer into `grep -q`. grep -q exits at its
first match and the producer takes SIGPIPE writing the rest, so pipefail reads the MATCH as a failure: on a big enough
producer the guard printed ✓ for exactly the case it exists to refuse, fail OPEN (plan-10224 S2F, seed #61794). Each
arm runs the guard against a fixture tree (its own copy of the script and an init.sh), the producer ~1 MB with the
offending line FIRST, three times, because the pipe form failed by timing.

    venv/bin/python tests/test_referral_guard.py      (REFERRAL_GUARD_SRC: mutation_probe's channel)
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("REFERRAL_GUARD_SRC") or REPO / "devtools" / "referral_guard.sh")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


QUIET = 'referral_optin() {\n  [ -t 0 ] || return 0\n  say "referral: $REFERRAL_ID"\n}\n'
LEAKY = ('referral_optin() {\n  say "referral: $REFERRAL_ID (shown on a NON-TTY path)"\n'
         '  for i in $(seq 1 60000); do say "filler line $i of the opt-in text"; done\n}\n')
FETCH = ('REFERRAL_URL=$(curl -s https://example.invalid/referral)\n'
         + "".join(f"# referral note {i}: harmless text that names the referral\n" for i in range(60000)))


def guard(init_sh):
    """rc and output of the guard run in a fixture tree whose init.sh is `init_sh`."""
    t = Path(tempfile.mkdtemp(prefix="refguard-"))
    try:
        (t / "devtools").mkdir()
        shutil.copy(SRC, t / "devtools" / "referral_guard.sh")
        (t / "init.sh").write_text(init_sh)
        p = subprocess.run(["bash", str(t / "devtools" / "referral_guard.sh")], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120)
        return p.returncode, p.stdout + p.stderr
    finally:
        shutil.rmtree(t, ignore_errors=True)


def main():
    rc, out = guard((REPO / "init.sh").read_text())
    check("control: the real init.sh PASSes (rc 0, all three checks ✓)", rc == 0 and out.count("  ✓ ") == 3, out)
    base = '#!/usr/bin/env bash\nREFERRAL_ID="TESTCODE"\n'
    rc, out = guard(base + QUIET)
    check("control: a TTY-gated opt-in with a static id PASSes", rc == 0 and "referral-guard: PASS" in out, out)

    runs = [guard(base + LEAKY) for _ in range(3)]
    check("(a) a referral shown on the NON-TTY path FAILs, 3 of 3, with ~1 MB after the leaked line (no SIGPIPE pass)",
          all(rc == 1 and "referral appeared on the non-interactive path" in out for rc, out in runs),
          "; ".join(f"rc {rc}" for rc, _ in runs))
    runs = [guard(base + QUIET + FETCH) for _ in range(3)]
    check("(c) a referral line that FETCHES (curl) FAILs, 3 of 3, with 60000 referral lines after it",
          all(rc == 1 and "a referral line fetches its id/url at runtime" in out for rc, out in runs),
          "; ".join(f"rc {rc}" for rc, _ in runs))
    rc, out = guard('#!/usr/bin/env bash\nREFERRAL_ID="$(curl -s x)"\n' + QUIET)
    check("(b) a templated id FAILs", rc == 1 and "REFERRAL_ID is not a static quoted literal" in out, out)
    print(f"\n{'FAIL' if fails else 'PASS'}: referral_guard ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
