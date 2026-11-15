#!/usr/bin/env python3
"""cog-rebuild Phase 3 end to end: PUBLIC SIGN-UP files a PENDING org request, a cog admin decides it, and an org with
no budget spawns nothing (owner 11-13: "everyone can sign up to a cog, and sign-up creates that user's OWN org";
DESIGN.md's GATE: it stays off until the per-org sandbox exists).

The REAL fronts (uvicorn front:app) before one REAL org observatory (uvicorn main:app on its own fixture database and
HOME), on loopback sockets the children inherit (nothing binds 8090). The cog (key, store schema, accounts, the cog
admin grant) is made by the REAL host CLI (src/astryx/cogauth.py); the store is its own fixture database. Four fronts
share one cog key: OFF (no flag), ON (the flag, the real provision_org stub), REC (the flag, provision_org replaced by
a recorder: the seam's ARGUMENTS) and CAP (the flag, its own store, a daily cap of 2). Dummy passwords only; every
assertion is on a status, a name or a row count, never a printed secret.

  U1 THE GATE: with no ASTRYX_COG_SIGNUP, GET and POST /auth/signup are 404 and /api/cog says signup false; the
     sign-in screen offers "Create your org" only under /api/cog's signup (source arm), and a store row is never made
  U2 SIGN-UP: flag on, a new email + org → 200, one astryx_session cookie, ONE account and ONE pending org_requests row;
     a foreign Origin is 403, a short password / bad key / no name is 400 (no row)
  U3 UNIQUE: a key in the registry is 409; a key another request holds is 409 and its would-be account is NOT left
     behind (one transaction); the same account can't hold two pending asks (409); an existing email with the wrong
     password is login's 401 (no row)
  U4 RATE: past ASTRYX_COG_SIGNUP_PER_IP validated tries from one client → 429 and nothing written; another client
     still signs up; the cog-wide daily cap (counted in the table) → 429 at the cap
  U5 PENDING: the new account's /auth/me lists no org, its request pending, cog_admin false; the org's owner-only route
     is 403 for it and whoami is not the owner
  U6 COG ADMIN ONLY: signed out 401; the pending account 403; an org's OWNER without the cog grant 403 (an org role is
     not a cog role), on list, approve and reject; `cogauth cog-admin` of an unknown email is rc 1
  U7 APPROVE: the cog admin lists the queue; a non-positive or non-integer budget is 400; approve → state approved, the
     budget and decided_by on the row, provision 'deferred' naming provision_org(<key>, <uid>@<cog>) (the stub);
     again → 409; an unknown id → 404. Through REC: the recorder got exactly (key, owner uid), provision 'done'
  U8 REJECT: → rejected with the note, the account's /auth/me shows it, and the key is free for a new sign-up
  U9 THE EMAIL CODE (owner 11-15: "an email otp so people don't sign themselves up with wrong emails"), on MAIL (the
     flag and a mailbox: MAIL_SMTP on a loopback SMTP sink) and DOWN (a mailbox nothing listens on): a new email → 202
     {code: sent}, NO account or request, one mail to it holding six digits, and the store keeps no code (a digest);
     again at once → 202 and no second mail; a wrong code → 400 {field: code}, nothing written; the right one → 200,
     the account and its pending request, and the code is used up; five wrong guesses and the right code no longer
     opens it; an EXISTING account proves its password and gets no mail; mail that can't be sent → 503 and no code
     left standing; ON (no mailbox) asks for no code (U2 made accounts with one submit), and a `code` sent to it
     still counts against the per-client cap; an email that is not one bare address is 400 and mails nothing
  G  THE SPAWN BUDGET GATE (runtime_env.py --gate, and spawn.sh's real path with stubbed psql/tmux/pgrep/node):
     a non-primary org with no budget → rc 4 / spawn rc 1 and NOTHING written (no psql, no homes/<agent>); a budget
     but only the host's ambient login → refused; a budget and its own login → passes (spawn reaches its first psql);
     the approved request's budget counts; a PENDING one doesn't; the primary and a one-org host pass with none
Seams: OBS_FRONT_SRC (a mutant front.py), RUNTIME_ENV_SRC (a mutant runtime_env.py, the G arms).
Exit 0 · 1 · 77 (no database, uvicorn or httpx).
"""
import atexit
import json
import os
import re
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
gate('test_signup', REPO, deps=('psycopg', 'asyncpg', 'fastapi', 'httpx', 'uvicorn', 'cryptography'), env=False)
from astryx.security.sqlguard import propagate  # noqa: E402
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402
from tests._smtp_sink import SmtpSink, dead_port  # noqa: E402

PY = sys.executable
fails = []
ORIGIN = "http://fx-signup.invalid"
PW = {"boss": "fx-dummy-pass-boss-0001", "own": "fx-dummy-pass-own-00002", "new": "fx-dummy-pass-new-00003",
      "two": "fx-dummy-pass-two-00004", "three": "fx-dummy-pass-three-005", "four": "fx-dummy-pass-four-0006",
      "five": "fx-dummy-pass-five-0007", "c1": "fx-dummy-pass-capone-08", "c2": "fx-dummy-pass-captwo-09",
      "c3": "fx-dummy-pass-capthr-10", "x": "fx-dummy-pass-other-011"}
