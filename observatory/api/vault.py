"""astryx observatory · HARNESS AND KEYS: what the org's agents run on, and which agent runs on what (owner 11-16;
docs/superpowers/specs/2026-11-16-harness-and-keys-design.md). Owner-only, every route, positively.

    GET    /api/harness               the whole page: harnesses, the provider catalog, the keys, the org's own login,
                                      every agent's connection
    PUT    /api/keys/{name}           add or change a key; `value` (optional on a change) is written to .env, never returned
    DELETE /api/keys/{name}           remove one (refused while an agent runs on it)
    POST   /api/keys/{name}/signin    sign a login in through its harness: the answer is the link to open
    POST   /api/keys/{name}/signin/code   the code that page shows; the login it yields is proved, then stored
    PUT    /api/connections/{agent}   an agent's harness, key and model ('*': everyone else); an empty one = the default

A value goes to .env under the key the server derives from the name (vault.env_key), through the one locked writer
(config.set_env), and is never echoed, logged or stored anywhere else. What fits what is the catalog's
(astryx.core.catalog), never decided here. An API key is metered spend: connecting an agent to one is the owner's
confirmed act (confirm_billing), and its daily cap holds: runtime_env.key_cap at spawn, energy (its day) at the pulse.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from astryx import config  # noqa: E402
from observatory.api import hostfile  # noqa: E402
from astryx.core import catalog as C  # noqa: E402
from astryx.core import runtime_env as RE  # noqa: E402
from astryx.core import vault as V  # noqa: E402
from astryx.econ import energy as E  # noqa: E402

router = APIRouter()
_owner = _pool = _roster = _alive = None
ESTATE: Path | None = None
APPLIES = "at each connected agent's next start"


def bind(owner, estate, pool=None, roster=None, alive=None) -> None:
    global _owner, ESTATE, _pool, _roster, _alive
    _owner, ESTATE, _pool, _roster, _alive = owner, Path(estate), pool, roster, alive


def _deny(request: Request):
    return None if (_owner is not None and _owner(request)) else JSONResponse({"error": "the owner's page"}, status_code=403)


def _err(msg: str, status: int = 400):
    return JSONResponse({"error": msg}, status_code=status)


def _runtime() -> dict:
    try:
        d = json.loads((ESTATE / "runtime.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_runtime(d: dict) -> None:
    hostfile.atomic_write(ESTATE / "runtime.json", json.dumps(d, indent=2, sort_keys=True) + "\n")   # the one writer


# ── what a key can do ────────────────────────────────────────────────────────────────────────────────────────────────
def _usable(e: dict, harness: dict, has_value: bool, cat: dict) -> str | None:
    """Why an agent on `harness` can't run on this key now, or None: it can."""
    if not harness.get("launcher"):
        return f"{harness['name']} isn't ready to run agents yet"
    if not C.fits(harness, e["provider"], e, cat):
        return f"{harness['name']} can't use {cat[e['provider']]['name']}"
    if not has_value:
        return "it has no value yet"
    if cat[e["provider"]]["billing"] == "metered" and not e.get("cap_tokens_day"):
        return "an API key needs a daily cap before an agent runs on it"
    return None


def _harnesses(cat: dict) -> list[dict]:
    return [{"id": h, "name": r.get("name", h), "by": r.get("by", ""), "ready": r.get("launcher") is True,
             "why": r.get("why"), "speaks": r.get("speaks", []), "logins": r.get("logins", []),
             "signin": (r.get("signin") or {}).get("provider")} for h, r in C.harnesses().items()]


async def _energy(names: list) -> dict:
    """{name | None: the newest fresh reading of that login's limits}: the org's own is None."""
    if _pool is None or _pool() is None:
        return {}
    rows = await _pool().fetch(
        "SELECT DISTINCT ON (credential) credential, five_hour_pct, five_hour_reset, seven_day_pct, seven_day_reset, "
        "extract(epoch FROM now() - fetched_at)::float AS age FROM usage_readings WHERE state = 'fresh' "
        "AND (credential IS NULL OR credential = ANY($1::text[])) ORDER BY credential, fetched_at DESC", names)
    num = lambda v: None if v is None else float(v)   # noqa: E731
    return {r["credential"]: {"h5": num(r["five_hour_pct"]), "h5_reset": r["five_hour_reset"], "d7": num(r["seven_day_pct"]),
                              "d7_reset": r["seven_day_reset"], "age_s": r["age"]} for r in rows}


