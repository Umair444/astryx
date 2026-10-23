"""Authored mutants for observatory/front.py's sign-in cost bound (plan-11859 U1U2-F, seed #62578). Every one must be
CAUGHT by tests/test_signin_burst.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_signin_burst.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "observatory" / "front.py"
ORACLE = REPO / "tests" / "test_signin_burst.py"
ENV = "OBS_FRONT_SRC"

MUTANTS = {
    "W1 the checks run on asyncio's default pool (unbounded by the sign-in's own two)":
        ("        got = await cogauth.sign_in(a.db, email, pw, check=_check)", "        got = await cogauth.sign_in(a.db, email, pw)"),
    "W2 no in-flight cap: every sign-in waits for a check, none is refused busy":
        ("    if _inflight >= INFLIGHT:", "    if False:"),
    "W3 an attempt counts only once it has FAILED (a concurrent burst passes the limit before any is counted)":
        ("    now = time.monotonic()\n    _fails[ck].append(now)\n    _fails[ak].append(now)\n    _inflight += 1\n",
         "    now = time.monotonic()\n    _inflight += 1\n"),
    "W4 the executor runs more checks at once":
        ("CHECKS, INFLIGHT = 2, 8", "CHECKS, INFLIGHT = 8, 8"),
}
