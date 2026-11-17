"""astryx observatory · the chat workspace's window onto CANVAS (feat/chat-workspace, iteration 13).

Canvases are live pages an agent paints (bridges/canvas.py; src/astryx/core/canvas.py is their ONE writer). The
workspace shows them beside the conversation about them: it lists them, shows a version, and answers the page's own
data reads. Its one write is sharing with members; asking for a change, rolling back and archiving stay in canvas.

    GET /api/ws/canvases                    the owner's canvases (not archived), newest first, each with its thread
    GET /api/ws/canvases/{id}               one canvas + its versions (newest first, ≤50)
    GET /api/ws/canvases/{id}/render?v=     {version, html}: that version wrapped in canvas's OWN shell
                                            (bridges/canvas_shell.render: its CSP, theme tokens and postMessage shim)
    GET /api/ws/canvases/{id}/data?key=     the page's live values (one key, or all)
    POST /api/ws/canvases/{id}/share         {shared: [account]}: its maker or the owner shares it with members

Why a read endpoint here and not the /canvas/ proxy: the proxy needs canvas's own cookie session, which the workspace
doesn't hold (its gate is the observatory owner key). These routes read canvas's tables with the observatory's pool and
serve the page through the SAME pure shell canvas serves, so the CSP and the sandbox contract are canvas's, unchanged.
The frame that shows it (web/src/chat/canvas/CanvasFrame.tsx) uses canvas's sandbox (allow-scripts allow-forms, no
allow-same-origin): an opaque origin with no cookie, no storage and no parent DOM.

WHO SEES A CANVAS is canvas's own rule (astryx.core.canvas.sees: the owner, its maker, whom it is shared with), asked
here with the viewer's keys (owner 11-17, msg 12979: "multiple members should be able to work on canvas"): a member
reaches these routes (main.MEMBER_GET, MEMBER) and sees only the canvases that rule gives them. Sharing with members
by account is the one write here, beside canvas's own share (which also shares with invitees, the owner's alone);
both go through cv.share_set. The workspace has no invitees.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from astryx.core import canvas as cv
from astryx.security import relay

router = APIRouter()

_get_pool = None
CANVAS_PRE = ""                                     # /o/<org> in a cog (main.CANVAS_PRE); "" on one org
VERSIONS_MAX = 50

COLS = "id, title, agent, user_name, tier, version AS ver, brief, updated_at, shared_with"
LIST_SQL = f"SELECT {COLS} FROM canvases WHERE NOT archived AND {cv.sees_sql('$1', '$2')} ORDER BY updated_at DESC LIMIT 200"


def bind(get_pool, canvas_prefix: str = "") -> None:
    global _get_pool, CANVAS_PRE
    _get_pool, CANVAS_PRE = get_pool, canvas_prefix


def _pool(request: Request):
    return _get_pool() if _get_pool else request.app.state.pool


def thread_of(cid: int) -> str:
    """The canvas's own conversation (bridges/canvas.py names it so: the viewer, the painter and the crew talk there)."""
    return f"cv:canvas-{cid}"


def keys(request: Request) -> tuple[bool, list[str]]:
    """(the owner?, the viewer's keys to a canvas): a member's canvas name (their handle less cv-) and account. The owner
    and the agents (no member scope) see every canvas."""
    from observatory.api import scope
    if scope.of(request) is None:
        return True, []
    me, uid = getattr(request.state, "me", None) or "", getattr(request.state, "uid", None) or ""
    return False, [k for k in (me[3:] if me.startswith("cv-") else "", uid) if k]


def shape(r, ks: tuple[bool, list[str]] = (True, [])) -> dict:
    return {"id": r["id"], "title": r["title"], "agent": r["agent"], "user": r["user_name"], "tier": r["tier"],
            "version": r["ver"], "brief": r["brief"], "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "thread": thread_of(r["id"]), "shared": [u for u in (r["shared_with"] or ()) if cv.is_account(u)],
            "yours": ks[0] or r["user_name"] in ks[1]}


def kit_url(request: Request) -> str:
    """The kit as the VIEWER reaches it: this origin's /canvas/kit/ (the observatory proxies /canvas/ to the canvas
    service; the kit is public vendored files). The shell's CSP allows exactly this one off-document source. Its host
    is the one the viewer reached (relay.viewer_host): behind a cog's front, never the backend's own."""
    return f"{request.url.scheme}://{relay.viewer_host(request, bool(CANVAS_PRE)) or request.url.netloc}{CANVAS_PRE}/canvas/kit/"


