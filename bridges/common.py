"""bridges/common.py — everything every CHAT surface shares, written once.

Scope: the chat-bridge family (whatsapp, telegram, discord) ONLY. gateway.py
(federation door) and geoloc.py (sensor intake) are deliberately independent
loose scripts — folding them in would couple the federation/sensor graphs to
the chat+ASR dependency tree for ~10 shared lines. Duplication beats coupling
at that size.

A chat bridge translates ONE platform to the wire; anything that isn't
platform translation lives here:

  config       env() reads .env; load_routes() re-reads a routes file per use
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
import time
from pathlib import Path

import asyncpg

from .transcribe import transcribe

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MEDIA_DIR = REPO / "media"

MARK = {"tool": "◌", "tool_done": "●", "error": "⚠", "response": "◌"}
POLL_RE = re.compile(r"\[\[poll:(.+?)\]\]", re.S)
AUDIO_KINDS = {"voice", "audio", "ptt"}


# ---------------------------------------------------------------------- config
def env(key: str, default: str = "") -> str:
    if os.environ.get(key):
        return os.environ[key]
    f = REPO / ".env"
    if f.is_file():
        for line in f.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return default


def load_routes(path: Path) -> list[dict]:
    """Re-read per use so routes can be edited live, no restart."""
    try:
        return [r for r in json.loads(path.read_text()) if r.get("enabled")]
    except Exception:
        return []


# --------------------------------------------------------------------- routing
AGENTS_DIR = REPO / "agents"
_MENTION = re.compile(r"(?:^|\s)@([a-z][a-z0-9_-]*)", re.I)


def agent_exists(name: str) -> bool:
    """True if `name` is a charter anywhere in the agents/ tree."""
    return bool(name) and any(AGENTS_DIR.rglob(f"{name}.md"))


def address_agent(text: str, default: str) -> tuple[str, str]:
    """Route a message to an @mentioned agent, wherever the mention sits.

    "Hi @canopus" and "@canopus hi" both reach canopus (a human mentions naturally,
    not always at the start); the mention token is stripped from the delivered text.
    The @ must open a word, so "a@b.com" is not a mention, and an @name with no
    matching charter falls back to the default surface agent — a typo never eats
    the message. Returns (agent, cleaned_text)."""
    for m in _MENTION.finditer(text):
        name = m.group(1).lower()
        if agent_exists(name):
            cleaned = (text[:m.start()] + " " + text[m.end():]).strip()
            return name, cleaned or text
    return default, text


async def route_target(pool, thread: str, text: str, default: str) -> tuple[str, str]:
    """Resolve which agent an inbound message routes to, and clean the text.

    The conversation is sticky: an @mention wins for this message and — because it
    becomes the message's to_agent on the wire — sets the thread's target going
    forward. With no mention, the message continues to the LAST agent addressed on
    this thread, so a chat stays with whoever you last tagged until you tag someone
    else. A fresh thread falls back to `default` (the surface's own agent). The wire
    is the state: "last tagged" is just the previous inbound message's to_agent.
    Standard on every channel."""
    agent, cleaned = address_agent(text, "")
    if agent:                                    # explicit @mention on this message
        return agent, cleaned
    row = await pool.fetchrow(
        "SELECT to_agent FROM messages WHERE thread=$1 AND intent='chat' "
        "AND from_org<>'local' AND to_org='local' ORDER BY id DESC LIMIT 1", thread)
    if row and agent_exists(row["to_agent"]):
        return row["to_agent"], text
    return default, text


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
                      thread: str | None, intent: str, body: str):
    await pool.execute(
        "INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body) "
        "VALUES ($1,$2,$3,$4,$5,$6)", from_agent, from_org, to_agent, thread, intent, body)


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
    await wire_insert(pool, reactor, channel, agent, thread, "reaction",
                      f'reacted {emoji} to: "{quoted}"')


# ----------------------------------------------------------------------- polls
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
def media_path(prefix: str, name: str) -> Path:
    MEDIA_DIR.mkdir(exist_ok=True)
    return MEDIA_DIR / f"{prefix}-{int(time.time())}-{name}"


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
async def step_line(pool, step_id: int, kind: str, agent: str = "") -> str | None:
    """The steps doorbell payload is {id, agent, kind} only — fetch the content.
    Pass agent to label the line (useful on group-chat surfaces)."""
    if kind not in MARK:
        return None
    row = await pool.fetchrow("SELECT content FROM steps WHERE id=$1", step_id)
    if not row:
        return None
    content = "writing a reply" if kind == "response" else row["content"]
    label = f"{agent} · " if agent else ""
    return f"{MARK[kind]} {label}{content[:140]}"


# -------------------------------------------------------------------- doorbell
async def listen(dsn: str, pending_where: str, deliver, on_step):
    """The reconnecting wire tap every bridge runs: LISTEN astryx_wire +
    astryx_steps; on wire ring, claim this surface's pending rows via
    `pending_where` and hand each to deliver(row); steps go to on_step(ev)."""
    while True:
        try:
            conn = await asyncpg.connect(dsn)
            q: asyncio.Queue = asyncio.Queue()
            for ch in ("astryx_wire", "astryx_steps"):
                await conn.add_listener(
                    ch, lambda c, p, chan, payload: q.put_nowait((chan, payload)))
            conn.add_termination_listener(lambda c: q.put_nowait(("__dead__", "")))
            while True:
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
