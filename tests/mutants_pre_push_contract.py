"""Authored mutants for hooks/pre-push — run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_pre_push_contract.py

THE LIST IS THE JUDGEMENT, WHICH IS WHY IT IS AUTHORED. Each entry is a one-line edit that
leaves the hook running, silent, and green-looking while a guarantee it exists for is gone.
That is the whole hazard class here: a pre-push hook reports nothing on the happy path, so
every mutation below is INVISIBLE AT THE PROMPT — you find out from a machine that is not
yours, days later, in the shape of "CI is broken" or a leak that already shipped.

M1 and M3 are the two directions of steward's 2026-08-16 push-window ruling; M2 is the
pre-hardening body itself, which was live until that same evening.

NOT A CLAIM OF COMPLETENESS. Coverage is bounded by this list; the probe reports CAUGHT or
NOT PROBED, never "vacuous". Unlike the guard estate under `triggers/`, this subject is
TRACKED, so a clean checkout carries it and these mutants run anywhere the repo does.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "hooks" / "pre-push"
ORACLE = REPO / "tests" / "test_pre_push_contract.py"
ENV = "PRE_PUSH_SRC"

MUTANTS = {
    # Fail-safe polarity inverted. 77 means VERIFIED NOTHING — no temp dir, not a repo, no
    # check.sh at that ref — and treating it as a failure hands a missing /tmp the power to
    # stop the org pushing. The damage is not the blocked push, it is the first time
    # someone reaches for --no-verify and finds that it works.
    "M1 a 77 (VERIFIED NOTHING) blocks instead of warning":
        ('    77) echo "pre-push: pushed-tree check VERIFIED NOTHING for $sha (exit 77) — allowing"',
         '    999) echo "pre-push: pushed-tree check VERIFIED NOTHING for $sha (exit 77) — allowing"'),

    # The pre-hardening body, reconstructed by starving the capture. Every push then checks
    # HEAD regardless of what is being pushed — which on this single-branch org is usually
    # the same commit, so it is right often enough to never look wrong.
    "M2 refs never captured — every push silently checks HEAD":
        ('refs_in="$(cat)"', 'refs_in=""'),

    # A red pushed tree is recorded and then discarded. The check runs, prints its failure,
    # and the push proceeds: the most expensive possible way to have no gate at all.
    "M3 a red pushed-tree check no longer blocks":
        ("    *)  rc=1 ;;", "    *)  rc=0 ;;"),

    # The privacy gate becomes advisory. This is the 07-27 leak class un-gated — and the
    # one mutation here whose damage is irreversible, since a pushed value is public.
    "M4 a red privacy gate no longer blocks":
        ('"$REPO/nucleus/privacy_gate.sh" || exit 1',
         '"$REPO/nucleus/privacy_gate.sh" || true'),

    # Dedup broken: one sha pushed to two refs pays the window twice. Not a correctness
    # hole — a latency one, and latency is exactly what nearly kept this gate unwired.
    "M5 dedup disabled — the same sha is checked once per ref":
        ('  case " $refs " in *" $local_sha "*) continue ;; esac',
         '  case " $refs " in *" __never__ "*) continue ;; esac'),

    # The all-zero deletion sentinel stops being recognised, so a branch deletion sends a
    # sha of forty zeros into the tree check — which cannot resolve it, exits nonzero, and
    # blocks a push that has no tree to object to.
    "M6 a branch deletion is checked as if it were a commit":
        ('    ""|0000000000000000000000000000000000000000) continue ;;',
         '    "") continue ;;'),
}
