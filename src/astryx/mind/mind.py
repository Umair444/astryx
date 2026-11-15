#!/usr/bin/env python3
"""astryx · mind — the org's own drive: it feels, wants, thinks, keeps and recognises, with nobody asking.

Owner 11-15: "humans don't start work because someone tells them; they do it because they want to … an org which
compresses information, generates ideas, stops and thinks; not a workhorse doing stuff and resting … homeostasis,
autopoiesis." Design: homes/seed/mind/DESIGN.md. The loop, each step a function here:

  FEEL       an ITCH is something an agent's own log shows it lived through, computed, never assigned:
               tedium    a tool it keeps calling by hand; a watcher that keeps waking it for nothing; the same ask again
               surprise  something that did not go as it expected          (noted by the agent, in the moment)
               wonder    a question it asked itself                         (noted by the agent, in the moment)
  WANT       itches build PRESSURE. An agent that is fed (the org has energy, nobody is waiting on it, it is idle)
             and whose pressure is high is woken by ITS OWN strongest itch, the instances laid side by side, across
             agents. The wake is not a task: it may follow another curiosity, or nothing.
  THINK      Poincaré's cycle: prepare (the packet), incubate (free), name it in ONE thought, verify. The check is
             PowerPlay's: the idea handles the instances that raised it and breaks nothing the org already could do.
  KEEP       an INSIGHT: a name, one thought, what it is (tool | concept | method | law), where it lives, the itches
             it came from and the insights it builds on. The org hears of it (org-news); a retired one leaves an
             epitaph so it isn't thought again (SkillSmith).
  RECOGNISE  recall(words) surfaces what the org already understands at the moment of need (the tool nudge reads it).
  LIVE       homeostasis: play only when fed; fast when energy is low; an itch that yields nothing backs off, each
             fruitless think doubling the wait (Herrmann & Schmidhuber: the chance of progress falls with stagnation),
             and is dropped after MAX_THINKS.

VALUE IS INTERNAL: nothing here asks whether a human accepted anything. The org's own measures are its HEAT (how much
of its doing is hand-repetition it has already felt) and what it has understood (insights alive, used by others, built
upon). Triggers are senses: a watcher that wakes an agent for nothing is itself tedium, so the agent feels it.

Storage is the org's own store (docs/store.md): store.<org>__mind_itch / _insight / _use. No core table, no sudo.
The meter is this module run by the pulse, outside any agent's charter; agents write only notes, insights and drops.

  mind.py tick [--dry]                      feel, then let whoever wants to think wake (the pulse runs this hourly)
  mind.py me --as A                         my drive: pressure, my itches
  mind.py note --as A --kind surprise|wonder "what"
  mind.py keep --as A --name N --thought "one sentence" --kind tool|concept|method|law --lives WHERE
               [--itch 3,4] [--on 1,2] [--check "how I verified it"]
  mind.py drop --as A --itch 3 --why "…"    not worth it (the reason is kept: an epitaph)
  mind.py recall words…                     what the org already understands about this
  mind.py use --as A NAME|ID                I applied this insight
  mind.py state                             the org's mind, as JSON (the observatory's Mind page reads it)
"""
from __future__ import annotations
if not __package__:  # run by path (the tools door, the pulse): the checkout root goes first on sys.path
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.realpath(__file__))))))

import argparse
import json
import os
import re
import sys

from astryx import config, orgs, paths

