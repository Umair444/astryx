#!/usr/bin/env python3
"""ASTRYX · the org's economy as a SYSTEM, read for the observatory (owner 11-15: "the base system should be simple;
obviously we need abstraction over it to see the stuff: the equations which drive the org, the objectives, the
simulations, the game theory, the system dynamics. Lending is simple, outrate vs disbursement, but we see a lot of
metrics in it which help us broaden our understanding").

The base is two things and stays two things: ENERGY (astryx.econ.energy: tired = need / left) and the MIND
(astryx.mind.mind: itch, pull, think, keep). Everything here is a VIEW over them and over the org's own log; it adds
no rule and nothing acts on it. One read:

  equations    the handful of formulas that drive the org, each with its live value
  objectives   the mind's three measures (keep rate, reach, heat) with what they are now
  flows        where the week's energy went, by WHO STARTED the work (people, agents asking agents, watchers, a prompt
               typed at a terminal, the org's own thinking), per day
  projection   each limit from now to its reset at the usual pace (the forecast energy.feel acts on), with what was
               actually read so far in the window
  commons      per agent: what it took from the shared energy and what it gave the others (its tools used by others,
               its ideas used by others, the asks it answered)
  trade        who asks whom (agent to agent messages): the org's internal market
  tools        the tool economy: each agent-made tool, who made it, who else calls it; GDP = distinct (tool, other
               caller) pairs (econ._v2_tool_gdp: the definition the old rollup had, computed live instead of archived)
  thermo       the org as Maxwell's demon (owner: "entropy will always increase, but we can be a Maxwell demon
               ourselves"): FLUX (energy burned), HEAT (turns that left no trace; repetition the org already feels),
               ORDER (what stays and is used: tools others call, ideas kept), K (the compressed size of the org's own
               description), the yield G = order in use / (flux x K), and COMPRESSION: the entropy of the org's actions
               (bits per tool call) and the share of its calls that go through a tool it built itself. Per day.
  game         the org as a game with few rules: how unequal the shares of the common energy are (Theil), each agent
               as a point (took, gave), and the size of the law it runs under (the fewer constraints the equilibrium
               needs, the better the design)
A missing number is absent, never 0.
"""
from __future__ import annotations
if not __package__:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))

from datetime import datetime, timedelta, timezone

from astryx.econ import energy as E
from astryx.mind import mind as M

DAYS = 7
WHO = f"""CASE WHEN m.id IS NULL THEN 'terminal' WHEN m.thread = 'mind' AND m.from_agent = 'pulse' THEN 'thinking'
               WHEN m.from_agent = 'pulse' THEN 'watchers' WHEN {M.HUMAN} THEN 'people' ELSE 'agents' END"""
STARTERS = ("people", "agents", "watchers", "terminal", "thinking")


def flows(c) -> dict:
    """The window's energy by who started the turn, in tokens, total and per day (the org's local days)."""
    rows = c.execute(f"""SELECT {WHO} AS who, (t.started_at AT TIME ZONE current_setting('TimeZone'))::date::text AS day,
            count(*) AS turns, coalesce(sum({E.BILL.replace('raw_payload', 't.raw_payload').replace('tokens_in', 't.tokens_in').replace('tokens_out', 't.tokens_out')}), 0)::float AS tokens
        FROM turns t LEFT JOIN messages m ON m.id = t.input_msg_id
        WHERE t.started_at > now() - make_interval(days => {DAYS}) GROUP BY 1, 2 ORDER BY 2""").fetchall()
    total = {w: {"tokens": 0.0, "turns": 0} for w in STARTERS}
    days: dict = {}
    for r in rows:
        total[r["who"]]["tokens"] += r["tokens"]; total[r["who"]]["turns"] += r["turns"]
        days.setdefault(r["day"], {w: 0.0 for w in STARTERS})[r["who"]] = r["tokens"]
    return {"days": DAYS, "total": total, "by_day": [{"day": d, **v} for d, v in sorted(days.items())]}


