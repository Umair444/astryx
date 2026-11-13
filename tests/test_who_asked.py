#!/usr/bin/env python3
"""Oracle: cog-rebuild Phase 2 option (a), "who asked" (owner rulings 11-13: tag only, the wire's EXISTING structure,
no privacy within an org, per-user chat lists a VIEW).

In-process: the observatory's main app on a throwaway fixture database (fixture_db), the cog sign-in stood up in a
temp HOME (identity.make_keys), every signed identity minted by identity.mint with that key and sent from 127.0.0.1
(the only peer _who believes). Dummy keys only; nothing leaves the host, no live row is read or written.

  H1 THE HANDLE RULE (main.member_handle): cv-<slug(label)>.<uid>; no label -> cv-u.<uid>; a sub with no numeric uid
     -> None. Every handle is addressable (address.check: the existing cv- surface) and can never be a canvas invitee's
     name (canvas.py's invite regex has no '.').
  W1 A MEMBER'S POST is stamped: from_agent = their handle, from_org 'local' (the observatory's surface tag), and
     delivery {surface 'observatory', display_name, role 'member'} (canvas's own stamp shape).
  W2 THE OWNER'S POST is the row it always was: 'owner', delivery NULL, through the key door AND as a signed-in owner.
  W3 a viewer, an anonymous caller and a member at an owner-only ACT (interrupt, goals) are 403; whoami names the
     member's role and handle, and the owner's as before (owner true, handle 'owner').
  R1 A REPLY TO THE HANDLE is delivered on that thread: canvas.py's own CLAIM (executed on the fixture) takes the
     agent->cv-<x>.<n> row on the chat: thread, and leaves the agent->owner reply on a chat: thread alone (as ever);
     /api/thread/read by the member marks only rows to HER handle, the owner's only his.
  R3 /api/chat/file for a member passes the gate only for a path some message ATTACHED ([[file:…]]); a viewer never.
  R2 the member reads the wire as the owner does (no privacy within an org): GET /api/messages?thread= returns the
     owner-only thread unfiltered for her, and filtered (nothing) for an anonymous caller.
  V1 THE VIEW: /api/ws/threads defaults to the viewer's own conversations (member: hers; owner: his), and
     ?scope=everyone lists every human's, each row naming who opened it (`by`).
  N1 THE NOTIFICATION (channel/asker.mjs, executed by node): a member's row -> role "member"; the owner's row -> none
     (even with a forged delivery.role); a canvas guest's row with no role -> none. server.mjs spreads asker(row)
     into the <channel> meta, its instructions carry the WHO ASKED line, and the permission VERDICT still requires
     from_agent === 'owner' (a member's "yes abcde" is chat, never a verdict).
Exit 0 pass · 1 fail · 77 fixture unavailable."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_who_asked", REPO, deps=("fastapi", "httpx", "asyncpg", "psycopg", "nacl"), env=False)   # fixture_db only
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402

KEY = "test-owner-key"
COG = "fxcog"
AUD = "fixture-org"
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def canvas_claim_sql() -> str:
    """bridges/canvas.py's CLAIM, read from the file (importing the bridge would start it)."""
    src = (REPO / "bridges" / "canvas.py").read_text()
    m = re.search(r'^CLAIM = """(.*?)"""', src, re.S | re.M)
    return m.group(1)


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
    from astryx.core import address

    # ── H1 the handle rule ─────────────────────────────────────────────────────────────────────────────────────
    print("H1 the handle rule")
    mh = obs.member_handle
    arm("H1 cv-<slug(label)>.<uid>", mh("7@fxcog", "Alice.Smith+x") == "cv-alice-smith-x.7", mh("7@fxcog", "Alice.Smith+x"))
    arm("H1 no label -> cv-u.<uid>", mh("12@fxcog", "") == "cv-u.12", mh("12@fxcog", ""))
    arm("H1 no numeric uid -> None", mh("bob@fxcog", "bob") is None and mh("7", "x") is None)
    arm("H1 a long label is clipped, the uid kept", mh("3@c", "a" * 80) == "cv-" + "a" * 24 + ".3")
    invitee = re.compile(r"[a-z][a-z0-9_-]{1,30}")         # bridges/canvas.py invite()
    hs = [mh("7@c", "alice"), mh("12@c", ""), mh("3@c", "o'brien")]
    arm("H1 every handle is addressable (the cv- surface)", all(address.check(h)[0] for h in hs), [address.check(h) for h in hs])
    arm("H1 no handle can be a canvas invitee's name", not any(invitee.fullmatch(h[3:]) for h in hs), hs)
    arm("H1 the canvas invite regex is still the one this oracle assumes",
        r're.fullmatch(r"[a-z][a-z0-9_-]{1,30}", name)' in (REPO / "bridges/canvas.py").read_text())

    # ── the cog sign-in, in a temp HOME ────────────────────────────────────────────────────────────────────────
    home = tmp / "cog"
    home.mkdir()
    identity.make_keys(home)
    signer = identity.load_signer(home)
    obs._COGAUTH, obs._AUD = {"id": COG, "home": str(home)}, AUD
    obs._verifiers, obs._verifiers_at = {}, 0.0
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO members (uid, role) VALUES ('1@fxcog','owner'), ('7@fxcog','member'), ('9@fxcog','viewer')")

    def as_(sub, name=None):
        return {identity.HEADER: identity.mint(signer, sub, AUD, name=name)}

    O = {"x-obs-key": KEY}
    cl = TestClient(obs.app, raise_server_exceptions=bool(os.environ.get("WHO_RAISE")), client=("127.0.0.1", 50000))
    cl.__enter__()
    anon = cl                                   # no key, no identity: the public face (one client: one lifespan, one pool)
    ALICE = "cv-alice.7"

    # ── W1/W2/W3 posting ───────────────────────────────────────────────────────────────────────────────────────
    print("W posting")
    r = cl.post("/api/messages", json={"to": "seed", "body": "member asks", "thread": "chat:20990101-alice"},
                headers=as_("7@fxcog", "alice"))
    arm("W1 a member's post is 200", r.status_code == 200, (r.status_code, r.text[:200]))
    with psycopg.connect(url, autocommit=True) as c:
        row = c.execute("SELECT from_agent, from_org, to_agent, delivery FROM messages WHERE body='member asks'").fetchone()
    arm("W1 from_agent is the member's handle", row and row[0] == ALICE, row)
    arm("W1 from_org stays the surface tag 'local'", row and row[1] == "local", row)
    arm("W1 delivery = {surface, display_name, role}",
        row and row[3] == {"surface": "observatory", "display_name": "alice", "role": "member"}, row)

    r1 = cl.post("/api/messages", json={"to": "seed", "body": "owner via key", "thread": "chat:20990101-owner"}, headers=O)
    r2 = cl.post("/api/messages", json={"to": "seed", "body": "owner signed", "thread": "chat:20990101-owner"},
                 headers=as_("1@fxcog", "umair"))
    with psycopg.connect(url, autocommit=True) as c:
        rows = c.execute("SELECT body, from_agent, from_org, delivery FROM messages WHERE body LIKE 'owner %' ORDER BY id").fetchall()
    arm("W2 the owner's posts are 200", r1.status_code == 200 and r2.status_code == 200, (r1.status_code, r2.status_code))
    arm("W2 key door and signed owner both write 'owner', local, delivery NULL",
        rows == [("owner via key", "owner", "local", None), ("owner signed", "owner", "local", None)], rows)

    rv = cl.post("/api/messages", json={"to": "seed", "body": "viewer"}, headers=as_("9@fxcog", "vic"))
    ra = anon.post("/api/messages", json={"to": "seed", "body": "anon"})
    arm("W3 a viewer is 403", rv.status_code == 403, rv.status_code)
    arm("W3 anonymous is 403", ra.status_code == 403, ra.status_code)
    ri = cl.post("/api/ws/agents/seed/interrupt", headers=as_("7@fxcog", "alice"))
    rg = cl.get("/api/goals", headers=as_("7@fxcog", "alice"))
    arm("W3 owner-only acts stay owner-only for a member (interrupt, goals)", ri.status_code == 403 and rg.status_code == 403,
        (ri.status_code, rg.status_code))
    wm = cl.get("/api/whoami", headers=as_("7@fxcog", "alice")).json()
    wo = cl.get("/api/whoami", headers=O).json()
    arm("W3 whoami names the member", wm.get("owner") is False and wm.get("role") == "member" and wm.get("handle") == ALICE, wm)
    arm("W3 whoami for the owner is as before (+ handle 'owner')", wo.get("owner") is True and wo.get("handle") == "owner", wo)

    # ── R1/R2 replies ──────────────────────────────────────────────────────────────────────────────────────────
    print("R replies")
    with psycopg.connect(url, autocommit=True) as c:
        to_alice = c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                             "('seed', %s, 'chat:20990101-alice', 'chat', 'reply to alice') RETURNING id", (ALICE,)).fetchone()[0]
        to_owner = c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                             "('seed', 'owner', 'chat:20990101-owner', 'chat', 'reply to owner') RETURNING id").fetchone()[0]
        to_alice2 = c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                              "('seed', %s, 'chat:20990101-alice', 'chat', 'second reply') RETURNING id", (ALICE,)).fetchone()[0]
        # thread/read first (the canvas bridge not yet run): a member marks only rows to HER handle
        rr = cl.post("/api/thread/read", json={"thread": "chat:20990101-alice", "upto": to_alice2},
                     headers=as_("7@fxcog", "alice"))
        ro = cl.post("/api/thread/read", json={"thread": "chat:20990101-alice", "upto": to_alice2}, headers=O)
        arm("R1 /api/thread/read: the member marks her replies", rr.status_code == 200 and rr.json().get("marked") == [to_alice, to_alice2], rr.text[:200])
        arm("R1 /api/thread/read: the owner never marks a member's reply", ro.status_code == 200 and ro.json().get("marked") == [], ro.text[:200])
        c.execute("UPDATE messages SET status='pending', delivered_at=NULL, delivery=NULL WHERE id = ANY(%s)", ([to_alice, to_alice2],))
        claimed = [x[0] for x in c.execute(canvas_claim_sql()).fetchall()]
        st = dict(c.execute("SELECT id, status FROM messages WHERE id = ANY(%s)", ([to_alice, to_owner],)).fetchall())
    arm("R1 canvas.py's CLAIM delivers the reply to the member's handle on her chat: thread",
        to_alice in claimed and st.get(to_alice) == "delivered", (claimed, st))
    arm("R1 ...and leaves the agent->owner reply on a chat: thread alone (owner unchanged)",
        to_owner not in claimed and st.get(to_owner) == "pending", (claimed, st))
    # canvas.py's claim() then runs thread_user's INSERT for that row: canvas_threads takes a member's bare name
    ins = re.search(r'"(INSERT INTO canvas_threads \(thread, user_name, agent, title\) VALUES \(\$1,\$2,\$3,\$4\) )"\s*"(ON CONFLICT \(thread\) DO NOTHING)"',
                    (REPO / "bridges" / "canvas.py").read_text())
    arm("R1 thread_user's canvas_threads INSERT is the one this oracle runs", bool(ins))
    if ins:
        sql = (ins.group(1) + ins.group(2)).replace("$1", "%s").replace("$2", "%s").replace("$3", "%s").replace("$4", "%s")
        try:
            with psycopg.connect(url, autocommit=True) as c:
                c.execute(sql, ("chat:20990101-alice", ALICE[3:], "seed", "reply to alice"))
                u = c.execute("SELECT user_name FROM canvas_threads WHERE thread='chat:20990101-alice'").fetchone()
            arm("R1 ...and registers the chat under the member (no FK/CHECK refuses alice.7)", u == (ALICE[3:],), u)
        except psycopg.Error as e:
            arm("R1 ...and registers the chat under the member (no FK/CHECK refuses alice.7)", False, e)
    # /api/chat/file: a member opens what the wire ATTACHED, never any path under the homes
    att = tmp / "estate-media" / "att.txt"
    att.parent.mkdir(parents=True, exist_ok=True)
    att.write_text("attached\n")
    other = att.parent / "other.txt"
    other.write_text("not attached\n")
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO messages (from_agent, to_agent, thread, intent, body) VALUES "
                  "('seed', %s, 'chat:20990101-alice', 'chat', %s)", (ALICE, f"here [[file:{att}]]"))
    fa = cl.get("/api/chat/file", params={"path": str(att)}, headers=as_("7@fxcog", "alice")).status_code
    fo = cl.get("/api/chat/file", params={"path": str(other)}, headers=as_("7@fxcog", "alice")).status_code
    fv = cl.get("/api/chat/file", params={"path": str(att)}, headers=as_("9@fxcog", "vic")).status_code
    arm("R3 a member's /api/chat/file passes the gate for an attached path", fa != 403, fa)
    arm("R3 ...and is 403 for a path no message attached", fo == 403, fo)
    arm("R3 ...and a viewer is 403 even for the attached one", fv == 403, fv)
    gm = cl.get("/api/messages", params={"thread": "chat:20990101-owner"}, headers=as_("7@fxcog", "alice")).json()
    ga = anon.get("/api/messages", params={"thread": "chat:20990101-owner"}).json()
    arm("R2 a member reads the owner's thread unfiltered", sorted(m["body"] for m in gm) == ["owner signed", "owner via key", "reply to owner"], gm)
    arm("R2 anonymous still gets the public rule (nothing local)", ga == [], ga)

    # ── V1 the view ────────────────────────────────────────────────────────────────────────────────────────────
    print("V the per-user list (a view)")
    tm = [t["thread"] for t in cl.get("/api/ws/threads", headers=as_("7@fxcog", "alice")).json()["threads"]]
    to = [t["thread"] for t in cl.get("/api/ws/threads", headers=O).json()["threads"]]
    ev = cl.get("/api/ws/threads", params={"scope": "everyone"}, headers=O).json()
    te = {t["thread"]: t.get("by") for t in ev["threads"]}
    arm("V1 a member's default list is her own chats", tm == ["chat:20990101-alice"], tm)
    arm("V1 the owner's default list is his own (as before)", to == ["chat:20990101-owner"], to)
    arm("V1 ?scope=everyone lists every human's, naming who opened each",
        ev.get("scope") == "everyone" and te == {"chat:20990101-alice": ALICE, "chat:20990101-owner": "owner"}, te)
    cl.__exit__(None, None, None)

    # ── N1 the notification ────────────────────────────────────────────────────────────────────────────────────
    print("N the agent's notification")
    cases = {
        "member": {"from_agent": ALICE, "delivery": {"surface": "observatory", "display_name": "alice", "role": "member"}},
        "owner_forged": {"from_agent": "owner", "delivery": {"role": "member"}},
        "owner_plain": {"from_agent": "owner", "delivery": None},
        "guest": {"from_agent": "cv-bob", "delivery": {"surface": "canvas", "display_name": "bob"}},
        "bad_role": {"from_agent": ALICE, "delivery": {"role": "owner"}},
    }
    js = (f"import {{ asker }} from {json.dumps((REPO / 'channel' / 'asker.mjs').as_uri())};"
          f"const c = {json.dumps(cases)};"
          "console.log(JSON.stringify(Object.fromEntries(Object.entries(c).map(([k, r]) => [k, asker(r)]))))")
    p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30)
    got = json.loads(p.stdout or "{}") if p.returncode == 0 else {}
    arm("N1 asker.mjs runs", p.returncode == 0, p.stderr[-300:])
    arm("N1 a member's row -> role member", got.get("member") == "member", got)
    arm("N1 the owner's rows -> no role (even forged)", got.get("owner_forged") == "" and got.get("owner_plain") == "", got)
    arm("N1 a canvas guest without a stamp -> none; a stamp can't mint 'owner'", got.get("guest") == "" and got.get("bad_role") == "", got)
    srv = (REPO / "channel" / "server.mjs").read_text()
    arm("N1 server.mjs imports asker and spreads it into the <channel> meta",
        "import { asker } from './asker.mjs'" in srv and "...(asker(row) ? { role: asker(row) } : {})" in srv)
    arm("N1 the shared instructions carry the WHO ASKED line",
        "WHO ASKED: a human's from= is who asked" in srv and "still need the owner himself" in srv)
    arm("N1 a permission verdict still needs from_agent === 'owner'",
        "if (v && row.from_agent === 'owner' && openPermits.has" in srv and "row.intent === 'poll' && row.from_agent === 'owner'" in srv)
    meta = re.search(r"from: `\$\{row\.from_agent\}@\$\{row\.from_org\}`", srv)
    arm("N1 from= is still from_agent@from_org (the surface tag)", bool(meta))


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
        unavailable("test_who_asked", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: who asked ({fails} failing)")
    sys.exit(1 if fails else 0)
