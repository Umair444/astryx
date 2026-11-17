"""astryx observatory · what a member may read of the wire: the agents they reach (owner 11-17: "a member to use only
the selected agents"), and of the people's own chats only theirs (owner 11-17, msg 12970: a normal chat is the person's
who started it; the owner reads everything).

privacy_gate (main.py) resolves the viewer once per /api request: request.state.reach (None = every agent: the owner,
a whole-org member; else the names they reach) and request.state.me (their wire handle). Every wire read a member can
make asks THIS module, in its POSITIVE form, and a message passes both arms:
  REACH  it is to or from an agent they reach, or to or from them. Never the complement ("everything but the agents
         outside"): a wire name that is no charter (a peer, a person, a retired or renamed agent) would show its whole
         history to every scoped member (medic 12822).
  OWN    it is not on a person's own chat (PERSONAL: a normal chat, a canvas chat), or that chat is open to them: they
         are a party of it (they wrote or were written to on it: workspace.party's rule), or it belongs to a project
         they see (workspace.project_visible), or it is the conversation of a canvas they see (cv.sees: its maker and
         whom it is shared with, owner 11-17 12979). A desk (obs:<agent>) is shared: whoever opens the agent reads it.
The owner and the agents themselves (no member role) are unscoped.

  of(request)              None (unscoped) or (reach | None, me)
  await load(pool, request)   the threads OWN opens to this viewer (request.state.open), read once per request
  sql(r, m, o)             the message predicate over $r (text[] | NULL = every agent), $m (text), $o (text[]: open)
  args(request)            (reach, me, open) for sql(): call load() first
  steps_sql(o, s)          a step a viewer may read: its turn was not opened on a personal thread closed to them
  await steps_open(pool, request)   that predicate's $o: None (unscoped: every step) or the open threads
  message_ok(request, d)   the same predicate on a feed event or a row dict ({from, to, thread} or {from_agent, ...})
  threads_ok(pool, request, threads)   the threads every one of whose messages passes (a thread with none is not)
"""
from __future__ import annotations

from observatory.api.members import MEMBER_ROLES   # the people this module scopes

PERSONAL = ("chat:", "cv:")          # a person's own chats; every other thread (a desk, the org's work) is shared


def personal_sql(col: str = "thread") -> str:
    return "(" + " OR ".join(f"{col} LIKE '{p}%'" for p in PERSONAL) + ")"


PERSONAL_SQL = personal_sql()


def of(request) -> tuple[list[str] | None, str] | None:
    reach = getattr(request.state, "reach", set())
    if reach is None and getattr(request.state, "role", None) not in MEMBER_ROLES:
        return None
    return (None if reach is None else sorted(reach)), getattr(request.state, "me", None) or ""


def personal(thread: str | None) -> bool:
    return bool(thread) and thread.startswith(PERSONAL)


async def load(pool, request) -> set[str]:
    """The personal threads open to this viewer: theirs (a party) and their visible projects'. A read that fails opens
    none (closed): a member never sees another's chat on a database blip, only misses their own until it answers."""
    if (got := getattr(request.state, "open", None)) is not None:
        return got
    from observatory.api import workspace as _ws
    me, out = getattr(request.state, "me", None) or "", set()
    try:
        if me:
            out = {r["thread"] for r in await pool.fetch(
                "SELECT DISTINCT thread FROM messages WHERE (from_agent = $1 OR to_agent = $1) "
                f"AND {PERSONAL_SQL}", me)}
        out |= {t for p in _ws._projects(_ws.account(request)) for t in (p.get("threads") or []) if isinstance(t, str)}
    except Exception:                               # noqa: BLE001 — closed, as the docstring says
        out = set()
    from astryx.core import canvas as _cv
    from observatory.api import ws_canvas as _wc
    try:
        out |= {_wc.thread_of(r["id"]) for r in await pool.fetch(
            f"SELECT id FROM canvases WHERE {_cv.sees_sql('$1', '$2')}", *_wc.keys(request))}
    except Exception:                               # noqa: BLE001 — no canvas tables (or a blip): no canvas opens
        pass
    request.state.open = out
    return out


def args(request) -> tuple[list[str] | None, str, list[str]]:
    reach, me = of(request) or (None, "")
    return reach, me, sorted(getattr(request.state, "open", None) or ())


def sql(r: str, m: str, o: str) -> str:
    """An agent arm counts only for THIS org's agent: a peer names its own envelope (gateway.py), so a peer calling
    itself after an agent here is not that agent (medic 12831)."""
    return (f"(({r}::text[] IS NULL OR (from_agent = ANY({r}::text[]) AND coalesce(from_org, 'local') = 'local') OR "
            f"(to_agent = ANY({r}::text[]) AND coalesce(to_org, 'local') = 'local') OR from_agent = {m} OR to_agent = {m})"
            f" AND NOT ({PERSONAL_SQL} AND NOT thread = ANY({o}::text[])))")


def steps_sql(o: str, s: str = "steps") -> str:
    """The ONE rule for a step's content, for every steps reader: /api/steps, an agent's profile, the briefing, the
    chat's work pane (medic 12975). A step's turn opened on its messages: meta.turn_msgs, written with the step while
    the turn runs, and its turn's input once the turn is linked; a step whose work served several chats at once
    (meta.many, hooks/step.py) is theirs too. $o NULL: unscoped."""
    arr = lambda k: f"COALESCE(CASE WHEN jsonb_typeof({s}.meta->'{k}') = 'array' THEN {s}.meta->'{k}' END, '[]'::jsonb)"  # noqa: E731
    msgs = (f"ARRAY(SELECT x::bigint FROM jsonb_array_elements_text({arr('turn_msgs')} || {arr('many')}) x "
            f"WHERE x ~ '^[0-9]{{1,18}}$')")
    return (f"({o}::text[] IS NULL OR NOT EXISTS (SELECT 1 FROM messages m WHERE (m.id = ANY({msgs}) OR m.id = "
            f"(SELECT t.input_msg_id FROM turns t WHERE t.id = {s}.turn_id)) "
            f"AND {personal_sql('m.thread')} AND NOT m.thread = ANY({o}::text[])))")


async def steps_open(pool, request) -> list[str] | None:
    return None if of(request) is None else sorted(await load(pool, request))


def message_ok(request, d: dict) -> bool:
    """The feed's copy of sql(), on one event. An event to or from the viewer on a personal thread opens that thread
    for the rest of the connection (a chat they start while watching: the agents' handoffs on it then pass too)."""
    s = of(request)
    if s is None:
        return True
    reach, me = s
    f, t, th = d.get("from", d.get("from_agent")), d.get("to", d.get("to_agent")), d.get("thread")
    mine = bool(me) and me in (f, t)
    here = lambda k: (d.get(k) or "local") == "local"   # noqa: E731 — this org's agent, never a peer's namesake
    if not (reach is None or (f in reach and here("from_org")) or (t in reach and here("to_org")) or mine):
        return False
    if not personal(th):
        return True
    opened = getattr(request.state, "open", None)
    if opened is None:
        opened = request.state.open = set()
    if mine:
        opened.add(th)
    return th in opened


async def threads_ok(pool, request, threads) -> set[str]:
    want = sorted({t for t in threads if t})
    s = of(request)
    if s is None:
        return set(want)
    if not want:
        return set()
    await load(pool, request)
    rows = await pool.fetch("SELECT thread FROM messages WHERE thread = ANY($1::text[]) GROUP BY thread "
                            f"HAVING bool_and({sql('$2', '$3', '$4')})", want, *args(request))
    return {r["thread"] for r in rows}
