"""Authored mutants for devtools/referral_guard.sh (plan-10224 S2F, seed #61794): each puts back the pipe-into-grep -q
shape that under pipefail passed on SIGPIPE, or drops a check. Every one must be CAUGHT by tests/test_referral_guard.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_referral_guard.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "devtools" / "referral_guard.sh"
ORACLE = REPO / "tests" / "test_referral_guard.py"
ENV = "REFERRAL_GUARD_SRC"

MUTANTS = {
    "G1 (a) pipes its captured output into grep -q again (a leaked referral passes on SIGPIPE)":
        ("if grep -qi 'referral' <<<\"$out\"; then", "if printf '%s' \"$out\" | grep -qi 'referral'; then"),
    "G2 (c) pipes the referral lines into grep -q again (a curl'd id passes on SIGPIPE)":
        ("if grep -qE 'curl|wget|\\$\\(|`' <<<\"$(grep -niE 'referral' init.sh)\"; then",
         "if grep -niE 'referral' init.sh | grep -qE 'curl|wget|\\$\\(|`'; then"),
    "G3 (a) is gone: a referral on the non-TTY path is never looked for":
        ("if grep -qi 'referral' <<<\"$out\"; then", "if false; then"),
}
