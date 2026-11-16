"""astryx · connect — an agent opens, closes and confirms a door to a PERSON on any channel (identity-channels P3;
owner 11-16: "a single tool … call it connect … it should work for all channels … agents are intelligent and can decide
things themselves"). The channels MCP server's `connect` tool is this, over the org's database.

A person may be on several channels (one identity, many handles: astryx.core.identity). `open` finds them (their linked
accounts first, then the channels' own contact search, a typed +number included), and opens a CONNECTION on one
channel: a `route` row, so the person's replies wake the agent on that chat's thread until no one has written for the
idle time (the connection_sweep tells the agent). The agent writes with `send` as always; connect only opens and closes.

  open    who, channel?, timeout?, note   the agent picks the channel when the person is on several
  close   who                              only a connection the agent opened
  link    who=<person's wire name>, channel, account   asks that account to reply YES; its YES links it (bridges)
  status                                   my connections and links

Guards: a group is the owner's to route (refused); a chat the owner's routes file already routes stays his; one agent
per chat at a time; at most CAP open per agent; the idle time is at most MAX_IDLE.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from astryx.core import channels

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


def _owner_route(estate: Path, channel: str, chat: str) -> str | None:
    """The agent the OWNER's routes file sends this chat to, if any (his routes win)."""
    from bridges.routing import read_table, resolve
    r = resolve(read_table(estate / "bridges" / f"routes-{channel}.json")).chat(chat)
    return r["agent"] if r else None


def run(conn, me: str, action: str, who: str = "", channel: str = "", timeout: str = "1d", note: str = "",
        account: str = "", *, search, estate: Path, by: str | None = None) -> str:
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
    if action not in ("open", "link"):
        return "action is open, close, link or status"
    if channel and channel not in channels.BY_NAME:
        return f"channel {channel!r}: one of {', '.join(channels.BY_NAME)}"
    try:
        idle = idle_of(timeout)
    except ValueError as e:
        return str(e)

    if action == "link":
        if not (who and channel and account):
            return "link needs who (the person's wire name, e.g. cv-faran.2), channel and account (their number or id)"
        hits = [h for h in find(conn, account, channel, search) if h.channel == channel]
        chat = hits[0].chat if hits else account      # a +number is the provider's to resolve (its search)
        return _open(conn, me, Handle(channel, chat, person_name(channel, chat), account), "link", idle, note, estate,
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
    return _open(conn, me, hits[0], "open", idle, note, estate)


def _open(conn, me, h: Handle, purpose, idle, note, estate, person=None, prompt=None, by=None) -> str:
    title = channels.BY_NAME[h.channel].title
    if channels.chat_kind(h.channel, h.chat) == "group":
        return f"that is a {title} group: groups are the owner's to route; ask him"
    owned = _owner_route(estate, h.channel, h.chat)
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
        "note = EXCLUDED.note, idle = EXCLUDED.idle, opened = now(), expires_at = EXCLUDED.expires_at",
        (h.channel, h.chat, me, purpose, person or h.person, by or me, note or None, idle, idle))
    thread = f"{channels.BY_NAME[h.channel].thread}:{h.chat}"
    if prompt:
        conn.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES (%s, %s, %s, 'chat', %s)",
                     (me, h.person, thread, prompt))
        return f"asked {h.label} on {title} to reply YES; the link lands when they do, or lapses after {idle} (you are told)"
    return (f"connected to {h.label} on {title} for {idle} of quiet (each message renews it). Write with "
            f"send(to={h.person!r}, thread={thread!r}); their replies come to you on that thread. "
            f"connect action=close who={h.person!r} ends it")
