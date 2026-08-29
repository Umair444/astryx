#!/usr/bin/env python3
"""ASTRYX · econ — the org as a dissipative structure, measured (owner design, 2026-08-22).

Astryx is a communication system that works because of the economic principles in its core.
This module is the ONE implementation of those equations — the observatory renders them and
the steward's rollup trigger archives them, both through here, so the math can never fork.

THE LAW (one functional, everything else is a projection of it):

    G = W / (Φ · K)        value-tokens earned, per token burned, per byte of self

  Φ  flux     Σ billable tokens burned in the window (turns.usage.billable_equiv_in)
  W  work     Σ budgets of goals VERIFIED in the window (goals.done_at) — value enters the
              economy at this boundary (Baum's conservation law). ATTRIBUTION-GRADE, NOT
              tamper-proof: done_at is auto-stamped on the shipped/done transition, but a
              genesis superuser forges it (a direct UPDATE mints W with no work), and this W is
              also MATERIALIZED into econ.metrics, a second forgeable surface. funded_by NAMES
              each mint's funder. "nothing internal can mint it" is the GOAL; the guarantee
              needs the NOSUPERUSER perimeter over the whole W-bearing set (done_at + this
              rollup + turns.agent + messages/quorum) — deferred, goal 3499.
  K  self     compressed size of the org's own description (genome + charters + triggers +
              sensors) — ABSOLUTE size, so bloat divides G down and deletion raises it
  Q  heat     Φ − W-attributable spend; measured two ways because they answer different
              questions: instant heat (turns with zero persistent effect) and final heat
              (spend on goals that died unverified — assignable only in hindsight)

PROVENANCE RULES (hard-won house laws):
  - a missing number is absent, never 0 — a zero is a POSITIVE CLAIM
  - every rate carries its window; every share names its denominator
  - K's definition is FROZEN (paths + zlib level 9) so the series only compares to itself
  - attribution is thread-derived (turns.goal_id); unattributed spend is named 'unattributed',
    never smeared across goals
"""
from __future__ import annotations

import json
import re
import sys
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

BILL = ("COALESCE((raw_payload->'usage'->>'billable_equiv_in')::bigint,"
        " (tokens_in*0.12)::bigint + tokens_out)")

# ── K: the org's description length ──────────────────────────────────────────────────
# FROZEN DEFINITION (change = a new series, version the key): zlib level 9 over the
# sorted concatenation of every file under these roots (the org's self-description:
# genome, minds, both nervous systems), excluding caches. homes/, var/, backups/ are
# runtime state, not description; node_modules and dist are vendored artifacts.
K_ROOTS = ("nucleus", "hooks", "channel", "observatory/api", "observatory/web/src",
           "agents", "triggers", "sensors", "mcp", "units", "bridges")
K_EXCLUDE = ("__pycache__", "node_modules", ".git", "dist", ".browser-profile")


def _k_files() -> list:
    """The K file set, in the FROZEN order (K_ROOTS order, sorted within each root). The
    concatenation order is load-bearing — it must not change or the compressed series breaks
    its own comparability. Kept separate so the fingerprint walk and the read walk agree."""
    files: list = []
    for root in K_ROOTS:
        base = REPO / root
        if not base.exists():
            continue
        if base.is_file():
            files.append(base)
        else:
            files.extend(sorted(
                p for p in base.rglob("*") if p.is_file()
                and not any(x in p.parts for x in K_EXCLUDE)))
    return files


# K is a zlib-9 pass over the whole self-description (~2MB) — cheap once a night, but the
# live dashboard now calls it per request. Cache on a (count, total-size, max-mtime)
# fingerprint: a stat-only walk is fast, and the read+compress runs ONLY when a file under
# K_ROOTS actually changed. The compressed VALUE is byte-identical to the uncached path
# (same files, same order, same level) — caching changes cost, never the number.
_K_CACHE: dict = {"fp": None, "val": None}


