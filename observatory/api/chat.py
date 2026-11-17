"""astryx observatory · /chat's server half (plan-11884).

The conversation itself has NO route here: a chat is the wire thread `chat:<id>`, written by the existing owner send
(POST /api/messages, one row per @mentioned agent) and read by the existing /api/messages + /api/steps + the SSE feed.
What /chat needs beyond the wire lives here, every path OWNER-ONLY BY OMISSION: none is in main.PUBLIC, so the
default-deny gate answers 403 to anyone without the owner key before a handler runs (E1; tests/test_chat_api.py
holds the census).

    GET  /api/chat/commands          the composer's / list: the org's skills (skills/*/SKILL.md front matter)
    POST /api/chat/upload?name=      raw body -> media/chat/<random>-<name>   (C3)   returns {path, url, size, type}
    GET  /api/chat/file?path=        a file under the media dir or an agent home, for the side panel (C4)
    GET  /api/chat/projects          {etag, projects}                          (C5)
    PUT  /api/chat/projects          If-Match: <etag>; the whole list (one writer: hostfile.atomic_write)
                                     a project = name, instructions (the brief its team works under), agents (the
                                     team), threads (any owner conversation: chat:/obs:/cv:), files (artifact ids
                                     pinned as its knowledge), color/emoji; created/updated are stamped HERE
    POST /api/chat/dictate/session   an ephemeral TRANSCRIPTION-only realtime secret (C6), spent through voice_mint
    POST /api/chat/dictate/usage     connected seconds for that session

R2 upload: a size cap, a type allowlist, the name reduced to [A-Za-z0-9._-], a random token from common.media_path (a
guessable name lets anyone who can make the server read a path enumerate files: steward #37433), atomic write.
R3 file: the path is resolve()d (symlinks followed) and must sit under one of ROOTS; anything else, a NUL byte, or a
non-file is 404, never a hint of what exists. R6: the OpenAI key is read by voice_mint and never leaves it.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from astryx.hearing import voice_mint as V
from astryx.security.serve import EXT, serve_untrusted, sniff
from observatory.api.hostfile import Conflict, atomic_write, etag

router = APIRouter()

MAX_UPLOAD = 20 * 1024 * 1024                      # 20 MiB: a phone photo, a PDF, a short clip
TRANSCRIBE = V.env("CHAT_DICTATE_MODEL", V.env("CANVAS_VOICE_TRANSCRIBE", "gpt-4o-mini-transcribe"))
_mints: list[float] = []

_get_pool = None
ESTATE: Path | None = None
MEDIA: Path | None = None
REPO: Path | None = None
_roster = lambda: set()                            # noqa: E731 — the live agent names (main.agent_meta)
_me = lambda request: "owner"                      # noqa: E731 — main.wire_handle: the viewer's wire handle (cog-who)
_sees = lambda request: (lambda agent: False)      # noqa: E731 — main.sees; unbound = no agent's insides (closed)


def bind(get_pool, estate: Path, media: Path, repo: Path, roster=None, me=None, sees=None) -> None:
    """The host app hands over its pool getter, its estate, its roster, the viewer's wire handle and its insides
    predicate (read at call time)."""
    global _get_pool, ESTATE, MEDIA, REPO, _roster, _me, _sees
    _get_pool, ESTATE, MEDIA, REPO = get_pool, Path(estate), Path(media), Path(repo)
    if roster is not None:
        _roster = roster
    if me is not None:
        _me = me
    if sees is not None:
        _sees = sees


SCRATCH_BASE = Path(f"/tmp/claude-{os.getuid()}")   # Claude Code's per-uid temp root (bridges/embed_root.py's)


def scratch_root(home: Path) -> Path:
    """Claude Code's scratchpad root for sessions started in `home`: /tmp/claude-<uid>/<home, non-alnum -> '-'>, the
    same rule bridges/embed_root.scratch_root applies."""
    return SCRATCH_BASE / re.sub(r"[^A-Za-z0-9]", "-", str(home))


def roots() -> list[Path]:
    """Where the side panel may read: the media dir (uploads, inbound channel media), the agents' homes (their
    artifacts) and each agent home's Claude scratchpads, the roots bridges/embed_root already lets an agent attach
    from (11-11: db's avatar.svg, attached from its scratchpad, was a 404 here while WhatsApp would have carried it).
    Resolved, so a symlinked root can't widen the set."""
    out = [p.resolve() for p in (MEDIA, (ESTATE / "homes") if ESTATE else None) if p is not None]
    if ESTATE and (ESTATE / "homes").is_dir():
        for home in sorted((ESTATE / "homes").iterdir()):
            if home.is_dir() and not home.name.startswith("."):
                # a session's root is named after the path it STARTED in: the estate's spelling or the resolved one
                for sr in {scratch_root(home), scratch_root(home.resolve())}:
                    if sr.is_dir():
                        out.append(sr.resolve())
    return out


def safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name or "file").name).strip(".-") or "file"
    return stem[-80:]


