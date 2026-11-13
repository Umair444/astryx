#!/usr/bin/env python3
"""Oracle: canvas recognizes the cog's sign-in (cog-gaps). A member signed in at the front who visits /o/<org>/canvas
was anonymous there: the observatory dropped the front's signed identity on its pipe to canvas (relay.FORWARD never
names it, D3) and canvas knew only its own cookie. Now main._pipe passes the token to canvas alone, only when it came
from the front and _who verified it, and canvas verifies it AGAIN (the cog's public keys, aud = its org, loopback) and
reads the role from THIS org's members table, mapping it by the who-asked rule: the owner is 'owner'; a member or an
admin is cv-<label>.<uid> (members.member_handle), the same handle and canvas_threads user her /chat uses.

A fixture registry with a `cog` block (two orgs, so the HOME names the org), keys made in the cog's home
(identity.make_keys), members rows in the org's fixture database, and the REAL bridges/canvas.py in a child process
(its org is resolved at import), driven in process (TestClient from 127.0.0.1, nothing bound). Dummy keys only.

  K1 the owner's token -> /api/me is the owner (wire 'owner')
  K2 a member's token -> /api/me names her cv-<label>.<uid>, not owner, every agent reachable (no privacy within an
     org); she opens a chat and says something: the row is from her handle, delivery {surface canvas, display_name
     <label>, role member}; canvas_threads registers it under <label>.<uid>
  K3 refused (401): no token; a VIEWER's token; a token for ANOTHER org (aud); a token signed by a key the cog never
     published; the right token from a non-loopback peer
  K4 a canvas cookie still wins: the owner's key login works as before, alongside
  M1 main.py: _pipe forwards the identity header only as the verified `vouched` extra (front + request.state.uid, not
     the ear), and relay.FORWARD still never names it
Exit 0 · 1 · 77."""
import atexit
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_canvas_signin', REPO, deps=('psycopg', 'asyncpg', 'fastapi', 'httpx', 'nacl'), env=False)
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

PY = sys.executable
COG = "fxcogsignin"
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


CHILD = r'''
import json, os, sys
from pathlib import Path
REPO, KEY, ORG, OTHER, COGHOME, ROGUE = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]
sys.path[:0] = [str(REPO), str(REPO / "src")]
import bridges.canvas as b
from astryx.security import identity
from fastapi.testclient import TestClient
signer, rogue = identity.load_signer(Path(COGHOME)), identity.load_signer(Path(ROGUE))
H = {"x-astryx": "1"}
pre = f"/o/{ORG}/canvas"
out = {"org": b._ORG}

def tok(sub, name=None, aud=None, key=None):
    return {identity.HEADER: identity.mint(key or signer, sub, aud or ORG, name=name)}

with TestClient(b.root, base_url="http://testserver", client=("127.0.0.1", 50000)) as cl:
    def me(h):
        cl.cookies.clear()
        r = cl.get("/canvas/api/me", headers=h)
        return [r.status_code, r.json() if r.status_code == 200 else None]
    out["owner"] = me(tok("1@" + sys.argv[7], "umair"))
    out["member"] = me(tok("7@" + sys.argv[7], "alice"))
    out["admin"] = me(tok("8@" + sys.argv[7], "ada"))
    out["none"] = me({})
    out["viewer"] = me(tok("9@" + sys.argv[7], "vic"))
    out["aud"] = me(tok("7@" + sys.argv[7], "alice", aud=OTHER))
    out["rogue"] = me(tok("7@" + sys.argv[7], "alice", key=rogue))
    cl.cookies.clear()
    r = cl.post("/canvas/api/threads", json={}, headers={**H, **tok("7@" + sys.argv[7], "alice")})
    out["new"] = [r.status_code, r.json() if r.status_code == 200 else r.text[:200]]
    if r.status_code == 200:
        th = r.json()["thread"]
        r = cl.post(f"/canvas/api/threads/{th}/messages", json={"body": "hello from canvas"},
                    headers={**H, **tok("7@" + sys.argv[7], "alice")})
        out["say"] = r.status_code
        out["thread"] = th
    cl.cookies.clear()
    r = cl.post("/canvas/api/login", json={"key": KEY}, headers=H)
    out["login"] = r.status_code
    c = next((x.split(";")[0] for x in r.headers.get_list("set-cookie") if x.startswith(b.COOKIE + "=")), "")
    cl.cookies.clear()
    r = cl.get("/canvas/api/me", headers={"cookie": c})
    out["cookie_me"] = [r.status_code, r.json() if r.status_code == 200 else None]
with TestClient(b.root, base_url="http://testserver", client=("10.9.9.9", 50000)) as cl:
    r = cl.get("/canvas/api/me", headers=tok("7@" + sys.argv[7], "alice"))
    out["remote"] = r.status_code
print("RESULT " + json.dumps(out))
'''


