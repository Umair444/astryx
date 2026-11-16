"""The ONE route resolver and validator (plan-11860 E2): every reader of a channel's routes (rows of the route table,
astryx.core.routes; owner 11-16) decides through here.

Its readers are the chat bridges (inbound: which agent a chat reaches; outbound: which chat an agent's un-threaded
doorbell rings), the observatory's routes PUT (what a write will do), and doctor (are the live routes sound). Before this,
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
An agent's CONNECTION (a route with a `connection` id: connect()) reaches its agent like any route, but is never its
doorbell: the owner's routes decide where an agent's un-threaded messages ring.
Dependency-free on purpose (stdlib and astryx.core.channels only): the observatory imports it without the bridges'
runtime, as owner_surfaces.
"""


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
        mine = [r for r in self if r.get("agent") == agent and r.get("connection") is None]   # never a connection
        if len(mine) == 1:
            return mine[0]
        homes = [r for r in mine if r.get("home") is True]
        return homes[0] if len(homes) == 1 else None


def resolve(rows) -> Routes:
    return Routes(rows or [])


def validate(rows, agents=None) -> list[str]:
    """Every problem in a route table, in words the owner can act on. `agents`: the names that exist (None: unchecked)."""
    if not isinstance(rows, list):
        return ["the routes must be a list of routes"]
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
            # named by its label and its two agents, never by the chat id (a3 #62025 N3: doctor prints this)
            label = next((str(x.get("note")).split(" -> ")[0].strip() for x in rows
                          if isinstance(x, dict) and str(x.get("chat")) == chat and x.get("note")), "")
            out.append(f"{repr(label) if label else 'a chat'} is routed twice ({seen[chat]} and {agent}); a chat reaches one agent")
        else:
            seen[chat] = agent
        if "show" in r and r["show"] not in ("steps", "replies"):
            out.append(f"{agent}'s route shows {r['show']!r}: a route shows steps (then the reply) or replies (the reply only)")
        # a TIERED route (its `tier` key, any spelling: the release door reads an odd one as malformed) can never show
        # steps, by `show` or by the older live_steps flag: step text would reach the chat around the door, so the
        # bridges refuse the whole route (release.route_tier). Said here, so the one write refuses it first (medic 12249)
        tiers = [k for k in r if "tier" in str(k).lower()]
        wants = r.get("show") == "steps" if r.get("show") is not None else bool(r.get("live_steps"))
        if tiers and wants:
            out.append(f"{agent}'s route is tiered ({r[tiers[0]]}): it shows replies only, steps would bypass the door")
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


def kind_of(channel: str, chat: str) -> str:
    """group or person, from the chat id's shape alone (the public glyphs carry this, never the id): the one channel
    table's rule (core/channels.py), a shape it can't place drawn as a person."""
    from astryx.core.channels import chat_kind
    return "group" if chat_kind(channel, chat) == "group" else "person"