def k_bytes() -> dict:
    """-> {raw, compressed} bytes of the org's self-description (fingerprint-cached)."""
    files = _k_files()
    total = 0
    max_mtime = 0.0
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        total += st.st_size
        if st.st_mtime > max_mtime:
            max_mtime = st.st_mtime
    fp = (len(files), total, round(max_mtime, 3))
    if _K_CACHE["fp"] == fp and _K_CACHE["val"] is not None:
        return _K_CACHE["val"]

    chunks: list[bytes] = []
    raw = 0
    for p in files:
        try:
            b = p.read_bytes()
        except OSError:
            continue
        raw += len(b)
        chunks.append(str(p.relative_to(REPO)).encode() + b"\x00" + b)
    comp = len(zlib.compress(b"".join(chunks), 9)) if chunks else 0
    val = {"raw": raw, "compressed": comp}
    _K_CACHE["fp"] = fp
    _K_CACHE["val"] = val
    return val


# ── the window queries (all pure reads; conn is a psycopg connection) ────────────────

def _one(conn, sql, args=()):
    cur = conn.execute(sql, args)
    r = cur.fetchone()
    return r


def _all(conn, sql, args=()):
    cur = conn.execute(sql, args)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def thermo(conn, since, until) -> dict:
    """First law over the window, both heat readings. NOTE: Q is measured from FLUX
    (Φ − phi_goal_attributed), NOT Φ − W — W is a sum of budgets (a price), not flux, so
    'Φ = W + Q' is a loose shorthand; read literally it mixes bases and Q can go negative."""
    flux = _one(conn, f"""
        SELECT coalesce(sum({BILL}),0)::bigint, count(*),
               coalesce(sum({BILL}) FILTER (WHERE goal_id IS NOT NULL),0)::bigint
        FROM turns WHERE ended_at >= %s AND ended_at < %s""", (since, until))
    phi, n_turns, phi_goal = int(flux[0]), int(flux[1]), int(flux[2])
    # W = Σ budgets of goals with done_at in-window. ATTRIBUTION-grade, NOT prevention: the
    # done_at boundary is forgeable by a genesis superuser (funded_by names each mint's funder;
    # goal 3499). This value is then MATERIALIZED into econ.metrics and consumed by economy() —
    # a second W-bearing surface, equally attribution-grade.
    work = _one(conn, """
        SELECT coalesce(sum(budget_tokens),0)::bigint, count(*)
        FROM goals WHERE done_at >= %s AND done_at < %s""", (since, until))
    w, n_shipped = int(work[0]), int(work[1])
    # instant heat: a turn that left NO persistent trace — no message sent, no goal turn,
    # no milestone/error step. Pure dissipation-as-waste, knowable same-day.
    eff = _one(conn, f"""
        SELECT count(*), coalesce(sum({BILL}),0)::bigint FROM turns t
        WHERE t.ended_at >= %s AND t.ended_at < %s
          AND t.goal_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.turn_id = t.id)
          AND NOT EXISTS (SELECT 1 FROM steps s WHERE s.turn_id = t.id
                          AND s.kind IN ('milestone','error'))""", (since, until))
    n_heat, phi_heat = int(eff[0]), int(eff[1])
    return {
        "phi": phi, "turns": n_turns, "phi_goal_attributed": phi_goal,
        "W": w, "goals_shipped": n_shipped,
        "heat_instant_turns": n_heat, "heat_instant_phi": phi_heat,
        "heat_instant_frac": round(n_heat / n_turns, 4) if n_turns else None,
        "eta": round(w / phi, 6) if phi else None,      # first-law efficiency W/Φ
    }


def final_heat(conn) -> dict:
    """Spend on goals that DIED unverified (refused/hibernated>90d) — hindsight heat.
    All-time, because a goal's death date is not a window property."""
    r = _one(conn, f"""
        SELECT coalesce(sum({BILL}),0)::bigint FROM turns t JOIN goals g ON g.id=t.goal_id
        WHERE g.state='refused' OR (g.state='hibernated' AND g.ts < now()-interval '90 days')
    """)
    return {"final_heat_phi": int(r[0])}


