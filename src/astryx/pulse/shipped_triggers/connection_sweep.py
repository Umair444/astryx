"""The shipped CONNECTION SWEEP: ends an agent's connection when no one has written for its idle time, and says so
(identity-channels P3, owner 11-15/11-16: connect "with a timeout … the agent is told on the wire").

A connection (connect(action=open), the `route` table) lives while someone writes: each message from the chat moves its
expiry to now + idle (bridges/common.connection). Every minute this deletes the expired rows, and each one becomes a
wire message: to the agent that opened it ("timed out with no reply: follow up or let it go"), or, for a link nobody
answered YES to, to whoever asked for the link. The table is the truth: a row past its expiry is already invisible to
the bridges (they read expires_at > now()), so a missed sweep delays only the notice, never re-opens a door.

Install (init.sh's connsweep node and devtools/cog_add_org.py do, from astryx.pulse.shipped_triggers.shims):
  from astryx.pulse.shipped_triggers.connection_sweep import connection_sweep  # noqa: F401
"""
from __future__ import annotations
# imported as a module only (a trigger shim imports it), never run by path: no sys.path preamble and no import inside a
# top-level conditional (org_backup.py says why)
from astryx import trigger
from astryx.core import channels


def notice(r: dict) -> tuple[str, str]:
    """PURE. (to, body) for one expired connection row."""
    title = channels.BY_NAME[r["channel"]].title if r["channel"] in channels.BY_NAME else r["channel"]
    if r["purpose"] == "link":
        return r["opened_by"], (f"[connect] the link of a {title} account to {r['person']} lapsed: no YES came back from "
                                f"it in time. Ask again (connect action=link) if it is still wanted.")
    return r["agent"], (f"[connect] your connection to {r['person'] or r['chat']} on {title} timed out: no one wrote for "
                        f"its idle time. Follow up (connect action=open again) or let it go.")


@trigger("* * * * *",
         note="connection sweep: ends an agent's connection (connect) when no one has written for its idle time, and "
              "tells the agent; a link nobody confirmed lapses, and the asker is told.")
def connection_sweep(ctx):
    for r in ctx.sql("DELETE FROM route WHERE expires_at <= now() RETURNING agent, channel, chat, purpose, person, opened_by"):
        to, body = notice(r)
        ctx.say(to, body, intent="chat")  # the pulse writes it (its ctx.sql refuses a messages write: the old INSERT
        # raised after the DELETE had committed, so every expired connection went with no one told)
    return None