async def _spent(names: list) -> dict:
    """{key: billable tokens its agents ran on it today} (energy.spent's sum, for every key in one read)."""
    if not names or _pool is None or _pool() is None:
        return {}
    rows = await _pool().fetch(f"SELECT run_on, coalesce(sum({E.BILL}), 0)::float AS t FROM turns "
                               "WHERE run_on = ANY($1::text[]) AND started_at >= $2 GROUP BY run_on",
                               names, E.midnight(datetime.now(timezone.utc)))
    return {r["run_on"]: r["t"] for r in rows}


async def _view() -> dict:
    def read():
        env, vault, rt = config.read_env(ESTATE / ".env"), V.load(ESTATE), _runtime()
        return env, vault, rt, C.providers(), C.harnesses(), RE.org_login(env)
    env, vault, rt, cat, rows, org = await asyncio.to_thread(read)
    uses = V.used_by(rt)
    energy = await _energy([n for n, e in vault.items() if e["kind"] == "login"])
    spend = await _spent([n for n, e in vault.items() if e["kind"] == "key"])
    keys = []
    for n, e in sorted(vault.items()):
        has = bool(env.get(V.PREFIX + V.slug(n)))
        keys.append({"name": n, **e, "has_value": has, "used_by": uses.get(n, []),
                     "fits": [h for h, r in rows.items() if C.fits(r, e["provider"], e, cat)],
                     "why_not": {h: _usable(e, r, has, cat) for h, r in rows.items() if C.fits(r, e["provider"], e, cat)},
                     "energy": energy.get(n) if e["kind"] == "login" else None,
                     "spent_today": spend.get(n, 0.0) if e["kind"] == "key" else None})
    roster = sorted(_roster()) if _roster else []
    alive = _alive() if _alive else set()
    return {"harnesses": _harnesses(cat), "providers": cat, "keys": keys,
            "org": {"billing": org["billing"], "harness": org["cli"], "energy": energy.get(None)},
            "default": {k: v for k, v in (rt.get("*") or {}).items() if k in ("harness", "credential", "model", "effort")},
            "agents": [{"name": a, "own": a in rt, "alive": a in alive,
                        "connection": {k: v for k, v in V.connection(rt, a).items()
                                       if k in ("harness", "credential", "model", "effort")}} for a in roster]}


@router.get("/api/harness")
async def harness_get(request: Request):
    return _deny(request) or await _view()


# ── keys ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
class Key(BaseModel):
    provider: str
    base_url: str = ""
    format: str = ""
    models: dict | None = None
    cap_tokens_day: int | None = None
    value: str = ""


@router.put("/api/keys/{name}")
async def key_put(name: str, body: Key, request: Request):
    """Add or change a key. A new one needs its value (a login can be signed in instead); a change keeps the old value
    unless a new one is given. An API key the provider can check is checked first: a rejected one is never stored."""
    if (d := _deny(request)):
        return d
    name = (name or "").strip()                 # one spelling per key: a stray space is never a second name
    value = "".join((body.value or "").split())  # a terminal wraps what it prints: a pasted line break is no part of it

    def run():
        vault = V.load(ESTATE)
        try:
            e = V.entry(name, body.provider, body.base_url, body.format, body.models, body.cap_tokens_day)
            key = V.env_key(name, config.read_env(ESTATE / ".env"), vault)
        except V.Refused as x:
            return _err(str(x), 409 if "share" in str(x) or "already" in str(x) else 400)
        if name in vault and vault[name]["provider"] != e["provider"]:
            return _err(f"'{name}' is a {C.providers()[vault[name]['provider']]['name']} key: name the new one differently")
        if name not in vault and not value:
            return _err("paste its key" if e["kind"] == "key" else "sign it in, or paste its token")
        if value and not V.value_ok(e, value):
            return _err(f"that doesn't look like a {C.providers()[e['provider']]['name']} "
                        f"{'token' if e['kind'] == 'login' else 'key'}")
        if value and e["kind"] == "key" and C.check(e["provider"], value) == "rejected":
            return _err(f"{C.providers()[e['provider']]['name']} rejected that key")
        if value:
            config.set_env(key, value, ESTATE / ".env")
        V.save(ESTATE, {**vault, name: e})
        return None
    try:
        out = await asyncio.to_thread(run)
    finally:
        value = ""
    return out or {"ok": True, "applies": APPLIES, **(await _view())}


