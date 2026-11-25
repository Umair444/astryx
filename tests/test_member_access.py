#!/usr/bin/env python3
"""Oracle: what a person may reach and use (owner 11-17: "is it possible an admin can assign a voice chat to a member
… is it possible for a member to use only the selected agents"). In-process on a fixture database, as
tests/test_member_insides.py: the observatory's main app, the cog sign-in in a temp HOME, identities minted and sent
from 127.0.0.1, the agents' tree paths stubbed (db sits in group `grp`). Dummy keys only; no
OpenAI call is made: voice_mint's key and mint are stubbed, so a session that passes the gate gets a fake secret).

  people: 1 the owner · 7 alice, a member of the whole org · 8 bob, a member on node `grp` only · 9 carol, an admin
  S1 /api/whoami: bob reaches [db]; alice and the owner reach every agent (null); caps are each role's default
  S2 POST /api/messages: bob to db 200, to medic 403 (and as a team member 403); alice to medic 200
  S3 bob's reads: /api/steps and /api/ws/agents hold db only; alice's hold every org-work agent
  S4 bob's wire (/api/messages, the live feed) holds no message to or from an agent outside his part; no everyone view
  F1 dictation: a member's default lets it through the gate; turned off for alice in Admin, 403
  R1 media library, ?thread= reads (media, artifacts, handoffs, work), attached files and non-charter names: bob's part only
  P  people's own chats (owner 11-17, msg 12970): alice, of the whole org, reads none of the owner's normal or canvas
     chats (wire, library, files, ?thread= reads, titles, the steps of a turn woken there, the live feed), nor carol's;
     she reads her own (an agents' handoff on it included) and a project chat shared with her; the owner reads all;
     a step of a turn opened there (linked, or still running) is not in her steps, an agent's profile, her briefing's
     `did` or /api/agents' last line (medic 12975)
  C  canvases (owner 11-17, 12979): a member lists, renders and reads the conversation of a canvas shared with her
     account or made by her, not another; she shares her own with members (not a non-member), not one she didn't make
  R2 a member's call is charged 10 min at its mint, which a 1 s report can't lower; past his limit the next is refused
  F2 the Call: a member's default is 403; given to bob in Admin with 25 minutes, status 200 with limit 25; a session as
     medic (outside his agents) is 403; spent minutes say so
  F3 Admin: the owner and an admin set a feature; an admin can't set an owner's; a member can't set any; an unknown
     feature is 400; allowed=null clears it back to the default
  F4 /api/admin/members carries the defaults and the overrides; activity carries today's voice minutes
Exit 0 pass · 1 fail · 77 fixture unavailable."""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_member_access", REPO, deps=("fastapi", "httpx", "asyncpg", "psycopg", "nacl"), env=False)   # fixture_db only
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402

