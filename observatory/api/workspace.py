"""astryx observatory · the chat WORKSPACE's server half (feat/chat-workspace, iteration 1).

The root cause this module exists for: /chat's sidebar listed only `chat:` threads, but the owner talks to agents on
three surfaces, each its own thread family on the ONE wire:

    chat:<day>-<rnd>   /chat itself (several agents, one thread)                    surface 'chat'
    obs:<agent>        the floor's desk sheet (components/ChatSheet.tsx); obs:library-*, obs:person-*, obs:estate
                       are the floor's other owner asks                               surface 'floor'
    cv:<hex>           a canvas chat (bridges/canvas.py; canvas_threads names the agent + a title)   surface 'canvas'

WhatsApp groups (wa:*) and every agent-to-agent thread are NOT the owner's conversations here and never listed.
A thread is listed only when the owner is a party of it (an invitee's canvas chat is theirs, not the owner's).

    GET /api/ws/threads         the unified list: thread, title, agents, surface, last_ts, preview, count, pinned, project
    PUT /api/ws/threads/meta    {thread, title?, pinned?}: a custom title / a pin, stored in <estate>/chat/threads.json
    GET /api/ws/agents          each agent's role (its charter's italic subtitle) and its last word to the owner
    GET /api/ws/handoffs        ?thread=: the turns that answered here but were STARTED by another agent's message
                                (a handoff into the conversation), each with that message (the payload)
    POST /api/ws/agents/{name}/interrupt   Stop: one Escape keystroke into the agent's tmux pane (its turn halts;
                                the session, its context and the wire are untouched)
    GET /api/ws/search          ?q=&limit=: full text over the message bodies of the SAME threads the list shows, newest
                                first, each hit a snippet (markers stripped) with the matched spans
    GET /api/ws/thread-titles   ?ids=a,b,c (≤40): each thread's name — an owner conversation's list title, any other
                                thread a ≤60-char label from its first message's first line (WhatsApp: its surface only)
    GET /api/ws/briefing        ?since=<iso> (default 12 h, at most 48 h back): "while you were away" — per agent its
                                counts, its messages TO THE OWNER as headlines (never bodies), files, top peers, whether
                                it waits on the owner; org-news headlines

OWNER-ONLY BY OMISSION, like chat.py: none of these paths is in main.PUBLIC, so the default-deny gate answers 403 to
anyone without the owner key before a handler runs. Writes go through hostfile.atomic_write with the etag read (one
writer, never a torn file, a lost race retried once on fresh bytes). The derivation is pure functions so
tests/test_ws_threads.py holds them without a database.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from observatory.api.hostfile import Conflict, atomic_write, etag

router = APIRouter()

_get_pool = None
ESTATE: Path | None = None
_roster = lambda: set()                            # noqa: E731 — the live agent names (main.agent_meta)
_charter = lambda name: None                       # noqa: E731 — name -> its charter Path (main._charter_path)
_owner = lambda request: False                     # noqa: E731 — main.owner_call; unbound = nobody (deny by default)

SURFACES = {"chat:": "chat", "obs:": "floor", "cv:": "canvas"}
TITLE_MAX = 80
PREVIEW_MAX = 140


def bind(get_pool, estate: Path, roster=None, charter=None, owner=None) -> None:
    """The host app hands over its pool getter, its estate, its roster, its charter resolver and its owner check
    (read at call time)."""
    global _get_pool, ESTATE, _roster, _charter, _owner
    _get_pool, ESTATE = get_pool, Path(estate)
    if roster is not None:
        _roster = roster
    if charter is not None:
        _charter = charter
    if owner is not None:
        _owner = owner


def meta_file() -> Path:
    return ESTATE / "chat" / "threads.json"


# ------------------------------------------------------------------------------------------------ pure derivation
def surface_of(thread: str | None) -> str | None:
    """Which owner surface a thread belongs to, or None (WhatsApp, plan threads, agent-to-agent: not listed)."""
    for prefix, surface in SURFACES.items():
        if thread and thread.startswith(prefix) and len(thread) > len(prefix):
            return surface
    return None


_EMBED = re.compile(r"\[\[file:[^\]\n]+\]\](?: \([^)\n]{1,120}\))?|\[\[ann:[^\]\n]{1,120}\]\]")   # + an ask-the-margin marker
_TEAM = re.compile(r"^\[chat with [^\]\n]*\]\n?")                  # model.bodyFor's first line
# a project chat's first message opens with the project's context (web/src/chat/projects/context.ts):
# "[project: <name>]\n<instructions + pinned files>\n[/project]\n" — the agents', never the reader's; a body cut
# short before the close (a 400-char preview) loses the whole block
_PROJECT = re.compile(r"^\[project: [^\]\n]{1,80}\]\n(?:[\s\S]*?\n\[/project\]\n?|[\s\S]*$)")
_CANVAS = re.compile(r"^\[canvas #\d+[^\]\n]*\]\s*")               # the canvas shell's context prefix
_BRIEF = re.compile(r'^NEW CANVAS #\d+\s*\W\s*"([^"]{1,80})"')     # the canvas bridge's first message to a painter
# "send my changes" (web/src/chat/artifacts/versions/changes.ts, the one place the format lives):
# "[changes to <name>: v2 (db) → v4 (owner)]\n<note>\n\n```diff\n…\n```\n(N more diff lines not shown: …)\n[[file:…]]"
# — a reader sees "Changes to <name> (v2 → v4):" then the owner's note; the fenced diff and its overflow line are the
# agent's (the chat draws them as a card), never a preview, a title or a search snippet
_CHANGES = re.compile(r"^\[changes to (.{1,120}?): v(\d+) \([\w-]+\) → v(\d+) \([\w-]+\)\]")
_DIFF = re.compile(r"\n?```diff\n[\s\S]*?(?:\n```|$)|\(\d+ more diff lines not shown[^)\n]*\)")


def changes(s: str) -> str:
    """A send-changes body's header summarized and its diff dropped; any other body unchanged."""
    m = _CHANGES.match(s)
    if not m:
        return s
    return f"Changes to {m.group(1)} (v{m.group(2)} → v{m.group(3)}):" + _DIFF.sub("", s[m.end():])