def main():
    import psycopg
    from astryx.security import identity
    t = Path(tempfile.mkdtemp(prefix="astryx-cvsign-")).resolve()
    atexit.register(shutil.rmtree, t, True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    pid = os.getpid()
    oa, ob = f"fxsga-{pid}", f"fxsgb-{pid}"
    cog_home, rogue = t / "cog", t / "rogue"
    identity.make_keys(cog_home)
    identity.make_keys(rogue)                      # a key the cog never published (its .pub is NOT in cog/keys)
    with fixture_db() as da:
        reg = {"cog": {"id": COG, "home": str(cog_home)}, "orgs": {}}
        for o, port in ((oa, 18191), (ob, 28191)):
            h = t / o
            (h / "agents").mkdir(parents=True)
            (h / "agents" / "seed.md").write_text("# seed\n*the founding agent*\n")
            (h / ".env").write_text(f"ASTRYX_ORG=fed-{o}\nASTRYX_DSN={da['url']}\nOBS_KEY=fx-owner-{o}\n")
            reg["orgs"][o] = {"home": str(h), "db": f"fxsgorg_{o.replace('-', '_')}",
                              "ports": {"astryx-canvas": port, "astryx-observatory-org": port + 9}}
        (t / "cog.json").write_text(json.dumps(reg))
        with psycopg.connect(da["url"], autocommit=True) as c:
            c.execute("INSERT INTO members (uid, role) VALUES (%s,'owner'), (%s,'member'), (%s,'viewer')",
                      (f"1@{COG}", f"7@{COG}", f"9@{COG}"))
            try:                                   # 'admin' where the members CHECK admits it (cog-rls slice 1)
                c.execute("INSERT INTO members (uid, role) VALUES (%s,'admin')", (f"8@{COG}",))
                admin = True
            except psycopg.Error:
                admin = False
        base = {k: os.environ[k] for k in ("PATH", "HOME", "ASTRYX_FIXTURE_ADMIN_DSN") if k in os.environ}
        env = {**base, "ASTRYX_COG_REGISTRY": str(t / "cog.json"), "ASTRYX_HOME": str(t / oa),
               "ASTRYX_DSN": da["url"], "OBS_KEY": f"fx-owner-{oa}"}
        p = subprocess.run([PY, "-c", CHILD, str(REPO), f"fx-owner-{oa}", oa, ob, str(cog_home), str(rogue), COG],
                           env=env, cwd=t, capture_output=True, text=True, timeout=180)
        g = next((json.loads(ln[7:]) for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
        if g is None:
            check("the child ran", False, (p.stderr or p.stdout)[-1200:])
            return
        with psycopg.connect(da["url"], autocommit=True) as c:
            row = c.execute("SELECT from_agent, from_org, delivery FROM messages WHERE body = 'hello from canvas'").fetchone()
            ct = c.execute("SELECT user_name FROM canvas_threads WHERE thread = %s", (g.get("thread", ""),)).fetchone()

    check("canvas's org is the HOME's registry name", g.get("org") == oa, g.get("org"))
    print("K1 the owner")
    st, body = g["owner"]
    check("K1 the owner's token -> /api/me is the owner", st == 200 and body["owner"] is True and body["wire"] == "owner", g["owner"])
    print("K2 a member")
    st, body = g["member"]
    check("K2 a member's token -> cv-<label>.<uid>, not owner", st == 200 and body["wire"] == "cv-alice.7"
          and body["name"] == "alice.7" and body["owner"] is False, g["member"])
    check("K2 ...every agent reachable (no privacy within an org)", st == 200 and body["agents"] == ["seed"], g["member"])
    if admin:
        check("K2 an admin is a member here too (cv-ada.8)", g["admin"][0] == 200 and g["admin"][1]["wire"] == "cv-ada.8", g["admin"])
    check("K2 she opens a chat with the home agent", g["new"][0] == 200 and g["new"][1].get("agent") == "seed", g["new"])
    check("K2 she says something: 200", g.get("say") == 200, g.get("say"))
    check("K2 the row is from her handle, stamped who asked (display_name, role member)",
          row is not None and row[0] == "cv-alice.7" and row[1] == "canvas"
          and row[2].get("display_name") == "alice" and row[2].get("role") == "member", row)
    check("K2 canvas_threads registers the chat under <label>.<uid> (/chat's canvas_user of her handle)",
          ct == ("alice.7",), ct)
    print("K3 refused")
    for k, why in (("none", "no token"), ("viewer", "a viewer's token"), ("aud", "a token for another org"),
                   ("rogue", "a key the cog never published")):
        check(f"K3 {why} -> 401", g[k][0] == 401, g[k])
    check("K3 the right token from a non-loopback peer -> 401", g.get("remote") == 401, g.get("remote"))
    print("K4 the cookie as before")
    check("K4 the owner's key login still works, and /api/me under its cookie is the owner",
          g.get("login") == 200 and g["cookie_me"][0] == 200 and g["cookie_me"][1]["owner"] is True, g)

    print("M1 main.py's pipe")
    msrc = (REPO / "observatory" / "api" / "main.py").read_text()
    check("M1 _pipe passes the identity only as the verified `vouched` extra (front, state.uid, not the ear)",
          "vouched = request.headers.get(_identity.HEADER) if (front and not owner_key and getattr(request.state, \"uid\", None)) else None" in msrc
          and "extra=[(_identity.HEADER, vouched)] if vouched else ()" in msrc)
    from astryx.security import relay
    check("M1 relay.FORWARD still never names the identity header (D3)", identity.HEADER not in relay.FORWARD)


if __name__ == "__main__":
    from astryx.security.sqlguard.estate import unavailable
    from astryx.security.sqlguard.fixture import FixtureUnavailable
    try:
        main()
    except FixtureUnavailable as e:
        unavailable("test_canvas_signin", REPO, e)
    print()
    print(f"FAILED ({len(fails)}): " + "; ".join(fails) if fails else
          "canvas knows the cog's sign-in: owner as owner, a member as cv-<label>.<uid>; everything else anonymous")
    sys.exit(1 if fails else 0)