def value_flow(conn, since, until) -> list[dict]:
    """v1 attribution: each verified budget splits across the turns of its goal,
    proportional to billable spend; each share credits its agent. First-order (one
    bounce); the Shapley upgrade slots in here without changing callers."""
    return _all(conn, f"""
        WITH shipped AS (
          SELECT id, budget_tokens FROM goals
          WHERE done_at >= %s AND done_at < %s AND budget_tokens > 0),
        spend AS (
          SELECT t.goal_id, t.agent, sum({BILL})::bigint AS cost
          FROM turns t JOIN shipped s ON s.id = t.goal_id GROUP BY 1, 2),
        tot AS (SELECT goal_id, sum(cost) AS total FROM spend GROUP BY 1)
        SELECT sp.agent,
               sum(s.budget_tokens * sp.cost / nullif(tot.total,0))::bigint AS value_earned,
               sum(sp.cost)::bigint AS spent_on_shipped
        FROM spend sp JOIN shipped s ON s.id = sp.goal_id
        JOIN tot ON tot.goal_id = sp.goal_id
        GROUP BY 1 ORDER BY 2 DESC NULLS LAST""", (since, until))


def pnl(conn, since, until) -> list[dict]:
    """Per-agent P&L: value earned (from value_flow) vs total burned in the window."""
    earned = {r["agent"]: r for r in value_flow(conn, since, until)}
    burned = _all(conn, f"""
        SELECT agent, sum({BILL})::bigint AS burned, count(*) AS turns
        FROM turns WHERE ended_at >= %s AND ended_at < %s
        GROUP BY 1 ORDER BY 2 DESC""", (since, until))
    out = []
    for b in burned:
        e = earned.get(b["agent"], {})
        v = int(e.get("value_earned") or 0)
        out.append({"agent": b["agent"], "burned": int(b["burned"]),
                    "turns": int(b["turns"]), "value_earned": v,
                    "net": v - int(b["burned"])})
    return out


def econ_standing(conn, agent: str) -> dict | None:
    """One agent's economic standing, read from the LATEST archived econ row (the nightly
    rollup) — never recomputed, so it is cheap enough to run in every agent's wake hook.
    Returns None when no econ row has been archived yet.

    FACTS ONLY, by the goal-#3407 design (16042): `priced` (is the org's W>0 this window —
    is there any standing to take at all), this agent's `net`, and its `rank` among all
    burners by net (rank 1 = most net-positive). The RENDERER decides wording; it states a
    factual position, NEVER an org verdict, and shows the neutral token while UNPRICED (W=0).
    The disambiguating fact — is a negative net expected-in-flight or genuine waste — lives
    at the agent, not here, so this returns the number and leaves the judgment to its reader."""
    row = _one(conn, "SELECT day, metrics FROM econ ORDER BY day DESC LIMIT 1")
    if not row:
        return None
    day, m = row[0], row[1] or {}
    priced = bool((m.get("thermo") or {}).get("W"))
    flows = m.get("pnl") or []
    # rank 1 = most net-positive; deterministic tiebreak by agent name so a wake is stable
    ordered = sorted(flows, key=lambda r: (-(r.get("net") or 0), r.get("agent") or ""))
    mine = next((r for r in flows if r.get("agent") == agent), None)
    rank = next((i + 1 for i, r in enumerate(ordered) if r.get("agent") == agent), None)
    return {"day": str(day), "priced": priced, "n": len(flows),
            "present": mine is not None,
            "net": (mine or {}).get("net"), "rank": rank}


def theil(shares: list[float]) -> float | None:
    """Normalized Theil T/ln(n) ∈ [0,1] — KL(share ‖ uniform), the entropic Gini."""
    import math
    xs = [s for s in shares if s and s > 0]
    n = len(xs)
    if n < 2:
        return None
    mu = sum(xs) / n
    t = sum((x / mu) * math.log(x / mu) for x in xs) / n
    return round(t / math.log(n), 4)


