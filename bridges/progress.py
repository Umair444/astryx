"""astryx bridges · progress — THE LIVE STEPS BUBBLE, one lifecycle for every channel.

A person asks an agent in a chat; while the agent works, one message in that chat shows its latest step, edited in
place. Each bridge used to keep its own copy of this (whatsapp, telegram, discord), and the copies drifted: a reply
kept the job alive so later work could show (owner 11-15), and the reply's OWN delivery step ("send done") then opened
a fresh bubble that no rule ever closed (owner 11-16, wm_ai). So the lifecycle lives here once.

A JOB is one agent's work for one chat's REQUEST, keyed (agent, chat): an agent serving two groups at once has two
jobs, and one never orphans the other's bubble (medic 12418). It lives as long as the request does, not one turn of
the agent (owner 11-18, homes/seed/progress-requests/DESIGN.md):
  open(agent, chat, thread)   a person's ask on a route that shows steps. A follow-up in the same chat while its job
                              is live joins it (no "finished", no new bubble). When another chat's job of the agent is
                              live, the new one says at once that it is queued (the agent may be inside a long tool)
  on_step(ev)                 a step for THIS chat's request (common.scoped_line's scope) updates its line; a step for
                              another chat's request says only that this one waits, is acked, or shares the agent
                              (no content), and only until the chat has been answered (after a reply, filler is
                              noise). One serialized writer per job, always pushing the newest line
  take(agent, chat, keep)     a reply is being delivered: the bubble to edit the reply into (or None). With `keep` the
                              job stays, bubble-less, so further work for that chat opens a new bubble under the reply
  FINISH                      at a turn's end (the 'response' step, whose meta the hook stamps) a job is closed unless
                              its request still has background work out (its bubble says so and it stays, up to
                              PENDING), still waits, or the turn goes on (`continues`: an owed reply). A job still
                              waiting for its turn (nothing shown, no reply) is left alone. Idle past its TIMEOUT
                              (counted from its last line), it closes. A bubble still holding only steps is then
                              FINISHED by the channel: deleted where that leaves no trace, closed with one true line
                              where deleting would leave a tombstone (WhatsApp). A step for a job closed in the last
                              REOPEN seconds reopens it: a false "finished" never stands
  edit window                 a channel whose messages can be edited only for so long (WhatsApp: 15 min) gets a fresh
                              bubble before the old one ages out; the old one says "continued below"

Never a step: the wire's own send (it IS the reply arriving as itself). A channel gives its small acts, each its own
business (signing, its API): post(agent, chat, line) -> id, edit(agent, chat, id, line), finish(agent, chat, id, steps),
typing(chat). A failing act is swallowed: progress is decoration, the reply is the delivery.
"""
from __future__ import annotations

import asyncio
import json
import time

from .common import scoped_line

TIMEOUT = 1800                     # a job is forgotten 30 min after its last line (or its opening, or its last reply)
PENDING = 12 * 3600                # a job whose request has background work out is kept this long
REOPEN = 120                       # a step for a job closed this recently reopens it
QUEUE_HINT = 900                   # another chat's job showed a line this recently: a new job says it is queued at once
WIRE_SEND = "mcp__astryx__send"    # the wire's send tool: its own steps are the reply arriving, not work to show
QUEUED = "◌ queued: finishing another request first; yours is next"
BACKGROUND = "◌ waiting on background work"
STALE = "◌ no update for 12 h"
CONTINUED = "↓ continued below"


def own_send(content: str) -> bool:
    """Is this step the agent's wire send itself ("mcp__astryx__send: …", "mcp__astryx__send done")?"""
    return (content or "").split(":", 1)[0].split(" ", 1)[0] == WIRE_SEND