@router.delete("/api/keys/{name}")
async def key_delete(name: str, request: Request):
    if (d := _deny(request)):
        return d
    name = (name or "").strip()

    def run():
        vault = V.load(ESTATE)
        if name not in vault:
            return _err("no such key", 404)
        users = V.used_by(_runtime()).get(name)
        if users:
            who = ", ".join("everyone else" if u == "*" else u for u in users)
            return _err(f"{who} still run{'s' if len(users) == 1 and users != ['*'] else ''} on it: connect them to "
                        "another key first", 409)
        config.unset_env(V.PREFIX + V.slug(name), ESTATE / ".env")
        V.save(ESTATE, {k: v for k, v in vault.items() if k != name})
        return None
    return await asyncio.to_thread(run) or {"ok": True, **(await _view())}


# ── connections ──────────────────────────────────────────────────────────────────────────────────────────────────────
class Connection(BaseModel):
    harness: str = ""
    credential: str = ""
    model: str = ""
    effort: str = ""
    confirm_billing: bool = False      # putting an agent on an API key is the owner's signed spend (local.md Economy)


EFFORTS = ("", "low", "medium", "high", "xhigh", "max")


@router.put("/api/connections/{agent}")
async def connection_put(agent: str, body: Connection, request: Request):
    """`agent` ('*': everyone else) runs on this harness, key and model from its next start. An empty connection
    removes the agent's own (it runs as everyone else; for '*', on the org's login)."""
    if (d := _deny(request)):
        return d
    if agent != "*" and agent not in (_roster() if _roster else set()):
        return _err("no such agent", 404)
    c = {k: v.strip() for k, v in body.model_dump().items() if isinstance(v, str) and v.strip()}

    def run():
        rows, cat, vault = C.harnesses(), C.providers(), V.load(ESTATE)
        h = c.get("harness") or "claude"
        if h not in rows:
            return _err("no such harness")
        if c.get("credential"):
            e = vault.get(c["credential"])
            if e is None:
                return _err("no such key")
            has = bool(config.read_env(ESTATE / ".env").get(V.PREFIX + V.slug(c["credential"])))
            if (why := _usable(e, rows[h], has, cat)):
                return _err(f"{c['credential']}: {why}", 409)
            if e["kind"] == "key" and not body.confirm_billing \
                    and V.connection(_runtime(), agent).get("credential") != c["credential"]:
                return JSONResponse({"error": f"{c['credential']} is billed per token, up to "
                                     f"{e['cap_tokens_day']:,} tokens a day", "needs_billing": True}, status_code=409)
        elif not rows[h].get("launcher"):
            return _err(f"{rows[h].get('name', h)} isn't ready to run agents yet", 409)
        if c.get("model") and not C.MODEL.fullmatch(c["model"]):
            return _err("a model name is letters, digits and . _ : / @ -")
        if c.get("effort", "") not in EFFORTS:
            return _err(f"effort is one of {', '.join(e for e in EFFORTS if e)}")
        rt = _runtime()
        if c:
            rt[agent] = c
        else:
            rt.pop(agent, None)
        _write_runtime(rt)
        return None
    out = await asyncio.to_thread(run)
    if out:
        return out
    if _pool is not None and _pool() is not None:           # who connected what: one row on the agent's own log
        who = "seed" if agent == "*" else agent
        what = " · ".join(c[k] for k in ("harness", "credential", "model") if c.get(k)) or "the org's login"
        await _pool().execute("INSERT INTO steps (agent, kind, content) VALUES ($1, 'runtime', $2)", who,
                              f"owner connected {'everyone else' if agent == '*' else 'it'} to {what}")
    return {"ok": True, "applies": APPLIES, **(await _view())}


