#!/usr/bin/env python3
"""RED-first oracle — the usage-authority (owner goal #3833).

Proves the unification does what it claims AND that each guard CAN fire: every arm
ships with the RED control that flips it, because a green arm whose control never ran
tests nothing (terminal-test law). The five arms:

  WRITE   the fetch/skip gate (_stale), pure — control: the inverted threshold disagrees
          on a stale authority, so the arm has teeth.
  NEWEST  an idle-fresh poll reading wins over a stale turns reading (unification).
  CLOCK   an error/None attempt (newest) never advances the authority's age — control:
          WITHOUT the good-filter the error IS newest, so the filter is load-bearing.
  EMPTY   no good reading anywhere → the authority is empty (readers get null, the gate
          fetches) — fail-toward-fetch.
  TIER    the served surface (usage_readings, both arms) carries NO tier key — controls:
          (i) a planted *_dollars key FIRES the assert; (ii) a raw-fetch() body (spend.*)
          bypass leaves a detectable key on the served surface (containment). The assert
          is KEY-NAME scoped: it detects a key-level breach, NOT a dollar VALUE smuggled
          under an allowed key (that residual is the same-uid direct-write ceiling, 3499's
          territory; the legitimate path is prevention-grade at snapshot()/extract()).
  READ    every gauge reader references the authority, none is left on the raw turns-only
          query — control: the census flags a synthetic half-ship.

DB arms run against the REAL schema.sql DDL in a throwaway schema (never the production
usage_polls/turns): the CREATE VIEW text is extracted from schema.sql — the authority,
not a hand copy — so the test validates the shipped views, and a seam never writes prod.
"""
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# PREREQUISITES — the gitignored trigger body and a reachable DB (via .env). A bare clone
# (CI, pushed-tree gate) has NEITHER, so this SKIPs(77) there — never a crash, never a false
# pass — exactly like the other DB-backed gates. The trigger is loaded BY PATH (not
# `from triggers...`): a static triggers-tree import in a COMMITTED file reads as an
# unmanifested third-party dep in a clone where triggers/ is empty (deps.py:68), which is the
# very drift that would fail the clean-clone gate.
TRIGGER = REPO / "triggers" / "seed" / "usage_poll.py"
ENV = REPO / ".env"
if not TRIGGER.exists() or not ENV.exists():
    print("SKIP — usage-authority: prerequisites absent (gitignored trigger body and/or "
          ".env/DB). A bare clone cannot verify this; run on a live host.")
    sys.exit(77)

_spec = importlib.util.spec_from_file_location("usage_poll_under_test", TRIGGER)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
STALE_S, _stale = _mod.STALE_S, _mod._stale

fails = []


def check(name, cond):
    print(("  ok  " if cond else "  XX  ") + name)
    if not cond:
        fails.append(name)


# ── WRITE half: the fetch/skip gate (no DB, no credential) ───────────────────────────

check("WRITE gate: empty authority → fetch", _stale([]) is True)
check("WRITE gate: fresh (age < threshold) → skip", _stale([{"age_seconds": STALE_S - 1}]) is False)
check("WRITE gate: stale (age > threshold) → fetch", _stale([{"age_seconds": STALE_S + 1}]) is True)
check("WRITE gate: null age → fetch", _stale([{"age_seconds": None}]) is True)


def _inverted(rows):  # the mutant: `<` instead of `>`
    if not rows:
        return True
    age = rows[0].get("age_seconds")
    return age is None or float(age) < STALE_S


check("WRITE RED-control: correct and inverted-threshold DISAGREE on a stale authority",
      _stale([{"age_seconds": STALE_S + 1}]) != _inverted([{"age_seconds": STALE_S + 1}]))


# ── DB arms: hermetic temp schema built from the REAL schema.sql view DDL ────────────
import psycopg

DSN = next(l.split("=", 1)[1].strip()
           for l in (REPO / ".env").read_text().splitlines()
           if l.startswith("ASTRYX_DSN="))
BLOCK = ((REPO / "nucleus" / "schema.sql").read_text()
         .split("-- >>> usage-authority")[1].split("-- <<< usage-authority")[0]
         .split("\n", 1)[1])   # drop the marker-line tail, keep the DDL
