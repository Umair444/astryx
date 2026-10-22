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
    POST /api/chat/dictate/session   an ephemeral TRANSCRIPTION-only realtime secret (C6), spent through voice_mint
    POST /api/chat/dictate/usage     connected seconds for that session

R2 upload: a size cap, a type allowlist, the name reduced to [A-Za-z0-9._-], a random token from common.media_path (a
guessable name lets anyone who can make the server read a path enumerate files: steward #37433), atomic write.
R3 file: the path is resolve()d (symlinks followed) and must sit under one of ROOTS; anything else, a NUL byte, or a
non-file is 404, never a hint of what exists. R6: the OpenAI key is read by voice_mint and never leaves it.
"""
from __future__ import annotations

import json
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
USER = "observatory-chat"
_mints: list[float] = []

_get_pool = None
ESTATE: Path | None = None
MEDIA: Path | None = None
REPO: Path | None = None
_roster = lambda: set()                            # noqa: E731 — the live agent names (main.agent_meta)


def bind(get_pool, estate: Path, media: Path, repo: Path, roster=None) -> None:
    """The host app hands over its pool getter, its estate and its roster (read at call time)."""
    global _get_pool, ESTATE, MEDIA, REPO, _roster
    _get_pool, ESTATE, MEDIA, REPO = get_pool, Path(estate), Path(media), Path(repo)
    if roster is not None:
        _roster = roster


def roots() -> list[Path]:
    """Where the side panel may read: the media dir (uploads, inbound channel media) and the agents' homes (their
    artifacts). Resolved, so a symlinked root can't widen the set."""
    return [p.resolve() for p in (MEDIA, (ESTATE / "homes") if ESTATE else None) if p is not None]


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
    kind = sniff(data[:4096])
    if not kind:
        return JSONResponse({"error": "this kind of file isn't accepted here (images, PDF, text, audio and video are)"},
                            status_code=415)
    dest = MEDIA / "upload" / f"{uuid.uuid4().hex}{EXT[kind]}"
    atomic_write(dest, data, mode=0o640)
    return {"path": str(dest), "name": safe_name(name), "size": len(data), "type": kind}


@router.get("/api/chat/file")
async def file(request: Request, path: str = ""):
    """D1: a ?key= never authenticates this route (a navigation that carries the key is refused, so stranger bytes
    are never a document opened as the owner; the panel fetches with the header). G3: served by serve_untrusted."""
    if "key" in request.query_params:
        return Response(status_code=403)
    p = readable(path)
    if p is None:
        return Response(status_code=404)
    return serve_untrusted(p, inline=True)


# ----------------------------------------------------------------------------------------------------- projects
class Project(BaseModel):
    id: str
    name: str
    brief: str = ""
    agents: list[str] = []
    threads: list[str] = []
    missing: list[str] = []          # D6': read-side only; never stored


def _valid(projects: list[Project]) -> str:
    seen = set()
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
        if any(not t.startswith("chat:") or len(t) > 120 for t in p.threads):
            return "a project holds only chat threads"
    return ""


def _read_projects() -> list[dict]:
    try:
        return json.loads(projects_file().read_text()).get("projects", [])
    except (OSError, ValueError, AttributeError):
        return []


@router.get("/api/chat/projects")
async def projects_get():
    """D6': every read is checked against the LIVE roster: an agent retired since the project was made is named in
    `missing`, so the page shows the gap instead of a project that quietly fans out to nobody."""
    live = _roster()
    out = []
    for p in _read_projects():
        if isinstance(p, dict):
            out.append({**p, "missing": [a for a in p.get("agents", []) if a not in live]})
    return {"etag": etag(projects_file()), "projects": out}