# ── sign in from the tab (medic 12364 R3) ─────────────────────────────────────────────────────────────────────────────
# `claude setup-token` runs in the observatory's OWN pseudo-terminal, never an agent's pane, in a THROWAWAY home and
# config dir (0700, removed after), with a minimal environment: whatever it writes on the way never lands on the host's
# ~/.claude that every agent's session uses. One at a time, killed (its whole process group) after SIGNIN_MAX_S. The
# browser gets the sign-in URL; the code it posts back is shape-checked and typed; the token is matched by its exact
# shape from the output, kept only in memory until the one .env write, and never returned. Nothing of the terminal's
# text is logged, returned or stored: the answers are {url} and then {ok, name}. The sign-in in flight lives in THIS
# process: with several workers, a code landing in another one is refused (409, "start it again"), never mixed up.
import re as _re  # noqa: E402
import shutil as _shutil  # noqa: E402
import signal as _signal  # noqa: E402
import time as _time  # noqa: E402

SIGNIN_MAX_S = 600
_SIGNIN: dict = {}                  # the one sign-in in flight: {name, proc, fd, home, started}
_CODE = _re.compile(r"[A-Za-z0-9#._~=-]{8,400}")
_ANSI = _re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]")


def _signin_end() -> None:
    s = _SIGNIN.pop("now", None)
    if not s:
        return
    try:
        os.killpg(s["proc"].pid, _signal.SIGKILL)
    except OSError:
        pass
    try:
        os.close(s["fd"])
    except OSError:
        pass
    _shutil.rmtree(s["home"], ignore_errors=True)


def _read_until(fd: int, pattern, seconds: float, raw: bool = False) -> str | None:
    """The first COMPLETE match of `pattern` in the terminal's output within `seconds`: in the ANSI-stripped text, a
    match counts only once something ends it (whitespace, BEL, ESC, CR), or once the stream has been quiet for half a
    second with the match at its very end. Claude's sign-in is a redrawing TUI: a token can arrive across reads, and a
    first-20-characters match would store a prefix (medic 12472). `raw`: search the output as it came (the sign-in
    LINK is a terminal hyperlink, OSC 8, whose target the stripped text loses; its own terminator, ESC or BEL, ends it).
    Never raw for a token: a style code inside it would end a prefix. The text is dropped on return."""
    import select
    done = _re.compile(r"(?:" + pattern.pattern + r")(?=[\s\x07\x1b\r])")
    tail = _re.compile(r"(?:" + pattern.pattern + r")$")
    buf, end, quiet_since = "", _time.time() + seconds, _time.time()
    try:
        while _time.time() < end:
            r, _w, _x = select.select([fd], [], [], 0.1)
            if r:
                try:
                    chunk = os.read(fd, 65536).decode(errors="replace")
                except OSError:
                    break
                if not chunk:
                    break
                buf, quiet_since = (buf + chunk)[-200_000:], _time.time()
            text = buf if raw else _ANSI.sub(" ", buf)
            m = done.search(text)
            if m:
                return m.group(0)
            m = tail.search(text.rstrip("\x00"))
            if m and _time.time() - quiet_since >= 0.5:
                return m.group(0)
        return None
    finally:
        buf = ""


