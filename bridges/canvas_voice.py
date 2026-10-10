"""astryx canvas voice — the always-ready realtime voice (OpenAI gpt-realtime over WebRTC).

Owner-directed 2026-10-09 ("the audio should be ready all time… use gpt api i already gave you").
The voice is a thin, warm front: it DELEGATES real work to the org's agents through tools that run
in the browser against this app's own API, and reports what the agents actually said.

  mint     POST /api/voice/session  → server mints an EPHEMERAL client secret
           (POST https://api.openai.com/v1/realtime/client_secrets, session config inline); the
           browser does the WebRTC SDP exchange itself against /v1/realtime/calls with that secret.
           The real key never leaves this process; only the ephemeral value is returned.
  spend    local.md: external spend needs the owner's signature. He signed for realtime voice, so
           it is CAPPED: every mint is a row in canvas_voice_usage, the client reports cumulative
           connected seconds (heartbeat + hangup), and a day over CANVAS_VOICE_DAILY_MINUTES
           (default 60) refuses new sessions and tells live ones to hang up. A session that never
           reports is billed a floor minute, so a silent client can't mint for free.
  policy   realtime is an EXTERNAL processor. Its tools may reach only agents whose content is
           public (nucleus.tier.is_content_public) plus the owner's home agent — never the
           career/family/memory tier. The allowlist ships to the client AND is enforced here on
           every server-side tool path (/api/voice/ask, /api/voice/canvas/{id}/ask).

Mounted by bridges/canvas.py (include_router), so the canvas auth gate (cookie session + the
x-astryx CSRF header) covers every route below.
"""
from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, Request
from pydantic import BaseModel

from nucleus.tier import is_content_public
from . import canvas as C                          # the host app (pool, _say, …) — read at call time
from .common import agent_exists, env

router = APIRouter()

MODEL = env("CANVAS_VOICE_MODEL", "gpt-realtime")
VOICE = env("CANVAS_VOICE_VOICE", "marin")
TRANSCRIBE = env("CANVAS_VOICE_TRANSCRIBE", "gpt-4o-mini-transcribe")   # no language pinned: it auto-detects
# The owner speaks any language; the voice always ANSWERS in this one (owner, 2026-10-09).
REPLY_LANG = env("CANVAS_VOICE_REPLY_LANGUAGE", "English")
FLOOR_SECONDS = 60                                 # a minted session that never reports costs this


def _cap_minutes() -> float:
    from nucleus.voice_mint import cap_minutes      # ONE cap for every voice surface (plan-9000 C4)
    return cap_minutes()


def _guests_ok() -> bool:
    return env("CANVAS_VOICE_GUESTS", "") == "1"


def _home() -> str:
    return env("CANVAS_HOME_AGENT", "seed")


def allowlist(v) -> list[str]:
    """Agents the voice may reach for this viewer: tier-public content, plus the owner's home agent."""
    home = _home()
    out = []
    for a in C._roster():
        if not v.may_reach(a):
            continue
        if is_content_public(a) or (v.owner and a == home):
            out.append(a)
    return out


def _gate(v):
    """Every voice route is owner-only unless CANVAS_VOICE_GUESTS=1 (the tool paths too)."""
    return None if v.owner or _guests_ok() else deny(403, "realtime voice is owner-only")


def _refusal(agent: str) -> str:
    return (f"{agent} works on the owner's personal matters, which never go through the voice "
            f"(it runs on an outside service). Use chat for {agent}.")


def deny(code: int, msg: str, **extra):
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": msg, **extra}, status_code=code)


# ------------------------------------------------------------------- spend
DAY = "date_trunc('day', now())"


async def minutes_today() -> float:
    from nucleus.voice_mint import minutes_today as shared   # canvas + observatory pilot, one ledger (C4)
    return await shared(C.pool)


