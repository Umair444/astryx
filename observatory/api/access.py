"""astryx observatory · access: the ONE answer to "may this person do this to this thing" (access-core, owner 11-25:
"the base system should be ready so advance systems can be built"; homes/seed/access-core/DESIGN.md).

A thing is a conversation (a thread) for now: a chat, a canvas's chat, a project's knowledge (project:<id>), a desk.
Everything INSIDE a thread follows the thread: its messages, the files sent on it, its Library artifacts, the work on it.
Verbs: read (see it and what is inside), say (add to it: talk, open a file into its Library, save a version), share and
manage (its maker's, and the owner's: maker_of). A shared thread's reader may also say (canvas parity, owner 11-17).

The viewer is the session's (privacy_gate: request.state), never a name the client sent. The owner and the agents
(no member role) are unscoped. A person's rule today lives in scope.py (the people's own chats, their reach) and
workspace.project_visible (projects); this module is the one door readers ask, so those rules can move behind it.

  await threads(request, ts)       the threads of `ts` this viewer reads
  await may(request, verb, thread) one thread, one verb
  await path_ok(request, path, thread=None)   a file path a member may name: one the SYSTEM attached ([[file:<path>]]
                                   in a message she may read, on `thread` when given, written by an agent of this org
                                   or the owner), or an upload (media/upload/<uuid>, unguessable) sent where she reads.
                                   A person's typed [[file:]] is text, never an attachment: hers, another handle of
                                   hers, a colleague's, a WhatsApp sender's (medic 16376 H5, 16380 HX1).
  await file_author(request, path, thread)    who a Library version of that file is by: the agent that attached it on
                                   that thread, else the viewer. Derived on the server; a client's name never decides.
"""
from __future__ import annotations

import os

from fastapi import Request

VERBS = ("read", "say", "share", "manage")


def _pool(request: Request):
    from observatory.api import workspace as _ws
    return _ws._get_pool() if _ws._get_pool else request.app.state.pool


def scoped(request: Request) -> bool:
    from observatory.api import scope
    return scope.of(request) is not None


def handle(request: Request) -> str:
    from observatory.api import workspace as _ws
    return _ws._me(request) or ""


def _project_ok(request: Request, thread: str) -> bool:
    """A project's knowledge (project:<id>, no wire of its own) is for those who see the project."""
    from observatory.api import workspace as _ws
    return any(p.get("id") == thread[8:] for p in _ws._projects(_ws.account(request)))


async def threads(request: Request, ts) -> set[str]:
    """The threads this viewer reads: a project's knowledge when they see the project; any other, scope.py's rule (a
    member: the threads whose every message is theirs to read)."""
    from observatory.api import scope
    want = {t for t in ts if t}
    proj = {t for t in want if t.startswith("project:") and (not scoped(request) or _project_ok(request, t))}
    rest = {t for t in want if not t.startswith("project:")}
    if rest and scoped(request):
        rest = await scope.threads_ok(_pool(request), request, rest)
    return proj | rest


async def may(request: Request, verb: str, thread: str) -> bool:
    if verb not in VERBS:
        raise ValueError(f"unknown verb {verb!r}")
    if not scoped(request):
        return True
    if verb in ("read", "say"):
        return thread in await threads(request, [thread])
    from observatory.api import workspace as _ws
    me, acct = handle(request), _ws.account(request)
    mine = {k for k in (_canvas_name(me) if me else "", acct or "") if k}   # a registry row names her either way
    return await maker_of(request, thread) in mine                         # share/manage: the maker's


def _canvas_name(me: str) -> str:
    from observatory.api import workspace as _ws
    return _ws.canvas_user(me)


async def maker_of(request: Request, thread: str) -> str | None:
    """Who made a conversation, in canvas_threads' shape ('owner' or a cv-<x>'s <x>): its registry row's user_name;
    a chat with no row, the first person who wrote on it (one maker, never two)."""
    from observatory.api import workspace as _ws
    pool = _pool(request)
    try:
        u = await pool.fetchval("SELECT user_name FROM canvas_threads WHERE thread = $1", thread)
    except Exception:                               # noqa: BLE001 — an estate without canvas_threads: the wire decides
        u = None
    if u:
        return u
    first = await pool.fetchval(   # the first person on it: who wrote first, or whom an agent opened it with (medic 16394)
        f"SELECT CASE WHEN {_ws.human_sql('from_agent')} THEN from_agent ELSE to_agent END FROM messages WHERE thread = $1 "
        f"AND ({_ws.human_sql('from_agent')} OR {_ws.human_sql('to_agent')}) ORDER BY id LIMIT 1", thread)
    return _canvas_name(first) if first else None


def _own_upload(path: str) -> bool:
    from observatory.api import chat as _chat
    return _chat.MEDIA is not None and os.path.realpath(path).startswith(os.path.realpath(_chat.MEDIA / "upload") + os.sep)


async def path_ok(request: Request, path: str, thread: str | None = None) -> bool:
    from observatory.api import scope
    if not path:
        return False
    pool = _pool(request)
    if not scoped(request):
        return bool(await pool.fetchval("SELECT 1 FROM messages WHERE strpos(body, $1) > 0 LIMIT 1", f"[[file:{path}]]"))
    from observatory.api import workspace as _ws
    await scope.load(pool, request)
    return bool(await pool.fetchval(
        f"SELECT 1 FROM messages WHERE strpos(body, $1) > 0 AND {scope.sql('$2', '$3', '$4')} "
        "AND ($5 OR (coalesce(from_org, 'local') = 'local' AND (from_agent = ANY($6::text[]) OR from_agent = 'owner'))) "
        "AND ($7::text IS NULL OR thread = $7) LIMIT 1",
        f"[[file:{path}]]", *scope.args(request), _own_upload(path), sorted(set(_ws._roster())), thread))


async def file_author(request: Request, path: str, thread: str) -> str:
    from observatory.api import workspace as _ws
    roster = sorted(set(_ws._roster()))
    a = await _pool(request).fetchval(
        "SELECT from_agent FROM messages WHERE thread = $1 AND strpos(body, $2) > 0 AND from_agent = ANY($3::text[]) "
        "AND coalesce(from_org, 'local') = 'local' ORDER BY id DESC LIMIT 1", thread, f"[[file:{path}]]", roster)
    return a or handle(request) or "owner"


async def message_author(request: Request, msg_id: int | None, thread: str) -> str:
    """Who words taken from a message are by (a turn opened as a document): that message's agent when it is on the
    thread, else the viewer."""
    from observatory.api import workspace as _ws
    if msg_id:
        a = await _pool(request).fetchval(
            "SELECT from_agent FROM messages WHERE id = $1 AND thread = $2 AND coalesce(from_org, 'local') = 'local'",
            msg_id, thread)
        if a and a in set(_ws._roster()):
            return a
    return handle(request) or "owner"