def readable(raw: str) -> Path | None:
    """R3: the one place a requested path is judged. None = refuse (the caller answers 404)."""
    if not raw or "\x00" in raw:
        return None
    try:
        p = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not p.is_file():
        return None
    for r in roots():
        if p.is_relative_to(r):
            rel = p.relative_to(r).parts
            # never a dot-path (an agent home's .claude/ holds its session and, under ORGAUTH, its login) or an .env
            return None if any(x.startswith(".") for x in rel) or p.name.endswith(".env") else p
    return None


def projects_file() -> Path:
    return ESTATE / "chat" / "projects.json"


# ----------------------------------------------------------------------------------------------------- commands
def _front(md: Path) -> dict:
    out: dict = {}
    try:
        text = md.read_text(errors="replace")
    except OSError:
        return out
    if text.startswith("---"):
        for line in text.split("---", 2)[1].splitlines():
            k, _, v = line.partition(":")
            if k.strip() in ("name", "description"):
                out[k.strip()] = v.strip()
    return out


@router.get("/api/chat/commands")
async def commands():
    skills = []
    for md in sorted((REPO / "skills").glob("*/SKILL.md")) if REPO else []:
        f = _front(md)
        skills.append({"name": f.get("name") or md.parent.name, "description": f.get("description", "")[:300]})
    return {"skills": skills}


# ------------------------------------------------------------------------------------------------------- upload
@router.post("/api/chat/upload")
async def upload(request: Request, name: str = "file"):
    """D3: the bytes decide the type (sniffed, the same allowlist serve_untrusted uses); the server mints the stored
    name (a uuid plus the sniffed extension, under media/upload/, a namespace no bridge writes); the client's
    filename is display metadata only, returned as `name` and never part of a path."""
    data = await request.body()
    if not data:
        return JSONResponse({"error": "the file is empty"}, status_code=400)
    if len(data) > MAX_UPLOAD:
        return JSONResponse({"error": "the file is over 20 MB"}, status_code=413)
    # EVERY kind is accepted (owner 11-13: "every kind of file should be acceptable from chat"): a sniffed passive type
    # keeps its type; anything else (docx, xlsx, zip, csv-as-binary…) is stored opaque and serve_untrusted only ever
    # hands it out as an octet-stream ATTACHMENT under the sandbox CSP, never interpreted on the owner's origin. Its
    # extension comes from the display name only when it is plain ([a-z0-9]{1,8}), so an agent can see what it is;
    # the stored name stays server-minted.
    kind = sniff(data[:4096])
    ext = EXT.get(kind) if kind else None
    if not ext:                                  # unknown bytes never wear an extension that claims a sniffed or
        m = re.fullmatch(r".*\.([A-Za-z0-9]{1,8})", safe_name(name) or "")     # rendered type (a script "photo.png")
        ext = "." + m.group(1).lower() if m else ".bin"
        if ext in set(EXT.values()) | {".svg", ".html", ".htm", ".xhtml", ".xml", ".js", ".mjs"}:
            ext = ".bin"
    dest = MEDIA / "upload" / f"{uuid.uuid4().hex}{ext}"
    atomic_write(dest, data, mode=0o640)
    return {"path": str(dest), "name": safe_name(name), "size": len(data), "type": kind or "application/octet-stream"}


