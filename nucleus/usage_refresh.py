#!/usr/bin/env python3
"""The ONE module in this estate that reads the Claude Code OAuth credential.

HISTORY. Born as a 5-minute systemd-timer poller writing var/usage_cache.json (goal
#2470). Owner restructure 2026-08-21: the timer, the cache, the baseline/shape machinery
and the standalone refresh loop are GONE — the Stop hook (hooks/step.py) calls snapshot()
after each turn (throttled org-wide) and writes the projection onto the turn's row, and
the observatory reads `turns`. Activity drives the cadence; the DB is the history.

READ-ONLY ON THE CREDENTIAL, ALWAYS. Never refresh, never write, never race Claude Code
for the org's auth — losing that race is the org-wide latch this exists to forecast. On
401/403 we record the state and tell nobody to re-auth but the reader. We never touch
refreshToken, even though it sits in the same file.
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CRED = Path.home() / ".claude" / ".credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# ─────────────────────────────────────────────────────────────────────────────────────
# THE EGRESS ALLOWLIST — single authority for what leaves the credential's blast radius.
# A HAND-MAINTAINED SET IS SAFE EXACTLY WHEN OMISSION IS THE SAFE DIRECTION: forgetting a
# key here DROPS it (fail-closed) — the failure is a missing number on a dashboard, never
# account data somewhere it can't be recalled. Derived from an OBSERVED 200 (BC-1, three
# calls), not from guesses; the live response carried ten present-but-null codename keys,
# and unreleased upstream features are exactly the unknown-key case, dropped by
# construction.
#
# DOLLAR FIGURES ARE DELIBERATELY EXCLUDED. `spend.*` and every `*_dollars` field are the
# owner's FINANCES — human-personal tier (local.md), never on the wire, and the snapshot's
# destination (`turns`) IS wire-readable. Utilization is a percentage; that is the job.
USAGE_ALLOWLIST = {
    "five_hour_utilization":       ("five_hour", "utilization"),
    "five_hour_resets_at":         ("five_hour", "resets_at"),
    "seven_day_utilization":       ("seven_day", "utilization"),
    "seven_day_resets_at":         ("seven_day", "resets_at"),
    "seven_day_opus_utilization":  ("seven_day_opus", "utilization"),
    "seven_day_opus_resets_at":    ("seven_day_opus", "resets_at"),
    "seven_day_sonnet_utilization": ("seven_day_sonnet", "utilization"),
    "seven_day_sonnet_resets_at":  ("seven_day_sonnet", "resets_at"),
}
# `limits` is a list of per-scope rungs; these are the fields taken from each element.
LIMITS_ALLOWLIST = ("kind", "group", "percent", "severity", "resets_at", "is_active")


def _scrub(text: str, *secrets: str) -> str:
    """No exception text may carry the token — the leak path is an exception repr echoing
    the Authorization header, which no name-based lint can see."""
    out = str(text)
    for s in secrets:
        if s:
            out = out.replace(s, "<redacted>")
    import re
    out = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}", "Bearer <redacted>", out)
    out = re.sub(r"sk-[A-Za-z0-9._\-]{16,}", "<redacted>", out)
    return out[:400]


def fetch(token: str, timeout: int = 20) -> tuple[int | None, dict | None, str | None]:
    """-> (status, body, error). Never raises outward; never leaks the token. The Stop
    hook runs on the agent's critical path and passes a tight timeout — a slow endpoint
    must cost a NULL snapshot, never a stalled turn."""
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "astryx-usage-refresh/1",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        return e.code, None, _scrub(f"HTTP {e.code}", token)
    except Exception as e:
        return None, None, _scrub(f"{type(e).__name__}: {e}", token)


def _dig(body: dict, path: tuple):
    cur = body
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def extract(body: dict) -> dict:
    """Allowlist-only projection. An unknown key cannot reach the output because the
    output is BUILT from the allowlist rather than filtered against it."""
    out = {k: _dig(body, path) for k, path in USAGE_ALLOWLIST.items()}
    rungs = []
    for item in (body.get("limits") or []):
        if isinstance(item, dict):
            rungs.append({f: item.get(f) for f in LIMITS_ALLOWLIST})
    out["limits"] = rungs
    return out


def snapshot(timeout: int = 4) -> dict | None:
    """A wire-safe account-usage snapshot for the Stop hook to store on the turn row.

      None                          -> nothing worth writing (no credential / no token);
                                       a missing snapshot is a NULL row, never a zero.
      {state: auth_rejected|unavailable, ...}  -> the attempt happened and FAILED; the
                                       STATE is recorded (never a fake number) so a reader
                                       can tell "the instrument was blind" from "low".
      {state: fresh, subscription, rate_limit_tier, data:{...}}  -> a live 200.

    subscription/rate_limit_tier come from the credential and are the plan NAME (e.g.
    'max') — not money, not the human-personal tier.
    """
    if not CRED.exists():
        return None
    try:
        oauth = (json.loads(CRED.read_text()).get("claudeAiOauth") or {})
    except Exception:
        return None
    token = oauth.get("accessToken")
    if not token:
        return None
    now = datetime.now(timezone.utc).isoformat()
    status, body, _err = fetch(token, timeout=timeout)
    if status != 200 or not isinstance(body, dict):
        state = "auth_rejected" if status in (401, 403) else "unavailable"
        return {"fetched_at": now, "state": state}
    return {
        "fetched_at": now,
        "state": "fresh",
        "subscription": oauth.get("subscriptionType"),
        "rate_limit_tier": oauth.get("rateLimitTier"),
        "data": extract(body),
    }
