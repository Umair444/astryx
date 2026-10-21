"""The ONE route resolver and validator (plan-11860 E2): every reader of routes-<channel>.json decides through here.

Its readers are the three chat bridges (inbound: which agent a chat reaches; outbound: which chat an agent's un-threaded
doorbell rings), the observatory's routes PUT (what a write will do), and doctor (is the live file sound). Before this,
each bridge kept its own first-match loops, so a duplicate chat or an agent with two routes was decided by FILE ORDER,
differently at each site. Now:
  - resolve(rows)   -> Routes: the enabled rows, with .chat(id) (inbound) and .doorbell(agent) (outbound)
  - validate(rows)  -> the problems a table has; [] means every reader resolves it the same way
  - effective(rows) / diff(a, b) -> what a change does, as the readers will see it (the floor's toast renders this)
Rules (validate enforces, resolve obeys):
  - one row per str(chat), enabled or not: a second row is dead weight no reader can reach (there is no fan-out);
  - an agent with two or more ENABLED rows marks exactly one `"home": true`: that is its doorbell. With one row, that
    row is the doorbell. An agent with several rows and no single home has NO doorbell (resolve returns None, and the
    bridge refuses to guess), never "the first one in the file".
Dependency-free on purpose (stdlib only): the observatory imports it without the bridges' runtime, as owner_surfaces.
"""
import json
import sys
import time
from pathlib import Path


class Routes(list):
    """A channel's ENABLED route rows, resolved. It is still a list (door_open/door_org and len() read it as one)."""

    def __init__(self, rows=()):
        super().__init__(r for r in rows if isinstance(r, dict) and r.get("enabled"))
        self._by_chat: dict[str, dict] = {}
        for r in self:
            self._by_chat.setdefault(str(r.get("chat")), r)

    def chat(self, chat) -> dict | None:
        """The route an inbound chat id reaches (None: not a surface this bridge serves)."""
        return self._by_chat.get(str(chat))

    def doorbell(self, agent: str) -> dict | None:
        """The route an agent's un-threaded message rings: its only row, else its single `home` row, else None."""
        mine = [r for r in self if r.get("agent") == agent]
        if len(mine) == 1:
            return mine[0]
        homes = [r for r in mine if r.get("home") is True]
        return homes[0] if len(homes) == 1 else None


def resolve(rows) -> Routes:
    return Routes(rows or [])


def validate(rows, agents=None) -> list[str]:
    """Every problem in a route table, in words the owner can act on. `agents`: the names that exist (None: unchecked)."""
    if not isinstance(rows, list):
        return ["the routes file must hold a list of routes"]
    out: list[str] = []
    seen: dict[str, str] = {}
    enabled: dict[str, list[dict]] = {}
    for i, r in enumerate(rows):
        if not isinstance(r, dict) or not str(r.get("chat", "")).strip() or not r.get("agent"):
            out.append(f"route {i + 1} needs a chat and an agent")
            continue
        chat, agent = str(r["chat"]), str(r["agent"])
        if agents is not None and agent not in agents:
            out.append(f"no such agent: {agent}")
        if chat in seen:
            out.append(f"chat {chat} is routed twice ({seen[chat]} and {agent}); a chat reaches one agent")
        else:
            seen[chat] = agent
        if r.get("enabled"):
            enabled.setdefault(agent, []).append(r)
    for agent, mine in enabled.items():
        if len(mine) > 1 and sum(1 for r in mine if r.get("home") is True) != 1:
            out.append(f"{agent} has {len(mine)} routes: mark exactly one as its home (\"home\": true), "
                       f"the chat its un-threaded messages ring")
    return out


def effective(rows) -> dict:
    """What the readers see: inbound chat -> agent, and agent -> doorbell chat."""
    m = resolve(rows)
    inbound = {c: r["agent"] for c, r in m._by_chat.items()}
    agents = sorted({r["agent"] for r in m})
    door = {a: str(d["chat"]) for a in agents if (d := m.doorbell(a))}
    return {"inbound": inbound, "doorbell": door}


def diff(before, after) -> dict:
    """The change from one table to another, over the EFFECTIVE maps (never the raw rows)."""
    a, b = effective(before), effective(after)
    ai, bi = a["inbound"], b["inbound"]
    out = {"added": [{"chat": c, "agent": bi[c]} for c in sorted(bi.keys() - ai.keys())],
           "removed": [{"chat": c, "agent": ai[c]} for c in sorted(ai.keys() - bi.keys())],
           "moved": [{"chat": c, "from": ai[c], "to": bi[c]} for c in sorted(ai.keys() & bi.keys()) if ai[c] != bi[c]],
           "doorbell": []}
    for ag in sorted(a["doorbell"].keys() | b["doorbell"].keys()):
        o, n = a["doorbell"].get(ag), b["doorbell"].get(ag)
        if o != n:
            out["doorbell"].append({"agent": ag, "old": o, "new": n})
    return out


# ---------------------------------------------------------------- reading the file (BC-3)
_last_good: dict[str, list] = {}
_alarmed: dict[str, float] = {}


def read_table(path: Path) -> list:
    """The raw rows of a routes file. An unreadable or unparseable file keeps the LAST GOOD table this process read
    (never [] = "nothing routed", which would drop every chat on a hand-edit typo) and alarms on stderr, once per
    file version. A file that was never good reads []."""
    key = str(path)
    try:
        rows = json.loads(Path(path).read_text())
        if not isinstance(rows, list):
            raise ValueError("not a list")
        _last_good[key] = rows
        _alarmed.pop(key, None)
        return rows
    except FileNotFoundError:
        _last_good.pop(key, None)
        return []
    except Exception as e:  # noqa: BLE001 — a torn or hand-broken file
        try:
            mt = Path(path).stat().st_mtime
        except OSError:
            mt = time.time()
        if _alarmed.get(key) != mt:
            _alarmed[key] = mt
            print(f"routes: ALARM {path} does not parse ({type(e).__name__}); keeping the last good table "
                  f"({len(_last_good.get(key, []))} routes) until it is fixed", file=sys.stderr, flush=True)
        return _last_good.get(key, [])


def kind_of(channel: str, chat: str) -> str:
    """group or person, from the chat id's shape alone (the public glyphs carry this, never the id)."""
    if channel == "whatsapp":
        return "group" if chat.endswith("@g.us") else "person"
    if channel == "telegram":
        return "group" if chat.startswith("-") else "person"
    return "group"          # a discord route is a guild channel
