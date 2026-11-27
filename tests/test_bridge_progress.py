#!/usr/bin/env python3
"""Oracle: the live steps bubble (bridges/progress.py), one lifecycle for every channel. No platform, no database: the
channel's acts and the pool are recorders.
  P1 a step of a turn this chat opened posts the bubble, the next edits it; another chat's turn never shows
  P2 the wire's own send (its call and its "done") never opens or moves a bubble: it IS the reply (owner 11-16, wm_ai)
  P3 a reply takes the bubble to edit itself into; with keep, the job stays bubble-less and further work opens a new one
  P4 the turn's end finishes a bubble that still holds only steps (with its step count) and forgets the job; a job with
     no bubble finishes nothing; a job still WAITING for its turn (nothing shown, no reply) is not closed by another
     turn's end (medic 12418)
  P5 a job past its timeout is finished and forgotten, its bubble never left standing (medic 12418 RED 2)
  P6 jobs are per (agent, chat): an agent asked in two chats keeps two bubbles; a new ask in the SAME chat joins a LIVE
     job (owner 11-18: no "finished" under a follow-up) and replaces only an idle one, finishing its bubble first
  P7 a job that opens while another chat's job of the agent is live says at once that it is queued
  P8 a turn's end keeps a job whose request has background work out (its bubble says so), one still waiting, and every
     job when the turn goes on (continues); it closes the rest
  P9 a step for a job closed in the last REOPEN seconds reopens it: WhatsApp edits its "finished" bubble back, a channel
     whose finish deletes posts a new one
  P11 a chat that has been answered gets no more content-free lines, only its own work
  P10 a channel with an edit window gets a fresh bubble before the old one ages out ("continued below"), and a reply
     never tries to edit an aged bubble; a job waiting on background work past PENDING says so, never "finished"
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
    """steps by id: (agent, content, meta); message i's thread is "t<i>"."""
    def __init__(self):
        self.steps = {}

    async def fetchrow(self, sql, sid, agent):
        st = self.steps.get(sid)
        if not st or st[0] != agent:
            return None
        return {"content": st[1], "meta": json.dumps(st[2])}

    async def fetch(self, sql, ids):
        return [{"id": i, "thread": f"t{i}"} for i in ids]


acts = []
seq = [0]


async def post(agent, chat, line):
    seq[0] += 1
    acts.append(("post", chat, line))
    return f"m{seq[0]}"


async def edit(agent, chat, ph, line):
    acts.append(("edit", chat, ph, line))


async def finish(agent, chat, ph, steps):
    acts.append(("finish", chat, ph, steps))


pool = Pool()
P = PG.Progress(lambda: pool, post=post, edit=edit, finish=finish)
W = PG.Progress(lambda: pool, post=post, edit=edit, finish=finish, edit_window=900, finish_keeps=True)   # WhatsApp's


async def settle():
    for _ in range(20):                                    # the writer runs as its own task: let it settle
        await asyncio.sleep(0)
    while any(j["busy"] for j in list(P.jobs.values()) + list(W.jobs.values())):
        await asyncio.sleep(0.01)


