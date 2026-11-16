"""astryx · connect — an agent opens, closes and confirms a door to a PERSON on any channel (identity-channels P3;
owner 11-16: "a single tool … call it connect … it should work for all channels … agents are intelligent and can decide
things themselves"). The channels MCP server's `connect` tool is this, over the org's database.

A person may be on several channels (one identity, many handles: astryx.core.identity). `open` finds them (their linked
accounts first, then the channels' own contact search, a typed +number included), and opens a CONNECTION on one
channel: a `route` row, so the person's replies wake the agent on that chat's thread until no one has written for the
idle time (the connection_sweep tells the agent). The agent writes with `send` as always; connect only opens and closes.

  open    who, channel?, timeout?, note   the agent picks the channel when the person is on several
  close   who                              only a connection the agent opened
  link    the web's "Your channels" only (by = the signed-in person = who): asks that account to reply YES
  status                                   my connections and links
  route   who=<a chat or person>, channel?, to=<agent>   the OWNER's standing route, set on his word: only an agent
          whose charter grants `org` (seed); a group is fine here. It is the rail's own write (routes.put)
  unroute who                              the owner's route to that chat removed (same grant)

Guards: a group is the owner's to route (refused); a chat the owner routes (a standing row) stays his; one agent
per chat at a time; at most CAP open per agent; the idle time is at most MAX_IDLE.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from astryx.core import channels, routes

CAP = 10
MAX_IDLE = timedelta(days=7)
UNIT = {"m": "minutes", "h": "hours", "d": "days"}


@dataclass
class Handle:
    channel: str
    chat: str            # the channel's own id for the person's chat (a jid, a Telegram user id)
    person: str          # the wire name they write as here: their identity's, else the channel's own (wa-<digits>)
    label: str


def idle_of(timeout: str) -> timedelta:
    """'30m' / '2h' / '1d' (default 1d), capped at MAX_IDLE. ValueError on anything else."""
    m = re.fullmatch(r"\s*(\d{1,4})\s*([mhd])\s*", timeout or "1d")
    if not m:
        raise ValueError(f"timeout {timeout!r}: say 30m, 2h or 1d")
    return min(timedelta(**{UNIT[m.group(2)]: int(m.group(1))}), MAX_IDLE)


def person_name(channel: str, chat: str) -> str:
    """The wire name an unlinked person's chat writes as (the bridges' own mint)."""
    c = channels.BY_NAME[channel]
    digits = "".join(ch for ch in chat.split("@")[0] if ch.isdigit())
    return f"{c.person}-{digits or chat}"


def find(conn, who: str, channel: str, search) -> list[Handle]:
    """Everyone `who` may mean, as one handle per channel account. A linked person's accounts come first (their
    identity's name, label or wire name); else the channels' contact search (`search(query, channel) -> Contacts`)."""
    rows = conn.execute(
        "SELECT i.wire_name, coalesce(i.label, i.wire_name), h.channel, h.account FROM identity i "
        "JOIN identity_handle h ON h.identity_id = i.id AND h.tenant = i.tenant "
        "WHERE h.channel <> 'web' AND (i.wire_name = %s OR i.label ILIKE %s) AND (%s = '' OR h.channel = %s) "
        "ORDER BY h.channel", (who, f"%{who}%", channel, channel)).fetchall()
    if rows:
        return [Handle(ch, acct, name, label) for name, label, ch, acct in rows if ch in channels.BY_NAME]
    out = []
    for c in search(who, channel):
        ch, _, chat = (c.handle or "").partition(":")
        if ch in channels.BY_NAME and chat:       # a group too: _open says it is the owner's, not "no one"
            linked = conn.execute("SELECT identity_who(%s, %s, %s, false)", (ch, chat, person_name(ch, chat))).fetchone()[0]
            out.append(Handle(ch, chat, linked, c.label))
    return out


def run(conn, me: str, action: str, who: str = "", channel: str = "", timeout: str = "1d", note: str = "",
        account: str = "", *, search, by: str | None = None, to: str = "", pool=None) -> str:
    """One connect call by agent `me`. `by`: who asked, when it is not the agent (a person adding their own account on
    the web asks through seed): the link's lapse is told to them."""
    action = (action or "").strip().lower()
    if action == "status":
        rows = conn.execute("SELECT purpose, channel, person, chat, expires_at, note FROM route "
                            "WHERE (agent = %s OR opened_by = %s) AND expires_at > now() ORDER BY opened", (me, me)).fetchall()
        return "\n".join(f"{p} · {channels.BY_NAME[ch].title if ch in channels.BY_NAME else ch} · {person or chat} · "
                         f"until {exp:%Y-%m-%d %H:%M} UTC" + (f" · {n}" if n else "") for p, ch, person, chat, exp, n in rows) \
            or "no open connections or links"
    if action == "close":
        gone = conn.execute("DELETE FROM route WHERE agent = %s AND (person = %s OR person ILIKE %s OR chat = %s) "
                            "RETURNING channel, person", (me, who, f"%{who}%", who)).fetchall()
        return "\n".join(f"closed: {p} on {channels.BY_NAME[c].title}" for c, p in gone) or f"no connection of yours matches {who!r}"
    if action in ("route", "unroute"):
        return _route(conn, me, action, who, channel, to, note, search)
    if action not in ("open", "link"):
        return "action is open, close, link, status, route or unroute"
    if channel and channel not in channels.BY_NAME:
        return f"channel {channel!r}: one of {', '.join(channels.BY_NAME)}"
    try:
        idle = idle_of(timeout)
    except ValueError as e:
        return str(e)

    if action == "link":
        if not by or who != by:         # only a person links THEIR OWN account; an agent can't link anyone (medic 12637)
            return ("only the person can link their own account: ask them to open \"Your channels\" in the observatory "
                    "(their account menu) and add it there")
        if not (who and channel and account):
            return "link needs who (the person's wire name, e.g. cv-faran.2), channel and account (their number or id)"
        hits = [h for h in find(conn, account, channel, search) if h.channel == channel]
        chat = hits[0].chat if hits else account      # a +number is the provider's to resolve (its search)
        return _open(conn, me, Handle(channel, chat, person_name(channel, chat), account), "link", idle, note,
                     person=who, by=by, prompt=f"Reply YES to link this {channels.BY_NAME[channel].title} account to the astryx "
                                        f"account {who}. (Asked by {by or me}; nothing happens if you don't.)")
    hits = find(conn, who, channel, search)
    if not hits:
        return (f"no one called {who!r} on {channel or 'any channel'}. A WhatsApp number works in full (+92…); Telegram "
                f"has no contact search, so a Telegram person is reachable once linked or by their id")
    people = {h.person for h in hits}
    if len(people) > 1:
        return "several people match; say which (connect again with who=<their name as listed>):\n" + \
            "\n".join(f"{h.label} · {channels.BY_NAME[h.channel].title} · {h.person}" for h in hits)
    if len(hits) > 1 and not channel:
        return f"{hits[0].label} is on {', '.join(channels.BY_NAME[h.channel].title for h in hits)}: connect again with " \
               f"channel=<one of {', '.join(h.channel for h in hits)}>"
    return _open(conn, me, hits[0], "open", idle, note)


