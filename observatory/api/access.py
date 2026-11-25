"""astryx observatory · access: the ONE answer to "may this person do this to this thing" (access-core, owner 11-25:
"the base system should be ready so advance systems can be built"; homes/seed/access-core/DESIGN.md).

A thing is a conversation (a thread) for now: a chat, a canvas's chat, a project's knowledge (project:<id>), a desk.
Everything INSIDE a thread follows the thread: its messages, the files sent on it, its Library artifacts, the work on it.
Verbs: read (see it and what is inside), say (add to it: talk, open a file into its Library, save a version), share and
manage (the maker's: chat sharing, step 2). A shared thread's reader may also say (canvas parity, owner 11-17).

The viewer is the session's (privacy_gate: request.state), never a name the client sent. The owner and the agents
(no member role) are unscoped. A person's rule today lives in scope.py (the people's own chats, their reach) and
workspace.project_visible (projects); this module is the one door readers ask, so those rules can move behind it.

  await threads(request, ts)       the threads of `ts` this viewer reads
  await may(request, verb, thread) one thread, one verb
  author_ok(request, author)       a name a viewer may sign a Library version with: anyone for the unscoped; a
                                   member her own handle or an agent's (the file's sender), never 'owner' or another
                                   person
"""
from __future__ import annotations

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
    return False                                   # share/manage: the maker's (chat sharing, step 2)


def author_ok(request: Request, author: str) -> bool:
    if not scoped(request):
        return True
    from observatory.api import workspace as _ws
    return author == handle(request) or author in set(_ws._roster())
