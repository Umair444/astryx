"""Mutants for plan-9139 S1c's bridge half, bridges/common.py (door_refuse, door_open, door_org_ok, the receipt's
census mark, the released receipt's merge). The oracle is tests/test_bridge_door.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "bridges" / "common.py"
ORACLE = REPO / "tests" / "test_bridge_door.py"
ENV = "BRIDGE_COMMON_SRC"
MUTANTS = {
    "C1 a refused row is left pending (re-refused on every wire event, never terminal)":
        ("        \"UPDATE messages SET status='refused', delivered_at=now(), \"",
         "        \"UPDATE messages SET status='pending', delivered_at=now(), \""),
    "C2 a bridge delivers another bridge's release":
        ("    if (R.released(row) or {}).get(\"channel\") != channel:\n        return None",
         "    if False:\n        return None"),
    "C3 a store error crashes deliver (only Refused is caught)":
        ("    except Exception as e:                         # noqa: BLE001 — Refused, or a store",
         "    except R.Refused as e:                         # noqa: BLE001 — Refused, or a store"),
    "C4 door_org_ok passes every unstamped row":
        ("        R.door_org(channel, chat, routes)\n        return True", "        return True"),
    "C5 the receipt drops the census mark":
        ("        if door:\n            r[\"door\"] = door", "        if False:\n            r[\"door\"] = door"),
}