def clean(body: str | None) -> str:
    """A body as a person reads it in a list: no file embeds, no routing prefixes, whitespace folded."""
    s = _PROJECT.sub("", _EMBED.sub("", body or "").lstrip())
    s = changes(_TEAM.sub("", s.lstrip()))
    s = _CANVAS.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def first_line(body: str | None) -> str:
    s = changes(_TEAM.sub("", _PROJECT.sub("", _EMBED.sub("", body or "").lstrip()).lstrip()))
    s = _CANVAS.sub("", s)
    for line in s.splitlines():
        if line.strip():
            return re.sub(r"\s+", " ", line).strip()
    return ""


def clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def derive_title(thread: str, custom: str | None, first_owner: str | None, canvas_title: str | None,
                 agents: list[str]) -> str:
    """The name a conversation goes by, in order: the owner's own title, the first line the owner wrote, the canvas
    shell's title, then a name from the thread itself (the floor desk is "<Agent>"), never an empty row."""
    if custom and custom.strip():
        return clip(re.sub(r"\s+", " ", custom).strip(), TITLE_MAX)
    line = first_line(first_owner)
    brief = _BRIEF.match(line)                      # a canvas's opening brief names the canvas: use the name
    if brief:
        return clip(brief.group(1), TITLE_MAX)
    if line:
        return clip(line, TITLE_MAX)
    if canvas_title and clean(canvas_title):
        return clip(clean(canvas_title), TITLE_MAX)
    if first_owner and _EMBED.search(first_owner):
        return "Attachment"
    if thread.startswith("obs:"):
        rest = thread[4:]
        if rest.startswith("library-"):
            return "A library question"
        if rest.startswith("person-"):
            return "About a person"
        if rest == "estate":
            return "The estate"
        return f"Desk with {pretty(rest)}"
    return f"Chat with {pretty(agents[0])}" if agents else "New chat"


def pretty(name: str) -> str:
    """api.ts displayName, server side: 'abstractor-1' -> 'Abstractor 1'."""
    return re.sub(r"\b\w", lambda m: m.group(0).upper(), re.sub(r"[-_]+", " ", name or ""))


def agents_of(thread: str, parties: list[str | None], roster: set[str], canvas_agent: str | None = None) -> list[str]:
    """The non-owner participants an owner can talk to, first-listed first: live agents only (a canvas page
    `canvas-<n>`, an invitee `cv-<x>`, the pulse or a federation peer is never a recipient). A desk thread obs:<agent>
    and a canvas chat name their agent even before it has spoken, so the composer always has someone to send to."""
    out: list[str] = []

    def add(n):
        if n and n != "owner" and (n in roster if roster else not re.match(r"^(canvas-|cv-)", n)) and n not in out:
            out.append(n)
    if thread.startswith("obs:"):
        add(thread[4:])
    add(canvas_agent)
    for p in parties:
        add(p)
    return out


def project_of(thread: str, projects: list[dict]) -> str | None:
    for p in projects:
        if isinstance(p, dict) and thread in (p.get("threads") or []):
            return p.get("id")
    return None


def build_rows(aggs: list[dict], meta: dict, projects: list[dict], roster: set[str],
               canvas: dict[str, dict] | None = None) -> list[dict]:
    """The unified list. `aggs` = one dict per thread (thread, count, last_ts, first_owner, last_body, parties);
    `meta` = {thread: {title?, pinned?}}; `canvas` = canvas_threads rows by thread. Owner-party threads of a known
    surface only; an archived canvas chat drops out. Pinned first, then newest."""
    canvas = canvas or {}
    out = []
    for a in aggs:
        t = a.get("thread") or ""
        surface = surface_of(t)
        parties = list(a.get("parties") or [])
        if surface is None or "owner" not in parties:
            continue
        cv = canvas.get(t) or {}
        if cv.get("archived"):
            continue
        m = meta.get(t) or {}
        # recipients = who exchanged messages WITH THE OWNER here (`partners`); an agent→agent row on an owner thread
        # (seed correcting finance) is history, never a recipient. Rows without `partners` (older callers) use parties
        partners = a.get("partners") if "partners" in a else parties
        agents = agents_of(t, list(partners or []), roster, cv.get("agent"))
        out.append({
            "thread": t,
            "title": derive_title(t, m.get("title"), a.get("first_owner"), cv.get("title"), agents),
            "custom_title": bool((m.get("title") or "").strip()),
            "agents": agents,
            "surface": surface,
            "last_ts": a.get("last_ts"),
            "preview": clip(clean(a.get("last_body")), PREVIEW_MAX) or ("Attachment" if a.get("last_body") else ""),
            "last_from": a.get("last_from"),
            "count": int(a.get("count") or 0),
            "pinned": bool(m.get("pinned")),
            "project": project_of(t, projects),
        })
    out.sort(key=lambda r: (r["last_ts"] or ""), reverse=True)
    out.sort(key=lambda r: not r["pinned"])         # stable: pinned first, each group newest first
    return out


def apply_meta(meta: dict, thread: str, title=..., pinned=...) -> dict:
    """One thread's patch onto the stored meta (a new dict; the input is never mutated). `...` = leave as is;
    a blank title clears it; an entry left with nothing in it is removed, so the file holds only what was set."""
    out = {k: dict(v) for k, v in meta.items() if isinstance(v, dict)}
    cur = out.get(thread, {})
    if title is not ...:
        t = re.sub(r"\s+", " ", title or "").strip()
        if t:
            cur["title"] = t[:TITLE_MAX]
        else:
            cur.pop("title", None)
    if pinned is not ...:
        if pinned:
            cur["pinned"] = True
        else:
            cur.pop("pinned", None)
    if cur:
        out[thread] = cur
    else:
        out.pop(thread, None)
    return out


def valid_thread(thread: str) -> bool:
    return bool(surface_of(thread)) and len(thread) <= 200 and "\x00" not in thread


