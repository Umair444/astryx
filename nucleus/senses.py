#!/usr/bin/env python3
"""ASTRYX · senses — the afferent nervous system (owner design, 2026-08-21).

The org has TWO nervous systems, and they are twins:

    triggers/<agent>/*.py   EFFERENT — the pulse evaluates them on the org clock; the org
                            ACTS (a trigger that returns a body wakes its agent).
    sensors/<agent>/*.py    AFFERENT — this server serves them as API endpoints; the world
                            CALLS IN and the org PERCEIVES.

A sense runs at CODE SPEED, without waking its resident. That is the scale answer for
app-facing traffic: a thousand requests/sec hit a sense (plain python — a langchain call,
a lookup, a transform) and get answers, and no Claude session is forked or woken. The
resident OWNS its senses (its folder, its code, editable via the repo) and decides what
deserves ATTENTION: like heat that is felt but not at focus until it burns, a sense stays
silent until its own code decides a threshold has crossed and calls focus() — which puts
one row on the wire to its resident. Perception is free; attention costs a wake.

DISCOVERY = the trigger law: writing sensors/<agent>/<name>.py IS deploying. No registry,
no restart — the file is resolved per request and hot-reloaded on mtime change.

CONTRACT for a sense module:
    def sense(params: dict, payload) -> dict | str | (int, dict)
        params  — query params (GET) merged over the JSON body (POST)
        payload — the raw body bytes (b'' for GET)
        return  — a dict/str (200), or (status, dict) to set the code
    METHODS = ["GET", "POST"]      # optional; default both
    docstring first line           # the description shown in the observatory Tools panel
Helper available to every sense:
    from nucleus.senses import focus
    focus("<agent>", "body text")  # escalate onto the wire — one messages row, delivered
                                   # by the agent's own channel like any other message

Runs as astryx-senses.service (FastAPI + systemd, the stack's one shape) on :8460.
Exposure is the host's call: ufw gates the port; open it to the LAN/world when an app
needs the sense. Errors in a sense return 500 with a short reason and never kill the
server — a broken sense is a numb patch, not a dead nervous system.
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
SENSORS = REPO / "sensors"
PORT = 8460

from fastapi import FastAPI, Request, Response  # noqa: E402

app = FastAPI(title="astryx senses", docs_url=None, redoc_url=None)

# module cache keyed on path, invalidated on mtime — hot-reload, the trigger discipline
_cache: dict[str, tuple[float, object]] = {}


def _safe(part: str) -> str | None:
    s = "".join(c for c in part if c.isalnum() or c in "-_").lower()
    return s or None


def _load(path: Path):
    mtime = path.stat().st_mtime
    hit = _cache.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    spec = importlib.util.spec_from_file_location(f"sense_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _cache[str(path)] = (mtime, mod)
    return mod


def senses_index() -> list[dict]:
    """Every sense in the tree — the same derive-at-use law as the trigger/charter roster.
    Also imported by the observatory for the Tools panel; reads files only, cheap."""
    out = []
    for p in sorted(SENSORS.glob("*/*.py")):
        if p.name.startswith("_") or ".example" in p.parts[-2]:
            continue
        desc = ""
        try:
            head = p.read_text(errors="replace")[:2000]
            if '"""' in head:
                desc = head.split('"""')[1].strip().splitlines()[0]
        except OSError:
            pass
        out.append({"agent": p.parent.name, "name": p.stem,
                    "path": f"/{p.parent.name}/{p.stem}", "description": desc})
    return out


def _dsn() -> str | None:
    try:
        return next(line.split("=", 1)[1].strip()
                    for line in (REPO / ".env").read_text().splitlines()
                    if line.startswith("ASTRYX_DSN="))
    except Exception:
        return None


def _log_call(agent: str, name: str, ms: int, status: int) -> None:
    """One steps row per sense call — the demand/pricing signal for the economy. The
    steps NOTIFY fires like any other row; subscribers filtering 'sense' can watch."""
    try:
        import psycopg
        dsn = _dsn()
        if not dsn:
            return
        with psycopg.connect(dsn, connect_timeout=2) as conn:
            conn.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'sense',%s)",
                         (agent, f"{agent}/{name} {ms}ms http={status}"))
    except Exception:
        pass


def focus(agent: str, body: str, thread: str = "", intent: str = "sense") -> int | None:
    """A sense escalating to ATTENTION: one row on the wire to its resident. The messages
    INSERT trigger notifies the agent's channel, which delivers it like any message —
    no side channel, the table is the truth. Returns the message id, or None on failure
    (a sense must keep answering its caller even when the wire is down)."""
    try:
        import psycopg
        dsn = _dsn()
        if not dsn:
            return None
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            row = conn.execute(
                "INSERT INTO messages (from_agent, to_agent, thread, intent, body) "
                "VALUES ('senses', %s, %s, %s, %s) RETURNING id",
                (agent, thread or None, intent, body[:4000])).fetchone()
            return row[0] if row else None
    except Exception:
        return None


@app.get("/")
async def index():
    return {"senses": senses_index()}


@app.api_route("/{agent}/{name}", methods=["GET", "POST"])
async def dispatch(agent: str, name: str, request: Request):
    a, n = _safe(agent), _safe(name)
    if not a or not n:
        return Response(json.dumps({"error": "bad path"}), 404,
                        media_type="application/json")
    path = SENSORS / a / f"{n}.py"
    if not path.is_file():
        return Response(json.dumps({"error": f"no sense {a}/{n}"}), 404,
                        media_type="application/json")
    try:
        mod = _load(path)
        fn = getattr(mod, "sense", None)
        if not callable(fn):
            return Response(json.dumps({"error": "sense() missing"}), 500,
                            media_type="application/json")
        methods = [m.upper() for m in getattr(mod, "METHODS", ["GET", "POST"])]
        if request.method not in methods:
            return Response(json.dumps({"error": f"{request.method} not allowed"}), 405,
                            media_type="application/json")
        raw = await request.body()
        params = dict(request.query_params)
        if raw:
            try:
                j = json.loads(raw)
                if isinstance(j, dict):
                    params = {**j, **params}
            except Exception:
                pass
        t0 = time.monotonic()
        result = fn(params, raw)
        status = 200
        if isinstance(result, tuple) and len(result) == 2:
            status, result = result
        # ECONOMY: every sense call is an org event and gets PRICED (a sense answer is the
        # cheapest request in the economy — the 1h→1min→~0 move — and its adoption is the
        # demand signal). One steps row, kind='sense'; fail-silent: pricing must never
        # cost the caller its answer.
        _log_call(a, n, round((time.monotonic() - t0) * 1000), status)
        if isinstance(result, str):
            return Response(result, status, media_type="text/plain")
        return Response(json.dumps(result, default=str), status,
                        media_type="application/json",
                        headers={"x-sense-ms": str(round((time.monotonic() - t0) * 1000))})
    except Exception as exc:
        # a broken sense is a numb patch, never a dead server — and never a traceback
        # to an external caller
        return Response(json.dumps({"error": f"{type(exc).__name__}: {exc}"[:200]}), 500,
                        media_type="application/json")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
