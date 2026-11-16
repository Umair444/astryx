#!/usr/bin/env python3
"""ASTRYX · energy — how tired the org is (owner 11-15: "nothing should be a switch. humans don't know what 60% is,
they get tired … the limit resets tomorrow, so the energy is good … at night people ask little, so an agent can do its
own stuff").

ONE NUMBER, FELT BY EVERYONE, AND NO THRESHOLD ANYWHERE:

    tired = what the org will need before a window resets / what is left in that window

  0    everything left is spare: it is lost at the reset, so one's own work costs nothing
  1    all of it is spoken for
  >1   at the usual pace the window runs out before it resets

NEED is a forecast, not a level: the org's usual burn in the hours between now and the reset (by hour of the day, over
the last DAYS, self-started thinking left out), times the RATE at which tokens move the gauge (learned from the gauge's
own history, so nobody sets it). There are two windows (the 5 hours, the week); the tighter one is how the org feels.
A quiet night, or a week about to reset with most of it unused, reads as rested without anyone saying so.

READERS bend with it, they never switch on it: `ease(tired, payback)` is the one curve. Work that gives energy back
(payback) keeps its pull when the org is tired; curiosity that gives none fades. That is how scarcity teaches: a tired
org is drawn to its own waste.

The slow half (the hourly profile, the rate, each agent's usual turn) is LEARNED hourly and kept in one row, so the
per-prompt reader does arithmetic on one row and one gauge read, never an aggregate. A missing reading is unknown,
never rested.
"""
from __future__ import annotations
if not __package__:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))
from astryx import orgs, paths  # noqa: E402

import json
import math
import re
from datetime import datetime, timedelta, timezone

DAYS = 14                     # the history the forecast and the rate are learned from
STEEP = 3.0                   # how fast pull fades with tiredness (the one constant of the curve)
STALE_H = 6                   # a gauge reading older than this is no reading (unknown, never rested)
THINK = 300_000               # a think's cost before any has been measured (billable tokens)
WINDOWS = (("h5", "five_hour", 5.0), ("d7", "seven_day", 168.0))
BILL = ("COALESCE((raw_payload->'usage'->>'billable_equiv_in')::bigint, (tokens_in*0.12)::bigint + tokens_out)")


def _t() -> str:
    key = orgs.here(paths.estate(__file__)) or "astryx"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", key):
        raise SystemExit(f"energy: odd org key {key!r}")
    return f'store."{key}__energy_pace"'


def _row(c, sql, args=()):
    r = c.execute(sql, args).fetchone()
    return (list(r.values()) if isinstance(r, dict) else list(r)) if r else None


def _rows(c, sql, args=()):
    return [list(r.values()) if isinstance(r, dict) else list(r) for r in c.execute(sql, args).fetchall()]


def ease(tired: float, payback: float = 0.0) -> float:
    """How much of its pull a piece of self-started work keeps at this tiredness: 1 when rested, fading smoothly, and
    fading slower the more energy the work would give back (payback = what it burns a week, in thinks)."""
    return math.exp(-STEEP * max(0.0, tired) / (1.0 + max(0.0, payback)))


