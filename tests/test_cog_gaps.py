#!/usr/bin/env python3
"""Oracle: the gaps today's cog work left (cog-gaps, owner rulings 11-13: NO privacy within an org; who-asked via the
wire's existing tags; a member's chat list, search and briefing are a VIEW of her own, never a wall).

In-process, as tests/test_who_asked.py: the observatory's main app on a throwaway fixture database (fixture_db), the
cog sign-in stood up in a temp HOME (identity.make_keys), each signed identity minted with that key and sent from
127.0.0.1. The workspace and chat modules are re-bound to a temp estate, so no projects/meta file of the checkout is
written. Dummy keys only; nothing leaves the host, no live row is read or written.

  S1 SEARCH follows the view: a member's /api/ws/search finds her own threads only by default, ?scope=everyone every
     human's; the owner's default search is his own, as before
  S2 THREAD TITLES name a member's chat by the list's own derivation (her first line), and the owner's alike
  S3 THE BRIEFING is the viewer's: a member's counts and headlines are what the agents said TO HER; ?scope=everyone
     counts every human's; the owner's is his, as before; anonymous is 403. /api/ws/agents' last word is the viewer's
  T1 THREAD TOOLS: a member renames/pins/switches a thread she is a party of (200), never another's (403); the owner
     any; dictation's routes pass the member gate
  T2 PROJECTS: a member sees only the projects made by her or shared with her (owner 11-17); her write never drops one
     she can't see; she shares her own with members' handles; she adds her own (server-stamped `by`, a client's `by`
     ignored), may not change or drop another's,
     and files only her own conversations in hers; the owner's edit of hers keeps her `by`
  T3 OWNER-ONLY stays owner-only for a member: interrupt, goals, admin, federation, people, the db workbench
Exit 0 pass · 1 fail · 77 fixture unavailable."""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_cog_gaps", REPO, deps=("fastapi", "httpx", "asyncpg", "psycopg", "nacl"), env=False)   # fixture_db only
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402

