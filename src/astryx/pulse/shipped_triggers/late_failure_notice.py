"""The shipped LATE FAILURE NOTICE: tells an agent when a message it sent to a person failed AFTER its send stopped
waiting (owner 11-19, medic heartbeat).

The send tool waits SEND_WAIT for the bridge's receipt (channel/server.mjs); a delivery slower than that returns "still in
flight", and the agent moves on. A file to WhatsApp can take longer, and when its upload then fails the row goes dead
with no one told: 11-18 merchant told a group "plus a new Excel (msg 13979)" while WhatsApp's media upload had failed,
and 10-28 lending's file died the same way. Every minute this reads the rows that went dead since its last run, after
the wait, from an agent, and tells that agent on the wire what failed and where, so it can resend or say so.

The table is the truth: `since` is the newest delivered_at seen (a row is judged when it goes dead, not when it was
written, so a slow row is never skipped). A first run starts from now: history is not re-announced.

Install (init.sh's latefail node and devtools/cog_add_org.py do, from astryx.pulse.shipped_triggers.shims):
  from astryx.pulse.shipped_triggers.late_failure_notice import late_failure_notice  # noqa: F401
"""
from __future__ import annotations
# imported as a module only (a trigger shim imports it), never run by path: no sys.path preamble and no import inside a
# top-level conditional (org_backup.py says why)
import re

from astryx import trigger
from astryx.core import address

SEND_WAIT = 20                          # seconds: channel/server.mjs's receipt wait (its `deadline`)
BATCH = 50

DEAD_SQL = ("SELECT id, from_agent, to_agent, thread, delivered_at, delivery->>'error' AS error FROM messages "
            "WHERE status = 'dead' AND delivered_at > %s AND delivered_at - ts >= make_interval(secs => %s) "
            "ORDER BY delivered_at LIMIT %s")


def sender(name: str | None) -> bool:
    """PURE. Is `name` an agent of ours (no person, no channel, not the pulse itself)?"""
    return bool(name) and name != "pulse" and address.surface_of(name) is None


def notice(r: dict) -> str:
    """PURE. The wire body for one late failure: what, to whom, where, and why (a URL in the error is cut: it can carry
    a signed upload token)."""
    why = re.sub(r"https?://\S+", "<url>", str(r.get("error") or "no reason recorded"))[:200]
    where = f" on thread {r['thread']}" if r.get("thread") else ""
    return (f"[delivery] your msg {r['id']} to {r['to_agent']}{where} FAILED after your send returned \"still in "
            f"flight\": {why}. What was sent before the failure (often the text) may have arrived; what failed did "
            f"not. Resend it, or tell them it didn't arrive.")


@trigger("* * * * *",
         note="late failure notice: tells an agent when a message it sent failed after its send stopped waiting "
              "(\"still in flight\"), so a file the person never got is resent or named.")
def late_failure_notice(ctx):
    since = ctx.state.get("since")
    if since is None:                    # a first run: from now on, never the history
        ctx.state["since"] = str(ctx.sql("SELECT now() AS t")[0]["t"])
        return None
    rows = ctx.sql(DEAD_SQL, (since, SEND_WAIT, BATCH))
    told = 0
    for r in rows:
        if sender(r["from_agent"]):
            ctx.say(r["from_agent"], notice(r), intent="chat")
            told += 1
    if rows:
        ctx.state["since"] = str(rows[-1]["delivered_at"])
    ctx.log(f"{len(rows)} late failures, {told} told")
    return None