DAYS = 7                      # the window an agent's feelings are read from
TOOL_N = 12                   # a tool called by hand this often in the window is tedium
SENSE_N, SENSE_EMPTY = 4, 0.7  # a watcher: this many wakes, this share of them leading to no message
ASK_N = 3                     # the same ask this many times
PRESSURE = 6.0                # an agent wakes itself above this
IDLE_MIN = 20                 # …after this many idle minutes
REST_H = 6                    # an agent thinks at most once in this many hours; an itch's wait doubles per think
MAX_THINKS = 4                # an itch that yielded nothing this many times is dropped
ENERGY_7D, ENERGY_5H = 70, 60  # the org is FED below these (percent of the token caps); above, it fasts
KINDS = ("tedium", "surprise", "wonder")
WHAT = ("tool", "concept", "method", "law")
# tools that are the medium of work, not work an agent repeats by hand
BASE = r"^(mcp__astryx__|mcp__tools__|mcp__org__|Read|Edit|Write|Bash|ToolSearch|Glob|Grep|TodoWrite|Agent|Task|WebSearch|WebFetch|ScheduleWakeup|NotebookEdit|Skill)"
HUMAN = "(m.from_agent = 'owner' OR m.from_agent LIKE 'cv-%%' OR m.from_agent LIKE 'wa-%%' OR m.from_agent LIKE 'fe-%%' OR m.from_agent LIKE 'tg-%%' OR m.from_agent LIKE 'dc-%%')"


def _estate():
    return paths.estate(__file__)


def _t(name: str) -> str:
    key = orgs.here(_estate()) or "astryx"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", key):
        raise SystemExit(f"mind: odd org key {key!r}")
    return f'store."{key}__mind_{name}"'


def connect():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(config.dsn(_estate() / ".env", env_first=False), autocommit=True, row_factory=dict_row)


def ensure(c) -> None:
    """The mind's three tables in the org's own store. Idempotent."""
    c.execute(f"""CREATE TABLE IF NOT EXISTS {_t('itch')} (
        id bigserial PRIMARY KEY, agent text NOT NULL, kind text NOT NULL CHECK (kind IN ('tedium','surprise','wonder')),
        key text NOT NULL, what text NOT NULL, evidence jsonb NOT NULL DEFAULT '[]', n int NOT NULL DEFAULT 1,
        also text[] NOT NULL DEFAULT '{{}}', strength real NOT NULL DEFAULT 1, source text NOT NULL DEFAULT 'felt',
        first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
        state text NOT NULL DEFAULT 'open' CHECK (state IN ('open','resolved','dropped')),
        thinks int NOT NULL DEFAULT 0, last_think timestamptz, insight_id bigint, why text,
        UNIQUE (agent, kind, key))""")
    c.execute(f"""CREATE TABLE IF NOT EXISTS {_t('insight')} (
        id bigserial PRIMARY KEY, name text NOT NULL UNIQUE, thought text NOT NULL,
        kind text NOT NULL CHECK (kind IN ('tool','concept','method','law')), lives text NOT NULL DEFAULT '',
        author text NOT NULL, born timestamptz NOT NULL DEFAULT now(), from_itch bigint[] NOT NULL DEFAULT '{{}}',
        builds_on bigint[] NOT NULL DEFAULT '{{}}', verified text NOT NULL DEFAULT '',
        state text NOT NULL DEFAULT 'alive' CHECK (state IN ('alive','retired')), epitaph text)""")
    c.execute(f"""CREATE TABLE IF NOT EXISTS {_t('use')} (
        insight_id bigint NOT NULL, agent text NOT NULL, ts timestamptz NOT NULL DEFAULT now(), note text NOT NULL DEFAULT '')""")


_DIGITS = re.compile(r"\d{7,}")


_TAG = re.compile(r"<[^>]{1,300}>")


def _line(s) -> str:
    """One evidence line: the words alone (a message's wrapper tags gone), flat, short, and never a long digit run
    (a customer number can't ride in)."""
    return _DIGITS.sub("N", " ".join(_TAG.sub(" ", str(s or "")).split()))[:170]


def _org_agents(c) -> set:
    """The agents whose work is org work (an agent holding the owner's personal tier is never read here)."""
    names = {r["agent"] for r in c.execute("SELECT DISTINCT agent FROM turns WHERE started_at > now() - interval '14 days'")}
    try:
        from astryx.core import tier
        return tier.content_org_agents(names)
    except Exception:  # noqa: BLE001 — no tier module on this tree: every agent
        return names