def _proves(home: str, token: str, harness: dict) -> bool:
    """One minimal authenticated call with the new login, inside the same throwaway home: a sign-in that the harness
    doesn't actually accept is never stored (medic 12472). The call and the env var the token goes in are the harness
    row's (signin.prove, connect.login)."""
    import subprocess
    si = harness["signin"]
    cli = _shutil.which(harness.get("binary") or "")
    if not cli:
        return False
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin:" + os.path.dirname(cli), "HOME": home, "TERM": "dumb",
           si["config_dir"]: os.path.join(home, "proof"), harness["connect"]["login"][si["provider"]]: token}
    try:
        r = subprocess.run([cli, *si["prove"]], cwd=home, env=env,
                           capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
        return r.returncode == 0 and bool(r.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def _signin_start(name: str, harness: dict) -> dict:
    import fcntl
    import pty
    import struct
    import subprocess
    import termios
    _signin_end()                                   # one at a time: a new start ends the old one
    si = harness["signin"]
    cli = _shutil.which(harness.get("binary") or "")
    if not cli:
        return {"error": f"{harness['name']} isn't installed on this machine"}
    home = tempfile.mkdtemp(prefix="astryx-signin-")
    os.chmod(home, 0o700)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 1000, 0, 0))   # wide: no URL or token wraps
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin:" + os.path.dirname(cli), "HOME": home,
           si["config_dir"]: os.path.join(home, "cfg"), "TERM": "xterm-256color", "BROWSER": "/bin/false"}
    proc = subprocess.Popen([cli, *si["args"]], stdin=slave, stdout=slave, stderr=slave, cwd=home, env=env,
                            start_new_session=True, close_fds=True)
    os.close(slave)
    _SIGNIN["now"] = {"name": name, "proc": proc, "fd": master, "home": home, "started": _time.time(), "harness": harness}
    import threading
    mine = _SIGNIN["now"]
    t = threading.Timer(SIGNIN_MAX_S, lambda: _SIGNIN.get("now") is mine and _signin_end())   # abandoned: ended, not left
    t.daemon = True
    t.start()
    url = _read_until(master, _re.compile(si["link"] + r"[^\s\x1b\x07\\]+"), 30, raw=True)
    if not url:
        _signin_end()
        return {"error": f"{harness['name']} didn't offer a sign-in link: try again in a minute"}
    return {"url": url}


class Code(BaseModel):
    code: str


def _signer(provider: str) -> dict | None:
    """The harness that signs `provider`'s logins in (its adapter row's `signin`), or None."""
    return next((r for r in C.harnesses().values() if (r.get("signin") or {}).get("provider") == provider), None)


@router.post("/api/keys/{name}/signin")
async def key_signin_start(name: str, request: Request, provider: str = "claude"):
    """Start signing a login in through its harness: the answer is the sign-in URL to open."""
    if (d := _deny(request)):
        return d
    name = (name or "").strip()
    harness = _signer(provider)
    if harness is None:
        return _err("signing in to that from here isn't built yet")
    try:
        V.slug(name)
        V.env_key(name, config.read_env(ESTATE / ".env"), V.load(ESTATE))
    except V.Refused as x:
        return _err(str(x), 409)
    out = await asyncio.to_thread(_signin_start, name, harness)
    return JSONResponse(out, status_code=503) if "error" in out else out


@router.post("/api/keys/{name}/signin/code")
async def key_signin_code(name: str, body: Code, request: Request):
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
            os.write(s["fd"], code.encode() + b"\r")
            h = s["harness"]
            pid = h["signin"]["provider"]
            shape = _re.compile(C.providers()[pid]["shape"])
            token = _read_until(s["fd"], shape, 60)
            if not token or not shape.fullmatch(token):
                return _err(f"{h['name']} didn't accept that code: start the sign-in again")
            if not _proves(s["home"], token, h):
                return _err(f"{h['name']} didn't accept that sign-in: start it again")
            vault = V.load(ESTATE)
            key = V.env_key(name, config.read_env(ESTATE / ".env"), vault)
            config.set_env(key, token, ESTATE / ".env")
            V.save(ESTATE, {**vault, name: vault.get(name) or V.entry(name, pid)})
            return None
        finally:
            _signin_end()
    return await asyncio.to_thread(run) or {"ok": True, "name": name, "applies": APPLIES, **(await _view())}


