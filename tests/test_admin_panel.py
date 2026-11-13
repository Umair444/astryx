#!/usr/bin/env python3
"""The per-org ADMIN PANEL end to end (cog-rebuild, owner 11-13: "an option to create new user … whoever is the owner
of org can decide the roles of other users … it should be managed by an admin").

The REAL front (uvicorn front:app) before two REAL org observatories (uvicorn main:app, each its own fixture database
and HOME), on loopback sockets the children inherit (nothing binds 8090). The cog (its key, store schema, accounts and
the first memberships) is made by the REAL host CLI (src/astryx/cogauth.py); the store lives in org B's fixture
database. Org A's members table is migrated to the TREE-SCOPED contract (feat/cog-rls, 3f8d5d1: node, admin,
org_role(), the last-owner trigger; CONTRACT below, the tenant column aside); org B keeps main's first shape, so
observatory/api/members.py is exercised on both. Dummy passwords and keys only; nothing secret is printed.

  M1 THE OWNER SEES USERS: /auth/admin/users?org=A lists every account with a role in A (email, role, live sessions),
     the roles A's table admits (admin among them) and that it is tree-scoped; /api/admin/nodes is the agents/ tree
  M2 A MEMBER GETS 403: on /auth/admin/users, invite, reset, revoke-sessions and on A's /api/admin/* (GET, PUT,
     DELETE, activity); signed out is 401; the owner key still opens the backend's half
  M3 AN ADMIN MANAGES, BELOW OWNER: lists users; can't invite an owner, make one, change or remove one (403); can
     change a member's role (200)
  M4 INVITE → ACCEPT → SIGNED IN WITH THAT ROLE: a new email accepts a member invite and /auth/me names A member; a
     node-scoped invite lands on that node; an EXISTING account must prove its password (401, link kept) and then joins
     with its own sessions untouched; a used link is 410; cancel closes an open invite
  M5 THE LAST OWNER: A's only owner can neither remove nor demote itself (409), on the tree shape AND on B's first
     shape (the module's end-state check); once a second owner exists, the first may step down
  M6 RESET LINK, ONCE: the link sets a new password, revokes the account's live sessions, signs in; a second use 410;
     the old password no longer signs in, the new one does
  M7 SIGN OUT EVERYWHERE: revoke-sessions kills the target's session (/auth/me 401)
  M8 COG-WIDE GUARD: a reset or sign-out of an account that also holds a role in an org the caller doesn't manage is
     403 (sessions are cog-wide), and an admin can't reset an owner
  M9 LINKS EXPIRE: past `expires` /auth/link and /auth/accept are 410; an invite whose inviter has since lost the role
     is refused at accept (409) and leaves no account behind and the link open
  M10 ACTIVITY: counts only; with no attribution on the wire it says so (attributed false), never a zero
Exit 0 · 1 · 77 (no database, uvicorn or httpx).
"""
import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_admin_panel', REPO, deps=('psycopg', 'asyncpg', 'fastapi', 'httpx', 'uvicorn', 'cryptography'), env=False)
from astryx.security.sqlguard import propagate  # noqa: E402
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

PY = sys.executable
fails = []
ORIGIN = "http://fx-admin.invalid"
PW = {"owner": "fx-dummy-pass-owner-0001", "adm": "fx-dummy-pass-admin-0002", "mem": "fx-dummy-pass-membr-0003",
      "cross": "fx-dummy-pass-cross-0004", "new": "fx-dummy-pass-newbie-005", "node": "fx-dummy-pass-noder-0006",
      "reset": "fx-dummy-pass-reset-0007", "late": "fx-dummy-pass-later-0008"}
KEY = {"a": "fx-dummy-obskey-a-0001", "b": "fx-dummy-obskey-b-0002"}

