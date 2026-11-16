"""astryx · owed — the replies an agent owes people (owner 11-15: "you never replied, so the counter was on for 20
minutes … agents can sometimes forget to reply; it's not a good experience").

A reply is OWED for a person's message (said or asked: intent chat or task; a reaction or a poll tap is not) to an agent (address.person_sql: owner, a WhatsApp, Telegram or Discord sender,
a signed-in member, a frontend) that reached it, when the agent has written nothing on that thread since. In a GROUP, only what addresses the agent is owed
(an @mention, a reply to its message, a task); people talking among themselves owe it nothing. A team's ask is owed by
its LEAD only (messages.delivery {team, lead}, bridges/common.team_stamp): the helpers answer the lead.

The one reader for every place that needs it: the Stop hook (an agent can't go idle with a reply owed: it is told
once per message and decides; hooks/step.py) and the chat's line ("finished without replying").
"""
from __future__ import annotations

import re

from astryx.core import address

BODY = 160
SIGN = "\u25b8 "        # bridges/common.SIGN: the label line every shared-identity channel signs an agent's message with
# a GROUP conversation: a WhatsApp group, a Telegram group (a negative chat id), a Discord channel. There, people talk
# among themselves, and a message is owed only when it ADDRESSES the agent (medic 12441): an @mention of its name, a
# reply to one of its messages (their quoted first line is its label), a task, or a team ask it leads
GROUP = "m.thread LIKE 'wa:%%@g.us' OR m.thread LIKE 'tg:-%%' OR m.thread LIKE 'dc:%%'"


def owed(cur, agent: str, since) -> list[tuple]:
    """(id, thread, from_agent, body excerpt) of each owed reply of `agent`, among messages delivered after `since`
    (a timestamp; None = the last day), oldest first. The name goes into a regex QUOTED (a '.' or '-' in it is
    itself), and a reply is the agent's only when the quoted message's first line is its LABEL (bridges/common.signed:
    SIGN, the name, a channel's bold), never the name anywhere in it ("dashboard" is not db's)."""
    rx = re.escape(agent)
    cur.execute(f"""
        SELECT m.id, m.thread, m.from_agent, left(m.body, {BODY}) FROM messages m
         WHERE m.to_agent = %s AND {address.person_sql('m.from_agent', org='m.from_org')} AND m.status = 'delivered'
           AND m.intent IN ('chat', 'task')
           AND (m.intent = 'task' OR m.delivery ? 'lead' OR NOT ({GROUP}) OR m.body ~* ('(^|[^[:alnum:]_])@' || %s || '([^[:alnum:]_-]|$)')
                OR split_part(m.delivery->>'reply_to_body', chr(10), 1) ~ ('^' || %s || '\\**' || %s || '\\**[[:space:]]*$'))
           AND m.delivered_at > coalesce(%s, now() - interval '1 day')
           AND coalesce(m.delivery->>'lead', %s) = %s
           AND NOT EXISTS (SELECT 1 FROM messages r WHERE r.from_agent = %s AND r.thread IS NOT DISTINCT FROM m.thread
                                                       AND r.id > m.id)
         ORDER BY m.id""", (agent, rx, re.escape(SIGN), rx, since, agent, agent, agent))
    return cur.fetchall()


def told(marks_dir: str, ids) -> list:
    """The ids not yet told: one empty 0600 file per message in the agent's own 0700 directory, made with O_EXCL, so a
    message is told ONCE however many times the agent stops (the second stop ends the turn). Older marks are pruned."""
    import os
    import time
    new = []
    try:
        for n in os.listdir(marks_dir):
            p = os.path.join(marks_dir, n)
            if n.isdigit() and time.time() - os.lstat(p).st_mtime > 2 * 86400:
                os.unlink(p)
    except OSError:
        return []
    for i in ids:
        try:
            os.close(os.open(os.path.join(marks_dir, str(int(i))), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
            new.append(i)
        except (OSError, ValueError):
            pass
    return new


def reminder(rows) -> str:
    """The words the agent reads when it would stop with replies owed: who, where, and the two ways out."""
    who = "; ".join(f"{frm} on {th or 'no thread'} (#{mid})" for mid, th, frm, _b in rows)
    n = len(rows)
    return (f"Before you stop: {n} message{'s' if n != 1 else ''} from {'people' if n != 1 else 'a person'} "
            f"{'have' if n != 1 else 'has'} no reply from you yet: {who}. Reply on that thread with send, or say when "
            f"you will. If one needs no answer from you, end your turn again: you are told once per message.")
