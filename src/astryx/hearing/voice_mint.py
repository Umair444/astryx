"""astryx · voice mint — the ONE realtime-voice spend path, shared by every surface (plan-9000 C4).

Canvas (bridges/canvas_voice.py) and the observatory pilot (observatory/api/pilot_voice.py) both mint OpenAI
realtime sessions. Spend is the owner's signature (local.md), so it has one cap and one ledger for the whole org:
  · ONE table, canvas_voice_usage: every mint is a row; the client reports cumulative connected seconds;
    a session that never reports costs FLOOR_SECONDS, so a silent client can't mint for free;
  · ONE cap, CANVAS_VOICE_DAILY_MINUTES (default 60, owner 10-10: "keep it 60 min"), across both surfaces;
  · the real key never leaves the server: only the provider's EPHEMERAL client secret is returned.
Each surface keeps its own owner predicate (canvas: cookie + CSRF; observatory: the obs key via its
default-deny middleware) and its own instructions and tools.
"""
from __future__ import annotations
if not __package__:  # run by path: the checkout root goes first on sys.path so `astryx` resolves (goal 10224 S4)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx.paths import repo_root  # noqa: E402
from astryx import config, paths  # noqa: E402

import asyncio
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

REPO = repo_root(__file__)
FLOOR_SECONDS = 60
CLIENT_SECRETS = "https://api.openai.com/v1/realtime/client_secrets"
CALLS_URL = "https://api.openai.com/v1/realtime/calls"


def env(key: str, default: str = "") -> str:
    v = config.org_env(key)
    if v:
        return v
    f = paths.estate(__file__) / ".env"
    if f.is_file():
        for line in f.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return default


def cap_minutes() -> float:
    try:
        return float(env("CANVAS_VOICE_DAILY_MINUTES", "60"))
    except ValueError:
        return 60.0


async def minutes_today(pool) -> float:
    s = await pool.fetchval(
        f"SELECT coalesce(sum(greatest(seconds, CASE WHEN reported THEN 0 ELSE {FLOOR_SECONDS} END)), 0) "
        f"FROM canvas_voice_usage WHERE minted_at >= date_trunc('day', now())")
    return round(float(s) / 60.0, 2)


async def unavailable(pool) -> str:
    """Why a new session can't start right now, or '' when it can."""
    if not env("OPENAI_API_KEY"):
        return "no OpenAI key configured"
    used, cap = await minutes_today(pool), cap_minutes()
    if used >= cap:
        return f"today's voice cap is spent ({used:.0f} of {cap:.0f} minutes)"
    return ""


async def mint(cfg: dict) -> tuple[int, dict]:
    """POST the session config for an ephemeral client secret. Never raises; never echoes the key."""
    def go():
        req = urllib.request.Request(
            CLIENT_SECRETS, data=json.dumps(cfg).encode(), method="POST",
            headers={"authorization": f"Bearer {env('OPENAI_API_KEY')}", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, {}
        except Exception as e:                       # network: the class name only
            return 0, {"error": {"message": type(e).__name__}}
    return await asyncio.to_thread(go)


async def record(pool, user: str, model: str) -> int:
    return await pool.fetchval(
        "INSERT INTO canvas_voice_usage (user_name, model) VALUES ($1,$2) RETURNING id", user, model)


async def report(pool, usage_id: int, user: str, seconds: float) -> dict:
    """Cumulative connected seconds for one session (monotonic: never lowers)."""
    sec = max(0, min(int(seconds), 4 * 3600))
    await pool.execute(
        "UPDATE canvas_voice_usage SET seconds=greatest(seconds, $3), reported=true, updated_at=now() "
        "WHERE id=$1 AND user_name=$2", usage_id, user, sec)
    used, cap = await minutes_today(pool), cap_minutes()
    return {"minutes_today": used, "cap": cap, "over": used >= cap}