def learn(c) -> dict:
    """The slow half, from the org's own history: tokens by hour of the day (UTC, per day, without thinking it started
    itself), the gauge points one token moves in each window, a think's usual cost, each agent's usual turn. Kept in one row."""
    hourly = [0.0] * 24
    span = _row(c, f"SELECT greatest(extract(epoch FROM now() - min(started_at)) / 86400.0, 1.0)::float FROM turns "
                   f"WHERE started_at > now() - make_interval(days => {DAYS})")
    days = min(float(DAYS), (span or [1.0])[0] or 1.0)
    for h, tok in _rows(c, f"""SELECT extract(hour FROM t.started_at AT TIME ZONE 'UTC')::int, sum({BILL})::float
            FROM turns t LEFT JOIN messages m ON m.id = t.input_msg_id
            WHERE t.started_at > now() - make_interval(days => {DAYS}) AND m.thread IS DISTINCT FROM 'mind' GROUP BY 1"""):
        hourly[int(h)] = float(tok or 0) / days
    total = (_row(c, f"SELECT coalesce(sum({BILL}), 0)::float FROM turns WHERE ended_at > now() - make_interval(days => {DAYS})") or [0.0])[0]
    rate = {}
    for key, col, _h in WINDOWS:
        moved = (_row(c, f"""SELECT coalesce(sum(greatest(p - lp, 0)), 0)::float FROM (
                SELECT usage_{col}_pct AS p, lag(usage_{col}_pct) OVER (ORDER BY ended_at) AS lp FROM turns
                WHERE ended_at > now() - make_interval(days => {DAYS}) AND usage_{col}_pct IS NOT NULL) x""") or [0.0])[0]
        rate[key] = moved / total if total and moved else None
    think = (_row(c, f"""SELECT avg({BILL})::float FROM turns t JOIN messages m ON m.id = t.input_msg_id
                         WHERE m.thread = 'mind' AND t.started_at > now() - make_interval(days => {DAYS})""") or [None])[0]
    usual = {a: float(v) for a, v in _rows(c, f"""SELECT agent, percentile_cont(0.5) WITHIN GROUP (ORDER BY {BILL})::float
            FROM turns WHERE started_at > now() - interval '7 days' GROUP BY 1 HAVING count(*) >= 5""") if v}
    pace = {"at": datetime.now(timezone.utc).isoformat(), "hourly": hourly, "rate": rate, "think": think or THINK, "usual": usual}
    c.execute(f"CREATE TABLE IF NOT EXISTS {_t()} (id int PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(), body jsonb NOT NULL)")
    c.execute(f"INSERT INTO {_t()} (id, body) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET at = now(), body = EXCLUDED.body",
              (json.dumps(pace),))
    return pace


def pace(c) -> dict | None:
    """The kept row, or None before the first learn (one row read: cheap enough for every prompt)."""
    try:
        r = _row(c, f"SELECT body FROM {_t()} WHERE id = 1")
    except Exception:  # noqa: BLE001  the table isn't there before the first learn
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None
    return (r[0] if isinstance(r[0], dict) else json.loads(r[0])) if r else None