def _open(conn, me, h: Handle, purpose, idle, note, person=None, prompt=None, by=None) -> str:
    title = channels.BY_NAME[h.channel].title
    if channels.chat_kind(h.channel, h.chat) == "group":
        return f"that is a {title} group: groups are the owner's to route; ask him"
    owned = routes.standing_route(conn, h.channel, h.chat)
    if owned:
        return f"the owner routes that chat to {owned}: write there (send to {owned} on it), or ask him"
    held = conn.execute("SELECT agent, expires_at FROM route WHERE channel = %s AND chat = %s AND expires_at > now()",
                        (h.channel, h.chat)).fetchone()
    if held and held[0] != me:
        return f"{h.label} is connected to {held[0]} until {held[1]:%H:%M} UTC; ask {held[0]}, or try again then"
    if not held and conn.execute("SELECT count(*) FROM route WHERE agent = %s AND expires_at > now()", (me,)).fetchone()[0] >= CAP:
        return f"you have {CAP} connections open: close one first (connect action=close)"
    conn.execute(
        "INSERT INTO route (channel, chat, agent, purpose, person, opened_by, note, idle, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now() + %s) ON CONFLICT ON CONSTRAINT route_chat_key DO UPDATE SET "
        "agent = EXCLUDED.agent, purpose = EXCLUDED.purpose, person = EXCLUDED.person, opened_by = EXCLUDED.opened_by, "
        "note = EXCLUDED.note, idle = EXCLUDED.idle, opened = now(), expires_at = EXCLUDED.expires_at "
        "WHERE route.purpose <> 'standing'",                     # the owner's route is never overwritten
        (h.channel, h.chat, me, purpose, person or h.person, by or me, note or None, idle, idle))
    thread = f"{channels.BY_NAME[h.channel].thread}:{h.chat}"
    if prompt:
        conn.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES (%s, %s, %s, 'chat', %s)",
                     (me, h.person, thread, prompt))
        return f"asked {h.label} on {title} to reply YES; the link lands when they do, or lapses after {idle} (you are told)"
    return (f"connected to {h.label} on {title} for {idle} of quiet (each message renews it). Write with "
            f"send(to={h.person!r}, thread={thread!r}); their replies come to you on that thread. "
            f"connect action=close who={h.person!r} ends it")