def _upsert(c, agent, kind, key, what, evidence, n, also, strength) -> None:
    from psycopg.types.json import Jsonb
    c.execute(f"""INSERT INTO {_t('itch')} (agent, kind, key, what, evidence, n, also, strength)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (agent, kind, key) DO UPDATE SET what = EXCLUDED.what, evidence = EXCLUDED.evidence, n = EXCLUDED.n,
            also = EXCLUDED.also, strength = EXCLUDED.strength, last_seen = now()
        WHERE {_t('itch')}.state = 'open'""", (agent, kind, key, what, Jsonb(evidence), n, sorted(also), strength))


def feel(c) -> dict:
    """Read each agent's own log and write what it has lived through as itches. Returns how many of each it found."""
    ensure(c)
    ok = _org_agents(c)
    found = {"tool": 0, "sense": 0, "ask": 0}
    # 1. a TOOL called by hand again and again: per agent and tool, with the asks it was doing it for, side by side
    rows = c.execute(f"""
        WITH s AS (SELECT agent, split_part(content, ':', 1) AS tool FROM steps
                   WHERE kind = 'tool' AND ts > now() - make_interval(days => {DAYS}) AND content !~ %s)
        SELECT tool, agent, count(*) AS n, 0 AS turns FROM s GROUP BY 1, 2""", (BASE,)).fetchall()
    by_tool: dict = {}
    for r in rows:
        if r["agent"] in ok:
            by_tool.setdefault(r["tool"], {})[r["agent"]] = (r["n"], r["turns"])
    # a tool MOST agents use heavily is a medium of work here (running a query, for a data org), like speech: no one
    # idea comes of "you spoke 300 times". Its tedium needs a finer sense (the shape of what was run), not this one
    active = {a for who in by_tool.values() for a in who}
    medium = {t for t, who in by_tool.items() if sum(1 for v in who.values() if v[0] >= 3) >= max(4, len(active) / 2)}
    if medium:
        c.execute(f"""UPDATE {_t('itch')} SET state = 'dropped', why = 'a medium of work here (most agents use it), not a tedium'
                      WHERE state = 'open' AND key = ANY(%s)""", ([f"tool:{t}" for t in medium],))
    for tool, who in by_tool.items():
        for agent, (n, turns) in who.items():
            if n < TOOL_N or tool in medium:
                continue
            others = {a: v[0] for a, v in who.items() if a != agent and v[0] >= 3}
            # the asks it was doing this for: each call's turn (the agent's turn open at that moment), by who asked and
            # what; its own first, then the other agents' beside them
            got = c.execute("""
                SELECT t.agent, to_char(t.started_at, 'MM-DD HH24:MI') AS at, x.calls,
                       coalesce(m.from_agent || ': ' || left(m.body, 300), left(t.input_prompt, 300)) AS line
                FROM (SELECT s.agent, count(*) AS calls,
                             (SELECT t2.id FROM turns t2 WHERE t2.agent = s.agent AND t2.started_at <= s.ts
                              ORDER BY t2.started_at DESC LIMIT 1) AS tid
                      FROM steps s WHERE s.kind = 'tool' AND s.ts > now() - make_interval(days => %s)
                        AND split_part(s.content, ':', 1) = %s AND (s.agent = %s OR s.agent = ANY(%s)) GROUP BY 1, 3) x
                JOIN turns t ON t.id = x.tid LEFT JOIN messages m ON m.id = t.input_msg_id
                WHERE coalesce(m.body, t.input_prompt, '') !~ '^\\s*<(task-notification|system-reminder|local-command)'
                ORDER BY x.calls DESC LIMIT 40""", (DAYS, tool, agent, list(others))).fetchall()
            ev = [e for e in got if e["agent"] == agent][:4] + [e for e in got if e["agent"] != agent][:3]
            short = tool.replace("mcp__", "").replace("__", ".")
            _upsert(c, agent, "tedium", f"tool:{tool}",
                    f"you called {short} by hand {n} times in {DAYS} days",
                    [{"agent": e["agent"], "at": e["at"], "calls": e["calls"], "line": _line(e["prompt"])} for e in ev],
                    n, others, round(n / DAYS * (1 + 0.5 * len(others)), 2))
            found["tool"] += 1
    # 2. a SENSE that keeps waking it for nothing: a trigger whose wakes mostly end with no message sent
    for r in c.execute(f"""
        SELECT m.to_agent AS agent, substring(m.body from '^\\[trigger ([^\\]]+)\\]') AS trig, count(*) AS n,
               count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM messages o WHERE o.turn_id = t.id)) AS empty,
               (array_agg(to_char(m.ts, 'MM-DD HH24:MI') || '  ' || left(m.body, 200) ORDER BY m.id DESC))[1:5] AS ev
        FROM messages m JOIN turns t ON t.input_msg_id = m.id
        WHERE m.from_agent = 'pulse' AND m.ts > now() - make_interval(days => {DAYS}) AND m.body LIKE '[trigger %'
        GROUP BY 1, 2""").fetchall():
        if r["agent"] in ok and r["trig"] and r["trig"] != "mind" and r["n"] >= SENSE_N and r["empty"] / r["n"] >= SENSE_EMPTY:
            _upsert(c, r["agent"], "tedium", f"sense:{r['trig']}",
                    f"your watcher {r['trig']} woke you {r['n']} times in {DAYS} days and {r['empty']} of those led to nothing you sent",
                    [{"agent": r["agent"], "line": _line(x)} for x in r["ev"]], r["n"], set(), float(r["empty"]))
            found["sense"] += 1
    # 3. the SAME ASK again: messages to an agent that open alike once numbers, dates and quoted text are blanked
    for r in c.execute(f"""
        WITH a AS (SELECT m.to_agent AS agent, m.from_agent, m.ts, m.body,
                          lower(left(regexp_replace(regexp_replace(m.body, '''[^'']*''|"[^"]*"', 'S', 'g'), '[0-9]+', 'N', 'g'), 48)) AS shape
                   FROM messages m WHERE m.ts > now() - make_interval(days => {DAYS * 2}) AND m.to_agent IS NOT NULL
                     AND m.from_agent <> 'pulse' AND coalesce(m.intent, 'chat') IN ('chat', 'task') AND length(m.body) > 30
                     AND m.body NOT LIKE '[%')
        SELECT agent, shape, count(*) AS n, array_agg(DISTINCT from_agent) AS askers,
               (array_agg(to_char(ts, 'MM-DD HH24:MI') || '  ' || from_agent || ': ' || left(body, 200) ORDER BY ts DESC))[1:6] AS ev
        FROM a GROUP BY 1, 2 HAVING count(*) >= {ASK_N}""").fetchall():
        if r["agent"] in ok:
            _upsert(c, r["agent"], "tedium", f"ask:{r['shape']}",
                    f"the same kind of ask reached you {r['n']} times in {DAYS * 2} days (from {', '.join(r['askers'][:4])})",
                    [{"agent": r["agent"], "line": _line(x)} for x in r["ev"]], r["n"], set(), float(r["n"]))
            found["ask"] += 1
    # an itch its agent no longer lives (unseen for a window) fades by itself; one thought about too often is dropped
    c.execute(f"""UPDATE {_t('itch')} SET state = 'dropped', why = 'faded: not lived again'
                  WHERE state = 'open' AND source = 'felt' AND last_seen < now() - make_interval(days => {DAYS * 2})""")
    c.execute(f"""UPDATE {_t('itch')} SET state = 'dropped', why = 'no progress after {MAX_THINKS} thinks'
                  WHERE state = 'open' AND thinks >= {MAX_THINKS}""")
    return found


