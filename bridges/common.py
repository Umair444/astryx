"""bridges/common.py — everything every CHAT surface shares, written once.

Scope: the chat-bridge family (whatsapp, telegram, discord) ONLY. gateway.py
(the federation door) is a deliberately independent loose script — folding it
in would couple the federation graph to the chat+ASR dependency tree for ~10
shared lines. Duplication beats coupling at that size.

A chat bridge translates ONE platform to the wire; anything that isn't
platform translation lives here:

  config       env() reads .env; Book holds a bridge's routes from the route table
  routing      address_agent / route_target — deliver to the @mentioned agent, or
               the last agent tagged on the thread (sticky); agent_exists() checks
               the agents/ tree
  reactions    reaction_signal — a reaction becomes a wire signal to the agent whose
               message was reacted to; the bridge supplies who + what (platform truth)
  embeds       split_files / split_polls — the [[file:]] and [[poll:]] grammar
  polls        one `polls` table for all surfaces (chat prefixed wa:/tg:/dc:),
               record on send, votes refreshed per event, DELTA reporting
               (never match webhook sender ids against store voter lists)
  media        describe_media() — bridge-side processing exists ONLY for
               senses agents lack: audio gets a transcript inline (models
               can't hear); images get clean delivery (agents see natively)
  progress     MARK glyphs + step_line() — the steps doorbell carries only
               {id, agent, kind}; content is fetched from the row
  doorbell     listen() — the reconnecting LISTEN astryx_wire/astryx_steps
               skeleton every bridge runs

Bridges import relatively (`from .common import ...`) and run as package
modules from the repo root: `uvicorn bridges.<platform>:app`.
"""

import asyncio
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path

import asyncpg

from .transcribe import transcribe

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))   # astryx.config/paths: the ONE resolver, this bridge's own tree (plan-11324 S3a)
from astryx import config, paths  # noqa: E402
from astryx.core import channels  # noqa: E402  the one channel table: a link reply names its channel's thread and title
from .routing import Routes, resolve  # noqa: E402,F401 — the one route resolver (plan-11860 E2)
ESTATE = paths.estate(__file__)          # the org's estate: this checkout on one org, the HOME on several
MEDIA_DIR = ESTATE / "media"

MARK = {"tool": "◌", "tool_done": "●", "error": "⚠", "response": "◌"}

# ── THE POLL / PERMISSION-RELAY BRIDGE CONTRACT (goal 3406) ───────────────────────────
# Native polls are a SHARED, channel-agnostic capability, not a per-bridge feature. Claude
# Code's permission protocol (channels-reference) is binary allow/deny with no native poll;
# astryx layers a poll UI on top, split at one seam so a NEW channel gets both for free:
#
#   channel/server.mjs (generic, zero per-channel code):
#     · emits a permission prompt whose body carries `[[poll: 🔐 <request_id>: … | ✅ Approve | ⛔ Deny]]`
#     · intercepts the vote-back and maps it to a `notifications/claude/channel/permission`
#       verdict — keyed ONLY on intent='poll' + from_agent='owner' + an id it issued.
#
#   a bridge (this layer) implements the contract, using the helpers below:
#     1. OUTBOUND: run split_polls() on every outgoing body; render each spec as a NATIVE
#        poll via the platform API; record_poll(msg_id, chat, asking_agent, q, opts, multi).
#     2. INBOUND vote: on a vote event, rebuild {aggregates, per-voter selected[]}, call
#        update_poll_votes() for the delta, vote_changes(), and wire_insert the result back
#        to the ASKING agent with intent='poll' and vote_body() as the text.
#     3. SENDER-GATE (the security line — this gates real money via the permission relay):
#        stamp from_agent='owner' ONLY when the voter's id is in the route's trusted set;
#        every other voter is `<chan>-<id>` and is IGNORED by server.mjs. Gate on the VOTER
#        identity, never the room. A bridge that skips this must NOT carry permission relays.
#
# Get these three right and permission-relay-as-polls + agent-initiated polls both work on
# the new channel with no server.mjs change. A channel that can't do native polls still works
# via Claude Code's own `yes <id>`/`no <id>` text fallback, which server.mjs also honors.
POLL_RE = re.compile(r"\[\[poll:(.+?)\]\]", re.S)
AUDIO_KINDS = {"voice", "audio", "ptt"}


# ---------------------------------------------------------------------- config
def env(key: str, default: str = "") -> str:
    """`key` from the environment first, else the org's .env: astryx.config.get, whose semantics are exactly this
    reader's (plan-11324 S3a routes it; every bridge's config goes through here). ASTRYX_DSN goes through
    config.dsn, which checks an environment DSN against the HOME in a cog of several orgs."""
    f = ESTATE / ".env"
    if key == "ASTRYX_DSN":
        try:
            return config.dsn(f)
        except LookupError:
            return default
    return config.get(key, default, f)


