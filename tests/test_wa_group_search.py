#!/usr/bin/env python3
"""Oracle: the WhatsApp provider's chat search finds GROUPS as well as people (owner 11-15: "ETL" found nothing in the
floor's channel rail). No WhatsApp is touched: the provider's one effect boundary (_wacli_json) is replaced.
  G1 a group whose name holds the query comes back, as a group handle, before the people
  G2 case does not matter; a group the account LEFT is not offered; an empty query offers no group
  G3 a failing group list still returns the people
  G4 A NUMBER nobody has chatted with (owner 11-16, "wa.me shows the number exists"): typed in international form it is
     looked up live (contacts check, one attempt) and offered when registered; a confirmed no is shown, never offered;
     an unasked lookup (an older wacli: the store is the sync's) still offers it, unchecked; a known contact is not doubled;
     a national 0… form or a short code is not a number
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
import bridges.providers.whatsapp as W  # noqa: E402
calls = []


def checker(answer):
    async def run(cmd, *args, retry=True):
        calls.append((args, retry))
        if isinstance(answer, Exception):
            raise answer
        return answer
    return run


W.run_wacli = checker('[{"query":"+923001234567","phone":"923001234567","jid":"923001234567@s.whatsapp.net","registered":true,"responded":true}]')
r = asyncio.run(provider().search_contacts("+92 300 1234567"))
arm("G4 a registered number is offered as its chat, checked once with no retries",
    [(c.handle, c.raw.get("registered")) for c in r] == [("whatsapp:923001234567@s.whatsapp.net", True)]
    and calls[-1] == (("--json", "contacts", "check", "+923001234567"), False), ([(c.handle, c.raw) for c in r], calls))
W.run_wacli = checker('[{"query":"+923001234567","phone":"923001234567","registered":false,"responded":true}]')
r = asyncio.run(provider().search_contacts("923001234567"))
arm("G4 a confirmed no: shown (registered False), with no handle to bind a route to", [(c.handle, c.raw.get("registered")) for c in r] == [("", False)], [(c.handle, c.raw) for c in r])
W.run_wacli = checker(RuntimeError("wacli --json contacts: store is locked"))
r = asyncio.run(provider().search_contacts("0092 300 1234567"))
arm("G4 not asked (the store is the sync's): still offered, unchecked", [(c.handle, c.raw.get("registered")) for c in r] == [("whatsapp:923001234567@s.whatsapp.net", None)], [(c.handle, c.raw) for c in r])
n = len(calls)
r = asyncio.run(provider().search_contacts("9"))
arm("G4 a short code is no number (no lookup)", len(calls) == n)
arm("G4 a national 0… form names no country: no lookup", asyncio.run(provider().search_contacts("03001234567")) == [] and len(calls) == n)
p = provider()


async def known(*args):
    return {"data": [{"jid": "923001234567@s.whatsapp.net", "name": "Known", "phone": "923001234567"}] if args[:2] == ("contacts", "search") else []}
p._wacli_json = known
r = asyncio.run(p.search_contacts("+923001234567"))
arm("G4 a number that is already a contact comes back once, as the contact", [c.label for c in r if "923001234567" in c.handle] == ["Known"] and len(calls) == n, [(c.label, c.handle) for c in r])
print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: a WhatsApp group is findable by name")
sys.exit(1 if fails else 0)
