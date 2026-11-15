#!/usr/bin/env python3
"""Oracle: the workspace's STOP button (observatory/api/workspace.py, POST /api/ws/agents/{name}/interrupt) and the
handoff payloads beside it (GET /api/ws/handoffs). No tmux is ever run and no database is touched: subprocess.run is
replaced by a recorder, and the route is called directly with a stand-in request.
  - NAME: only the avatar route's name shape passes (lowercase, no '.', ':', '=', '/', space, ';'); a well-shaped name
    that is not on the roster is 404, never sent to tmux.
  - ARGV: exactly [*tmux prefix, send-keys, -t, =ax-<name>:, Escape]: an EXACT session match (a bare target prefix-
    matches ax-<name>x), a key NAME (no literal text reaches the prompt), the org's own tmux server (-L passes through).
  - ROUTE: not the owner -> 403 before anything runs; a bad name -> 400/404 with tmux untouched; a timeout is bounded
    (timeout= passed) and answers 504; a missing session (rc != 0) answers 409 without echoing tmux's stderr.
  - GATE: the path is NOT in main.PUBLIC (owner-only by omission, like every workspace route).
  - HANDOFFS: only an AGENT on the roster opening the turn counts (pulse / a canvas page / owner do not); a turn that
    answered its own sender is not a handoff; ordered by where the turn first wrote on the thread.
WS_SRC names another workspace.py (a mutant) to run the same arms against."""
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

SUBJECT = Path(os.environ.get("WS_SRC") or REPO / "observatory" / "api" / "workspace.py")
sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_ws_interrupt", REPO, deps=('fastapi', 'asyncpg', 'psycopg'), env=False)   # a clean clone (no venv): 77, not an import crash
spec = importlib.util.spec_from_file_location("ws_subject_interrupt", SUBJECT)
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


ROSTER = {"seed", "db", "abstractor-1", "ops_ai"}

print("name shape")
for bad in ["", "DB", "db;ls", "db x", "../db", "db/..", "db:1", "=db", "db.0", "-db", "1db", "d" * 42, "db\n", "ax-db:"]:
    arm(f"refuses {bad!r}", W.interrupt_check(bad, ROSTER | {bad}) == (400, "not an agent name"), W.interrupt_check(bad, ROSTER))
arm("refuses a non-string", W.interrupt_check(None, ROSTER) == (400, "not an agent name"))
arm("well-shaped but not on the roster -> 404", W.interrupt_check("ghost", ROSTER) == (404, "no such agent"))
for good in ["seed", "db", "abstractor-1", "ops_ai"]:
    arm(f"accepts {good}", W.interrupt_check(good, ROSTER) is None)

print("argv")
arm("single org", W.interrupt_argv("db", ["tmux"]) == ["tmux", "send-keys", "-t", "=ax-db:", "Escape"], W.interrupt_argv("db", ["tmux"]))
arm("several orgs keep -L", W.interrupt_argv("abstractor-1", ["tmux", "-L", "ax-two"])
    == ["tmux", "-L", "ax-two", "send-keys", "-t", "=ax-abstractor-1:", "Escape"])
arm("Escape is a key name, the last argv element, no -l", W.interrupt_argv("db", ["tmux"])[-1] == "Escape" and "-l" not in W.interrupt_argv("db", ["tmux"]))


# ---------------------------------------------------------------------------------------------------- the route
class Req:                                          # what the handler reads from a request: nothing but identity
    pass


calls = []


def recorder(rc=0, raise_=None):
    def run(argv, **kw):
        calls.append((argv, kw))
        if raise_:
            raise raise_
        return subprocess.CompletedProcess(argv, rc, "", "can't find session: ax-secret-detail")
    return run