def role_of(charter_text: str) -> str:
    """An agent's role in one line: the first sentence of the italic subtitle under its charter's title (every
    charter opens `# name` then `*The … seat. …*`), else the first prose line. Display only."""
    lines = charter_text.splitlines()
    para: list[str] = []
    for ln in lines[1:12]:
        s = ln.strip()
        if not para and not s:
            continue
        if not para and not s.startswith("*"):
            break
        if not s:
            break
        para.append(s)
        if s.endswith("*") and (len(para) > 1 or len(s) > 2):
            break
    text = " ".join(para).strip("*_ ").strip()
    title = re.match(r"#\s*\S+\s+[—–-]\s+(.+)", lines[0].strip()) if lines else None
    if title and (not text or "·" in text):          # a metadata subtitle ("resident · ships with the genome")
        text = title.group(1).strip()               # loses to the title's own epithet: "the org's physician"
        text = text[:1].upper() + text[1:]
    if not text:
        for ln in lines:
            s = ln.strip()
            if s and not s.startswith(("#", "Grants:", "Model:", "Rank:", "Type:")):
                text = s.strip("*_> `")
                break
    text = re.sub(r"[`*_]+", "", text)              # markdown marks: a role is plain text
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return clip((m.group(1) if m else text).strip(), 120)


# ----------------------------------------------------------------------------------------------------- storage
def read_meta() -> dict:
    try:
        raw = json.loads(meta_file().read_text()).get("threads", {})
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _projects() -> list[dict]:
    try:
        raw = json.loads((ESTATE / "chat" / "projects.json").read_text()).get("projects", [])
        return raw if isinstance(raw, list) else []
    except (OSError, ValueError, AttributeError):
        return []


def _pool(request: Request):
    return _get_pool() if _get_pool else request.app.state.pool


# ------------------------------------------------------------------------------------------------------ routes
# a project chat's context block is cut off in SQL, before the 400-char clip, so the title and the preview are the
# owner's own words however long the project's instructions run
_BODY = "CASE WHEN strpos(body, E'\\n[/project]\\n') > 0 AND body LIKE '[project: %' " \
        "THEN substr(body, strpos(body, E'\\n[/project]\\n') + 12) ELSE body END"
THREADS_SQL = f"""
SELECT thread, count(*) AS count, max(ts) AS last_ts,
       (array_agg(left({_BODY}, 400) ORDER BY id) FILTER (WHERE from_agent = 'owner'))[1] AS first_owner,
       (array_agg(left({_BODY}, 400) ORDER BY id DESC))[1] AS last_body,
       (array_agg(from_agent ORDER BY id DESC))[1] AS last_from,
       array_agg(DISTINCT from_agent) || array_agg(DISTINCT to_agent) AS parties,
       array_agg(CASE WHEN from_agent = 'owner' THEN to_agent ELSE from_agent END ORDER BY id)
         FILTER (WHERE from_agent = 'owner' OR to_agent = 'owner') AS partners
  FROM messages
 WHERE thread LIKE 'chat:%' OR thread LIKE 'obs:%' OR thread LIKE 'cv:%'
 GROUP BY thread ORDER BY max(id) DESC LIMIT 400"""


@router.get("/api/ws/threads")
async def ws_threads(request: Request):
    pool = _pool(request)
    aggs = [{**dict(r), "last_ts": r["last_ts"].isoformat() if r["last_ts"] else None}
            for r in await pool.fetch(THREADS_SQL)]
    canvas: dict[str, dict] = {}
    try:                                            # canvas_threads exists where the canvas bridge has run
        for r in await pool.fetch("SELECT thread, agent, title, archived FROM canvas_threads WHERE user_name = 'owner'"):
            canvas[r["thread"]] = dict(r)
    except Exception:                               # noqa: BLE001 — an estate without canvas lists the rest
        canvas = {}
    return {"etag": etag(meta_file()), "threads": build_rows(aggs, read_meta(), _projects(), set(_roster()), canvas)}


class Meta(BaseModel):
    thread: str
    title: str | None = None
    pinned: bool | None = None


@router.put("/api/ws/threads/meta")
async def ws_meta(body: Meta):
    if not valid_thread(body.thread):
        return JSONResponse({"error": "not a conversation thread"}, status_code=400)
    patch = body.model_dump(exclude_unset=True)
    if "title" not in patch and "pinned" not in patch:
        return JSONResponse({"error": "nothing to change"}, status_code=400)
    for _ in range(2):                              # a concurrent writer: re-read and re-apply once
        tag = etag(meta_file())
        new = apply_meta(read_meta(), body.thread,
                         title=patch["title"] if "title" in patch else ...,
                         pinned=bool(patch["pinned"]) if "pinned" in patch else ...)
        try:
            atomic_write(meta_file(), json.dumps({"threads": new}, indent=2, sort_keys=True) + "\n", if_match=tag)
            return {"thread": body.thread, **new.get(body.thread, {})}
        except Conflict:
            continue
    return JSONResponse({"error": "the list changed while saving; try again"}, status_code=409)


@router.get("/api/ws/agents")
async def ws_agents(request: Request):
    """The empty state's team cards: role from the charter, and each agent's newest message to the owner (30 days)."""
    names = sorted(_roster())
    last = {r["from_agent"]: r for r in await _pool(request).fetch(
        "SELECT DISTINCT ON (from_agent) from_agent, ts, thread, left(body, 400) AS body FROM messages "
        "WHERE to_agent = 'owner' AND ts > now() - interval '30 days' ORDER BY from_agent, id DESC")}
    out = []
    for n in names:
        role = ""
        try:
            p = _charter(n)
            role = role_of(p.read_text()) if p else ""
        except OSError:
            pass
        r = last.get(n)
        out.append({"agent": n, "role": role,
                    "last_ts": r["ts"].isoformat() if r else None,
                    "last_thread": r["thread"] if r else None,
                    "last_said": clip(clean(r["body"]), PREVIEW_MAX) if r else ""})
    return out


