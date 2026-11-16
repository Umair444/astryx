#!/usr/bin/env python3
"""Oracle: the live steps bubble (bridges/progress.py), one lifecycle for every channel. No platform, no database: the
channel's four acts and the pool are recorders.
  P1 a step of a turn this chat opened posts the bubble, the next edits it; another chat's turn never shows
  P2 the wire's own send (its call and its "done") never opens or moves a bubble: it IS the reply (owner 11-16, wm_ai)
  P3 a reply takes the bubble to edit itself into; with keep, the job stays bubble-less and further work opens a new one
  P4 the turn's end removes a bubble that still holds only steps, and forgets the job; with no bubble it removes nothing
  P5 a job past its timeout is forgotten; a step for no job does nothing
Exit 0 · 1."""
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "src"))
from bridges import progress as PG  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        fails.append(name)


class Pool:
    """steps by id: (agent, content, opener thread); messages: one per thread, id = 100 + index."""
    def __init__(self):
        self.steps = {}

    async def fetchrow(self, sql, sid, agent):
        st = self.steps.get(sid)
        if not st or st[0] != agent:
            return None
        return {"content": st[1], "meta": json.dumps({"turn_msgs": [st[2]]})}

    async def fetchval(self, sql, ids, thread):
        return 1 if any(f"t{i}" == thread for i in ids) else None


acts = []
seq = [0]


async def post(agent, chat, line):
    seq[0] += 1
    acts.append(("post", chat, line))
    return f"m{seq[0]}"


async def edit(agent, chat, ph, line):
    acts.append(("edit", chat, ph, line))


async def remove(chat, ph):
    acts.append(("remove", chat, ph))


pool = Pool()
P = PG.Progress(lambda: pool, post=post, edit=edit, remove=remove)


async def step(sid, agent, content, opener, kind="tool"):
    pool.steps[sid] = (agent, content, opener)
    await P.on_step({"id": sid, "agent": agent, "kind": kind})
    for _ in range(20):                                    # the writer runs as its own task: let it settle
        await asyncio.sleep(0)
    while any(j["busy"] for j in P.jobs.values()):
        await asyncio.sleep(0.01)


async def main():
    P.open("db", "c1", "t1")
    await step(1, "db", "Bash: count loans", 1)
    await step(2, "db", "Read: notes.md", 1)
    await step(3, "db", "Bash: other chat's work", 9)
    arm("P1 the first step posts, the next edits the same bubble; another chat's turn never shows",
        [a[0] for a in acts] == ["post", "edit"] and acts[1][2] == "m1" and "other" not in str(acts), acts)
    n = len(acts)
    await step(4, "db", "mcp__astryx__send: to owner", 1)
    await step(5, "db", "mcp__astryx__send done", 1, kind="tool_done")
    arm("P2 the wire's own send (call and done) neither posts nor edits", len(acts) == n, acts[n:])
    ph = await P.take("db", "c1", keep=True)
    arm("P3 the reply takes the bubble to edit itself into", ph == "m1")
    await step(6, "db", "Bash: still working", 1)
    arm("P3 the job stays, bubble-less: further work opens a NEW bubble under the reply", acts[-1][0] == "post" and acts[-1][2].endswith("still working"), acts[-1])
    await step(7, "db", "", 1, kind="response")
    arm("P4 the turn's end removes the bubble of steps only, and forgets the job", acts[-1] == ("remove", "c1", "m2") and "db" not in P.jobs, acts[-1])
    acts.clear()
    P.open("db", "c1", "t1")
    await P.take("db", "c1", keep=True)
    await step(8, "db", "", 1, kind="response")
    arm("P4 a turn that ends with no bubble removes nothing", acts == [] and "db" not in P.jobs, acts)
    arm("P3 a reply to another chat takes nothing", await P.take("db", "c2", keep=True) is None)
    P.open("db", "c1", "t1")
    P.jobs["db"]["opened"] -= P.timeout + 1
    await step(9, "db", "Bash: late", 1)
    arm("P5 a job past its timeout is forgotten, nothing posted", "db" not in P.jobs and acts == [], acts)
    await step(10, "nobody", "Bash: x", 1)
    arm("P5 a step for no job does nothing", acts == [])
    arm("P2 own_send knows the wire's send and nothing else", PG.own_send("mcp__astryx__send: x") and PG.own_send("mcp__astryx__send done")
        and not PG.own_send("mcp__astryx__send_file: x") and not PG.own_send("Bash: mcp__astryx__send"))


asyncio.run(main())
print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: one live steps bubble for every channel")
sys.exit(1 if fails else 0)
