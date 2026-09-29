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


ECON_NEUTRAL = "[econ] between ships · no standing verdict"


def econ_mirror(conn, agent: str) -> dict | None:
    """The reader's OWN mirror from the NEWEST archived econ row — one indexed row read, cheap
    enough for every wake (a1 edge c: never aggregate in the hook). Only that row: a newest
    row below V2_MIN reads as not-yet-cut-over, never by reaching back to an older one.
    Self-scoped by construction: returns only `agent`'s entry, never the table."""
    row = _one(conn, "SELECT day::text, metrics->'v2' FROM econ ORDER BY day DESC LIMIT 1")
    if not row:
        return None
    v2 = v2_view({"v2": row[1]})
    if v2 is None:
        return {"day": row[0], "version": (row[1] or {}).get("version") if isinstance(row[1], dict)
                else None, "status": None, "coverage": None, "mine": None}
    mir = v2.get("mirror") or {}
    return {"day": row[0], "version": v2.get("version"), "status": mir.get("status"),
            "coverage": mir.get("coverage"), "mine": (mir.get("value") or {}).get(agent)}


def econ_line(rec: dict | None) -> str:
    """The per-wake [econ] line (hooks/usage.py renders this, fail-open). A SOFT ACTUATOR: it is
    injected into every prompt, so it shapes behaviour unread (a3 H2). It therefore shows ONLY
    the reader's own tools' use by OTHER agents, with its as-of day and coverage — never a
    signed net, a cross-agent rank, or another agent's name. Anything that is not a v2 mirror
    record at or above V2_MIN (None, a v1 standing dict, a v2.0 row) → the neutral token; a
    degenerate input → an explicit 'not evaluated' token, never a number."""
    if not isinstance(rec, dict) or _v2_ver(rec.get("version")) is None \
            or _v2_ver(rec.get("version")) < V2_MIN:
        return ECON_NEUTRAL
    day, status = rec.get("day") or "?", str(rec.get("status") or "")
    if not status or status.startswith("NOT_EVALUATED"):
        why = status.split(":", 1)[1].strip() if ":" in status else "no mirror in the newest row"
        return f"[econ] v2 · {day} · your tools: not evaluated ({why})"
    cov = rec.get("coverage")
    tail = (f"usage-GDP, compression=1, coverage {cov:.0%}" if isinstance(cov, (int, float))
            else "usage-GDP, compression=1") + (" · PARTIAL" if status.startswith("PARTIAL") else "")
    mine = rec.get("mine")
    if not mine:
        return f"[econ] v2 · {day} · no tool of yours was called by another agent on demand ({tail})"
    return (f"[econ] v2 · {day} · your tools: {mine['tools']} used by {mine['callers']} other "
            f"agent(s), {mine['pairs']} tool×caller pair(s) ({tail})")


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

# ── v2 SHADOW (goal 4227, S0) ────────────────────────────────────────────────────────
# The owner's tool-centered economy (2026-09-29): NO budgets. v2 is computed and archived
# BESIDE v1 at metrics['v2'] and nothing reads it until S2 cuts the readers over, so S0
# changes no behaviour. Every record is I1-shaped {value, version, coverage, status}: a
# number without its coverage cannot be displayed honestly, and an unmeasurable quantity
# is status NOT_EVALUATED with value None — never a measured 0. The v2 code path must not
# name any budget-era identifier (the oracle checks this source by AST).
# v2.1 (S2): the version gate. v2.0 rows were archived while S0's demand predicate was a
# tautology (fixed e36a66c) and the ledger counted a script NAMED in a command as called
# (fixed acfc1ea); readers take only V2_MIN and up, so nobody has to remember which days.
V2_VERSION = "v2.1"
V2_MIN = (2, 1)


def _v2_ver(v) -> tuple | None:
    """'v2.1' -> (2, 1); anything else -> None (unknown version = not readable)."""
    m = re.fullmatch(r"v(\d+)\.(\d+)", v) if isinstance(v, str) else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def v2_view(metrics) -> dict | None:
    """THE READ GATE: the v2 records of an econ metrics bundle if their version is >= V2_MIN,
    else None. Every v2 reader goes through here (economy(), the observatory, the [econ] hook);
    a caller that gets None shows v2 as not-yet-available — it never falls back to v1."""
    v2 = (metrics or {}).get("v2") if isinstance(metrics, dict) else None
    ver = _v2_ver((v2 or {}).get("version")) if isinstance(v2, dict) else None
    return v2 if ver is not None and ver >= V2_MIN else None