# ------------------------------------------------------------------------------------------------------ handoffs
HANDOFFS_SQL = """
SELECT DISTINCT ON (t.id) t.id AS turn_id, t.agent, m.id AS at,
       i.id, i.ts, i.from_agent, i.to_agent, i.thread, i.intent, left(i.body, $2) AS body
  FROM messages m
  JOIN turns t ON t.id = m.turn_id
  JOIN messages i ON i.id = t.input_msg_id
 WHERE m.thread = $1 AND i.from_agent <> 'owner' AND i.thread IS DISTINCT FROM $1
 ORDER BY t.id, m.id
 LIMIT 200"""
HANDOFF_BODY_MAX = 4000


def handoffs_of(rows: list[dict], roster: set[str]) -> list[dict]:
    """A HANDOFF into a conversation: a turn that wrote here, opened by a message from ANOTHER AGENT on another thread
    (seed asked db on a plan thread; db's answer landed in the owner's chat). The pulse, a canvas page or a peer
    opening a turn is not a handoff (no agent passed work), and a message already on this thread renders as its own
    row. Ordered by where the turn first wrote here (`at`), so the divider sits right above that answer."""
    out = []
    for r in rows:
        frm, to = r.get("from_agent"), r.get("agent")
        if not frm or frm == to or frm not in roster:
            continue
        ts = r.get("ts")
        out.append({"turn_id": r["turn_id"], "agent": to, "at": r["at"],
                    "msg": {"id": r["id"], "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts, "from": frm,
                            "to": r.get("to_agent"), "thread": r.get("thread"), "intent": r.get("intent"),
                            "body": r.get("body") or ""}})
    return sorted(out, key=lambda h: h["at"])


@router.get("/api/ws/handoffs")
async def ws_handoffs(request: Request, thread: str = ""):
    if not valid_thread(thread):
        return JSONResponse({"error": "not a conversation thread"}, status_code=400)
    rows = [dict(r) for r in await _pool(request).fetch(HANDOFFS_SQL, thread, HANDOFF_BODY_MAX)]
    return handoffs_of(rows, set(_roster()))


# ----------------------------------------------------------------------------------------------------- interrupt
AGENT_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")     # main._PUBLIC_AVATAR's name shape: no dots, no colon, no '='
INTERRUPT_TIMEOUT = 5


def interrupt_check(name: str, roster: set[str]) -> tuple[int, str] | None:
    """Why `name` may NOT be interrupted, as (status, reason), or None. The name is checked by SHAPE before the roster
    is consulted, so nothing a URL can carry ever reaches tmux's target parser (a '.', ':' or '=' would re-aim it)."""
    if not isinstance(name, str) or not AGENT_NAME.fullmatch(name):
        return 400, "not an agent name"
    if name not in roster:
        return 404, "no such agent"
    return None


def interrupt_argv(name: str, tmux: list[str]) -> list[str]:
    """One Escape into the agent's pane: Claude Code's own "interrupt" key, the same thing the owner would press in
    its tmux window. `=ax-<name>:` is an EXACT session match (a bare target falls back to a prefix match and would
    reach ax-<name>x; main.agent_retire's measured lesson) and its current window, the one context_compact also
    targets. A key NAME, never literal text: nothing typed reaches the prompt."""
    return [*tmux, "send-keys", "-t", f"=ax-{name}:", "Escape"]


def _tmux() -> list[str]:
    from astryx import orgs                        # the ONE resolver of this org's tmux server (main.py imports it too)
    return orgs.tmux()


@router.post("/api/ws/agents/{name}/interrupt")
async def ws_interrupt(name: str, request: Request):
    """Stop an agent's current turn. Owner-only twice: the gate (not in PUBLIC) and the owner check here."""
    if not _owner(request):
        return JSONResponse({"error": "owner only"}, status_code=403)
    bad = interrupt_check(name, set(_roster()))
    if bad:
        return JSONResponse({"error": bad[1]}, status_code=bad[0])
    try:
        r = await asyncio.to_thread(subprocess.run, interrupt_argv(name, _tmux()),
                                    capture_output=True, text=True, timeout=INTERRUPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "tmux did not answer"}, status_code=504)
    except OSError:
        return JSONResponse({"error": "tmux is not available here"}, status_code=503)
    if r.returncode != 0:                           # no such session: the body is down (tmux's stderr is not echoed)
        return JSONResponse({"error": f"{name} is not running"}, status_code=409)
    return {"ok": True, "agent": name}


# -------------------------------------------------------------------------------------------------------- search
# Full text over the owner's conversations: the bodies of the threads GET /api/ws/threads lists (an owner-party
# chat:/obs:/cv: thread, an archived canvas chat left out). Two matchers, either one is a hit: Postgres full text as
# PREFIX terms ('simple' config, every word of the query a `word:*` lexeme, so "quer" finds "query" while the owner is
# still typing; websearch_to_tsquery has no prefix form) and a plain ILIKE of the whole query, which carries what the
# parser splits or drops (an IP, "#412", a two-letter query). The match is SQL's; the SNIPPET is Python's, cut from the
# body as the list reads it (clean(): no file embeds, no [project:] block, no [[ann:]] marker) — a row whose only hit
# sat inside that hidden markup is dropped, never shown as a snippet with nothing marked. The owner's rows are
# MATERIALIZED first: left to itself the planner ran to_tsvector over the whole wire (10k rows, 400 ms measured)
# before joining to the owner's threads; on the candidate set it is a few ms.
SEARCH_Q_MAX = 200
SEARCH_LIMIT = 30
SEARCH_LIMIT_MAX = 100
SEARCH_SCAN = 4                                     # SQL rows read per result asked for (hidden-only hits, fan-out dups)
SNIPPET = 160
SNIPPET_LEAD = 48                                   # context kept before the first match
SEARCH_TIMEOUT = 5                                  # seconds; a slow search answers 504, never holds a worker