def productivity(conn, days=30) -> dict:
    """Supply side. Recurring triggers ARE task classes: same name = same task, fired
    daily — cost-per-fire over time is a true TFP curve. Senses are the limit case:
    a request served at code speed instead of a wake."""
    trig = _all(conn, f"""
        SELECT (regexp_match(input_prompt, '\\[trigger ([a-z0-9_.-]+)\\]'))[1] AS trigger,
               date_trunc('day', ended_at)::date::text AS day,
               avg({BILL})::bigint AS cost_per_fire, count(*) AS fires
        FROM turns
        WHERE source='trigger' AND ended_at > now() - interval '{int(days)} days'
          AND input_prompt ~ '\\[trigger '
        GROUP BY 1, 2 HAVING (regexp_match(input_prompt, '\\[trigger ([a-z0-9_.-]+)\\]'))[1]
            IS NOT NULL ORDER BY 1, 2""")
    senses = _all(conn, f"""
        SELECT split_part(content, ' ', 1) AS sense, count(*) AS calls,
               min(ts)::date::text AS first_call
        FROM steps WHERE kind='sense' AND ts > now() - interval '{int(days)} days'
        GROUP BY 1 ORDER BY 2 DESC""")
    # median wake cost = what each sense call AVOIDED costing
    med = _one(conn, f"""
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY {BILL})
        FROM turns WHERE ended_at > now() - interval '{int(days)} days'""")
    median_wake = int(med[0]) if med and med[0] else None
    for s in senses:
        s["calls"] = int(s["calls"])
        s["saved_est"] = s["calls"] * median_wake if median_wake else None
    return {"trigger_tfp": trig, "senses": senses, "median_wake_cost": median_wake,
            "window_days": days}


def trigger_roi(conn, days=30) -> list[dict]:
    """The demand half of the trigger economy: what did each trigger's wakes LEAD TO,
    minus what its fires cost. Firing is production, not sales — a cron line proves
    nothing — so value is traced from the wake to the boundary, two hops:

      hop 1: the wake turn itself carries goal_id (a plan-thread nudge)
      hop 2: the wake turn SENT messages into a goal thread (messages.turn_id -> thread)

    and only goals that SHIPPED (done_at set) count, at their budget, shared equally
    among the distinct wake-turns that touched them (first-order attribution, stated:
    no Shapley, no deeper causality — a trigger that starts a chain three turns long
    is under-credited today, which errs toward killing triggers LATE, the safe
    direction, because the decay actuator also requires premium=0).

    A guard's ROI is structurally <= 0 (its value is disasters that did not happen);
    guards survive via triggers.premium, never via this number."""
    return _all(conn, f"""
        WITH wakes AS (
          SELECT t.id, t.agent,
                 (regexp_match(t.input_prompt, '\\[trigger ([a-z0-9_.-]+)\\]'))[1] AS trig,
                 {BILL} AS cost, t.goal_id
          FROM turns t
          WHERE t.source='trigger' AND t.input_prompt ~ '\\[trigger '
            AND t.ended_at > now() - interval '{int(days)} days'),
        touched AS (                       -- (wake turn, goal) pairs, both hops, deduped
          SELECT DISTINCT w.id AS turn_id, w.agent, w.trig, g.id AS goal_id,
                 g.budget_tokens
          FROM wakes w
          JOIN LATERAL (
            SELECT w.goal_id AS gid
            UNION
            SELECT (regexp_match(m.thread, '^(?:plan|goal)-(\\d+)$'))[1]::bigint
            FROM messages m WHERE m.turn_id = w.id
              AND m.thread ~ '^(?:plan|goal)-\\d+$'
          ) hops ON hops.gid IS NOT NULL
          JOIN goals g ON g.id = hops.gid AND g.done_at IS NOT NULL
                       AND g.budget_tokens > 0),
        credit AS (                        -- a shipped budget splits over its wake-turns
          SELECT agent, trig,
                 sum(budget_tokens / cnt)::bigint AS value_reached
          FROM (SELECT t.*, count(*) OVER (PARTITION BY goal_id) AS cnt
                FROM touched t) x
          GROUP BY 1, 2)
        SELECT w.agent, w.trig AS trigger, count(*) AS fires,
               sum(w.cost)::bigint AS cost,
               coalesce(max(c.value_reached), 0)::bigint AS value_reached,
               (coalesce(max(c.value_reached), 0) - sum(w.cost))::bigint AS roi
        FROM wakes w
        LEFT JOIN credit c ON c.agent = w.agent AND c.trig = w.trig
        WHERE w.trig IS NOT NULL
        GROUP BY 1, 2 ORDER BY roi ASC""")


