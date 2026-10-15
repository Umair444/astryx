"""Mutants for plan-9139 S1c in bridges/whatsapp.py's deliver() and its live_steps start. The oracle is
tests/test_bridge_door.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "bridges" / "whatsapp.py"
ORACLE = REPO / "tests" / "test_bridge_door.py"
ENV = "WA_SRC"
MUTANTS = {
    "W1 deliver() skips the org-route check (the door bypassed for unstamped rows)":
        ("    if not stamped and not await door_org_ok(pool, row, \"whatsapp\", routes(), chat):",
         "    if False:"),
    "W2 a stamped row's receipt names the chat and carries the resolved body":
        ("out.receipt(\"whatsapp:release\", row[\"body\"], door=\"released\")",
         "out.receipt(f\"whatsapp:{chat}\", text, door=\"released\")"),
    "W3 a stamped row's destination comes from its thread":
        ("        chat = stamped[0][\"chat\"]", "        chat = thread[3:] or stamped[0][\"chat\"]"),
    "W4 the live_steps job starts on any route that asks (its second egress ungated)":
        ("    if live_steps_ok(route) and trusted:", "    if route.get(\"live_steps\") and trusted:"),
    "W5 a released row is not recognised (it takes the thread path)":
        ("    if released(row) is not None:\n        # plan-9139 S1c", "    if False:\n        # plan-9139 S1c"),
    "W6 a released row's receipt REPLACES its delivery (the release record lost)":
        ("                           \"delivery = coalesce(delivery, '{}'::jsonb) || $3::jsonb WHERE id=$1\", row[\"id\"], out.status,",
         "                           \"delivery = $3 WHERE id=$1\", row[\"id\"], out.status,"),
}