SEARCH_SQL = r"""
WITH owned AS MATERIALIZED (
  SELECT thread FROM messages
   WHERE thread LIKE 'chat:%' OR thread LIKE 'obs:%' OR thread LIKE 'cv:%'
   GROUP BY thread
  HAVING bool_or(from_agent = 'owner' OR to_agent = 'owner')
), cand AS MATERIALIZED (
  SELECT m.id, m.ts, m.thread, m.from_agent, m.to_agent, m.body
    FROM messages m
   WHERE (m.thread LIKE 'chat:%' OR m.thread LIKE 'obs:%' OR m.thread LIKE 'cv:%')
     AND m.thread IN (SELECT thread FROM owned)
)
SELECT id, ts, thread, from_agent, to_agent, left(body, 8000) AS body
  FROM cand
 WHERE body ILIKE $1 ESCAPE '\'
    OR CASE WHEN $2 = '' THEN false ELSE to_tsvector('simple', body) @@ to_tsquery('simple', $2) END
 ORDER BY id DESC
 LIMIT $3"""


def search_terms(q: str) -> list[str]:
    """The query's words, lowercased, each once, in order ("Query, the QUERY" -> ['query', 'the'])."""
    out: list[str] = []
    for w in re.findall(r"\w+", (q or "").lower()):
        if w not in out:
            out.append(w)
    return out[:12]


def search_args(q: str) -> tuple[str, str] | None:
    """(ILIKE pattern, prefix tsquery) for SEARCH_SQL, or None when there is nothing to look for. The tsquery is built
    from \\w words only, so nothing the owner types reaches to_tsquery's own syntax (& | ! : * ( ) quotes); it is empty
    for a query with no word of 2+ characters (one letter as a prefix matches everything; ILIKE carries it)."""
    q = re.sub(r"\s+", " ", (q or "")).strip()[:SEARCH_Q_MAX]
    if not q:
        return None
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    terms = search_terms(q)
    ts = " & ".join(f"{t}:*" for t in terms) if any(len(t) >= 2 for t in terms) else ""
    return like, ts


def match_spans(text: str, q: str) -> list[tuple[int, int]]:
    """Where `q` hits `text` (case-insensitive), as sorted, merged [start, end) spans, the first tier that hits: the
    whole query at a word start, else every word STARTING with a query term (as the prefix search found it), else the
    query anywhere, else each term anywhere (an ILIKE hit inside a word). A hit that ends inside a word is marked to the
    word's end ("quer" marks "querying")."""
    low = text.lower()
    phrase = re.sub(r"\s+", " ", (q or "")).strip().lower()
    terms = search_terms(q)
    tail = lambda s: re.escape(s) + (r"\w*" if re.search(r"\w$", s) else "")      # noqa: E731
    tiers = [[r"(?<!\w)" + tail(phrase)] if phrase else [],
             [r"(?<!\w)" + tail(t) for t in terms],
             [re.escape(phrase)] if phrase else [],
             [re.escape(t) for t in terms]]
    spans: list[tuple[int, int]] = []
    for tier in tiers:
        spans = [(m.start(), m.end()) for rx in tier for m in re.finditer(rx, low) if m.end() > m.start()]
        if spans:
            break
    spans.sort()
    out: list[tuple[int, int]] = []
    for s, e in spans:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


_MD_RULE = re.compile(r"\|?(?:\s*:?-{3,}:?\s*\|)+\s*(?::?-{3,}:?)?\s*")   # a table's |---|:--:| rule
_MD_MARK = re.compile(r"\*{1,3}|`+|(?<!\S)#{1,6} |(?<!\S)> ")                    # bold/italic stars, code ticks, #, >


def plain(text: str) -> str:
    """A cleaned body as a snippet reads: markdown's marks gone (a table's rule row, stars, backticks, heading hashes,
    quote marks), its cell bars as " · ". Underscores stay: snake_case table names are words here."""
    s = _MD_MARK.sub("", _MD_RULE.sub(" ", text))
    s = re.sub(r"\s*\|\s*", " · ", s)
    s = re.sub(r"(?:\s*·\s*){2,}", " · ", s)
    return re.sub(r"\s+", " ", s).strip(" ·")


_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\n]*\)")                            # [text](url) -> text
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+")                          # a list item's marker
_FENCE = re.compile(r"^\s*(?:```|~~~)")
_HRULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_UNDER = re.compile(r"(?<![\w_])_{1,2}(?=\S)|(?<=\S)_{1,2}(?![\w_])")             # _em_ / __strong__, not snake_case
_PHONE = re.compile(r"\+?\d[\d \-]{8,}\d")                                       # a long digit run (an MSISDN's shape)


def mask_numbers(s: str) -> str:
    """A run of ten or more digits (separators allowed) is personal-shaped (local.md's tier: MSISDNs, accounts):
    a label shows its shape, never its digits. Dates (8 digits) and figures with commas are untouched."""
    return _PHONE.sub(lambda m: "…" if sum(c.isdigit() for c in m.group(0)) >= 10 else m.group(0), s)


def headline(body: str | None, n: int = TITLE_MAX) -> str:
    """A message's first meaningful line, as a label: routing prefixes, a project's context, file embeds and margin
    markers gone; code fences, table rows and rules skipped; markdown's marks and list markers dropped, links read as
    their text; long digit runs masked; clipped to `n`. '' when the message has no words of its own."""
    s = changes(_TEAM.sub("", _PROJECT.sub("", _EMBED.sub("", body or "").lstrip()).lstrip()))
    s = _CANVAS.sub("", s)
    fenced = False
    for line in s.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced or line.lstrip().startswith("|") or _HRULE.match(line) or _MD_RULE.fullmatch(line.strip()):
            continue
        t = plain(_UNDER.sub("", _LINK.sub(r"\1", _BULLET.sub("", line))))
        t = t.rstrip(":").strip()
        if re.search(r"\w", t):
            return clip(mask_numbers(t), n)
    return ""


def snippet(body: str | None, q: str, width: int = SNIPPET) -> tuple[str, list[list[int]]] | None:
    """A hit as the list shows it: ~`width` characters of the cleaned body around the first match, "…" where cut, and
    the match spans as offsets INTO the returned string. None when the query hits nothing a reader would see."""
    text = plain(clean(body))
    spans = match_spans(text, q)
    if not spans:
        return None
    first = spans[0][0]
    start = 0 if first <= SNIPPET_LEAD else first - SNIPPET_LEAD
    if start:                                       # start on a word: the next space after the cut, if one is near
        sp = text.find(" ", start, first)
        start = sp + 1 if sp >= 0 else start
    end = min(len(text), max(start + width, spans[0][1]))
    if end < len(text):                             # end on a word
        sp = text.rfind(" ", spans[0][1], end)
        end = sp if sp > 0 else end
    lead = "…" if start else ""
    out = lead + text[start:end] + ("…" if end < len(text) else "")
    marks = [[s - start + len(lead), min(e, end) - start + len(lead)] for s, e in spans if s >= start and s < end]
    return out, marks


