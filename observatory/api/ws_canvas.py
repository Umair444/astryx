"""astryx observatory · the chat workspace's window onto CANVAS (feat/chat-workspace, iteration 13).

Canvases are live pages an agent paints (bridges/canvas.py; src/astryx/core/canvas.py is their ONE writer). The
workspace shows them beside the conversation about them, READ-ONLY: it lists them, shows a version, and answers the
page's own data reads. Nothing here writes; asking for a change, rolling back, sharing and archiving stay in canvas.

    GET /api/ws/canvases                    the owner's canvases (not archived), newest first, each with its thread
    GET /api/ws/canvases/{id}               one canvas + its versions (newest first, ≤50)
    GET /api/ws/canvases/{id}/render?v=     {version, html}: that version wrapped in canvas's OWN shell
                                            (bridges/canvas_shell.render: its CSP, theme tokens and postMessage shim)
    GET /api/ws/canvases/{id}/data?key=     the page's live values (one key, or all)

Why a read endpoint here and not the /canvas/ proxy: the proxy needs canvas's own cookie session, which the workspace
doesn't hold (its gate is the observatory owner key). These routes read canvas's tables with the observatory's pool and
serve the page through the SAME pure shell canvas serves, so the CSP and the sandbox contract are canvas's, unchanged.
The frame that shows it (web/src/chat/canvas/CanvasFrame.tsx) uses canvas's sandbox (allow-scripts allow-forms, no
allow-same-origin): an opaque origin with no cookie, no storage and no parent DOM.

OWNER-ONLY BY OMISSION: none of these paths is in main.PUBLIC, so the default-deny gate answers 403 to anyone without
the owner key. The owner sees every canvas, as he does in canvas itself (an invitee's view gate is canvas's business;
the workspace has no invitees).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from astryx.security import relay

router = APIRouter()

_get_pool = None
CANVAS_PRE = ""                                     # /o/<org> in a cog (main.CANVAS_PRE); "" on one org
VERSIONS_MAX = 50

LIST_SQL = ("SELECT id, title, agent, user_name, tier, version AS ver, brief, updated_at FROM canvases "
            "WHERE NOT archived ORDER BY updated_at DESC LIMIT 200")


def bind(get_pool, canvas_prefix: str = "") -> None:
    global _get_pool, CANVAS_PRE
    _get_pool, CANVAS_PRE = get_pool, canvas_prefix


def _pool(request: Request):
    return _get_pool() if _get_pool else request.app.state.pool


def thread_of(cid: int) -> str:
    """The canvas's own conversation (bridges/canvas.py names it so: the viewer, the painter and the crew talk there)."""
    return f"cv:canvas-{cid}"


def shape(r) -> dict:
    return {"id": r["id"], "title": r["title"], "agent": r["agent"], "user": r["user_name"], "tier": r["tier"],
            "version": r["ver"], "brief": r["brief"], "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "thread": thread_of(r["id"])}


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
    try:
        rows = await _pool(request).fetch(LIST_SQL)
    except Exception as e:                          # noqa: BLE001
        if missing(e):
            return []
        raise
    return [shape(r) for r in rows]


async def _one(request: Request, cid: int):
    try:
        return await _pool(request).fetchrow(
            "SELECT id, title, agent, user_name, tier, version AS ver, brief, updated_at FROM canvases WHERE id=$1 AND NOT archived", cid)
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
    return {**shape(c), "versions": [{"version": r["ver"], "author": r["author"], "note": r["note"],
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
