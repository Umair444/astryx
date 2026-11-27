"""astryx observatory · FEDERATION (cog-rebuild Phase 4, owner 11-13: "a fed can connect to other fed through introduce
… a lot of this stuff is missing in observatory and it should be there").

The recursion (DESIGN.md): fed (one HTTP installation: its gateway door, :8845) ⊃ cog ⊃ org ⊃ group ⊃ agent. A fed meets
another fed through `introduce` (src/astryx/federation/introduce.py), and the gateway (bridges/gateway.py) keeps who it
met in the org's `peers` table. This module is the observatory's window and the owner's hand on that table:

    GET  /api/federation/identity              this org's federation identity: name, public key + fingerprint, the way
                                               in (public url | relay | none: peers can't reach us), and whether the
                                               local gateway answers AS us right now (a fresh probe, 2 s)
    GET  /api/federation/peers                 every peer: url (or "polls us"), status, reputation, last contact, and
                                               the wire's COUNTS in/out over the last 30 days (pending /
                                               dead outbound). Counts only.
    GET  /api/federation/peers/{org}/messages  ?limit= (≤200): that peer's recent traffic either way, bodies included
    POST /api/federation/introduce             {url}: an http(s) gateway base → introduce.introduce (signed hello, the
                                               signed reply verified, stored as `introduced`); a bare federation name →
                                               introduce.introduce_via_relay. The SAME functions the CLI runs.
    POST /api/federation/peers/{org}/status    {action: trust|untrust|block|unblock}: the deliberate local act the
                                               gateway names ("widen or revoke via the peers table"). Statuses are
                                               schema.sql's: trust introduced→trusted, untrust trusted→introduced,
                                               block *→revoked (the ONE deny state the gateway honours at every door),
                                               unblock revoked→introduced. A transition is one conditional UPDATE
                                               (WHERE status = the from-state), so a race or a stale page is a 409,
                                               never a silent overwrite; each change writes an audit row to seed.

OWNER-ONLY BY OMISSION from main.PUBLIC (the public GET /api/peers stays what it was: org, status, reputation), and
checked again in each handler. Under ASTRYX_DEV_NO_WIRE (a worktree's dev server reading a live org) every POST here is
refused by main.privacy_gate: a click in a screenshot must never widen a live peer.

THE SECRET KEY. The observatory never loads the org's secret key (main._gateway_identity's stance, kept by the owner's
ruling for this phase). introduce must sign our hello with it, so the POST runs introduce.py's flows in a CHILD process
(src/astryx/federation/introduce_run.py, the home's .env named, a timeout) and reads back only its one-line outcome and
exit code: the key lives and dies in that child. This module imports nothing that loads it (the oracle checks).
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from astryx.core.orgname import org_ok

router = APIRouter()

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "src" / "astryx" / "federation" / "introduce_run.py"   # introduce.py's flows, in a child process
INTRO_TIMEOUT = 45                                 # introduce's own calls time out at 20 s each; the relay path makes two
WINDOW_DAYS = 30                                   # the peers listing counts the wire over this window

_get_pool = None
ESTATE: Path | None = None
_owner = lambda request: False                     # noqa: E731 — main.owner_call; unbound = nobody (deny by default)
_env = lambda key: ""                              # noqa: E731 — main._env: env first, then the home's .env
_me = lambda: "local"                              # noqa: E731 — this org's federation name

URL_MAX = 300
NAME_MAX = 120
PEER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")    # a peers.org as the gateway admits one (org_ok's charset)

# action -> (the statuses it moves FROM, the status it writes). block takes any live state; nothing moves a stranger
# to trusted without an introduction (a stranger has no verified key).
TRANSITIONS = {
    "trust":   (("introduced",), "trusted"),
    "untrust": (("trusted",), "introduced"),
    "block":   (("stranger", "introduced", "trusted"), "revoked"),
    "unblock": (("revoked",), "introduced"),
}
LABEL = {"revoked": "blocked"}                     # the UI's word; the row keeps schema.sql's


def bind(get_pool, estate: Path, owner, env, me) -> None:
    global _get_pool, ESTATE, _owner, _env, _me
    _get_pool, ESTATE, _owner, _env, _me = get_pool, estate, owner, env, me


def _deny(request: Request):
    return None if _owner(request) else JSONResponse({"error": "owner only"}, status_code=403)


def _fingerprint(pub: str | None) -> str | None:
    if not pub:
        return None
    return ":".join(pub[i:i + 4] for i in range(0, 16, 4))


def mode_of(url: str, relay: str) -> str:
    """How peers reach this org: its own public door, the relay's mailbox, or not at all (it can still knock)."""
    return "public" if url else "relay" if relay else "none"


