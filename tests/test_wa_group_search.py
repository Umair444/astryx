#!/usr/bin/env python3
"""Oracle: the WhatsApp provider's chat search finds GROUPS as well as people (owner 11-15: "ETL" found nothing in the
floor's channel rail). No WhatsApp is touched: the provider's one effect boundary (_wacli_json) is replaced.
  G1 a group whose name holds the query comes back, as a group handle, before the people
  G2 case does not matter; a group the account LEFT is not offered; an empty query offers no group
  G3 a failing group list still returns the people
Exit 0 · 1."""
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "src"))
from bridges.providers.whatsapp import WhatsAppProvider  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


GROUPS = [{"JID": "1@g.us", "Name": "ETL management", "LeftAt": "0001-01-01T00:00:00Z"},
          {"JID": "2@g.us", "Name": "old etl", "LeftAt": "2026-10-01T00:00:00Z"},
          {"JID": "3@g.us", "Name": "wm_ai", "LeftAt": "0001-01-01T00:00:00Z"}]
PEOPLE = [{"jid": "9@s.whatsapp.net", "name": "Etl Person", "phone": "9"}]


def provider(groups_fail=False):
    p = WhatsAppProvider()

    async def j(*args):
        if args[:2] == ("groups", "list"):
            if groups_fail:
                raise RuntimeError("wacli down")
            return {"data": GROUPS}
        return {"data": PEOPLE if args[:2] == ("contacts", "search") and "etl" in args[2].lower() else []}
    p._wacli_json = j
    return p


r = asyncio.run(provider().search_contacts("etl"))
arm("G1 the group comes back, first, as a group handle", r and r[0].label == "ETL management" and r[0].handle == "whatsapp:1@g.us", [(c.label, c.handle) for c in r])
arm("G1 …and the people after it", [c.label for c in r][-1] == "Etl Person", [c.label for c in r])
arm("G2 a group the account left is not offered", "old etl" not in [c.label for c in r])
arm("G2 case does not matter", [c.label for c in asyncio.run(provider().search_contacts("WM_AI"))] == ["wm_ai"])
arm("G2 an empty query offers no group", asyncio.run(provider().search_contacts("")) == [])
arm("G3 a failing group list still returns the people", [c.label for c in asyncio.run(provider(groups_fail=True).search_contacts("etl"))] == ["Etl Person"])
print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: a WhatsApp group is findable by name")
sys.exit(1 if fails else 0)
