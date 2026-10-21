"""astryx observatory · the Room's speaker (src/astryx/hearing/room.py is its ears' router).

An agent answers the room with send(to='room'). Every pending row with to_agent='room' is claimed here, once:
  · intent 'chat' (the default): the body is SPOKEN — OpenAI text-to-speech in that agent's own voice — saved as
    var/room/<id>.mp3 and announced to every open observatory tab as {type: 'room_say', id, agent, text, audio};
  · intent 'screen': the body is a JSON {action, args} from the pilot catalog, announced as 'room_screen' so the tab
    runs it through the AGENT principal (pilot.agent: view actions);
  · intent 'live': the agent hands the room to the realtime voice for a live back-and-forth, with its brief:
    announced as 'room_live'.
Delivery is claim-then-act (UPDATE … status='delivered' … RETURNING), so two observatory workers can't both speak a
row. The audio route is owner-only by omission from PUBLIC_PATHS.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from astryx.hearing import voice_mint as V
from observatory.api.hostfile import atomic_write

router = APIRouter()
REPO = Path(__file__).resolve().parents[2]
from astryx import paths  # noqa: E402 — var/ is org estate (its HOME in a cog of several orgs), plan-11324 S3a
AUDIO = paths.estate(__file__) / "var" / "room"
TTS_MODEL = V.env("ROOM_TTS_MODEL", "gpt-4o-mini-tts")
# one voice per agent, so the room can tell them apart by ear; an unlisted agent gets a stable pick from the rest
VOICES = {"seed": "cedar", "painter": "coral", "steward": "sage", "forge": "ash", "canopus": "verse",
          "memory": "shimmer", "scout": "echo", "gemini": "marin", "medic": "ballad"}
SPARE = ["alloy", "fable", "nova", "onyx"]
_get_pool = None
_broadcast = None


def bind(get_pool, broadcast) -> None:
    """The host app hands over its pool getter and its SSE fan-out."""
    global _get_pool, _broadcast
    _get_pool, _broadcast = get_pool, broadcast


def voice_of(agent: str) -> str:
    return VOICES.get(agent) or SPARE[sum(map(ord, agent)) % len(SPARE)]


def speak(text: str, voice: str, out: Path) -> str | None:
    """OpenAI TTS to an mp3 file. Returns None on success, else a short reason (never the key)."""
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech", method="POST",
        data=json.dumps({"model": TTS_MODEL, "voice": voice, "input": text[:3800], "response_format": "mp3",
                         "instructions": "Speak naturally and warmly, like a capable colleague talking in the room."}).encode(),
        headers={"authorization": f"Bearer {V.env('OPENAI_API_KEY')}", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            atomic_write(out, r.read())          # the one host writer (plan-11860 E3): never a torn mp3
        return None
    except urllib.error.HTTPError as e:
        return f"tts http {e.code}"
    except Exception as e:                               # noqa: BLE001: network
        return f"tts {type(e).__name__}"


async def claim_and_act(pool) -> int:
    """Claim every pending room row (to_agent='room') and act on it. Returns how many were handled."""
    rows = await pool.fetch(
        "UPDATE messages SET status='delivered' WHERE id IN (SELECT id FROM messages WHERE to_agent='room' "
        "AND status='pending' ORDER BY id LIMIT 5 FOR UPDATE SKIP LOCKED) RETURNING id, from_agent, intent, body")
    for r in rows:
        agent, intent, text = r["from_agent"], (r["intent"] or "chat"), (r["body"] or "").strip()
        if intent == "screen":
            try:
                cmd = json.loads(text)
                _broadcast({"type": "room_screen", "id": r["id"], "agent": agent,
                            "action": cmd.get("action"), "args": cmd.get("args") or {}})
            except Exception:                                # noqa: BLE001: a malformed screen command is skipped
                _broadcast({"type": "room_screen", "id": r["id"], "agent": agent, "error": "not JSON {action, args}"})
            continue
        if intent == "voice":                            # an agent established who a voice is
            try:
                v = json.loads(text)
                if v.get("merge_into"):                  # two prints are one person: fold the first into the second
                    ok = await merge_voices(pool, str(v.get("voice")), str(v["merge_into"]))
                    _broadcast({"type": "room_voice", "id": r["id"], "agent": agent, "voice": v.get("voice"),
                                "merged_into": v["merge_into"], "ok": ok})
                    continue
                trust = v.get("trust") if v.get("trust") in ("unknown", "claimed", "verified", "owner") else "claimed"
                n = await pool.execute(
                    "UPDATE voices SET name=$2, trust=$3, verified_by=$4, evidence=$5 WHERE label=$1",
                    str(v.get("voice")), (v.get("name") or None), trust, agent, (v.get("evidence") or "")[:500])
                _broadcast({"type": "room_voice", "id": r["id"], "agent": agent, "voice": v.get("voice"),
                            "name": v.get("name"), "trust": trust, "ok": n.endswith(" 1")})
            except Exception:                                # noqa: BLE001
                _broadcast({"type": "room_voice", "id": r["id"], "agent": agent, "error": "not JSON {voice, name, trust}"})
            continue
        if intent == "live":
            _broadcast({"type": "room_live", "id": r["id"], "agent": agent, "brief": text[:2000]})
            continue
        out = AUDIO / f"{r['id']}.mp3"
        err = await asyncio.to_thread(speak, text, voice_of(agent), out)
        _broadcast({"type": "room_say", "id": r["id"], "agent": agent, "text": text[:1200],
                    "audio": None if err else f"/api/room/audio/{r['id']}", "error": err})
    return len(rows)


async def merge_voices(pool, src: str, dst: str) -> bool:
    """Fold voice `src` into `dst` (one person heard at two mic distances, 10-11): dst's print becomes the n-weighted
    mean of both, and src is deleted. dst keeps its own name and trust: a merge never raises trust. False when either
    label is missing or they are the same."""
    if src == dst:
        return False
    async with pool.acquire() as c:
        async with c.transaction():
            a = await c.fetchrow("SELECT embedding, n FROM voices WHERE label=$1 FOR UPDATE", src)
            b = await c.fetchrow("SELECT embedding, n FROM voices WHERE label=$1 FOR UPDATE", dst)
            if a is None or b is None:
                return False
            na, nb = a["n"] or 1, b["n"] or 1
            mean = [(x * na + y * nb) / (na + nb) for x, y in zip(a["embedding"], b["embedding"])]
            await c.execute("UPDATE voices SET embedding=$2, n=$3, last_heard=now() WHERE label=$1", dst, mean, na + nb)
            await c.execute("DELETE FROM voices WHERE label=$1", src)
    return True


async def speaker_task():
    """Forever: wake on every wire NOTIFY (the host's listener calls nudge()), and sweep every 3s as a backstop."""
    while True:
        try:
            pool = _get_pool() if _get_pool else None
            if pool is not None and _broadcast is not None:
                await claim_and_act(pool)
        except Exception:                                    # noqa: BLE001: never kill the loop
            pass
        try:
            await asyncio.wait_for(_nudge.wait(), timeout=3)
        except asyncio.TimeoutError:
            pass
        _nudge.clear()


_nudge = asyncio.Event()


def nudge() -> None:
    _nudge.set()


@router.get("/api/room/audio/{mid}")
async def audio(mid: int):
    f = AUDIO / f"{int(mid)}.mp3"
    if not f.is_file():
        return JSONResponse({"error": "no audio"}, status_code=404)
    return FileResponse(f, media_type="audio/mpeg", headers={"cache-control": "private, max-age=3600"})


class Ask(__import__("pydantic").BaseModel):
    agent: str
    message: str


@router.post("/api/room/ask")
async def ask(body: Ask):
    """The live voice's ask_agent: the same wire message a spoken sentence makes (src/astryx/hearing/room.py's body)."""
    from astryx.hearing import room as R
    agent = body.agent.strip().lower()
    if agent not in R.roster():
        return JSONResponse({"error": f"no agent named {agent}"}, status_code=404)
    mid = await _get_pool().fetchval(
        "INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES ('room', $1, $2, 'chat', $3) "
        "RETURNING id", agent, R.THREAD, R.body(body.message, "owner (live voice)", None))
    return {"ok": True, "id": mid}


@router.get("/api/room/voices")
async def voices():
    return {"voices": VOICES, "model": TTS_MODEL}
