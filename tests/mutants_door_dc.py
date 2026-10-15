"""Mutants for plan-9139 S1c in bridges/discord.py: its deliver()'s door and its pending predicate. The oracle is
tests/test_bridge_door.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "bridges" / "discord.py"
ORACLE = REPO / "tests" / "test_bridge_door.py"
ENV = "DC_SRC"
MUTANTS = {
    "X1 the predicate never selects this bridge's releases":
        ("             \"OR (to_agent='owner' AND thread LIKE 'tier-%' AND delivery->'release'->>'channel' = 'discord')\",",
         "             \"\","),
    "X2 deliver() skips the org-route check":
        ("        if not await door_org_ok(pool, row, \"discord\", routes(), cid):", "        if False:"),
    "X3 the live_steps job starts on any route that asks":
        ("    if live_steps_ok(route) and trusted:", "    if route.get(\"live_steps\") and trusted:"),
}
