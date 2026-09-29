#!/usr/bin/env python3
"""astryx · pulse — one tick of the org's clock, then exit.

No daemon, no loop: systemd's timer (astryx-pulse.timer, every minute) is the
scheduler; this script is only the evaluator. One tick does three things:

  1. reconcile   scan triggers/<agent>/*.py for @trigger functions (each file
                 read in a throwaway subprocess: a broken file becomes an error
                 message to its agent, never a dead clock) and upsert rows.
  2. claim       atomically grab due rows (FOR UPDATE SKIP LOCKED) and advance
                 their next_fire per cron. Concurrent ticks cannot double-fire.
  3. evaluate    heartbeats fire as-is; sql checks fire on a new non-empty
                 result; python checks run in a killable 30s subprocess with
                 their persisted state. A firing is an ordinary wire message
                 from `pulse` to the owning agent. Silence costs nothing.

Everything durable lives in the triggers table; this process holds nothing.
Run by hand any time: venv/bin/python nucleus/pulse.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from croniter import croniter

REPO = Path(__file__).resolve().parents[1]
PY = str(REPO / "venv" / "bin" / "python")
# ASTRYX_DSN from the environment first (goal 4227 S1c: an oracle binds the pulse, and the pulse_run
# subprocesses that inherit its env, to a throwaway fixture database), else .env as before.
DSN = os.environ.get("ASTRYX_DSN") or next(
    l.split("=", 1)[1].strip()
    for l in (REPO / ".env").read_text().splitlines()
    if l.startswith("ASTRYX_DSN="))
CHECK_TIMEOUT = 30
PRESSURE_PCT = 85        # 5h gauge at/above this: non-survival wakes are held, not sent
HOLD_K = 5               # per held key, the newest K are delivered; older ones are elided (kept, marked)


def say(agent: str, body: str, conn, coalesce_key: str | None = None):
    """Fire a wire message. With coalesce_key: skip if an identical trigger's
    message is still pending undelivered — an unanswered alarm never stacks."""
    if coalesce_key:
        pending = conn.execute(
            "SELECT 1 FROM messages WHERE to_agent=%s AND from_agent='pulse' "
            "AND status='pending' AND body LIKE %s LIMIT 1",
            (agent, f"[trigger {coalesce_key}]%")).fetchone()
        if pending:
            return False
    conn.execute("INSERT INTO messages (from_agent, to_agent, intent, body) "
                 "VALUES ('pulse', %s, 'trigger', %s)", (agent, body[:3000]))
    return True


# ---------------------------------------------------------------- reconcile
def discover(path: Path) -> list[dict] | str:
    """Import one trigger file in a subprocess; return its @trigger registry."""
    prog = ("import json, sys, runpy; import astryx; "
            f"runpy.run_path({str(path)!r}); "
            "print(json.dumps([{k: t[k] for k in ('name','schedule','note')} "
            "for t in astryx._registry]))")
    r = subprocess.run([PY, "-c", prog], capture_output=True, text=True,
                       timeout=20, cwd=REPO)
    if r.returncode != 0:
        return r.stderr.strip()[-500:]
    return json.loads(r.stdout)


def reconcile(conn):
    seen: set[tuple[str, str]] = set()
    for f in sorted((REPO / "triggers").glob("*/*.py")):
        agent = f.parent.name
        try:
            found = discover(f)
        except Exception as e:
            found = str(e)
        if isinstance(found, str):                      # broken file: tell the owner
            # WHAT THIS MESSAGE MUST SAY, and did not (memory, msg 3046). A file that fails
            # to load is skipped here, so its triggers never enter `seen` — and the retirement
            # loop below then sets enabled=false on every one of them. A syntax error does not
            # merely fail to reload a trigger: it SWITCHES THE AGENT'S GUARDS OFF, for as long
            # as the file stays broken. It self-heals on the next clean parse (the upsert sets
            # enabled=true), so the damage is not durable — but an agent told only "failed to
            # load" has no way to know its watchers went dark, which is the difference between
            # a compile error and an unguarded window. So name them.
            try:
                dark = [r[0] for r in conn.execute(
                    "SELECT name FROM triggers WHERE kind='python' AND enabled "
                    "AND check_src LIKE %s ORDER BY name",
                    (f"triggers/{agent}/{f.name}::%",)).fetchall()]
            except Exception:
                dark = []                               # never let the diagnostic break reconcile
            detail = (f" — this DISABLES your trigger(s) until it parses: {', '.join(dark)}"
                      if dark else "")
            # coalesce_key: the only alarm in the pulse that lacked one. The timer runs every
            # 60s, so a file left broken overnight sent ~480 identical wakes. The key matches
            # the body already being sent ([trigger <key>]%), so no format change.
            say(agent, f"[trigger file {f.name}] failed to load: {found}{detail}", conn,
                coalesce_key=f"file {f.name}")
            continue
        for t in found:
            seen.add((agent, t["name"]))
            conn.execute(
                """INSERT INTO triggers (agent, name, schedule, kind, check_src, note, next_fire)
                   VALUES (%(a)s, %(n)s, %(s)s, 'python', %(src)s, %(note)s, now())
                   ON CONFLICT (agent, name) DO UPDATE
                     SET schedule = %(s)s, check_src = %(src)s, note = %(note)s,
                         enabled = true""",
                {"a": agent, "n": t["name"], "s": t["schedule"],
                 "src": f"triggers/{agent}/{f.name}::{t['name']}", "note": t["note"]})
    # a python trigger whose function vanished from its file is retired
    for a, n in conn.execute(
            "SELECT agent, name FROM triggers WHERE kind='python' AND enabled").fetchall():
        if (a, n) not in seen:
            conn.execute("UPDATE triggers SET enabled=false WHERE agent=%s AND name=%s",
                         (a, n))


# ----------------------------------------------------------------- evaluate
def run_python(src: str, state: dict) -> dict:
    """check in a killable subprocess: {state} in on stdin, {state, fire} out."""
    file, func = src.split("::")
    r = subprocess.run([PY, str(REPO / "nucleus" / "pulse_run.py"), file, func],
                       input=json.dumps({"state": state}), capture_output=True,
                       text=True, timeout=CHECK_TIMEOUT, cwd=REPO)
    if r.returncode != 0:
        durable = []
        try:                              # a crashed check still hands over its durable wakes (S1c)
            durable = json.loads(r.stdout.strip().splitlines()[-1]).get("durable_wakes") or []
        except Exception:
            pass
        return {"state": state, "error": r.stderr.strip()[-500:], "wakes": durable}
    return json.loads(r.stdout)


def evaluate(t: dict, conn) -> tuple[str | None, dict, list[dict]]:
    kind, src, state = t["kind"], t["check_src"], dict(t["state"] or {})
    if kind == "heartbeat":
        return (t["note"] or f"heartbeat: you chose to wake on '{t['schedule']}'. "
                "Look around; act only if something needs you. Silence is free."), state, []
    if kind == "sql":
        rows = conn.execute(src).fetchall()
        if not rows:
            return None, state, []
        digest = hashlib.sha256(repr(rows).encode()).hexdigest()
        if digest == state.get("last_digest"):
            return None, state, []                # same standing condition: quiet
        state["last_digest"] = digest
        return f"condition met ({len(rows)} rows): {repr(rows)[:800]}", state, []
    if kind == "python":
        out = run_python(src, state)
        if "error" in out:        # a crashed evaluation delivers only its DURABLE wakes (S1c)
            return (f"[trigger {t['name']}] check crashed: {out['error']}", out["state"],
                    list(out.get("wakes") or []))
        fire = out.get("fire")
        return ((fire if isinstance(fire, str) and fire.strip() else None), out["state"],
                list(out.get("wakes") or []))
    return None, state, []


def pressure(conn) -> bool | None:
    """Is the account's 5h window at/above PRESSURE_PCT? True / False, or None when the gauge is
    missing or unreadable. Callers treat None as NOT under pressure (fail-open: unknown pressure
    delivers)."""
    try:
        g = conn.execute(
            "SELECT five_hour_pct FROM current_usage").fetchone()   # unified authority (3833)
        return None if not g or g[0] is None else float(g[0]) >= PRESSURE_PCT
    except Exception:
        return None


def shed(due: list[dict], conn) -> list[dict]:
    """LOAD SHEDDING under quota pressure (plan-4227 S1c: R1 + R3).

    Quota is spent by WAKES, not by evaluation. So under pressure a python/sql check is ALWAYS
    evaluated (R1): its wakes go through the chokepoint in process(), which holds a non-survival
    trigger's wakes in held_wakes instead of sending them. A detection under pressure is delayed
    and visible, never skipped. That's derived from `kind` — no list, no flag, nothing to forget
    (it also closes 17080: run_check/run_backup/econ_rollup act inside evaluation).
    A heartbeat's evaluation IS its wake, so a premium=0 heartbeat waits, as before (R3).
    Reads NO value number (S1a). Fail-open: no gauge = no shedding."""
    if not pressure(conn):
        return due
    kept = [t for t in due
            if t.get("kind") != "heartbeat" or int(t.get("premium") or 0) > 0]
    for t in due:
        if t not in kept:
            print(f"shed {t['agent']}/{t['name']} (5h >={PRESSURE_PCT}%)")
    return kept


# ------------------------------------------------------------ the wake chokepoint (S1c)
_residents = None


def residents() -> set[str]:
    """Agents with a resident Claude body: a charter in the agents/ tree (the org structure's one
    authority; spawn.sh finds a charter by name at any depth). Only a wake TO one of these spends
    plan quota. The owner and the family chats are humans behind bridges, and a peer org is
    someone else's quota, so their wakes are never held — least of all the out-of-band owner
    alarm, which fires exactly when quota pressure latches the fleet. Unreadable tree → empty set
    → nothing held (fail-open: deliver)."""
    global _residents
    if _residents is None:
        try:
            _residents = {c.stem for c in (REPO / "agents").rglob("*.md")}
        except Exception:
            _residents = set()
    return _residents


def costs_quota(w: dict) -> bool:
    return (w.get("to_org") or "local") == "local" and w["to_agent"] in residents()


def emit(conn, w: dict, held_from=None):
    """THE writer of trigger wakes. Byte-compatible with the insert sites it replaced: the check
    names from_agent/from_org/to_agent/to_org/thread/intent/body itself. No pending-coalesce here
    (that stays in say(), the pulse's own alarms); supersede happens only through hold()."""
    conn.execute(
        "INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body, delivery) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
        (w["from_agent"], w.get("from_org") or "local", w["to_agent"], w.get("to_org") or "local",
         w.get("thread"), w.get("intent") or "trigger", w["body"],
         json.dumps({"held_from": held_from.isoformat()}) if held_from else None))


_KEY = "agent=%s AND trigger=%s AND to_agent=%s AND coalesce(thread,'')=coalesce(%s,'')"


def hold(conn, t: dict, w: dict):
    """Persist a wake raised under pressure (P1-P3). APPEND by default: distinct news is never
    merged away. A byte-identical wake under the same key only bumps n. supersede=True (opt-in,
    for report-style wakes whose later body contains the earlier) replaces the key's held reports.
    Past HOLD_K per key the oldest are marked elided: kept, readable, released as ONE marker."""
    key = (t["agent"], t["name"], w["to_agent"], w.get("thread"))
    if w.get("supersede"):
        conn.execute(f"DELETE FROM held_wakes WHERE {_KEY} AND NOT elided AND supersede", key)
    elif conn.execute(
            f"UPDATE held_wakes SET n = n + 1 WHERE {_KEY} AND NOT elided AND body=%s "
            "AND from_agent=%s AND intent=%s RETURNING id",
            (*key, w["body"], w["from_agent"], w.get("intent") or "trigger")).fetchone():
        return
    conn.execute(
        "INSERT INTO held_wakes (agent, trigger, from_agent, from_org, to_agent, to_org, thread, "
        "intent, body, supersede) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (t["agent"], t["name"], w["from_agent"], w.get("from_org") or "local", w["to_agent"],
         w.get("to_org") or "local", w.get("thread"), w.get("intent") or "trigger", w["body"],
         bool(w.get("supersede"))))
    ids = [r[0] for r in conn.execute(
        f"SELECT id FROM held_wakes WHERE {_KEY} AND NOT elided ORDER BY id", key).fetchall()]
    if len(ids) > HOLD_K:
        conn.execute("UPDATE held_wakes SET elided = true WHERE id = ANY(%s)", (ids[:-HOLD_K],))