# THE CONTRACT the members table moves to (feat/cog-rls slice 1, from 3f8d5d1), its tenant column aside: applied to org
# A's fixture after main's schema.sql, as that slice migrates a database of the first shape in place
CONTRACT = r"""
ALTER TABLE members ADD COLUMN IF NOT EXISTS node text NOT NULL DEFAULT '';
DO $$
BEGIN
  IF (SELECT array_length(conkey, 1) FROM pg_constraint
       WHERE conrelid = 'members'::regclass AND contype = 'p') IS DISTINCT FROM 2 THEN
    ALTER TABLE members DROP CONSTRAINT IF EXISTS members_pkey;
    ALTER TABLE members ADD CONSTRAINT members_pkey PRIMARY KEY (uid, node);
  END IF;
  ALTER TABLE members DROP CONSTRAINT IF EXISTS members_role_check;
  ALTER TABLE members ADD CONSTRAINT members_role_check CHECK (role IN ('owner', 'admin', 'member', 'viewer'));
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'members'::regclass AND conname = 'members_node_check') THEN
    ALTER TABLE members ADD CONSTRAINT members_node_check
      CHECK (node = '' OR node ~ '^[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*)*$');
  END IF;
END $$;
CREATE OR REPLACE FUNCTION member_role(p_uid text, p_node text DEFAULT '') RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT role FROM members
   WHERE uid = p_uid
     AND (node = '' OR node = p_node OR left(p_node, length(node) + 1) = node || '/')
   ORDER BY length(node) DESC
   LIMIT 1
$$;
CREATE OR REPLACE FUNCTION org_role(p_uid text) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT coalesce(member_role(p_uid, ''),
                  (SELECT CASE WHEN bool_or(role <> 'viewer') THEN 'member' WHEN count(*) > 0 THEN 'viewer' END
                     FROM members WHERE uid = p_uid))
$$;
CREATE OR REPLACE FUNCTION members_last_owner() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.role = 'owner' AND OLD.node = ''
     AND (TG_OP = 'DELETE' OR NEW.role <> 'owner' OR NEW.node <> '' OR NEW.uid <> OLD.uid)
     AND NOT EXISTS (SELECT 1 FROM members WHERE role = 'owner' AND node = '' AND uid <> OLD.uid)
     AND EXISTS (SELECT 1 FROM members WHERE uid <> OLD.uid) THEN
    RAISE EXCEPTION 'the last owner of this org can not be removed or demoted while it has other members'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;
DROP TRIGGER IF EXISTS members_last_owner ON members;
CREATE TRIGGER members_last_owner BEFORE DELETE OR UPDATE ON members
  FOR EACH ROW EXECUTE FUNCTION members_last_owner();
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {scrub(str(detail))}")


def scrub(s: str) -> str:
    for label, v in [*PW.items(), *KEY.items()]:
        s = s.replace(v, f"<{label}'s value>")
    return s


def listener() -> socket.socket:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(64)
    return s


def call(port, path, method="GET", body=None, headers=None, timeout=30):
    """(status, headers as a list of pairs, parsed JSON or the text)."""
    data = json.dumps(body).encode() if body is not None else None
    h = {"content-type": "application/json"} if body is not None else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=data,
                                 headers={**h, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            st, hs, txt = r.status, r.headers.items(), r.read().decode()
    except urllib.error.HTTPError as e:
        st, hs, txt = e.code, e.headers.items(), e.read().decode()
    try:
        return st, hs, json.loads(txt)
    except ValueError:
        return st, hs, txt


def session_of(hs) -> str:
    c = [v for k, v in hs if k.lower() == "set-cookie" and v.startswith("astryx_session=")]
    return c[0].split(";")[0] if c else ""


def wait(port, path, proc, t=60):
    end = time.time() + t
    while time.time() < end and proc.poll() is None:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2)
            return True
        except urllib.error.HTTPError:
            return True
        except OSError:
            time.sleep(0.3)
    return False


def main():
    t = Path(tempfile.mkdtemp(prefix="astryx-admin-")).resolve()
    atexit.register(shutil.rmtree, t, True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    procs = []
    atexit.register(lambda: [p.kill() for p in procs if p.poll() is None])
    cog_sql = (REPO / "src" / "astryx" / "sql" / "cog_schema.sql").read_text()
    with fixture_db(extra=(CONTRACT,)) as da, fixture_db(extra=(cog_sql,)) as dbb:
        run(t, da, dbb, procs)
    for p in procs:
        if p.poll() is None:
            p.terminate()
    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: the admin panel — users, roles, one-time "
          "links, sign out everywhere, and every guard")
    return 1 if fails else 0


def run(t, da, dbb, procs):
    import psycopg
    pid = os.getpid()
    oa, ob = f"fxad-a-{pid}", f"fxad-b-{pid}"
    cid = f"fxcog-{pid:08d}"
    socks = {k: listener() for k in ("a", "b", "front")}
    port = {k: s.getsockname()[1] for k, s in socks.items()}
    reg = {"orgs": {}}
    for o, d, k in ((oa, da, "a"), (ob, dbb, "b")):
        h = t / o
        h.mkdir()
        (h / ".env").write_text(f"ASTRYX_ORG=fed-{o}\nASTRYX_DSN={d['url']}\nOBS_KEY={KEY[k]}\n")
        reg["orgs"][o] = {"home": str(h), "db": f"fxaddb_{k}_{pid}", "ports": {"astryx-observatory-org": port[k]}}
    grp = t / oa / "agents" / "grp"             # A's agents/ tree: a group with one agent, for node-scoped roles
    grp.mkdir(parents=True)
    (grp / "scout.md").write_text("# scout\nA fixture agent.\n")
    (t / oa / "agents" / "solo.md").write_text("# solo\nA fixture agent.\n")
    home = t / "cog"
    home.mkdir()
    (home / ".env").write_text(f"ASTRYX_DSN={dbb['url']}\nASTRYX_COG_ORIGINS={ORIGIN}\n")
    regf = t / "cog.json"
    regf.write_text(json.dumps(reg))
    base = {k: os.environ[k] for k in ("PATH", "HOME", "ASTRYX_FIXTURE_ADMIN_DSN") if k in os.environ}
    cogbase = {**base, "ASTRYX_SQLGUARD_ROOT": str(REPO)}

    def cog(*args, stdin=None):
        return subprocess.run([PY, str(REPO / "src" / "astryx" / "cogauth.py"), *args], input=stdin,
                              capture_output=True, text=True, timeout=120,
                              env=propagate.env_for_child({**cogbase, "ASTRYX_COG_REGISTRY": str(regf)}))
    r = cog("init", "--home", str(home), "--id", cid)
    check("cogauth init (rc 0)", r.returncode == 0, r.stderr[-300:])
    reg["cog"] = {"id": cid, "home": str(home)}
    regf.write_text(json.dumps(reg))
    users = {k: f"{k}@fx-admin.invalid" for k in PW}
    for who in ("owner", "adm", "mem", "cross"):
        r = cog("user", "add", users[who], stdin=PW[who] + "\n")
        check(f"cogauth user add {who} (rc 0)", r.returncode == 0, r.stderr[-300:])
    for args in ((oa, "owner", "owner"), (oa, "adm", "admin"), (oa, "mem", "member"), (oa, "cross", "member"),
                 (ob, "cross", "owner"), (ob, "owner", "member")):
        r = cog("grant", args[0], users[args[1]], args[2])
        check(f"cogauth grant {'A' if args[0] == oa else 'B'} {args[1]} {args[2]} (rc 0)", r.returncode == 0,
              r.stderr[-300:])

    def acct(email):
        with psycopg.connect(dbb["url"]) as c:
            row = c.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        return f"{row[0]}@{cid}" if row else None

    def store(sql, *a):
        with psycopg.connect(dbb["url"], autocommit=True) as c:
            cur = c.execute(sql, a)
            return cur.fetchall() if cur.description else cur.rowcount

    def rows_a(uid):
        with psycopg.connect(da["url"]) as c:
            return sorted(c.execute("SELECT node, role FROM members WHERE uid = %s", (uid,)).fetchall())

    for o, k, d in ((oa, "a", da), (ob, "b", dbb)):
        s = socks[k]
        procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "main:app", "--fd", str(s.fileno())], pass_fds=(s.fileno(),),
            cwd=REPO / "observatory" / "api",
            env=propagate.env_for_child({**base, "ASTRYX_COG_REGISTRY": str(regf), "ASTRYX_HOME": str(t / o),
                                         "ASTRYX_DSN": d["url"], "OBS_KEY": KEY[k]}),
            stdout=subprocess.DEVNULL, stderr=(t / f"{k}.err").open("w")))
    s = socks["front"]
    procs.append(subprocess.Popen(
        [PY, "-m", "uvicorn", "front:app", "--fd", str(s.fileno())], pass_fds=(s.fileno(),), cwd=REPO / "observatory",
        env=propagate.env_for_child({**cogbase, "ASTRYX_COG_REGISTRY": str(regf)}),
        stdout=subprocess.DEVNULL, stderr=(t / "front.err").open("w")))
    for s in socks.values():
        s.close()
    F = port["front"]
    up = all(wait(port[k], "/api/whoami" if k != "front" else "/api/cog", procs[i])
             for i, k in enumerate(("a", "b", "front")))
    check("every server starts", up, " | ".join((t / f"{k}.err").read_text()[-400:] for k in ("a", "b", "front")))
    if not up:
        return

    SO = {"sec-fetch-site": "same-origin", "origin": ORIGIN}       # what a browser sends from the cog's own page
    ip = iter(range(1, 250))

    def login(who, pw=None):
        st, hs, _ = call(F, "/auth/login", "POST", {"email": users[who], "password": pw or PW[who]},
                         headers={"origin": ORIGIN, "x-forwarded-for": f"198.51.100.{next(ip)}"})
        return st, session_of(hs)

    S = {}
    for who in ("owner", "adm", "mem", "cross"):
        st, S[who] = login(who)
        check(f"{who} signs in", st == 200 and S[who], f"{st}")

    def as_(who):
        return {"cookie": S[who], **SO}

    def me(cookie):
        st, _, j = call(F, "/auth/me", headers={"cookie": cookie})
        return st, {o["org"]: o["role"] for o in (j.get("orgs", []) if isinstance(j, dict) else [])}

    U = {who: acct(users[who]) for who in ("owner", "adm", "mem", "cross")}

    print("\nM1 THE OWNER SEES USERS")
    st, _, j = call(F, f"/auth/admin/users?org={oa}", headers=as_("owner"))
    got = {u["email"]: u["role"] for u in j.get("users", [])} if st == 200 else {}
    check("/auth/admin/users?org=A: 200, every account with a role in A, each with its role",
          got == {users["owner"]: "owner", users["adm"]: "admin", users["mem"]: "member", users["cross"]: "member"},
          f"{st} {got if got else j}")
    check("...the caller is named owner, the roles A admits include admin, and A is tree-scoped",
          st == 200 and j.get("you") == "owner" and j.get("roles") == ["owner", "admin", "member", "viewer"]
          and j.get("tree") is True, f"{j.get('you')} {j.get('roles')} {j.get('tree')}")
    mine = next((u for u in j.get("users", []) if u.get("you")), {}) if st == 200 else {}
    check("...and its own row says you, with a live session and a last sign-in",
          mine.get("email") == users["owner"] and mine.get("live_sessions", 0) >= 1 and mine.get("last_session"),
          str(mine))
    st, _, nj = call(F, f"/o/{oa}/api/admin/nodes", headers=as_("owner"))
    nodes = {n["node"]: n["kind"] for n in nj.get("nodes", [])} if st == 200 else {}
    check("/api/admin/nodes: the org, the group and its agents from A's agents/ tree",
          nodes == {"": "org", "grp": "group", "grp/scout": "agent", "solo": "agent"}, f"{st} {nodes}")

    print("\nM2 A MEMBER GETS 403")
    probes = {
        "GET /auth/admin/users": call(F, f"/auth/admin/users?org={oa}", headers=as_("mem"))[0],
        "POST /auth/admin/invite": call(F, "/auth/admin/invite", "POST", {"org": oa, "role": "member"},
                                        headers=as_("mem"))[0],
        "POST /auth/admin/reset": call(F, "/auth/admin/reset", "POST", {"org": oa, "uid": U["adm"]}, headers=as_("mem"))[0],
        "POST /auth/admin/revoke-sessions": call(F, "/auth/admin/revoke-sessions", "POST", {"org": oa, "uid": U["adm"]},
                                                 headers=as_("mem"))[0],
        "GET /api/admin/members": call(F, f"/o/{oa}/api/admin/members", headers=as_("mem"))[0],
        "PUT /api/admin/members": call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["mem"], "role": "owner"},
                                       headers=as_("mem"))[0],
        "DELETE /api/admin/members": call(F, f"/o/{oa}/api/admin/members", "DELETE", {"uid": U["adm"]},
                                          headers=as_("mem"))[0],
        "GET /api/admin/activity": call(F, f"/o/{oa}/api/admin/activity?uid={U['mem']}", headers=as_("mem"))[0],
    }
    check("a member: 403 on every admin route, front and backend", set(probes.values()) == {403}, str(probes))
    check("...and nothing changed", rows_a(U["mem"]) == [("", "member")] and rows_a(U["adm"]) == [("", "admin")],
          f"{rows_a(U['mem'])} {rows_a(U['adm'])}")
    st0, _, _ = call(F, f"/auth/admin/users?org={oa}", headers=SO)
    st0b, _, _ = call(F, f"/o/{oa}/api/admin/members", headers=SO)
    check("signed out: the front's half is 401, the backend's 403", st0 == 401 and st0b == 403, f"{st0} {st0b}")
    stk, _, kj = call(F, f"/o/{oa}/api/admin/members", headers={"x-obs-key": KEY["a"]})
    check("the owner key opens the backend's half (you: owner)", stk == 200 and kj.get("you") == "owner", f"{stk}")
    st_b, _, _ = call(F, f"/auth/admin/users?org={ob}", headers=as_("owner"))
    check("each org decides: A's owner is only a member of B, so B's users list is 403", st_b == 403, f"{st_b}")

    print("\nM3 AN ADMIN MANAGES, BELOW OWNER")
    st, _, j = call(F, f"/auth/admin/users?org={oa}", headers=as_("adm"))
    check("an admin lists A's users (you: admin)", st == 200 and j.get("you") == "admin" and len(j.get("users", [])) == 4,
          f"{st}")
    refused = {
        "invite an owner": call(F, "/auth/admin/invite", "POST", {"org": oa, "role": "owner"}, headers=as_("adm"))[0],
        "make an owner": call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["mem"], "role": "owner"},
                              headers=as_("adm"))[0],
        "demote the owner": call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["owner"], "role": "member"},
                                 headers=as_("adm"))[0],
        "remove the owner": call(F, f"/o/{oa}/api/admin/members", "DELETE", {"uid": U["owner"]}, headers=as_("adm"))[0],
        "reset the owner": call(F, "/auth/admin/reset", "POST", {"org": oa, "uid": U["owner"]}, headers=as_("adm"))[0],
    }
    check("an admin can't invite, make, demote, remove or reset an owner: 403 each", set(refused.values()) == {403},
          str(refused))
    check("...and the owner is still the owner", rows_a(U["owner"]) == [("", "owner")], str(rows_a(U["owner"])))
    st, _, _ = call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["mem"], "role": "viewer"}, headers=as_("adm"))
    check("an admin changes a member to viewer: 200, and the row says so", st == 200 and rows_a(U["mem"]) == [("", "viewer")],
          f"{st} {rows_a(U['mem'])}")
    st, _, _ = call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["mem"], "role": "member"}, headers=as_("adm"))
    bad = {"a uid of another cog": call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": "9@fxcog-elsewhere", "role":
                                                                               "member"}, headers=as_("owner"))[0],
           "a role A doesn't have": call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["mem"], "role": "root"},
                                         headers=as_("owner"))[0],
           "a node outside the CHECK": call(F, f"/o/{oa}/api/admin/members", "PUT",
                                            {"uid": U["mem"], "role": "member", "node": "../etc"}, headers=as_("owner"))[0]}
    check("refused before any write: a uid of another cog, an unknown role, a bad node (400 each)",
          set(bad.values()) == {400}, str(bad))

    print("\nM4 INVITE → ACCEPT → SIGNED IN WITH THAT ROLE")
    st, _, inv = call(F, "/auth/admin/invite", "POST", {"org": oa, "role": "member"}, headers=as_("adm"))
    link = inv.get("link", "") if st == 200 else ""
    tok = link.partition("#/accept?t=")[2]
    check("an admin invites a member: 200 and a link on the cog's own origin, #/accept?t=…",
          st == 200 and link.startswith(ORIGIN + "/#/accept?t=") and len(tok) >= 40, f"{st} {inv}")
    with psycopg.connect(dbb["url"]) as c:
        stored = c.execute("SELECT count(*) FROM links WHERE digest = sha256(convert_to(%s, 'UTF8'))", (tok,)).fetchone()[0]
        clear = c.execute("SELECT count(*) FROM links WHERE encode(digest, 'escape') LIKE %s", (f"%{tok}%",)).fetchone()[0]
    check("...the store holds its sha256, never the token", stored == 1 and clear == 0, f"{stored} {clear}")
    st, _, li = call(F, f"/auth/link?t={tok}")
    check("/auth/link: an invite to A as member", st == 200 and li.get("kind") == "invite" and li.get("org") == oa
          and li.get("role") == "member" and li.get("name") == f"fed-{oa}", f"{st} {li}")
    st_short, _, _ = call(F, "/auth/accept", "POST", {"token": tok, "email": users["new"], "password": "short"},
                          headers={"origin": ORIGIN})
    st_far, _, _ = call(F, "/auth/accept", "POST", {"token": tok, "email": users["new"], "password": PW["new"]},
                        headers={"origin": "https://fx-elsewhere.invalid"})
    check("a short password is 400, a foreign Origin 403, and neither uses the link",
          st_short == 400 and st_far == 403 and call(F, f"/auth/link?t={tok}")[0] == 200, f"{st_short} {st_far}")
    st, hs, aj = call(F, "/auth/accept", "POST", {"token": tok, "email": users["new"], "password": PW["new"]},
                      headers={"origin": ORIGIN})
    new_s = session_of(hs)
    check("a new email accepts: 200 and a session cookie", st == 200 and new_s and aj.get("org") == oa, f"{st} {aj}")
    stm, roles = me(new_s)
    check("...signed in, /auth/me names A with the invited role (member)", stm == 200 and roles == {oa: "member"},
          f"{stm} {roles}")
    U["new"] = acct(users["new"])
    check("...and A's members row is the backend's own, written for the new account", rows_a(U["new"]) == [("", "member")],
          str(rows_a(U["new"])))
    st2, _, _ = call(F, "/auth/accept", "POST", {"token": tok, "email": users["late"], "password": PW["late"]},
                     headers={"origin": ORIGIN})
    check("the same link again: 410, and no account for the second email", st2 == 410 and acct(users["late"]) is None,
          f"{st2}")
    # a node-scoped invite
    st, _, inv = call(F, "/auth/admin/invite", "POST", {"org": oa, "role": "member", "node": "grp"}, headers=as_("owner"))
    tok_n = inv.get("link", "").partition("#/accept?t=")[2]
    st, hs, _ = call(F, "/auth/accept", "POST", {"token": tok_n, "email": users["node"], "password": PW["node"]},
                     headers={"origin": ORIGIN})
    U["node"] = acct(users["node"])
    check("a node-scoped invite (grp): the row lands on that node", st == 200 and rows_a(U["node"]) == [("grp", "member")],
          f"{st} {rows_a(U['node']) if U['node'] else None}")
    # an existing account (cross, member of A, owner of B) invited to … B already has it; invite owner@ (member of B)
    # into A as viewer on solo: it must prove its password, and its own session is untouched
    st, _, inv = call(F, "/auth/admin/invite", "POST", {"org": oa, "role": "viewer", "node": "solo"},
                      headers=as_("owner"))
    tok_e = inv.get("link", "").partition("#/accept?t=")[2]
    st_w, _, _ = call(F, "/auth/accept", "POST", {"token": tok_e, "email": users["mem"], "password": "fx-dummy-wrong-0009"},
                      headers={"origin": ORIGIN})
    check("an EXISTING email with the wrong password: 401, and the link stays open",
          st_w == 401 and call(F, f"/auth/link?t={tok_e}")[0] == 200 and rows_a(U["mem"]) == [("", "member")], f"{st_w}")
    st_r, hs, _ = call(F, "/auth/accept", "POST", {"token": tok_e, "email": users["mem"], "password": PW["mem"]},
                       headers={"origin": ORIGIN})
    check("...with its own password: 200, a second row on solo, and its old session still live",
          st_r == 200 and rows_a(U["mem"]) == [("", "member"), ("solo", "viewer")] and me(S["mem"])[0] == 200,
          f"{st_r} {rows_a(U['mem'])}")
    st, _, inv = call(F, "/auth/admin/invite", "POST", {"org": oa, "role": "viewer"}, headers=as_("owner"))
    tok_c = inv.get("link", "").partition("#/accept?t=")[2]
    _, _, lj = call(F, f"/auth/admin/users?org={oa}", headers=as_("owner"))
    open_ids = [i["id"] for i in lj.get("invites", [])]
    stc, _, cj = call(F, "/auth/admin/invite/cancel", "POST", {"org": oa, "id": open_ids[-1] if open_ids else -1},
                      headers=as_("owner"))
    check("the users list shows the open invite; cancel closes it (its link 410)",
          len(open_ids) == 1 and stc == 200 and cj.get("ok") and call(F, f"/auth/link?t={tok_c}")[0] == 410,
          f"{open_ids} {stc} {cj}")

    print("\nM5 THE LAST OWNER")
    st_d, _, dj = call(F, f"/o/{oa}/api/admin/members", "DELETE", {"uid": U["owner"]}, headers=as_("owner"))
    st_m, _, _ = call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["owner"], "role": "admin"}, headers=as_("owner"))
    check("A (tree shape): its only owner can't remove or demote itself (409 each), and stays owner",
          st_d == 409 and st_m == 409 and rows_a(U["owner"]) == [("", "owner")], f"{st_d} {st_m} {dj}")
    st_bd, _, _ = call(F, f"/o/{ob}/api/admin/members", "DELETE", {"uid": U["cross"]}, headers=as_("cross"))
    st_bm, _, _ = call(F, f"/o/{ob}/api/admin/members", "PUT", {"uid": U["cross"], "role": "member"},
                       headers=as_("cross"))
    with psycopg.connect(dbb["url"]) as c:
        b_cross = c.execute("SELECT role FROM members WHERE uid = %s", (U["cross"],)).fetchone()
    check("B (main's first shape, no trigger): the same 409s, by the module's end-state check",
          st_bd == 409 and st_bm == 409 and b_cross == ("owner",), f"{st_bd} {st_bm} {b_cross}")
    st, _, bj = call(F, f"/auth/admin/users?org={ob}", headers=as_("cross"))
    st_ba, _, _ = call(F, "/auth/admin/invite", "POST", {"org": ob, "role": "admin"}, headers=as_("cross"))
    st_bn, _, _ = call(F, "/auth/admin/invite", "POST", {"org": ob, "role": "member", "node": "grp"},
                       headers=as_("cross"))
    check("B offers only its CHECK's roles (no admin), no tree; an admin or node invite there is 400",
          st == 200 and bj.get("roles") == ["owner", "member", "viewer"] and bj.get("tree") is False
          and st_ba == 400 and st_bn == 400, f"{st} {bj.get('roles')} {bj.get('tree')} {st_ba} {st_bn}")
    st1, _, _ = call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["adm"], "role": "owner"}, headers=as_("owner"))
    st2, _, _ = call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["owner"], "role": "admin"}, headers=as_("owner"))
    check("with a second owner, the first may step down (200, 200)",
          st1 == 200 and st2 == 200 and rows_a(U["owner"]) == [("", "admin")], f"{st1} {st2}")
    st3, _, _ = call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["owner"], "role": "owner"}, headers=as_("adm"))
    st4, _, _ = call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["adm"], "role": "admin"}, headers=as_("owner"))
    check("...and the roles go back (the new owner restores, the old steps aside)", st3 == 200 and st4 == 200
          and rows_a(U["owner"]) == [("", "owner")] and rows_a(U["adm"]) == [("", "admin")], f"{st3} {st4}")

    print("\nM6 RESET LINK, ONCE")
    st, _, rj = call(F, "/auth/admin/reset", "POST", {"org": oa, "uid": U["new"]}, headers=as_("adm"))
    tok_r = rj.get("link", "").partition("#/accept?t=")[2]
    check("an admin makes a reset link for a member (200), never a password in it",
          st == 200 and tok_r and PW["new"] not in json.dumps(rj), f"{st} {rj}")
    st, _, li = call(F, f"/auth/link?t={tok_r}")
    check("/auth/link: a reset, naming the account's email", st == 200 and li.get("kind") == "reset"
          and li.get("email") == users["new"], f"{st} {li}")
    st, hs, _ = call(F, "/auth/accept", "POST", {"token": tok_r, "password": PW["reset"]}, headers={"origin": ORIGIN})
    reset_s = session_of(hs)
    check("the reset: 200, signed in with a new session", st == 200 and reset_s and me(reset_s) == (200, {oa: "member"}),
          f"{st}")
    check("...the account's old session is revoked (/auth/me 401)", me(new_s)[0] == 401, f"{me(new_s)}")
    st2, _, _ = call(F, "/auth/accept", "POST", {"token": tok_r, "password": "fx-dummy-pass-again-0010"},
                     headers={"origin": ORIGIN})
    check("the same reset link again: 410", st2 == 410, f"{st2}")
    users["new_old"] = users["new"]
    st_o, _ = (lambda: (call(F, "/auth/login", "POST", {"email": users["new"], "password": PW["new"]},
                             headers={"origin": ORIGIN, "x-forwarded-for": "198.51.100.251"})[0], None))()
    st_n, _ = (lambda: (call(F, "/auth/login", "POST", {"email": users["new"], "password": PW["reset"]},
                             headers={"origin": ORIGIN, "x-forwarded-for": "198.51.100.252"})[0], None))()
    check("the old password no longer signs in (401), the new one does (200)", st_o == 401 and st_n == 200,
          f"{st_o} {st_n}")

    print("\nM7 SIGN OUT EVERYWHERE")
    check("before: mem's session is live", me(S["mem"])[0] == 200)
    st, _, vj = call(F, "/auth/admin/revoke-sessions", "POST", {"org": oa, "uid": U["mem"]}, headers=as_("adm"))
    check("an admin signs a member out everywhere: 200, its session gone (/auth/me 401)",
          st == 200 and vj.get("revoked", 0) >= 1 and me(S["mem"])[0] == 401, f"{st} {vj}")

    print("\nM8 COG-WIDE GUARD")
    g = {"admin resets cross (owner of B)": call(F, "/auth/admin/reset", "POST", {"org": oa, "uid": U["cross"]},
                                                 headers=as_("adm"))[0],
         "A's owner resets cross (A's owner is only a member of B)": call(
             F, "/auth/admin/reset", "POST", {"org": oa, "uid": U["cross"]}, headers=as_("owner"))[0],
         "A's owner signs cross out everywhere": call(F, "/auth/admin/revoke-sessions", "POST",
                                                      {"org": oa, "uid": U["cross"]}, headers=as_("owner"))[0]}
    check("an account that also holds a role in an org the caller doesn't manage: 403 each", set(g.values()) == {403},
          str(g))
    check("...and cross is still signed in", me(S["cross"])[0] == 200)
    st_nm, _, _ = call(F, "/auth/admin/reset", "POST", {"org": ob, "uid": U["adm"]}, headers=as_("cross"))
    check("a reset for an account with no role in that org: 404", st_nm == 404, f"{st_nm}")

    print("\nM9 LINKS EXPIRE; THE INVITER IS JUDGED AT USE")
    st, _, inv = call(F, "/auth/admin/invite", "POST", {"org": oa, "role": "member"}, headers=as_("owner"))
    tok_x = inv.get("link", "").partition("#/accept?t=")[2]
    store("UPDATE links SET expires = now() - interval '1 second' WHERE digest = sha256(convert_to(%s, 'UTF8'))", tok_x)
    st_l, _, _ = call(F, f"/auth/link?t={tok_x}")
    st_a, _, _ = call(F, "/auth/accept", "POST", {"token": tok_x, "email": users["late"], "password": PW["late"]},
                      headers={"origin": ORIGIN})
    check("past its expiry: /auth/link 410, /auth/accept 410, no account made",
          st_l == 410 and st_a == 410 and acct(users["late"]) is None, f"{st_l} {st_a}")
    st, _, inv = call(F, "/auth/admin/invite", "POST", {"org": oa, "role": "member"}, headers=as_("adm"))
    tok_l = inv.get("link", "").partition("#/accept?t=")[2]
    call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["adm"], "role": "member"}, headers=as_("owner"))
    st_a, _, aj = call(F, "/auth/accept", "POST", {"token": tok_l, "email": users["late"], "password": PW["late"]},
                       headers={"origin": ORIGIN})
    check("an invite whose inviter is no longer an admin: 409 at accept, no account left, the link still open",
          st_a == 409 and acct(users["late"]) is None and call(F, f"/auth/link?t={tok_l}")[0] == 200, f"{st_a} {aj}")
    call(F, f"/o/{oa}/api/admin/members", "PUT", {"uid": U["adm"], "role": "admin"}, headers=as_("owner"))
    st_a, _, _ = call(F, "/auth/accept", "POST", {"token": tok_l, "email": users["late"], "password": PW["late"]},
                      headers={"origin": ORIGIN})
    check("...the inviter an admin again: the same link now works (200)", st_a == 200 and acct(users["late"]) is not None,
          f"{st_a}")

    print("\nM10 ACTIVITY")
    st, _, aj = call(F, f"/o/{oa}/api/admin/activity?uid={U['mem']}", headers=as_("owner"))
    check("activity: 200, counts only, and with no attribution on the wire it says so (attributed false, null counts)",
          st == 200 and aj.get("attributed") is False and aj.get("messages") is None and "body" not in json.dumps(aj),
          f"{st} {aj}")


if __name__ == "__main__":
    sys.exit(main())
