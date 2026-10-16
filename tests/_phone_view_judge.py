"""Did test_phone_view's arms RUN? The judgment test_phone_view_ci.py applies to one run (rc, output).

It ran when rc is 0, or rc is 77 with its own "NOT VERIFIED: <labels> (every other arm passed)" line naming only
HOST-BOUND arms. A host-bound arm needs something no committed tree can carry, so a CI runner may lack it; any other
arm unverified, an import-time exit, a deps skip or a FAIL is RED. The set is DECLARED here, not read from the
subject: a new unverified arm must be argued into it (seed #55544: the 3.12 runner had no snapper).
"""
import re

HOST_BOUND = {
    "B4 snapper": "the host's snapper configs and findmnt (a runner has neither)",
    "B5 live": "the running observatory service, a running Hands desktop and the host's OBS_KEY",
}
LINE = re.compile(r"^NOT VERIFIED: (.+) \(every other arm passed\)$", re.M)


def ran(rc: int, out: str) -> tuple[bool, str]:
    """(it ran, why)."""
    if rc == 0:
        return True, "rc 0"
    if rc != 77:
        return False, f"rc {rc}"
    m = LINE.search(out)
    if not m:
        return False, "rc 77 without its NOT VERIFIED line (a skip before the arms)"
    skipped = set(m.group(1).split(", "))
    other = sorted(skipped - set(HOST_BOUND))
    if other:
        return False, f"rc 77 with a non-host arm unverified: {', '.join(other)}"
    return True, f"rc 77, host-bound only: {', '.join(sorted(skipped))}"