async def step(sid, agent, content, opener, kind="tool", meta=None, prog=None):
    pool.steps[sid] = (agent, content, meta if meta is not None else {"turn_msgs": [opener]})
    await (prog or P).on_step({"id": sid, "agent": agent, "kind": kind})
    await settle()


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
    arm("P4 the turn's end finishes the bubble of steps only (one step), and forgets the job", acts[-1] == ("finish", "c1", "m2", 1) and not P.of("db"), acts[-1])
    acts.clear()
    P.open("db", "c1", "t1")
    await P.take("db", "c1", keep=True)
    await step(8, "db", "", 1, kind="response")
    arm("P4 a turn that ends with no bubble finishes nothing, and the replied job is forgotten", acts == [] and not P.of("db"), acts)
    P.open("db", "c1", "t1")
    await step(9, "db", "", 9, kind="response")
    arm("P4 another turn's end leaves a job still waiting for its own turn", ("db", "c1") in P.jobs, P.jobs)
    arm("P3 a reply to another chat takes nothing", await P.take("db", "c2", keep=True) is None)
    await step(10, "db", "Bash: late", 1)
    P.jobs[("db", "c1")]["last"] -= P.timeout + 1
    acts.clear()
    await step(11, "db", "Bash: later", 1)
    arm("P5 a job past its timeout is finished (its bubble never left) and forgotten, and a later step never reopens "
        "it (only a turn's end can be a false 'finished')", acts == [("finish", "c1", "m3", 1)] and not P.of("db"), acts)
    acts.clear()
    await step(12, "nobody", "Bash: x", 1)
    arm("P5 a step for no job does nothing", acts == [])
    pool.steps.clear()
    P.open("db", "cA", "t1")
    P.open("db", "cB", "t2")
    await step(20, "db", "Bash: for A", 1)
    await step(21, "db", "Bash: for B", 2)
    arm("P6 one agent, two chats: two jobs, each its own bubble", {a[1] for a in acts if a[0] == "post"} == {"cA", "cB"} and len(P.of("db")) == 2, acts)
    acts.clear()
    P.open("db", "cA", "t1")
    await settle()
    arm("P6 a follow-up in the same chat while its job is live joins it: no finish, no new bubble", acts == []
        and P.jobs[("db", "cA")]["ph"] is not None, acts)
    P.jobs[("db", "cA")]["last"] -= P.timeout + 1
    P.open("db", "cA", "t1")
    await settle()
    arm("P6 ...an IDLE job is replaced, its bubble finished first", acts and acts[0][0] == "finish" and acts[0][1] == "cA", acts)
    arm("P2 own_send knows the wire's send and nothing else", PG.own_send("mcp__astryx__send: x") and PG.own_send("mcp__astryx__send done")
        and not PG.own_send("mcp__astryx__send_file: x") and not PG.own_send("Bash: mcp__astryx__send"))

    # P11 (seed's live transcript, 11-18: a turn opened by an agent's message, the owner answered mid-turn many times)
    P.jobs.clear(); P.closed.clear(); pool.steps.clear(); acts.clear()
    P.open("db", "cQ", "t2")
    await step(60, "db", "Bash: work for another request", 1, meta={"turn_msgs": [1], "waiting": [2]})
    arm("P11 a chat waiting behind another request sees that it is queued (no content)",
        acts and acts[-1][1] == "cQ" and acts[-1][2] == PG.QUEUED, acts)
    await P.take("db", "cQ", keep=True)
    acts.clear()
    await step(61, "db", "Bash: more work for the other", 1, meta={"turn_msgs": [1], "waiting": [2], "acked": [2]})
    arm("P11 once answered, it gets no more filler: no 'on it' or 'queued' bubble under each reply", acts == [], acts)
    await step(62, "db", "Bash: now its own work", 2)
    arm("P11 ...and its own work shows again when the agent turns to it", acts and acts[-1][0] == "post"
        and acts[-1][2] == "◌ Bash: now its own work", acts)

    # P7..P10 (owner 11-18, homes/seed/progress-requests/DESIGN.md)
    P.jobs.clear(); P.closed.clear(); pool.steps.clear(); acts.clear()
    P.open("db", "cA", "t1")
    await step(30, "db", "Bash: long work for A", 1)
    P.open("db", "cB", "t2")
    await settle()
    arm("P7 a job opening while another chat's job is live says at once that it is queued",
        ("post", "cB", PG.QUEUED) in acts, acts)
    acts.clear()
    await step(31, "db", "", 1, kind="response", meta={"pending": [1], "waiting": [2]})
    arm("P8 a turn's end with A's background work out: A's bubble says so and A stays; B still waits and stays",
        any(a[:2] == ("edit", "cA") and a[3] == PG.BACKGROUND for a in acts) and ("db", "cA") in P.jobs and ("db", "cB") in P.jobs
        and not any(a[0] == "finish" for a in acts), acts)
    acts.clear()
    await step(32, "db", "Bash: background done, wrapping up A", 1)
    arm("P8 the background work reports back: A's bubble shows the step again", any(a[:2] == ("edit", "cA") and
        a[3] == "◌ Bash: background done, wrapping up A" for a in acts) and not P.jobs[("db", "cA")]["pending"], acts)
    acts.clear()
    await step(33, "db", "", 1, kind="response", meta={"continues": True})
    arm("P8 continues (an owed reply blocks the stop): nothing closes", ("db", "cA") in P.jobs and ("db", "cB") in P.jobs
        and acts == [], acts)
    await step(34, "db", "", 1, kind="response", meta={})
    arm("P8 a clean end closes what showed work (both bubbles finished)", not P.of("db")
        and {a[1] for a in acts if a[0] == "finish"} == {"cA", "cB"}, acts)
    acts.clear()
    await step(35, "db", "Bash: more for A after all", 1)
    arm("P9 a step for a job closed moments ago reopens it (a channel whose finish deletes: a new bubble)",
        ("db", "cA") in P.jobs and acts and acts[-1][0] == "post" and acts[-1][1] == "cA", acts)
    W.open("db", "w1", "t1")
    await step(40, "db", "Bash: one", 1, prog=W)
    await step(41, "db", "", 1, kind="response", meta={}, prog=W)
    acts.clear()
    await step(42, "db", "Bash: not done after all", 1, prog=W)
    arm("P9 WhatsApp: the reopened job edits its 'finished' bubble back to the live line, no new bubble",
        acts and acts[-1][0] == "edit" and acts[-1][1] == "w1" and "not done" in acts[-1][3]
        and not any(a[0] == "post" for a in acts), acts)
    W.jobs[("db", "w1")]["posted"] -= 900
    acts.clear()
    await step(43, "db", "Bash: fifteen minutes in", 1, prog=W)
    arm("P10 an edit window about to close: the old bubble says 'continued below' and a fresh one carries on",
        acts[:2] and acts[0][0] == "edit" and acts[0][3] == PG.CONTINUED and acts[1][0] == "post", acts)
    W.jobs[("db", "w1")]["posted"] -= 900
    arm("P10 a reply never tries to edit an aged bubble (it goes as a message of its own)",
        await W.take("db", "w1", keep=True) is None)
    W.jobs.clear(); acts.clear()
    W.open("db", "w2", "t1")
    await step(50, "db", "Bash: kick off a long job", 1, prog=W)
    await step(51, "db", "", 1, kind="response", meta={"pending": [1]}, prog=W)
    W.jobs[("db", "w2")]["last"] -= PG.PENDING + 1
    acts.clear()
    await step(52, "db", "Bash: unrelated", 9, prog=W)
    arm("P10 background work silent past PENDING: the bubble says so, never 'finished', and the job is forgotten",
        any(a[0] == "edit" and a[3] == PG.STALE for a in acts) and not any(a[0] == "finish" for a in acts)
        and ("db", "w2") not in W.jobs, acts)


asyncio.run(main())
print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: one live steps bubble for every channel")
sys.exit(1 if fails else 0)