async def identity_of(pool, channel: str, account, fallback: str, route: dict | None = None) -> str:
    """THE one minter of a sender's wire name (identity-channels P1, owner 11-15 "one identity per person"): the
    person the (channel, account) handle is linked to, else `fallback`, the bridge's own name for an unlinked sender
    (wa-<digits>, tg-<id>, …), so nothing changes for anyone unlinked. On a CLOSED `route` a first-seen stranger is not
    recorded (medic 12635): only who it is matters there. The owner is the identity `owner`, whose handles
    are the owner's own accounts: that replaced each route's trusted_* list. Schema: identity_who (schema.sql)."""
    try:
        return await pool.fetchval("SELECT identity_who($1, $2, $3, $4)", channel, str(account), fallback,
                                   bool(route is None or route.get("open"))) or fallback
    except Exception as e:  # noqa: BLE001 — loud: the owner reads as a stranger until it is fixed
        print(f"{channel}: identity_who FAILED ({type(e).__name__}: {str(e)[:120]}); {fallback} as minted", flush=True)
        return fallback


async def renew(pool, route: dict) -> None:
    """A message on an agent's CONNECTION is activity: it lives on for its idle time from now (connection_sweep ends
    it once no one has written for that long). A standing route has no expiry: nothing to do."""
    if route.get("connection") is None:
        return
    try:
        await pool.execute("UPDATE route SET expires_at = now() + idle WHERE id = $1 AND idle IS NOT NULL", route["connection"])
    except Exception as e:  # noqa: BLE001 — loud; the connection keeps its expiry
        print(f"route {route['connection']}: renew FAILED ({type(e).__name__})", flush=True)


YES = re.compile(r"^\s*(yes|y|haan|ha|ji)\s*[.!]*\s*$", re.I)


async def link_reply(pool, channel: str, route: dict, account: str, text: str) -> bool:
    """A connection opened to LINK this account (a person adding it in "Your channels"): its YES lands the link at once
    (link_land, the one landing the web's code confirm uses too) and astryx confirms to the account itself, through
    the provider: no agent is woken or named (owner 11-18). True when handled (the bridge stops there); anything else
    is an ordinary message to the connection's agent."""
    if route.get("purpose") != "link" or not YES.match(text or ""):
        return False
    try:
        person = await pool.fetchval("SELECT link_land($1, $2)", route["connection"], str(account))
    except Exception as e:  # noqa: BLE001 — refused (already someone else's) or lapsed: an ordinary message then
        print(f"{channel}: link of connection {route.get('connection')} REFUSED ({str(e).splitlines()[0][:120]})", flush=True)
        return False
    from astryx.core.connect import linked_text
    from bridges.providers import registry
    await registry.send(f"{channel}:{route['chat']}", linked_text(channel, person))
    return True


BOOKS: dict[str, "Book"] = {}  # each bridge's Book by channel: the door re-reads one on a miss


class Book:
    """A bridge's ROUTES, from the one route table (astryx.core.routes; owner 11-16: "just route table"): read once at
    start, then every EVERY seconds, so an edit on the rail or an agent's connect reaches the bridge within seconds, no
    restart. Readers ask .routes() (sync, as they always did): the last table read, resolved by the one resolver
    (.chat(id), .doorbell(agent)). A read that fails keeps the last good table and says so once (BC-3): a database
    blip never unroutes a chat."""
    EVERY = 3.0

    def __init__(self, channel: str):
        self.channel, self.table, self.failing = channel, resolve([]), False
        BOOKS[channel] = self

    def routes(self) -> Routes:
        return self.table

    async def refresh(self, pool) -> None:
        from astryx.core import routes as table
        try:
            self.table = resolve(await table.load(pool, self.channel))
            if self.failing:
                print(f"{self.channel}: routes read again ({len(self.table)} enabled)", flush=True)
            self.failing = False
        except Exception as e:  # noqa: BLE001 — keep the last good table
            if not self.failing:
                print(f"{self.channel}: routes ALARM: the route table did not read ({type(e).__name__}); keeping the last "
                      f"good table ({len(self.table)} routes)", file=sys.stderr, flush=True)
            self.failing = True

    async def follow(self, pool) -> None:
        while True:
            await asyncio.sleep(self.EVERY)
            await self.refresh(pool)


# --------------------------------------------------------------------- routing
AGENTS_DIR = ESTATE / "agents"
_MENTION = re.compile(r"(?:^|\s)@([a-z][a-z0-9_-]*)", re.I)


def agent_exists(name: str) -> bool:
    """True if `name` is a charter anywhere in the agents/ tree."""
    return bool(name) and any(AGENTS_DIR.rglob(f"{name}.md"))


def address_agent(text: str, default: str) -> tuple[str, str]:
    """Route a message to an @mentioned agent, wherever the mention sits.

    "Hi @canopus" and "@canopus hi" both reach canopus (a human mentions naturally,
    not always at the start). The @mention token is KEPT in the delivered text so the
    tagged agent can see it was explicitly addressed (not a sticky-route continuation)
    — on a group several agents share, the agent otherwise can't tell it was the
    addressee and may ask which of them was meant. The @ must open a word,
    so "a@b.com" is not a mention, and an @name with no matching charter falls back to
    the default surface agent — a typo never eats the message. Returns (agent, text)."""
    for m in _MENTION.finditer(text):
        name = m.group(1).lower()
        if agent_exists(name):
            return name, text
    return default, text