@router.get("/api/chat/file")
async def file(request: Request, path: str = ""):
    """D1: a ?key= never authenticates this route (a navigation that carries the key is refused, so stranger bytes
    are never a document opened as the owner; the panel fetches with the header). G3: served by serve_untrusted."""
    if "key" in request.query_params:
        return Response(status_code=403)
    p = readable(path)
    if p is None:
        return Response(status_code=404)
    return serve_untrusted(p, inline=True, svg=True)      # an .svg that IS one: image/svg+xml under SVG_CSP


@router.get("/api/chat/preview")
async def preview(request: Request, path: str = ""):
    """An Office document (pptx, ppt, docx, doc, xlsx, xls, odt, odp, ods, rtf) as the PDF it reads as, authored:
    converted once by the converter canvas uses (astryx.core.office, LibreOffice headless, cached by content hash),
    served by serve_untrusted, drawn by the panel's pdf.js. The same gate as /api/chat/file: a ?key= never
    authenticates it, and a member reaches only a file some message attached (main.member_file)."""
    if "key" in request.query_params:
        return Response(status_code=403)
    p = readable(path)
    if p is None:
        return Response(status_code=404)
    from astryx.core import office
    try:
        out = await office.to_pdf(p, MEDIA / ".preview")
    except office.Unavailable as e:
        return JSONResponse({"error": e.why}, status_code=e.status)
    return serve_untrusted(out, inline=True, filename=f"{p.stem}.pdf")


# ----------------------------------------------------------------------------------------------------- projects
# Iteration 5 widened a project from {name, brief, agents, chat: threads} to what claude.ai/ChatGPT call a project
# plus a TEAM: `instructions` (the old `brief`, read as it until rewritten), pinned artifact `files`, any owner thread
# kind, a colour/emoji, and server-stamped created/updated. An old file reads unchanged; the next write upgrades it.
PROJECT_COLORS = ("violet", "blue", "teal", "green", "amber", "orange", "rose", "slate")
PROJECT_THREADS = ("chat:", "obs:", "cv:")         # the owner's three surfaces (workspace.SURFACES)
INSTRUCTIONS_MAX = 20000
FILES_MAX = 200


class Project(BaseModel):
    id: str
    name: str
    instructions: str = ""
    brief: str = ""                  # the pre-iteration-5 name of `instructions`: accepted on a write, never stored
    agents: list[str] = []
    threads: list[str] = []
    files: list[str] = []            # artifact ids (observatory/api/artifacts.py: 16 hex)
    color: str | None = None
    emoji: str | None = None
    created: str | None = None       # read-side: the server stamps both, a client's value is ignored
    updated: str | None = None
    by: str | None = None            # read-side: the account that made it (members uid), server-stamped; none = owner
    yours: bool | None = None        # read-side: the viewer made it (or is the owner): theirs to share
    shared: list[str] = []           # who else sees it: members' accounts (members.uid), chosen by its maker (11-17)
    missing: list[str] = []          # D6': read-side only; never stored


def _valid(projects: list[Project]) -> str:
    seen, held = set(), set()
    for p in projects:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", p.id):
            return f"project id {p.id!r} must be lowercase letters, digits and dashes"
        if p.id in seen:
            return f"two projects share the id {p.id!r}"
        seen.add(p.id)
        if not p.name.strip() or len(p.name) > 80:
            return "a project needs a name of at most 80 characters"
        if any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", a) for a in p.agents):
            return "an agent name isn't valid"
        if any(not t.startswith(PROJECT_THREADS) or len(t) > 200 or not t.split(":", 1)[1] or re.search(r"[\x00-\x1f]", t)
               for t in p.threads):
            return "a project holds only conversations (chat:, obs: or cv: threads)"
        if held & set(p.threads):
            return "a conversation sits in one project at most"
        held |= set(p.threads)
        if len(p.files) > FILES_MAX or any(not re.fullmatch(r"[0-9a-f]{16}", f) for f in p.files):
            return "a project's files are artifact ids"
        if len(p.instructions) > INSTRUCTIONS_MAX or len(p.brief) > INSTRUCTIONS_MAX:
            return f"instructions run to at most {INSTRUCTIONS_MAX} characters"
        if p.color is not None and p.color not in PROJECT_COLORS:
            return "not a project colour"
        if p.emoji is not None and (len(p.emoji) > 8 or re.search(r"[\x00-\x20A-Za-z0-9<>&\"']", p.emoji)):
            return "an emoji is one emoji"
        if len(p.shared) > 200 or any(not ACCOUNT.fullmatch(h) for h in p.shared):
            return "a project is shared with members of this org"
    return ""


