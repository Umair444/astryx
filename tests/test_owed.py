#!/usr/bin/env python3
"""Oracle: the replies an agent owes people (src/astryx/core/owed.py) and the Stop hook that won't let it go idle with
one owed (owner 11-15). A fixture database (this tree's schema.sql), fixture rows only.
  O1 a person's message that reached the agent since its last turn, with nothing from it on that thread since: owed
  O2 a reply on that thread pays it; a reply on ANOTHER thread does not
  O3 agents, the pulse, a reaction or a poll tap are owed nothing; a message delivered before `since` is not owed now
  O4 a team's ask is owed by its lead only
  O5 told once per message: the second stop ends the turn; a new message is told
  O6 the reminder names who and where, never the message's words
  O9 a federated peer's sender, whatever name its envelope gives, is owed nothing
  O8 in a GROUP, people talking among themselves owe nothing; an @mention, a reply to the agent's message, or a task does
  O7 person_sql is the one table's people (owner, wa-, tg-, dc-, cv-, fe-), and nothing else
Exit 0 · 1 · 77 (no database)."""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_owed", REPO, deps=("psycopg",), env=False)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402
from astryx.core import address, owed as O  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {str(detail)[:300]}"))
    if not ok:
        fails.append(name)


sql = address.person_sql("x", params=False)
arm("O7 person_sql covers the people and only them",
    all(f"'{p}%'" in sql for p in ("wa-", "tg-", "dc-", "cv-", "fe-")) and "x='owner'" in sql and "canvas-" not in sql and "room" not in sql, sql)


def main():
    import psycopg
    with fixture_db() as d, psycopg.connect(d["url"], autocommit=True) as c:
        cur = c.cursor()

        def msg(frm, to, thread, body="please look", intent="chat", ago_min=5, delivery=None):
            import json
            cur.execute("""INSERT INTO messages (from_agent, to_agent, thread, intent, body, status, delivered_at, ts, delivery)
                           VALUES (%s, %s, %s, %s, %s, 'delivered', now() - make_interval(mins => %s), now() - make_interval(mins => %s), %s)
                           RETURNING id""", (frm, to, thread, intent, body, ago_min, ago_min, json.dumps(delivery) if delivery else None))
            return cur.fetchone()[0]

        since = None
        a = msg("owner", "seed", "obs:seed", "SECRET-WORDS fix the menu")
        b = msg("wa-923000000000", "seed", "wa:923000000000@s.whatsapp.net")
        ids = lambda: [r[0] for r in O.owed(cur, "seed", since)]   # noqa: E731
        arm("O1 a person's messages with nothing from the agent since: owed, oldest first", ids() == [a, b], ids())
        msg("seed", "owner", "obs:other", "elsewhere", ago_min=1)
        arm("O2 a reply on ANOTHER thread pays nothing", ids() == [a, b], ids())
        msg("seed", "owner", "obs:seed", "done", ago_min=1)
        arm("O2 a reply on the thread pays it", ids() == [b], ids())
        msg("db", "seed", "t-x", "from an agent")
        msg("pulse", "seed", "", "a watcher")
        msg("wa-923000000000", "seed", "wa:g2", "👍", intent="reaction")
        msg("owner", "seed", "obs:p", "2", intent="poll")
        arm("O3 agents, the pulse, a reaction and a poll tap are owed nothing", ids() == [b], ids())
        cur.execute("SELECT now() - interval '3 minutes'")
        since = cur.fetchone()[0]
        arm("O3 delivered before `since` (the last turn's end): not owed now", ids() == [], ids())
        since = None
        t = msg("owner", "seed", "obs:team", delivery={"team": ["db", "seed"], "lead": "db"})
        t2 = msg("owner", "db", "obs:team", delivery={"team": ["db", "seed"], "lead": "db"})
        arm("O4 a team's ask is owed by its lead only", t not in ids() and t2 in [r[0] for r in O.owed(cur, "db", None)], (ids(), O.owed(cur, "db", None)))
        g = "wa:1203@g.us"
        cur.execute("SELECT now() - interval '30 seconds'")
        since = cur.fetchone()[0]
        msg("wa-111", "seed", g, "lunch at 2?", ago_min=0)
        msg("wa-222", "seed", g, "sure, see you", ago_min=0)
        arm("O8 two people chatting in a routed group: nothing owed", ids() == [], ids())
        m1 = msg("wa-111", "seed", g, "@seed how many loans yesterday?", ago_min=0)
        m2 = msg("wa-222", "seed", g, "and the week?", ago_min=0, delivery={"reply_to_body": "▸ *seed*\nLoans: 189K"})
        m3 = msg("wa-333", "seed", g, "do this", intent="task", ago_min=0)
        msg("wa-444", "seed", g, "email me@seedling.com", ago_min=0)
        msg("wa-555", "seed", g, "about that", ago_min=0, delivery={"reply_to_body": "▸ *db*\nthe seed list for the dashboard"})
        msg("wa-666", "seed", g, "and this", ago_min=0, delivery={"reply_to_body": "seed money for the dashboard"})
        arm("O8 an @mention, a reply to its message, a task: owed; an address, another agent's label, a quote merely naming it: not", ids() == [m1, m2, m3], ids())
        cur.execute("INSERT INTO peers (org, status) VALUES ('peer.example', 'introduced')")
        for who in ("owner", "wa-923001112223"):
            cur.execute("""INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body, status, delivered_at)
                           VALUES (%s, 'peer.example', 'seed', 'o9-peer', 'chat', 'answer me', 'delivered', now())""", (who,))
        arm("O9 a federated peer's 'owner' or 'wa-<n>' (it names its own sender) is no person of ours: owed nothing (medic 12607)",
            ids() == [m1, m2, m3], ids())
        since = None
        with tempfile.TemporaryDirectory() as dd:
            arm("O5 told once per message", O.told(dd, [b, 7]) == [b, 7] and O.told(dd, [b, 7]) == [] and O.told(dd, [b, 9]) == [9])
        rem = O.reminder(O.owed(cur, "seed", None))
        arm("O6 the reminder names who and where, never the words", "wa-923000000000 on wa:923000000000@s.whatsapp.net" in rem and "SECRET" not in rem and "please look" not in rem, rem)


try:
    main()
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    fails.append(f"crashed: {type(e).__name__}")
print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: an agent can't go idle with a reply owed")
sys.exit(1 if fails else 0)
