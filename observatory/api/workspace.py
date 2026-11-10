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


def clean(body: str | None) -> str:
    """A body as a person reads it in a list: no file embeds, no routing prefixes, whitespace folded."""
    s = _PROJECT.sub("", _EMBED.sub("", body or "").lstrip())
    s = _TEAM.sub("", s.lstrip())
    s = _CANVAS.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def first_line(body: str | None) -> str:
    s = _TEAM.sub("", _PROJECT.sub("", _EMBED.sub("", body or "").lstrip()).lstrip())
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
        agents = agents_of(t, parties, roster, cv.get("agent"))
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
       array_agg(DISTINCT from_agent) || array_agg(DISTINCT to_agent) AS parties
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