def energy(c) -> dict:
    """The org's energy: the newest reading of the token caps (percent used). Fed = below both lines."""
    r = c.execute("""SELECT usage_seven_day_pct AS d7, usage_five_hour_pct AS h5 FROM turns
                     WHERE usage_seven_day_pct IS NOT NULL ORDER BY id DESC LIMIT 1""").fetchone() or {}
    d7, h5 = r.get("d7"), r.get("h5")
    return {"seven_day_pct": d7, "five_hour_pct": h5,
            "fed": d7 is not None and h5 is not None and d7 < ENERGY_7D and h5 < ENERGY_5H}


def drives(c) -> list[dict]:
    """Each agent's drive now: its pressure (its open itches, discounted by fruitless thinks), whether it is idle,
    whether a human is waiting on it, when it last thought."""
    ensure(c)
    return c.execute(f"""
        WITH p AS (SELECT agent, sum(strength / power(2, thinks)) AS pressure, count(*) AS itches,
                          max(last_think) AS last_think FROM {_t('itch')} WHERE state = 'open' GROUP BY 1),
             lt AS (SELECT agent, max(last_think) AS last_think FROM {_t('itch')} GROUP BY 1),
             t AS (SELECT agent, max(coalesce(ended_at, started_at)) AS last_end,
                          bool_or(ended_at IS NULL AND started_at > now() - interval '45 minutes') AS busy
                   FROM turns WHERE started_at > now() - interval '3 days' GROUP BY 1),
             w AS (SELECT m.to_agent AS agent, count(*) AS waiting FROM messages m
                   WHERE m.ts > now() - interval '6 hours' AND {HUMAN.replace('%%', '%')}
                     AND NOT EXISTS (SELECT 1 FROM messages r WHERE r.from_agent = m.to_agent AND r.thread = m.thread AND r.id > m.id)
                   GROUP BY 1)
        SELECT p.agent, round(p.pressure::numeric, 1)::float AS pressure, p.itches, coalesce(t.busy, false) AS busy,
               round(extract(epoch FROM now() - t.last_end) / 60)::int AS idle_min, coalesce(w.waiting, 0) AS waiting,
               round(extract(epoch FROM now() - lt.last_think) / 3600)::int AS thought_h_ago
        FROM p LEFT JOIN t USING (agent) LEFT JOIN w USING (agent) LEFT JOIN lt USING (agent)
        ORDER BY p.pressure DESC""").fetchall()


