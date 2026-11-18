#!/usr/bin/env python3
"""Oracle: SWITCHING the agent(s) of one chat (observatory/api/workspace.py, PUT /api/ws/threads/meta {switch_to}).
The owner can hand a conversation to another agent; the thread keeps every switch as {ts, agents}, the composer's
"To" and the list row's faces become the switched-to agents, and the chat draws a divider at each switch.
  - ONE SWITCH: stored as {ts, agents}; the list row's `agents` becomes the switched-to agents (old partners drop).
  - MANY: appended oldest first; a switch to the last switch's agents still lands (from NOW, only these: how an agent
    written to since is removed, owner 13780); the list keeps its newest
    SWITCHES_MAX; title and pin live beside them, and clearing both keeps the switches.
  - REFUSED: an unknown agent, a malformed name, an empty list, too many, a non-conversation thread -> 400, nothing
    stored (an unknown name is refused, never silently dropped: the owner meant someone).
  - MALFORMED FILE: a switch with no ts / no agents / a non-list is skipped on read, never a crash.
  - GATE: owner-only by omission (no /api/ws path in main.PUBLIC, and the meta PUT is not a wire write the dev
    server refuses).
WS_SRC names another workspace.py (a mutant) to run the same arms against."""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

SUBJECT = Path(os.environ.get("WS_SRC") or REPO / "observatory" / "api" / "workspace.py")
sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_ws_switch", REPO, deps=('fastapi', 'asyncpg', 'psycopg'), env=False)   # a clean clone (no venv): 77, not an import crash
spec = importlib.util.spec_from_file_location("ws_subject", SUBJECT)
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


ROSTER = {"seed", "db", "finance", "lending", "memory"}


def agg(thread, partners, last_ts="2099-12-31T10:00:00"):
    return {"thread": thread, "parties": ["owner", *partners], "partners": partners, "last_ts": last_ts,
            "first_owner": "hello", "last_body": "reply", "last_from": partners[-1], "count": 2}