class Progress:
    def __init__(self, pool_of, *, post, edit, finish, typing=None, timeout: int = TIMEOUT,
                 edit_window: int | None = None, finish_keeps: bool = False):
        self._pool_of = pool_of        # a callable: the bridge's pool is set after import
        self._post, self._edit, self._finish, self._typing = post, edit, finish, typing
        self.timeout = timeout
        self.edit_window = edit_window          # seconds a posted message stays editable (None: forever)
        self.finish_keeps = finish_keeps        # a finished bubble is still there to edit back (WhatsApp) or gone
        self.jobs: dict[tuple[str, str], dict] = {}
        self.closed: dict[tuple[str, str], tuple[dict, float]] = {}

    @staticmethod
    def _new(agent: str, chat: str, thread: str) -> dict:
        now = time.time()
        return {"agent": agent, "chat": chat, "thread": thread, "opened": now, "last": now, "ph": None, "posted": 0.0,
                "latest": "", "sent": "", "steps": 0, "busy": False, "taken": False, "pending": False}

    def open(self, agent: str, chat: str, thread: str) -> None:
        key, now = (agent, chat), time.time()
        old = self.jobs.get(key)
        if old and now - old["last"] <= self.timeout:
            return                                       # a follow-up in a live conversation: the same job
        job = self.jobs[key] = self._new(agent, chat, thread)
        self.closed.pop(key, None)
        if old and old["ph"] is not None:                # an idle job's bubble is finished, not lost
            asyncio.get_event_loop().create_task(self._end(old))
        if any(j is not job and j["sent"] and now - j["last"] < QUEUE_HINT for j in self.of(agent)):
            self._show(job, QUEUED, count=False)         # the agent is mid-way through another chat's request

    def of(self, agent: str) -> list[dict]:
        return [j for (a, _c), j in list(self.jobs.items()) if a == agent]

    def _show(self, job: dict, line: str, count: bool = True) -> None:
        job["latest"], job["last"] = line, time.time()
        job["steps"] += count
        if not job["busy"]:
            asyncio.get_event_loop().create_task(self._worker(job))

    async def on_step(self, ev: dict) -> None:
        agent, kind = ev.get("agent", ""), ev.get("kind", "")
        now = time.time()
        for job in self.of(agent):
            if now - job["last"] > (PENDING if job["pending"] else self.timeout):
                await self._close(job, stale=job["pending"], reopenable=False)   # idle past its bound: never left
        for key in [k for k, (_j, at) in self.closed.items() if now - at > REOPEN]:
            self.closed.pop(key, None)
        jobs = self.of(agent)
        recent = [j for (a, c), (j, _at) in list(self.closed.items()) if a == agent and (a, c) not in self.jobs]
        if not jobs and not recent:
            return
        pool = self._pool_of()
        sid = int(ev.get("id", 0))
        if kind == "response":                           # a turn ended: close what it finished
            end = await self._end_of(pool, sid, agent)
            for job in jobs:
                if end["continues"] or job["thread"] in end["hold"]:
                    continue                             # the turn goes on, or this request still waits
                if job["thread"] in end["pending"]:
                    job["pending"] = True
                    self._show(job, BACKGROUND, count=False)
                elif job["ph"] is not None or job["taken"] or job["sent"]:
                    await self._close(job)
            return
        row = await pool.fetchrow("SELECT content FROM steps WHERE id=$1 AND agent=$2", sid, agent)
        if not row or own_send(row["content"]):
            return
        for job in jobs + recent:
            role, line = await scoped_line(pool, sid, kind, agent=agent, thread=job["thread"])
            if not line or (role != "serves" and job["taken"]):
                continue                                 # an answered chat gets its own work again, never filler
            if job in recent:
                job = self._reopen(job)
            job["pending"] = False
            self._show(job, line)

    async def _end_of(self, pool, sid: int, agent: str) -> dict:
        """The turn's end as the hook stamped it: continues, and the threads with background work out (pending) or
        still waiting (hold)."""
        out = {"continues": False, "pending": set(), "hold": set()}
        try:
            r = await pool.fetchrow("SELECT meta FROM steps WHERE id=$1 AND agent=$2", sid, agent)
            m = json.loads(r["meta"]) if r and isinstance(r["meta"], str) else ((r or {}).get("meta") or {})
            out["continues"] = bool(m.get("continues"))
            ids = {k: [int(x) for x in (m.get(k) or [])][:20] for k in ("pending", "waiting", "acked")}
            every = sorted({i for v in ids.values() for i in v})
            if every:
                th = {x["id"]: x["thread"] for x in await pool.fetch(
                    "SELECT id, thread FROM messages WHERE id = ANY($1::bigint[])", every)}
                out["pending"] = {th.get(i) for i in ids["pending"]} - {None}
                out["hold"] = {th.get(i) for i in ids["waiting"] + ids["acked"]} - {None}
        except Exception:                                # unreadable: today's rule (close what showed work)
            pass
        return out

    def _reopen(self, job: dict) -> dict:
        key = (job["agent"], job["chat"])
        self.closed.pop(key, None)
        job = {**job, "busy": False, "sent": "", "ph": job["ph"] if self.finish_keeps else None}
        self.jobs[key] = job
        return job

    async def _worker(self, job: dict) -> None:
        job["busy"] = True
        key = (job["agent"], job["chat"])
        try:
            while job is self.jobs.get(key) and job["latest"] != job["sent"]:
                line = job["latest"]
                try:
                    if job["ph"] is not None and self.edit_window and time.time() - job["posted"] > self.edit_window - 60:
                        try:                             # about to age out: say so, and carry on in a fresh bubble
                            await self._edit(job["agent"], job["chat"], job["ph"], CONTINUED)
                        except Exception:
                            pass
                        job["ph"] = None
                    if job["ph"] is None:
                        job["ph"], job["posted"] = await self._post(job["agent"], job["chat"], line), time.time()
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
        """A reply to `chat` is being delivered: the bubble to edit the reply into (or None: none, or too old to
        edit, so the reply goes as a message of its own)."""
        job = self.jobs.get((agent, chat))
        if not job:
            return None
        await self._settled(job)
        ph = job["ph"]
        if ph is not None and self.edit_window and time.time() - job["posted"] > self.edit_window - 30:
            ph = None
        if keep:
            now = time.time()
            self.jobs[(agent, chat)] = {**job, "opened": now, "last": now, "ph": None, "posted": 0.0, "latest": "",
                                        "sent": "", "steps": 0, "busy": False, "taken": True, "pending": False}
        else:
            self.jobs.pop((agent, chat), None)
        return ph

    async def _close(self, job: dict, stale: bool = False, reopenable: bool = True) -> None:
        """Forget a job and finish its bubble. Only a turn's end can be a false "finished" (the hook died before it
        stamped `continues`), so only that close may be reopened by a later step; an idle timeout is final."""
        await self._settled(job)
        key = (job["agent"], job["chat"])
        if self.jobs.get(key) is job:
            self.jobs.pop(key, None)
        if stale and job["ph"] is not None:              # background work never reported back: say that, not "finished"
            try:
                await self._edit(job["agent"], job["chat"], job["ph"], STALE)
            except Exception:
                pass
            return
        await self._end(job)
        if reopenable:
            self.closed[key] = (job, time.time())

    async def _end(self, job: dict) -> None:
        if job["ph"] is not None:                        # a bubble of steps only: the reply, if any, arrived as itself
            try:
                await self._finish(job["agent"], job["chat"], job["ph"], job["steps"])
            except Exception:
                pass