def search_hits(rows: list[dict], q: str, archived: set[str], limit: int) -> list[dict]:
    """SEARCH_SQL's rows (newest first) -> results: an archived canvas chat out, a hidden-only hit out, the owner's one
    message to several agents (one row per recipient on the wire) once."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for r in rows:
        t = r.get("thread") or ""
        if t in archived or not surface_of(t):
            continue
        key = (t, r.get("from_agent"), r.get("body"))
        if key in seen:
            continue
        seen.add(key)
        cut = snippet(r.get("body"), q)
        if not cut:
            continue
        ts = r.get("ts")
        out.append({"thread": t, "msg_id": r["id"], "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
                    "from": r.get("from_agent"), "to": r.get("to_agent"), "snippet": cut[0], "marks": cut[1]})
        if len(out) >= limit:
            break
    return out


@router.get("/api/ws/search")
async def ws_search(request: Request, q: str = "", limit: int = SEARCH_LIMIT):
    args = search_args(q)
    if not args:
        return {"q": q, "results": []}
    limit = max(1, min(int(limit), SEARCH_LIMIT_MAX))
    pool = _pool(request)
    try:
        rows = [dict(r) for r in await pool.fetch(SEARCH_SQL, args[0], args[1], limit * SEARCH_SCAN, timeout=SEARCH_TIMEOUT)]
    except asyncio.TimeoutError:
        return JSONResponse({"error": "the search took too long; try more words"}, status_code=504)
    archived: set[str] = set()
    try:
        archived = {r["thread"] for r in await pool.fetch(
            "SELECT thread FROM canvas_threads WHERE user_name = 'owner' AND archived")}
    except Exception:                               # noqa: BLE001 — an estate without canvas: nothing is archived
        archived = set()
    return {"q": q, "results": search_hits(rows, q[:SEARCH_Q_MAX], archived, limit)}


# ------------------------------------------------------------------------------------------- thread titles (i12)
TITLE_IDS_MAX = 40
LABEL_MAX = 60
_THREAD_ID = re.compile(r"[\w:.@+\-]{1,200}")
TITLES_SQL = f"""
SELECT thread, count(*) AS count, max(ts) AS last_ts,
       (array_agg(left({_BODY}, 400) ORDER BY id) FILTER (WHERE from_agent = 'owner'))[1] AS first_owner,
       NULL::text AS last_body, NULL::text AS last_from,
       array_agg(DISTINCT from_agent) || array_agg(DISTINCT to_agent) AS parties
  FROM messages
 WHERE thread = ANY($1::text[]) AND (thread LIKE 'chat:%' OR thread LIKE 'obs:%' OR thread LIKE 'cv:%')
 GROUP BY thread"""
FIRST_SQL = ("SELECT DISTINCT ON (thread) thread, left(body, 2000) AS body FROM messages "
             "WHERE thread = ANY($1::text[]) ORDER BY thread, id")


def title_ids(raw: str) -> list[str]:
    """?ids=a,b,c -> the distinct well-formed thread ids, first-seen order, at most TITLE_IDS_MAX."""
    out: list[str] = []
    for t in (raw or "").split(","):
        t = t.strip()
        if t and _THREAD_ID.fullmatch(t) and t not in out:
            out.append(t)
    return out[:TITLE_IDS_MAX]


def thread_label(thread: str, first_body: str | None) -> str:
    """A humane name for a thread that is not one of the owner's conversations (an agent's t-… work thread, a plan):
    its first message's first line, cleaned, at most LABEL_MAX chars — never more of any body. WhatsApp is named by
    its surface only (its first line is a person's words)."""
    if thread.startswith("wa:"):
        return "A WhatsApp chat"
    s = re.sub(r"^\[[\w -]{1,30}\]\s+", "", (first_body or "").lstrip())                       # "[insurance] …" tag
    s = re.sub(r"^@?[\w-]{1,30} here\s*[.,:;—–-]+\s*", "", s, flags=re.I)                           # "general here. …"
    s = re.sub(r"^[\w-]{1,30} → [\w-]{1,30}\s*[,:;—–-]+\s*", "", s)                                   # "finance → seed, …"
    out = headline(s, LABEL_MAX)
    return out[:1].upper() + out[1:]


def titles_of(ids: list[str], owner_rows: list[dict], firsts: dict[str, str | None]) -> dict[str, str]:
    """The owner's conversations by the list's own derivation (build_rows' titles), every other thread by its label;
    a thread nothing can name is left out (the client keeps its id)."""
    out = {r["thread"]: r["title"] for r in owner_rows}
    for t in ids:
        if t not in out and t in firsts:
            label = thread_label(t, firsts[t])
            if label:
                out[t] = label
    return {t: out[t] for t in ids if t in out}


@router.get("/api/ws/thread-titles")
async def ws_thread_titles(request: Request, ids: str = ""):
    """?ids=a,b,c (≤40): {titles: {id: title}} — the names the "Also worked in" tags show instead of wire ids."""
    want = title_ids(ids)
    if not want:
        return {"titles": {}}
    pool = _pool(request)
    aggs = [{**dict(r), "last_ts": r["last_ts"].isoformat() if r["last_ts"] else None}
            for r in await pool.fetch(TITLES_SQL, want)]
    canvas: dict[str, dict] = {}
    if any(t.startswith("cv:") for t in want):
        try:
            for r in await pool.fetch("SELECT thread, agent, title, archived FROM canvas_threads "
                                      "WHERE user_name = 'owner' AND thread = ANY($1::text[])", want):
                canvas[r["thread"]] = {**dict(r), "archived": False}   # an archived chat still has its name
        except Exception:                           # noqa: BLE001 — an estate without canvas
            canvas = {}
    rows = build_rows(aggs, read_meta(), [], set(_roster()), canvas)
    named = {r["thread"] for r in rows}
    firsts = {r["thread"]: r["body"] for r in await pool.fetch(FIRST_SQL, [t for t in want if t not in named])} \
        if any(t not in named for t in want) else {}
    return {"titles": titles_of(want, rows, firsts)}


# ------------------------------------------------------------------------------------- the briefing (iteration 15)
# "While you were away": what each agent did since the owner last looked, in ONE request. Compact and privacy-safe by
# construction: counts, and for the messages the agent sent TO THE OWNER only their headline (headline(): one line,
# markup gone, digit runs of ten or more masked) — never a body. A sender outside the roster (a WhatsApp guest
# `wa-<number>`, the pulse, a peer org) is never named. Bounded: the window is at most BRIEF_MAX_H hours, and the
# messages are read from one id boundary (the primary key, walked backwards until a row is older than `since`), so the
# cost follows the window, never the table; each agent's turn count and last words are one index probe apiece.
BRIEF_DEFAULT_H = 12
BRIEF_MAX_H = 48
BRIEF_ROWS = 6000                                  # rows read past the boundary at most (a 48 h window is ~1-2k today)
BRIEF_SAID = 6                                     # messages to the owner listed per agent (the count is exact)
BRIEF_FILES = 8
BRIEF_PEERS = 3
BRIEF_NEWS = 8
BRIEF_LINE = 120
BRIEF_TIMEOUT = 5

BRIEF_EDGE_SQL = "SELECT id FROM messages WHERE ts < $1 ORDER BY id DESC LIMIT 1"
BRIEF_MSGS_SQL = """
SELECT id, ts, from_agent, to_agent, thread, intent,
       CASE WHEN to_agent = 'owner' OR thread = 'org-news' THEN left(body, 2000) END AS body
  FROM messages
 WHERE id > $1 AND ts >= $2
 ORDER BY id
 LIMIT $3"""
BRIEF_TURNS_SQL = """
SELECT a.agent, (SELECT count(*) FROM turns t WHERE t.agent = a.agent AND t.ended_at >= $2) AS turns
  FROM unnest($1::text[]) AS a(agent)"""
# each agent's newest words of its own (a `response` step) in the window: what an agent that never wrote to the owner
# was doing. One steps_agent_ts probe per agent; a tool-only turn's placeholder is no words
BRIEF_DID_SQL = """
SELECT a.agent, s.ts, s.content
  FROM unnest($1::text[]) AS a(agent)
  CROSS JOIN LATERAL (
    SELECT ts, left(content, 1200) AS content FROM steps
     WHERE agent = a.agent AND ts >= $2 AND kind = 'response' AND content NOT LIKE '(tool-only%'
     ORDER BY ts DESC LIMIT 1) s"""


def brief_window(since: str | None, now) -> tuple:
    """?since= -> the window's start: an ISO time (a bare one read as UTC), clamped to [now - BRIEF_MAX_H, now];
    missing or unreadable -> now - BRIEF_DEFAULT_H. Returns (start, clamped)."""
    from datetime import datetime, timedelta, timezone
    floor, default = now - timedelta(hours=BRIEF_MAX_H), now - timedelta(hours=BRIEF_DEFAULT_H)
    try:
        t = datetime.fromisoformat((since or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return default, False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    if t < floor:
        return floor, True
    return (now, True) if t > now else (t, False)


def said_line(body: str | None) -> str:
    """A message to the owner as one line: thread_label's prefix strips (a "[lending]" tag, "general here."), then
    headline() (markup gone, digit runs masked), at most BRIEF_LINE chars."""
    s = re.sub(r"^\[[\w -]{1,30}\]\s+", "", (body or "").lstrip())
    s = re.sub(r"^@?[\w-]{1,30} here\s*[.,:;—–-]+\s*", "", s, flags=re.I)
    out = headline(s, BRIEF_LINE)
    return out[:1].upper() + out[1:]


def brief_surface(thread: str | None) -> str:
    """Where a message lives, as the briefing names it: an owner conversation the workspace opens (chat/floor/canvas),
    WhatsApp (read there; the workspace never opens a group), or elsewhere (a plan thread, no thread)."""
    s = surface_of(thread)
    if s:
        return s
    return "whatsapp" if (thread or "").startswith("wa:") else "other"


def _iso(ts):
    return ts.isoformat() if hasattr(ts, "isoformat") else ts


def brief_files(said: list[dict], index: dict, versions: dict[str, int]) -> list[dict]:
    """What an agent produced for the owner: the [[file:]] embeds in its messages to the owner, one entry per
    (thread, name) at its newest mention, newest first. A file the artifact store already holds carries its id (the
    chip opens it by id) and its version count; else the chip imports it from the embed's path on open.
    The store itself is NOT a source of news: an agent-authored version there is written when the OWNER opens or
    keeps an agent's file (an import on view, "Open as document"), so its time is the owner's, not the agent's."""
    from observatory.api import artifacts as A
    out: dict[tuple, dict] = {}
    for m in said:
        for f in A.FILE_EMBED.finditer(m.get("body") or ""):
            path, label = f.group(1).strip(), f.group(2)
            name = A.artifact_name(path, label)
            aid = A.artifact_id(m.get("thread") or "", name)
            e = index.get(aid) if isinstance(index.get(aid), dict) else None
            out[(m.get("thread"), name)] = {"name": name, "kind": A.kind_of(name), "thread": m.get("thread"),
                                            "ts": m["ts"], "msg_id": m["id"], "path": path, "label": label,
                                            "artifact": aid if e else None,
                                            "versions": versions.get(e.get("path"), 0) if e else 0}
    return sorted(out.values(), key=lambda f: f["msg_id"], reverse=True)


def brief(rows: list[dict], turns: dict[str, int], did: dict[str, dict], index: dict, versions: dict[str, int],
          roster: set[str]) -> dict:
    """The briefing from the window's rows (BRIEF_MSGS_SQL, oldest first; `body` only on rows to the owner and
    org-news), each agent's turn count, its newest words (`did`: {ts, content}) and the artifact store's index and
    version counts (by store path).
    Agents ordered by what needs the owner first: waiting on the owner, then those who wrote to the owner, then those
    who only worked; newest activity first within each."""
    ag: dict[str, dict] = {}

    def one(n: str) -> dict:
        if n not in ag:
            ag[n] = {"agent": n, "turns": 0, "to_owner": 0, "to_agents": 0, "from_agents": 0, "_peers": {}, "_said": [],
                     "last_ts": None}
        return ag[n]

    owner_last: dict[str, int] = {}
    news: list[dict] = []
    seen_news: set[tuple] = set()
    for r in rows:
        frm, to, t = r.get("from_agent"), r.get("to_agent"), r.get("thread")
        ts = _iso(r.get("ts"))
        if t == "org-news":
            key = (frm, r.get("body"))
            if frm in roster and key not in seen_news:
                seen_news.add(key)
                line = said_line(r.get("body"))
                if line:
                    news.append({"id": r["id"], "ts": ts, "from": frm, "headline": line})
            continue
        if frm == "owner":
            if t:
                owner_last[t] = max(owner_last.get(t, 0), r["id"])
            continue
        if frm not in roster:
            continue
        a = one(frm)
        a["last_ts"] = max(a["last_ts"] or "", ts or "") or None
        if to == "owner":
            a["to_owner"] += 1
            a["_said"].append({"id": r["id"], "thread": t, "ts": ts, "body": r.get("body") or "", "intent": r.get("intent")})
        elif to in roster and to != frm:
            a["to_agents"] += 1
            a["_peers"][to] = a["_peers"].get(to, 0) + 1
            b = one(to)
            b["from_agents"] += 1
            b["_peers"][frm] = b["_peers"].get(frm, 0) + 1
    for n, k in turns.items():
        if n in roster and k:
            one(n)["turns"] = int(k)
    agents = []
    for n, a in ag.items():
        said = a.pop("_said")
        peers = a.pop("_peers")
        newest: dict[str, dict] = {}                # each thread's newest message from this agent to the owner
        for m in said:
            newest[m["thread"] or ""] = m
        waits = [m for th, m in newest.items() if th and m["id"] > owner_last.get(th, 0)]
        w = max(waits, key=lambda m: m["id"]) if waits else None
        listed = [{"id": m["id"], "thread": m["thread"], "ts": m["ts"], "headline": said_line(m["body"]) or "Sent a file",
                   "surface": brief_surface(m["thread"])} for m in reversed(said)][:BRIEF_SAID]
        d = did.get(n) or {}
        a.update({
            "said": listed,
            "files": brief_files(said, index, versions)[:BRIEF_FILES],
            "peers": [{"agent": p, "n": k} for p, k in sorted(peers.items(), key=lambda x: (-x[1], x[0]))[:BRIEF_PEERS]],
            "waiting": {"id": w["id"], "thread": w["thread"], "ts": w["ts"], "surface": brief_surface(w["thread"])} if w else None,
            "did": said_line(d.get("content")) if d else "",
        })
        a["last_ts"] = max([x for x in (a["last_ts"], _iso(d.get("ts")) if d else None,
                                         *(f["ts"] for f in a["files"])) if x] or [None])
        if a["turns"] or a["said"] or a["files"] or a["to_agents"] or a["from_agents"]:
            agents.append(a)
    agents.sort(key=lambda a: a["last_ts"] or "", reverse=True)
    agents.sort(key=lambda a: 0 if a["waiting"] else 1 if a["to_owner"] else 2)
    return {
        "totals": {"agents": len(agents), "to_owner": sum(a["to_owner"] for a in agents),
                   "files": sum(len(a["files"]) for a in agents), "waiting": sum(1 for a in agents if a["waiting"]),
                   "handoffs": sum(a["to_agents"] for a in agents), "turns": sum(a["turns"] for a in agents)},
        "agents": agents,
        "news": list(reversed(news))[:BRIEF_NEWS],
    }


def version_counts(log: str) -> dict[str, int]:
    """`git log --format=%x1e --name-only` -> {store path: number of versions}."""
    out: dict[str, int] = {}
    for chunk in log.split("\x1e")[1:]:
        for f in chunk.splitlines():
            if f.strip():
                out[f.strip()] = out.get(f.strip(), 0) + 1
    return out


def _store_view() -> tuple[dict, dict]:
    from observatory.api import artifacts as A
    st = A.store()
    if not st.ready():
        return {}, {}
    log = st.git("log", "--format=%x1e", "--name-only", "-n", "3000").stdout
    return st.index(), version_counts(log.decode(errors="replace"))


@router.get("/api/ws/briefing")
async def ws_briefing(request: Request, since: str = ""):
    """?since=<iso> (default 12 h ago, at most 48 h back): {since, until, clamped, totals, agents, news}."""
    if not _owner(request):
        return JSONResponse({"error": "owner only"}, status_code=403)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    start, clamped = brief_window(since, now)
    roster = set(_roster())
    names = sorted(roster)
    pool = _pool(request)
    try:
        edge = await pool.fetchval(BRIEF_EDGE_SQL, start, timeout=BRIEF_TIMEOUT) or 0
        rows = [dict(r) for r in await pool.fetch(BRIEF_MSGS_SQL, edge, start, BRIEF_ROWS, timeout=BRIEF_TIMEOUT)]
        turns = {r["agent"]: r["turns"] for r in await pool.fetch(BRIEF_TURNS_SQL, names, start, timeout=BRIEF_TIMEOUT)}
        did = {r["agent"]: dict(r) for r in await pool.fetch(BRIEF_DID_SQL, names, start, timeout=BRIEF_TIMEOUT)}
    except asyncio.TimeoutError:
        return JSONResponse({"error": "the briefing took too long"}, status_code=504)
    try:
        index, versions = await asyncio.to_thread(_store_view)
    except Exception:                               # noqa: BLE001 — no store (or git hiccup): the embeds' paths stand
        index, versions = {}, {}
    out = brief(rows, turns, did, index, versions, roster)
    return {"since": start.isoformat(), "until": now.isoformat(), "clamped": clamped, **out}