KEY = "test-owner-key"
COG = "fxcog"
AUD = "fixture-org"
ALICE = "cv-alice.7"
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
    from astryx.security import identity
    from observatory.api import chat, workspace as W

    estate = tmp / "estate"
    (estate / "media").mkdir(parents=True)
    roster = {"seed", "db"}
    W.bind(lambda: obs.pool, estate, roster=lambda: roster)        # owner/me keep main's (owner_call, wire_handle)
    chat.bind(lambda: obs.pool, estate, estate / "media", REPO, roster=lambda: roster)

    home = tmp / "cog"
    home.mkdir()
    identity.make_keys(home)
    signer = identity.load_signer(home)
    obs._COGAUTH, obs._AUD = {"id": COG, "home": str(home)}, AUD
    obs._verifiers, obs._verifiers_at = {}, 0.0
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO members (uid, role) VALUES ('1@fxcog','owner'), ('7@fxcog','member'), ('9@fxcog','viewer')")
        for frm, to, th, body in (("owner", "seed", "chat:20990101-o", "owner banana plan"),
                                  ("seed", "owner", "chat:20990101-o", "reply to owner, banana?"),
                                  (ALICE, "seed", "chat:20990101-a", "alice banana question"),
                                  ("seed", ALICE, "chat:20990101-a", "for alice: the banana answer?")):
            c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES (%s,%s,%s,'chat',%s)",
                      (frm, to, th, body))

    def as_(sub, name=None):
        return {identity.HEADER: identity.mint(signer, sub, AUD, name=name)}

    O = {"x-obs-key": KEY}
    cl = TestClient(obs.app, raise_server_exceptions=bool(os.environ.get("GAPS_RAISE")), client=("127.0.0.1", 50000))
    cl.__enter__()
    A = lambda: as_("7@fxcog", "alice")                         # noqa: E731 — a fresh token each call (60 s TTL)

    # ── S1 search ──────────────────────────────────────────────────────────────────────────────────────────────
    print("S search follows the view")
    def threads_of(r):
        return sorted({h["thread"] for h in r.json().get("results", [])}) if r.status_code == 200 else (r.status_code, r.text[:200])
    sm = threads_of(cl.get("/api/ws/search", params={"q": "banana"}, headers=A()))
    se = threads_of(cl.get("/api/ws/search", params={"q": "banana", "scope": "everyone"}, headers=A()))
    so = threads_of(cl.get("/api/ws/search", params={"q": "banana"}, headers=O))
    sa = cl.get("/api/ws/search", params={"q": "banana"}).status_code
    arm("S1 a member's search finds her own thread only", sm == ["chat:20990101-a"], sm)
    arm("S1 ...?scope=everyone finds every human's", se == ["chat:20990101-a", "chat:20990101-o"], se)
    arm("S1 the owner's default search is his own (as before)", so == ["chat:20990101-o"], so)
    arm("S1 anonymous is 403", sa == 403, sa)

    # ── S2 thread titles ───────────────────────────────────────────────────────────────────────────────────────
    print("S thread titles")
    tt = cl.get("/api/ws/thread-titles", params={"ids": "chat:20990101-a,chat:20990101-o"}, headers=A()).json().get("titles", {})
    arm("S2 a member's chat is named by her first line", tt.get("chat:20990101-a", "").lower().startswith("alice banana"), tt)
    arm("S2 the owner's chat is named by his", tt.get("chat:20990101-o", "").lower().startswith("owner banana"), tt)

    # ── S3 briefing + team cards ───────────────────────────────────────────────────────────────────────────────
    print("S the briefing is the viewer's")
    def seed_of(r):
        if r.status_code != 200:
            return (r.status_code, r.text[:200])
        return next((a for a in r.json().get("agents", []) if a["agent"] == "seed"), {})
    bm = seed_of(cl.get("/api/ws/briefing", headers=A()))
    be = seed_of(cl.get("/api/ws/briefing", params={"scope": "everyone"}, headers=A()))
    bo = seed_of(cl.get("/api/ws/briefing", headers=O))
    ba = cl.get("/api/ws/briefing").status_code
    said = lambda b: [s["headline"].lower() for s in b.get("said", [])] if isinstance(b, dict) else b   # noqa: E731
    arm("S3 a member's briefing: what seed said to HER", isinstance(bm, dict) and bm.get("to_owner") == 1
        and said(bm) and said(bm)[0].startswith("for alice"), bm)
    arm("S3 ...she is waiting on (its last line to her asks)", isinstance(bm, dict) and bool(bm.get("waiting")), bm)
    arm("S3 ...?scope=everyone counts every human's", isinstance(be, dict) and be.get("to_owner") == 2, be)
    arm("S3 the owner's briefing is his (as before)", isinstance(bo, dict) and bo.get("to_owner") == 1
        and said(bo)[0].startswith("reply to owner"), bo)
    arm("S3 anonymous is 403", ba == 403, ba)
    ag = {a["agent"]: a for a in cl.get("/api/ws/agents", headers=A()).json()}
    ao = {a["agent"]: a for a in cl.get("/api/ws/agents", headers=O).json()}
    arm("S3 /api/ws/agents: seed's last word is the viewer's", ag.get("seed", {}).get("last_said", "").startswith("for alice")
        and ao.get("seed", {}).get("last_said", "").startswith("reply to owner"), (ag.get("seed"), ao.get("seed")))

    # ── T1 thread tools ────────────────────────────────────────────────────────────────────────────────────────
    print("T a member's own thread tools")
    r1 = cl.put("/api/ws/threads/meta", json={"thread": "chat:20990101-a", "title": "Alice's", "pinned": True}, headers=A())
    r2 = cl.put("/api/ws/threads/meta", json={"thread": "chat:20990101-o", "title": "hijack"}, headers=A())
    r3 = cl.put("/api/ws/threads/meta", json={"thread": "chat:20990101-a", "switch_to": ["db"]}, headers=A())
    r4 = cl.put("/api/ws/threads/meta", json={"thread": "chat:20990101-a", "pinned": False}, headers=O)
    rv = cl.put("/api/ws/threads/meta", json={"thread": "chat:20990101-a", "title": "x"}, headers=as_("9@fxcog", "vic"))
    arm("T1 a member renames + pins her own thread", r1.status_code == 200 and r1.json().get("title") == "Alice's", (r1.status_code, r1.text[:200]))
    arm("T1 ...and switches it", r3.status_code == 200 and r3.json().get("switches"), (r3.status_code, r3.text[:200]))
    arm("T1 ...never another human's (403, nothing written)", r2.status_code == 403
        and "hijack" not in (W.meta_file().read_text() if W.meta_file().exists() else ""), r2.status_code)
    arm("T1 the owner changes any thread", r4.status_code == 200, r4.status_code)
    tt = cl.get("/api/ws/thread-titles", params={"ids": "chat:20990101-a"}, headers=O).json().get("titles", {})
    arm("S2 a member's renamed chat is named by her title (the list's derivation, not a raw label)",
        tt.get("chat:20990101-a") == "Alice's", tt)
    arm("T1 a viewer is 403", rv.status_code == 403, rv.status_code)
    arm("T1 dictation's routes are the dictate feature's, which a member holds by default (owner 11-17)",
        obs.FEATURE_PATHS["dictate"] == {("POST", "/api/chat/dictate/session"), ("POST", "/api/chat/dictate/usage")}
        and "member" in obs._members.FEATURES["dictate"])

    # ── T2 projects ────────────────────────────────────────────────────────────────────────────────────────────
    print("T a member's own projects")
    po = {"id": "own", "name": "Owner's", "agents": ["seed"], "threads": ["chat:20990101-o"]}
    w = cl.put("/api/chat/projects", json=[po], headers={**O, "if-match": ""})
    arm("T2 the owner writes a project", w.status_code == 200, (w.status_code, w.text[:200]))
    g = cl.get("/api/chat/projects", headers=A()).json()
    arm("T2 a member doesn't see a project nobody shared with her (owner 11-17)", g.get("projects") == [], g)
    w = cl.put("/api/chat/projects", json=[{**po, "shared": ["7@fxcog"]}], headers={**O, "if-match": w.json()["etag"]})
    g = cl.get("/api/chat/projects", headers=A()).json()
    arm("T2 ...once the owner shares it with her, she does", [p["id"] for p in g.get("projects", [])] == ["own"], g)
    stored = [{k: v for k, v in p.items() if k != "missing"} for p in g["projects"]]
    pa = {"id": "mine", "name": "Alice's", "agents": ["seed"], "threads": ["chat:20990101-a"], "by": "owner"}
    w = cl.put("/api/chat/projects", json=stored + [pa], headers={**A(), "if-match": g["etag"]})
    got = {p["id"]: p for p in w.json().get("projects", [])} if w.status_code == 200 else {}
    arm("T2 a member adds her own project", w.status_code == 200 and "mine" in got, (w.status_code, w.text[:200]))
    arm("T2 ...stamped by her (a client's `by` ignored)", got.get("mine", {}).get("by") == "7@fxcog", got.get("mine"))
    arm("T2 ...the owner's carries no `by`", "by" not in got.get("own", {"by": 1}), got.get("own"))
    tag = w.json().get("etag", "") if w.status_code == 200 else ""
    cur = [{k: v for k, v in p.items() if k != "missing"} for p in got.values()]
    before = chat.projects_file().read_text()
    for label, body in (("change the owner's", [{**p, "name": "Mine now"} if p["id"] == "own" else p for p in cur]),
                        ("drop the owner's", [p for p in cur if p["id"] != "own"]),
                        ("file the owner's thread in hers", [{**p, "threads": p["threads"] + ["chat:20990101-o"]}
                                                             if p["id"] == "mine" else
                                                             {**p, "threads": []} if p["id"] == "own" else p for p in cur])):
        r = cl.put("/api/chat/projects", json=body, headers={**A(), "if-match": tag})
        arm(f"T2 a member may not {label}: 403, nothing written",
            r.status_code == 403 and chat.projects_file().read_text() == before, (r.status_code, r.text[:200]))
    r = cl.put("/api/chat/projects", json=[{**p, "name": "Alice renamed"} if p["id"] == "mine" else p for p in cur],
               headers={**A(), "if-match": tag})
    arm("T2 a member edits her own", r.status_code == 200, (r.status_code, r.text[:200]))
    cur = [{k: v for k, v in p.items() if k != "missing"} for p in r.json().get("projects", [])]
    r = cl.put("/api/chat/projects", json=[{**p, "emoji": "🍌"} if p["id"] == "mine" else p for p in cur],
               headers={**O, "if-match": r.json().get("etag", "")})
    mine = next((p for p in r.json().get("projects", []) if p["id"] == "mine"), {}) if r.status_code == 200 else {}
    arm("T2 the owner's edit of hers keeps her `by`", mine.get("by") == "7@fxcog" and mine.get("emoji") == "🍌", (r.status_code, mine))
    cur = [{k: v for k, v in p.items() if k != "missing"} for p in r.json().get("projects", [])]
    r = cl.put("/api/chat/projects", json=[{**p, "shared": []} if p["id"] == "own" else p for p in cur],
               headers={**O, "if-match": r.json().get("etag", "")})
    g = cl.get("/api/chat/projects", headers=A()).json()
    arm("T2 unshared, the owner's project leaves her list", [p["id"] for p in g.get("projects", [])] == ["mine"], g)
    mine_only = [{k: v for k, v in p.items() if k != "missing"} for p in g["projects"]]
    r = cl.put("/api/chat/projects", json=[{**mine_only[0], "name": "Alice again"}], headers={**A(), "if-match": g["etag"]})
    stored = {p["id"] for p in chat._read_projects()}
    arm("T2 her write of the list she sees keeps the project she can't see", r.status_code == 200 and stored == {"own", "mine"},
        (r.status_code, r.text[:200], stored))
    tag = r.json().get("etag", "")
    for bad in ("not an account", "5@fxcog"):            # a shape, and an account that is no member here
        r = cl.put("/api/chat/projects", json=[{**mine_only[0], "shared": [bad]}], headers={**A(), "if-match": tag})
        arm(f"T2 a project is shared only with this org's members ({bad}: 400)", r.status_code == 400, (r.status_code, r.text[:200]))
    r = cl.put("/api/chat/projects", json=[{**mine_only[0], "shared": ["9@fxcog"]}], headers={**A(), "if-match": tag})
    arm("T2 she shares her own with a member, by account", r.status_code == 200 and r.json()["projects"][0]["shared"] == ["9@fxcog"],
        (r.status_code, r.text[:200]))
    ppl = cl.get("/api/chat/people", headers=A()).json().get("people")
    arm("T2 who she can share with is the members table: every member but her, owners aside (they see all)",
        ppl == ["9@fxcog"], ppl)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DELETE FROM members WHERE uid = '9@fxcog'")           # the member hers is shared with leaves
    g = cl.get("/api/chat/projects", headers=O).json()
    cur = [{k: v for k, v in p.items() if k not in ("missing", "yours")} for p in g["projects"]]
    r = cl.put("/api/chat/projects", json=[{**p, "name": "Owner's, renamed"} if p["id"] == "own" else p for p in cur],
               headers={**O, "if-match": g["etag"]})
    left = next((p for p in chat._read_projects() if p["id"] == "mine"), {}).get("shared")
    arm("T2 a member removed from the org doesn't lock saves, and drops out of what was shared (medic 12883)",
        r.status_code == 200 and left == [], (r.status_code, r.text[:200], left))
    os.environ["ASTRYX_WS_STORE"] = str(tmp / "store")       # a project's files: artifacts on thread project:<id>
    from observatory.api import artifacts as AR
    AR.bind(lambda: obs.pool, estate)
    aid = AR.store().create("project:own", "plan.md", "the owner's plan", "owner")["id"]
    lib = lambda: [a["id"] for a in cl.get("/api/ws/artifacts", headers=A()).json()]  # noqa: E731
    by_id = lambda: (cl.get(f"/api/ws/artifacts/{aid}", headers=A()).status_code,     # noqa: E731
                     cl.get(f"/api/ws/artifacts/{aid}/content", headers=A()).status_code)
    arm("T2 a project she can't see: its file is not in her library, and 403 by id and by content",
        aid not in lib() and by_id() == (403, 403), (lib(), by_id()))
    cur = [{k: v for k, v in p.items() if k != "missing"} for p in cl.get("/api/chat/projects", headers=O).json()["projects"]]
    r = cl.put("/api/chat/projects", json=[{**p, "shared": ["7@fxcog"]} if p["id"] == "own" else p for p in cur],
               headers={**O, "if-match": cl.get("/api/chat/projects", headers=O).json()["etag"]})
    arm("T2 ...shared with her, it is in her library and 200 by id and by content",
        r.status_code == 200 and aid in lib() and by_id() == (200, 200), (r.status_code, lib(), by_id()))

    # ── T3 owner-only stays owner-only ─────────────────────────────────────────────────────────────────────────
    print("T owner-only acts")
    for m, p in (("POST", "/api/ws/agents/seed/interrupt"), ("GET", "/api/goals"), ("GET", "/api/admin/members"),
                 ("GET", "/api/federation/peers"), ("GET", "/api/people/asks"), ("GET", "/api/db/databases")):
        st = cl.request(m, p, headers=A()).status_code
        arm(f"T3 a member at {m} {p} is 403", st == 403, st)

    # ── P1 the pipe to canvas carries the VERIFIED identity (canvas then verifies it again) ─────────────────────
    print("P the observatory's pipe to canvas")
    import httpx
    seen = []

    def upstream(req):
        seen.append((req.url.path, req.headers.get(identity.HEADER)))
        return httpx.Response(200, stream=httpx.ByteStream(b"{}"))      # unread: _pipe streams it
    real_http, real_cog = obs._canvas_http, obs._COG
    obs._canvas_http, obs._COG = httpx.AsyncClient(transport=httpx.MockTransport(upstream)), True
    try:
        ha = A()
        cl.get("/canvas/api/me", headers=ha)
        forged = {identity.HEADER: identity.mint(identity.load_signer(home), "7@fxcog", "another-org", name="alice")}
        cl.get("/canvas/api/me", headers=forged)
        cl.get("/canvas/api/me")
        far = TestClient(obs.app, client=("10.9.9.9", 50000))
        far.get("/canvas/api/me", headers=A())
    finally:
        obs._canvas_http, obs._COG = real_http, real_cog
    got = [h for _, h in seen]
    arm("P1 four requests reached canvas", len(seen) == 4, seen)
    arm("P1 a token _who verified (from the front) is passed to canvas as is", got[:1] == [ha[identity.HEADER]], got)
    arm("P1 a token _who refused (wrong aud) is never passed", len(got) > 1 and got[1] is None, got)
    arm("P1 no token, nothing passed; from a non-front peer, nothing passed", got[2:] == [None, None], got)
    cl.__exit__(None, None, None)


if __name__ == "__main__":
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
        unavailable("test_cog_gaps", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: cog gaps ({fails} failing)")
    sys.exit(1 if fails else 0)
