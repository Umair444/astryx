"""astryx bridges · progress — THE LIVE STEPS BUBBLE, one lifecycle for every channel.

A person asks an agent in a chat; while the agent works, one message in that chat shows its latest step, edited in
place. Each bridge used to keep its own copy of this (whatsapp, telegram, discord), and the copies drifted: a reply
kept the job alive so later work could show (owner 11-15), and the reply's OWN delivery step ("send done") then opened
a fresh bubble that no rule ever closed (owner 11-16, wm_ai). So the lifecycle lives here once.

A JOB is one agent's work for one chat, keyed (agent, chat): an agent serving two groups at once has two jobs, and one
never orphans the other's bubble (medic 12418).
  open(agent, chat, thread)   a person's ask on a route that shows steps
  on_step(ev)                 a step of a turn THAT chat opened (common.step_line's scope) updates its line; one
                              serialized writer per job, always pushing the newest line and skipping the ones between
  take(agent, chat, keep)     a reply is being delivered: the bubble to edit the reply into (or None). With `keep` the
                              job stays, bubble-less, so further work for that chat opens a new bubble under the reply
  FINISH                      a job ends at its turn's end (the agent's 'response' step, for a job that has shown work
                              or replied: a job still waiting for its turn is left alone) or at its TIMEOUT. A bubble
                              still holding only steps is then FINISHED by the channel: deleted where that leaves no
                              trace, closed with one true line where deleting would leave a tombstone (WhatsApp)

Never a step: the wire's own send (it IS the reply arriving as itself). A channel gives its small acts, each its own
business (signing, its API): post(agent, chat, line) -> id, edit(agent, chat, id, line), finish(agent, chat, id, steps),
typing(chat). A failing act is swallowed: progress is decoration, the reply is the delivery.
"""
from __future__ import annotations

import asyncio
import time

from .common import step_line

TIMEOUT = 1800                     # a job is forgotten 30 min after it opened (or after its last reply)
WIRE_SEND = "mcp__astryx__send"    # the wire's send tool: its own steps are the reply arriving, not work to show


def own_send(content: str) -> bool:
    """Is this step the agent's wire send itself ("mcp__astryx__send: …", "mcp__astryx__send done")?"""
    return (content or "").split(":", 1)[0].split(" ", 1)[0] == WIRE_SEND


class Progress:
    def __init__(self, pool_of, *, post, edit, finish, typing=None, timeout: int = TIMEOUT):
        self._pool_of = pool_of        # a callable: the bridge's pool is set after import
        self._post, self._edit, self._finish, self._typing = post, edit, finish, typing
        self.timeout = timeout
        self.jobs: dict[tuple[str, str], dict] = {}

    def open(self, agent: str, chat: str, thread: str) -> None:
        old = self.jobs.get((agent, chat))
        self.jobs[(agent, chat)] = {"agent": agent, "chat": chat, "thread": thread, "opened": time.time(), "ph": None,
                                    "latest": "", "sent": "", "steps": 0, "busy": False, "taken": False}
        if old and old["ph"] is not None:              # a new ask in the same chat: the old bubble is finished, not lost
            asyncio.get_event_loop().create_task(self._end(old))

    def of(self, agent: str) -> list[dict]:
        return [j for (a, _c), j in list(self.jobs.items()) if a == agent]

    async def on_step(self, ev: dict) -> None:
        agent, kind = ev.get("agent", ""), ev.get("kind", "")
        jobs = self.of(agent)
        if not jobs:
            return
        now = time.time()
        for job in [j for j in jobs if now - j["opened"] > self.timeout]:
            await self._close(job)                       # a turn past the timeout: its bubble is finished, never left
        jobs = [j for j in jobs if now - j["opened"] <= self.timeout]
        if kind == "response":                           # a turn ended: the jobs that showed work or replied are done
            for job in jobs:
                if job["ph"] is not None or job["taken"] or job["sent"]:
                    await self._close(job)
            return
        pool = self._pool_of()
        sid = int(ev.get("id", 0))
        row = await pool.fetchrow("SELECT content FROM steps WHERE id=$1 AND agent=$2", sid, agent)
        if not row or own_send(row["content"]):
            return
        for job in jobs:
            line = await step_line(pool, sid, kind, agent=agent, thread=job["thread"])
            if not line:
                continue
            job["latest"], job["steps"] = line, job["steps"] + 1
            if not job["busy"]:
                asyncio.get_event_loop().create_task(self._worker(job))

    async def _worker(self, job: dict) -> None:
        job["busy"] = True
        key = (job["agent"], job["chat"])
        try:
            while job is self.jobs.get(key) and job["latest"] != job["sent"]:
                line = job["latest"]
                try:
                    if job["ph"] is None:
                        job["ph"] = await self._post(job["agent"], job["chat"], line)
                    else:
                        await self._edit(job["agent"], job["chat"], job["ph"], line)
                    if self._typing:
                        await self._typing(job["chat"])
                except Exception:
                    pass
                job["sent"] = line
        finally:
            job["busy"] = False

    async def _settled(self, job: dict) -> None:
        while job["busy"]:                               # let an in-flight post or edit finish first
            await asyncio.sleep(0.2)

    async def take(self, agent: str, chat: str, keep: bool):
        """A reply to `chat` is being delivered: the bubble it may replace (None when there is none)."""
        job = self.jobs.get((agent, chat))
        if not job:
            return None
        await self._settled(job)
        ph = job["ph"]
        if keep:
            self.jobs[(agent, chat)] = {**job, "opened": time.time(), "ph": None, "latest": "", "sent": "", "steps": 0,
                                        "busy": False, "taken": True}
        else:
            self.jobs.pop((agent, chat), None)
        return ph

    async def _close(self, job: dict) -> None:
        await self._settled(job)
        key = (job["agent"], job["chat"])
        if self.jobs.get(key) is job:
            self.jobs.pop(key, None)
        await self._end(job)

    async def _end(self, job: dict) -> None:
        if job["ph"] is not None:                        # a bubble of steps only: the reply, if any, arrived as itself
            try:
                await self._finish(job["agent"], job["chat"], job["ph"], job["steps"])
            except Exception:
                pass
