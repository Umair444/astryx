#!/usr/bin/env python3
"""Oracle: the chat types a Claude Code command into an agent's terminal (observatory/api/workspace.py, POST and GET
/api/ws/agents/{name}/terminal). No tmux is ever run and no database touched: subprocess.run, the label and the audit
are replaced by recorders, and the routes are called directly with a stand-in request.
  - SHAPE: a line is "/command" and optional arguments, one printable line; prose, a newline, a control character (C0
    or C1), a bidi override or zero-width, an empty or an over-long line never reach tmux. Keys are names from a fixed
    set (or a picker's digit, y, n), at most 12. A line AND keys, or neither, is refused.
  - ALLOWLIST (medic 12290): only the read-only and turn-level built-ins and the agent's OWN commands and skills are
    typed; /hooks, /permissions, /mcp, /config, /add-dir, /exit, /login, /logout and anything unknown answer 403 with
    tmux untouched.
  - CONFIRM: /clear without {"confirm": true} is 409 "confirm", tmux untouched.
  - ARGV: the line goes as ONE literal argument after `-l --`, then Enter as its own call; a key NAME is never literal;
    a picker's character always is; every call targets the EXACT session `=ax-<name>:` on the org's own tmux server.
  - DIALOG: a line is refused (409) while the pane is asking something; keys still go.
  - LABELLED: a labelled session's screen is never read: GET 403; POST types and returns screen "" with no capture
    after the send. An unreadable label is labelled.
  - AUDIT: one record per send, BEFORE the keys, the command's name without its arguments; no record, no keys.
  - ROUTE: not the owner -> 403 before anything runs; a bad or unknown name -> 400/404 with tmux untouched; a missing
    session -> 409 without tmux's stderr; a timeout -> 504; every answer that carries a screen is no-store.
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

OWN = {"deploy", "brief:nightly"}
chk = lambda body: W.terminal_check(body, OWN)

print("shape")
for good in ["/compact", "/model opus", "/context", "/compact keep the open plan and the last three files", "  /cost  ", "/deploy now", "/brief:nightly", "/model ünï"]:
    arm(f"a line: {good!r}", chk({"text": good})[0] is None and chk({"text": good})[1] == good.strip(), chk({"text": good}))
for bad in ["compact", "hello /compact", "/", "/ compact", "/compact\nrm -rf", "/compact\x1b[A", "/model\topus", "", "/" + "a" * 70, "/model " + "x" * 401, 7,
            "/model a\u009b31m", "/model a‮b", "/model a​b", "/model a­b"]:
    r = chk({"text": bad})
    arm(f"refused: {ascii(bad)[:34]}", r[0] is not None and r[0][0] == 400 and r[1] == "" and r[2] == [], r)
arm("a trailing space is trimmed, not an argument", chk({"text": "/compact "}) == (None, "/compact", []))
arm("keys: names and a picker's characters", chk({"keys": ["Down", "Down", "Enter", "2", "y"]}) == (None, "", ["Down", "Down", "Enter", "2", "y"]))
for bad in [[], ["Enter"] * 13, ["C-c"], ["enter"], ["rm"], ["Enter", 1], "Enter", ["-l"], ["F1"]]:
    arm(f"keys refused: {str(bad)[:30]}", chk({"keys": bad})[0] is not None and chk({"keys": bad})[0][0] == 400, chk({"keys": bad}))
arm("a line AND keys is refused", chk({"text": "/cost", "keys": ["Enter"]})[0][0] == 400)
arm("neither is refused; so is no body", chk({})[0][0] == 400 and chk(None)[0][0] == 400)

print("allowlist")
for c in ["/hooks", "/permissions", "/mcp", "/config", "/add-dir /etc", "/terminal-setup", "/install-github-app", "/exit", "/quit", "/login", "/logout", "/LOGOUT", "/doctor", "/memory", "/nosuchthing x"]:
    r = chk({"text": c})
    arm(f"{c} -> 403, named, nothing to send", r[0] is not None and r[0][0] == 403 and "terminal" in r[0][1] and r[1] == "", r)
arm("an agent's own command is typed only for the agent that has it", chk({"text": "/deploy"})[0] is None and W.terminal_check({"text": "/deploy"}, set())[0][0] == 403)
import tempfile
with tempfile.TemporaryDirectory() as td:
    est = Path(td)
    (est / "homes" / "db" / ".claude" / "commands").mkdir(parents=True); (est / "homes" / "db" / ".claude" / "commands" / "Deploy.md").write_text("x")
    (est / "homes" / "db" / ".claude" / "skills" / "probe").mkdir(parents=True); (est / "homes" / "db" / ".claude" / "skills" / "bad name").mkdir()
    (est / ".claude" / "commands").mkdir(parents=True); (est / ".claude" / "commands" / "shared.md").write_text("x")
    W.ESTATE = est
    arm("own = its home's and the estate's commands and skills, by safe name", W.terminal_own("db") == {"deploy", "probe", "shared"}, W.terminal_own("db"))
    arm("an agent with no .claude has only the estate's", W.terminal_own("seed") == {"shared"}, W.terminal_own("seed"))

print("confirm")
arm("/clear without confirm -> 409 confirm", chk({"text": "/clear"}) == ((409, "confirm"), "", []))
arm("confirm must be exactly true", chk({"text": "/clear", "confirm": "yes"})[0] == (409, "confirm") and chk({"text": "/clear", "confirm": True}) == (None, "/clear", []))

print("argv")
a = W.terminal_argvs("db", T, "/model opus", [])
arm("the line is ONE literal argument after -l --, then Enter by itself",
    a == [[*T, "send-keys", "-t", "=ax-db:", "-l", "--", "/model opus"], [*T, "send-keys", "-t", "=ax-db:", "Enter"]], a)
a = W.terminal_argvs("db", T, "", ["Down", "2", "Enter"])
arm("a key name is never literal; a picker's character always is",
    a == [[*T, "send-keys", "-t", "=ax-db:", "Down"], [*T, "send-keys", "-t", "=ax-db:", "-l", "--", "2"], [*T, "send-keys", "-t", "=ax-db:", "Enter"]], a)
arm("the pane's tail: trailing spaces and the empty end dropped, at most TERMINAL_TAIL lines",
    W.terminal_tail("a  \nb\n\n   \n") == "a\nb" and len(W.terminal_tail("\n".join(map(str, range(200)))).splitlines()) == W.TERMINAL_TAIL)
arm("a dialog is seen: a numbered selector, a permission question; a plain prompt is not",
    W.terminal_dialog("x\n ❯ 1. Yes\n   2. No") and W.terminal_dialog("Do you want to proceed?") and not W.terminal_dialog("❯ \n? for shortcuts") and not W.terminal_dialog("> /cost\nTotal"))


class Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        if self._b is ...:
            raise ValueError("no body")
        return self._b


calls, audits = [], []
PLAIN = "> /cost\n  Total cost: 1\n\n"


def setup(owner, labelled, audit_fails=False):
    calls.clear(); audits.clear()
    W.bind(lambda: None, Path("/nonexistent"), roster=lambda: ROSTER, owner=lambda r: owner)
    W._tmux = lambda: list(T)
    W.TERMINAL_SETTLE = 0
    W.terminal_own = lambda name: set()
    W._labelled = (lambda name: labelled) if labelled is not None else W._labelled

    async def audit(request, name, what):
        if audit_fails:
            raise RuntimeError("db down")
        audits.append((name, what, len(calls)))
    W._audit = audit


def out(r):
    if isinstance(r, dict):
        return 200, r, {}
    return r.status_code, json.loads(r.body), dict(r.headers)


def call(name, body, owner=True, rc=0, raise_=None, screen=PLAIN, labelled=False, audit_fails=False):
    setup(owner, labelled, audit_fails)

    def run(argv, **kw):
        calls.append((argv, kw))
        if raise_:
            raise raise_
        return subprocess.CompletedProcess(argv, rc, screen if "capture-pane" in argv else "", "can't find session: ax-secret-detail")
    real = W.subprocess.run
    W.subprocess.run = run
    try:
        return out(asyncio.run(W.ws_terminal(name, Req(body))))
    finally:
        W.subprocess.run = real


verbs = lambda: [c[0][len(T)] for c in calls]
print("route")
st, b, h = call("db", {"text": "/cost"}, owner=False)
arm("not the owner -> 403, tmux untouched", st == 403 and not calls and not audits, (st, calls))
st, b, h = call("db;reboot", {"text": "/cost"})
arm("bad name -> 400, tmux untouched", st == 400 and not calls, (st, calls))
st, b, h = call("ghost", {"text": "/cost"})
arm("unknown agent -> 404, tmux untouched", st == 404 and not calls, (st, calls))
st, b, h = call("db", {"text": "run this for me"})
arm("prose -> 400, tmux untouched", st == 400 and not calls, (st, calls))
st, b, h = call("db", ...)
arm("no body -> 400, tmux untouched", st == 400 and not calls, (st, calls))
for c in ["/logout", "/hooks", "/permissions", "/exit"]:
    st, b, h = call("db", {"text": c})
    arm(f"{c} -> 403, tmux untouched, nothing recorded", st == 403 and not calls and not audits, (st, calls))
st, b, h = call("db", {"text": "/clear"})
arm("/clear unconfirmed -> 409 confirm, tmux untouched", st == 409 and b == {"error": "confirm"} and not calls and not audits, (st, b, calls))
st, b, h = call("db", {"text": "/clear", "confirm": True})
arm("/clear confirmed -> typed", st == 200 and b["sent"] == "/clear", (st, b))
st, b, h = call("db", {"text": "/model opus"})
arm("a line -> 200 with what was sent and the pane's last lines, no-store",
    st == 200 and b == {"ok": True, "agent": "db", "sent": "/model opus", "screen": "> /cost\n  Total cost: 1", "private": False} and h.get("cache-control") == "no-store", (st, b, h))
arm("in order: look at the pane, the literal line, Enter, read the pane; all of the exact session",
    verbs() == ["capture-pane", "send-keys", "send-keys", "capture-pane"] and calls[0][0] == W.terminal_screen_argv("db", T) and calls[1][0][-1] == "/model opus", calls)
arm("every call is bounded and none is a shell", all(c[1].get("timeout") == W.INTERRUPT_TIMEOUT and not c[1].get("shell") for c in calls), calls)
arm("recorded ONCE, before any key, by the command's name without its arguments", audits == [("db", "/model", 1)], audits)
st, b, h = call("db", {"keys": ["Down", "Enter"]})
arm("keys -> 200, one call per key then the read; recorded", st == 200 and verbs() == ["send-keys", "send-keys", "capture-pane"] and audits == [("db", "Down Enter", 0)], (st, verbs(), audits))
st, b, h = call("db", {"text": "/cost"}, audit_fails=True)
arm("no record, no keys -> 503 and no send-keys", st == 503 and "send-keys" not in verbs(), (st, verbs()))
st, b, h = call("db", {"text": "/cost"}, screen="Bash command\n Do you want to proceed?\n ❯ 1. Yes\n   2. No\n")
arm("a line while the pane asks something -> 409, nothing typed, nothing recorded", st == 409 and verbs() == ["capture-pane"] and not audits and "keys" in b["error"], (st, b, verbs()))
st, b, h = call("db", {"keys": ["2"]}, screen="Do you want to proceed?\n ❯ 1. Yes\n   2. No\n")
arm("…and keys answer it", st == 200 and verbs()[0] == "send-keys", (st, verbs()))
st, b, h = call("db", {"text": "/cost"}, rc=1)
arm("no session -> 409 after ONE call, tmux's stderr not echoed", st == 409 and len(calls) == 1 and "secret" not in json.dumps(b), (st, b, calls))
st, b, h = call("db", {"text": "/cost"}, raise_=subprocess.TimeoutExpired(["tmux"], 5))
arm("timeout -> 504", st == 504, (st, b))
st, b, h = call("db", {"text": "/cost"}, raise_=FileNotFoundError())
arm("no tmux -> 503", st == 503, (st, b))

print("a labelled session")
st, b, h = call("db", {"keys": ["Enter"]}, labelled=True, screen="SECRET-SESSION-TEXT")
arm("POST keys: typed, and its screen is never read", st == 200 and b["screen"] == "" and b["private"] is True and "capture-pane" not in verbs() and "SECRET" not in json.dumps(b), (st, b, verbs()))
st, b, h = call("db", {"text": "/cost"}, labelled=True, screen="SECRET-SESSION-TEXT")
arm("POST a line: the dialog look happens, but no screen is returned", st == 200 and b["screen"] == "" and verbs() == ["capture-pane", "send-keys", "send-keys"] and "SECRET" not in json.dumps(b), (st, b, verbs()))


def screen(name, owner=True, rc=0, labelled=False):
    setup(owner, labelled)

    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, rc, "line one\nline two  \n\n", "can't find session: ax-secret-detail")
    real = W.subprocess.run
    W.subprocess.run = run
    try:
        return out(asyncio.run(W.ws_terminal_screen(name, Req(None))))
    finally:
        W.subprocess.run = real


print("the screen alone")
st, b, h = screen("db", labelled=True)
arm("GET a labelled session -> 403, tmux untouched", st == 403 and not calls and "private" in b["error"], (st, b, calls))
st, b, h = screen("db", owner=False)
arm("GET: not the owner -> 403, tmux untouched", st == 403 and not calls, (st, calls))
st, b, h = screen("ghost")
arm("GET: unknown agent -> 404, tmux untouched", st == 404 and not calls, (st, calls))
st, b, h = screen("db")
arm("GET: ONE call, a capture and never a send-keys; the pane's lines back, no-store",
    st == 200 and b == {"agent": "db", "screen": "line one\nline two"} and len(calls) == 1 and calls[0][0] == W.terminal_screen_argv("db", T) and h.get("cache-control") == "no-store", (st, b, calls, h))
st, b, h = screen("db", rc=1)
arm("GET: no session -> 409, tmux's stderr not echoed", st == 409 and "secret" not in json.dumps(b), (st, b))
spec2 = importlib.util.spec_from_file_location("ws_subject_terminal_label", SUBJECT)
W2 = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(W2)
W2.ESTATE = Path("/nonexistent")
arm("a label that can't be read is a labelled session (fail closed)", W2._labelled("db") is True)
W2.ESTATE = None
arm("…and so is an unbound estate", W2._labelled("db") is True)

print("gate")
main_src = (REPO / "observatory" / "api" / "main.py").read_text()
arm("the path is not in main.PUBLIC", "/terminal" not in main_src.split("PUBLIC", 1)[1].split("\n\n", 1)[0] if "PUBLIC" in main_src else False)

print(f"\n{'ALL PASS' if not fails else f'FAILED ({fails})'}: a chat line that starts with / is typed in the agent's terminal, and only that")
sys.exit(1 if fails else 0)
