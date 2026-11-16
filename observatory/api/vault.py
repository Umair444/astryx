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


# ── sign in from the tab (medic 12364 R3) ─────────────────────────────────────────────────────────────────────────────
# `claude setup-token` runs in the observatory's OWN pseudo-terminal, never an agent's pane, in a THROWAWAY home and
# config dir (0700, removed after), with a minimal environment: whatever it writes on the way never lands on the host's
# ~/.claude that every agent's session uses. One at a time, killed (its whole process group) after SIGNIN_MAX_S. The
# browser gets the sign-in URL; the code it posts back is shape-checked and typed; the token is matched by its exact
# shape from the output, kept only in memory until the one .env write, and never returned. Nothing of the terminal's
# text is logged, returned or stored: the answers are {url} and then {ok, name}.
import os as _os  # noqa: E402
import re as _re  # noqa: E402
import shutil as _shutil  # noqa: E402
import signal as _signal  # noqa: E402
import tempfile as _tempfile  # noqa: E402
import time as _time  # noqa: E402

SIGNIN_MAX_S = 600
_SIGNIN: dict = {}                  # the one sign-in in flight: {name, proc, fd, home, started}
_URL = _re.compile(r"https://claude\.com/cai/oauth/authorize\?[^\s\x1b\x07\\]+")
_CODE = _re.compile(r"[A-Za-z0-9#._~=-]{8,400}")
_ANSI = _re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]")


def _signin_end() -> None:
    s = _SIGNIN.pop("now", None)
    if not s:
        return
    try:
        _os.killpg(s["proc"].pid, _signal.SIGKILL)
    except OSError:
        pass
    try:
        _os.close(s["fd"])
    except OSError:
        pass
    _shutil.rmtree(s["home"], ignore_errors=True)


def _read_until(fd: int, pattern, seconds: float) -> str | None:
    """The first match of `pattern` in the terminal's output within `seconds` (the text itself is never kept)."""
    import select
    buf, end = "", _time.time() + seconds
    while _time.time() < end:
        r, _w, _x = select.select([fd], [], [], 0.5)
        if not r:
            continue
        try:
            chunk = _os.read(fd, 65536).decode(errors="replace")
        except OSError:
            break
        if not chunk:
            break
        buf = (buf + chunk)[-200_000:]
        m = pattern.search(buf) or pattern.search("".join(_ANSI.sub("", buf).split()))
        if m:
            return m.group(0)
    return None


def _signin_start(name: str) -> dict:
    import fcntl
    import pty
    import struct
    import subprocess
    import termios
    _signin_end()                                   # one at a time: a new start ends the old one
    cli = _shutil.which("claude")
    if not cli:
        return {"error": "Claude Code isn't installed on this machine"}
    home = _tempfile.mkdtemp(prefix="astryx-signin-")
    _os.chmod(home, 0o700)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 1000, 0, 0))   # wide: no URL or token wraps
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin:" + _os.path.dirname(cli), "HOME": home,
           "CLAUDE_CONFIG_DIR": _os.path.join(home, "cfg"), "TERM": "xterm-256color", "BROWSER": "/bin/false"}
    proc = subprocess.Popen([cli, "setup-token"], stdin=slave, stdout=slave, stderr=slave, cwd=home, env=env,
                            start_new_session=True, close_fds=True)
    _os.close(slave)
    _SIGNIN["now"] = {"name": name, "proc": proc, "fd": master, "home": home, "started": _time.time()}
    import threading
    mine = _SIGNIN["now"]
    t = threading.Timer(SIGNIN_MAX_S, lambda: _SIGNIN.get("now") is mine and _signin_end())   # abandoned: ended, not left
    t.daemon = True
    t.start()
    url = _read_until(master, _URL, 30)
    if not url:
        _signin_end()
        return {"error": "Claude Code didn't offer a sign-in link: try again in a minute"}
    return {"url": url}


class Code(BaseModel):
    code: str


@router.post("/api/vault/{name}/signin")
async def vault_signin_start(name: str, request: Request):
    """Start signing a Claude login in: the answer is the sign-in URL to open."""
    if (d := _deny(request)):
        return d
    name = (name or "").strip()
    try:
        V.slug(name)
        V.env_key(name, config.read_env(ESTATE / ".env"), V.load(ESTATE))
    except V.Refused as x:
        return JSONResponse({"error": str(x)}, status_code=409)
    out = await asyncio.to_thread(_signin_start, name)
    return JSONResponse(out, status_code=503) if "error" in out else out


@router.post("/api/vault/{name}/signin/code")
async def vault_signin_code(name: str, body: Code, request: Request):
    """The code the sign-in page showed: typed into the waiting setup-token; the login it prints goes into the vault."""
    if (d := _deny(request)):
        return d
    name = (name or "").strip()
    s = _SIGNIN.get("now")
    if not s or s["name"] != name or _time.time() - s["started"] > SIGNIN_MAX_S:
        _signin_end()
        return JSONResponse({"error": "That sign-in has ended: start it again"}, status_code=409)
    code = (body.code or "").strip()
    if not _CODE.fullmatch(code) or not code.isprintable():
        return JSONResponse({"error": "Paste the code exactly as the sign-in page shows it"}, status_code=400)

    def run():
        try:
            _os.write(s["fd"], code.encode() + b"\r")
            token = _read_until(s["fd"], V.SHAPE["login"], 60)
            if not token:
                return JSONResponse({"error": "Claude didn't accept that code: start the sign-in again"}, status_code=400)
            vault = V.load(ESTATE)
            key = V.env_key(name, config.read_env(ESTATE / ".env"), vault)
            config.set_env(key, token, ESTATE / ".env")
            V.save(ESTATE, {**vault, name: vault.get(name) or V.entry(name, "login")})
            return {"ok": True, "name": name, **_view(), "applies": "at each connected agent's next spawn"}
        finally:
            _signin_end()
    return await asyncio.to_thread(run)


@router.delete("/api/vault/signin")
async def vault_signin_cancel(request: Request):
    if (d := _deny(request)):
        return d
    await asyncio.to_thread(_signin_end)
    return {"ok": True}
