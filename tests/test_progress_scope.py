#!/usr/bin/env python3
"""Oracle: a chat's live progress carries only the work THIS chat asked for (owner 11-15: progress for everyone's ask;
medic 12159: a bridge streamed every step of the agent while a job was open, so the agent's work for other threads
(a member's web ask, seed's task, another group) landed in the group, and opening a job to everyone would have let any
participant pull that stream).

  H  hooks/step.py turn_msgs: the msg_ids that opened the session's CURRENT turn, read from its transcript
     H1 a cold start finds the last opening line (a tool_result line is no opening; a list-shaped prompt is read)
     H2 the next call reads only what was appended: a new opening replaces the ids; a half-written line waits
     H3 a redelivered batch keeps every id; no channel tag is an opening with no ids ([]); a missing file is []
     H4 step_meta keeps the ledger's keys and adds turn_msgs; no ids leaves the ledger's meta as it was
     H5 a message queued into a running turn (a queued_command attachment) makes the scope unknown, warm or cold
     H6 a helper (sub-agent) is bound to the turn that launched it
     H7 an unbound helper takes a launch in flight (agreeing), else nothing; H8 parallel binds lose nothing
  B  bridges/common.step_line(thread=...) on a fixture database
     B1 a step whose turn this thread opened is a line for it; for another thread it is nothing
     B2 a step with no stamp is nothing for a scoped job (never everything); unscoped callers are unchanged
     B3 a turn opened by several messages counts for each of their threads
Exit 0 pass · 1 fail · 77 fixture unavailable."""
import asyncio
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


spec = importlib.util.spec_from_file_location("step_hook", REPO / "hooks" / "step.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)


def line(kind, content, **kw):
    return json.dumps({"type": kind, "message": {"content": content}, **kw}) + "\n"


def tool_result():
    return line("user", [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}])


def chan(*ids):
    return "".join(f'<channel source="astryx" from="owner" thread="wa:1" intent="chat" msg_id="{i}">hi</channel>\n'
                   for i in ids)


print("H the hook's turn scope")
with tempfile.TemporaryDirectory() as td:
    H.TURN_CACHE = str(Path(td) / "cache" / "turn-{agent}.json")
    H.TURN_SCAN = 64                                       # tiny chunks: the cold scan must cross chunk edges
    t = Path(td) / "session.jsonl"
    t.write_text(line("user", chan(7)) + line("assistant", "x") + tool_result()
                 + line("user", [{"type": "text", "text": chan(41)}]) + line("assistant", "y" * 300) + tool_result())
    arm("H1 a cold start finds the last opening, past tool results and across chunks", H.turn_msgs(str(t), "db") == [41],
        H.turn_msgs(str(t), "db"))
    with t.open("a") as f:
        f.write(tool_result() + line("user", chan(99)) + line("assistant", "z"))
    arm("H2 the next call reads what was appended: a new opening replaces the ids", H.turn_msgs(str(t), "db") == [99])
    with t.open("a") as f:
        f.write(line("user", chan(123))[:-30])             # half written: no newline yet
    arm("H2 ...a half-written line waits (still the last whole opening)", H.turn_msgs(str(t), "db") == [99])
    with t.open("a") as f:
        f.write(line("user", chan(123))[-30:])
    arm("H2 ...and counts once it is whole", H.turn_msgs(str(t), "db") == [123], H.turn_msgs(str(t), "db"))
    with t.open("a") as f:
        f.write(json.dumps({"type": "user", "isMeta": True, "message": {"content": chan(150)}}) + "\n")
    arm("H1 a channel wake is written isMeta, and it IS an opening (the real transcripts' shape)",
        H.turn_msgs(str(t), "db") == [150], H.turn_msgs(str(t), "db"))
    with t.open("a") as f:
        f.write(line("user", "This session is being continued from a previous conversation that ran out of context."))
    arm("H1 a compaction summary inside a turn opens nothing (the ids stay)", H.turn_msgs(str(t), "db") == [150])
    with t.open("a") as f:
        f.write(line("user", chan(300)) + tool_result()
                + json.dumps({"type": "attachment", "attachment": {"type": "queued_command", "prompt": chan(301)}}) + "\n")
    arm("H5 a message queued INTO a running turn makes its scope unknown ([]): a WA-opened turn that absorbs a web ask "
        "streams nothing more to the group (medic 12163)", H.turn_msgs(str(t), "db") == [], H.turn_msgs(str(t), "db"))
    cold = Path(td) / "cold.jsonl"
    cold.write_text(t.read_text())
    arm("H5 ...and a cold start lands on the same answer", H.turn_msgs(str(cold), "lending") == [])
    with t.open("a") as f:
        f.write(line("user", chan(200, 201, 202)))
    arm("H3 a redelivered batch keeps every id", H.turn_msgs(str(t), "db") == [200, 201, 202])
    with t.open("a") as f:
        f.write(line("user", "the owner typed in the terminal"))
    arm("H3 a prompt with no channel tag opens a turn with no ids", H.turn_msgs(str(t), "db") == [])
    arm("H3 a missing transcript is []", H.turn_msgs(str(Path(td) / "nope.jsonl"), "db") == [])
    other = Path(td) / "other.jsonl"
    other.write_text(line("user", chan(5)))
    arm("H3 a new session (another path) starts cold, not from the old offset", H.turn_msgs(str(other), "db") == [5])
    from psycopg.types.json import Jsonb
    m = H.step_meta(Jsonb({"registry_id": "mcp:x", "v": 2}), [5])
    arm("H4 step_meta keeps the ledger's keys and adds turn_msgs", m.obj == {"registry_id": "mcp:x", "v": 2, "turn_msgs": [5]})
    arm("H4 ...and no ids leaves the ledger's meta as it was", H.step_meta(None, []) is None)