def team_of(text: str) -> list[str]:
    """Every agent @mentioned in `text`, in the order the human named them, each once. Two or more is a TEAM: the
    message fans out to each, and the first named LEADS (owner 11-13: "@lending, @seed work together"). Names with
    no charter are skipped, exactly as address_agent skips them."""
    team: list[str] = []
    for m in _MENTION.finditer(text or ""):
        name = m.group(1).lower()
        if name not in team and agent_exists(name):
            team.append(name)
    return team


def team_stamp(team: list[str]) -> dict:
    """The delivery fields a fanned-out row carries ({} for one agent): the members in order and the lead. The
    channel server turns them into each member's prompt line (channel/team.mjs); nothing new on the wire."""
    return {"team": list(team), "lead": team[0]} if len(team) > 1 else {}


async def wire_chat(pool, who: str, org: str, default: str, thread: str, text: str, meta: dict | None,
                    route: dict | None = None, said: str | None = None) -> list[str]:
    """A human's CHAT onto the wire, for every bridge: one agent as before (route_target's precedence), or, when the
    message names two or more agents, one row per member stamped with the team. The lead's row is written LAST, so
    route_target's "whoever the human last addressed" carries a bare follow-up to the lead. A tier route has one
    reader and never fans out (wire_insert sends it to the route's agent). Returns the agents written to."""
    team = team_of(text)
    tiered = False
    if route is not None:
        from astryx.security import release as R
        try:
            tiered = R.route_tier(route) is not None
        except R.GrantError:
            tiered = True
    if len(team) < 2 or tiered:
        agent, text = await route_target(pool, thread, text, default, (meta or {}).get("reply_to_id") or "")
        await wire_insert(pool, who, org, agent, thread, "chat", text, meta, route=route, said=said)
        return [agent]
    stamp = team_stamp(team)
    for agent in team[1:] + team[:1]:                # helpers first, the lead last (the sticky follow-up)
        await wire_insert(pool, who, org, agent, thread, "chat", text, {**(meta or {}), **stamp},
                          route=route, said=said)
    return team


# The human's inbound that ANSWERS an agent: a poll vote, the one structured answer bridges issue
# ids for (live inbound intents: chat, poll, reaction; there's no inbound 'permission', since an
# answer to a permission prompt arrives as chat). NAMED POSITIVELY, because the failure directions
# differ. An intent that wrongly counts can steal the next reply: a REACTION can target any old
# message (abstractor-2 #33265). One that wrongly doesn't count falls back to the last agent
# message the human saw, which is usually the agent that asked anyway.
ANSWER_INTENTS = frozenset({"poll"})


async def route_target(pool, thread: str, text: str, default: str, reply_to: str = "") -> tuple[str, str]:
    """Resolve which agent an inbound message routes to, and clean the text.

    PRECEDENCE (seed #33255/#33256/#33262):
      1. an explicit @mention on THIS message, always. It routes only the message that
         carries it; it does NOT stick;
      2. otherwise, when the message REPLIES to an agent's message on this thread (`reply_to`, the platform id of the
         quoted message, matched against the delivery.message_id we stored when we sent it), that agent (owner
         15960: "when someone replies to a message, that agent should be called and not the recent one");
      3. otherwise the newest thing an agent put in front of the human, which is either
           - an agent's message TO THE HUMAN (ANY intent: chat, poll, receipt, permission…),
             counted as its from_agent, or
           - the human's ANSWER to an agent (ANSWER_INTENTS: a poll vote), counted as its
             to_agent, or
           - the human's own CHAT, counted as its to_agent: a bare follow-up goes on to whoever
             the human last addressed, even before that agent has answered (owner 10-27:
             "@b …" then "…" while b was still working went back to a).
         Newest wins, so a past @mention still can't pull the next plain reply away from an
         agent that spoke to the human since. Reactions (which can point at any old message)
         don't count;
      4. otherwise `default` (the surface's own agent).
    "To the human" means to a non-agent: the registry of agents is the one authority, so
    'owner' and every wa-/dc-/tg- person qualify with no name typed here. That's also what
    lets an agent that STARTS a thread get the first reply.

    What the human SAW is the rule, not an intent allowlist (abstractor-2 #33257): a receipt
    or permission prompt the bridge renders is the agent speaking, as far as the human can
    tell. An agent-to-AGENT handoff on the thread (seed → canopus) is not "the conversation",
    so it never steals the human's next reply. Names with no charter (pulse) are skipped. The
    wire is the state."""
    agent, cleaned = address_agent(text, "")
    if agent:                                    # 1. explicit @mention on this message
        return agent, cleaned
    if reply_to:                                 # 2. a reply to an agent's message on THIS thread
        r = await pool.fetchrow(
            "SELECT from_agent FROM messages WHERE thread=$1 AND from_org='local' "
            "AND (delivery->>'message_id'=$2 OR delivery->'message_ids' ? $2) ORDER BY id DESC LIMIT 1",
            thread, str(reply_to))
        if r and agent_exists(r["from_agent"]):
            return r["from_agent"], text
    rows = await pool.fetch(
        "SELECT from_org, from_agent, to_agent, intent FROM messages WHERE thread=$1 "
        "ORDER BY id DESC LIMIT 50", thread)
    for r in rows:                               # 3. newest first
        if r["from_org"] != "local":             # the human's own message: an ANSWER, or a chat
            if r["intent"] not in ANSWER_INTENTS and r["intent"] != "chat":  # a reaction: no
                continue
            who = r["to_agent"]                  # whoever the human last addressed (owner 10-27)
        elif not agent_exists(r["to_agent"]):    # an agent speaking TO the human
            who = r["from_agent"]
        else:                                    # agent-to-agent: not the conversation
            continue
        if agent_exists(who):
            return who, text
    return default, text                         # 4.