def recall(c, words: str, limit: int = 3) -> list[dict]:
    """What the org already understands about these words: living insights ranked by the words they share."""
    ensure(c)
    ws = [w for w in re.findall(r"[a-z0-9_]{3,}", (words or "").lower())][:24]
    if not ws:
        return []
    return c.execute(f"""
        SELECT id, name, thought, kind, lives, author,
               (SELECT count(*) FROM unnest(%s::text[]) w WHERE lower(name || ' ' || thought || ' ' || lives) LIKE '%%' || w || '%%') AS hit
        FROM {_t('insight')} WHERE state = 'alive' ORDER BY hit DESC, id DESC LIMIT %s""", (ws, limit)).fetchall()


def packet(c, agent: str, itch: dict) -> str:
    """The wake: the agent's own itch, its instances side by side, what the org already understands near it, and the
    freedom to do something else. Never a task."""
    ev = itch["evidence"] if isinstance(itch["evidence"], list) else json.loads(itch["evidence"] or "[]")
    lines = [f"  - {e.get('agent', agent)}{(' ' + e['at']) if e.get('at') else ''}"
             f"{(' (' + str(e['calls']) + ' calls)') if e.get('calls') else ''}: {e.get('line', '')}" for e in ev[:7]]
    also = f" {', '.join(itch['also'])} lived it too." if itch.get("also") else ""
    known = recall(c, itch["what"] + " " + " ".join(e.get("line", "") for e in ev[:3]))
    known = [k for k in known if k["hit"] >= 2]
    me = f"{sys.executable} {os.path.realpath(__file__)}"
    out = [f"[mind] Nobody is waiting on you and the org has energy. This time is yours; it is not a task.",
           "", f"Your strongest itch ({itch['kind']}, #{itch['id']}): {itch['what']}.{also}", "Side by side:", *lines]
    if known:
        out += ["", "The org already understands, nearby:",
                *[f"  - {k['name']} ({k['kind']}, by {k['author']}): {k['thought']}" for k in known]]
    out += ["",
            "Stop and look. Is there ONE idea that makes these the same thing: a tool, a concept, a method, or a rule "
            "that could be deleted? If you see it: name it in one sentence, make it real, check it against these "
            "very instances and that it breaks nothing the org could already do, then keep it:",
            f"  {me} keep --as {agent} --name \"…\" --thought \"one sentence\" --kind tool|concept|method|law --lives <path or page> --itch {itch['id']} --check \"how you verified it\"",
            "Built on an earlier insight? add --on <its id>. The org hears of what you keep.",
            f"If it isn't worth an idea, say why and let it go:  {me} drop --as {agent} --itch {itch['id']} --why \"…\"",
            f"Or follow another curiosity of your own. Anything that surprises you or that you wonder about, note it when it happens:  {me} note --as {agent} --kind surprise|wonder \"…\"",
            "You owe nobody a report."]
    return "\n".join(out)