async def _probe(port: str, name: str) -> dict:
    """The local gateway, asked now: does it answer, and as whom? In a cog the root may serve the door org, so the
    org's own /o/<name>/ door is asked when the root answers as someone else."""
    base = f"http://127.0.0.1:{port or 8845}"
    out = {"port": int(port) if (port or "").isdigit() else 8845, "reachable": False, "org": None, "pubkey": None}
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            j = (await c.get(f"{base}/astryx/identity")).json()
            if isinstance(j, dict) and j.get("org") != name and name:
                r = await c.get(f"{base}/o/{name}/astryx/identity")
                if r.status_code == 200:
                    j = r.json()
    except Exception:  # noqa: BLE001 — a down gateway is a fact to show, not an error
        return out
    if isinstance(j, dict):
        out.update(reachable=True, org=j.get("org"), pubkey=j.get("pubkey"))
    return out


@router.get("/api/federation/identity")
async def identity(request: Request):
    if (d := _deny(request)):
        return d
    name = _me()
    url, relay = _env("ASTRYX_URL"), _env("ASTRYX_RELAY")
    gw = await _probe(_env("ASTRYX_GATEWAY_PORT"), name)
    pub = gw["pubkey"] if gw["org"] == name else None
    pool = _get_pool()
    n = await pool.fetchrow(PEER_COUNTS_SQL)
    return {"org": name, "pubkey": pub, "fingerprint": _fingerprint(pub), "url": url or None, "relay": relay or None,
            "mode": mode_of(url, relay),
            "gateway": {**gw, "as_us": bool(gw["reachable"] and gw["org"] == name)},
            "peers": {"total": n["total"], "trusted": n["trusted"], "introduced": n["introduced"], "blocked": n["revoked"]}}


PEER_COUNTS_SQL = (
    "SELECT count(*) AS total, count(*) FILTER (WHERE status = 'trusted') AS trusted, "
    "count(*) FILTER (WHERE status = 'introduced') AS introduced, count(*) FILTER (WHERE status = 'revoked') AS revoked "
    "FROM peers")

# one pass over the cross-org wire: each row belongs to its counterpart org (inbound: from_org; outbound: to_org)
PEERS_SQL = """
WITH t AS (
  SELECT CASE WHEN from_org <> 'local' THEN from_org ELSE to_org END AS org,
         from_org <> 'local' AS inbound, ts, status
  FROM messages WHERE (from_org <> 'local' OR to_org <> 'local') AND ts >= now() - make_interval(days => $1))
SELECT p.org, p.url, p.status, p.reputation, p.pubkey, p.last_pickup, p.notes,
       count(t.org) FILTER (WHERE t.inbound)                          AS n_in,
       count(t.org) FILTER (WHERE NOT t.inbound)                      AS n_out,
       count(t.org) FILTER (WHERE NOT t.inbound AND t.status = 'pending') AS out_pending,
       count(t.org) FILTER (WHERE NOT t.inbound AND t.status = 'dead')    AS out_dead,
       max(t.ts) FILTER (WHERE t.inbound)                             AS last_in,
       max(t.ts) FILTER (WHERE NOT t.inbound)                         AS last_out
FROM peers p LEFT JOIN t ON t.org = p.org
GROUP BY p.tenant, p.org ORDER BY (p.status = 'revoked'), max(t.ts) DESC NULLS LAST, p.org"""


