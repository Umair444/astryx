#!/usr/bin/env python3
"""astryx · tokenwatch — what every body is spending, read from the substrate.

WHY (owner directive, 2026-08-15, after the fleet latched on the usage-limit modal): the
org burned its entire usage window overnight and discovered it only when fourteen bodies
froze. Usage was invisible at every level — no agent knew its own context size, nothing
watched the fleet's burn rate, and the first signal was an outage. Inspired by
Maciek-roboblog/Claude-Code-Usage-Monitor, adapted to this org's substrate: the monitor
reads one human's sessions; this reads a fleet of resident agents, each with its own
transcript, and feeds three consumers —

    hooks/usage.py                per-prompt self-knowledge (each agent sees its own load)
    triggers/memory/context_compact.py   the actuator (auto /compact near the ceiling)
    /api/economy                  the owner's dashboard (burn, cost, windows)

DATA SOURCES, all local, none new: each agent's newest transcript JSONL under
~/.claude/projects/-<home>- carries per-message `usage` (the same records the Usage
Monitor reads); the org's own `steps` table carries tokens_in/tokens_out per step with
timestamps, which is what burn rate and cost want. Nothing here calls any API.

CONTEXT SIZE is the LAST assistant message's input-side usage (fresh + cache_read +
cache_creation): that is what the model actually carried into its most recent turn, which
is the number /compact acts on. A session with no usage yet reads 0, honestly.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PROJECTS = Path.home() / ".claude" / "projects"
CONTEXT_LIMIT = 200_000          # default window; % figures are against the INFERRED one
# Not a model: the transcript stamps `<synthetic>` on records the client generated rather
# than the API (interrupts, notices). model_mix already excluded them; the meter did not,
# so a trailing synthetic — they all carry a ZERO-token usage block, 16/16 measured — was
# read as the session's current load and reported 0%, which is an actuator skipping a
# session that may be full. Excluded on both paths, and it also keeps `<synthetic>` from
# ever becoming a key in the marks map.
SYNTHETIC = "<synthetic>"
HIGHWATER = REPO / "var" / "tokenwatch_highwater.json"   # var/ is gitignored, derived state


def infer_limit(tokens: int, agent: str | None = None,
                model: str | None = None) -> int:
    """A session cannot exceed a window it does not have: an observed load past 200k is
    PROOF of the extended (1M) window. Under 200k alone, the small window is assumed —
    the safe direction for a meter that feeds a compaction actuator.

    THE MARK (memory's finding, 2026-08-15): reading only the CURRENT load gives the
    inference amnesia, and the actuator makes it self-sealing — it compacts at 80% of
    the assumed 200k, so a session it clamps can never again produce the >200k reading
    that would prove its real window. The seed was compacted at 18% of a 1M window its
    own transcript had already demonstrated (999,318 observed 08-14). So the evidence is
    max(current, mark): an observed load of N is DURABLE proof the window is >= N.

    WHAT THE MARK IS KEYED ON (abstractor-3, 2026-08-15). The mark was first keyed on the
    AGENT, with fleet-wide "rejected until config is provably uniform" (msg 9896). I
    measured that premise: config is NOT uniform (opus 5 / fable 5 / haiku 4.5 run side by
    side), so fleet-wide stays correctly rejected — but the agent is not the right key
    either, because it is only a CARRIER. A context window is a property of the MODEL, and
    every consumer already reads the model id off the very record it takes the usage from
    (7,601/7,601 usage records fleet-wide carry `message.model`). Keying on the carrier is
    wrong in both directions at once:
      - too NARROW to transfer (MEASURED, 2026-08-15): seed's 999,318 was carried by
        claude-opus-5, and steward (238,499) and abstractor-4 (234,910) exceeded 200k on
        that same id. Yet eight live agents running the identical model id on the identical
        account were still labelled 200k — forge among them at 76.1%, four points from an
        automatic /compact at 16% of the window its siblings had already demonstrated. The
        seal memory broke for seed stayed shut for everyone who had not personally earned
        proof, and the clamp is exactly what stops them earning it: the self-sealing
        property surviving its own fix, one level down.
      - too BROAD to stay valid (STRUCTURAL — no live instance; every model seed has run is
        independently proven past 200k, so nothing is currently mis-lifted): an agent that
        changes model keeps a mark earned on the old one. The mark then describes nothing
        the agent runs, and it errs toward never compacting a session with no such window.
    So with `model` known the evidence is the MODEL's mark; `agent` alone falls back to the
    per-agent mark (unchanged behaviour for callers that cannot see a model id).

    THE ASSUMPTION THIS KEY MAKES, named the way round that breaks first (memory's
    correction, msg 11062): the load-bearing clause is ONE ACCOUNT, not one id. The id is
    a PROXY for the account's window flag, so the proxy fails before the id does — the day
    the org runs two accounts, or a `[1m]`-style per-session beta on some sessions and not
    others, the flag has to join the key.

    Polarity, unchanged: a stale-high mark errs toward compacting late, which degrades to
    the pre-tokenwatch world (hooks/usage.py still warns); the amnesiac rule imposed a
    certain, recurring 5x-too-frequent compaction tax."""
    return window(tokens, agent, model)[0]


def window(tokens: int, agent: str | None = None,
           model: str | None = None) -> tuple[int, bool]:
    """(limit, proven) — the window AND whether anything ever measured it.

    WHY THE SECOND HALF EXISTS (memory's ruling, msg 11062). Keying the mark on the model
    redistributes proof; it does not create a way to EARN it. Run the arithmetic for a
    model with NO mark: the window is assumed 200k, the actuator fires at 160k, and
    unlocking needs a reading past 200k — so the only path out is overshoot between the
    fire and the compact landing at the next turn boundary. That is luck, and its most
    reliable prover is a WEDGED session, which eats the keystrokes. A 1M-window model
    joining this org tomorrow therefore starts sealed and stays sealed.

    The ruling was NOT to widen the assumption — 200k-for-unproven is the right direction
    and early compaction is a cheap failure. What was wrong is that the seal is INVISIBLE:
    a pct computed against an ASSUMED window rendered identically to one computed against
    a MEASURED one, which is the org's a-SKIP-is-not-a-PASS shape inside a meter. A guess
    and a measurement must not print the same, or every consumer downstream treats them
    the same. So the flag is derived here, at the one place that knows which happened, and
    the renderers say "assumed" when it is false.

    It is deliberately computed from the EVIDENCE and not from the limit. Today
    `limit == CONTEXT_LIMIT` happens to mean the same thing, but that equivalence is an
    accident of there being exactly two tiers; a third would silently make the shorthand
    lie. 200k is never proven — evidence proves a floor, never a ceiling."""
    evidence = tokens
    if agent:
        agent_mark = high_water(agent)      # also refreshes the model marks it scans
        evidence = max(evidence, model_water(model) if model else agent_mark)
    elif model:
        evidence = max(evidence, model_water(model))
    return (1_000_000, True) if evidence > 200_000 else (CONTEXT_LIMIT, False)


STORE_V = 2          # v2 keys the evidence by model as well as by agent


def _hw_load() -> dict:
    """The evidence store, always in current-version shape.

    A FORMAT CHANGE IS A MIGRATION: a v1 store carries per-file byte offsets and NO model
    marks, so keeping it would starve the new map forever — every proof already scanned
    would be invisible to the key that now matters (state accrued under the old rule).
    An unrecognised version is therefore discarded, which costs one full rescan and
    re-derives every mark from the transcripts themselves. What that rescan cannot
    recover is a mark whose transcript has since been DELETED; that loses evidence in the
    compact-EARLY direction, which is the cheap one and the documented fail-open."""
    try:
        store = json.loads(HIGHWATER.read_text())
        if isinstance(store, dict) and store.get("v") == STORE_V:
            store.setdefault("agents", {})
            store.setdefault("models", {})
            return store
    except Exception:
        pass
    return {"v": STORE_V, "agents": {}, "models": {}}


def _hw_save(store: dict) -> None:
    HIGHWATER.parent.mkdir(parents=True, exist_ok=True)
    tmp = HIGHWATER.with_suffix(".tmp")
    tmp.write_text(json.dumps(store))
    tmp.replace(HIGHWATER)          # atomic: concurrent readers see old or new, never torn


def high_water(agent: str) -> int:
    """The largest context load ever OBSERVED in this agent's transcripts — durable
    proof of the window it demonstrably had. Incremental so three consumers can afford
    it: per-file byte offsets live in HIGHWATER; the first call pays one full scan
    (~1.5s on a 20MB transcript), every later call reads only the appended delta, and
    only up to the last complete line (a partial tail line is re-read next call, never
    half-parsed). The agent's mark is MONOTONIC: a deleted transcript's proof outlives
    the file. Fail-open: any error returns what is already proved (worst case 0, which
    restores the pre-mark behaviour — compact early, the cheap direction)."""
    try:
        store = _hw_load()
        rec = store["agents"].get(agent) or {"max": 0, "files": {}}
        models = store["models"]
        d = _project_dir(agent)
        changed = False
        seen: set[str] = set()
        for f in (d.glob("*.jsonl") if d else ()):
            seen.add(f.name)
            try:
                size = f.stat().st_size
            except OSError:
                continue
            ent = rec["files"].get(f.name) or {"scanned": 0, "max": 0}
            start = ent["scanned"] if 0 <= ent["scanned"] <= size else 0  # shrunk → rescan
            if start >= size:
                continue
            try:
                with open(f, "rb") as fh:
                    fh.seek(start)
                    data = fh.read()
            except OSError:
                continue
            nl = data.rfind(b"\n")
            if nl < 0:
                continue
            mx = ent["max"]
            for line in data[:nl + 1].splitlines():
                try:
                    msg = json.loads(line).get("message") or {}
                except (json.JSONDecodeError, AttributeError):
                    continue
                u = msg.get("usage")
                if u and "input_tokens" in u and msg.get("model") != SYNTHETIC:
                    t = (u.get("input_tokens", 0)
                         + u.get("cache_read_input_tokens", 0)
                         + u.get("cache_creation_input_tokens", 0))
                    mx = max(mx, t)
                    # the same record proves two things: this agent carried t, and the
                    # MODEL that carried it has a window >= t. Both marks are monotonic.
                    m = msg.get("model")
                    if m and t > models.get(m, 0):
                        models[m] = t
                        changed = True
            rec["files"][f.name] = {"scanned": start + nl + 1, "max": mx}
            changed = True
        peak = max([rec["max"], *(e["max"] for e in rec["files"].values())])
        if peak != rec["max"]:
            rec["max"] = peak
            changed = True
        for name in [n for n in rec["files"] if n not in seen]:
            rec["files"].pop(name)      # file gone; its proof lives on in rec["max"]
            changed = True
        if changed:
            store["agents"][agent] = rec
            _hw_save(store)
        return rec["max"]
    except Exception:
        return 0


def model_water(model: str) -> int:
    """The largest context load ever observed on this MODEL id, across every agent that
    has run it — the durable proof of the window that id carries. Read-only: the marks
    are written by high_water()'s scan, so a caller wanting fresh evidence scans first
    (infer_limit does). Fail-open at 0, which restores the pre-mark behaviour."""
    try:
        return int(_hw_load()["models"].get(model, 0))
    except Exception:
        return 0

# $/MTok, mirrored from hooks/step.py's accounting (Opus-class default the fleet runs).
# If step.py's rates move, these move with them — one source would be better, but step.py
# keeps its rates inline for hook-startup speed; a drift here shows up only in the COST
# figure, never in tokens, and the economy panel labels cost as an estimate.
RATE_IN, RATE_OUT, RATE_CACHE_READ, RATE_CACHE_WRITE = 15.0, 75.0, 1.5, 18.75


def _project_dir(agent: str) -> Path | None:
    """The transcript dir for an agent's home. seed's home is homes/seed like the rest."""
    slug = f"-home-umair-astryx-homes-{agent}"
    p = PROJECTS / slug
    return p if p.is_dir() else None


def context_tokens(agent: str) -> dict:
    """The agent's CURRENT context load, from its newest transcript.

    Scans the newest .jsonl backwards for the last assistant message carrying `usage`.
    Reads at most the file's tail (~200KB) — a transcript can be tens of MB and this runs
    inside hooks and the pulse, so full reads are a budget violation waiting to happen.
    """
    d = _project_dir(agent)
    if not d:
        return {"agent": agent, "tokens": 0, "pct": 0.0, "found": False}
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"agent": agent, "tokens": 0, "pct": 0.0, "found": False}
    f = files[0]
    try:
        size = f.stat().st_size
        with open(f, "rb") as fh:
            if size > 262_144:
                fh.seek(-262_144, os.SEEK_END)
            tail = fh.read().decode(errors="replace")
    except OSError:
        return {"agent": agent, "tokens": 0, "pct": 0.0, "found": False}
    last = model = None
    for line in tail.splitlines():
        try:
            msg = (json.loads(line).get("message") or {})
        except (json.JSONDecodeError, AttributeError):
            continue
        u = msg.get("usage")
        if u and "input_tokens" in u and msg.get("model") != SYNTHETIC:
            last, model = u, msg.get("model")
    if not last:
        return {"agent": agent, "tokens": 0, "pct": 0.0, "found": False,
                "transcript": f.name}
    total = (last.get("input_tokens", 0)
             + last.get("cache_read_input_tokens", 0)
             + last.get("cache_creation_input_tokens", 0))
    limit, proven = window(total, agent, model)
    # `model: None` is the OBSERVABLE for the per-agent fallback firing (memory's point):
    # with 7,601/7,601 records carrying a model id that path is very nearly dead code, and
    # a fallback that never runs cannot be seen to rot. The trigger names a nonzero count.
    return {"agent": agent, "tokens": total, "limit": limit,
            "limit_proven": proven, "pct": round(100.0 * total / limit, 1),
            "found": True, "transcript": f.name, "model": model,
            "age_s": round(time.time() - f.stat().st_mtime)}


def fleet_context(agents: list[str] | None = None) -> list[dict]:
    """Context load for every live resident, roster-derived (never a hand list)."""
    if agents is None:
        from nucleus.charter import roster
        agents = roster()
    return [context_tokens(a) for a in agents]


def burn(dsn: str | None = None, hours: float = 1.0) -> dict:
    """Fleet burn from the org's own steps table: tokens and estimated cost, recent window
    plus today, per agent and total. The steps table is the truth the hooks already write;
    no transcript parsing, no API calls."""
    import psycopg
    from nucleus import people
    dsn = dsn or people._dsn()
    out = {"window_h": hours, "agents": [], "total_tokens": 0, "tokens_per_min": 0.0,
           "today_tokens": 0, "today_cost_usd": 0.0}
    if not dsn:
        return out
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT agent, COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0) "
            "FROM steps WHERE ts > now() - make_interval(mins => %s) "
            "AND agent IS NOT NULL GROUP BY agent ORDER BY 2 DESC",
            (int(hours * 60),))
        win_in = win_out = 0
        for a, tin, tout in cur.fetchall():
            out["agents"].append({"agent": a, "in": int(tin), "out": int(tout)})
            out["total_tokens"] += int(tin) + int(tout)
            win_in += int(tin)
            win_out += int(tout)
        out["cost_per_min"] = round(
            (win_in * RATE_CACHE_READ + win_out * RATE_OUT) / 1_000_000 / (hours * 60), 4)
        cur.execute(
            "SELECT COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0) "
            "FROM steps WHERE ts > date_trunc('day', now())")
        tin, tout = cur.fetchone()
        out["today_tokens"] = int(tin) + int(tout)
        # Cost is an ESTIMATE and says so where displayed: steps carry in/out but not the
        # cache split, so this prices input at the cache-read rate (the dominant class in
        # a cached fleet) — a floor, not an invoice.
        out["today_cost_usd"] = round(
            (int(tin) * RATE_CACHE_READ + int(tout) * RATE_OUT) / 1_000_000, 2)
    out["tokens_per_min"] = round(out["total_tokens"] / (hours * 60), 1)
    return out


def _segment(rows, window_h: float) -> list[dict]:
    """Fold time-ordered (ts, tin, tout) rows into Anthropic-style session blocks: a
    block OPENS at the first row after the previous block's expiry and lasts window_h
    hours from its opening row — the Usage Monitor's model, and the property the oracle
    pins: a row inside the window joins the block even after a long lull; a row one
    second past expiry opens a new one."""
    blocks: list[dict] = []
    for ts, tin, tout in rows:
        if not blocks or (ts - blocks[-1]["start"]).total_seconds() > window_h * 3600:
            blocks.append({"start": ts, "tin": 0, "tout": 0, "steps": 0})
        b = blocks[-1]
        b["tin"] += tin
        b["tout"] += tout
        b["steps"] += 1
    return blocks


def window_stats(dsn: str | None = None, window_h: float = 5.0,
                 history_days: int = 14) -> dict:
    """The Anthropic-style rolling session window, inferred from the org's own steps.

    STATED APPROXIMATION: the true window lives account-side and is unqueryable (there
    is no usage API) — so, exactly like the Usage Monitor, we infer. A window OPENS at
    the first step after the previous window expired and lasts `window_h` hours; every
    step inside it counts. Ceilings are P90 of HISTORICAL window totals — "the biggest
    window this org has survived", the Monitor's P90-limit idea — never a quota from
    Anthropic. A young org's ceiling therefore starts low and grows honest.
    """
    import math

    import psycopg
    from nucleus import people
    dsn = dsn or people._dsn()
    if not dsn:
        return {}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ts, coalesce(tokens_in,0), coalesce(tokens_out,0) FROM steps "
            "WHERE ts > now() - make_interval(days => %s) ORDER BY ts",
            (history_days,))
        rows = cur.fetchall()
    blocks = _segment(rows, window_h)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    def _cost(b):
        return (b["tin"] * RATE_CACHE_READ + b["tout"] * RATE_OUT) / 1_000_000

    cur_b = None
    if blocks and (now - blocks[-1]["start"]).total_seconds() < window_h * 3600:
        cur_b = blocks[-1]
    hist = [b for b in blocks if b is not cur_b and (b["tin"] + b["tout"]) > 0]

    def _p90(vals):
        s = sorted(vals)
        return s[max(0, math.ceil(0.9 * len(s)) - 1)] if s else 0

    out = {
        "window_h": window_h,
        "windows_measured": len(hist),
        "token_ceiling": _p90([b["tin"] + b["tout"] for b in hist]),
        "step_ceiling": _p90([b["steps"] for b in hist]),
        "cost_ceiling": round(_p90([_cost(b) for b in hist]), 2),
        "active": bool(cur_b),
    }

    # ── REPOINTED, NOT DELETED (goal #2470) ──────────────────────────────────────────
    # The docstring above states the premise this plan falsified: "the true window lives
    # account-side and is unqueryable — there is no usage API". There is one, and where it
    # answers, the ACCOUNT-level gauge is authoritative and this module's P90-of-our-own-
    # history is a guess about the same quantity.
    #
    # What moves is the CEILING, and only that. The segmentation of the org's own steps
    # above is this module's own measurement, it is not superseded by anything, and it
    # stays exactly as it was. What is superseded is PLAN-QUOTA proximity per ACCOUNT.
    # CONTEXT-WINDOW proximity per SESSION (`infer_limit`) is a different quantity on a
    # different axis and this plan does not touch it.
    #
    # EXACTLY ONE INSTRUMENT IS EVER SHOWN AND THE OUTPUT SAYS WHICH. Two gauges of one
    # fact rendered side by side is how a reader ends up believing the wrong one; `source`
    # is what lets the panel label the fallback rather than quietly serving it as fact.
    #
    # FAIL-SOFT TO INFERRED, ALWAYS. A NOT-CONFIGURED install — the modal case in the
    # population this ships to — must behave exactly as it did before this plan, so every
    # failure here is swallowed and leaves `source: inferred` standing. usage_view reads
    # var/ and never the credential, so importing it here keeps BC-2 intact.
    auth = None
    try:
        from nucleus import usage_view
        auth = usage_view.authoritative_ceiling()
    except Exception:
        auth = None
    out["source"] = "authoritative" if auth else "inferred"
    if auth:
        out["authoritative"] = auth
    else:
        # Say WHY the fallback is showing, so the panel can label it truthfully instead
        # of implying the authoritative gauge simply reads this way today.
        try:
            from nucleus import usage_view
            out["fallback_reason"] = usage_view.read_cache().get("state")
        except Exception:
            out["fallback_reason"] = "unavailable"
    if cur_b:
        reset = cur_b["start"].timestamp() + window_h * 3600
        out.update({
            "start": cur_b["start"].isoformat(),
            "reset_at": datetime.fromtimestamp(reset, timezone.utc).isoformat(),
            "remaining_s": round(reset - now.timestamp()),
            "tokens": cur_b["tin"] + cur_b["tout"],
            "steps": cur_b["steps"],
            "cost": round(_cost(cur_b), 2),
        })
        # prediction, the Monitor's headline: at the last hour's burn, when does this
        # window cross the observed ceiling — before or after the reset?
        b = burn(dsn)
        rate = b["tokens_per_min"]
        left = out["token_ceiling"] - out["tokens"]
        if rate > 0 and left > 0:
            eta = now.timestamp() + (left / rate) * 60
            out["runout_at"] = datetime.fromtimestamp(eta, timezone.utc).isoformat()
        elif out["token_ceiling"] and left <= 0:
            out["runout_at"] = now.isoformat()   # already past the observed ceiling
        else:
            out["runout_at"] = None
    return out


def _pretty_model(m: str) -> str:
    """claude-opus-4-1-20250805 -> opus 4.1 ; claude-fable-5 -> fable 5"""
    parts = m.removeprefix("claude-").split("-")
    if parts and len(parts[-1]) == 8 and parts[-1].isdigit():
        parts = parts[:-1]                       # drop the date stamp
    name = [parts[0]] if parts else []
    ver = ".".join(p for p in parts[1:] if p.isdigit())
    return " ".join(name + ([ver] if ver else [])) or m


def model_mix(agents: list[str] | None = None) -> list[dict]:
    """Which models the fleet is actually generating with, weighted by OUTPUT tokens,
    from the same transcript tails context_tokens reads. A tail is a RECENT sample by
    construction (the last ~256KB per agent), and the result says so via 'sample'."""
    if agents is None:
        from nucleus.charter import roster
        agents = roster()
    weight: dict[str, int] = {}
    records = 0
    for a in agents:
        d = _project_dir(a)
        if not d:
            continue
        files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            continue
        try:
            size = files[0].stat().st_size
            with open(files[0], "rb") as fh:
                if size > 262_144:
                    fh.seek(-262_144, os.SEEK_END)
                tail = fh.read().decode(errors="replace")
        except OSError:
            continue
        for line in tail.splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message") or {}
            u = msg.get("usage")
            m = msg.get("model")
            if not (u and m) or m == "<synthetic>":
                continue
            records += 1
            weight[m] = weight.get(m, 0) + u.get("output_tokens", 0) + 1
    total = sum(weight.values()) or 1
    return sorted(
        ({"model": _pretty_model(m), "share": round(100.0 * w / total, 1),
          "sample": records} for m, w in weight.items()),
        key=lambda r: -r["share"])


def live_sessions() -> set[str]:
    """Agents with a live tmux body — the only ones a /compact can reach."""
    try:
        r = subprocess.run(["tmux", "ls", "-F", "#S"], capture_output=True,
                           text=True, timeout=10)
        return {s[3:] for s in r.stdout.split() if s.startswith("ax-")}
    except Exception:
        return set()


def send_compact(agent: str) -> bool:
    """Queue /compact into an agent's session. OWNER-DIRECTED EXCEPTION to the wire-only
    law (2026-08-15, explicit): maintenance keystrokes — the literal string '/compact',
    nothing else — may enter a pane, because context hygiene is substrate maintenance,
    not communication, and the wire cannot reach a session's OWN context size. Any wider
    use of send-keys remains forbidden."""
    try:
        subprocess.run(["tmux", "send-keys", "-t", f"ax-{agent}", "/compact", "Enter"],
                       capture_output=True, timeout=10, check=True)
        return True
    except Exception:
        return False


def main() -> int:
    rows = sorted(fleet_context(), key=lambda r: -r["tokens"])
    print(f"  {'agent':<14} {'context':>9} {'%':>6}")
    for r in rows:
        mark = "  <- near ceiling" if r["pct"] >= 70 else ""
        print(f"  {r['agent']:<14} {r['tokens']:>9,} {r['pct']:>5.1f}%{mark}")
    b = burn()
    print(f"\n  burn: {b['tokens_per_min']}/min (last {b['window_h']}h) · "
          f"today {b['today_tokens']:,} tokens ≈ ${b['today_cost_usd']} (floor estimate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
