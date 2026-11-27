#!/usr/bin/env python3
"""Oracle: an org's insider reads the agents' insides as the owner does, short of the personal tier (owner 11-13 "no
privacy within an org"; 11-15: a member's chat showed db silent through 11 minutes of work, because /api/presence and
/api/steps refused her while the live feed streamed her every step).

In-process, as tests/test_cog_gaps.py: the observatory's main app on a throwaway fixture database (fixture_db), the cog
sign-in in a temp HOME, each signed identity minted with that key and sent from 127.0.0.1. Grants come from a stub of
tier._grants, so the fixture's three agents are one of each tier: db (chat-sql: org work), medic (compose: public) and
butler (gmail: the owner's personal tier). Dummy keys only; nothing leaves the host, no live row is read or written.

  G1 THE INSIDE TIER (tier.is_content_org, real charters in a temp agents/): chat-sql, ocr, org and the public grants
     are org work; gmail, an unclassified grant, growbot, a mix, an unknown agent are NOT (fail-closed)
  M1 sees(): the owner reads every agent; a member db, medic, seed, never butler; anonymous medic only
  M2 /api/steps: the owner all three; a member db + medic, no butler row even asked by name; anonymous medic only
  M3 /api/presence: a member 200 with db's row and no butler's; anonymous 403
  M4 /api/pulse: a member has db's buckets, not butler's; anonymous 403
  M5 /api/agents: a member reads db's step count and last line; butler's are zeroed for her, kept for the owner;
     anonymous gets db zeroed (the public floor, as before)
  M6 the live feed: an insider's filter passes db's step, a message and a resync, never butler's step or presence
  M7 /api/chat/work: a member reads db's live lane on its thread; on butler's thread there is no butler lane and its
     turn carries no steps (its shape stays)
  M8 an agent's profile and charter: a member 200 for seed while seed's grants are org work, 404 once they hold gmail;
     the owner 200 either way
  M9 acts stay the owner's: a member's interrupt is 403
  M10 the briefing's turn counts are insides too: butler's counted for the owner, not for a member
Exit 0 pass · 1 fail · 77 fixture unavailable."""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_member_insides", REPO, deps=("fastapi", "httpx", "asyncpg", "psycopg", "nacl"), env=False)   # fixture_db only
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402

KEY = "test-owner-key"
COG = "fxcog"
AUD = "fixture-org"
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def tier_arms(tmp: Path):
    from astryx.core import tier
    d = tmp / "agents"
    d.mkdir()
    cases = {"est": "chat-sql, ocr", "hub": "org", "pub": "compose", "mail": "gmail", "cal": "calendar",
             "grow": "growbot", "mix": "chat-sql, gmail"}
    for name, grants in cases.items():
        (d / f"{name}.md").write_text(f"# {name}\n\nGrants: {grants}\n")
    (d / "bare.md").write_text("# bare\n\nno grants line\n")
    got = {n: tier.is_content_org(n, d) for n in [*cases, "bare", "ghost"]}
    want = {"est": True, "hub": True, "pub": True, "bare": True, "mail": False, "cal": False, "grow": False,
            "mix": False, "ghost": False}
    arm("G1 the inside tier is a positive, fail-closed allowlist", got == want, got)
    arm("G1 ...and it is wider than the public floor, never narrower",
        all(tier.is_content_org(n, d) for n in [*cases, "bare"] if tier.is_content_public(n, d)), got)