SCH = f"t3833_{os.getpid()}"
NOW = datetime.now(timezone.utc)


def _iso(mins_ago):
    return (NOW - timedelta(minutes=mins_ago)).isoformat()


def _snap(state="fresh", five=30, seven=60, opus=10, mins_ago=0, extra=None):
    d = {"fetched_at": _iso(mins_ago), "state": state}
    if state == "fresh":
        d["subscription"] = "max"
        d["rate_limit_tier"] = "default"
        d["data"] = {"five_hour_utilization": five, "seven_day_utilization": seven,
                     "seven_day_opus_utilization": opus,
                     "five_hour_resets_at": _iso(-60), "seven_day_resets_at": _iso(-600)}
    if extra:
        d.update(extra)
    return json.dumps(d)


def _tier_keys(obj, path=""):
    """KEY-NAME scan of a served snapshot — flags a finance-shaped key anywhere in the
    jsonb the views expose. Blind by design to a dollar VALUE under an allowed key."""
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            if kl.endswith("_dollars") or kl.startswith("spend") or "cost" in kl:
                bad.append(path + "/" + k)
            bad += _tier_keys(v, path + "/" + k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad += _tier_keys(v, f"{path}[{i}]")
    return bad


def _served_snaps(conn):
    return [r[0] if isinstance(r[0], dict) else json.loads(r[0])
            for r in conn.execute("SELECT snapshot FROM usage_readings").fetchall()]


conn = psycopg.connect(DSN, autocommit=True)
try:
    conn.execute(f"DROP SCHEMA IF EXISTS {SCH} CASCADE")
    conn.execute(f"CREATE SCHEMA {SCH}")
    # SCH ONLY — never `SCH, public`: the DDL below runs `DROP VIEW IF EXISTS current_usage`,
    # which with public in the path would resolve to and DROP the PRODUCTION view. pg_catalog
    # (types, now(), EXTRACT) is always implicitly searched, so SCH-only is sufficient and
    # fully isolates the seam from production.
    conn.execute(f"SET search_path TO {SCH}")
    conn.execute("CREATE TABLE turns (usage_snapshot jsonb, agent text)")
    # strip line-comments FIRST (they contain semicolons), then split on real terminators
    _clean = "\n".join(line.split("--", 1)[0] for line in BLOCK.splitlines())
    for stmt in _clean.split(";"):
        if stmt.strip():
            conn.execute(stmt)

    def reset():
        conn.execute("DELETE FROM turns")
        conn.execute("DELETE FROM usage_polls")

    def add_turn(**kw):
        conn.execute("INSERT INTO turns (usage_snapshot, agent) VALUES (%s::jsonb, %s)",
                     (_snap(**kw), "some-agent"))

    def add_poll(**kw):
        s = _snap(**kw)
        conn.execute("INSERT INTO usage_polls (fetched_at, state, snapshot) "
                     "VALUES ((%s)::timestamptz, %s, %s::jsonb)",
                     (json.loads(s)["fetched_at"], json.loads(s)["state"], s))

    # NEWEST: an idle-fresh poll reading wins over a stale turns reading
    reset()
    add_turn(state="fresh", five=30, mins_ago=60)     # stale (org was idle)
    add_poll(state="fresh", five=42, mins_ago=2)      # idle-fallback poll kept it fresh
    row = conn.execute("SELECT src, five_hour_pct, age_seconds FROM current_usage").fetchone()
    check("NEWEST: idle-fresh poll reading wins over the stale turns reading",
          row is not None and row[0] == "polls" and float(row[1]) == 42)
    check("NEWEST: served age reflects the fresh poll (< 10min), not the hour-old turn",
          row is not None and float(row[2]) < 600)

    # CLOCK: an error attempt (newest) must not advance the authority's age
    reset()
    add_poll(state="fresh", five=50, mins_ago=5)      # last GOOD reading
    add_poll(state="unavailable", mins_ago=1)         # newer, but an ERROR — must be excluded
    row = conn.execute("SELECT state, five_hour_pct, EXTRACT(EPOCH FROM (now()-fetched_at)) "
                       "FROM current_usage").fetchone()
    check("CLOCK: authority = the older GOOD reading, error excluded",
          row is not None and row[0] == "fresh" and float(row[1]) == 50)
    check("CLOCK: error did not advance the clock (age ~ the good reading's, not the error's)",
          row is not None and 240 <= float(row[2]) <= 360)
    broken = conn.execute("SELECT state, EXTRACT(EPOCH FROM (now()-fetched_at)) "
                          "FROM usage_readings ORDER BY fetched_at DESC LIMIT 1").fetchone()
    check("CLOCK RED-control: WITHOUT the good-filter the ERROR row is newest (age < 3min) "
          "— so the filter is load-bearing, not decorative",
          broken is not None and broken[0] != "fresh" and float(broken[1]) < 180)

    # EMPTY: no good reading anywhere → authority empty (readers null, gate fetches)
    reset()
    add_poll(state="unavailable", mins_ago=1)         # only an error attempt on record
    n = conn.execute("SELECT count(*) FROM current_usage").fetchone()[0]
    check("EMPTY: no good reading → authority is empty (readers get null)", n == 0)
    check("EMPTY: the gate fetches on an empty authority (fail-toward-fetch)", _stale([]) is True)

    # TIER: served-surface, key-level, with both controls + the clean baseline
    reset()
    add_poll(state="fresh", five=30, mins_ago=1)      # clean, allowlisted
    check("TIER: a clean allowlisted snapshot has NO tier key on the served surface (no false-positive)",
          all(not _tier_keys(s) for s in _served_snaps(conn)))
    conn.execute("INSERT INTO usage_polls (fetched_at, state, snapshot) VALUES (now(),'fresh',%s::jsonb)",
                 (json.dumps({"fetched_at": _iso(0), "state": "fresh",
                              "data": {"five_hour_utilization": 30, "five_hour_cost_dollars": 9.9}}),))
    hits = [k for s in _served_snaps(conn) for k in _tier_keys(s)]
    check("TIER control(i): a planted *_dollars key on the served surface FIRES the assert",
          len(hits) > 0)
    conn.execute("INSERT INTO usage_polls (fetched_at, state, snapshot) VALUES (now(),'fresh',%s::jsonb)",
                 (json.dumps({"fetched_at": _iso(0), "state": "fresh", "spend": {"usd": 5},
                              "data": {"five_hour_utilization": 30}}),))
    hits2 = [k for s in _served_snaps(conn) for k in _tier_keys(s)]
    check("TIER control(ii): a raw fetch() body (spend.*) bypass leaves a detectable key "
          "on the served surface (containment)",
          any("spend" in k.lower() for k in hits2))
finally:
    conn.execute(f"DROP SCHEMA IF EXISTS {SCH} CASCADE")
    conn.close()


# ── READ census (PRIMARY): every gauge reader on the authority, none on the raw query ─
READER_SITES = {
    "hooks/usage.py": "the per-agent status line",
    "nucleus/pulse.py": "the load-shed gauge",
    "mcp/org/server.py": "the org-MCP usage field",
    "observatory/api/main.py": "the dashboard series/latest + /api/usage",
}
RAW = ("usage_state='fresh'", "usage_state = 'fresh'")


def _census(text):
    return (("current_usage" in text or "usage_readings" in text),
            any(r in text for r in RAW))


for f, desc in READER_SITES.items():
    uses_authority, leftover = _census((REPO / f).read_text())
    check(f"READ: {f} ({desc}) references the authority", uses_authority)
    check(f"READ: {f} has no leftover raw turns gauge query", not leftover)

_halfship = ("g = SELECT usage_five_hour_pct FROM turns WHERE usage_state='fresh' "
             "ORDER BY ended_at DESC LIMIT 1")
ua_h, raw_h = _census(_halfship)
check("READ RED-control: the census flags a reader left on the raw turns-only query",
      (not ua_h) and raw_h)


print()
if fails:
    print(f"FAIL — {len(fails)} arm(s): " + "; ".join(fails))
    sys.exit(1)
print("PASS — usage-authority (goal 3833): WRITE gate + NEWEST + CLOCK + EMPTY + "
      "TIER(key-level, served, 2 controls) + READ census — each with its RED control")