# ---------------------------------------------------------------------- embeds
def split_files(text: str) -> tuple[str, list[str]]:
    """Pull [[file:/abs/path]] tokens out of an outbound body."""
    files, keep = [], text
    while "[[file:" in keep:
        pre, _, rest = keep.partition("[[file:")
        path, sep, post = rest.partition("]]")
        if not sep:
            break
        files.append(path.strip())
        keep = pre + post
    return keep.strip(), files


def split_polls(text: str, max_options: int = 12) -> tuple[str, list[tuple[str, list[str], int]]]:
    """Pull [[poll: q | opt | opt | multi=N]] tokens out of an outbound body."""
    specs = []
    for m in POLL_RE.finditer(text):
        parts = [p.strip() for p in m.group(1).split("|") if p.strip()]
        multi = 1
        if parts and parts[-1].lower().replace(" ", "").startswith("multi="):
            try:
                multi = max(1, int(parts.pop().split("=", 1)[1]))
            except ValueError:
                pass
        if len(parts) >= 3:                     # question + at least 2 options
            specs.append((parts[0], parts[1:1 + max_options], multi))
    return POLL_RE.sub("", text).strip(), specs


# ----------------------------------------------------------------------- wire
async def wire_insert(pool, from_agent: str, from_org: str, to_agent: str,
                      thread: str | None, intent: str, body: str, meta: dict | None = None,
                      route: dict | None = None, said: str | None = None):
    # `meta` carries INBOUND context the wire row otherwise loses: the real sender identity
    # (jid/phone/push_name — from_agent collapses a trusted sender to 'owner') and reply/quote
    # context (which message it answered, + that message's body). Stored in the `delivery`
    # jsonb, which is unused on an inbound row. server.mjs surfaces it on the <channel> tag.
    #
    # `route` (plan-9139 S1b-2b): the inbound chat sites pass the route the message arrived on. A route that
    # DECLARES a tier, or anything that looks like one, never reaches the raw row: see _tier_ingress. `said` is the text
    # as the human typed it, before route_target stripped an @mention: a tier route stores THAT (a4 #53081), so its
    # member sees who the owner tried to address.
    if route is not None:
        from astryx.security import release as R
        try:
            tiered = R.route_tier(route) is not None
        except R.GrantError:
            tiered = True                      # a malformed declaration is judged (and refused) by the door
        if tiered:
            text = body if said is None else said
            return await _tier_ingress(pool, R, from_agent, from_org, thread, intent, text, meta, route)
    await pool.execute(
        "INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body, delivery) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7)", from_agent, from_org, to_agent, thread, intent, body,
        json.dumps(meta) if meta else None)


# identity fields an inbound row carries today on every owner message; anything else in meta (the quoted reply's
# BODY, above all) is content, so on a tier route it travels inside the stored body, never in `delivery`
_INGRESS_META = ("sender_jid", "phone", "push_name", "sender_id", "username", "display_name", "reply_to_id",
                 "reply_to_sender_jid")


async def _tier_ingress(pool, R, from_agent, from_org, thread, intent, body, meta, route):
    """An inbound message on a tier route (#46033 item 4). The row goes to the ROUTE's agent only, never to an
    @mention's (a pointer there is unreadable, and the private surface has one reader); its body is a size marker;
    delivery carries the pointer, keyed body MAC and tier, plus the identity fields. A quoted reply's text rides in
    the stored body. Any refusal (a malformed or undeclared tier, an open route, a non-owner audience, no key)
    stores NOTHING and writes a metadata-only WITHHELD row, so the owner's message is never silently lost."""
    meta = dict(meta or {})
    quoted = meta.pop("reply_to_body", "") or ""
    stored = f"{body}\n[in reply to: {quoted}]" if quoted else body
    keep = {k: meta[k] for k in _INGRESS_META if k in meta}
    try:
        marker, extra = R.ingress(from_org, route, stored, R.mac_key(), R.TierStore())
        out, delivery = marker, {**keep, **extra}
    except R.Refused as e:
        print(f"tier ingress REFUSED on {thread}: {e} (the message was withheld; nothing stored)", flush=True)
        out = "[tier-routed message withheld: " + type(e).__name__ + "]"
        delivery = {**keep, "ingress_withheld": str(e)[:200]}
    await pool.execute(
        "INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body, delivery) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7)", from_agent, from_org, route.get("agent"), thread, intent, out,
        json.dumps(delivery))