def _when(s) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def forecast(hourly: list, start: datetime, end: datetime) -> float:
    """The tokens the org usually burns between two moments (the hourly profile, part hours counted in part)."""
    tok, t = 0.0, start
    while t < end:
        nxt = min(end, (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
        tok += hourly[t.astimezone(timezone.utc).hour] * (nxt - t).total_seconds() / 3600.0
        t = nxt
    return tok


def window(used, resets, hours: float, rate, hourly: list, now: datetime) -> dict | None:
    """One window's feeling. PURE. `used` percent, `resets` when (None or past: the window isn't running, a new one
    of `hours` starts with the next call)."""
    if used is None or rate is None:
        return None
    end = _when(resets)
    if end is None or end <= now:
        end, used = now + timedelta(hours=hours), (0.0 if end is not None else float(used))
    left = max(0.0, 100.0 - float(used))
    need = forecast(hourly, now, end) * rate
    out = {"used": float(used), "left": left, "need": round(need, 1), "spare": round(left - need, 1),
           "resets_at": end.isoformat(), "tired": round(need / left, 3) if left > 0 else 99.0, "dry_at": None}
    if need > left:                      # it runs out before the reset: when, at the usual pace
        t, acc = now, 0.0
        while t < end:
            step = hourly[t.astimezone(timezone.utc).hour] * rate
            if step > 0 and acc + step >= left:
                out["dry_at"] = (t + timedelta(hours=(left - acc) / step)).isoformat()
                break
            acc, t = acc + step, t + timedelta(hours=1)
    return out


def _clock(iso: str, now: datetime) -> str:
    d = _when(iso).astimezone()
    return d.strftime("%H:%M") if d.date() == now.astimezone().date() else d.strftime("%a %H:%M")


def word(tired: float) -> str:
    """A word for people (a label on a continuous feeling; nothing acts on it)."""
    return "rested" if tired < 0.35 else "steady" if tired < 0.7 else "tiring" if tired < 1.0 else "tired"


def feel(c, now: datetime | None = None, relearn_after_h: float | None = 1.0, credential: str | None = None) -> dict:
    """How the org feels now: {known, tired, word, binding, windows, say, think_pct}. `relearn_after_h=None` never
    learns (the per-prompt reader); otherwise a kept row older than that is learned again first. `credential`: how a
    vault LOGIN feels, from its own reading (the pace is the org's: its agents' hours look like the org's day)."""
    now = now or datetime.now(timezone.utc)
    p = pace(c)
    if relearn_after_h is not None and (p is None or (now - _when(p["at"])).total_seconds() > relearn_after_h * 3600):
        p = learn(c)
    # a vault login's own reading (its limits are its own, owner 11-16), else the org's: current_usage
    g = _row(c, "SELECT five_hour_pct, seven_day_pct, five_hour_reset, seven_day_reset, "
                "extract(epoch FROM now() - fetched_at)::float FROM usage_readings WHERE state = 'fresh' AND credential = %s "
                "ORDER BY fetched_at DESC LIMIT 1", (credential,)) if credential else \
        _row(c, "SELECT five_hour_pct, seven_day_pct, five_hour_reset, seven_day_reset, age_seconds FROM current_usage")
    if g and g[4] is not None and float(g[4]) > STALE_H * 3600:   # an old reading says nothing of now
        g = None
    if not p or not g:
        return {"known": False, "say": "energy unknown: no reading of the limits yet"}
    ws = {}
    for (key, _col, hours), used, resets in zip(WINDOWS, (g[0], g[1]), (g[2], g[3])):
        w = window(used, resets, hours, p["rate"].get(key), p["hourly"], now)
        if w:
            ws[key] = w
    if not ws:
        return {"known": False, "say": "energy unknown: no reading of the limits yet"}
    binding = max(ws, key=lambda k: ws[k]["tired"])
    b, name = ws[binding], {"h5": "the 5-hour window", "d7": "the week"}[binding]
    tired = b["tired"]
    if b["left"] <= 0:
        fact = f"{name} is used up until {_clock(b['resets_at'], now)}"
    elif b["dry_at"]:
        fact = (f"at the usual pace {name} runs out around {_clock(b['dry_at'], now)}, "
                f"before its reset at {_clock(b['resets_at'], now)}")
    else:
        fact = (f"{name}: {b['left']:.0f}% left, about {b['need']:.0f}% usually needed before the reset at "
                f"{_clock(b['resets_at'], now)}, so about {b['spare']:.0f}% would go unused")
    w = "spent" if b["left"] <= 0 else word(tired)
    # `fact` is what every prompt carries: the reading with no verdict word (owner 08-21: numbers, no advice; medic
    # 12281: a word injected unread into every prompt steers the whole fleet). `say` adds the word, for people.
    return {"known": True, "tired": tired, "word": w, "binding": binding,
            "windows": ws, "say": f"{w} · {fact}", "fact": fact, "think": p.get("think") or THINK,
            "think_pct": {k: round((p.get("think") or THINK) * p["rate"][k], 2) for k in ws}, "learned_at": p["at"],
            "hourly": p["hourly"], "rate": p["rate"], "usual": p.get("usual") or {}}


def _share(p: dict, tokens: float) -> str:
    wk = (p.get("rate") or {}).get("d7")
    return f", {tokens * wk:.1f}% of the week" if wk and tokens * wk >= 0.05 else ""


def mine(p: dict | None, agent: str, last_tokens) -> str:
    """An agent's own last turn against its usual, said only when it was at least twice it (a fact, never advice).
    `p` is the kept pace or a feeling: both carry `usual` and `rate`."""
    usual = ((p or {}).get("usual") or {}).get(agent)
    if not usual or not last_tokens or last_tokens < 2 * usual:
        return ""
    return f"your last turn took {last_tokens / usual:.0f}× your usual{_share(p, last_tokens)}"


def effort(transcript: str, tail: int = 1_048_576) -> tuple[float, float]:
    """THIS turn so far, and before its newest model call: the billable tokens of the turn's model calls, read from
    the transcript's tail (from the last prompt that wasn't a tool result). A lower bound when the turn began before
    the tail. Weights as the Stop hook's (cache write 1.25, cache read 0.1); output left out, as there."""
    import os
    total, last, seen = 0.0, 0.0, set()
    with open(transcript, "rb") as fh:
        size = os.path.getsize(transcript)
        if size > tail:
            fh.seek(-tail, os.SEEK_END)
        lines = fh.read().decode(errors="replace").splitlines()
    for ln in lines:
        try:
            o = json.loads(ln)
            m = o.get("message") or {}
        except (json.JSONDecodeError, AttributeError):
            continue
        if o.get("type") == "user" and not o.get("isSidechain"):
            body = m.get("content")
            if isinstance(body, str) or not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in body or []):
                total, last, seen = 0.0, 0.0, set()          # a prompt: the turn starts here
            continue
        u = m.get("usage")
        if not u or o.get("isSidechain") or m.get("model") == "<synthetic>" or m.get("id") in seen:
            continue
        seen.add(m.get("id"))
        last = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) * 1.25
                + u.get("cache_read_input_tokens", 0) * 0.1)
        total += last
    return total, total - last


