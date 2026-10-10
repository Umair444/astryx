"""astryx · ear_lease — D4's ONE lease seam (plan-8674 S1): the EAR/MUTED state of a room's microphone.

The ONLY writer of the main db's `leases` table (schema.sql). One row per resource; for hearing the resource is
'ear:<room>', so the primary key IS "one ear per room". No text ever lives here (the transcript is `utterances`).

  claim(conn, res, holder)      atomic UPDATE … WHERE state='free' (or this holder's / an EXPIRED EAR) RETURNING.
                                MUTED is never claimable: only the owner's unmute ends it.
  heartbeat(conn, res, holder)  extends a live EAR held by `holder`; None if it isn't (muted, lost, taken)
  release(conn, res, holder)    EAR → free, only by its holder
  mute(conn, res)               ANY state → MUTED, no TTL (one tap; it always wins)
  unmute(conn, res)             MUTED → free
  indicator(row, now)           what the observatory shows, DERIVED from the row + heartbeat age: never stored

  hold(conn, res, holder, ttl)   HELD, for a resource that isn't a microphone (plan-8675 C4: 'vm-slot',
                                'android:<avd>'): free, this holder's own, or an expired hold → HELD by holder
  unhold(conn, res, holder)     HELD → free, only while `holder` holds it (also how a caller frees a hold whose
                                holder it has PROVED gone: keyed on the holder it inspected, never a newer one)

Deliberately NOT nucleus/hands.py / hands_leases: the owner rejected that design (2026-10-10).
"""
from __future__ import annotations

from datetime import datetime, timezone

TTL_S = 30                      # an EAR hold dies 30 s after its last heartbeat (the browser beats every ~10 s)
COLS = "resource, holder, state, granted_at, expires_at, heartbeat_at, budget"


def _row(cur) -> dict | None:
    r = cur.fetchone()
    if r is None:
        return None
    return dict(zip([d.name for d in cur.description], r))


def _ensure(conn, resource: str) -> None:
    conn.execute("INSERT INTO leases (resource) VALUES (%s) ON CONFLICT (resource) DO NOTHING", (resource,))


def get(conn, resource: str) -> dict | None:
    return _row(conn.execute(f"SELECT {COLS} FROM leases WHERE resource = %s", (resource,)))


def claim(conn, resource: str, holder: str, ttl_s: int = TTL_S) -> dict | None:
    """The row if `holder` now holds the EAR, else None. One statement: two racing tabs can't both win."""
    _ensure(conn, resource)
    return _row(conn.execute(
        f"UPDATE leases SET holder = %s, state = 'EAR', granted_at = now(), "
        f"expires_at = now() + make_interval(secs => %s), heartbeat_at = now() "
        f"WHERE resource = %s AND (state = 'free' OR (state = 'EAR' AND (holder = %s OR expires_at < now()))) "
        f"RETURNING {COLS}", (holder, ttl_s, resource, holder)))


def heartbeat(conn, resource: str, holder: str, ttl_s: int = TTL_S) -> dict | None:
    return _row(conn.execute(
        f"UPDATE leases SET heartbeat_at = now(), expires_at = now() + make_interval(secs => %s) "
        f"WHERE resource = %s AND state = 'EAR' AND holder = %s AND expires_at >= now() RETURNING {COLS}",
        (ttl_s, resource, holder)))


def release(conn, resource: str, holder: str) -> dict | None:
    return _row(conn.execute(
        f"UPDATE leases SET holder = NULL, state = 'free', granted_at = NULL, expires_at = NULL "
        f"WHERE resource = %s AND state = 'EAR' AND holder = %s RETURNING {COLS}", (resource, holder)))


def mute(conn, resource: str, by: str = "owner") -> dict:
    """Idempotent: an already-MUTED room keeps its original mute (who, since when) and is returned as it is."""
    _ensure(conn, resource)
    return _row(conn.execute(
        f"UPDATE leases SET holder = %s, state = 'MUTED', granted_at = now(), expires_at = NULL, "
        f"heartbeat_at = now() WHERE resource = %s AND state <> 'MUTED' RETURNING {COLS}", (by, resource))) \
        or get(conn, resource)


def unmute(conn, resource: str) -> dict | None:
    return _row(conn.execute(
        f"UPDATE leases SET holder = NULL, state = 'free', granted_at = NULL, expires_at = NULL "
        f"WHERE resource = %s AND state = 'MUTED' RETURNING {COLS}", (resource,)))


def indicator(row: dict | None, now: datetime | None = None) -> dict:
    """{'mic': off|listening|stale|muted|focal|reverting, 'holder', 'age_s'}. A hold past its TTL never reads as
    live: EAR → 'stale' (the tab died; the next claim takes it), FOCAL → 'reverting' (a3 R3-6)."""
    now = now or datetime.now(timezone.utc)
    if not row or row["state"] == "free":
        return {"mic": "off", "holder": None, "age_s": None}
    age = (now - row["heartbeat_at"]).total_seconds() if row.get("heartbeat_at") else None
    if row["state"] == "MUTED":
        return {"mic": "muted", "holder": row["holder"], "age_s": age}
    live = row["expires_at"] is not None and row["expires_at"] >= now
    mic = {"EAR": "listening" if live else "stale", "FOCAL": "focal" if live else "reverting"}[row["state"]]
    return {"mic": mic, "holder": row["holder"], "age_s": age}


def _not_ear(resource: str) -> None:
    # A microphone's lease has states a plain hold must never touch (MUTED only the owner ends).
    if resource.startswith("ear:"):
        raise ValueError(f"{resource} is a microphone lease: use claim/release/mute")


def hold(conn, resource: str, holder: str, ttl_s: int) -> dict | None:
    """The row if `holder` now holds `resource`, else None (someone else holds it, live). One statement."""
    _not_ear(resource)
    _ensure(conn, resource)
    return _row(conn.execute(
        f"UPDATE leases SET holder = %s, state = 'HELD', granted_at = CASE WHEN holder = %s AND state = 'HELD' "
        f"THEN granted_at ELSE now() END, expires_at = now() + make_interval(secs => %s), heartbeat_at = now() "
        f"WHERE resource = %s AND (state = 'free' OR (state = 'HELD' AND (holder = %s OR expires_at < now()))) "
        f"RETURNING {COLS}", (holder, holder, ttl_s, resource, holder)))


def unhold(conn, resource: str, holder: str) -> dict | None:
    _not_ear(resource)
    return _row(conn.execute(
        f"UPDATE leases SET holder = NULL, state = 'free', granted_at = NULL, expires_at = NULL "
        f"WHERE resource = %s AND state = 'HELD' AND holder = %s RETURNING {COLS}", (resource, holder)))

