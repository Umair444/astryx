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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from croniter import croniter

REPO = Path(__file__).resolve().parents[1]
PY = str(REPO / "venv" / "bin" / "python")
DSN = next(l.split("=", 1)[1].strip()
           for l in (REPO / ".env").read_text().splitlines()
           if l.startswith("ASTRYX_DSN="))
CHECK_TIMEOUT = 30


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
            say(agent, f"[trigger file {f.name}] failed to load: {found}", conn)
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
        return {"state": state, "error": r.stderr.strip()[-500:]}
    return json.loads(r.stdout)


def evaluate(t: dict, conn) -> tuple[str | None, dict]:
    kind, src, state = t["kind"], t["check_src"], dict(t["state"] or {})
    if kind == "heartbeat":
        return (t["note"] or f"heartbeat: you chose to wake on '{t['schedule']}'. "
                "Look around; act only if something needs you. Silence is free."), state
    if kind == "sql":
        rows = conn.execute(src).fetchall()
        if not rows:
            return None, state
        digest = hashlib.sha256(repr(rows).encode()).hexdigest()
        if digest == state.get("last_digest"):
            return None, state                    # same standing condition: quiet
        state["last_digest"] = digest
        return f"condition met ({len(rows)} rows): {repr(rows)[:800]}", state
    if kind == "python":
        out = run_python(src, state)
        if "error" in out:
            return f"[trigger {t['name']}] check crashed: {out['error']}", out["state"]
        fire = out.get("fire")
        return (fire if isinstance(fire, str) and fire.strip() else None), out["state"]
    return None, state


def tick():
    now = datetime.now(timezone.utc)
    with psycopg.connect(DSN, autocommit=True) as conn:
        reconcile(conn)
        with conn.transaction():
            due = conn.execute(
                """SELECT id, agent, name, schedule, kind, check_src, state, note
                   FROM triggers WHERE enabled AND next_fire <= now()
                   ORDER BY next_fire FOR UPDATE SKIP LOCKED""").fetchall()
            cols = ["id", "agent", "name", "schedule", "kind", "check_src", "state", "note"]
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
        for t in due:                              # evaluate outside the lock
            try:
                fired, state = evaluate(t, conn)
            except Exception as e:
                fired, state = f"[trigger {t['name']}] evaluator error: {e}", t["state"]
            conn.execute("UPDATE triggers SET state=%s WHERE id=%s",
                         (json.dumps(state or {}), t["id"]))
            if fired:
                sent = say(t["agent"], f"[trigger {t['name']}] {fired}"
                           if not fired.startswith("[trigger") else fired,
                           conn, coalesce_key=t["name"])
                if sent:
                    conn.execute("UPDATE triggers SET last_fired=%s WHERE id=%s",
                                 (now, t["id"]))
                    print(f"fired {t['agent']}/{t['name']}")


if __name__ == "__main__":
    try:
        tick()
    except Exception as e:
        print(f"pulse tick failed: {e}", file=sys.stderr)
        sys.exit(1)