def _held_for(raised_at, now) -> str:
    m = max(0, int((now - raised_at).total_seconds() // 60))
    return f"{m // 60}h{m % 60:02d}m" if m >= 60 else f"{m}m"


def release(conn):
    """Deliver every held wake, oldest first, in ONE transaction (called when not under pressure).
    Each body carries the facts a reader needs to judge staleness (P4), and delivery.held_from
    records the raised time (B2). Elided rows are announced by one marker per key and stay
    readable for 7 days after it."""
    with conn.transaction():
        now = conn.execute("SELECT now()").fetchone()[0]
        keys = conn.execute(
            "SELECT DISTINCT agent, trigger, to_agent, thread FROM held_wakes "
            "WHERE NOT elided OR released_at IS NULL").fetchall()
        for key in keys:
            n, first = conn.execute(
                f"SELECT count(*), min(raised_at) FROM held_wakes WHERE {_KEY} "
                "AND elided AND released_at IS NULL", key).fetchone()
            rows = conn.execute(
                f"SELECT id, from_agent, from_org, to_agent, to_org, thread, intent, body, raised_at "
                f"FROM held_wakes WHERE {_KEY} AND NOT elided ORDER BY id", key).fetchall()
            if n:
                agent, trig, to, thread = key
                where = (f"agent='{agent}' AND trigger='{trig}' AND to_agent='{to}' "
                         f"AND coalesce(thread,'')='{thread or ''}' AND elided ORDER BY id")
                src = rows[0] if rows else None
                emit(conn, {"from_agent": src[1] if src else "pulse", "to_agent": to,
                            "to_org": src[4] if src else "local", "thread": thread,
                            "intent": src[6] if src else "trigger",
                            "body": f"[{n} earlier held wakes elided · first held "
                                    f"{first.astimezone().isoformat(timespec='seconds')} · read them: "
                                    f"SELECT body FROM held_wakes WHERE {where}]"})
                conn.execute(f"UPDATE held_wakes SET released_at = now() WHERE {_KEY} "
                             "AND elided AND released_at IS NULL", key)
            for (hid, fa, fo, ta, to_org, th, it, body, raised) in rows:
                stamp = (f"[held wake · raised {raised.astimezone().isoformat(timespec='seconds')} · "
                         f"held {_held_for(raised, now)} under 5h ≥{PRESSURE_PCT}% quota pressure]\n")
                emit(conn, {"from_agent": fa, "from_org": fo, "to_agent": ta, "to_org": to_org,
                            "thread": th, "intent": it, "body": stamp + body}, held_from=raised)
                conn.execute("DELETE FROM held_wakes WHERE id=%s", (hid,))
        conn.execute("DELETE FROM held_wakes WHERE elided AND released_at < now() - interval '7 days'")


def process(conn, due: list[dict], now):
    """Evaluate the claimed triggers and route their wakes: the one path every trigger wake takes.

    Held = the 5h gauge reads >=PRESSURE_PCT, the trigger has no survival flag (premium=0), AND the
    recipient spends plan quota (a resident agent). Per trigger, the state UPDATE and ALL of its wake writes (sends or holds) commit in ONE
    transaction (C1.3): if any part fails, nothing of it lands, the state is unchanged, and the
    check re-detects next tick (at-least-once, the duplicate direction). A held wake is persisted,
    never rewound, so no side effect of the evaluation re-runs. Returned fire strings take the same
    path, keeping say()'s header and its pending-coalesce when they are sent."""
    hot = pressure(conn)
    if not hot:
        try:
            release(conn)
        except Exception as e:
            print(f"release failed (held wakes kept): {e}", file=sys.stderr)
    for t in shed(due, conn):                      # evaluate outside the claim's lock
        try:
            fired, state, wakes = evaluate(t, conn)
        except Exception as e:
            fired, state, wakes = f"[trigger {t['name']}] evaluator error: {e}", t["state"], []
        held_here = bool(hot) and int(t.get("premium") or 0) <= 0
        try:
            with conn.transaction():
                conn.execute("UPDATE triggers SET state=%s WHERE id=%s",
                             (json.dumps(state or {}), t["id"]))
                sent = False
                if fired:
                    body = fired if fired.startswith("[trigger") else f"[trigger {t['name']}] {fired}"
                    if held_here and t["agent"] in residents():
                        hold(conn, t, {"from_agent": "pulse", "to_agent": t["agent"],
                                       "intent": "trigger", "body": body[:3000]})
                    else:
                        sent = say(t["agent"], body, conn, coalesce_key=t["name"]) or sent
                for w in wakes:
                    if held_here and costs_quota(w):
                        hold(conn, t, w)
                    else:
                        emit(conn, w)
                        sent = True
                if sent:
                    conn.execute("UPDATE triggers SET last_fired=%s WHERE id=%s", (now, t["id"]))
                    print(f"fired {t['agent']}/{t['name']}")
                elif held_here and (fired or wakes):
                    print(f"wake held {t['agent']}/{t['name']} (5h >={PRESSURE_PCT}%)")
        except Exception as e:
            print(f"wake write failed {t['agent']}/{t['name']} — state kept, re-detects next tick: {e}",
                  file=sys.stderr)


def tick():
    # LOCAL time, tz-aware: cron fields mean the server's own wall clock, so a
    # "3am review" is 3am wherever this org lives — never UTC (owner decree
    # 2026-07-25; the night-review fired at 7-9am PKT for two days).
    now = datetime.now().astimezone()
    with psycopg.connect(DSN, autocommit=True) as conn:
        reconcile(conn)
        with conn.transaction():
            due = conn.execute(
                """SELECT id, agent, name, schedule, kind, check_src, state, note, premium
                   FROM triggers WHERE enabled AND next_fire <= now()
                   ORDER BY next_fire FOR UPDATE SKIP LOCKED""").fetchall()
            cols = ["id", "agent", "name", "schedule", "kind", "check_src", "state",
                    "note", "premium"]
            due = [dict(zip(cols, r)) for r in due]
            for t in due:                          # advance clocks inside the claim
                try:
                    nxt = croniter(t["schedule"], now).get_next(datetime)
                except Exception:
                    conn.execute("UPDATE triggers SET enabled=false WHERE id=%s", (t["id"],))
                    say(t["agent"], f"[trigger {t['name']}] bad schedule "
                                    f"'{t['schedule']}', disabled", conn)
                    continue
                conn.execute("UPDATE triggers SET next_fire=%s, last_eval=%s WHERE id=%s",
                             (nxt, now, t["id"]))
        process(conn, due, now)


if __name__ == "__main__":
    try:
        tick()
    except Exception as e:
        print(f"pulse tick failed: {e}", file=sys.stderr)
        sys.exit(1)