async def resolve_quoted_body(pool, rid) -> str:
    """A quoted reply carries an id; resolve it to the ORIGINAL message text from what we
    stored — our own sends carry the platform message id in delivery.message_id, and an
    inbound row's own id also matches. Empty if we never saw it. Channel-agnostic; every
    bridge falls back to this when the platform payload doesn't include the quoted text."""
    r = await pool.fetchrow(
        "SELECT body FROM messages WHERE delivery->>'message_id'=$1 OR id::text=$1 "
        "ORDER BY id DESC LIMIT 1", str(rid))
    return r["body"] if r else ""


# -------------------------------------------------------------------- reactions
async def reacted_message(pool, thread: str, target_msg_id: str) -> tuple:
    """(agent, snippet) for the message a reaction targets, from the delivery id we
    stored when we sent it — or (None, None) if we never recorded it. For channels
    that can't fetch the message back from the platform."""
    rec = await pool.fetchrow(
        "SELECT from_agent, body FROM messages WHERE thread=$1 "
        "AND delivery->>'message_id'=$2 ORDER BY id DESC LIMIT 1", thread, str(target_msg_id))
    return (rec["from_agent"], rec["body"]) if rec else (None, None)


async def reaction_signal(pool, channel: str, thread: str, reactor: str,
                          emoji: str, agent: str, snippet: str | None) -> None:
    """Deliver a reaction as a wire signal to `agent`, quoting the message reacted
    to. A pure formatter: the bridge resolves who sent the message and what it said
    from its platform (the source of truth), since that differs per channel."""
    quoted = (snippet or "a message").strip().replace("\n", " ")[:100]
    emoji = emoji[:32]                            # an emoji is a few code points; a client can send any string (a4 A-1)
    await wire_insert(pool, reactor, channel, agent, thread, "reaction",
                      f'reacted {emoji} to: "{quoted}"')


# ----------------------------------------------------------------------- polls
class Outcome:
    """The delivery receipt's producer — it reports THE WORK, not the wrapper.

    Every bridge's `deliver()` used to open with `ok, message_id, error = True, None, None`
    and wrap the whole body in one try, while each inner step swallowed its own failure
    (`except Exception: pass`, a silent `if p.is_file():`, a `(poll failed)` note that
    never touched `ok`). So the row stamped `delivered` whenever the OUTER try didn't
    throw — i.e. it recorded that the wrapper survived, not that anything arrived. Three
    separate reports in 24h (canopus msgs 3468/4510/5707, gemini 4669) were that one
    sentence in three costumes.

    `ok` is the AND of every part, so ANY failed part marks the row `dead` and canopus's
    existing `outbound_undelivered` guard sees it within the hour. That is deliberate:
    the repair routes failure into the detector the org already has instead of adding a
    second one — a detector cannot witness its own producer being wrong, so a falsely
    settled row is invisible to every guard of that shape by construction.

    PARTIAL SUCCESS IS PRESERVED, NOT FLATTENED. A body whose text lands and whose poll
    fails is not the same event as nothing arriving, and collapsing them loses what the
    reader needs. `message_id` still records the text that landed and `error` names each
    failed part in order, so the receipt distinguishes "nothing arrived" (`message_id`
    null) from "text arrived, poll didn't" (`message_id` set, `error` names the poll).

    The receipt SCHEMA is unchanged — same five keys. Only its honesty changes.
    """

    def __init__(self):
        self.message_id: str | None = None
        self.message_ids: list[str] = []             # every part's platform id (text parts, files), in order
        self._entries: list[tuple[bool, str]] = []   # (is_failure, text), in order
        self._kinds: list[str] = []                  # each FAILURE as "part: ExceptionType" (no platform text)

    def sent(self, message_id=None) -> None:
        """A part succeeded; keep the first real platform id (the text's) for the row, and every id in message_ids, so
        a reply quoting ANY part (a file, a later chunk) finds its agent (medic 15971)."""
        if message_id:
            self.message_ids.append(str(message_id))
        if message_id and not self.message_id:
            self.message_id = str(message_id)

    def failed(self, part: str, detail) -> None:
        """A part FAILED — something was attempted and did not arrive. Fails the row."""
        self._entries.append((True, f"{part}: {self._say(detail)}"[:200]))
        self._kinds.append(f"{part}: {type(detail).__name__ if isinstance(detail, BaseException) else 'failed'}")

    def noted(self, part: str, detail) -> None:
        """A part was DELIBERATELY NOT ATTEMPTED — reported, but does NOT fail the row.

        gemini's catch (msg 5981), and it is the mirror of the bug this class exists for.
        `WA_DATA_HOST` unset is not broken configuration: `whatsapp.py:55` documents it as
        the surface's media on/off switch. Treating an operator's deliberate setting as a
        hard failure would install a FALSE FAILURE in the same breath as we removed a false
        success — and it would fail rows whose text genuinely delivered. But a caller who
        attached a file still had it silently dropped, which deserves a receipt. So the two
        cases get different answers rather than one of them getting the wrong one.
        """
        self._entries.append((False, f"note: {part}: {self._say(detail)}"[:200]))

    @staticmethod
    def _say(detail) -> str:
        return (f"{type(detail).__name__}: {detail}"
                if isinstance(detail, BaseException) else str(detail))

    @property
    def ok(self) -> bool:
        return not any(is_failure for is_failure, _ in self._entries)

    @property
    def error(self) -> str | None:
        # Failures first so the reason a row is `dead` is never buried behind a note.
        ordered = ([t for f, t in self._entries if f]
                   + [t for f, t in self._entries if not f])
        return "; ".join(ordered)[:500] or None

    @property
    def status(self) -> str:
        return "delivered" if self.ok else "dead"

    @property
    def classified(self) -> str | None:
        """`error` cut to each failure's PART and exception TYPE, recorded when it failed: never the platform's text.
        A failed released send's str(e) is the CLI's or the API's own words, which may name the chat (a4 #53846).
        Notes are dropped: they say what was not attempted, and their detail is free text too."""
        return "; ".join(self._kinds)[:500] or None

    def receipt(self, handle: str, rendered: str | None, door: str | None = None, classified: bool = False) -> str:
        # `door` (plan-9139 S1c): how the row passed the door. "org-unstamped" is the CENSUS mark (a delivered row
        # no stamp covered, to a declared org route); "released" a stamped row. Additive: the five keys are unchanged.
        # `classified` (a released row): `error` carries part and exception type only, never the platform's text.
        r = {"ok": self.ok, "handle": handle, "message_id": self.message_id, "rendered": rendered,
             "error": self.classified if classified else self.error}
        if self.message_ids:
            r["message_ids"] = self.message_ids
        if door:
            r["door"] = door
        return json.dumps(r)