def _owner_asked(conn, me: str) -> bool:
    """The turn this call runs in was opened by the OWNER alone (medic 12649: the code decides, never the prompt). The
    step hook writes this very tool call's step before the tool runs, with the turn's opening messages (meta.turn_msgs);
    every one must be the owner's own (address.person_sql's rule, so a peer's 'owner' is not him). Unknown: refused."""
    from astryx.core import address
    r = conn.execute("SELECT meta->'turn_msgs' FROM steps WHERE agent = %s AND kind = 'tool' "
                     "AND left(content, 23) = 'mcp__channels__connect:' ORDER BY id DESC LIMIT 1", (me,)).fetchone()
    ids = [int(x) for x in (r[0] or [])] if r else []
    if not ids:
        return False
    n = conn.execute(f"SELECT count(*) FROM messages m WHERE m.id = ANY(%s) AND m.from_agent = 'owner' AND "
                     f"{address.person_sql('m.from_agent', org='m.from_org')}", (ids,)).fetchone()[0]
    return n == len(ids)


def _route(conn, me, action, who, channel, to, note, search) -> str:
    """The owner's STANDING route, set by the org's own agent on his word (an agent granted `org`: seed). One write
    path with the rail (route_put): the channel's owner routes, read with their version, replaced in one act."""
    from astryx.core import tier
    if "org" not in (tier.grants(me) or set()):
        return "only the org's own agent (granted org: seed) sets the owner's routes; ask seed, or use the Channels rail"
    if not _owner_asked(conn, me):
        return "only on the owner's own message: ask him to do it, or to change it in the Channels rail"
    if action == "route" and not to:
        return "route needs to=<the agent the chat should reach>"
    hits = find(conn, who, channel, search)
    chats = {(h.channel, h.chat): h for h in hits}
    if len(chats) != 1:
        return (f"no chat called {who!r}" if not chats else "several chats match; say which:\n" +
                "\n".join(f"{h.label} · {channels.BY_NAME[h.channel].title}" for h in chats.values()))
    h = next(iter(chats.values()))
    now = routes.standing_sync(conn, h.channel)
    keep = [r for r in now if str(r["chat"]) != h.chat]
    if action == "route":
        old = next((r for r in now if str(r["chat"]) == h.chat), {})
        theirs = [r for r in keep if r.get("agent") == to and r.get("enabled")]
        if len(theirs) == 1 and not theirs[0].get("home"):      # its one route was its doorbell: it stays so
            theirs[0]["home"] = True
        keep.append({**old, "chat": h.chat, "agent": to, "enabled": True, "open": old.get("open", True),
                     "show": old.get("show", "steps"), "note": note or old.get("note") or f"{h.label} -> {to} (by {me})"})
    elif len(keep) == len(now):
        return f"the owner has no route to {h.label}"
    from bridges.routing import validate
    problems = validate(keep)
    if problems:
        return "refused: " + problems[0]
    routes.put_sync(conn, h.channel, keep, routes.version_sync(conn, h.channel), by=me)
    opened = action == "route" and not old
    return (f"{h.label} on {channels.BY_NAME[h.channel].title} now reaches {to}"
            + (" (open to everyone in it; the owner can close it in the Channels rail)" if opened else "") if action == "route"
            else f"{h.label} on {channels.BY_NAME[h.channel].title} is no longer routed")
