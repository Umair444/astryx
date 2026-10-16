"""Mutants for plan-9139 S1c's decision half, src/astryx/security/release.py's door (door_org, door_stamped,
route_tier's live_steps refusal, live_steps_ok). The oracle is tests/test_bridge_door.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "src" / "astryx" / "security" / "release.py"
ORACLE = REPO / "tests" / "test_bridge_door.py"
ENV = "RELEASE_SRC"
MUTANTS = {
    "D1 the exemption keyed 'not labelled' instead of 'a declared org route' (a4 #45091: a no-route destination passes)":
        ("    if not hits:\n        raise Refused(\"an unstamped row to a destination on no declared route",
         "    if False:\n        raise Refused(\"an unstamped row to a destination on no declared route"),
    "D2 a TIERED route takes an unstamped row":
        ("        if route_tier(r) is not None:\n            raise Refused(\"an unstamped row to a TIERED route",
         "        if False:\n            raise Refused(\"an unstamped row to a TIERED route"),
    "D3 a disabled route counts as declared":
        ("    hits = [r for r in routes if r.get(\"enabled\") and str(r.get(\"chat\")) == str(chat)]",
         "    hits = [r for r in routes if str(r.get(\"chat\")) == str(chat)]"),
    "D4 the stamped destination is the sender's route, not the one its stamp names":
        ("    hits = [r for r in routes if hmac.compare_digest(route_key(key, channel, r), rkey)]",
         "    hits = [r for r in routes if r.get(\"agent\") == row.get(\"from_agent\")][:1]"),
    "D5 a route rebound since release still delivers":
        ("    if not releasable(lbl, audience(channel, route, members)):\n        raise Refused(f\"the stamped route's",
         "    if False:\n        raise Refused(f\"the stamped route's"),
    "D6 a tiered route may declare live_steps":
        ("    if route.get(\"live_steps\"):\n        # live_steps streams", "    if False:\n        # live_steps streams"),
    "D7 live_steps_ok ignores the tier":
        ("route.get(\"live_steps\")) and route_tier(route) is None", "route.get(\"live_steps\"))"),
    "D8 door_stamped skips open_stamped's checks (the body read straight from the store)":
        ("    body = open_stamped(key, store, int(row[\"id\"]), rkey, lbl, str(rel.get(\"pointer\")), str(rel.get(\"body_mac\")),\n"
         "                        str(rel.get(\"stamp\") or \"\"))",
         "    body = store.get(str(rel.get(\"pointer\")), lbl)"),
}
