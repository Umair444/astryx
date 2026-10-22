#!/usr/bin/env python3
"""astryx · usage hook — every wake tells the agent what it is carrying and what the org
has left. UserPromptSubmit: stdout is injected alongside the prompt.

ONE LINE OF NUMBERS, NO ADVICE (owner ruling 2026-08-21): context load + the org's plan
gauges, and nothing else. The agent is intelligent; given "5h 99%" it will deprioritize by
itself — an appended instruction would be the org second-guessing its own minds. This is
proprioception, not supervision.

SOURCES. Context: the session's own transcript tail (the hook is handed the path; the last
usage block IS the load, accurate mid-session). Window proof + plan gauges: postgres —
turns.raw_payload->usage->context high-water proves a window floor (an observed load of N
is proof the window >= N, read from the newest 200 turns, so the proof is RECENT, not durable), and the latest fresh usage_snapshot carries the account's
5h/7d utilization written by the Stop hook. The DB is the truth; no inference engine, no
var/ state. (Replaces the tokenwatch high-water machinery, deleted the same day.)

FAIL-OPEN BY CONTRACT: any error prints what it has (or nothing) and exits 0. A meter must
never be the reason a prompt fails.
"""
import json
import os
import sys

REPO = str(__import__("pathlib").Path(__file__).resolve().parent.parent)

try:
    payload = json.load(sys.stdin)
    tp = payload.get("transcript_path", "")

    # ── context: last usage block in this session's own transcript ──────────────────
    total = 0
    if tp and os.path.isfile(tp):
        size = os.path.getsize(tp)
        with open(tp, "rb") as fh:
            if size > 262_144:
                fh.seek(-262_144, os.SEEK_END)
            tail = fh.read().decode(errors="replace")
        for line in tail.splitlines():
            try:
                msg = json.loads(line).get("message") or {}
            except (json.JSONDecodeError, AttributeError):
                continue
            u = msg.get("usage")
            if u and "input_tokens" in u and msg.get("model") != "<synthetic>":
                total = (u.get("input_tokens", 0)
                         + u.get("cache_read_input_tokens", 0)
                         + u.get("cache_creation_input_tokens", 0))

    # ── the DB: window proof (agent's context high-water) + org plan gauges ─────────
    agent = None
    slug = os.path.basename(os.path.dirname(tp)) if tp else ""
    if "-homes-" in slug:
        agent = slug.rsplit("-homes-", 1)[-1]
    plan = ""
    high = 0
    econ_line = ""
    try:
        import psycopg
        sys.path.insert(0, REPO)
        from astryx import config, paths       # the ONE resolver (plan-11324 S3a); the file only, as before
        dsn = config.dsn(paths.estate(__file__) / ".env", env_first=False)
        # every statement is capped (worst path 1s connect + 3 x 0.9s, ~3.7s of DB, plus interpreter start-up under spawn.sh's 15s cap): this runs on every prompt, for every
        # agent, and a slow DB must cost the line, never the wake (owner 10-10: the hook timed out)
        with psycopg.connect(dsn, connect_timeout=1, options="-c statement_timeout=900") as conn:
            if agent:
                # the high-water over the agent's RECENT turns: max() over all of them read every jsonb
                # payload the agent ever wrote (1.6s for seed on 10-10, growing with every turn)
                r = conn.execute(
                    "SELECT coalesce(max((raw_payload->'usage'->>'context')::bigint),0) FROM "
                    "(SELECT raw_payload FROM turns WHERE agent=%s ORDER BY id DESC LIMIT 200) t",
                    (agent,)).fetchone()
                high = int(r[0]) if r else 0
            g = conn.execute(
                "SELECT five_hour_pct, seven_day_pct, five_hour_reset "
                "FROM current_usage").fetchone()   # unified authority (goal 3833)
            if g and g[0] is not None:
                reset = str(g[2] or "")[11:16]      # HH:MM of the ISO, blank if absent
                plan = (f" · plan 5h {g[0]:.0f}%"
                        + (f" (resets {reset}Z)" if reset else "")
                        + (f" · 7d {g[1]:.0f}%" if g[1] is not None else ""))
            # ── [econ] line: the v2 MIRROR (goal 4227 S2) — this agent's OWN tools' use by
            # other agents, one precomputed econ row read (never an aggregate in the per-prompt
            # prompt budget), version-gated, no rank. Its OWN fail-open try — a meter must
            # never break the wake for every agent on the org.
            try:
                sys.path.insert(0, REPO)
                from nucleus.econ import econ_line as _render, econ_mirror
                econ_line = _render(econ_mirror(conn, agent) if agent else None)
            except Exception:
                econ_line = ""
    except Exception:
        pass

    if total:
        evidence = max(total, high)
        limit = 1_000_000 if evidence > 200_000 else 200_000
        proven = evidence > 200_000
        pct = 100.0 * total / limit
        assumed = "" if proven else "an assumed "
        print(f"[usage] context ~{total:,} tokens (~{pct:.0f}% of "
              f"{assumed}{limit // 1000}k){plan}")
    elif plan:
        print(f"[usage]{plan}")
    if econ_line:
        print(econ_line)
except Exception:
    pass
sys.exit(0)
