#!/home/umair/astryx/venv/bin/python
"""Authoritative plan-limit gauges: the ONE module in this estate that reads the
Claude Code OAuth credential. Goal #2470, plan-2470 (quorum 4/4 against msg 12363).

WHY THIS IS A SEPARATE UNIT AND NOT A HANDLER. The observatory process must never open
the credential, so this runs on its own timer and leaves a cache the API reads. Grade the
prevention honestly, because the sentence ships to every install with the code:

  PREVENTED, structurally: disclosure through the HTTP surface — a misconfigured gate, an
    exception repr carrying an Authorization header, a forward-and-redact miss, any future
    response-construction bug. None can leak a token the process does not hold.
  NOT PREVENTED: code execution in the observatory process, which runs as the same uid and
    can open the credential directly, placement or no placement.

It is a boundary against REACHABILITY, not against EXECUTION.

READ-ONLY ON THE CREDENTIAL, ALWAYS. Never refresh, never write, never race Claude Code
for the org's auth — losing that race is the org-wide latch this panel exists to forecast.
On 401/403 we degrade to STALE and tell the human to re-auth in Claude Code. We do not
touch refreshToken, ever, even though it is sitting right there in the same file.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CRED = Path.home() / ".claude" / ".credentials.json"
CACHE = REPO / "var" / "usage_cache.json"   # var/ is gitignored (.gitignore:45)
STATUS = REPO / "var" / "usage_status.json"  # last-run state, NEVER any numbers
ARCHIVE = REPO / "memory" / "usage"             # memory's sampler; baseline authority
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
REFRESH_INTERVAL_S = 300        # see plan-2470 §3: 15-min sampling floor derives from this
STALE_AFTER_S = 3 * REFRESH_INTERVAL_S

# ─────────────────────────────────────────────────────────────────────────────────────
# THE EGRESS ALLOWLIST. Single authority for what leaves this box AND what memory's
# sampler archives — one writer for the schema, so the archive can never restate it and
# drift. memory derives its columns from this constant; do not inline a second copy.
#
# A HAND-MAINTAINED SET IS SAFE EXACTLY WHEN OMISSION IS THE SAFE DIRECTION.
#   forget to add to a COVERAGE set        -> the member goes UNCHECKED  (fail-open, unsafe)
#   forget to add to an EXEMPTION manifest -> the member gets ACCUSED    (fail-closed, safe)
#   forget to add to an EGRESS allowlist   -> the key is DROPPED         (fail-closed, safe)
# Three sets, one test, and the test is a question about the FAILURE MODE OF FORGETTING
# rather than about what membership confers. So this list being hand-written is not tech
# debt to apologise for — it is the property that makes it safe. An unknown key defaults
# to DROPPED: the failure is a missing number on a dashboard rather than another org's
# account data on a machine we cannot reach.
#
# DERIVED FROM AN OBSERVED 200 (BC-1, three calls), never from the design thread's guesses.
# The live response carried ten present-but-null codename keys (tangelo, iguana_necktie,
# nimbus_quill, cinder_cove, amber_ladder, omelette_promotional, seven_day_cowork,
# seven_day_omelette, seven_day_oauth_apps, ...). Unreleased upstream features are exactly
# the unknown-key case, and they are dropped by construction.
#
# DOLLAR FIGURES ARE DELIBERATELY EXCLUDED. `spend.*`, `limit_dollars`, `used_dollars`,
# `remaining_dollars` are the owner's FINANCES, which local.md puts in the human-personal
# tier — never on the wire, never in a RAG-reachable artifact. The panel's job is
# utilization, and utilization is a percentage.
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
# `limits` is a list of per-scope rungs; these are the fields we take from each element.
LIMITS_ALLOWLIST = ("kind", "group", "percent", "severity", "resets_at", "is_active")

# The keys whose PRESENCE is the shape contract. BC-1 measured the discriminator: the
# upstream marks an inapplicable rung with a NULL VALUE, never by dropping the key —
# `seven_day_opus` was null across three calls while this org ran Opus all week. So a
# missing KEY is a real upstream change and a null VALUE is ordinary operation, and
# SHAPE-CHANGED must test membership, never truthiness. Testing non-null here would make
# every idle model raise it and demote the authoritative gauge during normal use.
STRUCTURAL_KEYS = ("five_hour", "seven_day", "limits", "extra_usage")

CRED_ABSENT, CRED_UNREADABLE, CRED_UNPARSEABLE, CRED_OK = (
    "not_configured", "unreadable", "unparseable", "ok")


def _scrub(text: str, *secrets: str) -> str:
    """No exception text may carry the token. The leak path this closes is an exception
    repr echoing the Authorization header, which no name-based lint can see."""
    out = str(text)
    for s in secrets:
        if s:
            out = out.replace(s, "<redacted>")
    # belt: anything that looks like a bearer credential goes regardless of provenance
    import re
    out = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}", "Bearer <redacted>", out)
    out = re.sub(r"sk-[A-Za-z0-9._\-]{16,}", "<redacted>", out)
    return out[:400]


def read_credential() -> tuple[str, str | None]:
    """-> (state, access_token). Absent / unreadable / unparseable are three different
    human actions, so they are three different states and never one 'no credential'."""
    if not CRED.exists():
        return CRED_ABSENT, None
    try:
        raw = CRED.read_text()                      # read-only; never open for write
    except Exception:
        return CRED_UNREADABLE, None
    try:
        tok = (json.loads(raw).get("claudeAiOauth") or {}).get("accessToken")
    except Exception:
        # includes the read-while-Claude-Code-rotates case: a truncated JSON is a
        # transient READ failure on a different file, and can never present as
        # SHAPE-CHANGED, which is defined only over a successful 200.
        return CRED_UNPARSEABLE, None
    return (CRED_OK, tok) if tok else (CRED_UNPARSEABLE, None)


def fetch(token: str) -> tuple[int | None, dict | None, str | None]:
    """-> (status, body, error). Never raises outward; never leaks the token."""
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "astryx-usage-refresh/1",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
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


BASELINE = ARCHIVE / "baseline.json"     # written by memory; see the contract below
BASELINE_MAX_AGE_DAYS = 7


def baseline_keys() -> tuple[set, str]:
    """The shape baseline, and WHERE it came from — never silently nothing.

    CONTRACT (agreed with memory, thread t-mt0hk4ar): memory writes
    `memory/usage/baseline.json` carrying the DERIVED key set plus its own provenance:

        {"keys": [...], "sample_count": N, "min_samples": M, "window": "...",
         "presence_threshold": 0.8, "generated_at": "<iso8601>"}

    `min_samples` is an INTEGER PRECONDITION I enforce: the baseline may not arm until the
    window holds at least this many samples. `presence_threshold` is memory's derivation
    rule (a key must appear in >= this fraction of the window) — recorded for a human
    reading the file, deliberately NOT enforced here, because how the set is derived is
    memory's organ and duplicating the rule would give it two writers. The field was
    briefly called `quorum`, which read as an integer count to me and as a fraction to
    memory: one name for two quantities, caught before either side wrote a file. A name
    two readers can read differently is the defect, not the disagreement it produces.

    memory derives it by QUORUM over a trailing window — a key must appear in at least M
    of N samples. A union over all history was the first design and it was wrong in a way
    that only a history can fix: a union only ever GROWS, so a legitimately retired key
    fires forever with no remedy but falsifying the archive, and ONE transient key poisons
    the baseline for the life of the org. Quorum still refuses "adopt whatever I see now",
    because a single sample can never reach it. The reason to depend on a series is that
    it can outvote a sample; a union throws the series away and keeps only its envelope.

    WHY NOT DERIVE IT HERE. The raw series is memory's format and its organ's job. The
    first version of this function globbed `*.json` against an archive declared as
    `*.jsonl` and whole-file-parsed a line-delimited series — it read NOTHING, reported
    "none", and would have left SHAPE-CHANGED dormant forever with no error anywhere.
    Reproduced before believing it. Reading one small file with its own provenance removes
    my dependency on someone else's serialisation entirely.

    EVERY REFUSAL IS NAMED. This returns a REASON, never a bare empty set, because the
    defect above was invisible precisely for want of one. Dormant is the correct fail
    direction — a false SHAPE-CHANGED demotes the authoritative gauge, which is the
    instrument switching itself off — but dormant must be LEGIBLE, so the state travels
    to the panel as `baseline_source` rather than dying here.
    """
    if not BASELINE.exists():
        return set(), "none"
    try:
        d = json.loads(BASELINE.read_text())
    except Exception:
        return set(), "unreadable"
    if not isinstance(d, dict):
        return set(), "unreadable"
    keys = d.get("keys")
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        return set(), "unreadable"
    try:
        n, q = int(d.get("sample_count", 0)), int(d.get("min_samples", 0))
    except Exception:
        return set(), "unreadable"
    if q < 1 or n < q:
        return set(), "insufficient"
    ts = d.get("generated_at")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).days
    except Exception:
        return set(), "unreadable"
    if age > BASELINE_MAX_AGE_DAYS:
        return set(), "stale"
    return set(keys), "baseline"


def shape_missing(body: dict, baseline: set) -> list:
    """The SHAPE-CHANGED predicate, in ONE place so the oracle tests the real thing
    rather than its own re-derivation of it.

    MEMBERSHIP, NEVER TRUTHINESS. BC-1 measured the discriminator: the upstream marks an
    inapplicable rung with a NULL VALUE and keeps the key — `seven_day_opus` was null
    across three calls while this org ran Opus all week. A truthiness test would fire on
    every idle model and demote the authoritative gauge during ordinary operation, which
    is the instrument switching itself off in response to the thing it measures.
    """
    return sorted(k for k in (baseline & set(STRUCTURAL_KEYS)) if k not in body)


def refresh() -> dict:
    now = datetime.now(timezone.utc)
    state, token = read_credential()
    if state != CRED_OK:
        # NOT-CONFIGURED / UNREADABLE / UNPARSEABLE never write the cache: the cache is
        # written ONLY on successful extraction, so a dead refresher can never mint a
        # number, and freshness stays a property of the last GOOD observation.
        return {"state": state, "wrote_cache": False}

    status, body, err = fetch(token)
    if status in (401, 403):
        return {"state": "stale", "reason": "auth_rejected",
                "hint": "re-auth in Claude Code", "wrote_cache": False}
    if status != 200 or not isinstance(body, dict):
        return {"state": "stale", "reason": err or f"http_{status}", "wrote_cache": False}

    observed = set(body.keys())
    base, base_src = baseline_keys()
    # membership, not truthiness — see STRUCTURAL_KEYS
    missing = shape_missing(body, base)
    shape_changed = bool(missing)

    payload = {
        "fetched_at": now.isoformat(),
        "state": "shape_changed" if shape_changed else "fresh",
        "missing_structural_keys": missing,
        "baseline_source": base_src,
        "observed_keys": sorted(observed),
        "data": extract(body),
    }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1))
    os.replace(tmp, CACHE)          # atomic: a reader never sees a half-written cache
    return {"state": payload["state"], "wrote_cache": True,
            "missing_structural_keys": missing}


def _write_status(state: str, hint: str | None = None, **extra) -> None:
    """Every run, success or not. NO NUMBERS EVER LIVE HERE — this file exists so the
    read side can tell 'nobody is configured' from 'the timer never ran' without opening
    the credential (BC-2 clause 2). The moment a gauge value lands in here it becomes a
    second, undated source of numbers and the never-render-an-undated-number rule is
    silently gone, so the omission is the point."""
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    payload = {"checked_at": datetime.now(timezone.utc).isoformat(), "state": state}
    if hint:
        payload["hint"] = hint
    payload.update({k: v for k, v in extra.items() if k != "data"})
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1))
    os.replace(tmp, STATUS)


if __name__ == "__main__":
    r = refresh()
    _write_status(r["state"], r.get("hint"),
                  reason=r.get("reason"),
                  missing_structural_keys=r.get("missing_structural_keys") or [])
    print(json.dumps(r))
    # A refresher that cannot reach the endpoint is not a broken unit; an install with no
    # credential is the MODAL case and must not spam the journal with failures.
    sys.exit(0)
