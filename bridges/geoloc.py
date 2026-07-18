#!/usr/bin/env python3
"""astryx · geoloc bridge — FastAPI location intake on :8766 (forwarded, internet-exposed).

Receives Android/Tasker "Get Location v2" (%gl_*) JSON pushes and writes them to the
PostGIS geo.track.locations table. The port is public, so every write requires the shared
secret in GEOLOC_TOKEN (query ?token=, X-Token header, Bearer, or a "token" body field).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from contextlib import asynccontextmanager
from typing import Any, Optional

import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

TOKEN = os.environ.get("GEOLOC_TOKEN", "")
DSN = os.environ.get("GEOLOC_DSN", "")
if not TOKEN or not DSN:
    raise SystemExit("refusing to start: GEOLOC_TOKEN and GEOLOC_DSN must be set")

pool: Optional[asyncpg.Pool] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=4)
    yield
    await pool.close()


app = FastAPI(title="astryx geoloc", lifespan=lifespan)

# THE OBSERVER moved to services/observer (own service, :8767) 2026-07-12 —
# stationed agents are not plumbing for other services. This service is location-only.
# Self-contained module; wildcard CORS + rate limits are scoped inside it.


# ── helpers ──────────────────────────────────────────────────────────────────
def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


def lenient_json(body: str) -> dict:
    """Parse JSON, tolerating Tasker's unresolved %variables.

    Tasker substitutes bare (unquoted) numbers, but an *unavailable* variable is left as a
    literal like %gl_bearing — which is invalid JSON. Replace any remaining %token, and any
    now-empty value (`: ,` / `: }`), with null before parsing.
    """
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # Only null out %tokens sitting in VALUE position (right after a colon) so we don't
        # clobber %-encoded sequences inside quoted strings (e.g. %C2%B0 in a maps URL).
        cleaned = re.sub(r"(:\s*)%[A-Za-z0-9_]+", r"\1null", body)
        cleaned = re.sub(r":\s*(?=[,}\]])", ": null", cleaned)  # ": ," -> ": null,"
        return json.loads(cleaned)


def extract(obj: dict) -> dict:
    """Map the nested Get-Location-v2 body (and simple flat bodies) to columns."""
    loc = obj.get("location") or {}
    alt = obj.get("altitude") or {}
    mov = obj.get("movement") or {}
    dev = obj.get("device") or {}

    lat = _num(loc.get("latitude") if isinstance(loc, dict) else None) or _num(obj.get("lat"))
    lon = _num(loc.get("longitude") if isinstance(loc, dict) else None) or _num(obj.get("lon"))
    # fallback: "lat,lon" string in location.coordinates or top-level loc
    if lat is None or lon is None:
        coords = (loc.get("coordinates") if isinstance(loc, dict) else None) or obj.get("loc")
        if isinstance(coords, str) and "," in coords:
            a, b = coords.split(",", 1)
            lat = lat if lat is not None else _num(a)
            lon = lon if lon is not None else _num(b)

    batt = _num(dev.get("battery_level_percent") if isinstance(dev, dict) else None)
    if batt is None:
        batt = _num(obj.get("battery"))

    return {
        "source": obj.get("source", "tasker"),
        "lat": lat,
        "lon": lon,
        "accuracy": _num(loc.get("accuracy_meters") if isinstance(loc, dict) else None) or _num(obj.get("accuracy")),
        "altitude": _num(alt.get("elevation_meters") if isinstance(alt, dict) else None) or _num(obj.get("altitude")),
        "speed": _num(mov.get("speed_mps") if isinstance(mov, dict) else None) or _num(obj.get("speed")),
        "bearing": _num(mov.get("bearing_degrees") if isinstance(mov, dict) else None) or _num(obj.get("bearing")),
        "battery": int(batt) if batt is not None else None,
    }


def authorized(request: Request, obj: dict) -> bool:
    t = (
        request.query_params.get("token")
        or request.headers.get("x-token")
        or re.sub(r"(?i)^bearer\s+", "", request.headers.get("authorization", ""))
        or (obj.get("token") if isinstance(obj, dict) else None)
    )
    return bool(t) and t == TOKEN


# ── routes ───────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"ok": True, "service": "geoloc"}


@app.api_route("/loc", methods=["POST"])
@app.api_route("/", methods=["POST"])
async def ingest(request: Request):
    raw = await request.body()
    text = raw.decode("utf-8", "replace").strip()
    obj: dict = {}
    if text:
        try:
            obj = lenient_json(text)
        except Exception:
            # last resort: form-encoded
            from urllib.parse import parse_qsl
            obj = dict(parse_qsl(text))
    if not isinstance(obj, dict):
        obj = {}
    # merge query params (body wins)
    for k, v in request.query_params.items():
        obj.setdefault(k, v)

    if not authorized(request, obj):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    rec = extract(obj)
    if rec["lat"] is None or rec["lon"] is None:
        return JSONResponse({"error": "lat/lon required", "parsed": rec}, status_code=400)

    obj.pop("token", None)  # never persist the secret
    row = await pool.fetchrow(
        """
        INSERT INTO track.locations
            (source, lat, lon, accuracy, altitude, speed, bearing, battery, raw, geom)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,
                ST_SetSRID(ST_MakePoint($3,$2),4326)::geography)
        RETURNING id, ts
        """,
        rec["source"], rec["lat"], rec["lon"], rec["accuracy"], rec["altitude"],
        rec["speed"], rec["bearing"], rec["battery"], json.dumps(obj),
    )
    await update_presence(rec["lat"], rec["lon"])
    return {"ok": True, "id": row["id"], "ts": row["ts"].isoformat(),
            "lat": rec["lat"], "lon": rec["lon"]}


PRESENCE_FILE = "/home/umair/genesis/org/presence.json"
SAY = "/home/umair/genesis/tools/say"


async def update_presence(lat: float, lon: float) -> None:
    """Zone-match the fix; on enter/leave, record it and announce on the bus."""
    try:
        zone = await pool.fetchval(
            """SELECT name FROM track.zones
               WHERE ST_DWithin(ST_SetSRID(ST_MakePoint(lon,lat),4326)::geography,
                                ST_SetSRID(ST_MakePoint($2,$1),4326)::geography, radius_m)
               ORDER BY radius_m LIMIT 1""", lat, lon)
        prev = await pool.fetchrow("SELECT zone, since FROM track.presence WHERE id")
        prev_zone = prev["zone"] if prev else None
        if zone != prev_zone:
            await pool.execute(
                "UPDATE track.presence SET zone=$1, since=now(), updated=now() WHERE id", zone)
            if zone and not prev_zone:
                text = f"📍 Umair arrived at {zone}"
            elif prev_zone and not zone:
                text = f"📍 Umair left {prev_zone}"
            else:
                text = f"📍 Umair moved: {prev_zone} → {zone}"
            subprocess.run([SAY, "GEOLOC", "all", text, "--channel", "general",
                            "--kind", "event"], capture_output=True, timeout=10)
        else:
            await pool.execute("UPDATE track.presence SET updated=now() WHERE id")
        cur = await pool.fetchrow("SELECT zone, since, updated FROM track.presence WHERE id")
        with open(PRESENCE_FILE, "w") as f:
            json.dump({"zone": cur["zone"],
                       "since": cur["since"].isoformat() if cur["since"] else None,
                       "updated": cur["updated"].isoformat()}, f)
    except Exception as e:  # presence is best-effort; never fail the ingest
        print("presence update failed:", e)


@app.get("/recent")
async def recent(request: Request):
    local = request.client and request.client.host in ("127.0.0.1", "::1")
    if not local and not authorized(request, {}):
        return JSONResponse({"error": "localhost or token required"}, status_code=401)
    rows = await pool.fetch(
        "SELECT id, ts, lat, lon, accuracy, battery FROM track.locations ORDER BY ts DESC LIMIT 20"
    )
    return [dict(r) | {"ts": r["ts"].isoformat()} for r in rows]
