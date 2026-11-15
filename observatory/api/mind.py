"""astryx observatory · the org's MIND (src/astryx/mind/mind.py, owner 11-15): what the org feels, wants and has
understood, read from the mind's own store. One read, nothing written:

    GET /api/mind      {energy, drives, itches, insights, heat, rules}

OWNER-ONLY BY OMISSION (the path is in no public or member list): an itch's evidence quotes the org's own asks.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from astryx.mind import mind as _mind  # noqa: E402

router = APIRouter()


def _state() -> dict:
    with _mind.connect() as c:
        return json.loads(json.dumps(_mind.state(c), default=str))


@router.get("/api/mind")
async def mind_state():
    try:
        return await asyncio.to_thread(_state)
    except Exception as e:  # noqa: BLE001 — the store unreachable: say so, never a stack
        return JSONResponse({"error": f"the mind's store is not answering ({type(e).__name__})"}, status_code=503)