def _iso(v):
    return v.isoformat() if v is not None else None


def peer_row(r) -> dict:
    last = max((x for x in (r["last_in"], r["last_out"]) if x is not None), default=None)
    return {"org": r["org"], "url": r["url"], "mode": "direct" if r["url"] else "polls us",
            "status": r["status"], "label": LABEL.get(r["status"], r["status"]), "reputation": r["reputation"],
            "fingerprint": _fingerprint(r["pubkey"]), "keyed": bool(r["pubkey"]), "last_pickup": r["last_pickup"],
            "notes": r["notes"], "last_contact": _iso(last), "last_in": _iso(r["last_in"]), "last_out": _iso(r["last_out"]),
            "traffic": {"in": r["n_in"], "out": r["n_out"], "out_pending": r["out_pending"], "out_dead": r["out_dead"]}}


@router.get("/api/federation/peers")
async def peers(request: Request):
    if (d := _deny(request)):
        return d
    rows = await _get_pool().fetch(PEERS_SQL, WINDOW_DAYS)
    return {"org": _me(), "window_days": WINDOW_DAYS, "peers": [peer_row(r) for r in rows]}


PEER_MSGS_SQL = (
    "SELECT id, ts, from_agent, from_org, to_agent, to_org, thread, intent, status, body FROM messages "
    "WHERE from_org = $1 OR to_org = $1 ORDER BY id DESC LIMIT $2")


@router.get("/api/federation/peers/{org}/messages")
async def peer_messages(org: str, request: Request, limit: int = 50):
    if (d := _deny(request)):
        return d
    if not PEER_RE.match(org):
        return JSONResponse({"error": "not a federation name"}, status_code=400)
    limit = max(1, min(int(limit), 200))
    rows = await _get_pool().fetch(PEER_MSGS_SQL, org, limit)
    return {"org": org, "messages": [
        {"id": r["id"], "ts": _iso(r["ts"]), "from": r["from_agent"], "from_org": r["from_org"], "to": r["to_agent"],
         "to_org": r["to_org"], "thread": r["thread"], "intent": r["intent"], "status": r["status"],
         "inbound": r["from_org"] == org, "body": r["body"]} for r in rows]}


# ------------------------------------------------------------------ the owner's hand
class Introduce(BaseModel):
    url: str


def target_of(raw: str) -> tuple[str, str] | None:
    """('url', base) for an http(s) gateway base, ('relay', name) for a bare federation name, None when it is neither.
    A url carries a host, no credentials, no query or fragment; its path may be a cog's /o/<org> door."""
    s = (raw or "").strip()
    if not s or len(s) > URL_MAX or any(c.isspace() or ord(c) < 32 for c in s):
        return None
    if s.startswith(("http://", "https://")):
        try:
            u = urlsplit(s)
            u.port                                  # noqa: B018 — raises on a malformed port
        except ValueError:
            return None
        if not u.hostname or u.username or u.password or u.query or u.fragment or "@" in u.netloc:
            return None
        if u.path not in ("", "/") and not re.fullmatch(r"/o/[A-Za-z0-9][A-Za-z0-9._-]*/?", u.path):
            return None
        return "url", s.rstrip("/")
    if "://" in s or "/" in s:
        return None
    return ("relay", s) if len(s) <= NAME_MAX and org_ok(s) else None


async def _audit(conn, body: str) -> None:
    """The ONE wire write here (tests/test_owner_surface.py G2 lists it): the owner's federation act, told to seed, the
    agent the gateway already tells about introductions (gateway.py introduce: "widen or revoke via the peers table")."""
    await conn.execute("INSERT INTO messages (from_agent, from_org, to_agent, intent, thread, body) "
                       "VALUES ('owner', 'local', 'seed', 'federation', 'federation', $1)", body)


