"""Mutants for the S1b-2b door half, src/astryx/security/release.py (plan-9139): ways ingress and the read rule could
fail OPEN. The oracle is tests/test_release_ingress.py. The bridge half's mutants: tests/mutants_bridge_ingress.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "src" / "astryx" / "security" / "release.py"
ORACLE = REPO / "tests" / "test_release_ingress.py"
ENV = "RELEASE_SRC"
MUTANTS = {
    "I1 the read rule is 'any label', not 'its tiers within the label'":
        ("    if not lbl or not tiers <= lbl:\n", "    if not lbl:\n"),
    "I2 the read rule is equality, not subset (a wider member can't read its own tier)":
        ("    if not lbl or not tiers <= lbl:\n", "    if not lbl or tiers != lbl:\n"),
    "I3 read_for drops the body MAC check":
        ("    if not hmac.compare_digest(body_mac(key, body), str(bmac)):\n        raise Refused(\"the resolved body is "
         "not the body the row names\")\n", ""),
    "I4 a look-alike tier key reads as untiered":
        ("    if odd:\n        raise GrantError", "    if False:\n        raise GrantError"),
    "I5 an undeclared tier value is accepted":
        ("    if t not in TIERS:\n        raise GrantError(f\"the route declares", "    if False:\n        raise GrantError(f\"the route declares"),
    "I6 an open tier route is admitted":
        ("    if route.get(\"open\"):\n        raise GrantError", "    if False:\n        raise GrantError"),
    "I7 ingress skips the audience check (groups, undeclared DMs)":
        ("    if not releasable(lbl, audience(channel, route)):\n        raise Refused(f\"the route's audience",
         "    if False:\n        raise Refused(f\"the route's audience"),
}