# ----------------------------------------------------------------------- the door
# plan-9139 S1c (a4 #45091): every chat bridge's deliver() asks the door FIRST. A row carrying delivery.release is
# delivered only through release.door_stamped (its stamp names the route; the body comes from the tier store); any
# other row only to a DECLARED ORG ROUTE of the bridge (release.door_org), and the receipt carries the census mark.
# Everything else is REFUSED: status 'refused' (terminal: outbound_stuck watches it, nothing re-tries it), the reason
# in delivery.door_refused. The release key is read only on the stamped branch: an unstamped row needs none.
def _release():
    from astryx.security import release as R
    return R


def released(row) -> dict | None:
    return _release().released(row)


async def door_refuse(pool, row, channel: str, reason) -> None:
    why = (f"{type(reason).__name__}: {reason}" if isinstance(reason, BaseException) else str(reason))[:200]
    print(f"{channel}: the door REFUSED outbound msg {row['id']}: {why}", flush=True)
    await pool.execute(
        "UPDATE messages SET status='refused', delivered_at=now(), "
        "delivery = coalesce(delivery, '{}'::jsonb) || $2::jsonb WHERE id=$1 AND status='pending'",
        row["id"], json.dumps({"ok": False, "handle": f"{channel}:door", "message_id": None, "rendered": None,
                               "error": None, "door_refused": why}))


async def door_open(pool, row, channel: str, routes) -> tuple[dict, str] | None:
    """A RELEASED row: (its route, the resolved body) when this bridge delivers it. None when it is another bridge's
    (left pending, untouched) or when the door refused it (status 'refused' written). Never raises."""
    R = _release()
    if (R.released(row) or {}).get("channel") != channel:
        return None                                # another bridge's release: its own consumer delivers it
    try:
        return R.door_stamped(row, channel, routes, key=R.mac_key(), store=R.TierStore())
    except Exception as e:                         # noqa: BLE001 — Refused, or a store that can't be read: refuse
        await door_refuse(pool, row, channel, e if isinstance(e, R.Refused) else type(e).__name__)
        return None


async def cap_spent(pool, row, channel: str, cap: int) -> bool:
    """A channel that reaches people outside the org (SMS, email) bounds what it sends in a day: this send takes one
    of today's `cap` (send_take, atomic: a burst never overshoots), or the row is refused saying the cap is spent."""
    if await pool.fetchval("SELECT send_take($1, $2)", channel, cap):
        return False
    await door_refuse(pool, row, channel, f"the org's {channels.BY_NAME[channel].title} cap for today ({cap}) is spent")
    return True


async def door_org_ok(pool, row, channel: str, routes, chat) -> bool:
    """An UNSTAMPED row: True when `chat` is a declared org route of this bridge; else the row is refused. A miss re-reads
    the route table once first: a route opened in the same breath as its message (a link's "Reply YES", 13614) is
    newer than the Book's last 3-second read, and refusing it would drop the one message that route exists for."""
    R = _release()
    try:
        R.door_org(channel, chat, routes)
        return True
    except R.Refused as e:
        book = BOOKS.get(channel)
        if book is not None:
            await book.refresh(pool)
            try:
                R.door_org(channel, chat, book.routes())
                return True
            except R.Refused as again:
                e = again
        await door_refuse(pool, row, channel, e)
        return False


# The sender's label on a channel where every agent shares ONE identity (one WhatsApp number, one Telegram bot, a
# Discord bot without a webhook): "▸ <agent>" on its own line, then the body. `bold` is the channel's own markup
# (WhatsApp *x*, Discord **x**, Telegram plain text: none). A route with `"signed": false` stays unlabelled: an agent
# speaking there in the owner's voice. Idempotent (an edited bubble is never signed twice).
SIGN = "\u25b8 "


