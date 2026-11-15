#!/usr/bin/env python3
"""Oracle: the mind (src/astryx/mind/mind.py) wakes only who is free to think, and keeps numbers out of what it quotes.

    venv/bin/python tests/test_mind.py

A fixture database (this tree's schema.sql; the mind's own tables in its store), fixture rows only, nothing live. The
agents are a fixed set here (mind.is_agent is seated): a, b are agents; nobody else is. Arms, in medic 12260's order:
  W1 LIVENESS IS THE STEPS': an agent with a fresh step and an old turn end is at work, never woken; with no fresh step it is
  W2 THE TARGET IS AN AGENT: pressure under `owner`, an unknown name or a personal-tier agent never wakes; a note as one is refused
  W3 A NUMBER BY ITS SHAPE: digits typed with dashes, spaces or brackets are masked; times, counts and versions are not
  W4 FASTING: no energy reading, or a reading over either line, wakes nobody
  W5 SOMEONE WAITING: an unanswered human message to the agent (within a day) wakes nobody; once answered, it may wake
  W6 REST AND BACK-OFF: the same agent isn't woken twice within REST_H; an itch's wait doubles with each think
  W7 ONE WAKE PER TICK, across agents
  W8 an itch thought about MAX_THINKS times is let go by the mind itself
  W9 an agent can't let another agent's itch go; the caller is bound to its shell's ASTRYX_AGENT
  W11 THE SAME SHAPE: a call's fingerprint repeated by an agent is one itch, naming the other agents who made it
  W10 a thought that isn't ONE sentence is refused; a kept idea reaches org-news with its numbers masked
Exit 0 · 1 · 77 (no database).
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_mind", REPO, deps=("psycopg",), env=False)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402
from astryx.mind import mind as M  # noqa: E402

fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {str(detail)[:300]}"))
    if not ok:
        fails.append(name)


M.is_agent = lambda n: n in ("a", "b")
os.environ.pop("ASTRYX_AGENT", None)

print("W3 a number by its shape")
shapes = ["0300-123-4567", "0300 1234 567", "1234 5678 9012 3456", "+92 (300) 123.4567", "call 03001234567 now"]
arm("W3 digits joined by dashes, spaces, brackets or dots are masked (no 7 digits left)",
    all(sum(ch.isdigit() for ch in M.mask(x)) < 7 for x in shapes), [M.mask(x) for x in shapes])
keep = ["at 21:31, 14 calls", "v1.2.3", "idle 396 min", "3 of 12 agents"]
arm("W3 times, counts and versions stay", all(M.mask(x) == x for x in keep), [M.mask(x) for x in keep])


def main():
    import psycopg
    from psycopg.rows import dict_row
    with fixture_db() as d, psycopg.connect(d["url"], autocommit=True, row_factory=dict_row) as c:
        M.ensure(c)
        T = M._t

        def reset():
            c.execute(f"TRUNCATE {T('itch')}, {T('insight')}, {T('use')}")
            c.execute("DELETE FROM messages"); c.execute("DELETE FROM steps"); c.execute("DELETE FROM turns")

        def turn(agent, ended_min_ago, d7=10, h5=10):
            # the two percentages are GENERATED from usage_snapshot (schema.sql): the reading is written as the hook writes it
            c.execute("""INSERT INTO turns (agent, started_at, ended_at, usage_snapshot)
                         VALUES (%s, now() - make_interval(mins => %s + 5), now() - make_interval(mins => %s),
                                 jsonb_build_object('data', jsonb_build_object('seven_day_utilization', %s::numeric, 'five_hour_utilization', %s::numeric)))""",
                      (agent, ended_min_ago, ended_min_ago, d7, h5))

        def step(agent, min_ago):
            c.execute("INSERT INTO steps (agent, kind, content, ts) VALUES (%s, 'tool', 'x: y', now() - make_interval(mins => %s))", (agent, min_ago))

        def itch(agent, strength=20.0, thinks=0, think_h_ago=None, key="tool:x"):
            return c.execute(f"""INSERT INTO {T('itch')} (agent, kind, key, what, strength, thinks, last_think)
                VALUES (%s, 'tedium', %s, 'did x by hand', %s, %s, CASE WHEN %s::int IS NULL THEN NULL ELSE now() - make_interval(hours => %s::int) END)
                RETURNING id""", (agent, key, strength, thinks, think_h_ago, think_h_ago)).fetchone()["id"]

        said = []
        want = lambda: M.want(c, lambda to, body: said.append(to))

        print("W1 liveness is the steps'")
        reset(); turn("a", 60); step("a", 1); itch("a")
        arm("W1 a fresh step and an old turn end: at work, NOT woken", want()["woke"] is None, M.drives(c))
        reset(); step("a", 70); turn("a", 60); itch("a")
        arm("W1 control: its last step before its last turn end, an hour ago: woken", want()["woke"] == "a", M.drives(c))

        reset(); turn("a", 40); step("a", 25); itch("a")
        arm("W1b inside one long tool call (newest step 25 min ago, last turn end 40 min ago): the turn is OPEN, not woken",
            want()["woke"] is None, M.drives(c))
        reset(); step("a", 40); turn("a", 25); itch("a")
        arm("W1b control: a turn end AFTER that step: it may wake", want()["woke"] == "a", M.drives(c))

        print("W2 the target is an agent")
        reset(); turn("a", 60, 10, 10)
        for who in ("owner", "nobody-here", "cv-pat.2"):
            turn(who, 60); itch(who)
        arm("W2 pressure under owner, an unknown name or a member never wakes", want()["woke"] is None, M.drives(c))
        try:
            M.note(c, "owner", "wonder", "what is the meaning of this")
            arm("W2 a note as a non-agent is refused", False, "written")
        except SystemExit:
            arm("W2 a note as a non-agent is refused", True)

        print("W4 fasting")
        reset(); c.execute("INSERT INTO turns (agent, started_at, ended_at) VALUES ('a', now() - interval '65 minutes', now() - interval '60 minutes')"); itch("a")
        arm("W4 no energy reading: nobody wakes", want()["woke"] is None)
        reset(); turn("a", 60, d7=M.ENERGY_7D + 1); itch("a")
        arm("W4 the week's line crossed: nobody wakes", want()["woke"] is None)
        reset(); turn("a", 60, h5=M.ENERGY_5H + 1); itch("a")
        arm("W4 the 5-hour line crossed: nobody wakes", want()["woke"] is None)

        print("W5 someone waiting")
        reset(); turn("a", 60); itch("a")
        c.execute("INSERT INTO messages (from_agent, from_org, to_agent, intent, thread, body, ts) VALUES ('owner', 'local', 'a', 'chat', 't1', 'please look', now() - interval '7 hours')")
        arm("W5 a human ask unanswered for 7 hours still holds the wake", want()["woke"] is None, M.drives(c))
        c.execute("INSERT INTO messages (from_agent, from_org, to_agent, intent, thread, body) VALUES ('a', 'local', 'owner', 'chat', 't1', 'done')")
        arm("W5 answered: it may wake", want()["woke"] == "a", M.drives(c))

        print("W6 rest and back-off")
        arm("W6 the same agent isn't woken again within REST_H", want()["woke"] is None, M.drives(c))
        reset(); turn("a", 60); itch("a", thinks=1, think_h_ago=M.REST_H + 1)
        arm("W6 one fruitless think: the wait is doubled (REST_H + 1 hours is not enough)", want()["woke"] is None)
        reset(); turn("a", 60); itch("a", thinks=1, think_h_ago=M.REST_H * 2 + 1)
        arm("W6 …and past the doubled wait it may wake", want()["woke"] == "a")

        print("W7 one wake per tick")
        reset(); said.clear(); turn("a", 60); turn("b", 60); itch("a"); itch("b")
        want()
        arm("W7 two agents free and wanting: exactly one wake", len(said) == 1, said)

        print("W8 MAX_THINKS")
        reset(); i = itch("a", thinks=M.MAX_THINKS, think_h_ago=1)
        M.feel(c)
        r = c.execute(f"SELECT state, why FROM {T('itch')} WHERE id = %s", (i,)).fetchone()
        arm("W8 thought about MAX_THINKS times: let go by the mind, with the reason", r["state"] == "dropped" and "no progress" in r["why"], r)

        print("W9 whose itch, whose shell")
        reset(); i = itch("a")
        arm("W9 b can't let a's itch go", M.drop(c, "b", i, "not mine")["dropped"] is False
            and c.execute(f"SELECT state FROM {T('itch')} WHERE id = %s", (i,)).fetchone()["state"] == "open")
        os.environ["ASTRYX_AGENT"] = "a"
        try:
            M._me("b"); arm("W9 a's shell can't act as b", False, "allowed")
        except SystemExit:
            arm("W9 a's shell can't act as b", True)
        arm("W9 …and acts as itself with no --as", M._me("") == "a")
        os.environ.pop("ASTRYX_AGENT", None)

        print("W10 one thought; numbers out")
        try:
            M.keep(c, "a", "two thoughts", "First this is one thing. Then it is another. And a third.", "concept", "")
            arm("W10 a thought that isn't one sentence is refused", False, "kept")
        except SystemExit:
            arm("W10 a thought that isn't one sentence is refused", True)
        M.keep(c, "a", "probe", "One call reads the job for 0300-123-4567 style ids.", "tool", "x.py", [i])
        news = c.execute("SELECT body FROM messages WHERE thread = 'org-news' ORDER BY id DESC LIMIT 1").fetchone()["body"]
        arm("W10 the kept idea reaches org-news, its number masked, and resolves its itch",
            "probe" in news and sum(ch.isdigit() for ch in news.split("Recall")[0]) < 7
            and c.execute(f"SELECT state FROM {T('itch')} WHERE id = %s", (i,)).fetchone()["state"] == "resolved", news)


        print("W11 the same shape")
        M._org_agents = lambda _c: {"a", "b"}
        reset(); turn("a", 60); turn("b", 60)
        for who, n in (("a", 5), ("b", 2)):
            for _ in range(n):
                c.execute("INSERT INTO steps (agent, kind, content, meta, ts) VALUES (%s, 'tool', 'Bash: run', '{\"shape\": \"abc123def456\"}', now() - interval '2 hours')", (who,))
        c.execute("INSERT INTO steps (agent, kind, content, meta, ts) VALUES ('a', 'tool', 'Bash: other', '{\"shape\": \"ffffffffffff\"}', now() - interval '2 hours')")
        M.feel(c)
        rows = c.execute(f"SELECT agent, n, also, key FROM {T('itch')} WHERE key LIKE 'shape:%'").fetchall()
        arm("W11 the same call made 5 times is one itch for its agent, naming who else made it; a one-off shape is none",
            [(r["agent"], r["n"], r["also"]) for r in rows] == [("a", 5, ["b"])], rows)

try:
    main()
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    fails.append(f"crashed: {type(e).__name__}")
print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: the mind wakes only who is free to think")
sys.exit(1 if fails else 0)
