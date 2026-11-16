"""astryx · channels — THE one table of the messaging channels the org speaks on (owner 11-16: "channels stuff should be
a standard … we can't patch it by each channel. later we will add slack and teams too").

Each channel is one row: its name (the from_org its bridge stamps, its provider's NAME, routes-<name>.json, the unit
astryx-<name>, bridges/<name>.py), the prefix of its people's wire names (wa-<id>) and of its threads (wa:<chat>), and
the SHAPE of its chat ids: which are groups (people talking among themselves, where only what addresses an agent is
owed a reply) and which are one person. Every place that used to list channels by hand reads this instead, so adding a
channel is one row here plus its bridge and provider files; tests/test_channels.py adds a fake one and proves every
reader takes it.

Pure and dependency-free on purpose: hooks (a 5 s Stop hook), the pulse, the observatory, the cli and the bridges all
import it. The id rules are regexes that Python (re.fullmatch) and Postgres (~, anchored) both run, so the SQL and the
code can never disagree. Prefixes are the wire's, already in the database: they are recorded here, never renamed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Channel:
    name: str                 # provider NAME, routes-<name>.json, unit astryx-<name>, bridges/<name>.py
    title: str
    person: str               # a person's wire name is <person>-<id>
    thread: str               # a conversation's thread is <thread>:<chat>
    group: str                # a chat id that is a GROUP (regex, whole id; "" = this channel has none)
    dm: str = ""              # a chat id that is ONE person ("" = this channel has none)
    token_key: str = ""       # the .env key holding its bot token ("" = connected another way: a QR, the web)
    token_ask: str = ""       # how the cli asks for that token
    token_shape: str = ""     # what such a token looks like (regex, whole token), judged before the platform is asked
    secret_key: str = ""      # a secret the bridge needs that this org GENERATES (no platform issues it): its .env key
    secret_ask: str = ""      # how the cli asks for it (Enter generates one)
    connect: bool = True      # the owner connects it from the channel screen and `astryx connect`
    org: str = ""             # the from_org its bridge stamps ("" = its name); reserved, so no peer can pose as it
    owner_rows: bool = True   # its bridge delivers rows addressed to the owner on its threads (owner_surfaces)
    trusted_key: str = "trusted_ids"   # a route's field naming the senders it trusts
    numbers: bool = False     # its people are phone numbers: found by number, shown as +<digits>
    steps: tuple[str, ...] = ()   # how the owner gets its token, shown on the channel screen

    @property
    def stamp(self) -> str:
        return self.org or self.name


CHANNELS: tuple[Channel, ...] = (
    Channel("whatsapp", "WhatsApp", person="wa", thread="wa", group=r".+@g\.us", dm=r".+@(s\.whatsapp\.net|lid)",
            secret_key="WA_WEBHOOK_SECRET", secret_ask="WhatsApp webhook secret (press Enter to generate one)",
            trusted_key="trusted_jids", numbers=True),
    Channel("telegram", "Telegram", person="tg", thread="tg", group=r"-\d+", dm=r"\d+",
            token_key="TG_BOT_TOKEN", token_ask="Telegram bot token (from @BotFather)",
            token_shape=r"\d{5,16}:[A-Za-z0-9_-]{30,64}",
            steps=("In Telegram, open @BotFather and send /newbot.", 'Choose a name, then a username that ends in "bot".',
                   "BotFather replies with a token. Paste it below.")),
    Channel("discord", "Discord", person="dc", thread="dc", group=r".+",
            token_key="DISCORD_BOT_TOKEN", token_ask="Discord bot token (Developer Portal → Bot → Reset Token)",
            token_shape=r"[A-Za-z0-9_-]{20,40}\.[A-Za-z0-9_-]{4,10}\.[A-Za-z0-9_-]{20,60}",
            steps=("Open the Discord Developer Portal and create a New Application.",
                   "Under Bot, reset the token and copy it. Turn on Message Content Intent.",
                   "Paste the token below. You get a link to add the bot to your server.")),
    # the web's own: a named person on a canvas page (cv-<name>, threads cv:<id>); no chat is a group
    Channel("canvas", "Canvas", person="cv", thread="cv", group="", connect=False),
    # a deployed third-party frontend (bridges/frontends.py): one user's conversation with one pinned agent
    Channel("frontends", "Frontends", person="fe", thread="fe", group="", dm=r".+", connect=False, org="frontend",
            owner_rows=False),
)
BY_NAME = {c.name: c for c in CHANNELS}


def chat_kind(channel: str, chat: str) -> str:
    """'group' | 'dm' | 'unknown', from the chat id's own shape (the one rule: release.py's audience gate, routing's
    public glyphs and owed's group test all read it)."""
    c = BY_NAME.get(channel)
    chat = str(chat or "")
    if c is None:
        return "unknown"
    if c.group and re.fullmatch(c.group, chat):
        return "group"
    if c.dm and re.fullmatch(c.dm, chat):
        return "dm"
    return "unknown"


def group_thread_sql(col: str) -> str:
    """SQL: the thread in `col` is a GROUP conversation on some channel (no bind-parameter characters in it)."""
    return "(" + " OR ".join(f"{col} ~ '^{c.thread}:({c.group})$'" for c in CHANNELS if c.group) + ")"


def thread_like_sql(col: str, params: bool = False) -> str:
    """SQL: the thread in `col` belongs to a channel whose bridge delivers the owner's rows. `params`: the statement carries bind parameters, so
    a LIKE's % is doubled for the driver."""
    pct = "%%" if params else "%"
    return "(" + " OR ".join(f"{col} LIKE '{c.thread}:{pct}'" for c in CHANNELS if c.owner_rows) + ")"


def of_thread(thread: str | None) -> Channel | None:
    t = str(thread or "")
    return next((c for c in CHANNELS if t.startswith(c.thread + ":")), None)


def connectable() -> tuple[Channel, ...]:
    return tuple(c for c in CHANNELS if c.connect)