def main(tmp: Path, url: str):
    import importlib.util
    import psycopg
    import observatory.api  # noqa: F401
    mspec = importlib.util.spec_from_file_location("main", REPO / "observatory" / "api" / "main.py")
    obs = importlib.util.module_from_spec(mspec)
    sys.modules["main"] = obs
    mspec.loader.exec_module(obs)
    from fastapi.testclient import TestClient
    from astryx.core import tier
    from astryx.security import identity
    from observatory.api import chat, workspace as W

    grants = {"db": {"chat-sql"}, "medic": {"compose"}, "butler": {"gmail"}, "seed": {"org"}}
    tier.grants = lambda name, agents_dir=None: grants.get(name)        # the tiers are the real functions over these
    names = ("db", "medic", "butler", "seed")
    obs.agent_meta = lambda: {a: {"group_path": [], "rank": None, "model_pin": None} for a in names}
    from astryx.core import charter as CH
    CH.roster = lambda *a, **k: list(names)                           # the tree is the registry (/api/agents)
    estate = tmp / "estate"
    (estate / "media").mkdir(parents=True)
    W.bind(lambda: obs.pool, estate, roster=lambda: set(names))
    chat.bind(lambda: obs.pool, estate, estate / "media", REPO, roster=lambda: set(names))

    home = tmp / "cog"
    home.mkdir()
    identity.make_keys(home)
    signer = identity.load_signer(home)
    obs._COGAUTH, obs._AUD = {"id": COG, "home": str(home)}, AUD
    obs._verifiers, obs._verifiers_at = {}, 0.0
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO members (uid, role) VALUES ('1@fxcog','owner'), ('7@fxcog','member')")
        for a in ("db", "medic", "butler"):
            c.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'tool',%s)", (a, f"Bash: {a} at work"))
            c.execute("INSERT INTO presence (agent, surface, state) VALUES (%s,'thread:chat:x','working')", (a,))
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                  "('cv-alice.7','db','chat:20990101-d','chat','alice asks db'), "
                  "('owner','butler','obs:butler','chat','owner asks butler')")
        bid = c.execute("SELECT id FROM messages WHERE to_agent='butler'").fetchone()[0]
        tid = c.execute("INSERT INTO turns (agent, session_id, started_at, ended_at, input_msg_id) VALUES "
                        "('butler','s1', now() - interval '2 min', now() - interval '1 min', %s) RETURNING id",
                        (bid,)).fetchone()[0]
        c.execute("INSERT INTO steps (agent, kind, content, turn_id, ts) VALUES "
                  "('butler','tool','Bash: read the inbox',%s, now() - interval '90 s')", (tid,))
        c.execute("INSERT INTO steps (agent, kind, content) VALUES ('db','tool','mcp__chat-sql__run_query: za')")

    O = {"x-obs-key": KEY}
    cl = TestClient(obs.app, raise_server_exceptions=bool(os.environ.get("INSIDES_RAISE")), client=("127.0.0.1", 50000))
    cl.__enter__()
    A = lambda: {identity.HEADER: identity.mint(signer, "7@fxcog", AUD, name="alice")}   # noqa: E731 — fresh each call

    print("M sees()")

    class R:                                       # a request as sees() reads it: headers, query, the gate's state
        def __init__(self, headers=None, role=None):
            self.headers, self.query_params = headers or {}, {}
            self.state = type("S", (), {"role": role, "uid": "7@fxcog" if role else "", "reach": None})()   # a whole-org member
            self.cookies = {}
    so = obs.sees(R(O))
    sm = obs.sees(R(role="member"))
    sa = obs.sees(R())
    arm("M1 the owner reads every agent", all(so(a) for a in names))
    arm("M1 a member reads db, medic and seed, never butler",
        [sm(a) for a in names] == [True, True, False, True], [sm(a) for a in names])
    arm("M1 anonymous reads the public floor only", [sa(a) for a in names] == [False, True, False, False],
        [sa(a) for a in names])

    print("M the REST doors")
    agents_of = lambda r: sorted({s["agent"] for s in r.json()}) if r.status_code == 200 else r.status_code  # noqa: E731
    arm("M2 /api/steps: the owner reads all three", agents_of(cl.get("/api/steps", headers=O)) == ["butler", "db", "medic"])
    sm2 = agents_of(cl.get("/api/steps", headers=A()))
    arm("M2 ...a member db and medic, no butler", sm2 == ["db", "medic"], sm2)
    arm("M2 ...not even asked by name", cl.get("/api/steps", params={"agent": "butler"}, headers=A()).json() == [])
    arm("M2 ...anonymous: 403, the route is not public at all", cl.get("/api/steps").status_code == 403)
    pm = cl.get("/api/presence", headers=A())
    arm("M3 /api/presence: a member reads db's row and no butler's", pm.status_code == 200
        and {p["agent"] for p in pm.json()} == {"db", "medic"}, (pm.status_code, pm.text[:200]))
    arm("M3 ...anonymous 403", cl.get("/api/presence").status_code == 403)
    pu = cl.get("/api/pulse", headers=A())
    arm("M4 /api/pulse: a member has db's buckets, not butler's", pu.status_code == 200 and "db" in pu.json()
        and "butler" not in pu.json(), (pu.status_code, pu.text[:200]))
    arm("M4 ...anonymous 403", cl.get("/api/pulse").status_code == 403)
    by = lambda h: {a["agent"]: a for a in cl.get("/api/agents", headers=h).json()}  # noqa: E731
    am, ao, aa = by(A()), by(O), by({})
    arm("M5 /api/agents: a member reads db's count and last line",
        am["db"]["steps"] == 2 and bool(am["db"]["last_content"]), am["db"])
    arm("M5 ...butler's are zeroed for her", am["butler"]["steps"] == 0 and am["butler"]["last_content"] is None
        and am["butler"]["last_seen"] is None, am["butler"])
    arm("M5 ...and kept for the owner", ao["butler"]["steps"] == 2 and bool(ao["butler"]["last_content"]), ao["butler"])
    arm("M5 ...anonymous: db zeroed, medic counted with no last line (the public floor, as before)",
        aa["db"]["steps"] == 0 and aa["medic"]["steps"] == 1 and aa["medic"]["last_content"] is None, (aa["db"], aa["medic"]))

    print("M the live feed")
    ev = [{"type": "step", "agent": "db"}, {"type": "message", "from_org": "local"}, {"type": "resync"},
          {"type": "step", "agent": "butler"}, {"type": "presence", "agent": "butler"}, {"type": "step"}]
    arm("M6 an insider's feed passes db's step, a message, a resync; never butler's step or presence, nor a nameless step",
        [obs.insider_sees_event(e, sm) for e in ev] == [True, True, True, False, False, False],
        [obs.insider_sees_event(e, sm) for e in ev])

    print("M the chat's work pane")
    wd = cl.get("/api/chat/work", params={"thread": "chat:20990101-d"}, headers=A())
    arm("M7 a member reads db's live lane on its thread", wd.status_code == 200
        and any("run_query" in s["content"] for s in wd.json()["live"].get("db", [])), (wd.status_code, wd.text[:300]))
    wb = cl.get("/api/chat/work", params={"thread": "obs:butler"}, headers=A()).json()
    arm("M7 ...on butler's desk (shared, so hers to read): no butler lane, and its turn carries no steps (its shape stays)",
        "butler" not in wb["live"] and [t["steps"] for t in wb["turns"] if t["agent"] == "butler"] == [[]], wb)
    wo = cl.get("/api/chat/work", params={"thread": "obs:butler"}, headers=O).json()
    arm("M7 ...the owner reads butler's turn in full", [len(t["steps"]) for t in wo["turns"] if t["agent"] == "butler"] == [1], wo)

    print("M profile and charter")
    seed_md = REPO / "agents" / "seed" / "seed.md"
    if seed_md.exists():
        pr = lambda h: cl.get("/api/agents/seed/profile", headers=h).status_code  # noqa: E731
        ch = lambda h: cl.get("/api/agents/seed/charter", headers=h).status_code  # noqa: E731
        before = (pr(A()), ch(A()))
        grants["seed"] = {"org", "gmail"}
        after, owner = (pr(A()), ch(A())), (pr(O), ch(O))
        grants["seed"] = {"org"}
        arm("M8 a member reads seed's profile and charter while its grants are org work", before == (200, 200), before)
        arm("M8 ...404 once they hold gmail", after == (404, 404), after)
        arm("M8 ...the owner 200 either way", owner == (200, 200), owner)
    else:
        print("  NOT VERIFIED  M8: no agents/seed/seed.md in this tree")

    print("M the briefing (medic's review)")
    turns_of = lambda h: {a["agent"]: a.get("turns") for a in cl.get("/api/ws/briefing", params={"since": "2000-01-01T00:00:00Z"}, headers=h).json().get("agents", [])}  # noqa: E731
    bm, bo = turns_of(A()), turns_of(O)
    arm("M10 the briefing counts butler's turns for the owner, not for a member", bo.get("butler") == 1 and not bm.get("butler"),
        (bo.get("butler"), bm.get("butler")))

    print("M acts stay the owner's")
    arm("M9 a member's interrupt is 403", cl.post("/api/ws/agents/db/interrupt", headers=A()).status_code == 403)
    cl.__exit__(None, None, None)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as t0:
        tier_arms(Path(t0))
    try:
        with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
            os.environ["ASTRYX_DSN"] = fx["url"]
            os.environ["OBS_KEY"] = KEY
            os.environ["ASTRYX_ORG"] = "fixture.example"
            os.environ["ASTRYX_GATEWAY_PORT"] = "9"
            os.environ.setdefault("ASTRYX_COG_REGISTRY", str(Path(td) / "absent.json"))
            main(Path(td), fx["url"])
    except FixtureUnavailable as e:
        from astryx.security.sqlguard.estate import unavailable
        unavailable("test_member_insides", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: member insides ({fails} failing)")
    sys.exit(1 if fails else 0)