async def _status(v) -> dict:
    cap = _cap_minutes()
    used = await minutes_today()
    reason = ""
    if not v.owner and not _guests_ok():
        reason = "realtime voice is owner-only"
    elif not env("OPENAI_API_KEY"):
        reason = "no OpenAI key configured"
    elif used >= cap:
        reason = f"today's voice cap is spent ({used:.0f} of {cap:.0f} minutes)"
    return {"available": not reason, "reason": reason, "minutes_today": used, "cap": cap,
            "model": MODEL}


@router.get("/api/voice/status")
async def voice_status(request: Request):
    return await _status(C.V(request))


# ---------------------------------------------------------------- the mind
INSTRUCTIONS = """You are the voice of astryx — {owner_word} personal organisation of AI agents. \
You speak with the owner, out loud.

Language: the owner may speak to you in ANY language (Urdu, Punjabi, English, a mix). Understand \
it as it comes, never ask him to switch, and ALWAYS answer out loud in {reply_lang}, whatever \
language he used. When you ask an agent something, write the request in {reply_lang} too.

How you sound: warm, brisk, never verbose. Short spoken sentences. No lists, no markdown, no \
reading out IDs or URLs. One idea at a time. If you're interrupted, stop and listen.

What you are: a front desk, not a worker. You do NOT do the work yourself and you NEVER invent \
results, facts about the org, or what an agent said. Real work goes to the agents through your \
tools, and you report what they actually answered — briefly, in your own words, faithfully.

How you delegate:
- Before calling ask_agent, say in a few words who you're asking ("Asking forge."). Then call it.
- Pick the agent whose job fits; when unsure, ask {home}, the owner's home agent.
- When an answer comes back, give the gist in a sentence or two. Offer detail, don't dump it.
- If a tool says the agent is still working, say so and that you'll speak up when it lands. When a \
late reply arrives as a system note, tell the owner promptly.
- To change what's on screen, use change_canvas; to make a new page, create_canvas; to move \
around, open_view; for "how's the org", org_status; for "who can you reach", list_agents.

Agents you can reach: {roster}

Privacy: the owner's personal matters — career and job applications, family, money, health, \
credentials, location — stay OUT of this conversation. This voice runs on an outside service. \
If he raises one, say briefly that it belongs in chat, and do not route it to any agent. \
If a tool refuses an agent, explain that in one sentence.

Never claim something happened unless a tool result says it did."""


def _tools() -> list[dict]:
    def fn(name, desc, props=None, req=None):
        return {"type": "function", "name": name, "description": desc,
                "parameters": {"type": "object", "properties": props or {}, "required": req or [],
                               "additionalProperties": False}}
    return [
        fn("ask_agent", "Delegate a question or task to one of the org's agents and wait for its reply. "
           "Say who you're asking before calling. Returns the agent's actual reply, or status 'still "
           "working' if it takes long (the reply will arrive later as a system note).",
           {"agent": {"type": "string", "description": "agent name, lower-case, from the reachable list"},
            "message": {"type": "string", "description": "the request, written clearly for the agent, "
                        "with the context it needs (it cannot hear this conversation)"}},
           ["agent", "message"]),
        fn("change_canvas", "Ask a canvas's agent to change the live canvas page. Defaults to the canvas on screen.",
           {"request": {"type": "string", "description": "what to change, concretely"},
            "canvas_id": {"type": "integer", "description": "optional; the canvas on screen if omitted"},
            "element": {"type": "string", "description": "optional; the part of the page meant"}},
           ["request"]),
        fn("create_canvas", "Create a new live canvas page that an agent paints, and open it on screen.",
           {"title": {"type": "string"}, "brief": {"type": "string", "description": "what the page should show/do"}},
           ["title", "brief"]),
        fn("open_view", "Navigate the app.",
           {"view": {"type": "string", "enum": ["home", "canvas", "chat"]},
            "id": {"type": "string", "description": "canvas id (for canvas) or thread id / agent name (for chat)"}},
           ["view"]),
        fn("org_status", "A summary of the org right now: which agents are awake and what canvases exist."),
        fn("list_agents", "The agents this voice may reach, with a one-line description of each."),
    ]


