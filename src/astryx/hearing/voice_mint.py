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
    return config.read_env(paths.estate(__file__) / ".env").get(key, default)   # the ONE .env reader (plan-10224)


def cap_minutes() -> float:
    try:
        return float(env("CANVAS_VOICE_DAILY_MINUTES", "60"))
    except ValueError:
        return 60.0


async def minutes_today(pool, user: str | None = None) -> float:
    """Today's voice minutes: the whole org's, or one ledger user's (a person's feature: see who())."""
    s = await pool.fetchval(
        f"SELECT coalesce(sum(greatest(seconds, CASE WHEN reported THEN 0 ELSE {FLOOR_SECONDS} END)), 0) "
        f"FROM canvas_voice_usage WHERE minted_at >= date_trunc('day', now())"
        + (" AND user_name = $1" if user else ""), *([user] if user else []))
    return round(float(s) / 60.0, 2)


def who(handle: str | None, feature: str) -> str:
    """The ledger's user for one person's use of one feature (owner 11-17: each member's minutes are their own)."""
    return f"{handle or 'owner'}/{feature}"


async def unavailable(pool, user: str | None = None, limit: float | None = None, charge: int = 0) -> str:
    """Why a new session can't start right now, or '' when it can. The org's cap always holds; a person's own daily
    `limit` (their feature's minutes in the Admin panel) holds on top of it, counting the `charge` (seconds) this new
    session would cost at once."""
    if not env("OPENAI_API_KEY"):
        return "no OpenAI key configured"
    used, cap = await minutes_today(pool), cap_minutes()
    if used >= cap:
        return f"today's voice cap is spent ({used:.0f} of {cap:.0f} minutes)"
    if user and limit is not None:
        mine = await minutes_today(pool, user)
        if mine >= limit or mine + charge / 60.0 > limit + 1e-9:
            return f"your voice minutes for today are spent ({mine:.0f} of {limit:.0f})"
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


async def record(pool, user: str, model: str, seconds: int = 0) -> int:
    """One mint on the ledger. `seconds` > 0 charges it that much at once, and report() can only raise it: what a
    non-owner's session costs at least, whatever their own browser later reports (medic 12822)."""
    return await pool.fetchval(
        "INSERT INTO canvas_voice_usage (user_name, model, seconds, reported) VALUES ($1,$2,$3,$4) RETURNING id",
        user, model, int(seconds), seconds > 0)


def member_floor(feature: str, limit: float | None) -> int:
    """The seconds a non-owner's session is charged at its mint (never lowered by a report): a Call
    PILOT_MEMBER_SESSION_MIN minutes (default 10), dictation FLOOR_SECONDS; never more than the person's own limit."""
    try:
        base = float(env("PILOT_MEMBER_SESSION_MIN", "10")) * 60 if feature == "call" else FLOOR_SECONDS
    except ValueError:
        base = 600.0 if feature == "call" else FLOOR_SECONDS
    return int(min(base, limit * 60) if limit is not None else base)


_mints_by: dict[str, list[float]] = {}


def mint_allowed(user: str, per_hour: int) -> bool:
    """This person's mints in the last hour are under `per_hour` (each person their own count: a member never uses up
    the owner's). Records the mint when it is."""
    import time
    now = time.time()
    got = _mints_by.setdefault(user, [])
    got[:] = [t for t in got if now - t < 3600]
    if len(got) >= per_hour:
        return False
    got.append(now)
    return True


async def report(pool, usage_id: int, user: str, seconds: float) -> dict:
    """Cumulative connected seconds for one session (monotonic: never lowers)."""
    sec = max(0, min(int(seconds), 4 * 3600))
    await pool.execute(
        "UPDATE canvas_voice_usage SET seconds=greatest(seconds, $3), reported=true, updated_at=now() "
        "WHERE id=$1 AND user_name=$2", usage_id, user, sec)
    used, cap = await minutes_today(pool), cap_minutes()
    return {"minutes_today": used, "cap": cap, "over": used >= cap}
