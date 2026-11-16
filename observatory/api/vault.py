"""astryx observatory · the vault: the org's named logins and keys (src/astryx/core/vault.py;
homes/seed/agents-credentials/DESIGN.md, medic 12364). Owner-only, every route, positively.

    GET    /api/vault                 every credential: name, kind, endpoint, models, cap, whether a value is set, who uses it
    PUT    /api/vault/{name}          add or change one; `value` (optional on a change) is written to .env and never returned
    DELETE /api/vault/{name}          remove one (refused while an agent uses it)

A value goes to .env under the key the server derives from the name (vault.env_key), through the one locked writer
(config.set_env), and is never echoed, logged or stored anywhere else. An agent is connected to a credential through
its runtime entry (PUT /api/agents/{name}/runtime, `credential`): a KEY is metered spend, so that needs the owner's
confirm_billing, as the org's own metered login does (local.md Economy).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from astryx import config  # noqa: E402
from astryx.core import vault as V  # noqa: E402

router = APIRouter()
_owner = None
ESTATE: Path | None = None


def bind(owner, estate) -> None:
    global _owner, ESTATE
    _owner, ESTATE = owner, Path(estate)


class Cred(BaseModel):
    kind: str
    base_url: str = ""
    models: dict | None = None
    cap_tokens_day: int | None = None
    value: str = ""


def _runtime() -> dict:
    try:
        d = json.loads((ESTATE / "runtime.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _view() -> dict:
    env, vault, uses = config.read_env(ESTATE / ".env"), V.load(ESTATE), V.used_by(_runtime())
    return {"credentials": [{"name": n, **e, "has_value": bool(env.get(V.PREFIX + V.slug(n))), "used_by": uses.get(n, [])}
                            for n, e in sorted(vault.items())]}


def _deny(request: Request):
    return None if (_owner is not None and _owner(request)) else JSONResponse({"error": "the owner's page"}, status_code=403)


@router.get("/api/vault")
async def vault_get(request: Request):
    return _deny(request) or await asyncio.to_thread(_view)


@router.put("/api/vault/{name}")
async def vault_put(name: str, body: Cred, request: Request):
    """Add or change a credential. A new one needs its value; a change keeps the old value unless a new one is given."""
    if (d := _deny(request)):
        return d
    name = (name or "").strip()                 # one spelling per credential: a stray space is never a second name
    value = "".join((body.value or "").split())  # a terminal wraps what it prints: a pasted line break is no part of it

    def run():
        vault = V.load(ESTATE)
        try:
            e = V.entry(name, body.kind, body.base_url, body.models, body.cap_tokens_day)
            key = V.env_key(name, config.read_env(ESTATE / ".env"), vault)
        except V.Refused as x:
            return JSONResponse({"error": str(x)}, status_code=409 if "share" in str(x) or "already" in str(x) else 400)
        if name not in vault and not value:
            return JSONResponse({"error": "a new credential needs its login token or key"}, status_code=400)
        if value and not V.value_ok(e["kind"], e["base_url"], value):
            return JSONResponse({"error": "that doesn't look like a Claude login token (claude setup-token)" if e["kind"] == "login"
                                 else "that doesn't look like an API key for that endpoint"}, status_code=400)
        if value:
            config.set_env(key, value, ESTATE / ".env")
        V.save(ESTATE, {**vault, name: e})
        return {"ok": True, **_view(), "applies": "at each connected agent's next spawn"}
    try:
        return await asyncio.to_thread(run)
    finally:
        value = ""


@router.delete("/api/vault/{name}")
async def vault_delete(name: str, request: Request):
    if (d := _deny(request)):
        return d
    name = (name or "").strip()

    def run():
        vault = V.load(ESTATE)
        if name not in vault:
            return JSONResponse({"error": "no such credential"}, status_code=404)
        users = V.used_by(_runtime()).get(name)
        if users:
            return JSONResponse({"error": f"{', '.join(users)} still use{'s' if len(users) == 1 else ''} it: connect "
                                 "them to another login first"}, status_code=409)
        config.unset_env(V.PREFIX + V.slug(name), ESTATE / ".env")
        V.save(ESTATE, {k: v for k, v in vault.items() if k != name})
        return {"ok": True, **_view()}
    return await asyncio.to_thread(run)