print("H helpers (sub-agents)")
with tempfile.TemporaryDirectory() as td:
    H.TURN_CACHE = str(Path(td) / "cache" / "turn-{agent}.json")
    t = Path(td) / "parent.jsonl"
    t.write_text(line("user", chan(500)) + line("assistant", "x"))
    parent = {"transcript_path": str(t)}
    arm("H6 the parent's own step is scoped by its turn, no helper", H.scope(parent, "db") == ([500], None))
    H.bind_sub("db", "agentA", H.scope(parent, "db")[0], "check partitions", "general-purpose")
    with t.open("a") as f:                                  # the parent moves on to a turn another thread opened
        f.write(line("user", chan(777)))
    msgs, sub = H.scope({**parent, "agent_id": "agentA", "agent_type": "general-purpose"}, "db")
    arm("H6 a launched helper keeps the turn that launched it, after the parent moved on (the measured hook shape: the "
        "helper's events carry the PARENT's transcript_path)", msgs == [500] and sub == {"id": "agentA", "type": "general-purpose", "desc": "check partitions"}, (msgs, sub))
    msgs2, sub2 = H.scope({**parent, "agent_id": "agentB", "agent_type": "Explore"}, "db")
    arm("H7 an UNBOUND helper with no launch in flight gets nothing, never the parent's current turn (medic 12186: "
        "that turn may be another thread's)", msgs2 == [] and sub2 == {"id": "agentB", "type": "Explore"}, (msgs2, sub2))
    H.launch_open("db", "toolu_1", [777])
    arm("H7 a foreground helper (its launch still in flight) takes the launching turn", H.scope({**parent, "agent_id": "agentC"}, "db")[0] == [777])
    H.launch_open("db", "toolu_2", [500])
    arm("H7 launches in flight from two turns disagree: nothing", H.scope({**parent, "agent_id": "agentC"}, "db")[0] == [])
    arm("H7 a launch keeps the scope it opened with", H.launch_scope("db", "toolu_1") == [777] and H.launch_scope("db", "nope") is None)
    H.launch_close("db", "toolu_1")
    arm("H7 closing one launch leaves the other", H.launch_scope("db", "toolu_2") == [500])
    H.launch_close("db")                                    # the turn ended (Stop)
    arm("H7 a turn's end closes every launch; a closed launch scopes nothing",
        H.launch_scope("db", "toolu_2") is None and H.scope({**parent, "agent_id": "agentD"}, "db")[0] == [])
    from psycopg.types.json import Jsonb as _J
    arm("H6 step_meta carries the helper beside the scope", H.step_meta(None, [500], {"id": "agentA"}).obj == {"turn_msgs": [500], "sub": {"id": "agentA"}})
    # medic 12186: three parallel launches in one message, each PostToolUse its own process: none may lose its binding
    import subprocess
    code = ("import importlib.util,sys; s=importlib.util.spec_from_file_location('h',sys.argv[1]); m=importlib.util.module_from_spec(s); "
            "s.loader.exec_module(m); m.TURN_CACHE=sys.argv[2]; import time; time.sleep(float(sys.argv[4])); "
            "m.bind_sub('db', sys.argv[3], [42], 'd', 't')")
    lost = 0
    for trial in range(10):
        ids = [f"par{trial}x{k}" for k in range(3)]
        ps = [subprocess.Popen([sys.executable, "-c", code, str(REPO / "hooks" / "step.py"), H.TURN_CACHE, a, "0.3"]) for a in ids]
        for p_ in ps:
            p_.wait()
        lost += sum(1 for a in ids if H.scope({**parent, "agent_id": a}, "db")[0] != [42])
    arm("H8 three parallel bind_sub processes, 10 trials: no binding lost", lost == 0, f"{lost} of 30 lost")


