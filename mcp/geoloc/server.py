#!/usr/bin/env python3
"""astryx · geoloc MCP server — the owner's location as a scoped capability.

Tools over the location store fed by bridges/geoloc.py. `locate(fresh=True)` fires
the AutoRemote getlocation push, the phone's Tasker task POSTs the fix back to the
intake, and this server returns the fresh row.

Privacy: location is personal-tier data. This server is granted per charter
(a `Grants: geoloc` line); agents that hold it answer the owner and his trusted
surfaces, and never disclose coordinates on public ones.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import asyncpg
from mcp.server.fastmcp import FastMCP

# Config from the org's .env (single source of truth).
ENV = Path(__file__).resolve().parents[2] / ".env"
_cfg = dict(
    line.split("=", 1)
    for line in ENV.read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
DSN = _cfg["GEOLOC_DSN"]
TRIGGER_URL = _cfg.get("AUTOREMOTE_GETLOC_URL", "")

mcp = FastMCP("astryx-geoloc")
_pool: Optional[asyncpg.Pool] = None


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    return _pool


def _row(r) -> dict:
    return {
        "id": r["id"],
        "ts": r["ts"].isoformat(),
        "lat": r["lat"],
        "lon": r["lon"],
        "accuracy_m": r["accuracy"],
        "altitude_m": r["altitude"],
        "speed_mps": r["speed"],
        "battery_pct": r["battery"],
        "maps": f"https://maps.google.com/?q={r['lat']},{r['lon']}",
    }


@mcp.tool()
async def locate(fresh: bool = False, timeout_seconds: int = 45) -> dict:
    """The owner's location — one tool, last-known or fresh by the `fresh` flag.

    fresh=False (default): the last KNOWN fix from the store — instant, no phone round-trip.
    fresh=True: push a getlocation request to the phone via AutoRemote and wait for Tasker to
                post the new fix back (~5-15s when the phone is online); falls back to the last
                known fix if the phone doesn't answer.

    EFFECT: fresh=True pings the phone (a real side effect). PRIVATE data — never disclose on
    public surfaces. For a privacy-safe ZONE-only answer (family-facing), use where_is_owner.

    Args:
        fresh: True forces a live phone fix; False returns the stored last-known fix.
        timeout_seconds: how long to wait for the phone when fresh=True (default 45).
    Returns: {ok, fresh, ts, lat, lon, accuracy_m, battery_pct, maps, …}; last-known also
             carries age_minutes, a phone timeout carries fallback_last_known.
    """
    p = await pool()
    if fresh:
        if not TRIGGER_URL:
            return {"ok": False, "error": "AUTOREMOTE_GETLOC_URL not configured"}
        before = await p.fetchval("SELECT coalesce(max(id),0) FROM track.locations")
        r = subprocess.run(["curl", "-s", "-m", "10", TRIGGER_URL], capture_output=True, text=True)
        if "OK" not in r.stdout:
            return {"ok": False, "error": f"AutoRemote push failed: {r.stdout or r.stderr}"}
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            row = await p.fetchrow(
                "SELECT * FROM track.locations WHERE id > $1 ORDER BY id DESC LIMIT 1", before)
            if row:
                return {"ok": True, "fresh": True, **_row(row)}
            await asyncio.sleep(2)
        last = await p.fetchrow("SELECT * FROM track.locations ORDER BY ts DESC LIMIT 1")
        return {"ok": False, "error": "phone did not answer in time",
                "fallback_last_known": _row(last) if last else None}
    row = await p.fetchrow("SELECT * FROM track.locations ORDER BY ts DESC LIMIT 1")
    if not row:
        return {"ok": False, "error": "no locations stored yet"}
    age = await p.fetchval("SELECT extract(epoch FROM now()-ts)/60 FROM track.locations ORDER BY ts DESC LIMIT 1")
    return {"ok": True, "fresh": False, "age_minutes": round(float(age), 1), **_row(row)}


@mcp.tool()
async def location_history(limit: int = 20, since: Optional[str] = None) -> list[dict]:
    """Recent location fixes, newest first. PRIVATE data.

    Args:
        limit: max rows (default 20).
        since: optional ISO date/time lower bound (e.g. '2026-07-07' or full timestamp).
    """
    p = await pool()
    if since:
        rows = await p.fetch(
            "SELECT * FROM track.locations WHERE ts >= $1::timestamptz ORDER BY ts DESC LIMIT $2",
            since, limit)
    else:
        rows = await p.fetch("SELECT * FROM track.locations ORDER BY ts DESC LIMIT $1", limit)
    return [_row(r) for r in rows]


@mcp.tool()
async def where_is_owner() -> dict:
    """The owner's presence by ZONE (home/office/...) — the privacy-safe answer for
    family-facing surfaces. Returns zone name + time there, never raw coordinates.
    Falls back to 'roaming' when outside all zones."""
    p = await pool()
    r = await p.fetchrow("SELECT zone, since, updated FROM track.presence WHERE id")
    if not r or (not r["zone"] and not r["updated"]):
        return {"zone": None, "note": "no presence data yet"}
    age_min = await p.fetchval("SELECT extract(epoch FROM now()-updated)/60 FROM track.presence WHERE id")
    return {
        "zone": r["zone"] or "roaming",
        "since": r["since"].isoformat() if r["since"] else None,
        "data_age_minutes": round(float(age_min), 1),
        "note": "zone-level only; use locate(fresh=True) for exact coords (private surfaces only)",
    }


@mcp.tool()
async def zones() -> list[dict]:
    """List the defined geofence zones (name, center, radius, privacy tier)."""
    p = await pool()
    rows = await p.fetch("SELECT name, lat, lon, radius_m, tier FROM track.zones ORDER BY name")
    return [dict(r) for r in rows]


@mcp.tool()
async def zone_add(name: str, lat: float, lon: float, radius_m: float = 250,
                   tier: str = "trusted") -> dict:
    """Define or update a geofence zone (e.g. 'office', 'parents'). Presence updates
    when the owner enters/leaves it.

    Args:
        name: zone name (unique; lowercase, e.g. 'office').
        lat, lon: center coordinates.
        radius_m: radius in meters (default 250).
        tier: privacy tier — 'private' | 'trusted' | 'public' (default trusted).
    """
    p = await pool()
    await p.execute(
        """INSERT INTO track.zones(name,lat,lon,radius_m,tier) VALUES ($1,$2,$3,$4,$5)
           ON CONFLICT (name) DO UPDATE SET lat=$2, lon=$3, radius_m=$4, tier=$5""",
        name, lat, lon, radius_m, tier)
    return {"ok": True, "zone": name}


@mcp.tool()
async def distance_between(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    """Geodesic distance in meters between two lat/lon points (PostGIS geography)."""
    p = await pool()
    d = await p.fetchval(
        "SELECT ST_Distance(ST_SetSRID(ST_MakePoint($2,$1),4326)::geography,"
        "                   ST_SetSRID(ST_MakePoint($4,$3),4326)::geography)",
        lat1, lon1, lat2, lon2)
    return {"meters": round(float(d), 1), "km": round(float(d) / 1000, 3)}


if __name__ == "__main__":
    mcp.run()
