"""astryx observatory · the pilot's realtime voice (plan-9000 S2).

    GET  /api/pilot/voice/status    can a session start now (key present, today's minutes under the cap)
    POST /api/pilot/voice/session   mint an EPHEMERAL client secret; the browser does the WebRTC exchange itself
    POST /api/pilot/voice/usage     cumulative connected seconds for one session (heartbeat + hangup)

THE CALL (iteration 17): the session body may name an agent ({"agent": "db"}; default seed). The voice then speaks AS
that agent: its own room voice (room.voice_of) and its charter's one-line role (workspace.role_of), masked for digit
runs and capped. An unknown or malformed name is a 400 before anything is minted. Nothing else of a charter leaves.

OWNER-ONLY BY OMISSION: none of these paths is in main.PUBLIC_PATHS, so the observatory's default-deny middleware
answers 403 to anyone without the obs key before a handler runs (the guests flag of canvas does not exist here,
since :8090 listens on 0.0.0.0; C4). Spend is the shared ledger and cap in src/astryx/hearing/voice_mint.py.

The voice's tools are the pilot catalog's actions (observatory/pilot/catalog.json), handed to the provider as
function tools. The provider's calls come back to the BROWSER, where the executor runs each as the `room`
principal: views run, reads go through the egress projection, writes and actuates wait for the owner's tap. Nothing
here executes a tool, and no agent prose is reachable from this voice in S2 (C1: screen-only replies come in S3).
"""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from astryx.hearing import voice_mint as V
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
- When he asks to see or change something on screen (a view, an agent, a thread, a chat conversation, a file, the \
theme, scrolling, a search), call the tool AT ONCE, then confirm in a few words ("Done, Nord."). Never describe what \
you are about to do first.
- You can SEE his screen: system notes headed "The owner's screen now" tell you the page, its headings, the open \
conversation and its last lines, kept current as he moves. Use them to understand "this", "that chart", "here". \
For a fresh look call read_screen. Numbers shown as [number] are masked for privacy: never guess them.
- When you talk about something on screen, call point_at with its visible words so your figure goes there.
- In a chat you may draft into the message box (type_in_composer) and switch who the chat is with (switch_agent). \
Sending is send_message: it waits for his tap on Confirm, so say "Tap Confirm to send." and nothing more. Never claim \
a message was sent until a note says he tapped Allow.
- If he asks you to dance, or something he wanted just worked and he's pleased, you may call dance.
- For token or plan usage, call get_usage and say the 5-hour and 7-day percentages and when they reset.
- For goals, call list_goals and give the count and one or two titles.
- Opening an agent's desktop or sending a message needs his tap: when a tool says it is waiting for him, say "Tap \
Confirm on the screen." and nothing more.
- If a tool refuses or fails, say why in one sentence. Never claim something happened unless a tool result says so.
- For real work or questions about the org, call ask_agent ({agent} by default) and say who you asked in a few words.
  In a chat the request goes on that conversation and the answer shows there. When the answer comes it is read back to \
you as a note: tell the owner the gist briefly, in a sentence or two. Never guess an answer before it comes. Only when \
the tool says they will answer aloud in the room, don't repeat it.

Who you are: {persona}

Privacy: the owner's personal matters (career, family, money, health, credentials, location) stay out of this \
conversation; it runs on an outside service."""


def _tools() -> list[dict]:
    ask = {"type": "function", "name": "ask_agent",
           "description": "Hand a request to one of the org's agents (the agent this call is with is the default; seed hosts, forge builds tools, "
                          "painter does design, steward runs infrastructure, canopus careers, memory knows the org's "
                          "past). In an open chat it is posted on that conversation and the answer is shown there; the answer is read back to "
                          "you when it comes, to tell the owner briefly. Use it for anything that is "
                          "real work, not a screen change.",
           "parameters": {"type": "object", "additionalProperties": False, "required": ["agent", "message"],
                          "properties": {"agent": {"type": "string", "maxLength": 64},
                                         "message": {"type": "string", "maxLength": 2000}}}}
    return [{"type": "function", "name": a["name"], "description": a["description"], "parameters": a["parameters"]}
            for a in load_catalog()["actions"]] + [ask]


def deny(code: int, msg: str, **extra):
    return JSONResponse({"error": msg, **extra}, status_code=code)


_get_pool = None


def bind(get_pool) -> None:
    """The host app hands over its pool getter (read at call time: the pool opens in the app's lifespan)."""
    global _get_pool
    _get_pool = get_pool


def _pool(request: Request):
    return _get_pool()


@router.get("/api/pilot/voice/status")
async def status(request: Request):
    pool = _pool(request)
    why = await V.unavailable(pool)
    return {"available": not why, "reason": why, "minutes_today": await V.minutes_today(pool),
            "cap": V.cap_minutes(), "model": MODEL}


NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DIGITS = re.compile(r"(?:\+?\d[\s\-.()]{0,2}){7,}")


def persona(agent: str) -> tuple[str, str] | None:
    """(the persona line, the voice) for `agent`, or None when no such agent exists. The line is the charter's one-line
    role only (workspace.role_of), masked for digit runs and capped: nothing else of a charter reaches the provider."""
    if not NAME.match(agent or ""):
        return None
    try:
        from astryx.core.charter import resolve
        path = resolve(agent)
    except Exception:
        return None
    if not path:
        return None
    from observatory.api import workspace as W
    from observatory.api import room as R
    try:
        role = W.role_of(path.read_text())
    except Exception:
        role = ""
    role = _DIGITS.sub("[number]", role or "")[:200].strip()
    line = (f"you speak as {agent}, one of the org's agents: {role}" if role else f"you speak as {agent}, one of the org's agents.")
    if agent == "seed":
        line = f"you speak as seed, the org's founding agent and the owner's line to it. {role}".strip()
    v = R.voice_of(agent)
    return line + " Stay in that character, briefly; you still drive the screen for him.", (v if v in REALTIME_VOICES else "")


# the voices OpenAI realtime accepts (its 400 lists them); a Room voice outside this set (e.g. 'fable', a TTS-only
# voice) made the mint fail 400 for that agent (11-11), so it falls back to VOICE instead
REALTIME_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "marin", "cedar"}


class SessionReq(BaseModel):
    agent: str = "seed"


@router.post("/api/pilot/voice/session")
async def session(request: Request, body: SessionReq | None = Body(default=None)):
    pool = _pool(request)
    agent = (body.agent if body else "seed").strip().lower() or "seed"
    who = persona(agent)
    if who is None:
        return deny(400, f"no agent named {agent[:64]}")
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
            "instructions": INSTRUCTIONS.format(reply_lang=REPLY_LANG, agent=agent, persona=who[0]),
            "audio": {
                "input": {
                    "transcription": {"model": TRANSCRIBE},
                    "turn_detection": {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300,
                                       "silence_duration_ms": 500, "create_response": True,
                                       "interrupt_response": True},
                    "noise_reduction": {"type": "near_field"},
                },
                "output": {"voice": who[1] or VOICE},
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
            "minutes_today": await V.minutes_today(pool), "cap": V.cap_minutes(), "calls_url": V.CALLS_URL, "agent": agent}


class Usage(BaseModel):
    id: int
    seconds: float


@router.post("/api/pilot/voice/usage")
async def usage(body: Usage, request: Request):
    return await V.report(_pool(request), body.id, USER, body.seconds)