async def bridge(url):
    import asyncpg
    from bridges import common as C
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        ids = {}
        for th in ("wa:A", "wa:B", "chat:web"):
            ids[th] = await pool.fetchval("INSERT INTO messages (from_agent, to_agent, thread, intent, body) "
                                          "VALUES ('owner','db',$1,'chat','ask') RETURNING id", th)

        async def step(meta):
            return await pool.fetchval("INSERT INTO steps (agent, kind, content, meta) VALUES ('db','tool','Bash: q',$1) "
                                       "RETURNING id", json.dumps(meta) if meta is not None else None)
        mine = await step({"turn_msgs": [ids["wa:A"]]})
        web = await step({"turn_msgs": [ids["chat:web"]], "registry_id": "mcp:x"})
        bare = await step(None)
        both = await step({"turn_msgs": [ids["wa:B"], ids["wa:A"]]})
        sl = lambda sid, th: C.step_line(pool, sid, "tool", agent="db", thread=th)    # noqa: E731
        arm("B1 a step whose turn this thread opened is a line for it", bool(await sl(mine, "wa:A")))
        arm("B1 ...and nothing for another thread", await sl(mine, "wa:B") is None)
        arm("B1 the agent's work for a web chat never lands in a group", await sl(web, "wa:A") is None)
        arm("B2 an unstamped step is nothing for a scoped job", await sl(bare, "wa:A") is None)
        arm("B2 ...while an unscoped caller is unchanged", bool(await C.step_line(pool, bare, "tool", agent="db")))
        helped = await step({"turn_msgs": [ids["wa:A"]], "sub": {"id": "agentA", "desc": "check partitions"}})
        hl = await sl(helped, "wa:A")
        arm("B4 a helper's step is a line for the thread its launch served, naming the helper", bool(hl) and "↳ check partitions · " in hl, hl)
        arm("B3 a turn opened by several messages counts for each of their threads",
            bool(await sl(both, "wa:A")) and bool(await sl(both, "wa:B")) and await sl(both, "chat:web") is None)
    finally:
        await pool.close()


try:
    from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db
    with fixture_db() as fx:
        os.environ["ASTRYX_DSN"] = fx["url"]
        print("B the bridge's scoped line")
        asyncio.run(bridge(fx["url"]))
except Exception as e:  # noqa: BLE001
    if type(e).__name__ != "FixtureUnavailable":
        raise
    print(f"  NOT SEARCHED: B arms, no fixture database ({e})")
    print(f"{'FAIL' if fails else 'PARTIAL'}: progress scope")
    sys.exit(1 if fails else 77)
print(f"{'PASS' if not fails else 'FAIL'}: progress scope ({fails} failing)")
sys.exit(1 if fails else 0)
