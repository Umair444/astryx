"""astryx observatory · the org's MIND (src/astryx/mind/mind.py, owner 11-15): what the org feels, wants and has
understood, read from the mind's own store. One read, nothing written:

    GET  /api/mind                        {energy, drives, itches, insights, yields, thinking, heat, rules}
    GET  /api/mind/system                 the economy as a system: equations, objectives, flows, thermo, market, game
    POST /api/mind/tick                   feel now, and let whoever wants to think wake: {woke, what} | {woke: null, why}
    POST /api/mind/itch/{id}/drop         {why}   the owner lets an itch go (the reason is kept)
    POST /api/mind/insight/{id}/retire    {why}   the owner retires an idea (its epitaph)
    POST /api/mind/wonder                 {agent, what}   the owner shares a question with an agent: a wonder, not a task

OWNER-ONLY: the read by omission (the path is in no public or member list: an itch's evidence quotes the org's own
asks), every write by the owner predicate main binds here.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from astryx.mind import mind as _mind  # noqa: E402

router = APIRouter()
_owner = None


def bind(owner) -> None:
    global _owner
    _owner = owner


class Why(BaseModel):
    why: str = ""


class Wonder(BaseModel):
    agent: str
    what: str


async def _act(request: Request, fn):
    """One owner act on the mind's store: 403 unless the owner; the mind's own refusal (SystemExit) as a 400 in words."""
    if _owner is None or not _owner(request):
        return JSONResponse({"error": "the owner's act"}, status_code=403)
    def run():
        with _mind.connect() as c:
            return json.loads(json.dumps(fn(c), default=str))
    try:
        return await asyncio.to_thread(run)
    except SystemExit as e:
        return JSONResponse({"error": str(e).removeprefix("mind: ")}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"the mind's store is not answering ({type(e).__name__})"}, status_code=503)


@router.post("/api/mind/tick")
async def mind_tick(request: Request):
    def go(c):
        out = {"felt": _mind.feel(c), **_mind.want(c, lambda to, body: _mind._wake(c, to, body))}
        out.pop("body", None)
        return out
    return await _act(request, go)


@router.post("/api/mind/itch/{itch_id}/drop")
async def mind_drop(itch_id: int, body: Why, request: Request):
    return await _act(request, lambda c: _mind.drop(c, "owner", itch_id, body.why, any_agent=True))


@router.post("/api/mind/insight/{insight_id}/retire")
async def mind_retire(insight_id: int, body: Why, request: Request):
    return await _act(request, lambda c: _mind.retire(c, "owner", insight_id, body.why, any_author=True))


@router.post("/api/mind/wonder")
async def mind_wonder(body: Wonder, request: Request):
    import re
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,60}", body.agent or ""):
        return JSONResponse({"error": "name an agent"}, status_code=400)
    return await _act(request, lambda c: _mind.note(c, body.agent, "wonder", body.what, by="the owner"))


def _state() -> dict:
    with _mind.connect() as c:
        return json.loads(json.dumps(_mind.state(c), default=str))


def _system():
    from astryx.econ import system
    with _mind.connect() as c:
        return json.loads(json.dumps(system.read(c), default=str))


@router.get("/api/mind/system")
async def mind_system(request: Request):
    """The org's economy as a system (src/astryx/econ/system.py): equations, objectives, flows, projection, thermo,
    market, commons, game. One read; the owner's page."""
    if _owner is None or not _owner(request):
        return JSONResponse({"error": "the owner's page"}, status_code=403)
    try:
        return await asyncio.to_thread(_system)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"the economy's view is not answering ({type(e).__name__})"}, status_code=503)


@router.get("/api/mind")
async def mind_state(request: Request):
    if _owner is None or not _owner(request):       # a positive check, not absence from a list (medic 12260)
        return JSONResponse({"error": "the owner's page"}, status_code=403)
    try:
        return await asyncio.to_thread(_state)
    except Exception as e:  # noqa: BLE001 — the store unreachable: say so, never a stack
        return JSONResponse({"error": f"the mind's store is not answering ({type(e).__name__})"}, status_code=503)