from nucleus.orgname import RESERVED_ORGS  # the demand predicate's authority (see _V2_DEMAND)
# a call serves REAL demand (owner edge b) only when its turn served a goal, or was woken
# by a trigger, the owner, a human chat or a federated peer. An inter-agent message alone
# does NOT qualify: messaging a peer to look used is the named gaming vector. "Outside this
# org" is `from_org NOT IN orgname.RESERVED_ORGS`, DERIVED from that authority — NOT
# `from_org IS NOT NULL`: the column DEFAULTS to 'local', so that clause was a tautology that
# qualified every peer message (a2, plan-4227 #21324; its SQL had never been executed by the
# oracle). Channel rows (whatsapp/discord/telegram) and federated orgs carry a non-reserved
# from_org, so human and federated demand qualify. Detection-grade (same-uid forgeable).
_V2_DEMAND = """(t.goal_id IS NOT NULL OR EXISTS (
        SELECT 1 FROM messages im WHERE im.id = t.input_msg_id
          AND (im.from_agent IN ('pulse','owner') OR im.from_agent LIKE 'wa-%%'
               OR im.from_org <> ALL(%s))))"""   # %s = orgname.RESERVED_ORGS (the authority)


def _v2_rec(value, coverage, status) -> dict:
    return {"value": value, "version": V2_VERSION, "coverage": coverage, "status": status}


def _v2_counted(rows) -> set:
    """The (tool, caller, author) triples tool GDP COUNTS: demand-qualified calls whose caller
    is not the tool's author. One definition, shared by _v2_tool_gdp (the value) and
    nucleus/wash_detector.py (rings over the same edges), so the two cannot drift apart."""
    return {(rid, caller, author) for rid, caller, author, dq in rows if dq and caller != author}


def _v2_tool_gdp(rows, version=V2_VERSION, authorship_ok=True) -> dict:
    """PURE core of v1-grade tool GDP. rows = (registry_id, caller, author, demand_qualified)
    per tool call. Value = distinct (tool, caller) pairs among demand-qualified calls whose
    caller is not the tool's author (self-use discounted; an 'unknown'/None author is never
    self-discounted). compression = 1, declared: savings per call enter only after the
    placebo oracle (O4) passes. coverage = the demand-qualified share of observed calls."""
    if not rows:
        return {"value": None, "version": version, "coverage": 0,
                "status": "NOT_EVALUATED: ledger absent (no meta.v-stamped registry_id calls in window)"}
    if not authorship_ok:
        return {"value": None, "version": version, "coverage": 0,
                "status": "NOT_EVALUATED: authorship unavailable (cannot discount self-use)"}
    qualified = [r for r in rows if r[3]]
    pairs = {(rid, caller) for rid, caller, _ in _v2_counted(rows)}
    # an unresolved author (None, or toolreg's literal 'unknown' — every pre-ledger file) can't
    # be self-discounted: those calls still COUNT (dropping them would under-state real use),
    # but the number is then PARTIAL and coverage is capped by the author-resolved share, so it
    # is never presented as fully self-use-discounted (a2 #21324).
    unresolved = [r for r in rows if r[2] in (None, "unknown")]
    cov = min(len(qualified) / len(rows), 1 - len(unresolved) / len(rows))
    partial = any(r[2] in (None, "unknown") for r in qualified)
    return {"value": len(pairs), "version": version, "coverage": round(cov, 4),
            "status": ("PARTIAL: some counted callers' authors unresolved (self-use not "
                       "discountable for them); compression=1 declared") if partial
                      else "OK: usage-GDP, compression=1 declared"}


def _v2_mirror(rows, tool_gdp) -> dict:
    """PURE. The [econ] mirror, per AUTHOR: their own tools' use by OTHER agents on demand —
    distinct tools, distinct callers, (tool, caller) pairs, over econ._v2_counted (the same
    edges tool GDP counts). Self-scoped: a record holds counts only, never a name. Unresolved
    authors get no entry. It inherits tool_gdp's status and coverage, so a degenerate ledger
    is NOT_EVALUATED here too (never 'nobody used your tools')."""
    if tool_gdp.get("value") is None:
        return {"value": None, "version": tool_gdp["version"], "coverage": 0,
                "status": tool_gdp["status"]}
    per: dict = {}
    for rid, caller, author in _v2_counted(rows):
        if author in (None, "unknown"):
            continue
        a = per.setdefault(author, {"tools": set(), "callers": set(), "pairs": set()})
        a["tools"].add(rid)
        a["callers"].add(caller)
        a["pairs"].add((rid, caller))
    return {"value": {k: {f: len(v[f]) for f in ("tools", "callers", "pairs")} for k, v in per.items()},
            "version": tool_gdp["version"], "coverage": tool_gdp["coverage"],
            "status": tool_gdp["status"]}


def _v2_tool_rows(conn, since, until):
    """(rows, authorship_ok) from forge's ledger (plan-4227 #21266): one kind='tool' step per
    call carrying meta.registry_id; closed turns only (turn_id back-fills at Stop). Only rows
    stamped with meta.v (forge #21604, toolreg.LEDGER_V) count: an unstamped row predates
    versioned call semantics. Strict on purpose — a remembered timestamp window for the
    interim would be the cut-over-by-memory this filter replaced; the gap under-counts."""
    calls = _all(conn, f"""
        SELECT s.meta->>'registry_id' AS rid, s.agent AS caller, {_V2_DEMAND} AS dq
        FROM steps s JOIN turns t ON t.id = s.turn_id
        WHERE s.kind = 'tool' AND s.meta ? 'registry_id' AND s.meta ? 'v'
          AND s.ts >= %s AND s.ts < %s""", (sorted(RESERVED_ORGS), since, until))
    if not calls:
        return [], True
    try:
        from nucleus import toolreg
        with conn.cursor() as cur:
            who = toolreg.authorship(cur, sorted({c["rid"] for c in calls}))
    except Exception:
        return [(c["rid"], c["caller"], None, bool(c["dq"])) for c in calls], False
    return [(c["rid"], c["caller"], (who.get(c["rid"]) or {}).get("author"), bool(c["dq"]))
            for c in calls], True