def upgrade(p: dict) -> dict:
    """A stored project as the current shape: `brief` read as `instructions`, the new fields defaulted."""
    out = {"id": p.get("id"), "name": p.get("name"), "instructions": p.get("instructions") or p.get("brief") or "",
           "agents": list(p.get("agents") or []), "threads": list(p.get("threads") or []), "files": list(p.get("files") or []),
           "color": p.get("color"), "emoji": p.get("emoji"), "created": p.get("created"), "updated": p.get("updated"),
           "shared": list(p.get("shared") or [])}
    if p.get("by"):                  # a member's project names her ACCOUNT (11-17); the owner's carry no key, as before
        out["by"] = p["by"]
    return out


# the fields a member must leave as they are on a project that is not hers (cog-gaps: her projects are hers to edit;
# the rest of the org's are shown, never changed by her)
PROJECT_FIELDS = ("name", "instructions", "agents", "threads", "files", "color", "emoji", "shared")
ACCOUNT = re.compile(r"^[0-9]{1,18}@[A-Za-z0-9_.-]{1,64}$")   # a members uid: <account>@<cog id>


def project_owner(p: dict) -> str:
    return p.get("by") or "owner"


def foreign_edit(new: list[dict], old: list[dict], who: str) -> str:
    """A member's PUT may add, change and drop only projects that are HERS: '' when it does, else the reason. Every
    stored project of another human must come back unchanged in PROJECT_FIELDS."""
    got = {p["id"]: p for p in new}
    for p in old:
        if project_owner(p) == who:
            continue
        q = got.get(p["id"])
        if q is None:
            return f"the project {p.get('name')!r} is not yours to remove"
        if any(q.get(k) != p.get(k) for k in PROJECT_FIELDS):
            return f"the project {p.get('name')!r} is not yours to change"
    return ""


def stamp(new: list[dict], old: list[dict], now: str) -> list[dict]:
    """created/updated are the SERVER's: a project keeps its stored `created` (or gets `now` when it is new) and its
    stored `updated` unless what the owner can see of it changed."""
    before = {p.get("id"): upgrade(p) for p in old if isinstance(p, dict)}
    out = []
    for p in new:
        was = before.get(p["id"])
        same = was is not None and all(was.get(k) == p.get(k) for k in p if k not in ("created", "updated"))
        out.append({**p, "created": (was or {}).get("created") or now,
                    "updated": ((was or {}).get("updated") or now) if same else now})
    return out


def _read_projects() -> list[dict]:
    try:
        raw = json.loads(projects_file().read_text()).get("projects", [])
        return [upgrade(p) for p in raw if isinstance(p, dict)] if isinstance(raw, list) else []
    except (OSError, ValueError, AttributeError):
        return []


@router.get("/api/chat/projects")
async def projects_get(request: Request):
    """D6': every read is checked against the LIVE roster: an agent retired since the project was made is named in
    `missing`, so the page shows the gap instead of a project that quietly fans out to nobody. Only the projects this
    viewer sees (workspace.project_visible: its maker, whom they shared it with, the owner)."""
    from observatory.api.workspace import account, project_visible
    who, live = account(request), _roster()           # nobody: no project (medic 12845), never the owner's
    out = [{**p, "missing": [a for a in p["agents"] if a not in live], "yours": who in ("owner", project_owner(p))}
           for p in _read_projects() if project_visible(p, who)]
    return {"etag": etag(projects_file()), "projects": out}