def main():
    print("pure: apply_meta / switches_of / switch_check")
    m1 = W.apply_meta({}, "chat:1-a", switch=["finance"], now="2099-12-31T10:00:00+00:00")
    arm("one switch stored as {ts, agents}", m1 == {"chat:1-a": {"switches": [{"ts": "2099-12-31T10:00:00+00:00", "agents": ["finance"]}]}}, m1)
    arm("the input is never mutated", W.apply_meta(m1, "chat:1-a", switch=["db"], now="x") is not m1
        and len(m1["chat:1-a"]["switches"]) == 1)
    m2 = W.apply_meta(m1, "chat:1-a", switch=["db", "lending"], now="2099-12-31T11:00:00+00:00")
    m3 = W.apply_meta(m2, "chat:1-a", switch=["finance"], now="2099-12-31T12:00:00+00:00")
    arm("many switches append, oldest first", [s["agents"] for s in m3["chat:1-a"]["switches"]] == [["finance"], ["db", "lending"], ["finance"]], m3)
    again = W.apply_meta(m3, "chat:1-a", switch=["finance"], now="2099-12-31T13:00:00+00:00")["chat:1-a"]["switches"]
    arm("a switch to the last switch's agents lands from now (owner 13780: an agent written to since comes off)",
        len(again) == 4 and again[-1] == {"ts": "2099-12-31T13:00:00+00:00", "agents": ["finance"]}, again)
    arm("a switch gets a server ts when none is given", W.apply_meta({}, "c", switch=["db"])["c"]["switches"][0]["ts"].startswith("20"))
    many = {}
    for i in range(W.SWITCHES_MAX + 7):
        many = W.apply_meta(many, "c", switch=["db" if i % 2 else "seed"], now=f"t{i:03d}")
    sw = many["c"]["switches"]
    arm("the list keeps its newest SWITCHES_MAX", len(sw) == W.SWITCHES_MAX and sw[-1]["ts"] == f"t{W.SWITCHES_MAX + 6:03d}", (len(sw), sw[-1]))
    t = W.apply_meta(W.apply_meta(m3, "chat:1-a", title="Close", pinned=True), "chat:1-a", title="", pinned=False)
    arm("title and pin live beside the switches; clearing both keeps them", t == m3, t)
    arm("switches_of skips malformed entries", W.switches_of({"switches": [
        {"ts": "a", "agents": ["db"]}, {"agents": ["db"]}, {"ts": "b"}, {"ts": "c", "agents": []}, "x",
        {"ts": "d", "agents": "db"}, {"ts": "e", "agents": [1]}]}) == [{"ts": "a", "agents": ["db"]}])
    arm("switches_of on a non-list / no entry", W.switches_of({"switches": "x"}) == [] and W.switches_of({}) == [])
    arm("check: known agents pass, deduped, order kept", W.switch_check(["finance", "db", "finance"], ROSTER) == (["finance", "db"], None))
    for bad, why in ((["ghost"], "unknown"), (["Finance"], "case"), (["../x"], "path"), ([], "empty"), ("db", "not a list"),
                     ([None], "None"), (["db", "nobody"], "one unknown among known")):
        arm(f"check refuses {why}", W.switch_check(bad, ROSTER)[1] is not None)
    big = {f"a{i}" for i in range(W.SWITCH_AGENTS_MAX + 1)}
    arm("check refuses more than SWITCH_AGENTS_MAX", W.switch_check(sorted(big), big)[1] is not None)

    print("listing: the row follows the switch")
    meta = {"chat:1-a": m3["chat:1-a"], "obs:seed": {"switches": [{"ts": "x", "agents": ["db"]}]},
            "chat:1-b": {"switches": [{"ts": "x", "agents": ["ghost"]}]}}
    rows = {r["thread"]: r for r in W.build_rows(
        [agg("chat:1-a", ["seed", "db"]), agg("obs:seed", ["seed"]), agg("chat:1-b", ["lending"]), agg("chat:1-c", ["db"])],
        meta, [], ROSTER)}
    arm("a switched chat's agents = the last switch's (old partners drop)", rows["chat:1-a"]["agents"] == ["finance"], rows["chat:1-a"])
    arm("the row carries its switches", [s["agents"] for s in rows["chat:1-a"]["switches"]] == [["finance"], ["db", "lending"], ["finance"]])
    arm("a desk switched away from its agent lists the new one", rows["obs:seed"]["agents"] == ["db"], rows["obs:seed"])
    arm("a switch to a since-retired agent falls back to who spoke", rows["chat:1-b"]["agents"] == ["lending"], rows["chat:1-b"])
    arm("an unswitched chat: no switches, partners as before", rows["chat:1-c"]["switches"] == [] and rows["chat:1-c"]["agents"] == ["db"])

    print("route (in-process, a temp estate; skipped without fastapi)")
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        print("  SKIP  fastapi/httpx not importable")
        return
    est = Path(tempfile.mkdtemp())
    W.bind(lambda: None, est, roster=lambda: ROSTER)
    app = FastAPI()
    app.include_router(W.router)
    c = TestClient(app)
    put = lambda body: c.put("/api/ws/threads/meta", json=body)  # noqa: E731
    stored = lambda: json.loads((est / "chat" / "threads.json").read_text())["threads"]  # noqa: E731
    r = put({"thread": "chat:1-a", "switch_to": ["finance"]})
    arm("one switch -> 200 with the thread's switches", r.status_code == 200 and [s["agents"] for s in r.json()["switches"]] == [["finance"]], r.text)
    arm("...stored with a server ts", stored()["chat:1-a"]["switches"][0]["ts"].startswith("20"), stored())
    put({"thread": "chat:1-a", "switch_to": ["db", "lending"]})
    r = put({"thread": "chat:1-a", "switch_to": ["seed"], "pinned": True})
    arm("multiple switches accumulate (and ride with a pin)", r.status_code == 200 and [s["agents"] for s in r.json()["switches"]] == [["finance"], ["db", "lending"], ["seed"]]
        and r.json()["pinned"] is True, r.text)
    before = stored()
    for body, why in (({"thread": "chat:1-a", "switch_to": ["ghost"]}, "an unknown agent"),
                      ({"thread": "chat:1-a", "switch_to": []}, "an empty switch"),
                      ({"thread": "chat:1-a", "switch_to": ["db", "x/../y"]}, "a malformed name"),
                      ({"thread": "wa:1@g.us", "switch_to": ["db"]}, "a WhatsApp thread")):
        r = put(body)
        arm(f"{why} -> 400, nothing stored", r.status_code == 400 and stored() == before, (r.status_code, r.text))
    arm("the refusal names the unknown agent", "ghost" in put({"thread": "chat:1-a", "switch_to": ["ghost"]}).json().get("error", ""))
    W.bind(lambda: None, est, roster=lambda: set())
    arm("no roster bound -> nobody is switchable", put({"thread": "chat:1-a", "switch_to": ["db"]}).status_code == 400)
    W.bind(lambda: None, est, roster=lambda: ROSTER)

    print("gate")
    main_src = (REPO / "observatory" / "api" / "main.py").read_text()
    pub = main_src[main_src.index("PUBLIC = {"):main_src.index("PUBLIC_PATHS =")]
    arm("the meta path is not PUBLIC (owner-only by the default-deny gate)", "/api/ws" not in pub and "threads/meta" not in pub)
    wire = main_src[main_src.index("_WIRE_WRITE = re.compile("):].split("\n", 1)[0]
    arm("the meta PUT is not a wire write (a switch works on the dev server)", "ws/threads" not in wire and "meta" not in wire, wire)


if __name__ == "__main__":
    print(f"test_ws_switch: {SUBJECT}")
    main()
    print(f"\n{'FAIL' if fails else 'PASS'}: {fails} failing arm(s)")
    sys.exit(1 if fails else 0)
