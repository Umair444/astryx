"""Mutants for devtools/sqlsite.sh (seed #56477). The oracle is tests/test_sqlsite.py, which runs SQLSITE_SRC in place
of the real script. Each oracle run drives the late-replies oracle three times (~90 s), so TIMEOUT is raised."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "devtools" / "sqlsite.sh"
ORACLE = REPO / "tests" / "test_sqlsite.py"
ENV = "SQLSITE_SRC"
TIMEOUT = 400
MUTANTS = {
    "S1 the prefix filter is dropped (every site and every ledger row is 'mine')":
        ("mine = lambda k: any(k.startswith(p) for p in args)", "mine = lambda k: True"),
    "S2 R-STALE absent is suppressed (a re-texted key goes unseen)":
        ("    if mine(lk) and lk not in live:", "    if False:"),
    "S3 a listed site that climbed reads ok (no shrink asked)":
        ("v = \"R-STALE\" if listed and not lo", "v = \"ok\" if listed and not lo"),
    "S4 the oracle inherits ASTRYX_AGENT":
        ("rc=0; env -u ASTRYX_AGENT \"$PY\" \"$T\"", "rc=0; \"$PY\" \"$T\""),
    "S5 the registration warning is never printed":
        ("if [ \"$LEDGER_MODE\" = 1 ] && ! command grep", "if false && ! command grep"),
    "S6 a failing oracle's grades read as evidence":
        ("[ \"$rc\" = 0 ] || { echo \"test FAILED", "true || { echo \"test FAILED"),
    "S7 a live-only RESPONSIVE site that is unlisted reads R-NEW (the a4 #56606 drift)":
        ("        v = \"R-STALE\" if listed and not lo else \"ok\"",
         "        v = \"R-STALE\" if listed and not lo else \"R-NEW\" if lo and not listed else \"ok\""),
    "S8 NOT SEARCHED is graded like any rung below RESPONSIVE":
        ("    elif s[\"rung\"] == \"NOT SEARCHED\":", "    elif False:"),
    "S9 the registration check matches a comment mention":
        ("command grep -E '^[[:space:]]*run ' devtools/check.sh |", "cat devtools/check.sh |"),
}