def missing(e: Exception) -> bool:
    """An estate where the canvas bridge never ran has no canvas tables: that is an empty list, not an error."""
    return "does not exist" in str(e)


@router.get("/api/ws/canvases")
async def ws_canvases(request: Request):
    ks = keys(request)
    try:
        rows = await _pool(request).fetch(LIST_SQL, *ks)
    except Exception as e:                          # noqa: BLE001
        if missing(e):
            return []
        raise
    return [shape(r, ks) for r in rows]


async def _one(request: Request, cid: int):
    """The canvas, when this viewer sees it; else None (a 404: never "it exists, not yours")."""
    try:
        return await _pool(request).fetchrow(
            f"SELECT {COLS} FROM canvases WHERE id=$1 AND NOT archived AND {cv.sees_sql('$2', '$3')}", cid, *keys(request))
    except Exception as e:                          # noqa: BLE001
        if missing(e):
            return None
        raise


@router.get("/api/ws/canvases/{cid}")
async def ws_canvas(cid: int, request: Request):
    c = await _one(request, cid)
    if not c:
        return JSONResponse({"error": "no such canvas"}, status_code=404)
    vers = await _pool(request).fetch(
        "SELECT version AS ver, author, note, ts FROM canvas_versions WHERE canvas_id=$1 ORDER BY version DESC LIMIT $2",
        cid, VERSIONS_MAX)
    return {**shape(c, keys(request)), "versions": [{"version": r["ver"], "author": r["author"], "note": r["note"],
                                      "ts": r["ts"].isoformat() if r["ts"] else None} for r in vers]}


@router.get("/api/ws/canvases/{cid}/render")
async def ws_canvas_render(cid: int, request: Request, v: int = 0, theme: str = "dark"):
    from bridges.canvas_shell import render       # pure (no db, no app): canvas's own shell, CSP and shim
    c = await _one(request, cid)
    if not c:
        return JSONResponse({"error": "no such canvas"}, status_code=404)
    ver = v or c["ver"]
    row = await _pool(request).fetchrow("SELECT html FROM canvas_versions WHERE canvas_id=$1 AND version=$2", cid, ver)
    if not row:
        return {"version": 0, "html": None}
    return {"version": ver, "html": render(cid, c["title"], ver, row["html"], kit_url(request), "light" if theme == "light" else "dark")}


@router.get("/api/ws/canvases/{cid}/data")
async def ws_canvas_data(cid: int, request: Request, key: str | None = None):
    if not await _one(request, cid):
        return JSONResponse({"error": "no such canvas"}, status_code=404)
    pool = _pool(request)
    if key is not None:
        row = await pool.fetchrow("SELECT value FROM canvas_data WHERE canvas_id=$1 AND key=$2", cid, key)
        return {"key": key, "value": json.loads(row["value"]) if row else None}
    rows = await pool.fetch("SELECT key, value FROM canvas_data WHERE canvas_id=$1", cid)
    return {r["key"]: json.loads(r["value"]) for r in rows}


class Share(BaseModel):
    shared: list[str]


@router.post("/api/ws/canvases/{cid}/share")
async def ws_canvas_share(cid: int, body: Share, request: Request):
    """Its maker or the owner shares a canvas with members, by account (cv.share_set: the members table's; one no longer
    a member drops out). Its invitees stay as canvas set them: they are shared from canvas, by the owner."""
    from observatory.api import members
    ks = keys(request)
    c = await _one(request, cid)
    if not c:
        return JSONResponse({"error": "no such canvas"}, status_code=404)
    if not (ks[0] or c["user_name"] in ks[1]):
        return JSONResponse({"error": "only the canvas's maker or the owner shares it"}, status_code=403)
    pool = _pool(request)
    guests = [u for u in (c["shared_with"] or ()) if not cv.is_account(u)]
    users, _, strangers = cv.share_set([u for u in body.shared if cv.is_account(u)] + guests, c["shared_with"],
                                       [r["uid"] for r in await members.rows(pool)])
    if strangers:
        return JSONResponse({"error": "share with this org's members only"}, status_code=400)
    if users != guests and c["tier"] == "personal":
        return JSONResponse({"error": "a personal-tier canvas is never shared"}, status_code=400)
    await pool.execute("UPDATE canvases SET shared_with=$2 WHERE id=$1", cid, users)
    return {"id": cid, "shared": [u for u in users if cv.is_account(u)]}