def projection(c, f: dict, now: datetime | None = None) -> dict:
    """Each limit from now to its reset at the usual pace, hour by hour (percent used), and the readings so far."""
    if not f.get("known"):
        return {}
    now = now or datetime.now(timezone.utc)
    out = {}
    for key, col, hours in E.WINDOWS:
        w = f["windows"].get(key)
        if not w:
            continue
        end, used, rate = E._when(w["resets_at"]), w["used"], f["rate"][key]
        ahead, t = [{"t": now.isoformat(), "used": round(used, 1)}], now
        while t < end:
            nxt = min(end, (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
            used += E.forecast(f["hourly"], t, nxt) * rate
            ahead.append({"t": nxt.isoformat(), "used": round(used, 1)})
            t = nxt
        if len(ahead) > 60:                                  # a week ahead: every third hour is enough to draw
            ahead = ahead[::3] + ([ahead[-1]] if (len(ahead) - 1) % 3 else [])
        start = end - timedelta(hours=hours)
        past = c.execute(f"""SELECT date_trunc('hour', ended_at) AS t, max(usage_{col}_pct)::float AS used FROM turns
            WHERE ended_at > %s AND ended_at <= %s AND usage_{col}_pct IS NOT NULL
              AND usage_{col}_reset IS NOT NULL AND abs(extract(epoch FROM (usage_{col}_reset::timestamptz - %s))) < 3600
            GROUP BY 1 ORDER BY 1""", (start, now, end)).fetchall()
        out[key] = {"resets_at": w["resets_at"], "starts_at": start.isoformat(), "dry_at": w["dry_at"],
                    "past": [{"t": r["t"].isoformat(), "used": r["used"]} for r in past], "ahead": ahead}
    return out


def market(c) -> dict:
    """The tool economy and the internal market, from the ledger and the wire."""
    import psycopg
    from astryx import config, paths
    from astryx.econ import econ as EC
    now = datetime.now(timezone.utc)
    tools, gdp, mirror = [], None, {}
    try:                                    # the ledger's readers take a plain connection (their own row shape)
        with psycopg.connect(config.dsn(paths.estate(__file__) / ".env", env_first=False)) as pc:
            rows, ok = EC._v2_tool_rows(pc, now - timedelta(days=DAYS), now)
        gdp = EC._v2_tool_gdp(rows, authorship_ok=ok)
        mirror = (EC._v2_mirror(rows, gdp).get("value") or {})
        per: dict = {}
        for rid, caller, author, _dq in EC._v2_domain(rows):
            t = per.setdefault(rid, {"tool": rid, "author": author if author not in (None, "unknown") else None, "calls": 0, "callers": set()})
            t["calls"] += 1; t["callers"].add(caller)
        for t in per.values():
            others = sorted(x for x in t["callers"] if x != t["author"])
            tools.append({"tool": t["tool"], "author": t["author"], "calls": t["calls"], "callers": len(t["callers"]), "others": others})
        tools.sort(key=lambda t: (-len(t["others"]), -t["calls"]))
    except Exception as e:  # noqa: BLE001  the market view is absent, never invented
        gdp = {"value": None, "status": f"NOT_EVALUATED: {type(e).__name__}", "coverage": 0}
    ok_agents = M._org_agents(c)
    trade = [r for r in c.execute(f"""SELECT from_agent AS "from", to_agent AS "to", count(*) AS n FROM messages m
        WHERE ts > now() - make_interval(days => {DAYS}) AND from_agent <> to_agent AND from_org = 'local'
        GROUP BY 1, 2 ORDER BY 3 DESC""").fetchall() if r["from"] in ok_agents and r["to"] in ok_agents]
    return {"gdp": gdp, "tools": tools[:40], "mirror": mirror, "trade": trade[:60], "days": DAYS}


def commons(c, mk: dict) -> list[dict]:
    """Per agent: what it took from the shared energy, and what it gave the others."""
    ok = M._org_agents(c)
    took = {r["agent"]: r for r in c.execute(f"""SELECT agent, coalesce(sum({E.BILL}), 0)::float AS tokens, count(*) AS turns
        FROM turns WHERE started_at > now() - make_interval(days => {DAYS}) GROUP BY 1""").fetchall()}
    total = sum(r["tokens"] for a, r in took.items() if a in ok) or 0.0
    ideas = {r["author"]: r for r in c.execute(f"""SELECT i.author, count(*) AS kept,
            count(*) FILTER (WHERE EXISTS (SELECT 1 FROM {M._t('use')} u WHERE u.insight_id = i.id AND u.agent <> i.author)) AS reused
        FROM {M._t('insight')} i WHERE i.state = 'alive' GROUP BY 1""").fetchall()}
    asked, answered = {}, {}
    for t in mk.get("trade", []):
        asked[t["from"]] = asked.get(t["from"], 0) + t["n"]
        answered[t["to"]] = answered.get(t["to"], 0) + t["n"]
    out = []
    for a in sorted(ok):
        tk, mi, idea = took.get(a) or {}, (mk.get("mirror") or {}).get(a) or {}, ideas.get(a) or {}
        out.append({"agent": a, "tokens": tk.get("tokens", 0.0), "turns": tk.get("turns", 0),
                    "share": round(tk.get("tokens", 0.0) / total, 4) if total else None,
                    "tools_used_by_others": mi.get("tools", 0), "tool_callers": mi.get("callers", 0),
                    "ideas_kept": idea.get("kept", 0), "ideas_reused": idea.get("reused", 0),
                    "asked": asked.get(a, 0), "was_asked": answered.get(a, 0)})
    return sorted(out, key=lambda r: -r["tokens"])


THERMO_DAYS = 14


def thermo(c, mk: dict) -> dict:
    """The demon's ledger, per local day and for the window. Heat's definition is econ.thermo's own (a turn that left
    no message, no goal and no milestone or error), kept so the series compares to itself."""
    import math
    from astryx.econ import econ as EC
    day = "(%s AT TIME ZONE current_setting('TimeZone'))::date::text"
    turns = c.execute(f"""SELECT {day % 't.ended_at'} AS day, count(*) AS turns, coalesce(sum({E.BILL}), 0)::float AS flux,
            count(*) FILTER (WHERE q.heat) AS heat_turns, coalesce(sum({E.BILL}) FILTER (WHERE q.heat), 0)::float AS heat
        FROM turns t, LATERAL (SELECT t.goal_id IS NULL
              AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.turn_id = t.id)
              AND NOT EXISTS (SELECT 1 FROM steps s WHERE s.turn_id = t.id AND s.kind IN ('milestone', 'error')) AS heat) q
        WHERE t.ended_at > now() - make_interval(days => {THERMO_DAYS}) GROUP BY 1 ORDER BY 1""").fetchall()
    calls = c.execute(f"""SELECT {day % 'ts'} AS day, split_part(content, ':', 1) AS tool, count(*) AS n,
            count(*) FILTER (WHERE meta ? 'registry_id') AS reg, max(meta->>'registry_id') AS rid
        FROM steps WHERE kind = 'tool' AND ts > now() - make_interval(days => {THERMO_DAYS}) GROUP BY 1, 2""").fetchall()
    per: dict = {}
    for r in calls:
        d = per.setdefault(r["day"], {"n": 0, "own": 0, "tools": {}})
        d["n"] += r["n"]; d["tools"][r["tool"]] = d["tools"].get(r["tool"], 0) + r["n"]
        if r["reg"] and r["rid"] and not EC._v2_core(r["rid"]):          # a tool the org built, not a core server's
            d["own"] += r["reg"]
    series = []
    for t in turns:
        d = per.get(t["day"]) or {"n": 0, "own": 0, "tools": {}}
        h = -sum((n / d["n"]) * math.log2(n / d["n"]) for n in d["tools"].values()) if d["n"] else None
        series.append({"day": t["day"], "flux": t["flux"], "turns": t["turns"], "heat": t["heat"],
                       "heat_share": round(t["heat"] / t["flux"], 4) if t["flux"] else None,
                       "calls": d["n"], "distinct_tools": len(d["tools"]), "entropy_bits": round(h, 3) if h is not None else None,
                       "own_tool_share": round(d["own"] / d["n"], 4) if d["n"] else None})
    week = series[-DAYS:]
    flux = sum(x["flux"] for x in week); heat = sum(x["heat"] for x in week)
    k = EC.k_bytes()
    order = (mk["gdp"].get("value") or 0)
    ideas = c.execute(f"SELECT count(*) AS n FROM {M._t('insight')} WHERE state = 'alive'").fetchone()["n"]
    rep = c.execute(f"SELECT coalesce(sum(n), 0) AS n FROM {M._t('itch')} WHERE state = 'open' AND kind = 'tedium' AND source <> 'noted'").fetchone()["n"]
    kmb, fm = k["compressed"] / 1e6, flux / 1e8
    return {"days": DAYS, "series": series, "flux": flux, "heat": heat, "heat_share": round(heat / flux, 4) if flux else None,
            "order": {"tool_pairs": mk["gdp"].get("value"), "ideas_alive": ideas, "repetitions_felt": int(rep)},
            "k": {"compressed": k["compressed"], "raw": k["raw"]},
            # G, the dissipative yield, on the new base: order IN USE per unit of energy per unit of self. The old one
            # divided the budgets of closed goals, which were all 0; this one divides what others actually use.
            "g": round((order + ideas) / (fm * kmb), 3) if fm and kmb and mk["gdp"].get("value") is not None else None,
            "g_units": "things in use (tool pairs + ideas) per 100M tokens per MB of self"}


def game(c, cm: list[dict]) -> dict:
    """The game's shape: inequality of the common energy's shares, and the size of the law the org runs under."""
    from astryx import paths
    from astryx.econ import econ as EC
    est = paths.estate(__file__)
    shares = [r["share"] for r in cm if r.get("share")]

    def size(globs) -> dict:
        n = b = 0
        for g in globs:
            for p in est.glob(g):
                if p.is_file():
                    n += 1; b += p.stat().st_size
        return {"files": n, "bytes": b}
    law = {"the law (local.md)": size(["local.md"]), "charters": size(["agents/**/*.md"]),
           "watchers": size(["triggers/**/*.py"]), "hooks": size(["hooks/*.py"])}
    return {"theil": EC.theil(shares) if len(shares) > 1 else None, "agents": len(cm), "law": law,
            "law_bytes": sum(v["bytes"] for v in law.values())}


def read(c) -> dict:
    """Everything the Economy tab's views draw, in one read."""
    M.ensure(c)
    f = E.feel(c)
    y = M.yields(c)
    tr = c.execute(f"""SELECT count(*) FILTER (WHERE thinks > 0) AS trials, count(*) FILTER (WHERE state = 'resolved') AS kept,
            count(*) FILTER (WHERE state = 'dropped' AND thinks > 0) AS let_go, count(*) FILTER (WHERE state = 'open') AS open,
            coalesce(sum(strength / power(2, thinks)) FILTER (WHERE state = 'open'), 0)::float AS pressure FROM {M._t('itch')}""").fetchone()
    ins = c.execute(f"""SELECT count(*) AS alive, count(*) FILTER (WHERE EXISTS (SELECT 1 FROM {M._t('use')} u
            WHERE u.insight_id = i.id AND u.agent <> i.author)) AS reused FROM {M._t('insight')} i WHERE state = 'alive'""").fetchone()
    hand = c.execute(f"SELECT count(*) AS n FROM steps WHERE kind = 'tool' AND ts > now() - make_interval(days => {M.DAYS}) AND content !~ %s", (M.BASE,)).fetchone()["n"]
    felt = c.execute(f"SELECT coalesce(sum(n), 0) AS n FROM {M._t('itch')} WHERE state = 'open' AND key LIKE 'tool:%'").fetchone()["n"]
    mk = market(c)
    cm = commons(c, mk)
    fl = flows(c)
    th = thermo(c, mk)
    week = sum(v["tokens"] for v in fl["total"].values())
    known = bool(f.get("known"))
    t = f["tired"] if known else None
    eq = [
        {"id": "tired", "name": "Tiredness", "formula": "tired = need before the reset / what is left", "value": t,
         "reads": "0 = everything left is spare. 1 = all of it is spoken for. Above 1 it runs out before the reset.",
         "parts": ({k: {"need": w["need"], "left": w["left"], "tired": w["tired"]} for k, w in f["windows"].items()} if known else None)},
        {"id": "need", "name": "Need", "formula": "need = Σ usual burn of each hour until the reset × gauge points per token", "value": None,
         "reads": "The usual burn is the org's own last 14 days by hour of day; the rate is learned from the gauge.",
         "parts": ({"points_per_million_tokens": {k: round(v * 1e6, 3) for k, v in f["rate"].items() if v}, "usual_tokens_per_day": round(sum(f["hourly"]))} if known else None)},
        {"id": "ease", "name": "Pull kept when tired", "formula": f"ease = e^(−{E.STEEP:g} × tired ÷ (1 + payback))", "value": round(E.ease(t), 3) if known else None,
         "reads": "The share of its pull a curiosity keeps right now. Work that gives energy back fades slower.",
         "parts": ({"payback 0": round(E.ease(t, 0), 3), "payback 1": round(E.ease(t, 1), 3), "payback 5": round(E.ease(t, 5), 3)} if known else None)},
        {"id": "payback", "name": "Payback", "formula": "payback = repetitions × the agent's cost of one ÷ the cost of a think", "value": None,
         "reads": "What thinking about an itch could give back, in thinks. A noted surprise or question has none.",
         "parts": ({"a think costs (tokens)": round(f["think"])} if known else None)},
        {"id": "pull", "name": "Pull", "formula": "pull = strength ÷ 2^(fruitless thinks) × ease", "value": None,
         "reads": f"An agent wakes itself when its ready itches pull {M.PRESSURE:g} or more, it is idle {M.IDLE_MIN} minutes and nobody waits on it.",
         "parts": {"bar": M.PRESSURE, "open pressure, all agents": round(tr["pressure"], 1)}},
        {"id": "yield", "name": "A sense's yield", "formula": "yield = (kept + 1) ÷ (kept + let go + 2)", "value": None,
         "reads": "Every wake is a trial of the sense that raised it. A sense that keeps failing counts for less.",
         "parts": {k: v.get("yield") for k, v in y.items()} or None},
        {"id": "wait", "name": "Back-off", "formula": f"wait = {M.REST_H} h × 2^(fruitless thinks)", "value": None,
         "reads": f"An itch that yields nothing waits twice as long each time and is let go after {M.MAX_THINKS}.", "parts": None},
    ]
    n = lambda v, d=2: "?" if v is None else f"{v:,.{d}f}"   # noqa: E731
    b = f["windows"][f["binding"]] if known else None
    p0 = 0.0
    sub = {
        "tired": f"{n(b['need'], 1)} ÷ {n(b['left'], 1)} = {n(t)}" if known else None,
        "need": (f"{sum(f['hourly']) / 1e6:,.1f}M tokens a day × {f['rate'][f['binding']] * 1e6:.2f} points per M" if known and f["rate"].get(f["binding"]) else None),
        "ease": f"e^(−{E.STEEP:g} × {n(t)} ÷ (1 + {p0:g})) = {n(E.ease(t), 3)}" if known else None,
        "payback": f"a think costs {f['think'] / 1e3:,.0f}k tokens" if known else None,
        "pull": f"open pressure {tr['pressure']:,.1f} across the org; an agent wakes at {M.PRESSURE:g}",
        "yield": ", ".join(f"{k} {v['yield']:.2f}" for k, v in y.items()) or None,
        "wait": f"{M.REST_H} h, {M.REST_H * 2} h, {M.REST_H * 4} h, then let go",
    }
    for e in eq:
        e["sub"] = sub.get(e["id"])
    kmb = th["k"]["compressed"] / 1e6
    week_turns = [x for x in th["series"][-DAYS:] if x["entropy_bits"] is not None]
    hbar = sum(x["entropy_bits"] * x["calls"] for x in week_turns) / max(1, sum(x["calls"] for x in week_turns)) if week_turns else None
    own = sum((x["own_tool_share"] or 0) * x["calls"] for x in week_turns) / max(1, sum(x["calls"] for x in week_turns)) if week_turns else None
    eq += [
        {"id": "g", "name": "G · dissipative yield", "formula": "G = order in use ÷ (flux × K)", "value": th["g"],
         "reads": "Order in use is what others actually use: tool pairs and ideas alive. Flux is the week's energy (per 100M tokens); K is the org's own compressed description (MB). Bloat divides G down; deleting raises it.",
         "sub": (f"({th['order']['tool_pairs']} + {th['order']['ideas_alive']}) ÷ ({th['flux'] / 1e8:.2f} × {kmb:.2f}) = {n(th['g'])}" if th["g"] is not None else None), "parts": th["order"]},
        {"id": "heat", "name": "Heat", "formula": "Q = energy of turns that left no trace ÷ flux", "value": th["heat_share"],
         "reads": "A turn that sent nothing, served no goal and marked no milestone or error. The demon's job is to turn heat into order.",
         "sub": (f"{th['heat'] / 1e6:,.1f}M ÷ {th['flux'] / 1e6:,.1f}M = {th['heat_share']:.1%}" if th["heat_share"] is not None else None), "parts": None},
        {"id": "entropy", "name": "Compression", "formula": "H = −Σ p(tool) log₂ p(tool)", "value": round(hbar, 3) if hbar is not None else None,
         "reads": "Bits per tool call: how spread the org's actions are. A general tool that replaces many ad-hoc calls lowers it, and raises the share of calls through tools the org built.",
         "sub": (f"{hbar:.2f} bits per call; {own:.1%} of calls through tools the org built" if hbar is not None else None), "parts": None},
    ]
    closed = (tr["kept"] or 0) + (tr["let_go"] or 0)
    objectives = [
        {"id": "keep", "name": "Keep rate", "is": "of the wakes that ended, the share that ended in a kept idea",
         "value": round(tr["kept"] / closed, 3) if closed else None, "of": f"{tr['kept']} of {closed}", "wants": "up"},
        {"id": "reach", "name": "Reach", "is": "of the ideas kept, the share another agent has used",
         "value": round(ins["reused"] / ins["alive"], 3) if ins["alive"] else None, "of": f"{ins['reused']} of {ins['alive']}", "wants": "up"},
        {"id": "heat", "name": "Heat", "is": "the share of hand tool calls that repeat something the org already feels",
         "value": round(felt / hand, 3) if hand else None, "of": f"{int(felt)} of {hand}", "wants": "down"},
        {"id": "gdp", "name": "Tool GDP", "is": "distinct pairs of an agent-made tool and another agent who called it, this week",
         "value": mk["gdp"].get("value"), "of": (f"coverage {mk['gdp'].get('coverage', 0):.0%}" if mk["gdp"].get("value") is not None else mk["gdp"].get("status", "")), "wants": "up"},
        {"id": "thinking", "name": "Thinking's share", "is": "of the week's energy, the share the org spent on thinking it started itself",
         "value": round(fl["total"]["thinking"]["tokens"] / week, 4) if week else None, "of": f"{fl['total']['thinking']['turns']} wakes", "wants": "a bound, not a goal"},
    ]
    return {"energy": {k: f.get(k) for k in ("known", "tired", "word", "say", "binding", "windows", "hourly", "rate", "think")},
            "equations": eq, "objectives": objectives, "flows": fl, "projection": projection(c, f), "market": mk,
            "commons": cm, "thermo": th, "game": game(c, cm), "mind": {"trials": tr["trials"], "kept": tr["kept"], "let_go": tr["let_go"], "open": tr["open"],
                                                "pressure": round(tr["pressure"], 1), "bar": M.PRESSURE, "steep": E.STEEP,
                                                "rest_h": M.REST_H, "max_thinks": M.MAX_THINKS}}


if __name__ == "__main__":
    import json
    with M.connect() as conn:
        out = read(conn)
    print(json.dumps(out, indent=1, default=str)[:6000])
