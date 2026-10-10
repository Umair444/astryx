"""astryx observatory · the pilot's realtime voice (plan-9000 S2).

    GET  /api/pilot/voice/status    can a session start now (key present, today's minutes under the cap)
    POST /api/pilot/voice/session   mint an EPHEMERAL client secret; the browser does the WebRTC exchange itself
    POST /api/pilot/voice/usage     cumulative connected seconds for one session (heartbeat + hangup)

OWNER-ONLY BY OMISSION: none of these paths is in main.PUBLIC_PATHS, so the observatory's default-deny middleware
answers 403 to anyone without the obs key before a handler runs (the guests flag of canvas does not exist here,
since :8090 listens on 0.0.0.0; C4). Spend is the shared ledger and cap in nucleus/voice_mint.py.

The voice's tools are the pilot catalog's actions (observatory/pilot/catalog.json), handed to the provider as
function tools. The provider's calls come back to the BROWSER, where the executor runs each as the `room`
principal: views run, reads go through the egress projection, writes and actuates wait for the owner's tap. Nothing
here executes a tool, and no agent prose is reachable from this voice in S2 (C1: screen-only replies come in S3).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from nucleus import voice_mint as V
from observatory.pilot.catalog import load as load_catalog

router = APIRouter()

MODEL = V.env("PILOT_VOICE_MODEL", V.env("CANVAS_VOICE_MODEL", "gpt-realtime"))
VOICE = V.env("CANVAS_VOICE_VOICE", "marin")
TRANSCRIBE = V.env("CANVAS_VOICE_TRANSCRIBE", "gpt-4o-mini-transcribe")
REPLY_LANG = V.env("CANVAS_VOICE_REPLY_LANGUAGE", "English")
USER = "observatory-owner"
_mints: list[float] = []                          # this process's mint times, for the hourly rate limit

INSTRUCTIONS = """You are the voice of the astryx observatory: the live view of the owner's organisation of AI \
agents. You speak with the owner, out loud, and you DRIVE THE SCREEN for him with your tools.

Language: he may speak any language (Urdu, Punjabi, English, a mix). Understand it as it comes and always answer \
out loud in {reply_lang}.

How you sound: warm, brisk, never verbose. One or two short spoken sentences. No lists, no markdown, never read \
out IDs, URLs or code.

What you do:
- When he asks to see or change something on screen (a view, an agent, a thread, the theme, scrolling), call the \
tool AT ONCE, then confirm in a few words ("Done, Nord."). Never describe what you are about to do first.
- When he asks what is on screen, call get_view_state.
- For token or plan usage, call get_usage and say the 5-hour and 7-day percentages and when they reset.
- For goals, call list_goals and give the count and one or two titles.
- Opening an agent's desktop needs his tap: when a tool says it is waiting for him, say "Tap Allow on the \
screen." and nothing more.
- If a tool refuses or fails, say why in one sentence. Never claim something happened unless a tool result says so.
- You cannot ask agents to do work yet. If he asks for that, say it is coming next and he can use the wire.

Privacy: the owner's personal matters (career, family, money, health, credentials, location) stay out of this \
conversation; it runs on an outside service."""


def _tools() -> list[dict]:
    return [{"type": "function", "name": a["name"], "description": a["description"], "parameters": a["parameters"]}
            for a in load_catalog()["actions"]]


def deny(code: int, msg: str, **extra):
    return JSONResponse({"error": msg, **extra}, status_code=code)


def _pool(request: Request):
    import main                                   # the host app's pool, read at call time
    return main.pool


@router.get("/api/pilot/voice/status")
async def status(request: Request):
    pool = _pool(request)
    why = await V.unavailable(pool)
    return {"available": not why, "reason": why, "minutes_today": await V.minutes_today(pool),
            "cap": V.cap_minutes(), "model": MODEL}


@router.post("/api/pilot/voice/session")
async def session(request: Request):
    pool = _pool(request)
    why = await V.unavailable(pool)
    if why:
        return deny(429 if "cap" in why else 503, why)
    now = time.time()
    _mints[:] = [t for t in _mints if now - t < 3600]
    if len(_mints) >= 20:
        return deny(429, "too many voice sessions this hour")
    cfg = {
        "expires_after": {"anchor": "created_at", "seconds": 120},   # only has to survive the SDP exchange
        "session": {
            "type": "realtime",
            "model": MODEL,
            "instructions": INSTRUCTIONS.format(reply_lang=REPLY_LANG),
            "audio": {
                "input": {
                    "transcription": {"model": TRANSCRIBE},
                    "turn_detection": {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300,
                                       "silence_duration_ms": 500, "create_response": True,
                                       "interrupt_response": True},
                    "noise_reduction": {"type": "near_field"},
                },
                "output": {"voice": VOICE},
            },
            "tools": _tools(),
            "tool_choice": "auto",
            "max_output_tokens": 600,
        },
    }
    code, out = await V.mint(cfg)
    if code != 200 or not out.get("value"):
        msg = ((out.get("error") or {}).get("message") or "mint failed")[:200]
        print(f"pilot voice: mint failed {code}: {msg}", flush=True)
        return deny(502, f"OpenAI refused the session ({code})")
    _mints.append(now)
    usage_id = await V.record(pool, USER, MODEL)
    return {"value": out["value"], "expires_at": out.get("expires_at"), "model": MODEL, "usage_id": usage_id,
            "minutes_today": await V.minutes_today(pool), "cap": V.cap_minutes(), "calls_url": V.CALLS_URL}


class Usage(BaseModel):
    id: int
    seconds: float


@router.post("/api/pilot/voice/usage")
async def usage(body: Usage, request: Request):
    return await V.report(_pool(request), body.id, USER, body.seconds)
