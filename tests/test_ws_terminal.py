#!/usr/bin/env python3
"""Oracle: the chat types a Claude Code command into an agent's terminal (observatory/api/workspace.py, POST
/api/ws/agents/{name}/terminal). No tmux is ever run: subprocess.run is replaced by a recorder and the route is called
directly with a stand-in request.
  - SHAPE: a line is "/command" and optional arguments, one printable line; prose, a newline, a control character, an
    empty or an over-long line never reach tmux. Keys are names from a fixed set (or a picker's digit, y, n), at most 12.
    A line AND keys, or neither, is refused.
  - REFUSED: /login and /logout (one login for the whole fleet) answer 403 with the reason, tmux untouched.
  - ARGV: the line goes as ONE literal argument after `-l --` (tmux reads no key name in it, and a line starting with
    "-" is no option), then Enter as its own call; a key NAME is never literal; a picker's character always is; every
    call targets the EXACT session `=ax-<name>:` on the org's own tmux server.
  - ROUTE: not the owner -> 403 before anything runs; a bad or unknown name -> 400/404 with tmux untouched; a missing
    session -> 409 without tmux's stderr; a timeout -> 504; the pane's last lines come back, trailing blanks dropped.
  - GATE: the path is NOT in main.PUBLIC.
WS_SRC names another workspace.py (a mutant) to run the same arms against."""
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

SUBJECT = Path(os.environ.get("WS_SRC") or REPO / "observatory" / "api" / "workspace.py")
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_ws_terminal", REPO, deps=('fastapi', 'asyncpg', 'psycopg'), env=False)
spec = importlib.util.spec_from_file_location("ws_subject_terminal", SUBJECT)
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


ROSTER = {"seed", "db"}
T = ["tmux", "-L", "ax-test"]

print("shape")
for good in ["/compact", "/model opus", "/context", "/compact keep the open plan and the last three files", "  /cost  ", "/plugin:cmd x"]:
    arm(f"a line: {good!r}", W.terminal_check({"text": good})[0] is None and W.terminal_check({"text": good})[1] == good.strip())
for bad in ["compact", "hello /compact", "/", "/ compact", "/compact\nrm -rf", "/compact\x1b[A", "/model\topus", "", "/" + "a" * 70, "/c " + "x" * 401, "/compact ", 7, None]:
    r = W.terminal_check({"text": bad}) if bad is not None else W.terminal_check({"text": None, "keys": None})
    arm(f"refused: {str(bad)[:30]!r}", r[0] is not None and r[0][0] == 400 and r[1] == "" and r[2] == [], r) if bad != "/compact " else \
        arm("a trailing space is trimmed, not an argument", r[0] is None and r[1] == "/compact", r)
arm("keys: names and a picker's characters", W.terminal_check({"keys": ["Down", "Down", "Enter", "2", "y"]}) == (None, "", ["Down", "Down", "Enter", "2", "y"]))
for bad in [[], ["Enter"] * 13, ["C-c"], ["enter"], ["rm"], ["Enter", 1], "Enter", ["-l"], ["F1"]]:
    arm(f"keys refused: {str(bad)[:30]}", W.terminal_check({"keys": bad})[0] is not None and W.terminal_check({"keys": bad})[0][0] == 400, W.terminal_check({"keys": bad}))
arm("a line AND keys is refused", W.terminal_check({"text": "/cost", "keys": ["Enter"]})[0][0] == 400)
arm("neither is refused; so is no body", W.terminal_check({})[0][0] == 400 and W.terminal_check(None)[0][0] == 400)

print("refused commands")
for c in ["/login", "/logout", "/LOGOUT", "/logout now"]:
    r = W.terminal_check({"text": c})
    arm(f"{c} -> 403 with its reason", r[0] is not None and r[0][0] == 403 and len(r[0][1]) > 20, r)

print("argv")
a = W.terminal_argvs("db", T, "/model opus", [])
arm("the line is ONE literal argument after -l --, then Enter by itself",
    a == [[*T, "send-keys", "-t", "=ax-db:", "-l", "--", "/model opus"], [*T, "send-keys", "-t", "=ax-db:", "Enter"]], a)
a = W.terminal_argvs("db", T, "", ["Down", "2", "Enter"])
arm("a key name is never literal; a picker's character always is",
    a == [[*T, "send-keys", "-t", "=ax-db:", "Down"], [*T, "send-keys", "-t", "=ax-db:", "-l", "--", "2"], [*T, "send-keys", "-t", "=ax-db:", "Enter"]], a)
arm("the pane's tail: trailing spaces and the empty end dropped, at most TERMINAL_TAIL lines",
    W.terminal_tail("a  \nb\n\n   \n") == "a\nb" and len(W.terminal_tail("\n".join(map(str, range(200)))).splitlines()) == W.TERMINAL_TAIL)


class Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        if self._b is ...:
            raise ValueError("no body")
        return self._b


calls = []