KEY = {"a": "fx-dummy-obskey-a-0001"}
SO = {"sec-fetch-site": "same-origin"}

RECORDER = r"""
import json, os, sys, types
m = types.ModuleType('astryx.cog_provision')
class ProvisionUnavailable(NotImplementedError):
    pass
def provision_org(key, owner_uid, budget_tokens):
    with open(os.environ['FX_PROVISION_LOG'], 'a') as f:
        f.write(json.dumps([key, owner_uid, budget_tokens]) + '\n')
    return {'state': 'done', 'org': key}
m.ProvisionUnavailable, m.provision_org = ProvisionUnavailable, provision_org
sys.path.insert(0, sys.argv[1]); del sys.argv[1]
import astryx; sys.modules['astryx.cog_provision'] = m; astryx.cog_provision = m
import uvicorn; sys.exit(uvicorn.main())
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
    """(status, headers as a list of pairs, body text)."""
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    h = {"content-type": "application/json"} if isinstance(body, dict) else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=data, headers={**h, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.items(), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.items(), e.read().decode()


def jl(body):
    try:
        return json.loads(body)
    except ValueError:
        return {}


def session_of(hs):
    c = [v for k, v in hs if k.lower() == "set-cookie" and v.startswith("astryx_session=")]
    return c[0].split(";")[0] if len(c) == 1 else ""


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
    t = Path(tempfile.mkdtemp(prefix="astryx-signup-")).resolve()
    atexit.register(shutil.rmtree, t, True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    procs = []
    atexit.register(lambda: [p.kill() for p in procs if p.poll() is None])
    cog_sql = (REPO / "src" / "astryx" / "sql" / "cog_schema.sql").read_text()
    with fixture_db() as da, fixture_db(extra=(cog_sql,)) as ds, fixture_db(extra=(cog_sql,)) as dc:
        run(t, da, ds, dc, procs)
        for p in procs:
            if p.poll() is None:
                p.terminate()
        gate_arms(t, ds)
    print(f"\n{'ALL PASS' if not fails else f'FAILED ({len(fails)})'}: a sign-up is a pending request, a cog admin "
          "decides it, and no budget means no residents")
    return 1 if fails else 0


def run(t, da, ds, dc, procs):
    import psycopg
    pid = os.getpid()
    oa = f"fxsu-a-{pid}"
    cid = f"fxsucog-{pid:08d}"
    names = ("a", "off", "on", "rec", "cap", "mail", "down")
    sink, dead = SmtpSink(), dead_port()
    socks = {k: listener() for k in names}
    port = {k: s.getsockname()[1] for k, s in socks.items()}
    ha = t / oa
    ha.mkdir()
    (ha / ".env").write_text(f"ASTRYX_ORG=fed-{oa}\nASTRYX_DSN={da['url']}\nOBS_KEY={KEY['a']}\n")
    reg = {"orgs": {oa: {"home": str(ha), "db": f"fxsudb_a_{pid}", "primary": True, "door": True,
                         "ports": {"astryx-observatory-org": port["a"]}}}}
    home = t / "cog"
    home.mkdir()
    (home / ".env").write_text(f"ASTRYX_DSN={ds['url']}\nASTRYX_COG_ORIGINS={ORIGIN}\n")
    regf = t / "cog.json"
    regf.write_text(json.dumps(reg))
    base = {k: os.environ[k] for k in ("PATH", "HOME", "ASTRYX_FIXTURE_ADMIN_DSN") if k in os.environ}
    cogbase = {**base, "ASTRYX_SQLGUARD_ROOT": str(REPO)}

    def cog(*args, stdin=None):
        return subprocess.run([PY, str(REPO / "src" / "astryx" / "cogauth.py"), *args], input=stdin, capture_output=True,
                              text=True, timeout=120,
                              env=propagate.env_for_child({**cogbase, "ASTRYX_COG_REGISTRY": str(regf)}))
    r = cog("init", "--home", str(home), "--id", cid)
    check("cogauth init (rc 0)", r.returncode == 0, r.stderr[-300:])
    reg["cog"] = {"id": cid, "home": str(home)}
    regf.write_text(json.dumps(reg))
    users = {"boss": "boss@fx-signup.invalid", "own": "own@fx-signup.invalid"}
    for who, email in users.items():
        r = cog("user", "add", email, stdin=PW[who] + "\n")
        check(f"cogauth user add ({who}) (rc 0)", r.returncode == 0, r.stderr[-300:])
    r = cog("grant", oa, users["boss"], "owner")
    check("cogauth grant A boss owner (rc 0)", r.returncode == 0, r.stderr[-300:])
    r = cog("grant", oa, users["own"], "owner")
    check("cogauth grant A own owner (rc 0): an org OWNER who is no cog admin", r.returncode == 0, r.stderr[-300:])
    r = cog("cog-admin", users["boss"])
    check("cogauth cog-admin boss (rc 0)", r.returncode == 0, r.stderr[-300:])
    r = cog("cog-admin", "nobody@fx-signup.invalid")
    check("cogauth cog-admin of an unknown email: rc 1, named", r.returncode == 1 and "no such account" in r.stderr,
          f"{r.returncode} {r.stderr[-200:]}")
    r2 = cog("cog-admin", users["boss"])
    check("cogauth cog-admin again: idempotent (rc 0)", r2.returncode == 0, r2.stderr[-200:])

    # the fronts' cog homes: one key (copied), each its own .env
    def cog_home(name, dsn, extra):
        h = t / f"cog-{name}"
        shutil.copytree(home / "keys", h / "keys")
        shutil.copy2(home / "identity.key", h / "identity.key")
        (h / ".env").write_text(f"ASTRYX_DSN={dsn}\nASTRYX_COG_ORIGINS={ORIGIN}\n{extra}")
        f = t / f"reg-{name}.json"
        f.write_text(json.dumps({**reg, "cog": {"id": cid, "home": str(h)}}))
        return f
    regs = {"off": regf,
            "on": cog_home("on", ds["url"], "ASTRYX_COG_SIGNUP=1\nASTRYX_COG_SIGNUP_PER_IP=5\nASTRYX_COG_SIGNUP_DAILY=50\n"),
            "rec": cog_home("rec", ds["url"], "ASTRYX_COG_SIGNUP=on\n"),
            "cap": cog_home("cap", dc["url"], "ASTRYX_COG_SIGNUP=1\nASTRYX_COG_SIGNUP_DAILY=2\n"),
            "mail": cog_home("mail", ds["url"], "ASTRYX_COG_SIGNUP=1\nASTRYX_COG_SIGNUP_PER_IP=50\nASTRYX_COG_SIGNUP_DAILY=500\n"
                             f"MAIL_FROM=codes@fx-signup.invalid\nMAIL_SMTP=127.0.0.1:{sink.port}\n"),
            "down": cog_home("down", ds["url"], "ASTRYX_COG_SIGNUP=1\nASTRYX_COG_SIGNUP_PER_IP=50\n"
                             f"MAIL_FROM=codes@fx-signup.invalid\nMAIL_SMTP=127.0.0.1:{dead}\n")}

    s = socks["a"]
    procs.append(subprocess.Popen(
        [PY, "-m", "uvicorn", "main:app", "--fd", str(s.fileno())], pass_fds=(s.fileno(),), cwd=REPO / "observatory" / "api",
        env=propagate.env_for_child({**base, "ASTRYX_COG_REGISTRY": str(regf), "ASTRYX_HOME": str(ha),
                                     "ASTRYX_DSN": da["url"], "OBS_KEY": KEY["a"]}),
        stdout=subprocess.DEVNULL, stderr=(t / "a.err").open("w")))
    front_src = os.environ.get("OBS_FRONT_SRC")
    fdir = REPO / "observatory"
    if front_src:
        fdir = t / "observatory"
        fdir.mkdir()
        (fdir / "front.py").write_text(Path(front_src).read_text().replace(
            'ROOT = Path(__file__).resolve().parent', f'ROOT = Path({str(REPO / "observatory")!r})'))
    (t / "recorder.py").write_text(RECORDER)
    plog = t / "provision.log"
    for k in ("off", "on", "rec", "cap", "mail", "down"):
        s = socks[k]
        launch = [PY, "-m", "uvicorn"] if k != "rec" else [PY, str(t / "recorder.py"), str(REPO / "src")]
        procs.append(subprocess.Popen(
            [*launch, "front:app", "--fd", str(s.fileno())], pass_fds=(s.fileno(),), cwd=fdir,
            env=propagate.env_for_child({**cogbase, "ASTRYX_COG_REGISTRY": str(regs[k]), "FX_PROVISION_LOG": str(plog)}),
            stdout=subprocess.DEVNULL, stderr=(t / f"{k}.err").open("w")))
    for s in socks.values():
        s.close()
    up = all(wait(port[k], "/api/whoami" if k == "a" else "/api/cog", procs[i]) for i, k in enumerate(names))
    check("every server starts", up, " | ".join((t / f"{k}.err").read_text()[-300:] for k in names
                                                 if (t / f"{k}.err").exists()))
    if not up:
        return
    OFF, ON, REC, CAP, MAIL, DOWN = port["off"], port["on"], port["rec"], port["cap"], port["mail"], port["down"]
    O = {"origin": ORIGIN}

    def signup(p, email, pw, key, name="Fixture Org", ip="198.51.100.1", headers=None, code=None):
        return call(p, "/auth/signup", "POST", {"email": email, "password": pw, "org_name": name, "org_key": key,
                                                **({"code": code} if code is not None else {})},
                    headers={**O, "x-forwarded-for": ip, **(headers or {})})

    def login(p, email, pw, ip="198.51.100.200"):
        st, hs, _ = call(p, "/auth/login", "POST", {"email": email, "password": pw},
                         headers={**O, "x-forwarded-for": ip})
        return session_of(hs) if st == 200 else ""

    def q(dsn, sql, *args):
        with psycopg.connect(dsn) as c:
            return c.execute(sql, args).fetchall()

    def n_users(dsn=ds["url"]):
        return q(dsn, "SELECT count(*) FROM users")[0][0]

    def n_reqs(dsn=ds["url"]):
        return q(dsn, "SELECT count(*) FROM org_requests")[0][0]

    print("\nU1 THE GATE (flag off)")
    st_g, _, _ = call(OFF, "/auth/signup")
    before = (n_users(), n_reqs())
    st_p, hs_p, _ = signup(OFF, "gated@fx-signup.invalid", PW["x"], "fx-gated")
    check("flag off: GET /auth/signup and POST /auth/signup are 404, no cookie", st_g == 404 and st_p == 404
          and not session_of(hs_p), f"{st_g} {st_p}")
    check("...and nothing written", (n_users(), n_reqs()) == before, f"{before} → {(n_users(), n_reqs())}")
    c_off, c_on = jl(call(OFF, "/api/cog")[2]), jl(call(ON, "/api/cog")[2])
    check("/api/cog says signup false with the flag off, true with it on",
          c_off.get("signup") is False and c_on.get("signup") is True, f"{c_off.get('signup')} {c_on.get('signup')}")
    st_gi, _, gi = call(ON, "/auth/signup")
    check("flag on: GET /auth/signup is 200 {open: true}", st_gi == 200 and jl(gi).get("open") is True, f"{st_gi}")
    screens = (REPO / "observatory/web/src/components/AuthScreens.tsx").read_text()
    sign_in = screens[screens.find("export function SignInScreen"):screens.find("function Sky(")]
    check("the sign-in screen offers 'Create your org' only under /api/cog's signup (rooms.signup)",
          "Create your org" in sign_in and re.search(r"rooms\?\.signup\s*&&|canSignUp\s*&&", sign_in) is not None
          and "signup: j.signup === true" in screens, "no gated Create your org")

    print("\nU2 SIGN-UP")
    st_f, _, _ = signup(ON, "far@fx-signup.invalid", PW["x"], "fx-far", headers={"origin": "https://fx-else.invalid"})
    bads = [signup(ON, "short@fx-signup.invalid", "short-pw", "fx-short")[0],
            signup(ON, "badkey@fx-signup.invalid", PW["x"], "Bad_Key!")[0],
            signup(ON, "noname@fx-signup.invalid", PW["x"], "fx-noname", name="   ")[0],
            signup(ON, "not-an-email", PW["x"], "fx-noemail")[0]]
    check("a foreign Origin is 403; a short password, a bad key, no name, no email are 400; nothing written",
          st_f == 403 and bads == [400] * 4 and (n_users(), n_reqs()) == before, f"{st_f} {bads}")
    k1 = f"fx-req1-{pid}"
    st1, hs1, b1 = signup(ON, "New@FX-Signup.invalid", PW["new"], k1, name="  New   Org ")
    new = session_of(hs1)
    rows = q(ds["url"], "SELECT u.email, r.key, r.name, r.state, r.budget_tokens FROM org_requests r JOIN users u "
                        "ON u.id = r.uid WHERE r.key = %s", k1)
    check("a new email + org: 200, one session cookie, and the request is pending in the body",
          st1 == 200 and bool(new) and jl(b1).get("request", {}).get("state") == "pending", f"{st1} {b1[:120]}")
    check("ONE account (email lowercased) and ONE pending request (name tidied, no budget)",
          rows == [("new@fx-signup.invalid", k1, "New Org", "pending", None)] and n_users() == before[0] + 1, rows)

    print("\nU3 UNIQUE")
    st_r, _, _ = signup(ON, "regkey@fx-signup.invalid", PW["x"], oa)
    check("a key the registry holds: 409", st_r == 409, f"{st_r}")
    nu = n_users()
    st_d, _, bd = signup(ON, "two@fx-signup.invalid", PW["two"], k1)
    check("a key another request holds: 409 naming the key, and its would-be account is NOT left behind",
          st_d == 409 and jl(bd).get("field") == "org_key" and n_users() == nu
          and not q(ds["url"], "SELECT 1 FROM users WHERE email = 'two@fx-signup.invalid'"), f"{st_d} {bd[:100]}")
    st_2, _, b2 = signup(ON, "new@fx-signup.invalid", PW["new"], f"fx-req1b-{pid}")
    check("the same account, a second pending ask: 409", st_2 == 409 and "waiting" in b2, f"{st_2} {b2[:100]}")
    st_w, _, bw = signup(ON, "new@fx-signup.invalid", "fx-dummy-wrong-0099", f"fx-req1c-{pid}")
    st_lw, _, blw = call(ON, "/auth/login", "POST", {"email": "new@fx-signup.invalid", "password": "fx-dummy-wrong-0099"},
                         headers={**O, "x-forwarded-for": "198.51.100.9"})
    check("an existing email with the wrong password: login's own 401 bytes, no row",
          st_w == 401 and (st_lw, blw) == (401, bw) and n_reqs() == 1, f"{st_w} {st_lw}")

    print("\nU4 RATE")
    k3 = f"fx-req3-{pid}"
    st3, hs3, _ = signup(ON, "three@fx-signup.invalid", PW["three"], k3)      # the 5th validated try from this client
    three = session_of(hs3)
    nb = (n_users(), n_reqs())
    st4, _, _ = signup(ON, "four@fx-signup.invalid", PW["four"], f"fx-req4-{pid}")
    check("5 validated tries from one client (PER_IP 5): the 5th lands, the 6th is 429 and writes nothing",
          st3 == 200 and st4 == 429 and (n_users(), n_reqs()) == nb, f"{st3} {st4}")
    st4b, _, _ = signup(ON, "four@fx-signup.invalid", PW["four"], f"fx-req4-{pid}", ip="198.51.100.2")
    check("...another client still signs up", st4b == 200, f"{st4b}")
    caps = [signup(CAP, f"c{i}@fx-signup.invalid", PW[f"c{i}"], f"fx-cap{i}-{pid}", ip=f"198.51.100.{60 + i}")[0]
            for i in (1, 2, 3)]
    check("the cog-wide daily cap (2, counted in the table): 200, 200, then 429 from a fresh client, nothing written",
          caps == [200, 200, 429] and n_reqs(dc["url"]) == 2, f"{caps} {n_reqs(dc['url'])}")

    print("\nU5 PENDING")
    st_m, _, mb = call(ON, "/auth/me", headers={"cookie": new})
    me = jl(mb)
    check("/auth/me: no org, the request pending, not a cog admin",
          st_m == 200 and me.get("orgs") == [] and [(x.get("key"), x.get("state")) for x in me.get("requests", [])]
          == [(k1, "pending")] and me.get("cog_admin") is False, f"{st_m} {mb[:200]}")
    st_pr, _, _ = call(ON, f"/o/{oa}/api/presence", headers={"cookie": new, **SO})
    _, _, wh = call(ON, f"/o/{oa}/api/whoami", headers={"cookie": new, **SO})
    check("the org's owner-only route is 403 for it, and whoami is not the owner",
          st_pr == 403 and jl(wh).get("owner") is False, f"{st_pr} {wh[:80]}")

    print("\nU6 COG ADMIN ONLY")
    own = login(ON, users["own"], PW["own"])
    rid1 = q(ds["url"], "SELECT id FROM org_requests WHERE key = %s", k1)[0][0]
    rid3 = q(ds["url"], "SELECT id FROM org_requests WHERE key = %s", k3)[0][0]
    for label, h, want in (("signed out", {}, 401), ("the pending account", {"cookie": new, **SO}, 403),
                           ("an org OWNER without the cog grant", {"cookie": own, **SO}, 403)):
        got = [call(ON, "/auth/cog/requests", headers=h)[0],
               call(ON, f"/auth/cog/requests/{rid1}/approve", "POST", {"budget_tokens": 1000}, headers={**O, **h})[0],
               call(ON, f"/auth/cog/requests/{rid1}/reject", "POST", {"note": "x"}, headers={**O, **h})[0]]
        check(f"{label}: list, approve, reject are each {want}", got == [want] * 3 and bool(own), got)
    check("...and the request is still pending", q(ds["url"], "SELECT state FROM org_requests WHERE id = %s", rid1)
          == [("pending",)])

    print("\nU7 APPROVE")
    boss = login(ON, users["boss"], PW["boss"])
    B = {"cookie": boss, **SO}
    st_me, _, bm = call(ON, "/auth/me", headers=B)
    check("the cog admin: /auth/me says cog_admin true", jl(bm).get("cog_admin") is True, f"{st_me} {bm[:120]}")
    st_l, _, bl = call(ON, "/auth/cog/requests?state=pending", headers=B)
    listed = sorted(x.get("key") for x in jl(bl).get("requests", []))
    check("the queue lists the pending requests with their emails",
          st_l == 200 and k1 in listed and k3 in listed and any(x.get("email") == "new@fx-signup.invalid"
                                                                 for x in jl(bl).get("requests", [])), f"{st_l} {listed}")
    badb = [call(ON, f"/auth/cog/requests/{rid1}/approve", "POST", {"budget_tokens": b}, headers={**O, **B})[0]
            for b in (0, -5, "1000", 1.5, True, None)]
    check("a budget that is not a positive integer: 400 each", badb == [400] * 6, badb)
    st_a, _, ba = call(ON, f"/auth/cog/requests/{rid1}/approve", "POST", {"budget_tokens": 500000}, headers={**O, **B})
    new_uid = q(ds["url"], "SELECT id FROM users WHERE email = 'new@fx-signup.invalid'")[0][0]
    boss_uid = q(ds["url"], "SELECT id FROM users WHERE email = %s", users["boss"])[0][0]
    row = q(ds["url"], "SELECT state, budget_tokens, decided_by, decided_at IS NOT NULL, provision, provision_note "
                       "FROM org_requests WHERE id = %s", rid1)[0]
    call_txt = f"provision_org({k1}, {new_uid}@{cid}, 500000)"
    check("approve: 200, state approved, budget and decided_by on the row",
          st_a == 200 and jl(ba).get("state") == "approved" and row[:4] == ("approved", 500000, boss_uid, True),
          f"{st_a} {ba[:160]} {row[:4]}")
    check("...provision_org was called with (key, owner uid, budget) and, a stub until feat/cog-rls2, is 'deferred'",
          row[4] == "deferred" and row[5].startswith(call_txt) and "feat/cog-rls2" in row[5]
          and jl(ba).get("provision") == "deferred", f"{row[4:]}")
    st_aa, _, _ = call(ON, f"/auth/cog/requests/{rid1}/approve", "POST", {"budget_tokens": 9}, headers={**O, **B})
    st_nx, _, _ = call(ON, "/auth/cog/requests/987654321/approve", "POST", {"budget_tokens": 9}, headers={**O, **B})
    check("approving it again: 409 (budget unchanged); an unknown id: 404",
          st_aa == 409 and st_nx == 404 and q(ds["url"], "SELECT budget_tokens FROM org_requests WHERE id = %s", rid1)
          == [(500000,)], f"{st_aa} {st_nx}")
    st_mn, _, mn = call(ON, "/auth/me", headers={"cookie": new})
    check("the account's /auth/me now shows its request approved (still no org until it is provisioned)",
          [(x.get("key"), x.get("state")) for x in jl(mn).get("requests", [])] == [(k1, "approved")]
          and jl(mn).get("orgs") == [], mn[:200])

    print("\nU8 REJECT")
    st_rj, _, brj = call(ON, f"/auth/cog/requests/{rid3}/reject", "POST", {"note": "not this week"}, headers={**O, **B})
    check("reject: 200, the row rejected with its note", st_rj == 200 and q(
        ds["url"], "SELECT state, note, decided_by FROM org_requests WHERE id = %s", rid3) == [("rejected", "not this week",
                                                                                              boss_uid)], f"{st_rj} {brj}")
    _, _, m3 = call(ON, "/auth/me", headers={"cookie": three})
    check("the account's /auth/me shows it rejected, with the note",
          [(x.get("state"), x.get("note")) for x in jl(m3).get("requests", [])] == [("rejected", "not this week")], m3[:200])
    st5, _, _ = signup(REC, "five@fx-signup.invalid", PW["five"], k3, ip="198.51.100.80")
    check("the rejected key is free again: a new sign-up takes it (200)", st5 == 200, f"{st5}")
    rid5 = q(ds["url"], "SELECT id FROM org_requests WHERE key = %s AND state = 'pending'", k3)[0][0]
    uid5 = q(ds["url"], "SELECT id FROM users WHERE email = 'five@fx-signup.invalid'")[0][0]
    boss_r = login(REC, users["boss"], PW["boss"], ip="198.51.100.201")
    st_ra, _, bra = call(REC, f"/auth/cog/requests/{rid5}/approve", "POST", {"budget_tokens": 1234},
                         headers={**O, "cookie": boss_r, **SO})
    calls = [json.loads(x) for x in plog.read_text().splitlines()] if plog.exists() else []
    check("through the recorder: provision_org got exactly (key, '<uid>@<cog id>', budget), once, and the row says 'done'",
          st_ra == 200 and calls == [[k3, f"{uid5}@{cid}", 1234]] and q(
              ds["url"], "SELECT provision FROM org_requests WHERE id = %s", rid5) == [("done",)], f"{st_ra} {calls}")

    print("\nU9 THE EMAIL CODE")
    code_of = lambda text: (re.findall(r"\b(\d{6})\b", text) or [""])[0]
    has = lambda email: q(ds["url"], "SELECT count(*) FROM users WHERE email = %s", email)[0][0]
    nr = n_reqs()
    e1, k9 = "mailed@fx-signup.invalid", f"fx-mail-{pid}"
    st, _, b = signup(MAIL, e1, PW["x"], k9, ip="198.51.100.90")
    mails = [m for m in sink.mails if m[0] == [e1]]
    got = code_of(mails[0][1]) if mails else ""
    stored = q(ds["url"], "SELECT encode(digest, 'hex'), tries FROM email_codes WHERE email = %s", e1)
    check("a new email: 202 {code: sent}, NO account and no request", st == 202 and jl(b).get("code") == "sent"
          and not has(e1) and n_reqs() == nr, f"{st} {b[:120]}")
    check("...one mail, to that address only, from the cog's MAIL_FROM, holding six digits",
          len(mails) == 1 and len(got) == 6 and "From: codes@fx-signup.invalid" in mails[0][1], [m[0] for m in sink.mails])
    check("...and the store keeps a digest, never the code", len(stored) == 1 and got not in stored[0][0]
          and stored[0][1] == 0, stored)
    st, _, _ = signup(MAIL, e1, PW["x"], k9, ip="198.51.100.90")
    check("again at once: 202, and NO second mail (one a minute; the first code stands)",
          st == 202 and len([m for m in sink.mails if m[0] == [e1]]) == 1, f"{st} {len(sink.mails)}")
    wrong = "000000" if got != "000000" else "111111"
    st, _, b = signup(MAIL, e1, PW["x"], k9, ip="198.51.100.90", code=wrong)
    check("a wrong code: 400 {field: code}, nothing written", st == 400 and jl(b).get("field") == "code"
          and not has(e1) and n_reqs() == nr, f"{st} {b[:120]}")
    st, hs, b = signup(MAIL, e1, PW["x"], k9, ip="198.51.100.90", code=got)
    check("the right code: 200, a session, the account and its pending request", st == 200 and bool(session_of(hs))
          and has(e1) == 1 and q(ds["url"], "SELECT state FROM org_requests WHERE key = %s", k9) == [("pending",)],
          f"{st} {b[:120]}")
    check("...and the code is used up", not q(ds["url"], "SELECT 1 FROM email_codes WHERE email = %s", e1))
    e2, k10 = "guesser@fx-signup.invalid", f"fx-guess-{pid}"
    signup(MAIL, e2, PW["x"], k10, ip="198.51.100.91")
    real = code_of(next((m[1] for m in sink.mails if m[0] == [e2]), ""))
    for g in range(5):
        signup(MAIL, e2, PW["x"], k10, ip=f"198.51.100.{100 + g}", code=f"{(int(real or 0) + 1 + g) % 10**6:06d}")
    st, _, _ = signup(MAIL, e2, PW["x"], k10, ip="198.51.100.110", code=real)
    check("five wrong guesses, then the right code: refused (400 or the account's 429), and no account",
          len(real) == 6 and st in (400, 429) and not has(e2), f"{st} {real!r}")
    nm = len(sink.mails)
    bad = [signup(MAIL, e, PW["x"], f"fx-comma-{pid}", ip="198.51.100.94")[0]
           for e in ("x@fx-a.invalid,y@fx-b.invalid", "x@fx-a.invalid;y@fx-b.invalid", "X <x@fx-a.invalid>",
                     '"x,y"@fx-a.invalid')]
    check("an email that is not ONE bare address (a list, a display name, a quoted local part): 400, and NO mail "
          "(medic 12207: a comma mailed one code to two addresses)", bad == [400] * 4 and len(sink.mails) == nm,
          f"{bad} {len(sink.mails) - nm} mails")
    check("...the store counted the five tries", q(ds["url"], "SELECT tries FROM email_codes WHERE email = %s", e2)
          == [(5,)], q(ds["url"], "SELECT tries FROM email_codes WHERE email = %s", e2))
    before_mails = len(sink.mails)
    st, _, _ = signup(MAIL, users["own"], PW["own"], f"fx-own-{pid}", ip="198.51.100.92")
    check("an EXISTING account proves its password: 200 with no code and no mail",
          st == 200 and len(sink.mails) == before_mails, f"{st}")
    e3 = "down@fx-signup.invalid"
    st, _, b = signup(DOWN, e3, PW["x"], f"fx-down-{pid}", ip="198.51.100.93")
    check("mail that can't be sent: 503, no account, and no code left standing (a retry mails at once)",
          st == 503 and not has(e3) and not q(ds["url"], "SELECT 1 FROM email_codes WHERE email = %s", e3), f"{st} {b}")
    sink.sock.close()
    sts = [signup(ON, f"capped{i}@fx-signup.invalid", PW["x"], k1, ip="198.51.100.150", code="x")[0] for i in range(6)]
    check("a code sent to a cog with no mailbox changes nothing: those tries still count, the 6th is 429 (PER_IP 5)",
          sts == [409] * 5 + [429], sts)


# ---------------------------------------------------------------- G: the spawn budget gate
STUB = "#!/bin/sh\necho \"$(basename \"$0\") $*\" >> \"$FX_STUB_LOG\"\nexit {rc}\n"


def gate_arms(t, ds):
    import psycopg
    pid = os.getpid()
    venv = REPO / "venv" / "bin" / "python"
    if not venv.exists():
        check("G: this checkout has venv/ (spawn.sh runs $ROOT/venv/bin/python)", False, "no venv")
        return
    rt_src = os.environ.get("RUNTIME_ENV_SRC")
    rt = Path(rt_src) if rt_src else REPO / "src" / "astryx" / "core" / "runtime_env.py"
    g = t / "gate"
    g.mkdir()
    # one APPROVED request (U7's key) and one PENDING one in the store: an org named after each
    with psycopg.connect(ds["url"]) as c:
        approved = c.execute("SELECT key FROM org_requests WHERE state = 'approved' AND provision = 'deferred'").fetchone()
        pending = c.execute("SELECT key FROM org_requests WHERE state = 'pending' LIMIT 1").fetchone()
    homes, reg = {}, {"orgs": {}}
    orgs_ = {"p": f"fxgp-{pid}", "s": f"fxgs-{pid}", "ap": approved[0] if approved else "fx-none",
             "pe": pending[0] if pending else "fx-none2"}
    for k, o in orgs_.items():
        h = g / f"home-{k}"
        (h / "agents").mkdir(parents=True)
        (h / ".astryx").write_text("astryx home\n")
        (h / "local.md").write_text(f"# the law of fixture org {k}\n")
        (h / "agents" / "fxagent.md").write_text("# fxagent\nA fixture charter.\n")
        (h / ".env").write_text(f"ASTRYX_ORG=fed-{o}\n")
        homes[k] = h
        reg["orgs"][o] = {"home": str(h), "db": f"fxgdb_{k}_{pid}", "primary": k == "p"}
    cogh = g / "cog"
    cogh.mkdir()
    (cogh / ".env").write_text(f"ASTRYX_DSN={ds['url']}\n")
    regf = g / "reg.json"
    regf.write_text(json.dumps({**reg, "cog": {"id": f"fxgcog-{pid:08d}", "home": str(cogh)}}))
    base = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "USER", "LOGNAME") if k in os.environ}

    def gate(k, env_lines="", registry=regf):
        (homes[k] / ".env").write_text(f"ASTRYX_ORG=fed-{orgs_[k]}\n{env_lines}")
        r = subprocess.run([str(venv), str(rt), "--gate", "fxagent"], capture_output=True, text=True, timeout=60,
                           env={**base, "ASTRYX_COG_REGISTRY": str(registry), "ASTRYX_HOME": str(homes[k])})
        return r.returncode, r.stdout + r.stderr

    LOGIN = "CLAUDE_CODE_OAUTH_TOKEN=fx-dummy-oauth-0001\n"
    print("\nG THE SPAWN BUDGET GATE (runtime_env.py --gate)")
    rc, out = gate("s")
    check("a non-primary org, no budget: rc 4, named", rc == 4 and "no token budget" in out, f"{rc} {out[-200:]}")
    rc, out = gate("s", "ASTRYX_ORG_BUDGET_TOKENS=0\n" + LOGIN)
    check("a budget of 0 is no budget: rc 4", rc == 4, f"{rc} {out[-200:]}")
    rc, out = gate("s", "ASTRYX_ORG_BUDGET_TOKENS=100000\n")
    check("a budget but only the host's ambient login (the owner's): rc 4, named", rc == 4 and "ambient" in out,
          f"{rc} {out[-200:]}")
    rc, out = gate("s", "ASTRYX_ORG_BUDGET_TOKENS=100000\n" + LOGIN)
    check("a budget and its own login: rc 0", rc == 0 and "100000" in out, f"{rc} {out[-200:]}")
    rc, out = gate("ap", LOGIN)
    check("no .env budget, but a cog admin APPROVED one (the store's row): rc 0, from the approved request",
          approved is not None and rc == 0 and "500000" in out and "approved request" in out, f"{rc} {out[-200:]}")
    rc, out = gate("pe", LOGIN)
    check("a PENDING request is no budget: rc 4", pending is not None and rc == 4, f"{rc} {out[-200:]}")
    rc, out = gate("p")
    check("the cog's primary, no budget and no login of its own: rc 0 (as before)", rc == 0, f"{rc} {out[-200:]}")
    one = g / "one.json"
    one.write_text(json.dumps({"orgs": {orgs_["s"]: reg["orgs"][orgs_["s"]]}}))
    rc, out = gate("s", "", registry=one)
    check("a host of ONE org (not marked primary), no budget: rc 0 (as before)", rc == 0, f"{rc} {out[-200:]}")
    rc, out = gate("s", "", registry=g / "absent.json")
    check("no registry at all: rc 0 (as before)", rc == 0, f"{rc} {out[-200:]}")

    print("\nG SPAWN.SH, THE REAL PATH (psql, tmux, pgrep, node stubbed: nothing real is touched)")
    stub = g / "bin"
    stub.mkdir()
    for tool, rc_ in (("psql", 0), ("tmux", 1), ("pgrep", 1), ("node", 0)):
        (stub / tool).write_text(STUB.replace("{rc}", str(rc_)))
        (stub / tool).chmod(0o755)
    spawn = REPO / "scripts" / "spawn.sh"
    co = None
    if rt_src:                         # a mutant runtime_env: run spawn.sh from a copy whose runtime_env is the mutant
        co = g / "co"
        shutil.copytree(REPO / "scripts", co / "scripts")
        shutil.copytree(REPO / "src", co / "src", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(rt, co / "src" / "astryx" / "core" / "runtime_env.py")
        (co / "venv").symlink_to((REPO / "venv").resolve())
        spawn = co / "scripts" / "spawn.sh"

    def spawn_s(env_lines):
        # a DSN that names the org's registry db on a port nothing serves: only the stub psql ever "uses" it
        (homes["s"] / ".env").write_text(f"ASTRYX_ORG=fed-{orgs_['s']}\nASTRYX_DSN=postgresql://fxg@127.0.0.1:9/"
                                         f"{reg['orgs'][orgs_['s']]['db']}\n{env_lines}")
        log = g / "stub.log"
        log.unlink(missing_ok=True)
        shutil.rmtree(homes["s"] / "homes", ignore_errors=True)
        fake_home = g / "fakehome"
        fake_home.mkdir(exist_ok=True)
        r = subprocess.run(["bash", str(spawn), "fxagent"], capture_output=True, text=True, timeout=120,
                           env={**base, "HOME": str(fake_home), "PATH": f"{stub}:{base.get('PATH', '')}",
                                "ASTRYX_COG_REGISTRY": str(regf), "ASTRYX_HOME": str(homes["s"]),
                                "FX_STUB_LOG": str(log), "ASTRYX_CLI": str(stub / "node")})
        calls = log.read_text().splitlines() if log.exists() else []
        return r.returncode, r.stdout + r.stderr, calls

    rc, out, calls = spawn_s("")
    check("no budget: spawn.sh rc 1, says why, and NOTHING after the gate ran (no psql, no homes/fxagent)",
          rc == 1 and "no budget" in out and not any(c.startswith("psql") for c in calls)
          and not (homes["s"] / "homes" / "fxagent").exists(), f"{rc} {out[-300:]} {calls}")
    rc, out, calls = spawn_s("ASTRYX_ORG_BUDGET_TOKENS=100000\n")
    check("a budget on the ambient login: refused the same way (never the owner's login, silently)",
          rc == 1 and "ambient" in out and not any(c.startswith("psql") for c in calls), f"{rc} {out[-300:]} {calls}")
    rc, out, calls = spawn_s("ASTRYX_ORG_BUDGET_TOKENS=100000\n" + LOGIN)
    check("a budget and its own login: past the gate (its first psql ran; the stub tmux then ends the run)",
          any(c.startswith("psql") for c in calls) and "no budget" not in out, f"{rc} {out[-300:]} {calls}")
    if co:
        shutil.rmtree(co, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