def call(name, owner=True, rc=0, raise_=None):
    calls.clear()
    W.bind(lambda: None, Path("/nonexistent"), roster=lambda: ROSTER, owner=lambda r: owner)
    W._tmux = lambda: ["tmux", "-L", "ax-test"]
    real = W.subprocess.run
    W.subprocess.run = recorder(rc, raise_)
    try:
        r = asyncio.run(W.ws_interrupt(name, Req()))
    finally:
        W.subprocess.run = real
    if isinstance(r, dict):
        return 200, r
    return r.status_code, json.loads(r.body)


print("route")
st, body = call("db", owner=False)
arm("not the owner -> 403, tmux untouched", st == 403 and not calls, (st, calls))
st, body = call("db;reboot")
arm("bad name -> 400, tmux untouched", st == 400 and not calls, (st, calls))
st, body = call("ghost")
arm("unknown agent -> 404, tmux untouched", st == 404 and not calls, (st, calls))
st, body = call("db")
arm("valid -> 200 {ok}", st == 200 and body == {"ok": True, "agent": "db"}, (st, body))
arm("valid -> exactly one tmux call with the exact argv",
    len(calls) == 1 and calls[0][0] == ["tmux", "-L", "ax-test", "send-keys", "-t", "=ax-db:", "Escape"], calls)
arm("the call is bounded by a timeout", calls and calls[0][1].get("timeout") == W.INTERRUPT_TIMEOUT and W.INTERRUPT_TIMEOUT <= 10, calls)
arm("no shell", calls and not calls[0][1].get("shell"), calls)
st, body = call("db", rc=1)
arm("no session -> 409, tmux's stderr not echoed", st == 409 and "secret" not in json.dumps(body), (st, body))
st, body = call("db", raise_=subprocess.TimeoutExpired(["tmux"], 5))
arm("timeout -> 504", st == 504, (st, body))
st, body = call("db", raise_=FileNotFoundError("tmux"))
arm("no tmux binary -> 503", st == 503, (st, body))

print("gate")
main_src = (REPO / "observatory" / "api" / "main.py").read_text()
pub = main_src[main_src.index("PUBLIC = {"):main_src.index("PUBLIC_PATHS =")]
arm("interrupt is not a PUBLIC path", "interrupt" not in pub and "/api/ws" not in pub)
arm("main binds the owner check", "owner=lambda r: owner_call(r)" in main_src)
W2 = importlib.util.module_from_spec(importlib.util.spec_from_file_location("ws_fresh", SUBJECT))
importlib.util.spec_from_file_location("ws_fresh", SUBJECT).loader.exec_module(W2)
arm("unbound module denies (default owner check is False)", W2._owner(Req()) is False)

print("handoffs")
T = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def row(turn, agent, at, frm, body="payload", thread="plan-1", intent="chat"):
    return {"turn_id": turn, "agent": agent, "at": at, "id": 1000 + turn, "ts": T, "from_agent": frm, "to_agent": agent,
            "thread": thread, "intent": intent, "body": body}


got = W.handoffs_of([row(3, "seed", 50, "db"), row(1, "db", 20, "seed"), row(2, "finance", 30, "pulse"),
                     row(4, "seed", 60, "canvas-1"), row(5, "db", 70, "db"), row(6, "seed", 80, None)], ROSTER)
arm("agent-opened turns only, ordered by `at`", [h["turn_id"] for h in got] == [1, 3], got)
arm("payload carries from/to/thread/intent/body/iso ts",
    got and got[0]["msg"] == {"id": 1001, "ts": T.isoformat(), "from": "seed", "to": "db", "thread": "plan-1",
                              "intent": "chat", "body": "payload"} and got[0]["agent"] == "db" and got[0]["at"] == 20, got)
arm("handoff SQL never reads the opener's own thread (in-thread rows render themselves)",
    "IS DISTINCT FROM $1" in W.HANDOFFS_SQL and "NOT " + W.human_sql("i.from_agent") in W.HANDOFFS_SQL)   # every human, not 'owner' alone

print(f"\n{'ALL PASS' if not fails else f'{fails} FAIL'}")
sys.exit(1 if fails else 0)
