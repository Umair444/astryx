"""astryx bridges · progress — THE LIVE STEPS BUBBLE, one lifecycle for every channel.

A person asks an agent in a chat; while the agent works, one message in that chat shows its latest step, edited in
place. Each bridge used to keep its own copy of this (whatsapp, telegram, discord), and the copies drifted: a reply
kept the job alive so later work could show (owner 11-15), and the reply's OWN delivery step ("send done") then opened
a fresh bubble that no rule ever closed (owner 11-16, wm_ai). So the lifecycle lives here once:

  open(agent, chat, thread)   a person's ask on a route that shows steps: the agent's job for that chat
  on_step(ev)                 a step of a turn THIS chat opened (common.step_line's scope) updates the line; one
                              serialized writer per job, always pushing the newest line and skipping the ones between
  take(agent, chat, keep)     a reply is being delivered: the bubble to edit the reply into (or None). The job stays,
                              bubble-less, when `keep`, so further work for this chat opens a new bubble under the reply
  the turn's end              (its 'response' step) closes the job: a bubble still holding only steps is removed

Two things are never a step: the wire's own send (it IS the reply: the reply arrives as itself) and anything after the
job's TIMEOUT. A channel gives four small acts, each its own business (signing, its API): post(agent, chat, line) -> id,
edit(agent, chat, id, line), remove(chat, id), typing(chat). A failing act is swallowed: progress is decoration, the
reply is the delivery.
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
    def __init__(self, pool_of, *, post, edit, remove, typing=None, timeout: int = TIMEOUT):
        self._pool_of = pool_of        # a callable: the bridge's pool is set after import
        self._post, self._edit, self._remove, self._typing = post, edit, remove, typing
        self.timeout = timeout
        self.jobs: dict[str, dict] = {}

    def open(self, agent: str, chat: str, thread: str) -> None:
        self.jobs[agent] = {"chat": chat, "thread": thread, "opened": time.time(),
                            "ph": None, "latest": "", "sent": "", "busy": False}

    async def on_step(self, ev: dict) -> None:
        agent, kind = ev.get("agent", ""), ev.get("kind", "")
        job = self.jobs.get(agent)
        if not job:
            return
        if time.time() - job["opened"] > self.timeout:
            self.jobs.pop(agent, None)
            return
        if kind == "response":                       # the turn ended: whatever it said has been delivered (or never will)
            await self._close(agent, job)
            return
        pool = self._pool_of()
        row = await pool.fetchrow("SELECT content FROM steps WHERE id=$1 AND agent=$2", int(ev.get("id", 0)), agent)
        if not row or own_send(row["content"]):
            return
        line = await step_line(pool, int(ev.get("id", 0)), kind, agent=agent, thread=job["thread"])
        if not line:
            return
        job["latest"] = line
        if not job["busy"]:
            asyncio.get_event_loop().create_task(self._worker(agent, job))

    async def _worker(self, agent: str, job: dict) -> None:
        job["busy"] = True
        try:
            while job is self.jobs.get(agent) and job["latest"] != job["sent"]:
                line = job["latest"]
                try:
                    if job["ph"] is None:
                        job["ph"] = await self._post(agent, job["chat"], line)
                    else:
                        await self._edit(agent, job["chat"], job["ph"], line)
                    if self._typing:
                        await self._typing(job["chat"])
                except Exception:
                    pass
                job["sent"] = line
        finally:
            job["busy"] = False

    async def _settled(self, job: dict) -> None:
        while job["busy"]:                           # let an in-flight post or edit finish first
            await asyncio.sleep(0.2)

    async def take(self, agent: str, chat: str, keep: bool):
        """A reply to `chat` is being delivered: the bubble it may replace (None when there is none for this chat)."""
        job = self.jobs.get(agent)
        if not job or job["chat"] != chat:
            return None
        await self._settled(job)
        ph = job["ph"]
        if keep:
            self.jobs[agent] = {**job, "opened": time.time(), "ph": None, "latest": "", "sent": "", "busy": False}
        else:
            self.jobs.pop(agent, None)
        return ph

    async def _close(self, agent: str, job: dict) -> None:
        await self._settled(job)
        if self.jobs.get(agent) is job:
            self.jobs.pop(agent, None)
        if job["ph"] is not None:                    # a bubble of steps only: the reply, if any, arrived as itself
            try:
                await self._remove(job["chat"], job["ph"])
            except Exception:
                pass