def want(c, say=None, dry: bool = False) -> dict:
    """Let ONE agent that wants to think wake itself: fed org, idle agent, nobody waiting, pressure over the line, not
    thought within REST_H, and an itch whose back-off has passed. `say(to, body)` delivers the wake (the pulse's)."""
    e = energy(c)
    if not e["fed"]:
        return {"woke": None, "why": f"fasting: energy at {e['seven_day_pct']}% of the week, {e['five_hour_pct']}% of 5 h"}
    for d in drives(c):
        if d["busy"] or d["waiting"] or (d["idle_min"] is not None and d["idle_min"] < IDLE_MIN) or d["pressure"] < PRESSURE:
            continue
        if d["thought_h_ago"] is not None and d["thought_h_ago"] < REST_H:
            continue
        itch = c.execute(f"""SELECT * FROM {_t('itch')} WHERE agent = %s AND state = 'open'
            AND (last_think IS NULL OR last_think < now() - make_interval(hours => ({REST_H} * power(2, thinks))::int))
            ORDER BY strength / power(2, thinks) DESC LIMIT 1""", (d["agent"],)).fetchone()
        if not itch:
            continue
        body = packet(c, d["agent"], itch)
        if not dry:
            c.execute(f"UPDATE {_t('itch')} SET thinks = thinks + 1, last_think = now() WHERE id = %s", (itch["id"],))
            if say:
                say(d["agent"], body)
        return {"woke": d["agent"], "itch": itch["id"], "what": itch["what"], "body": body}
    return {"woke": None, "why": "nobody both wants to think and is free to"}


def _wake(c, to: str, body: str) -> None:
    """Deliver a wake on the wire as the pulse does (a row; the doorbell rings by itself)."""
    c.execute("INSERT INTO messages (from_agent, from_org, to_agent, intent, thread, body) VALUES ('pulse', 'local', %s, 'drive', 'mind', %s)", (to, body))


def tick(say=None, dry: bool = False) -> dict:
    with connect() as c:
        return {"felt": feel(c), **want(c, say or (lambda to, body: _wake(c, to, body)), dry)}


def _news(c, agent: str, body: str) -> None:
    """The org hears of it: one row on org-news (the fan-out carries it to every agent)."""
    c.execute("INSERT INTO messages (from_agent, from_org, to_agent, intent, thread, body) VALUES (%s, 'local', 'steward', 'milestone', 'org-news', %s)",
              (agent, body))