def call(name, body, owner=True, rc=0, raise_=None, screen="> /cost\n  Total cost: 1\n\n"):
    calls.clear()
    W.bind(lambda: None, Path("/nonexistent"), roster=lambda: ROSTER, owner=lambda r: owner)
    W._tmux = lambda: list(T)
    W.TERMINAL_SETTLE = 0

    def run(argv, **kw):
        calls.append((argv, kw))
        if raise_:
            raise raise_
        return subprocess.CompletedProcess(argv, rc, screen if "capture-pane" in argv else "", "can't find session: ax-secret-detail")
    real = W.subprocess.run
    W.subprocess.run = run
    try:
        r = asyncio.run(W.ws_terminal(name, Req(body)))
    finally:
        W.subprocess.run = real
    return (200, r) if isinstance(r, dict) else (r.status_code, json.loads(r.body))


print("route")
st, b = call("db", {"text": "/cost"}, owner=False)
arm("not the owner -> 403, tmux untouched", st == 403 and not calls, (st, calls))
st, b = call("db;reboot", {"text": "/cost"})
arm("bad name -> 400, tmux untouched", st == 400 and not calls, (st, calls))
st, b = call("ghost", {"text": "/cost"})
arm("unknown agent -> 404, tmux untouched", st == 404 and not calls, (st, calls))
st, b = call("db", {"text": "run this for me"})
arm("prose -> 400, tmux untouched", st == 400 and not calls, (st, calls))
st, b = call("db", ...)
arm("no body -> 400, tmux untouched", st == 400 and not calls, (st, calls))
st, b = call("db", {"text": "/logout"})
arm("/logout -> 403, tmux untouched", st == 403 and not calls, (st, calls))
st, b = call("db", {"text": "/cost"})
arm("a line -> 200 with what was sent and the pane's last lines", st == 200 and b == {"ok": True, "agent": "db", "sent": "/cost", "screen": "> /cost\n  Total cost: 1"}, (st, b))
arm("three tmux calls in order: the literal line, Enter, the capture of the exact session",
    [c[0][len(T)] for c in calls] == ["send-keys", "send-keys", "capture-pane"] and calls[2][0][len(T):] == ["capture-pane", "-p", "-t", "=ax-db:", "-S", f"-{W.TERMINAL_TAIL}"], calls)
arm("every call is bounded and none is a shell", all(c[1].get("timeout") == W.INTERRUPT_TIMEOUT and not c[1].get("shell") for c in calls), calls)
st, b = call("db", {"keys": ["Down", "Enter"]})
arm("keys -> 200, one call per key then the capture", st == 200 and len(calls) == 3 and b["sent"] == "Down Enter", (st, b, calls))
st, b = call("db", {"text": "/cost"}, rc=1)
arm("no session -> 409 after ONE call, tmux's stderr not echoed", st == 409 and len(calls) == 1 and "secret" not in json.dumps(b), (st, b, calls))
st, b = call("db", {"text": "/cost"}, raise_=subprocess.TimeoutExpired(["tmux"], 5))
arm("timeout -> 504", st == 504, (st, b))
st, b = call("db", {"text": "/cost"}, raise_=FileNotFoundError())
arm("no tmux -> 503", st == 503, (st, b))

print("the screen alone")


def screen(name, owner=True, rc=0):
    calls.clear()
    W.bind(lambda: None, Path("/nonexistent"), roster=lambda: ROSTER, owner=lambda r: owner)
    W._tmux = lambda: list(T)

    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, rc, "line one\nline two  \n\n", "can't find session: ax-secret-detail")
    real = W.subprocess.run
    W.subprocess.run = run
    try:
        r = asyncio.run(W.ws_terminal_screen(name, Req(None)))
    finally:
        W.subprocess.run = real
    return (200, r) if isinstance(r, dict) else (r.status_code, json.loads(r.body))


st, b = screen("db", owner=False)
arm("reading: not the owner -> 403, tmux untouched", st == 403 and not calls, (st, calls))
st, b = screen("ghost")
arm("reading: unknown agent -> 404, tmux untouched", st == 404 and not calls, (st, calls))
st, b = screen("db")
arm("reading: ONE call, a capture and never a send-keys; the pane's lines back",
    st == 200 and b == {"agent": "db", "screen": "line one\nline two"} and len(calls) == 1 and "send-keys" not in calls[0][0] and calls[0][0] == W.terminal_screen_argv("db", T), (st, b, calls))
st, b = screen("db", rc=1)
arm("reading: no session -> 409, tmux's stderr not echoed", st == 409 and "secret" not in json.dumps(b), (st, b))

print("gate")
main_src = (REPO / "observatory" / "api" / "main.py").read_text()
arm("the path is not in main.PUBLIC", "/terminal" not in main_src.split("PUBLIC", 1)[1].split("\n\n", 1)[0] if "PUBLIC" in main_src else False)

print(f"\n{'ALL PASS' if not fails else f'FAILED ({fails})'}: a chat line that starts with / is typed in the agent's terminal, and only that")
sys.exit(1 if fails else 0)
