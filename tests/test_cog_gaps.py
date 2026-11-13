#!/usr/bin/env python3
"""Oracle: the gaps today's cog work left (cog-gaps, owner rulings 11-13: NO privacy within an org; who-asked via the
wire's existing tags; a member's chat list, search and briefing are a VIEW of her own, never a wall).

In-process, as tests/test_who_asked.py: the observatory's main app on a throwaway fixture database (fixture_db), the
cog sign-in stood up in a temp HOME (identity.make_keys), each signed identity minted with that key and sent from
127.0.0.1. The workspace and chat modules are re-bound to a temp estate, so no projects/meta file of the checkout is
written. Dummy keys only; nothing leaves the host, no live row is read or written.

  T1 THREAD TOOLS: a member renames/pins/switches a thread she is a party of (200), never another's (403); the owner
     any; dictation's routes pass the member gate
  T2 PROJECTS: a member adds her own (server-stamped `by`, a client's `by` ignored), may not change or drop another's,
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
    arm("T1 a viewer is 403", rv.status_code == 403, rv.status_code)
    arm("T1 dictation's routes pass the member gate", obs.member_may("POST", "/api/chat/dictate/session")
        and obs.member_may("POST", "/api/chat/dictate/usage"))

    # ── T2 projects ────────────────────────────────────────────────────────────────────────────────────────────
    print("T a member's own projects")
    po = {"id": "own", "name": "Owner's", "agents": ["seed"], "threads": ["chat:20990101-o"]}
    w = cl.put("/api/chat/projects", json=[po], headers={**O, "if-match": ""})
    arm("T2 the owner writes a project", w.status_code == 200, (w.status_code, w.text[:200]))
    g = cl.get("/api/chat/projects", headers=A()).json()
    arm("T2 a member reads the org's projects", [p["id"] for p in g.get("projects", [])] == ["own"], g)
    stored = [{k: v for k, v in p.items() if k != "missing"} for p in g["projects"]]
    pa = {"id": "mine", "name": "Alice's", "agents": ["seed"], "threads": ["chat:20990101-a"], "by": "owner"}
    w = cl.put("/api/chat/projects", json=stored + [pa], headers={**A(), "if-match": g["etag"]})
    got = {p["id"]: p for p in w.json().get("projects", [])} if w.status_code == 200 else {}
    arm("T2 a member adds her own project", w.status_code == 200 and "mine" in got, (w.status_code, w.text[:200]))
    arm("T2 ...stamped by her (a client's `by` ignored)", got.get("mine", {}).get("by") == ALICE, got.get("mine"))
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
    arm("T2 the owner's edit of hers keeps her `by`", mine.get("by") == ALICE and mine.get("emoji") == "🍌", (r.status_code, mine))

    # ── T3 owner-only stays owner-only ─────────────────────────────────────────────────────────────────────────
    print("T owner-only acts")
    for m, p in (("POST", "/api/ws/agents/seed/interrupt"), ("GET", "/api/goals"), ("GET", "/api/admin/members"),
                 ("GET", "/api/federation/peers"), ("GET", "/api/people/asks"), ("GET", "/api/db/databases")):
        st = cl.request(m, p, headers=A()).status_code
        arm(f"T3 a member at {m} {p} is 403", st == 403, st)
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