def keep(c, agent, name, thought, kind, lives, itches=(), on=(), check="") -> dict:
    ensure(c)
    name, thought = " ".join(name.split())[:80], " ".join(thought.split())
    if not name or not thought:
        raise SystemExit("mind: an insight needs a name and its one thought")
    if len(thought) > 300 or thought.count(". ") > 1:
        raise SystemExit("mind: say the thought in ONE sentence (under 300 characters); what can't be said in one thought isn't one yet")
    if kind not in WHAT:
        raise SystemExit(f"mind: --kind is one of {', '.join(WHAT)}")
    old = c.execute(f"SELECT id, state, epitaph FROM {_t('insight')} WHERE lower(name) = lower(%s)", (name,)).fetchone()
    if old:
        raise SystemExit(f"mind: the org already has an insight named {name!r} (#{old['id']}, {old['state']}"
                         + (f": {old['epitaph']}" if old["epitaph"] else "") + "). Build on it (--on) or name what is new.")
    r = c.execute(f"""INSERT INTO {_t('insight')} (name, thought, kind, lives, author, from_itch, builds_on, verified)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, thought, kind, lives or "", agent, list(itches), list(on), check or "")).fetchone()
    if itches:
        c.execute(f"UPDATE {_t('itch')} SET state = 'resolved', insight_id = %s WHERE id = ANY(%s) AND state = 'open'", (r["id"], list(itches)))
    _news(c, agent, f"New idea from {agent}: {name} ({kind}). {thought}" + (f" Lives at {lives}." if lives else "")
          + f" Recall it with: {sys.executable} {os.path.realpath(__file__)} recall {name.split()[0].lower()}")
    return {"kept": r["id"], "name": name}


def drop(c, agent, itch_id: int, why: str) -> dict:
    ensure(c)
    n = c.execute(f"UPDATE {_t('itch')} SET state = 'dropped', why = %s WHERE id = %s AND agent = %s AND state = 'open'",
                  (" ".join((why or "").split())[:300] or "let go", itch_id, agent)).rowcount
    return {"dropped": bool(n)}


def note(c, agent, kind, what) -> dict:
    ensure(c)
    if kind not in ("surprise", "wonder"):
        raise SystemExit("mind: you note a surprise or a wonder; tedium is read from your log")
    what = _line(what)
    if len(what) < 8:
        raise SystemExit("mind: say what it was")
    key = re.sub(r"[^a-z0-9]+", " ", what.lower())[:60]
    r = c.execute(f"""INSERT INTO {_t('itch')} (agent, kind, key, what, source, strength) VALUES (%s, %s, %s, %s, 'noted', 3)
        ON CONFLICT (agent, kind, key) DO UPDATE SET n = {_t('itch')}.n + 1, strength = {_t('itch')}.strength + 2, last_seen = now()
        RETURNING id, n""", (agent, kind, key, what)).fetchone()
    return {"itch": r["id"], "times": r["n"]}


def use(c, agent, ref, why="") -> dict:
    ensure(c)
    r = c.execute(f"SELECT id, name FROM {_t('insight')} WHERE state = 'alive' AND (id::text = %s OR lower(name) = lower(%s))", (ref, ref)).fetchone()
    if not r:
        raise SystemExit(f"mind: no living insight {ref!r}")
    c.execute(f"INSERT INTO {_t('use')} (insight_id, agent, note) VALUES (%s, %s, %s)", (r["id"], agent, _line(why)))
    return {"used": r["name"]}


def state(c) -> dict:
    """The org's mind for the observatory: energy, each agent's drive, the open itches, the insights and their lineage,
    and HEAT: the share of the window's hand tool calls that belong to a tedium the org has already felt."""
    ensure(c)
    hand = c.execute(f"SELECT count(*) AS n FROM steps WHERE kind = 'tool' AND ts > now() - make_interval(days => {DAYS}) AND content !~ %s", (BASE,)).fetchone()["n"]
    felt = c.execute(f"SELECT coalesce(sum(n), 0) AS n FROM {_t('itch')} WHERE state = 'open' AND key LIKE 'tool:%'").fetchone()["n"]
    ins = c.execute(f"""SELECT i.id, i.name, i.thought, i.kind, i.lives, i.author, i.born, i.from_itch, i.builds_on, i.verified, i.state, i.epitaph,
            (SELECT count(*) FROM {_t('use')} u WHERE u.insight_id = i.id) AS uses,
            (SELECT count(DISTINCT u.agent) FROM {_t('use')} u WHERE u.insight_id = i.id AND u.agent <> i.author) AS used_by_others,
            (SELECT count(*) FROM {_t('insight')} j WHERE i.id = ANY(j.builds_on)) AS built_upon
        FROM {_t('insight')} i ORDER BY i.id DESC LIMIT 200""").fetchall()
    itches = c.execute(f"""SELECT id, agent, kind, what, n, also, round(strength::numeric, 1)::float AS strength, state, thinks,
            last_think, why, insight_id, source, evidence FROM {_t('itch')}
        ORDER BY (state = 'open') DESC, strength / power(2, thinks) DESC LIMIT 120""").fetchall()
    return {"energy": energy(c), "drives": drives(c), "itches": itches, "insights": ins,
            "heat": {"hand_calls": hand, "felt_as_tedium": int(felt), "share": round(felt / hand, 3) if hand else 0.0, "days": DAYS},
            "rules": {"pressure": PRESSURE, "idle_min": IDLE_MIN, "rest_h": REST_H, "max_thinks": MAX_THINKS,
                      "fed_below": {"seven_day_pct": ENERGY_7D, "five_hour_pct": ENERGY_5H}}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mind", description="the org's own drive")
    sub = ap.add_subparsers(dest="cmd", required=True)
    who = lambda p: p.add_argument("--as", dest="agent", default=os.environ.get("ASTRYX_AGENT", ""))
    p = sub.add_parser("tick"); p.add_argument("--dry", action="store_true")
    p = sub.add_parser("me"); who(p)
    p = sub.add_parser("note"); who(p); p.add_argument("--kind", required=True); p.add_argument("what", nargs="+")
    p = sub.add_parser("keep"); who(p)
    for a in ("--name", "--thought", "--kind"):
        p.add_argument(a, required=True)
    p.add_argument("--lives", default=""); p.add_argument("--itch", default=""); p.add_argument("--on", default=""); p.add_argument("--check", default="")
    p = sub.add_parser("drop"); who(p); p.add_argument("--itch", type=int, required=True); p.add_argument("--why", required=True)
    p = sub.add_parser("recall"); p.add_argument("words", nargs="+")
    p = sub.add_parser("use"); who(p); p.add_argument("ref"); p.add_argument("--why", default="")
    sub.add_parser("state")
    a = ap.parse_args(argv)
    if a.cmd in ("me", "note", "keep", "drop", "use") and not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,60}", a.agent or ""):
        raise SystemExit("mind: say who you are: --as <your agent name>")
    ids = lambda s: [int(x) for x in re.findall(r"\d+", s or "")]
    with connect() as c:
        if a.cmd == "tick":
            out = {"felt": feel(c), **want(c, lambda to, body: _wake(c, to, body), a.dry)}
        elif a.cmd == "me":
            ensure(c)
            mine = c.execute(f"SELECT id, kind, what, n, also, strength, thinks FROM {_t('itch')} WHERE agent = %s AND state = 'open' ORDER BY strength / power(2, thinks) DESC LIMIT 12", (a.agent,)).fetchall()
            out = {"agent": a.agent, "drive": next((d for d in drives(c) if d["agent"] == a.agent), None), "itches": mine}
        elif a.cmd == "note":
            out = note(c, a.agent, a.kind, " ".join(a.what))
        elif a.cmd == "keep":
            out = keep(c, a.agent, a.name, a.thought, a.kind, a.lives, ids(a.itch), ids(a.on), a.check)
        elif a.cmd == "drop":
            out = drop(c, a.agent, a.itch, a.why)
        elif a.cmd == "recall":
            out = recall(c, " ".join(a.words), 5)
        elif a.cmd == "use":
            out = use(c, a.agent, a.ref, a.why)
        else:
            out = state(c)
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