def signed(agent: str, text: str, route: dict | None, bold: str = "") -> str:
    if route is not None and route.get("signed") is False:
        return text
    label = f"{SIGN}{bold}{agent}{bold}\n"
    return text if not text or text.startswith(label) else label + text


def live_steps_ok(route) -> bool:
    return _release().live_steps_ok(route)



async def record_poll(pool, msg_id: str, chat: str, agent: str | None,
                      question: str, options: list[str], multi: int):
    """Record a poll the moment it exists (agent-sent or externally seen)."""
    await pool.execute(
        "INSERT INTO polls (msg_id, chat, agent, question, options, multi) "
        "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (msg_id) DO NOTHING",
        msg_id, chat, agent, question, json.dumps(options), multi)


async def update_poll_votes(pool, msg_id: str, aggregates: dict,
                            voters: list[dict]) -> dict:
    """Persist the new vote snapshot; returns the PREVIOUS votes for delta calc."""
    prev = await pool.fetchrow("SELECT votes FROM polls WHERE msg_id=$1", msg_id)
    old = json.loads(prev["votes"]) if prev and prev["votes"] else {}
    await pool.execute(
        "UPDATE polls SET votes=$2, updated_at=now() WHERE msg_id=$1",
        msg_id, json.dumps({"aggregates": aggregates, "voters": voters}))
    return old


def vote_changes(old_votes: dict, voters: list[dict]) -> list[str]:
    """Human lines for what CHANGED between snapshots — voter identity comes
    from the store's own list, never the webhook sender id."""
    old_sel = {v.get("jid"): v.get("selected") or []
               for v in (old_votes.get("voters") or [])}
    changes = []
    for v in voters:
        if (v.get("selected") or []) != old_sel.get(v.get("jid"), []):
            nm = v.get("name") or str(v.get("jid", "?")).split("@")[0]
            changes.append(f'{nm} → {", ".join(v.get("selected") or ["(retracted)"])}')
    gone = set(old_sel) - {v.get("jid") for v in voters}
    changes += [f'{str(j).split("@")[0]} retracted their vote' for j in gone if old_sel[j]]
    return changes


def vote_body(question: str, changes: list[str], aggregates: dict) -> str:
    totals = " · ".join(f"{k}: {v}" for k, v in (aggregates or {}).items() if v)
    return (f'poll answer — "{question}"\n'
            + ("; ".join(changes) or "no net change")
            + f'\ntotals so far: {totals or "no votes"}')


# ----------------------------------------------------------------------- media
def media_path(prefix: str, name: str, sub: str | None = None) -> Path:
    """Where an inbound file lands. The name carries a RANDOM token, never a timestamp: a guessable
    name lets anyone who can make the server read a path enumerate other people's files (steward
    #37433). `sub` puts it in its uploader's own folder (canvas: media/cv/<wire handle>/)."""
    d = MEDIA_DIR / sub if sub else MEDIA_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{prefix}-{secrets.token_hex(12)}-{name}"


async def describe_media(path: Path | str, kind: str = "") -> str:
    """The body line for an inbound file. Audio gets its transcript inline —
    the one sense agents lack; everything else is delivered clean (agents
    read images natively; a caption would be a worse copy of their own eyes)."""
    p = Path(path)
    if kind.lower() in AUDIO_KINDS:
        t = await transcribe(p)
        if t:
            return f"<voice attached: {p}>\n(transcript: {t})"
        return f"<voice attached: {p}>"
    return f"<file attached: {p}>"


# -------------------------------------------------------------------- progress
async def step_line(pool, step_id: int, kind: str, *, agent: str, label: str = "", thread: str | None = None) -> str | None:
    """The steps doorbell payload is {id, agent, kind} only — fetch the content.

    `agent` is the payload's agent and is REQUIRED: the row must belong to it, so a payload
    whose id names another agent's step resolves to nothing (defense in depth, a4 #22117).
    It is deliberately separate from `label`, the optional display prefix (useful on
    group-chat surfaces), because telegram/discord show no label, and matching on their ""
    would be matching on nothing. An empty agent never matches.

    `thread` (a progress job's own chat, owner 11-15): only a step of a turn THIS thread opened is a line for it. The
    hook stamps meta.turn_msgs, the msg_ids that opened the step's turn (hooks/step.py turn_msgs); a step whose turn was
    opened on another thread (a member's web ask, seed's task, another group) is the agent's work for someone else and
    never lands here (medic 12159). A step with no stamp has no known scope: nothing, never everything."""
    return (await scoped_line(pool, step_id, kind, agent=agent, label=label, thread=thread))[1]


async def scoped_line(pool, step_id: int, kind: str, *, agent: str, label: str = "",
                      thread: str | None = None) -> tuple[str | None, str | None]:
    """(role, line): step_line's line and what the step is to `thread` (_role: 'serves', 'many', 'acked', 'waiting';
    'serves' for an unscoped caller). A progress job uses the role: a chat already answered gets no content-free line."""
    if kind not in MARK or not agent:
        return None, None
    row = await pool.fetchrow("SELECT content, meta FROM steps WHERE id=$1 AND agent=$2",
                              step_id, agent)
    if not row:
        return None, None
    role = "serves"
    if thread is not None:
        role, n, since = await _role(pool, row["meta"], thread)
        if role is None:
            return None, None
        if role != "serves":                       # another chat's work: said without its content (DESIGN, 11-18)
            return role, _elsewhere(role, n, since)
    content = "writing a reply" if kind == "response" else row["content"]
    prefix = f"{label} · " if label else ""
    sub = _sub_of(row["meta"])
    if sub:                                        # a helper the agent launched (hooks/step.py scope): say whose step
        prefix += f"↳ {sub} · "
    return role, f"{MARK[kind]} {prefix}{content[:140]}"