KEY = "test-owner-key"
COG = "fxcog"
AUD = "fixture-org"
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


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

    grants = {"db": {"chat-sql"}, "medic": {"compose"}, "seed": {"org"}}
    tier.grants = lambda name, agents_dir=None: grants.get(name)
    names = ("db", "medic", "seed")
    obs.agent_meta = lambda: {a: {"group_path": [], "rank": None, "model_pin": None} for a in names}
    obs.agent_nodes = lambda: {"db": "grp/db", "medic": "medic", "seed": "seed"}
    from astryx.core import charter as CH
    CH.roster = lambda *a, **k: list(names)
    estate = tmp / "estate"
    (estate / "media").mkdir(parents=True)
    os.environ["ASTRYX_WS_STORE"] = str(tmp / "ws-store")   # the Library under test is this run's own, never a shared one
    W.bind(lambda: obs.pool, estate, roster=lambda: set(names))
    chat.bind(lambda: obs.pool, estate, estate / "media", REPO, roster=lambda: set(names))
    obs._pilot_voice.persona = lambda agent: (f"{agent}'s line", "") if agent in names else None
    from astryx.hearing import voice_mint as V                       # never the real key, never a real mint
    real_env = V.env
    V.env = lambda key, default="": "sk-fake" if key == "OPENAI_API_KEY" else real_env(key, default)
    V.cap_minutes = lambda: 60.0

    async def fake_mint(cfg):
        return 200, {"value": "ek-fake", "expires_at": 0}
    V.mint = fake_mint

    home = tmp / "cog"
    home.mkdir()
    identity.make_keys(home)
    signer = identity.load_signer(home)
    obs._COGAUTH, obs._AUD = {"id": COG, "home": str(home)}, AUD
    obs._verifiers, obs._verifiers_at = {}, 0.0
    obs._admin.bind(lambda: obs.pool, url, estate, COG, owner=lambda r: obs.is_owner(r))
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO members (uid, node, role) VALUES ('1@fxcog','','owner'), ('7@fxcog','','member'), "
                  "('8@fxcog','grp','member'), ('9@fxcog','','admin')")
        for a in names:
            c.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,'tool',%s)", (a, f"Bash: {a} at work"))

    O = {"x-obs-key": KEY}
    cl = TestClient(obs.app, raise_server_exceptions=bool(os.environ.get("ACCESS_RAISE")), client=("127.0.0.1", 50000))
    cl.__enter__()
    as_ = lambda uid, name: {identity.HEADER: identity.mint(signer, f"{uid}@fxcog", AUD, name=name)}  # noqa: E731
    ALICE, BOB, CAROL = (lambda: as_(7, "alice")), (lambda: as_(8, "bob")), (lambda: as_(9, "carol"))

    print("S scope")
    wb, wa, wo = (cl.get("/api/whoami", headers=h()).json() for h in (BOB, ALICE, lambda: O))
    arm("S1 bob reaches db only", wb["reach"] == ["db"], wb)
    arm("S1 alice and the owner reach every agent", wa["reach"] is None and wo["reach"] is None, (wa, wo))
    arm("S1 caps are each role's default: a member dictates, the owner has everything",
        wb["caps"] == {"dictate": None} and wa["caps"] == {"dictate": None} and wo["caps"] == {"dictate": None, "call": None},
        (wb["caps"], wo["caps"]))
    # each person posts on her own chat: since access-core 2 a chat's id is no key to someone else's
    send = lambda h, to, team=None: cl.post("/api/messages", headers=h(), json={"to": to, "body": "hi", "thread": "chat:20990101-b0" if h is BOB else "chat:20990101-s", **({"team": team} if team else {})}).status_code  # noqa: E731
    arm("S2 bob may message db", send(BOB, "db") == 200, send(BOB, "db"))
    arm("S2 ...not medic", send(BOB, "medic") == 403)
    arm("S2 ...nor tag medic onto a team", send(BOB, "db", ["db", "medic"]) == 403)
    arm("S2 alice may message medic", send(ALICE, "medic") == 200)
    st = lambda h: sorted({s["agent"] for s in cl.get("/api/steps", headers=h()).json()})  # noqa: E731
    arm("S3 bob's steps: db only", st(BOB) == ["db"], st(BOB))
    arm("S3 alice's steps: every org-work agent", st(ALICE) == ["db", "medic", "seed"], st(ALICE))
    ag = lambda h: sorted(a["agent"] for a in cl.get("/api/ws/agents", headers=h()).json())  # noqa: E731
    arm("S3 bob's agent list: db only", ag(BOB) == ["db"], ag(BOB))
    arm("S3 alice's: all three", ag(ALICE) == ["db", "medic", "seed"], ag(ALICE))

    rows = lambda h: cl.get("/api/messages", headers=h()).json()  # noqa: E731
    mb, ma = rows(BOB), rows(ALICE)
    arm("S4 bob's wire holds no message to or from medic", mb and not any("medic" in (m["from"], m["to"]) for m in mb),
        [(m["from"], m["to"]) for m in mb])
    arm("S4 alice's holds alice's message to medic", any(m["to"] == "medic" for m in ma), [(m["from"], m["to"]) for m in ma])
    ev = {"type": "message", "from": "cv-alice.7", "to": "medic"}
    class Rq:                                      # the gate's state, as the live feed's filter reads it
        def __init__(self, reach, me, role="member"):
            self.state = type("S", (), {"reach": reach, "me": me, "role": role})()
    from observatory.api import scope
    arm("S4 the live feed: bob's filter drops a message to medic; alice's passes it",
        not obs.insider_sees_event(ev, lambda a: True, lambda d: scope.message_ok(Rq({"db"}, "cv-bob.8"), d))
        and obs.insider_sees_event(ev, lambda a: True, lambda d: scope.message_ok(Rq(None, "cv-alice.7"), d)))
    ev_scope = lambda h: cl.get("/api/ws/threads", params={"scope": "everyone"}, headers=h()).json()["scope"]  # noqa: E731
    arm("S4 no member has the everyone-view (bob, alice, carol the admin); the owner has",
        [ev_scope(h) for h in (BOB, ALICE, CAROL, lambda: O)] == ["mine", "mine", "mine", "everyone"],
        [ev_scope(h) for h in (BOB, ALICE, CAROL, lambda: O)])

    print("R1 every wire read is the member's part")
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                  "('medic','owner','obs:medic','chat','[[file:/tmp/fx/medic.png]]'), "
                  "('db','cv-bob.8','chat:20990101-b2','chat','[[file:/tmp/fx/db.png]]'), "
                  "('pulse','owner','chat:20990101-p','chat','a note from no charter')")
    lib = cl.get("/api/ws/media", headers=BOB()).json()
    paths = {m["path"] for m in lib} if isinstance(lib, list) else lib
    arm("R1a bob's media library has db's file, not medic's", "/tmp/fx/db.png" in paths and "/tmp/fx/medic.png" not in paths, paths)
    for route in ("/api/ws/media", "/api/ws/artifacts", "/api/ws/handoffs", "/api/chat/work"):
        code = cl.get(route, params={"thread": "obs:medic"}, headers=BOB()).status_code
        arm(f"R1b {route}?thread=<medic's> is 403 for bob", code == 403, code)
    arm("R1b ...and alice reads medic's thread", cl.get("/api/ws/handoffs", params={"thread": "obs:medic"}, headers=ALICE()).status_code == 200)
    fcode = lambda h: cl.get("/api/chat/file", params={"path": "/tmp/fx/medic.png"}, headers=h()).status_code  # noqa: E731
    arm("R1c /api/chat/file for medic's file: bob 403, alice past the gate", fcode(BOB) == 403 and fcode(ALICE) != 403,
        (fcode(BOB), fcode(ALICE)))
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO messages (from_agent, from_org, to_agent, thread, intent, body) VALUES "
                  "('db','peer.example','seed','chat:20990101-pe','chat','a peer named db')")
    arm("R1e a peer that names itself db is not bob's db", not any(m.get("from_org") == "peer.example" for m in rows(BOB)),
        [(m["from"], m.get("from_org")) for m in rows(BOB)])
    arm("R1d a message from a name that is no charter is not on bob's wire",
        not any(m["from"] == "pulse" for m in rows(BOB)), [m["from"] for m in rows(BOB)])

    print("P people's own chats")
    import json as _json
    (estate / "chat").mkdir(exist_ok=True)
    (estate / "chat" / "projects.json").write_text(_json.dumps({"projects": [
        {"id": "pa", "name": "shared with alice", "shared": ["7@fxcog"], "threads": ["chat:20990101-pa"]},
        {"id": "pb", "name": "the owner's alone", "threads": ["chat:20990101-pb"]}]}))
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                  "('owner','medic','chat:20990101-o','chat','the owner alone [[file:/tmp/fx/own.png]]'), "
                  "('medic','owner','chat:20990101-o','chat','to the owner'), "
                  "('medic','db','chat:20990101-o','chat','a handoff on the owner''s chat'), "
                  "('owner','seed','cv:20990101-c','chat','the owner on canvas [[file:/tmp/fx/cv.png]]'), "
                  "('cv-carol.9','seed','chat:20990101-k','chat','carol alone'), "
                  "('medic','db','chat:20990101-s','chat','a handoff on alice''s chat'), "
                  "('owner','db','chat:20990101-pa','chat','a project chat shared with alice'), "
                  "('owner','db','chat:20990101-pb','chat','a project chat not shared')")
        mid = c.execute("SELECT id FROM messages WHERE thread = 'chat:20990101-o' ORDER BY id LIMIT 1").fetchone()[0]
        tid = c.execute("INSERT INTO turns (agent, input_msg_id) VALUES ('medic', %s) RETURNING id", (mid,)).fetchone()[0]
        c.execute("INSERT INTO steps (agent, kind, content, turn_id) VALUES ('medic','tool','reading the owner''s chat',%s)", (tid,))
    theirs = ("chat:20990101-o", "cv:20990101-c", "chat:20990101-k", "chat:20990101-pb")
    wire = lambda h: {(m["thread"], m["body"][:20]) for m in cl.get("/api/messages", params={"limit": 500}, headers=h()).json()}  # noqa: E731
    wa_, wo_ = {t for t, _ in wire(ALICE)}, {t for t, _ in wire(lambda: O)}
    arm("P1 alice's wire holds none of the owner's chats, canvas chats, carol's, or an unshared project's",
        not wa_ & set(theirs), sorted(wa_ & set(theirs)))
    arm("P1 ...nor when she asks for one by id", all(cl.get("/api/messages", params={"thread": t}, headers=ALICE()).json() == []
                                                     for t in theirs))
    arm("P1 the owner's wire holds them all", set(theirs) <= wo_, sorted(set(theirs) - wo_))
    arm("P2 alice reads her own chat, the agents' handoff on it included",
        ("chat:20990101-s", "a handoff on alice's") in wire(ALICE), sorted(wire(ALICE)))
    arm("P3 alice reads the project chat shared with her", "chat:20990101-pa" in wa_, sorted(wa_))
    lib = {m["path"] for m in cl.get("/api/ws/media", headers=ALICE()).json()}
    arm("P4 alice's library has neither the owner's chat file nor his canvas file",
        not {"/tmp/fx/own.png", "/tmp/fx/cv.png"} & lib, sorted(lib))
    arm("P4 the owner's library has both", {"/tmp/fx/own.png", "/tmp/fx/cv.png"} <= {m["path"] for m in cl.get("/api/ws/media", headers=O).json()})
    fc = cl.get("/api/chat/file", params={"path": "/tmp/fx/own.png"}, headers=ALICE()).status_code
    arm("P4 /api/chat/file for the owner's chat file is 403 for alice", fc == 403, fc)
    for route in ("/api/ws/media", "/api/ws/artifacts", "/api/ws/handoffs", "/api/chat/work"):
        code = cl.get(route, params={"thread": "chat:20990101-o"}, headers=ALICE()).status_code
        arm(f"P5 {route}?thread=<the owner's chat> is 403 for alice", code == 403, code)
    tt = cl.get("/api/ws/thread-titles", params={"ids": "chat:20990101-o,cv:20990101-c,chat:20990101-s"}, headers=ALICE()).json()["titles"]
    arm("P5 thread-titles names her chat, not the owner's", "chat:20990101-o" not in tt and "cv:20990101-c" not in tt, tt)
    sa = [s_["content"] for s_ in cl.get("/api/steps", headers=ALICE()).json()]
    so = [s_["content"] for s_ in cl.get("/api/steps", headers=O).json()]
    arm("P6 a step of a turn woken on the owner's chat is not in alice's steps; it is in the owner's",
        "reading the owner's chat" not in sa and "reading the owner's chat" in so and "Bash: medic at work" in sa, sa)
    feed = Rq(None, "cv-alice.7")
    fe = lambda f_, t_, th: obs.insider_sees_event({"type": "message", "from": f_, "to": t_, "thread": th}, lambda a: True,  # noqa: E731
                                                  lambda d: scope.message_ok(feed, d))
    arm("P7 the live feed: alice's filter drops the owner's chat and a handoff on it",
        not fe("owner", "medic", "chat:20990101-n") and not fe("medic", "db", "chat:20990101-n"))
    arm("P7 ...a chat she starts while watching passes, and so does the agents' handoff on it after",
        fe("cv-alice.7", "medic", "chat:20990101-a") and fe("medic", "db", "chat:20990101-a"))
    arm("P7 ...a desk is shared", fe("owner", "medic", "obs:medic"))
    arm("P7 the owner's feed is unscoped", scope.message_ok(Rq(None, "owner", role=None), {"from": "owner", "to": "medic", "thread": "chat:x"}))
    with psycopg.connect(url, autocommit=True) as c:          # db's newest work and words are on the owner's chat
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                  "('db','cv-alice.7','chat:20990101-s','chat','db to alice')")
        c.execute("INSERT INTO steps (agent, kind, content) VALUES ('db','response','db says hers')")
        t2 = c.execute("INSERT INTO turns (agent, input_msg_id) VALUES ('db', %s) RETURNING id", (mid,)).fetchone()[0]
        c.execute("INSERT INTO steps (agent, kind, content, turn_id) VALUES ('db','tool','db works the owner''s chat',%s), "
                  "('db','response','db answers the owner privately',%s)", (t2, t2))
        c.execute("INSERT INTO steps (agent, kind, content, meta) VALUES ('medic','tool','medic mid-turn on the owner''s chat',"
                  "jsonb_build_object('turn_msgs', jsonb_build_array(%s::bigint)))", (mid,))
        c.execute("INSERT INTO steps (agent, kind, content, meta) VALUES ('medic','tool','medic juggling two chats, one the owner''s',"
                  "jsonb_build_object('many', jsonb_build_array(%s::bigint)))", (mid,))   # hooks/step.py: work for 2+ chats
    sa = [s_["content"] for s_ in cl.get("/api/steps", headers=ALICE()).json()]
    arm("P6 a step of a turn still running on the owner's chat (meta.turn_msgs, no turn yet) is not in alice's steps",
        "medic mid-turn on the owner's chat" not in sa, sa)
    arm("P6 a step whose work served several chats at once (meta.many) naming the owner's chat is not in alice's steps "
        "(medic 13170)", "medic juggling two chats, one the owner's" not in sa, sa)
    obs.ESTATE, est0 = estate, obs.ESTATE                  # db's charter, for its profile
    (estate / "agents").mkdir(exist_ok=True)
    (estate / "agents" / "db.md").write_text("# db\n*the estate steward*\n")
    prof = lambda h: [r_["content"] for r_ in cl.get("/api/agents/db/profile", headers=h()).json().get("recent", [])]  # noqa: E731
    pa, po = prof(ALICE), prof(lambda: O)
    obs.ESTATE = est0
    arm("P8 db's profile: its recent steps on the owner's chat are not in alice's; they are in the owner's",
        "db works the owner's chat" not in pa and "db works the owner's chat" in po, (pa, po))
    did = lambda h: next((a_["did"] for a_ in cl.get("/api/ws/briefing", headers=h()).json().get("agents", []) if a_["agent"] == "db"), None)  # noqa: E731
    arm("P8 alice's briefing: db's newest words she may read, not its private answer to the owner",
        (did(ALICE) or "").lower() == "db says hers", did(ALICE))
    arm("P8 ...the owner's briefing has db's newest", "privately" in (did(lambda: O) or ""), did(lambda: O))
    last = lambda h: next(a_["last_content"] for a_ in cl.get("/api/agents", headers=h()).json() if a_["agent"] == "db")  # noqa: E731
    arm("P8 /api/agents: db's last line for alice is hers to read; the owner's is the newest",
        last(ALICE) == "db says hers" and "privately" in (last(lambda: O) or ""), (last(ALICE), last(lambda: O)))

    print("A a thing's contents follow the thing (access-core, owner 11-25)")
    upa = cl.post("/api/chat/upload", params={"name": "alice-sheet.csv"}, headers=ALICE(), content=b"a,b\n1,2\n")
    af = upa.json()["path"]                        # a member's file is one she uploads (media/upload/<uuid>)
    cl.post("/api/messages", headers=ALICE(), json={"to": "db", "thread": "chat:20990101-s", "body": f"my sheet [[file:{af}]]"})
    op = lambda h, author="cv-alice.7": cl.post("/api/ws/artifacts/open", headers=h(), json={  # noqa: E731
        "path": str(af), "thread": "chat:20990101-s", "author": author, "label": "alice-sheet.csv"})
    r = op(ALICE)
    arm("A1 alice opens the file she sent into the Library, as its author (Kumail's attachments, 11-25)",
        r.status_code == 200, (r.status_code, r.text[:160]))
    r = op(lambda: O)
    arm("A1 ...and the owner opens a member's attachment, the member as its author", r.status_code == 200,
        (r.status_code, r.text[:160]))
    r = op(BOB)
    arm("A2 bob, not a party of alice's chat, can't open it", r.status_code in (403, 404), (r.status_code, r.text[:160]))
    arts = lambda h: {a_.get("name") for a_ in cl.get("/api/ws/artifacts", params={"thread": "chat:20990101-s"}, headers=h()).json()}  # noqa: E731
    arm("A3 the opened file is in alice's Library for her chat", "alice-sheet.csv" in arts(ALICE), arts(ALICE))
    code = cl.get("/api/ws/artifacts", params={"thread": "chat:20990101-s"}, headers=BOB()).status_code
    arm("A3 ...and bob can't list her chat's Library", code in (403, 404), code)

    by = lambda r: r.json()["versions"][-1]["author"] if r.status_code == 200 else r.status_code  # noqa: E731 — v1's author
    for claim in ("owner", "cv-carol.9", "db"):
        r = op(ALICE, claim)
        arm(f"A4 a member's claimed author {claim!r} never decides: her own file's version is by her (medic 16376 H4)",
            by(r) == "cv-alice.7", (r.status_code, r.text[:160]))
    art = op(ALICE).json()
    txt_ = cl.post("/api/ws/artifacts/create", headers=ALICE(), json={"thread": "chat:20990101-s", "name": "notes",
                                                                       "text": "v1\n", "author": "cv-alice.7"})
    arm("A5 alice creates a document in her chat's Library", txt_.status_code == 200, (txt_.status_code, txt_.text[:120]))
    did_ = txt_.json().get("id")
    sv = cl.post(f"/api/ws/artifacts/{did_}/save", headers=ALICE(), json={"text": "v2\n"})
    arm("A5 her saved version is by her, not by 'owner'", sv.status_code == 200 and sv.json()["versions"][0]["author"] == "cv-alice.7",
        (sv.status_code, sv.text[:160]))
    for verb, call in (("save", lambda h: cl.post(f"/api/ws/artifacts/{did_}/save", headers=h(), json={"text": "x\n"})),
                       ("restore", lambda h: cl.post(f"/api/ws/artifacts/{did_}/restore", headers=h(), json={"rev": "HEAD"})),
                       ("export", lambda h: cl.post(f"/api/ws/artifacts/{did_}/export", headers=h())),
                       ("annotate", lambda h: cl.put(f"/api/ws/artifacts/{did_}/annotations", headers=h(), json=[]))):
        code = call(BOB).status_code
        arm(f"A6 bob can't {verb} a document in alice's chat", code in (403, 404), code)
    code = cl.put(f"/api/ws/artifacts/{art.get('id')}/standard", headers=ALICE(), json={"on": True}).status_code
    arm("A7 a member can't pin an org standard (the owner's)", code == 403, code)
    print("H a member's own message attaches only what she uploaded (medic 16376 H5)")
    secret = estate / "media" / "someone-elses.csv"
    secret.write_text("x,y\n1,2\n")
    dbf = estate / "media" / "db-sent.csv"
    dbf.write_text("a\n1\n")
    up = cl.post("/api/chat/upload", params={"name": "mine.csv"}, headers=ALICE(), content=b"m,n\n1,2\n")
    upath = up.json().get("path", "") if up.status_code == 200 else ""
    for body in (f"look [[file:{secret}]]", f"mine [[file:{upath}]]"):
        cl.post("/api/messages", headers=ALICE(), json={"to": "db", "thread": "chat:20990101-h", "body": body})
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                  "('db','cv-alice.7','chat:20990101-h','chat',%s)", (f"here [[file:{dbf}]]",))
    get = lambda h, p_: cl.get("/api/chat/file", params={"path": str(p_)}, headers=h()).status_code  # noqa: E731
    arm("H5 naming a path in her own message doesn't give alice its bytes", get(ALICE, secret) == 403, get(ALICE, secret))
    arm("H5 ...her own upload, attached by her, opens", up.status_code == 200 and get(ALICE, upath) == 200,
        (up.status_code, get(ALICE, upath) if upath else None))
    arm("H5 ...an agent's attachment on her chat opens", get(ALICE, dbf) == 200, get(ALICE, dbf))
    arm("H5 ...and the owner reads all three", all(get(lambda: O, p_) == 200 for p_ in (secret, upath, dbf)))
    arm("H5 bob reads none of them (not a party of her chat:…-h)", all(get(BOB, p_) == 403 for p_ in (secret, dbf)), [get(BOB, p_) for p_ in (secret, dbf)])

    print("HX1 a person's typed [[file:]] is text, never an attachment (medic 16380)")
    planted = estate / "media" / "planted.csv"
    planted.write_text("k\n1\n")
    with psycopg.connect(url, autocommit=True) as c:
        for frm, org in (("cv-alice", "local"), ("wa-923001234567", "local"), ("cv-carol.9", "local"), ("db", "peer.example")):
            c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body, from_org) VALUES "
                      "(%s,'cv-alice.7','chat:20990101-h','chat',%s,%s)", (frm, f"see [[file:{planted}]]", org))
    arm("HX1 a path typed by her canvas handle, a WhatsApp sender, a colleague or a federated peer's 'db' gives alice nothing",
        get(ALICE, planted) == 403, get(ALICE, planted))
    r = cl.post("/api/ws/artifacts/open", headers=ALICE(), json={"path": str(planted), "thread": "chat:20990101-h"})
    arm("HX1 ...and doesn't open into her Library", r.status_code == 403, (r.status_code, r.text[:120]))
    arm("HX1 the owner still reads it (unscoped)", get(lambda: O, planted) == 200, get(lambda: O, planted))

    print("H1/H2/H4 the Library opens only what was sent on that conversation (medic 16376)")
    own_only = estate / "media" / "owner-only.csv"
    own_only.write_text("p,q\n1,2\n")
    never = estate / "media" / "never-sent.csv"
    never.write_text("z\n1\n")
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                  "('owner','medic','chat:20990101-o','chat',%s)", (f"mine [[file:{own_only}]]",))
    opn = lambda h, p_, th="chat:20990101-h", au=None: cl.post("/api/ws/artifacts/open", headers=h(), json={  # noqa: E731
        "path": str(p_), "thread": th, **({"author": au} if au else {})})
    r = opn(ALICE, own_only)
    arm("H1 alice can't open into her Library a file sent only on the owner's chat", r.status_code == 403, (r.status_code, r.text[:120]))
    r = opn(ALICE, never)
    arm("H2 ...nor a file no message ever sent", r.status_code == 403, (r.status_code, r.text[:120]))
    r = opn(ALICE, secret)
    arm("H2 ...nor one she only named in her own message", r.status_code == 403, (r.status_code, r.text[:120]))
    r = opn(ALICE, dbf)
    arm("H4 db's attachment on her chat opens, as db's work", by(r) == "db", (r.status_code, r.text[:160]))
    r = opn(ALICE, upath)
    arm("H4 her own upload sent on her chat opens, as hers", by(r) == "cv-alice.7", (r.status_code, r.text[:160]))
    r = opn(ALICE, dbf, th="chat:20990101-s")
    arm("H1 ...but db's file sent on ANOTHER chat of hers doesn't open into this one", r.status_code == 403, (r.status_code, r.text[:120]))
    r = opn(lambda: O, own_only, th="chat:20990101-o", au="owner")
    arm("H1 the owner opens his own file as before", r.status_code == 200, (r.status_code, r.text[:120]))
    cr = cl.post("/api/ws/artifacts/create", headers=ALICE(), json={"thread": "chat:20990101-h", "name": "n2", "text": "w\n",
                                                                    "author": "db"})
    arm("H4 create: a member's claimed author never decides (no message named: hers)", by(cr) == "cv-alice.7", (cr.status_code, cr.text[:160]))

    print("CS chat sharing: a canvas's rule and shape for a chat; what is inside follows (owner 11-25)")
    SH = "chat:20990101-sh"
    shf = estate / "media" / "db-on-shared.csv"
    shf.write_text("r\n1\n")
    cl.post("/api/messages", headers=ALICE(), json={"to": "db", "thread": SH, "body": "alice's chat to share"})
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                  "('db','cv-alice.7',%s,'chat',%s)", (SH, f"the sheet [[file:{shf}]]"))
    share = lambda h, users, th=SH: cl.post("/api/ws/chats/share", headers=h(), json={"thread": th, "shared": users})  # noqa: E731
    bodies = lambda h, th=SH: [m_["body"][:24] for m_ in cl.get("/api/messages", params={"thread": th}, headers=h()).json()]  # noqa: E731
    mine = lambda h: {r_["thread"]: r_ for r_ in cl.get("/api/ws/threads", headers=h()).json()["threads"]}  # noqa: E731
    arm("CS0 before sharing, bob reads none of alice's chat", bodies(BOB) == [], bodies(BOB))
    r = share(ALICE, ["8@fxcog"])
    arm("CS1 alice, its maker, shares her chat with bob by account", r.status_code == 200 and r.json()["shared"] == ["8@fxcog"],
        (r.status_code, r.text[:160]))
    lb = mine(BOB)
    arm("CS2 bob's chat list has it, marked shared with him", SH in lb and lb[SH].get("shared_with_me") is True, sorted(lb))
    arm("CS2 ...alice's list shows whom it is shared with", mine(ALICE).get(SH, {}).get("shared") == ["8@fxcog"], mine(ALICE).get(SH))
    la = mine(ALICE).get(SH, {})
    arm("CS2 the Share button's flags: alice's chat is hers to share; bob's copy is shared with him, not his",
        la.get("shareable") and la.get("yours") and la.get("by_member") and lb[SH].get("yours") is False,
        ({k: la.get(k) for k in ("shareable", "yours", "by_member")}, lb[SH].get("yours")))
    arm("CS3 bob reads it", any("alice's chat to share" in b_ for b_ in bodies(BOB)), bodies(BOB))
    arm("CS3 ...and the file db sent on it", get(BOB, shf) == 200, get(BOB, shf))
    code = cl.get("/api/ws/artifacts", params={"thread": SH}, headers=BOB()).status_code
    arm("CS3 ...and its Library", code == 200, code)
    po = cl.post("/api/messages", headers=BOB(), json={"to": "db", "thread": SH, "body": "bob joins"})
    arm("CS4 bob talks in it (canvas parity)", po.status_code == 200, (po.status_code, po.text[:120]))
    arm("CS5 carol, not shared, reads none of it", bodies(CAROL) == [] and get(CAROL, shf) == 403, (bodies(CAROL), get(CAROL, shf)))
    po = cl.post("/api/messages", headers=CAROL(), json={"to": "db", "thread": SH, "body": "carol barges in"})
    arm("CS5 ...nor can she talk in it (a chat's id is no key)", po.status_code == 403, (po.status_code, po.text[:120]))
    r = share(BOB, ["8@fxcog", "9@fxcog"])
    arm("CS6 bob, shared but not its maker, can't share it on", r.status_code == 403, (r.status_code, r.text[:120]))
    r = share(ALICE, ["8@fxcog", "99@elsewhere"])
    arm("CS6 ...alice can't share with a non-member", r.status_code == 400, (r.status_code, r.text[:120]))
    for th, why in (("obs:db", "a desk"), ("cv:canvas-1", "a canvas's chat")):
        r = share(lambda: O, ["8@fxcog"], th)
        arm(f"CS7 {why} isn't shared as a chat", r.status_code == 400, (r.status_code, r.text[:120]))
    r = share(lambda: O, ["8@fxcog", "7@fxcog"], "chat:20990101-pb")
    arm("CS7 the owner shares any chat", r.status_code == 200, (r.status_code, r.text[:120]))
    r = share(ALICE, [])
    arm("CS8 alice unshares it: bob reads none of it again", r.status_code == 200 and bodies(BOB) == [] and get(BOB, shf) == 403,
        (r.status_code, bodies(BOB), get(BOB, shf)))
    po = cl.post("/api/messages", headers=ALICE(), json={"to": "medic", "thread": "chat:20990101-o", "body": "let me in"})
    arm("CS9 posting on the owner's chat doesn't make alice a party of it any more", po.status_code == 403
        and not any(m_["thread"] == "chat:20990101-o" for m_ in cl.get("/api/messages", params={"limit": 500}, headers=ALICE()).json()),
        (po.status_code, po.text[:120]))
    po = cl.post("/api/messages", headers=ALICE(), json={"to": "db", "thread": "chat:20990101-new", "body": "a new chat"})
    arm("CS9 ...a new chat of her own she starts as ever", po.status_code == 200, (po.status_code, po.text[:120]))

    with psycopg.connect(url, autocommit=True) as c:      # the registry names makers both ways (live: '14@…' and 'kumail-…')
        c.execute("INSERT INTO canvas_threads (thread, user_name, agent) VALUES ('cv:20990101-acct','7@fxcog','db'), "
                  "('cv:20990101-carol','carol.9','db')")
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                  "('cv-alice.7','db','cv:20990101-acct','chat','alice on her cv chat'), "
                  "('cv-alice.7','db','cv:20990101-carol','chat','alice wrote on carol''s')")
    arm("CS10 a chat registered under its maker's ACCOUNT opens to her (Kumail's cv chats are stored that way)",
        any("alice on her cv chat" in b_ for b_ in bodies(ALICE, "cv:20990101-acct")), bodies(ALICE, "cv:20990101-acct"))
    arm("CS10 a registered chat she only wrote on is not hers (its maker is carol)", bodies(ALICE, "cv:20990101-carol") == [],
        bodies(ALICE, "cv:20990101-carol"))
    r = share(ALICE, ["8@fxcog"], "cv:20990101-acct")
    arm("CS10 ...and she shares the one she made", r.status_code == 200, (r.status_code, r.text[:120]))

    print("R3 a reply names only a message the sender may read (medic 12990)")
    with psycopg.connect(url, autocommit=True) as c:
        own = c.execute("SELECT id FROM messages WHERE thread = 'chat:20990101-o' AND from_agent = 'medic' ORDER BY id LIMIT 1").fetchone()[0]
        hers = c.execute("SELECT id FROM messages WHERE thread = 'chat:20990101-s' AND from_agent = 'db' ORDER BY id LIMIT 1").fetchone()[0]
    rp = lambda h, mid, frm="medic", th="chat:20990101-s", to="db": cl.post("/api/messages", headers=h(), json={  # noqa: E731
        "to": to, "thread": th, "body": f"[reply #{mid} {frm}] “x”\nwhat did this say?"})
    r = rp(ALICE, own)
    arm("R3a alice can't reply to a message on the owner's chat (400): no agent reads it for her", r.status_code == 400, (r.status_code, r.text[:200]))
    r = rp(ALICE, hers, "db")
    arm("R3b her reply to a message in her own chat goes, stamped reply_to", r.status_code == 200, (r.status_code, r.text[:200]))
    with psycopg.connect(url, autocommit=True) as c:
        st = c.execute("SELECT delivery->'reply_to' FROM messages WHERE body LIKE %s ORDER BY id DESC LIMIT 1", (f"[reply #{hers} db]%",)).fetchone()
    arm("R3b ...the stamp is the id", st is not None and st[0] == hers, st)
    r = rp(ALICE, hers, "medic")
    arm("R3 a reference naming the wrong author is refused (400)", r.status_code == 400, r.status_code)
    r = rp(lambda: O, own, th="chat:20990101-o", to="medic")
    arm("R3c the owner replies to any message: 200", r.status_code == 200, (r.status_code, r.text[:200]))

    print("C canvases by members (owner 11-17, 12979)")
    with psycopg.connect(url, autocommit=True) as c:
        ca, cb, cc = (c.execute("INSERT INTO canvases (title, agent, user_name, tier, version, shared_with) VALUES "
                                "(%s,'db',%s,'org',1,%s) RETURNING id", (t, u, sw)).fetchone()[0]
                      for t, u, sw in (("shared with alice", "owner", ["7@fxcog"]), ("the owner's alone", "owner", []),
                                       ("alice's own", "alice.7", [])))
        for cid in (ca, cb, cc):
            c.execute("INSERT INTO canvas_versions (canvas_id, version, html, author) VALUES (%s,1,'<p>x</p>','db')", (cid,))
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                  "('owner','db',%s,'chat','on the shared canvas'), ('owner','db',%s,'chat','on the owner''s canvas')",
                  (f"cv:canvas-{ca}", f"cv:canvas-{cb}"))
    ids = lambda h: sorted(x["id"] for x in cl.get("/api/ws/canvases", headers=h()).json())  # noqa: E731
    arm("C1 alice lists the canvas shared with her and her own, not the owner's alone", ids(ALICE) == sorted([ca, cc]), ids(ALICE))
    arm("C1 the owner lists all three", {ca, cb, cc} <= set(ids(lambda: O)), ids(lambda: O))
    rc = lambda cid, h: cl.get(f"/api/ws/canvases/{cid}/render", headers=h()).status_code  # noqa: E731
    arm("C1 it renders for her; the owner's alone is 404", rc(ca, ALICE) == 200 and rc(cb, ALICE) == 404, (rc(ca, ALICE), rc(cb, ALICE)))
    th = lambda cid: [m["body"] for m in cl.get("/api/messages", params={"thread": f"cv:canvas-{cid}"}, headers=ALICE()).json()]  # noqa: E731
    arm("C2 she reads the shared canvas's conversation, not the owner's canvas's", th(ca) == ["on the shared canvas"] and th(cb) == [],
        (th(ca), th(cb)))
    sh = lambda cid, shared, h: cl.post(f"/api/ws/canvases/{cid}/share", json={"shared": shared}, headers=h())  # noqa: E731
    r = sh(ca, ["7@fxcog", "8@fxcog"], ALICE)
    arm("C3 she can't share a canvas she didn't make (403)", r.status_code == 403, (r.status_code, r.text[:200]))
    r = sh(cc, ["8@fxcog"], ALICE)
    arm("C3 she shares her own with bob, by account", r.status_code == 200 and r.json()["shared"] == ["8@fxcog"], (r.status_code, r.text[:200]))
    arm("C3 ...and bob lists it", cc in ids(BOB), ids(BOB))
    r = sh(cc, ["8@fxcog", "99@fxcog"], ALICE)
    arm("C3 never with a non-member (400)", r.status_code == 400, (r.status_code, r.text[:200]))
    r = sh(cb, ["7@fxcog"], lambda: O)
    arm("C3 the owner shares any canvas", r.status_code == 200 and cb in ids(ALICE), (r.status_code, ids(ALICE)))

    print("F features")
    dic = lambda h: cl.post("/api/chat/dictate/session", headers=h()).status_code  # noqa: E731
    r = dic(ALICE)
    arm("F1 a member's dictation passes the gate", r == 200, r)
    put = lambda h, **b: cl.put("/api/admin/features", headers=h(), json=b)  # noqa: E731
    arm("F3 the owner turns alice's dictation off", put(lambda: O, uid="7@fxcog", feature="dictate", allowed=False).status_code == 200)
    r = dic(ALICE)
    arm("F1 ...and then it is 403", r == 403, r)
    arm("F1 ...and her whoami says so", cl.get("/api/whoami", headers=ALICE()).json()["caps"] == {})
    call = lambda h: cl.get("/api/pilot/voice/status", headers=h())  # noqa: E731
    arm("F2 a member's Call is 403 by default", call(BOB).status_code == 403)
    r = put(CAROL, uid="8@fxcog", feature="call", allowed=True)
    arm("F3 an admin can't give the Call without a daily limit (spend stays the owner's to leave open)", r.status_code == 400, r.text)
    r = put(CAROL, uid="8@fxcog", feature="call", allowed=True, minutes=25)
    arm("F3 an admin gives bob the Call with 25 minutes", r.status_code == 200, (r.status_code, r.text))
    s = call(BOB)
    arm("F2 ...then his status answers, with his limit", s.status_code == 200 and s.json()["limit"] == 25, (s.status_code, s.text[:200]))
    sess = lambda agent: cl.post("/api/pilot/voice/session", headers=BOB(), json={"agent": agent})  # noqa: E731
    r = sess("medic")
    arm("F2 a session as medic, outside his agents, is 403", r.status_code == 403, r.text)
    mine = lambda: s_["mine"] if (s_ := call(BOB).json()) else None  # noqa: E731
    r = sess("db")
    arm("F2 as db it mints, charged the member floor at once (10 min)", r.status_code == 200 and mine() == 10.0, (r.text, mine()))
    rep = cl.post("/api/pilot/voice/usage", headers=BOB(), json={"id": r.json()["usage_id"], "seconds": 1})
    arm("R2 his browser reporting 1 s never lowers it", rep.status_code == 200 and mine() == 10.0, (rep.text, mine()))
    r2 = sess("db")
    arm("R2 a second call: 20 of his 25", r2.status_code == 200 and mine() == 20.0, (r2.text, mine()))
    r3 = sess("db")
    arm("R2 a third would pass 25: refused, and nothing charged", r3.status_code == 429 and "your voice minutes" in r3.text
        and mine() == 20.0, (r3.status_code, r3.text, mine()))
    arm("F3 an admin can't set an owner's", put(CAROL, uid="1@fxcog", feature="call", allowed=False).status_code == 403)
    arm("F3 a member can't set any", put(ALICE, uid="8@fxcog", feature="call", allowed=False).status_code == 403)
    arm("F3 an unknown feature is 400", put(lambda: O, uid="8@fxcog", feature="teleport", allowed=True).status_code == 400)
    arm("F3 allowed=null puts alice back on the default", put(lambda: O, uid="7@fxcog", feature="dictate", allowed=None).status_code == 200
        and dic(ALICE) == 200)
    lm = cl.get("/api/admin/members", headers=O).json()
    arm("F4 the members list carries the defaults and bob's override",
        lm["features"]["call"] == ["owner"] and lm["overrides"].get("8@fxcog", {}).get("call") == {"allowed": True, "minutes": 25},
        (lm.get("features"), lm.get("overrides")))
    act = cl.get("/api/admin/activity", params={"uid": "8@fxcog"}, headers=O).json()
    arm("F4 activity carries bob's voice minutes today", act.get("voice_minutes_today") == 20.0, act)
    cl.__exit__(None, None, None)


if __name__ == "__main__":
    try:
        with fixture_db() as fx, tempfile.TemporaryDirectory() as td:
            os.environ["ASTRYX_DSN"] = fx["url"]
            os.environ["OBS_KEY"] = KEY
            os.environ["ASTRYX_ORG"] = "fixture.example"
            os.environ["ASTRYX_GATEWAY_PORT"] = "9"
            os.environ.setdefault("ASTRYX_COG_REGISTRY", str(Path(td) / "absent.json"))
            os.environ.pop("OPENAI_API_KEY", None)
            main(Path(td), fx["url"])
    except FixtureUnavailable as e:
        from astryx.security.sqlguard.estate import unavailable
        unavailable("test_member_access", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: member access ({fails} failing)")
    sys.exit(1 if fails else 0)