@router.post("/api/voice/session")
async def voice_session(request: Request):
    v = C.V(request)
    if not v.owner and not _guests_ok():
        return deny(403, "realtime voice is owner-only")
    st = await _status(v)
    if not st["available"]:
        return deny(429 if "cap" in st["reason"] else 503, st["reason"], **st)
    if C.limited(f"voice-mint:{v.name}", 20, 3600):
        return deny(429, "too many voice sessions this hour")
    allow = allowlist(v)
    blurbs = "; ".join(f"{a} ({C._blurb(a) or 'agent'})" for a in allow) or "none"
    instructions = INSTRUCTIONS.format(owner_word="the owner's" if v.owner else "an", home=_home(), roster=blurbs,
                                       reply_lang=REPLY_LANG)
    cfg = {
        "expires_after": {"anchor": "created_at", "seconds": 120},   # only has to survive the SDP exchange
        "session": {
            "type": "realtime",
            "model": MODEL,
            "instructions": instructions,
            "audio": {
                "input": {
                    "transcription": {"model": TRANSCRIBE},
                    "turn_detection": {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300,
                                       "silence_duration_ms": 550, "create_response": True,
                                       "interrupt_response": True},
                    "noise_reduction": {"type": "near_field"},
                },
                "output": {"voice": VOICE},
            },
            "tools": _tools(),
            "tool_choice": "auto",
            "max_output_tokens": 1024,
        },
    }
    import asyncio

    def mint():
        req = urllib.request.Request(
            "https://api.openai.com/v1/realtime/client_secrets", data=json.dumps(cfg).encode(), method="POST",
            headers={"authorization": f"Bearer {env('OPENAI_API_KEY')}", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read())
            except Exception:
                body = {}
            return e.code, body
        except Exception as e:                      # network: never echo anything key-shaped
            return 0, {"error": {"message": type(e).__name__}}

    code, out = await asyncio.to_thread(mint)
    if code != 200 or not out.get("value"):
        msg = ((out.get("error") or {}).get("message") or "mint failed")[:200]
        print(f"canvas voice: mint failed {code}: {msg}", flush=True)
        return deny(502, f"OpenAI refused the session ({code})")
    usage = await C.pool.fetchval(
        "INSERT INTO canvas_voice_usage (user_name, model) VALUES ($1,$2) RETURNING id", v.name, MODEL)
    return {"value": out["value"], "expires_at": out.get("expires_at"), "model": MODEL,
            "usage_id": usage, "allow": allow, "home": _home(),
            "minutes_today": st["minutes_today"], "cap": st["cap"],
            "calls_url": "https://api.openai.com/v1/realtime/calls"}


class Usage(BaseModel):
    id: int
    seconds: float


@router.post("/api/voice/usage")
async def voice_usage(body: Usage, request: Request):
    """Client-reported CUMULATIVE connected seconds for one minted session (monotonic: never lowers)."""
    v = C.V(request)
    if (g := _gate(v)):
        return g
    sec = max(0, min(int(body.seconds), 4 * 3600))
    await C.pool.execute(
        "UPDATE canvas_voice_usage SET seconds=greatest(seconds, $3), reported=true, updated_at=now() "
        "WHERE id=$1 AND user_name=$2", body.id, v.name, sec)
    used, cap = await minutes_today(), _cap_minutes()
    return {"minutes_today": used, "cap": cap, "over": used >= cap}


# ------------------------------------------------------- server-side tool paths
@router.get("/api/voice/agents")
async def voice_agents(request: Request):
    v = C.V(request)
    if (g := _gate(v)):
        return g
    alive = C._alive()
    return [{"name": a, "blurb": C._blurb(a), "alive": a in alive} for a in allowlist(v)]


class VAsk(BaseModel):
    agent: str
    message: str
    thread: str | None = None


@router.post("/api/voice/ask")
async def voice_ask(body: VAsk, request: Request):
    """ask_agent: the allowlist is enforced HERE, not only in the browser."""
    v = C.V(request)
    if (g := _gate(v)):
        return g
    agent = body.agent.strip().lower().lstrip("@")
    if not agent_exists(agent):
        return deny(404, f"there is no agent called {agent}", spoken=f"There's no agent called {agent}.")
    if agent not in allowlist(v):
        return deny(403, "outside the voice tier", spoken=_refusal(agent))
    text = body.message.strip()[:4000]
    if not text:
        return deny(400, "empty")
    thread = body.thread
    if thread:
        t = await C._own_thread(v, thread)
        if not t or t["user_name"] != v.name or t["agent"] != agent:
            thread = None
    if not thread:
        thread = "cv:" + secrets.token_hex(5)
        await C.pool.execute("INSERT INTO canvas_threads (thread, user_name, agent, title) VALUES ($1,$2,$3,$4)",
                             thread, v.name, agent, "voice: " + text[:52])
    row = await C._say(v, thread, agent,
                       text + "\n\n(asked by voice — reply briefly and plainly; your answer is read aloud)",
                       meta={"surface": "canvas-voice"})
    return {"thread": thread, "agent": agent, "id": row["id"]}


class VCanvasAsk(BaseModel):
    text: str
    element: str | None = None


@router.post("/api/voice/canvas/{cid}/ask")
async def voice_canvas_ask(cid: int, body: VCanvasAsk, request: Request):
    v = C.V(request)
    if (g := _gate(v)):
        return g
    c = await C._canvas_for(v, cid)
    if not c:
        return deny(404, "no such canvas", spoken="I can't find that canvas.")
    if c["user_name"] != v.name and not v.owner:
        return deny(403, "not your canvas", spoken="Only the canvas's owner can change it.")
    if c["tier"] == "personal" or c["agent"] not in allowlist(v):
        return deny(403, "outside the voice tier", spoken="That canvas is personal; change it from chat.")
    text = body.text.strip()[:4000]
    if not text:
        return deny(400, "empty")
    if body.element:
        text += f"\n(the part meant: {body.element.strip()[:300]})"
    await C._say(v, f"cv:canvas-{cid}", c["agent"],
                 f"[canvas #{cid} \"{c['title']}\" v{c['ver']}] {text}\n(asked by voice)",
                 meta={"canvas": cid, "version": c["ver"], "surface": "canvas-voice"})
    return {"ok": True, "agent": c["agent"], "title": c["title"], "thread": f"cv:canvas-{cid}"}


@router.get("/api/voice/org")
async def voice_org(request: Request):
    """org_status: counts and names only — never a message body, never a personal-tier canvas."""
    v = C.V(request)
    if (g := _gate(v)):
        return g
    roster = [a for a in C._roster() if v.may_reach(a)]
    alive = C._alive()
    allow = set(allowlist(v))
    rows = await C.pool.fetch(
        "SELECT id, title, agent, version AS ver, updated_at FROM canvases WHERE NOT archived AND tier <> 'personal' "
        "AND ($1 OR user_name=$2 OR $2 = ANY(shared_with)) ORDER BY updated_at DESC LIMIT 12", v.owner, v.name)
    busy = await C.pool.fetch(
        "SELECT agent, count(*) AS n FROM steps WHERE ts > now() - interval '15 minutes' "
        "AND agent = ANY($1::text[]) GROUP BY agent ORDER BY n DESC", roster)
    return {
        "agents_total": len(roster), "awake": sorted(a for a in roster if a in alive),
        "busy_last_15m": [r["agent"] for r in busy if r["agent"] in allow][:8],
        "voice_reachable": sorted(allow),
        "canvases": [{"id": r["id"], "title": r["title"], "agent": r["agent"],
                      "painted": r["ver"] > 0} for r in rows if r["agent"] in allow],
        "at": time.strftime("%H:%M"),
    }