async def run_introduce(target: str) -> tuple[int, dict]:
    """introduce_run.py as a child (cwd the checkout, the home's .env named): the secret key that signs our hello is
    loaded THERE and dies with it; this process reads one JSON line of outcome and the exit code, nothing else."""
    try:
        p = await asyncio.create_subprocess_exec(
            sys.executable, str(RUNNER), "--env", str(ESTATE / ".env"), "--", target, cwd=str(REPO),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    except OSError as e:
        return -1, {"ok": False, "error": f"could not start the introduction ({type(e).__name__})"}
    try:
        out, _ = await asyncio.wait_for(p.communicate(), INTRO_TIMEOUT)
    except asyncio.TimeoutError:
        p.kill()
        await p.wait()
        return -1, {"ok": False, "error": f"the introduction took longer than {INTRO_TIMEOUT} s: stopped"}
    lines = out.decode(errors="replace").strip().splitlines()
    try:
        j = json.loads(lines[-1]) if lines else {}
    except ValueError:
        j = {}
    if not isinstance(j, dict) or (p.returncode == 0) != bool(j.get("ok")):
        return p.returncode, {"ok": False, "error": f"introduction failed (rc {p.returncode})"}
    return p.returncode, j


@router.post("/api/federation/introduce")
async def introduce(m: Introduce, request: Request):
    if (d := _deny(request)):
        return d
    t = target_of(m.url)
    if t is None:
        return JSONResponse({"error": "give a gateway url (http(s)://host[:port][/o/<org>]) or a federation name "
                                      "listed on the relay"}, status_code=400)
    kind, target = t
    rc, them = await run_introduce(target)
    if not them.get("ok"):
        return JSONResponse({"ok": False, "error": str(them.get("error") or f"introduction failed (rc {rc})")[:300]},
                            status_code=502)
    org = them.get("org") or target
    await _audit(
        _get_pool(), f"the owner introduced this org to '{org}' from the observatory "
                   f"({'direct, ' + target if kind == 'url' else 'through the relay'}). It is `introduced`: it may write "
                   f"to seed, rate-capped. Widening is a separate act (Federation pane: trust).")
    return {"ok": True, "via": kind, "org": org, "url": them.get("url"),
            "fingerprint": _fingerprint(them.get("pubkey")),
            "pending": kind == "relay" and not them.get("url")}


class StatusChange(BaseModel):
    action: str


@router.post("/api/federation/peers/{org}/status")
async def set_status(org: str, m: StatusChange, request: Request):
    if (d := _deny(request)):
        return d
    if not PEER_RE.match(org):
        return JSONResponse({"error": "not a federation name"}, status_code=400)
    if m.action not in TRANSITIONS:
        return JSONResponse({"error": f"action is one of {', '.join(TRANSITIONS)}"}, status_code=400)
    froms, to = TRANSITIONS[m.action]
    pool = _get_pool()
    async with pool.acquire() as c:
        async with c.transaction():
            prev = await c.fetchrow("SELECT status, pubkey FROM peers WHERE org = $1 FOR UPDATE", org)
            if prev is None:
                return JSONResponse({"error": f"'{org}' is not a peer"}, status_code=404)
            if to in ("trusted", "introduced") and not prev["pubkey"]:
                return JSONResponse({"error": f"'{org}' has no verified key: introduce it first"}, status_code=409)
            row = await c.fetchrow(
                "UPDATE peers SET status = $2 WHERE org = $1 AND status = ANY($3::text[]) RETURNING status",
                org, to, list(froms))
            if row is None:
                return JSONResponse({"error": f"cannot {m.action} '{org}': it is {LABEL.get(prev['status'], prev['status'])}",
                                     "status": prev["status"]}, status_code=409)
            await _audit(c, f"the owner moved peer '{org}' {prev['status']} → {to} ({m.action}) from the "
                                       f"observatory's Federation pane.")
    return {"ok": True, "org": org, "from": prev["status"], "status": to, "label": LABEL.get(to, to)}