def integrity(conn, since, until) -> dict:
    """The Goodhart panel: every metric's exploit, with its detector. A detector that
    cannot fire is decoration — each one names its denominator."""
    # budget CPI: budget per shipped goal, this window vs all history before it
    cpi = _one(conn, """
        SELECT (SELECT avg(budget_tokens) FROM goals
                WHERE done_at >= %s AND done_at < %s AND budget_tokens>0),
               (SELECT avg(budget_tokens) FROM goals
                WHERE done_at < %s AND budget_tokens>0)""", (since, until, since))
    now_avg = float(cpi[0]) if cpi[0] is not None else None
    hist_avg = float(cpi[1]) if cpi[1] is not None else None
    # verification latency: goal open → shipped (collapsing latency = lazy gates)
    lat = _one(conn, """
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY
                 extract(epoch FROM done_at - ts)/3600)
        FROM goals WHERE done_at >= %s AND done_at < %s""", (since, until))
    # persistent-effect rate ≈ 1.0 is milestone spam, not health
    eff = _one(conn, """
        SELECT count(*) FILTER (WHERE EXISTS (SELECT 1 FROM steps s
                 WHERE s.turn_id=t.id AND s.kind='milestone'))::float
               / nullif(count(*),0)
        FROM turns t WHERE ended_at >= %s AND ended_at < %s""", (since, until))
    return {
        "budget_cpi": (round(now_avg / hist_avg, 3)
                       if now_avg and hist_avg else None),
        "verify_latency_h_median": round(float(lat[0]), 1) if lat and lat[0] else None,
        "milestone_rate": round(float(eff[0]), 4) if eff and eff[0] is not None else None,
        "unattributed_spend_note": "see thermo.phi vs phi_goal_attributed",
    }


# ── the daily rollup (steward's trigger and the CLI both land here) ──────────────────

def compute(conn, since, until) -> dict:
    """The full metrics bundle for a window — PURE (no write). Shared by rollup (which
    archives a COMPLETE day) and the live dashboard (which calls it for today-so-far,
    since=midnight, until=now, on every request). Window metrics (thermo/pnl/integrity)
    honour [since,until); the rolling ones (productivity/trigger_roi over 30d, final_heat
    all-time) are as-of-now by design and don't depend on the window bounds."""
    t = thermo(conn, since, until)
    k = k_bytes()
    flows = pnl(conn, since, until)
    burn_shares = [f["burned"] for f in flows]
    return {
        "thermo": t,
        "K": k,
        # G: None only when a DENOMINATOR is unmeasurable; a measured W=0 is a real 0.0
        # (a zero is a positive claim — and here the claim is true: nothing shipped).
        "G": (round(t["W"] / (t["phi"] * k["compressed"]) * 1e9, 6)
              if t["phi"] and k["compressed"] else None),  # ×1e9: per-GB·tok scale
        "final_heat": final_heat(conn),
        "pnl": flows,
        "theil_burn": theil(burn_shares),
        "productivity": productivity(conn),
        "trigger_roi": trigger_roi(conn),
        "integrity": integrity(conn, since, until),
    }


def rollup(conn, day: str | None = None) -> dict:
    """Compute one day's metrics and upsert the econ row. day='YYYY-MM-DD' (default:
    yesterday, so a day is only ever archived COMPLETE)."""
    if day is None:
        day = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    since = f"{day}T00:00:00+00:00"
    until = (datetime.fromisoformat(since) + timedelta(days=1)).isoformat()
    metrics = compute(conn, since, until)
    from psycopg.types.json import Jsonb
    conn.execute("INSERT INTO econ (day, metrics) VALUES (%s, %s) "
                 "ON CONFLICT (day) DO UPDATE SET metrics=EXCLUDED.metrics, "
                 "computed_at=now()", (day, Jsonb(metrics)))
    conn.commit()
    return metrics


def _dsn() -> str:
    return next(line.split("=", 1)[1].strip()
                for line in (REPO / ".env").read_text().splitlines()
                if line.startswith("ASTRYX_DSN="))


if __name__ == "__main__":
    import psycopg
    day = sys.argv[1] if len(sys.argv) > 1 else None
    with psycopg.connect(_dsn()) as conn:
        m = rollup(conn, day)
    print(json.dumps(m, indent=1, default=str))