@router.get("/api/chat/people")
async def people(request: Request):
    """Who a project can be shared with: this org's MEMBERS TABLE (every account with a role here, owners aside, who
    see every project), never the viewer. Accounts only: their names are the cog's (the sign-in front's
    /auth/people adds them), since the org keeps no names of its own."""
    rows = await _pool(request).fetch("SELECT uid FROM members GROUP BY uid HAVING NOT bool_or(role = 'owner' AND node = '') "
                                      "ORDER BY uid")
    me = getattr(request.state, "uid", None)
    return {"people": [r["uid"] for r in rows if r["uid"] != me]}


@router.put("/api/chat/projects")
async def projects_put(body: list[Project], request: Request):
    tag = request.headers.get("if-match")
    if tag is None:
        return JSONResponse({"error": "If-Match is required"}, status_code=428)
    why = _valid(body)
    if why:
        return JSONResponse({"error": why}, status_code=400)
    from observatory.api.workspace import account, project_visible
    me, who = _me(request), account(request)
    if not me or not who:
        return JSONResponse({"error": "who are you?"}, status_code=403)
    old = _read_projects()
    was = {p["id"]: p for p in old}
    unseen = [p for p in old if not project_visible(p, who)]   # a member's list never names these: they stay as stored
    members = {r["uid"] for r in await _pool(request).fetch("SELECT DISTINCT uid FROM members")}
    keep = []
    for p in body:
        d = p.model_dump(exclude={"missing", "brief", "created", "updated", "by", "yours"})
        d["instructions"] = p.instructions or p.brief
        d["name"] = p.name.strip()
        maker = was[p.id].get("by") if p.id in was else (None if who == "owner" else who)
        if maker:                                    # server-stamped: a client's `by` is never read
            d["by"] = maker
        before = set((was.get(p.id) or {}).get("shared") or [])
        if set(d["shared"]) - before - members:     # judged on what THIS write adds (medic 12883)
            return JSONResponse({"error": "a project is shared with members of this org"}, status_code=400)
        d["shared"] = [u for u in d["shared"] if u in members]   # a removed member drops out on the next write
        keep.append(d)
    sent = {d["id"] for d in keep}
    if any(p["id"] in sent for p in unseen):
        return JSONResponse({"error": "no such project"}, status_code=403)
    keep += unseen
    if who != "owner":                               # a member: her own projects only (cog-gaps)
        why = foreign_edit(keep, old, who)
        if not why:                                  # ...and a conversation she files must be one of hers
            pool = _pool(request)
            from observatory.api.workspace import party
            prior = {t for p in old if project_owner(p) == who for t in p["threads"]}
            for t in {t for p in keep if project_owner(p) == who for t in p["threads"]} - prior:
                if not await party(pool, t, me):
                    why = "a project of yours holds only your own conversations"
                    break
        if why:
            return JSONResponse({"error": why}, status_code=403)
    keep = stamp(keep, old, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    text = json.dumps({"projects": keep}, indent=2, ensure_ascii=False) + "\n"
    try:
        new = atomic_write(projects_file(), text, if_match=tag)
    except Conflict:
        return JSONResponse({"error": "projects changed since you loaded them", "etag": etag(projects_file()),
                             "projects": [p for p in _read_projects() if project_visible(p, who)]}, status_code=409)
    return {"etag": new, "projects": [{**p, "missing": [], "yours": who in ("owner", project_owner(p))}
                                      for p in keep if project_visible(p, who)]}


# --------------------------------------------------------------------------------------------------------- work
QUIET = ("tool_done", "heartbeat", "response")      # the done-marks and echoes: they say nothing a person reads


@router.get("/api/chat/work")
async def work(request: Request, thread: str = ""):
    """D4 (a3 #62264, a4 #62268): the work behind a thread, at TURN level. A turn belongs to EVERY thread it touched:
    the one whose message opened it (turns.input_msg_id) and every one it wrote to (messages.turn_id), since 10% of
    turns read a message mid-turn and many answer on another thread. Each turn comes with its steps and the OTHER
    threads it touched, never split by step. Steps are linked to their turn only when the turn ends (the Stop hook
    back-fills steps.turn_id), so an agent's newest unlinked steps are its LIVE lane, "current work (any thread)", and
    the unlinked steps older than its last turn end are COUNTED (never dropped). Residual, named: a message read
    mid-turn and not answered leaves no marker, so that turn isn't filed here.
    `msgs` (11-11): the ids of THIS thread's rows the turn wrote. The Stop hook back-fills messages.turn_id only when
    the turn ENDS, but each row was inserted (and NOTIFY'd to every open tab) mid-turn with turn_id NULL, so a tab's
    live copy never names its turn: the workspace pairs reply and turn by these ids, and an id it does not hold is a
    row the stream never brought it (it fetches the thread past it)."""
    if not thread or len(thread) > 200:
        return JSONResponse({"error": "thread required"}, status_code=400)
    pool = _pool(request)
    from observatory.api import scope
    if scope.of(request) is not None and thread not in await scope.threads_ok(pool, request, [thread]):
        return JSONResponse({"error": "that conversation is outside the agents you were given"}, status_code=403)
    turns = await pool.fetch(
        """WITH th AS (SELECT id FROM messages WHERE thread = $1),
                ids AS (SELECT DISTINCT turn_id AS id FROM messages WHERE thread = $1 AND turn_id IS NOT NULL
                        UNION SELECT id FROM turns WHERE input_msg_id IN (SELECT id FROM th))
           SELECT t.id, t.agent, t.started_at, t.ended_at, t.input_msg_id,
                  ARRAY(SELECT DISTINCT x FROM (SELECT thread AS x FROM messages WHERE turn_id = t.id AND thread IS NOT NULL
                                                 UNION SELECT thread FROM messages WHERE id = t.input_msg_id AND thread IS NOT NULL) q
                        WHERE x <> $1) AS elsewhere,
                  ARRAY(SELECT m.id FROM messages m WHERE m.turn_id = t.id AND m.thread = $1 ORDER BY m.id) AS msgs
             FROM turns t JOIN ids ON ids.id = t.id ORDER BY t.ended_at LIMIT 300""", thread)
    tids = [r["id"] for r in turns]
    steps = await pool.fetch(
        "SELECT id, ts, agent, kind, left(content, 300) AS content, turn_id, meta->'turn_msgs' AS turn_msgs, meta->'sub' AS sub FROM steps "
        "WHERE turn_id = ANY($1::bigint[]) AND kind <> ALL($2::text[]) ORDER BY id LIMIT 6000", tids, list(QUIET)) if tids else []
    see = _sees(request)                           # a member reads every agent's work the owner does, short of the
    by_turn: dict[int, list] = {}                  # personal tier (main.sees, 11-15): a refused agent's turn keeps
    for st in steps:                               # its shape (when, how long), never its steps
        if see(st["agent"]):
            by_turn.setdefault(st["turn_id"], []).append(_step(st))
    live_names = _roster()
    parties = [r["a"] for r in await pool.fetch(
        "SELECT DISTINCT x AS a FROM messages, LATERAL (VALUES (from_agent), (to_agent)) v(x) WHERE thread = $1", thread)
        if r["a"] in live_names and see(r["a"])]
    first = await pool.fetchval("SELECT min(ts) FROM messages WHERE thread = $1", thread)
    live, unlinked, ended = {}, {}, {}
    for a in parties:
        end = await pool.fetchval("SELECT max(ended_at) FROM turns WHERE agent = $1", a)
        ended[a] = _iso(end)                   # its last turn's end: an ask older than this, still unanswered, was passed by
        rows = await pool.fetch(
            "SELECT id, ts, agent, kind, left(content, 300) AS content, turn_id, meta->'turn_msgs' AS turn_msgs, meta->'sub' AS sub FROM steps WHERE agent = $1 "
            "AND turn_id IS NULL AND ($2::timestamptz IS NULL OR ts > $2) AND kind <> ALL($3::text[]) "
            "ORDER BY id DESC LIMIT 30", a, end, list(QUIET))
        live[a] = [_step(r) for r in reversed(rows)]
        unlinked[a] = (await pool.fetchrow(
            "SELECT count(*) AS n FROM steps WHERE agent = $1 AND turn_id IS NULL AND ts <= coalesce($2, now()) "
            "AND ts >= coalesce($3, now())", a, end, first))["n"] if end else 0
    return {"turns": [{"id": r["id"], "agent": r["agent"], "started_at": _iso(r["started_at"]),
                       "ended_at": _iso(r["ended_at"]), "input_msg_id": r["input_msg_id"],
                       "elsewhere": list(r["elsewhere"]), "msgs": list(r["msgs"]),
                       "steps": by_turn.get(r["id"], [])} for r in turns],
            "live": live, "unlinked": unlinked, "ended": ended}


def _iso(t):
    return t.isoformat() if t else None


def _step(r) -> dict:
    """`turn_msgs` (hooks/step.py): the msg_ids that opened the step's turn, so the page can tell which conversation an
    agent's LIVE work serves (11-15: db replied, kept working, and the chat went blank)."""
    tm = r["turn_msgs"] if "turn_msgs" in r.keys() else None
    if isinstance(tm, str):
        try:
            tm = json.loads(tm)
        except ValueError:
            tm = None
    sub = r["sub"] if "sub" in r.keys() else None
    if isinstance(sub, str):
        try:
            sub = json.loads(sub)
        except ValueError:
            sub = None
    sub = ({k: str(sub[k])[:80] for k in ("id", "type", "desc") if sub.get(k)} or None) if isinstance(sub, dict) else None
    return {"id": r["id"], "ts": _iso(r["ts"]), "agent": r["agent"], "kind": r["kind"], "content": r["content"],
            "turn_id": r["turn_id"], "turn_msgs": [int(x) for x in tm][:20] if isinstance(tm, list) else None,
            "sub": sub}     # a helper (sub-agent) the agent launched did this step (hooks/step.py scope)


# ------------------------------------------------------------------------------------------------------ dictate
def _pool(request: Request):
    return _get_pool() if _get_pool else request.app.state.pool


def _dictator(request: Request) -> tuple[str, float | None, int]:
    """(the ledger user for this person's dictation, their own daily minutes or None, what a session costs them at
    once: 0 for the owner, else voice_mint.member_floor): each person's minutes are theirs, inside the org's one cap."""
    me = _me(request)
    limit = (getattr(request.state, "caps", {}) or {}).get("dictate")
    return V.who(me, "dictate"), limit, 0 if me == "owner" else V.member_floor("dictate", limit)


@router.post("/api/chat/dictate/session")
async def dictate(request: Request):
    pool = _pool(request)
    user, limit, charge = _dictator(request)
    why = await V.unavailable(pool, user, limit, charge)
    if why:
        return JSONResponse({"error": why}, status_code=429 if ("cap" in why or "spent" in why) else 503)
    now, owner = time.time(), _me(request) == "owner"
    _mints[:] = [t for t in _mints if now - t < 3600]
    if (owner and len(_mints) >= 30) or (not owner and not V.mint_allowed(user, 30)):   # a member's count is theirs
        return JSONResponse({"error": "too many dictation sessions this hour"}, status_code=429)
    cfg = {
        "expires_after": {"anchor": "created_at", "seconds": 120},
        "session": {
            "type": "transcription",
            "audio": {"input": {
                "transcription": {"model": TRANSCRIBE},
                "turn_detection": {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300,
                                   "silence_duration_ms": 450},
                "noise_reduction": {"type": "near_field"},
            }},
        },
    }
    code, out = await V.mint(cfg)
    if code != 200 or not out.get("value"):
        return JSONResponse({"error": f"the speech service refused the session ({code})"}, status_code=502)
    if owner:
        _mints.append(now)
    usage_id = await V.record(pool, user, TRANSCRIBE, charge)
    return {"value": out["value"], "usage_id": usage_id, "model": TRANSCRIBE, "calls_url": V.CALLS_URL,
            "minutes_today": await V.minutes_today(pool), "cap": V.cap_minutes()}


class Usage(BaseModel):
    id: int
    seconds: float


@router.post("/api/chat/dictate/usage")
async def dictate_usage(body: Usage, request: Request):
    return await V.report(_pool(request), body.id, _dictator(request)[0], body.seconds)