def v2(conn, since, until, k) -> dict:
    """The v2 records. Effort side = the boundary law in EFFORT units: W is the billable
    spend on turns of goals that SHIPPED in-window and went through plan quorum (approve
    rows on plan-<id>; quorum size is not stored, so this is 'went through the pipeline',
    detection-grade). Q = flux - W. G = W/(flux*K), same 1e9 scale as v1."""
    f = _one(conn, f"""
        SELECT coalesce(sum({BILL}),0)::bigint,
               coalesce(sum({BILL}) FILTER (WHERE goal_id IS NOT NULL),0)::bigint
        FROM turns WHERE ended_at >= %s AND ended_at < %s""", (since, until))
    phi, phi_goal = int(f[0]), int(f[1])
    # v2 W is EFFORT (billable tokens, a flux), not v1's budget-price: named shipped_flux at
    # its sum(BILL) binding so legend_guard reads Q = phi - shipped_flux as flux - flux.
    shipped_flux = int(_one(conn, f"""
        SELECT coalesce(sum({BILL}),0)::bigint FROM turns t JOIN goals g ON g.id = t.goal_id
        WHERE g.done_at >= %s AND g.done_at < %s
          AND EXISTS (SELECT 1 FROM messages m
                      WHERE m.thread = 'plan-'||g.id AND m.intent = 'approve')""",
        (since, until))[0])
    cov = round(phi_goal / phi, 4) if phi else None
    ok = "OK" if phi else "VACUOUS: no flux in window"
    kc = (k or {}).get("compressed")
    rows, auth_ok = _v2_tool_rows(conn, since, until)
    gdp = _v2_tool_gdp(rows, V2_VERSION, auth_ok)
    return {
        "version": V2_VERSION,
        # W counts a shipped goal's LIFETIME turns at its done_at (the boundary transfer), so
        # coverage — the in-window goal-attributed flux share — does not describe W's
        # out-of-window turns; and Q = flux - W is a DAILY TRANSFER that may be < 0 on a quiet
        # ship day. Both are conserved over windows (oracle arm 6). No reader may assume Q>=0.
        "W": _v2_rec(shipped_flux, cov, ok if not phi else
                     "OK: lifetime turns of goals shipped in-window; coverage = in-window share"),
        # Q = flux - flux: both operands are billable tokens (see shipped_flux above)
        "Q": _v2_rec(phi - shipped_flux, cov, ok if not phi else
                     "OK: daily transfer, may be <0; conserved over windows"),
        "G": _v2_rec(round(shipped_flux / (phi * kc) * 1e9, 6) if phi and kc else None, cov,
                     ok if phi and kc else "VACUOUS: flux or K unmeasured"),
        "tool_gdp": gdp,
        # the [econ] mirror (S2): each author's own tools' use by others, read one row per wake
        "mirror": _v2_mirror(rows, gdp),
    }


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
        # goal 4227 S0: the v2 shadow. Archived, read by NOTHING until S2 (v1 above untouched)
        "v2": v2(conn, since, until, k),
    }


def built_from() -> dict:
    """PROVENANCE of an archived row (a2, S2 review #21969): the tree that computed it — HEAD sha
    and whether that tree was dirty. DETECTION-grade, not a gate: v2_view trusts the stamped
    version, and a worktree or hand-run rollup can stamp any version (09-29: an unreviewed tree
    wrote a gate-passing v2.1 row). This makes such a row identifiable after the fact. TRIP:
    any econ row whose sha is not an ancestor of main → promote to a gate.
    ACCEPTED LIMIT (a2 #21986): dirty ignores UNTRACKED files (so the live tree's stray .github/
    does not mark every row dirty) — a new untracked module econ imports would not mark it
    either. Today econ imports only tracked nucleus modules."""
    import subprocess
    def git(*a):
        r = subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    try:
        sha, status = git("rev-parse", "HEAD"), git("status", "--porcelain", "--untracked-files=no")
    except Exception:                                              # noqa: BLE001
        sha, status = None, None
    return {"sha": sha, "dirty": None if status is None else bool(status),
            "grade": "detection: self-reported by the writing tree"}


def rollup(conn, day: str | None = None) -> dict:
    """Compute one day's metrics and upsert the econ row. day='YYYY-MM-DD' (default:
    yesterday, so a day is only ever archived COMPLETE)."""
    if day is None:
        day = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    since = f"{day}T00:00:00+00:00"
    until = (datetime.fromisoformat(since) + timedelta(days=1)).isoformat()
    metrics = compute(conn, since, until)
    metrics["built_from"] = built_from()
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