def _sub_of(meta) -> str:
    """A helper's name for its step's line: its task description, else its type ("helper" when neither is known)."""
    try:
        m = json.loads(meta) if isinstance(meta, str) else (meta or {})
        sub = m.get("sub")
        if not isinstance(sub, dict):
            return ""
        return (str(sub.get("desc") or sub.get("type") or "helper"))[:40]
    except Exception:
        return ""


def _meta(meta) -> dict:
    try:
        m = json.loads(meta) if isinstance(meta, str) else (meta or {})
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def _ids(m: dict, key: str) -> list[int]:
    try:
        return [int(x) for x in (m.get(key) or [])][:20]
    except Exception:
        return []


async def _role(pool, meta, thread: str) -> tuple[str | None, int, int]:
    """What a step is to `thread`'s chat (hooks/step.py stamps the scope): 'serves' (its request is being worked on),
    'many' (the agent's work can't be told apart), 'acked' / 'waiting' (it waits behind another request), or None.
    Returns (role, the number of chats in `many`, since). One lookup: the threads of every id the step names."""
    m = _meta(meta)
    keys = ("turn_msgs", "many", "acked", "waiting")
    ids = {k: _ids(m, k) for k in keys}
    every = sorted({i for v in ids.values() for i in v})
    if not every:
        return None, 0, 0
    th = {r["id"]: r["thread"] for r in await pool.fetch("SELECT id, thread FROM messages WHERE id = ANY($1::bigint[])",
                                                          every)}
    since = int(m.get("since") or 0)
    for k, role in zip(keys, ("serves", "many", "acked", "waiting")):
        if any(th.get(i) == thread for i in ids[k]):
            return role, len({th.get(i) for i in ids["many"]} - {None}), since
    return None, 0, 0


async def _serves(pool, meta, thread: str) -> bool:
    """Was the step's turn opened by a message on `thread`? (meta.turn_msgs; see step_line)"""
    return (await _role(pool, meta, thread))[0] == "serves"


def _elsewhere(role: str, n: int, since: int) -> str:
    """The content-free line for a chat whose request is not the one being worked on."""
    if role == "many":
        return f"◌ working on {max(n, 2)} requests (yours included)"
    if role == "acked":
        return "◌ on it: starting after the current task"
    mins = int((time.time() - since) // 60) if since else 0
    return "◌ queued: finishing another request first; yours is next" + (f" (busy {mins} min so far)" if mins >= 2 else "")


# -------------------------------------------------------------------- doorbell
async def listen(dsn: str, pending_where: str, deliver, on_step, on_idle=None):
    """The reconnecting wire tap every bridge runs: LISTEN astryx_wire +
    astryx_steps; on wire ring, claim this surface's pending rows via
    `pending_where` and hand each to deliver(row); steps go to on_step(ev).

    on_idle (optional): an async no-arg callback invoked once per inner-loop pass —
    at least every 60s (the q.get timeout), more often when the wire is busy. It rides
    this existing periodic path so a bridge can run a lightweight watcher WITHOUT a
    second timer or task. It is called inside a try/except that swallows everything: a
    rider's fault must never break this bridge's message delivery. Only whatsapp passes
    one today (the pulse-liveness witness, bridges/pulse_witness.py); the other bridges
    leave it None and are unaffected."""
    while True:
        try:
            conn = await asyncpg.connect(dsn)
            q: asyncio.Queue = asyncio.Queue()
            # cog-rls slice 3: this org's channels (ax<n>_wire/_steps), dispatched below by their logical names
            from astryx.pg import channels
            await channels.listen(conn, ("wire", "steps"), lambda chan, payload: q.put_nowait((chan, payload)))
            conn.add_termination_listener(lambda c: q.put_nowait(("__dead__", "")))
            while True:
                if on_idle is not None:
                    try:
                        await on_idle()
                    except Exception:
                        pass          # the wire tap never breaks for a rider's fault
                try:
                    chan, payload = await asyncio.wait_for(q.get(), timeout=60)
                except asyncio.TimeoutError:
                    if conn.is_closed():
                        raise ConnectionError("pg lost")
                    continue
                if chan == "__dead__":
                    raise ConnectionError("pg terminated")
                if chan == "astryx_steps":
                    try:
                        ev = json.loads(payload)
                    except Exception:
                        continue
                    await on_step(ev)
                    continue
                rows = await conn.fetch(
                    "SELECT * FROM messages WHERE status='pending' "
                    f"AND to_org='local' AND ({pending_where})")
                for row in rows:
                    await deliver(row)
        except Exception:
            await asyncio.sleep(3)