def felt(total: float, before: float, usual) -> int:
    """Effort is felt at each DOUBLING of one's usual turn (2x, 4x, 8x …), the way fatigue is: returns the multiple
    just passed by the newest model call, or 0. Nothing stops here; the agent is told and decides."""
    if not usual or total < 2 * usual:
        return 0
    k = int(math.log2(total / usual))
    return 2 ** k if before < usual * 2 ** k else 0


def claim(d: str, x: int) -> bool:
    """ONE NOTICE PER DOUBLING PER TURN (medic 12281): `d` is the agent's own 0700 directory, one empty file per
    multiple already said this turn. True only for the first caller of a multiple above every one said: parallel tool
    calls in one model message race on an exclusive create, and a transcript tail that slid back under a doubling and
    climbed again finds its file. `rest(d)` at the turn's end forgets them."""
    import os
    try:
        if any(int(n) >= x for n in os.listdir(d) if n.isdigit()):
            return False
        os.close(os.open(os.path.join(d, str(int(x))), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
        return True
    except (OSError, ValueError):
        return False


def rest(d: str) -> None:
    """The turn ended: the next one feels its own doublings afresh."""
    import os
    try:
        for n in os.listdir(d):
            if n.isdigit():
                os.unlink(os.path.join(d, n))
    except OSError:
        pass


def during(c, agent: str, transcript: str, said: str | None = None) -> str:
    """The mid-turn line, at a doubling only: what this turn has taken against the agent's usual, and how the org
    feels. `said` is the directory claim() keeps this turn's notices in (None: no memory, the pure reading)."""
    p = pace(c)
    usual = ((p or {}).get("usual") or {}).get(agent)
    if not usual:
        return ""
    total, before = effort(transcript)
    x = felt(total, before, usual)
    if not x or (said is not None and not claim(said, x)):
        return ""
    f = feel(c, relearn_after_h=None)
    return (f"[energy] this turn has taken {x}× your usual so far{_share(p, total)}"
            + (f" · {f['fact']}" if f.get("known") else ""))


def prompt_line(c, agent: str | None, estate) -> tuple[str, bool]:
    """(the [energy] line, keep the raw gauges) for `agent`'s next prompt. An agent on a vault LOGIN feels that login;
    with no reading of it yet the line says so and the org's gauges are NOT shown as its own (medic 12481). An agent
    on the org's login reads the org's feeling; unknown keeps the raw gauges."""
    from astryx.core import vault
    cred = vault.login_of(estate, agent)[0] if agent else None
    f = feel(c, relearn_after_h=None, credential=cred)
    if cred and not f.get("known"):
        return f"[energy] {cred}: no reading of this login's limits yet", False
    if not f.get("known"):
        return "", True
    last = _row(c, f"SELECT {BILL} FROM turns WHERE agent=%s ORDER BY id DESC LIMIT 1", (agent,)) if agent else None
    return line(f, mine(f, agent, last[0] if last else None)), False


def line(f: dict, own: str = "") -> str:
    """The per-prompt line: the feeling as a fact (owner 08-21: numbers, no advice)."""
    return "[energy] " + f["fact"] + (f" · {own}" if own else "") if f.get("known") else ""


if __name__ == "__main__":
    import psycopg
    from astryx import config
    with psycopg.connect(config.dsn(paths.estate(__file__) / ".env", env_first=False), autocommit=True) as conn:
        out = feel(conn)
        out.pop("hourly", None)
        print(json.dumps(out, indent=1, default=str))