@router.put("/api/chat/projects")
async def projects_put(body: list[Project], request: Request):
    tag = request.headers.get("if-match")
    if tag is None:
        return JSONResponse({"error": "If-Match is required"}, status_code=428)
    why = _valid(body)
    if why:
        return JSONResponse({"error": why}, status_code=400)
    keep = [p.model_dump(exclude={"missing"}) for p in body]
    text = json.dumps({"projects": keep}, indent=2) + "\n"
    try:
        new = atomic_write(projects_file(), text, if_match=tag)
    except Conflict:
        return JSONResponse({"error": "projects changed since you loaded them", "etag": etag(projects_file()),
                             "projects": _read_projects()}, status_code=409)
    return {"etag": new, "projects": [{**p, "missing": []} for p in keep]}


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
    mid-turn and not answered leaves no marker, so that turn isn't filed here."""
    if not thread or len(thread) > 200:
        return JSONResponse({"error": "thread required"}, status_code=400)
    pool = _pool(request)
    turns = await pool.fetch(
        """WITH th AS (SELECT id FROM messages WHERE thread = $1),
                ids AS (SELECT DISTINCT turn_id AS id FROM messages WHERE thread = $1 AND turn_id IS NOT NULL
                        UNION SELECT id FROM turns WHERE input_msg_id IN (SELECT id FROM th))
           SELECT t.id, t.agent, t.started_at, t.ended_at, t.input_msg_id,
                  ARRAY(SELECT DISTINCT x FROM (SELECT thread AS x FROM messages WHERE turn_id = t.id AND thread IS NOT NULL
                                                 UNION SELECT thread FROM messages WHERE id = t.input_msg_id AND thread IS NOT NULL) q
                        WHERE x <> $1) AS elsewhere
             FROM turns t JOIN ids ON ids.id = t.id ORDER BY t.ended_at LIMIT 300""", thread)
    tids = [r["id"] for r in turns]
    steps = await pool.fetch(
        "SELECT id, ts, agent, kind, left(content, 300) AS content, turn_id FROM steps "
        "WHERE turn_id = ANY($1::bigint[]) AND kind <> ALL($2::text[]) ORDER BY id LIMIT 6000", tids, list(QUIET)) if tids else []
    by_turn: dict[int, list] = {}
    for st in steps:
        by_turn.setdefault(st["turn_id"], []).append(_step(st))
    live_names = _roster()
    parties = [r["a"] for r in await pool.fetch(
        "SELECT DISTINCT x AS a FROM messages, LATERAL (VALUES (from_agent), (to_agent)) v(x) WHERE thread = $1", thread)
        if r["a"] in live_names]
    first = await pool.fetchval("SELECT min(ts) FROM messages WHERE thread = $1", thread)
    live, unlinked = {}, {}
    for a in parties:
        end = await pool.fetchval("SELECT max(ended_at) FROM turns WHERE agent = $1", a)
        rows = await pool.fetch(
            "SELECT id, ts, agent, kind, left(content, 300) AS content, turn_id FROM steps WHERE agent = $1 "
            "AND turn_id IS NULL AND ($2::timestamptz IS NULL OR ts > $2) AND kind <> ALL($3::text[]) "
            "ORDER BY id DESC LIMIT 30", a, end, list(QUIET))
        live[a] = [_step(r) for r in reversed(rows)]
        unlinked[a] = (await pool.fetchrow(
            "SELECT count(*) AS n FROM steps WHERE agent = $1 AND turn_id IS NULL AND ts <= coalesce($2, now()) "
            "AND ts >= coalesce($3, now())", a, end, first))["n"] if end else 0
    return {"turns": [{"id": r["id"], "agent": r["agent"], "started_at": _iso(r["started_at"]),
                       "ended_at": _iso(r["ended_at"]), "input_msg_id": r["input_msg_id"],
                       "elsewhere": list(r["elsewhere"]), "steps": by_turn.get(r["id"], [])} for r in turns],
            "live": live, "unlinked": unlinked}


def _iso(t):
    return t.isoformat() if t else None


def _step(r) -> dict:
    return {"id": r["id"], "ts": _iso(r["ts"]), "agent": r["agent"], "kind": r["kind"], "content": r["content"],
            "turn_id": r["turn_id"]}


# ------------------------------------------------------------------------------------------------------ dictate
def _pool(request: Request):
    return _get_pool() if _get_pool else request.app.state.pool


@router.post("/api/chat/dictate/session")
async def dictate(request: Request):
    pool = _pool(request)
    why = await V.unavailable(pool)
    if why:
        return JSONResponse({"error": why}, status_code=429 if "cap" in why else 503)
    now = time.time()
    _mints[:] = [t for t in _mints if now - t < 3600]
    if len(_mints) >= 30:
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
    _mints.append(now)
    usage_id = await V.record(pool, USER, TRANSCRIBE)
    return {"value": out["value"], "usage_id": usage_id, "model": TRANSCRIBE, "calls_url": V.CALLS_URL,
            "minutes_today": await V.minutes_today(pool), "cap": V.cap_minutes()}


class Usage(BaseModel):
    id: int
    seconds: float


@router.post("/api/chat/dictate/usage")
async def dictate_usage(body: Usage, request: Request):
    return await V.report(_pool(request), body.id, USER, body.seconds)
