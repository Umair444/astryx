#!/usr/bin/env python3
"""Oracle: the cog fan-out (owner 11-13: "@lending, @seed work together and do this"). A human message naming two or
more agents reaches EACH of them, stamped {team, lead} in delivery; the FIRST named leads and owns the one reply.

In-process on a throwaway fixture database (fixture_db); dummy keys; nothing leaves the host.

  T1 team_of: every @mentioned agent in order, once each; a name with no charter is skipped; an e-mail is no mention.
  F1 wire_chat with two agents: one row each, both stamped {team, lead}, the lead's row written LAST; the body is the
     human's own words (no line added to the stored row).
  F2 a bare follow-up after the fan-out goes to the LEAD (route_target's sticky "whoever the human last addressed").
  F3 one agent: exactly today's row (no stamp); no mention: the surface's default agent.
  F4 a tier route never fans out (its one reader).
  N1 channel/team.mjs (executed by node): the lead's line says it LEADS and replies; a helper's line names the lead
     and forbids replying to the human; a non-member, a one-agent stamp or a lead outside the team -> null.
     server.mjs prefixes the line on the notification only, spreads team=/lead= into its meta, and its instructions
     carry the TEAMS norm.
  O1 the observatory: POST /api/messages with team=[lending, seed] stamps the owner's row with the team; without a
     team the owner's row is byte-identical to before (delivery NULL); a team that doesn't include `to` is ignored.
Exit 0 pass · 1 fail · 77 fixture unavailable."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_fanout", REPO, deps=("fastapi", "httpx", "asyncpg", "psycopg"), env=False)   # fixture_db only
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402

KEY = "test-owner-key"
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def two_agents():
    """Two real charters in this tree (the fan-out needs agents that exist)."""
    names = sorted({p.stem for p in (REPO / "agents").rglob("*.md")
                    if p.stem == p.parent.name or p.parent == REPO / "agents"} - {"README", "seed"})
    return names[0], names[1]


async def wire_arms(url):
    import asyncpg
    from bridges import common as C
    a, b = two_agents()
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        print("T1 team_of")
        arm("T1 order kept, each once", C.team_of(f"@{b} and @{a} please, @{b} again") == [b, a], C.team_of(f"@{b} @{a}"))
        arm("T1 an unknown name is skipped", C.team_of(f"@nosuchagentx @{a}") == [a])
        arm("T1 an e-mail is no mention", C.team_of(f"mail x@{a}.com") == [])
        arm("T1 one agent is not a team", C.team_stamp([a]) == {} and C.team_stamp([b, a]) == {"team": [b, a], "lead": b})

        print("F1 two agents fan out")
        text = f"@{b} @{a} work together on this"
        got = await C.wire_chat(pool, "owner", "whatsapp", "seed", "wa:fx1", text, {"push_name": "o"})
        rows = await pool.fetch("SELECT id, to_agent, body, delivery FROM messages WHERE thread='wa:fx1' ORDER BY id")
        d = [json.loads(r["delivery"]) if isinstance(r["delivery"], str) else r["delivery"] for r in rows]
        arm("F1 one row per member", sorted(r["to_agent"] for r in rows) == sorted([a, b]) and sorted(got) == sorted([a, b]), rows)
        arm("F1 every row stamped {team, lead}, the first named leads",
            all(x.get("team") == [b, a] and x.get("lead") == b for x in d), d)
        arm("F1 the lead's row is written LAST", rows[-1]["to_agent"] == b, [r["to_agent"] for r in rows])
        arm("F1 the stored body is the human's own words", all(r["body"] == text for r in rows))
        arm("F1 the inbound meta survives the stamp", all(x.get("push_name") == "o" for x in d))

        print("F2 the follow-up")
        who, _ = await C.route_target(pool, "wa:fx1", "and also this", "seed")
        arm("F2 a bare follow-up goes to the lead", who == b, who)

        print("F3 one agent / none")
        got1 = await C.wire_chat(pool, "owner", "whatsapp", "seed", "wa:fx2", f"@{a} just you", None)
        r1 = await pool.fetch("SELECT to_agent, delivery FROM messages WHERE thread='wa:fx2'")
        arm("F3 one mention: one row, no stamp", got1 == [a] and len(r1) == 1 and r1[0]["delivery"] is None, r1)
        got0 = await C.wire_chat(pool, "owner", "whatsapp", "seed", "wa:fx3", "no mention here", None)
        arm("F3 no mention: the surface's default", got0 == ["seed"])

        print("F4 tier route")
        src = (REPO / "bridges" / "common.py").read_text()
        body = src[src.index("async def wire_chat"):src.index("# The human's inbound that ANSWERS")]
        arm("F4 a tiered route takes the one-agent path (its one reader)",
            "if len(team) < 2 or tiered:" in body and "route_tier(route)" in body)
    finally:
        await pool.close()


def node_arms():
    print("N1 the member's line (channel/team.mjs)")
    cases = {
        "lead": [{"delivery": {"team": ["lending", "seed"], "lead": "lending"}}, "lending"],
        "helper": [{"delivery": {"team": ["lending", "seed"], "lead": "lending"}}, "seed"],
        "outsider": [{"delivery": {"team": ["lending", "seed"], "lead": "lending"}}, "db"],
        "one": [{"delivery": {"team": ["lending"], "lead": "lending"}}, "lending"],
        "badlead": [{"delivery": {"team": ["lending", "seed"], "lead": "db"}}, "seed"],
        "none": [{"delivery": None}, "seed"],
    }
    js = (f"import {{ team }} from {json.dumps((REPO / 'channel' / 'team.mjs').as_uri())};"
          f"const c = {json.dumps(cases)};"
          "console.log(JSON.stringify(Object.fromEntries(Object.entries(c).map(([k, [r, me]]) => [k, team(r, me)]))))")
    p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30)
    got = json.loads(p.stdout or "{}") if p.returncode == 0 else {}
    arm("N1 team.mjs runs", p.returncode == 0, p.stderr[-300:])
    lead, helper = got.get("lead") or {}, got.get("helper") or {}
    arm("N1 the lead is told it LEADS and replies", "You LEAD" in lead.get("line", "") and lead.get("lead") == "lending", lead)
    arm("N1 a helper names the lead and must not reply to the human",
        "lending leads" in helper.get("line", "") and "Do NOT reply" in helper.get("line", ""), helper)
    arm("N1 meta values", lead.get("members") == "lending,seed", lead)
    arm("N1 outsider / one-agent / lead outside the team / no stamp -> null",
        all(got.get(k) is None for k in ("outsider", "one", "badlead", "none")), got)
    srv = (REPO / "channel" / "server.mjs").read_text()
    arm("N1 server.mjs prefixes the line on the notification and spreads team=/lead=",
        "const crew = team(row, AGENT)" in srv and "{ team: crew.members, lead: crew.lead }" in srv
        and "crew ? `${crew.line}\\n${text}` : text" in srv)
    arm("N1 the shared instructions carry the TEAMS norm", "TEAMS: when a human tags several agents" in srv)


def obs_arms(url):
    import importlib.util
    import psycopg
    import observatory.api  # noqa: F401
    mspec = importlib.util.spec_from_file_location("main", REPO / "observatory" / "api" / "main.py")
    obs = importlib.util.module_from_spec(mspec)
    sys.modules["main"] = obs
    mspec.loader.exec_module(obs)
    from fastapi.testclient import TestClient
    print("O1 the observatory")
    O = {"x-obs-key": KEY}
    with TestClient(obs.app, client=("127.0.0.1", 50000)) as cl:
        for to in ("seed", "lending"):
            r = cl.post("/api/messages", headers=O,
                        json={"to": to, "body": "@lending @seed together", "thread": "chat:fx", "team": ["lending", "seed"]})
            arm(f"O1 post to {to} ok", r.status_code == 200, r.text[:200])
        cl.post("/api/messages", headers=O, json={"to": "seed", "body": "plain", "thread": "chat:fy"})
        cl.post("/api/messages", headers=O, json={"to": "seed", "body": "odd", "thread": "chat:fz", "team": ["db", "lending"]})
    with psycopg.connect(url) as c:
        team_rows = c.execute("SELECT from_agent, delivery FROM messages WHERE thread='chat:fx' ORDER BY id").fetchall()
        plain = c.execute("SELECT from_agent, delivery FROM messages WHERE thread='chat:fy'").fetchall()
        odd = c.execute("SELECT delivery FROM messages WHERE thread='chat:fz'").fetchall()
    arm("O1 the owner's team rows are stamped (lead = the first named)",
        len(team_rows) == 2 and all(fa == "owner" and d and d.get("team") == ["lending", "seed"] and d.get("lead") == "lending"
                                    for fa, d in team_rows), team_rows)
    arm("O1 without a team the owner's row is as before (delivery NULL)", plain == [("owner", None)], plain)
    arm("O1 a team that doesn't include `to` is ignored", odd == [(None,)], odd)


if __name__ == "__main__":
    try:
        with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
            os.environ["ASTRYX_DSN"] = fx["url"]
            os.environ["OBS_KEY"] = KEY
            os.environ["ASTRYX_ORG"] = "fixture.example"
            os.environ["ASTRYX_GATEWAY_PORT"] = "9"
            os.environ.setdefault("ASTRYX_COG_REGISTRY", str(Path(td) / "absent.json"))
            asyncio.run(wire_arms(fx["url"]))
            node_arms()
            obs_arms(fx["url"])
    except FixtureUnavailable as e:
        from astryx.security.sqlguard.estate import unavailable
        unavailable("test_fanout", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: fan-out ({fails} failing)")
    sys.exit(1 if fails else 0)
