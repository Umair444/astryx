#!/usr/bin/env python3
"""Oracle: two orgs with NO public URL exchange signed messages through a relay (goal 10224 S5).

Three REAL gateways (bridges/gateway.py under uvicorn, ephemeral loopback ports), each on its own
throwaway database: a relay host (ASTRYX_RELAY_HOST=1) and two NAT'd orgs (ASTRYX_URL empty,
ASTRYX_RELAY = the host). The orgs register, meet through the relay (signed hello and signed
reply), and a row inserted on one org's wire arrives on the other's through the same inbox path a
direct POST takes. Then: a tampered envelope dies at the relay AND at the recipient (planted in
the mailbox past the relay), a duplicate is dropped, the directory is opt-in, reach answers with
the target's key, and the wizard's .env edits hold for each choice (temp .env files).
Every wait is on a condition with a named deadline. The live database is never touched.
"""
import asyncio
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate('test_relay', REPO, deps=('psycopg', 'asyncpg', 'fastapi', 'nacl', 'httpx', 'uvicorn'))
import httpx  # noqa: E402
import psycopg  # noqa: E402
from nacl.encoding import HexEncoder  # noqa: E402
from nacl.signing import SigningKey  # noqa: E402

from bridges import relay  # noqa: E402
from astryx.federation import federate, introduce as intro  # noqa: E402
from astryx.security.sqlguard.fixture import fixture_db  # noqa: E402

PY = sys.executable
B_RATE = 5                                   # B's inbox cap per window (ASTRYX_INBOX_RATE)
fails = 0


def arm(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def wait(cond, deadline_s, what):
    """Wait on a CONDITION; on expiry say which one never held."""
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            v = cond()
            if v:
                return v
        except Exception:
            pass
        time.sleep(0.1)
    print(f"        (deadline {deadline_s}s: {what} never held)")
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def q(dsn, sql, *args):
    with psycopg.connect(dsn, autocommit=True) as c:
        return c.execute(sql, args).fetchall()


class Org:
    def __init__(self, name, fx, port, logdir, url="", relay_url="", listed=False, host=False, extra=None):
        self.name, self.dsn, self.port = name, fx["dsn"], port
        self.base = f"http://127.0.0.1:{port}"
        self.key = SigningKey.generate()
        self.pub = self.key.verify_key.encode(HexEncoder).decode()
        self.url = url
        self.env = {"ASTRYX_ORG": name, "ASTRYX_SECRET_KEY": self.key.encode(HexEncoder).decode(),
                    "ASTRYX_DSN": fx["url"], "ASTRYX_URL": url, "ASTRYX_RELAY": relay_url,
                    "ASTRYX_RELAY_LISTED": "1" if listed else "0",
                    "ASTRYX_RELAY_HOST": "1" if host else "0",
                    "ASTRYX_RELAY_REACH_PRIVATE": "1" if host else "0", **(extra or {})}
        self.log = Path(logdir) / f"{name}.log"
        self.start()

    def start(self):
        with open(self.log, "a") as log:
            self.proc = subprocess.Popen(
                [PY, "-m", "uvicorn", "gateway:app", "--host", "127.0.0.1", "--port", str(self.port)],
                cwd=REPO / "bridges", env={**os.environ, **self.env},
                stdout=log, stderr=subprocess.STDOUT)

    def up(self):
        return wait(lambda: httpx.get(f"{self.base}/astryx/identity", timeout=2).status_code == 200,
                    40, f"{self.name} gateway answers /astryx/identity")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def tail(self):
        return self.log.read_text()[-1500:]

    def envelope(self, to, body):
        e = {"astryx": 0, "id": str(uuid.uuid4()), "from": f"alice@{self.name}", "to": to,
             "thread": "t-relay", "intent": "chat", "body": body, "ts": time.time()}
        return relay.signed(e, self.key)


def landed(org, frm, body):
    return q(org.dsn, "SELECT count(*) FROM messages WHERE from_org=%s AND body=%s", frm, body)[0][0]


def run(fr, fa, fb, tmp):
    port = free_port()                           # the relay host is the one org WITH a public URL
    R = Org("relayhost.test", fr, port, tmp, url=f"http://127.0.0.1:{port}", host=True)
    orgs = [R]
    try:
        rel = R.base
        A = Org("orga.test", fa, free_port(), tmp, relay_url=rel, listed=True)
        orgs.append(A)
        # B's own door is capped small and fast, so the over-the-cap arm runs in seconds
        B = Org("orgb.test", fb, free_port(), tmp, relay_url=rel, listed=False,
                extra={"ASTRYX_INBOX_RATE": str(B_RATE), "ASTRYX_RATE_WINDOW": "4", "ASTRYX_RELAY_BACKOFF": "1"})
        orgs.append(B)
        for o in orgs:
            if not o.up():
                arm(f"{o.name} gateway starts", False, o.tail())
                return
        # A meets the host directly first (a peer WITH a URL): its pickup_task then has a peer to poll
        intro.introduce(R.base, {**A.env, "ASTRYX_DSN": A.dsn})

        # --- registration and the directory
        reg = wait(lambda: len(q(R.dsn, "SELECT org FROM relay_orgs WHERE org IN ('orga.test','orgb.test')")) == 2,
                   20, "both NAT orgs registered at the relay")
        arm("both NAT'd gateways register with the relay on start (signed by their org key)", bool(reg),
            q(R.dsn, "SELECT org FROM relay_orgs") or A.tail())
        d = httpx.get(f"{rel}/relay/directory").json()["orgs"]
        names = {x["org"] for x in d}
        arm("the directory is opt-in: the listed org is there, the unlisted one is not",
            "orga.test" in names and "orgb.test" not in names, names)
        arm("the directory carries the registered key",
            any(x["org"] == "orga.test" and x["pubkey"] == A.pub for x in d), d)
        thief = relay.register_claim(SigningKey.generate(), "orga.test", None, True)
        r = httpx.post(f"{rel}/relay/register", json=thief)
        arm("a second key cannot take a registered name (409)", r.status_code == 409, r.status_code)

        # --- the introduction, through the relay, between two orgs with no door
        intro.introduce_via_relay("orgb.test", {**A.env, "ASTRYX_DSN": A.dsn})
        met = wait(lambda: q(B.dsn, "SELECT pubkey, url FROM peers WHERE org='orga.test'")
                   and q(A.dsn, "SELECT pubkey, url FROM peers WHERE org='orgb.test'"),
                   20, "each org holds the other as a peer")
        pa = q(B.dsn, "SELECT pubkey, url, status FROM peers WHERE org='orga.test'")
        pb = q(A.dsn, "SELECT pubkey, url, status FROM peers WHERE org='orgb.test'")
        arm("a signed hello through the relay makes each org the other's peer, with the right key",
            bool(met) and pa and pb and pa[0][0] == A.pub and pb[0][0] == B.pub
            and pa[0][2] == "introduced" and pb[0][2] == "introduced", (pa, pb, B.tail()))
        arm("neither peer row has a URL (both NAT'd: the relay is the only path)",
            bool(pa and pb) and pa[0][1] is None and pb[0][1] is None, (pa, pb))

        # --- MANDATORY: a wire row crosses A -> relay -> B, and back
        body_ab = f"hello from orga through the relay {uuid.uuid4().hex[:6]}"
        q(A.dsn, "INSERT INTO messages (from_agent, to_agent, to_org, intent, body, thread) "
                 "VALUES ('alice', 'seed', 'orgb.test', 'chat', %s, 't-relay') RETURNING id", body_ab)
        got = wait(lambda: landed(B, "orga.test", body_ab), 20, "A's row lands on B's wire")
        arm("E2E: a row on A's wire arrives on B's wire through the relay", bool(got), A.tail() + B.tail())
        row = q(B.dsn, "SELECT from_agent, to_agent, to_org, sig FROM messages WHERE body=%s", body_ab)
        arm("it arrives as an ordinary local row for seed, carrying A's signature",
            bool(row) and row[0][0] == "alice" and row[0][1] == "seed" and row[0][2] == "local"
            and bool(row[0][3]), row)
        st = q(A.dsn, "SELECT status FROM messages WHERE body=%s", body_ab)
        arm("A's outbound row is marked delivered (the relay accepted it)", st == [("delivered",)], st)
        body_ba = f"reply from orgb {uuid.uuid4().hex[:6]}"
        q(B.dsn, "INSERT INTO messages (from_agent, to_agent, to_org, intent, body) "
                 "VALUES ('seed', 'seed', 'orga.test', 'chat', %s) RETURNING id", body_ba)
        arm("E2E: and B's reply arrives on A's wire", bool(wait(lambda: landed(A, "orgb.test", body_ba), 20,
                                                             "B's reply lands on A")), B.tail())

        # --- tampering dies
        e = A.envelope("seed@orgb.test", "the real words")
        e["body"] = "altered words"
        r = httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg", "envelope": e})
        arm("a tampered envelope is refused at the relay (403)", r.status_code == 403, r.status_code)
        planted = A.envelope("seed@orgb.test", "planted original")
        planted["body"] = "planted and altered"
        q(R.dsn, "INSERT INTO relay_mail (to_org, from_org, kind, envelope) VALUES "
                 "('orgb.test', 'orga.test', 'msg', %s) RETURNING id", json.dumps(planted))
        canary = f"canary-1 {uuid.uuid4().hex[:6]}"
        r = httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg",
                                                  "envelope": A.envelope("seed@orgb.test", canary)})
        arrived = wait(lambda: landed(B, "orga.test", canary), 20, "canary after the planted envelope")
        arm("a tampered envelope planted past the relay dies at the recipient's verify",
            bool(arrived) and landed(B, "orga.test", "planted and altered") == 0, (r.status_code, B.tail()))

        # --- a duplicate is dropped
        dup = A.envelope("seed@orgb.test", f"said once {uuid.uuid4().hex[:6]}")
        codes = [httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg",
                                                       "envelope": dup}).status_code for _ in range(2)]
        canary2 = f"canary-2 {uuid.uuid4().hex[:6]}"
        httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg",
                                              "envelope": A.envelope("seed@orgb.test", canary2)})
        arrived = wait(lambda: landed(B, "orga.test", canary2), 20, "canary after the duplicate")
        arm("the same envelope relayed twice lands once", codes == [200, 200] and bool(arrived)
            and landed(B, "orga.test", dup["body"]) == 1, (codes, landed(B, "orga.test", dup["body"])))
        # across a restart: seen_ids is gone, so the row in messages is what drops the copy
        mark = len(R.log.read_text())
        B.stop()
        B.start()
        back = B.up() and wait(lambda: "POST /relay/register" in R.log.read_text()[mark:], 20,
                               "B registers again after its restart")
        httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg", "envelope": dup})
        canary4 = f"canary-4 {uuid.uuid4().hex[:6]}"
        httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg",
                                              "envelope": A.envelope("seed@orgb.test", canary4)})
        arrived = wait(lambda: landed(B, "orga.test", canary4), 20, "canary after the post-restart duplicate")
        arm("a duplicate relayed after the recipient restarts still lands once (the row is the memory)",
            bool(arrived) and landed(B, "orga.test", dup["body"]) == 1, (back, landed(B, "orga.test", dup["body"])))
        # R1: over B's own inbox cap. Each of these is "delivered" for the sender the moment the relay
        # takes it, so a 429 at B's door must leave it in the mailbox for later, never ack it away.
        burst = [f"burst {i} {uuid.uuid4().hex[:6]}" for i in range(B_RATE + 1)]
        codes = [httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg", "envelope":
                 A.envelope("seed@orgb.test", b)}).status_code for b in burst]
        allin = wait(lambda: all(landed(B, "orga.test", b) == 1 for b in burst), 40,
                     f"all {len(burst)} of a burst over B's cap of {B_RATE} land")
        arm(f"R1: {len(burst)} envelopes against an inbox cap of {B_RATE} all land, eventually (429 = keep, back off)",
            codes == [200] * len(burst) and bool(allin),
            (codes, [landed(B, "orga.test", b) for b in burst], B.tail()))
        # R2: an item that RAISES (a dict thread breaks the INSERT) must not jam the mailbox
        bad = A.envelope("seed@orgb.test", f"raises {uuid.uuid4().hex[:6]}")
        bad["thread"] = {"not": "text"}
        bad = relay.signed(bad, A.key)
        good = f"after the raiser {uuid.uuid4().hex[:6]}"
        c1 = httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg", "envelope": bad}).status_code
        httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg",
                                              "envelope": A.envelope("seed@orgb.test", good)})
        through = wait(lambda: landed(B, "orga.test", good), 40, "the good envelope behind the raiser lands")
        arm("R2: a validly signed item that raises is retried, then skipped; the one behind it lands",
            c1 == 200 and bool(through) and landed(B, "orga.test", bad["body"]) == 0
            and f"(attempt {3}/3)" in B.log.read_text(), (c1, B.tail()))
        left = q(R.dsn, "SELECT count(*) FROM relay_mail WHERE to_org='orgb.test'")[0][0]
        arm("collected mail is acked off the relay", bool(wait(
            lambda: q(R.dsn, "SELECT count(*) FROM relay_mail WHERE to_org='orgb.test'")[0][0] == 0,
            40, "B's mailbox empties")), left)
        arm("the relay host's own wire never saw the relayed traffic",
            q(R.dsn, "SELECT count(*) FROM messages WHERE from_org IN ('orga.test','orgb.test')")[0][0] == 0
            and q(R.dsn, "SELECT count(*) FROM peers WHERE org='orgb.test'")[0][0] == 0)
        r = httpx.post(f"{rel}/relay/send", json={"to": "nobody.test", "kind": "msg",
                                                  "envelope": A.envelope("seed@nobody.test", "x")})
        arm("an unknown recipient is a 404, not a silent drop", r.status_code == 404, r.status_code)

        # (b): the host registers itself on its own relay, listed with its URL, so a NAT org finds it by
        # NAME and introduces directly (`introduce.py relayhost.test`)
        hd = httpx.get(f"{rel}/relay/directory", params={"org": "relayhost.test"}).json()["orgs"]
        arm("the relay's host is listed on its own relay, with its URL and key",
            hd == [{**hd[0], "org": "relayhost.test", "pubkey": R.pub, "url": R.base}] if hd else False, hd)
        benv = {**B.env, "ASTRYX_DSN": B.dsn}
        real_load, intro.load_env = intro.load_env, (lambda path=None: benv)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                intro.main(["relayhost.test"])
        finally:
            intro.load_env = real_load
        arm("`introduce.py <host-name>` finds the host by name and introduces DIRECTLY",
            "directly" in out.getvalue()
            and q(B.dsn, "SELECT url, pubkey FROM peers WHERE org='relayhost.test'") == [(R.base, R.pub)]
            and q(R.dsn, "SELECT pubkey FROM peers WHERE org='orgb.test'") == [(B.pub,)]
            and q(R.dsn, "SELECT count(*) FROM relay_mail WHERE to_org='relayhost.test'")[0][0] == 0,
            out.getvalue())
        ghost = SigningKey.generate()
        e = relay.signed({"astryx": 0, "id": str(uuid.uuid4()), "from": "x@ghost.test", "to": "seed@orgb.test",
                          "thread": None, "intent": "chat", "body": "hi", "ts": time.time()}, ghost)
        r = httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg", "envelope": e})
        arm("an unregistered sender cannot post (403)", r.status_code == 403, r.status_code)
        r = httpx.get(f"{rel}/relay/pickup", params=relay.pickup_claim(ghost, "ghost.test", 0))
        arm("an unregistered org cannot collect (403)", r.status_code == 403, r.status_code)
        r = httpx.get(f"{rel}/relay/pickup", params=relay.pickup_claim(ghost, "orgb.test", 0))
        arm("nobody collects another org's mail without its key (403)", r.status_code == 403, r.status_code)
        q(R.dsn, "INSERT INTO relay_mail (to_org, from_org, kind, envelope, created_at) VALUES "
                 "('gone.test', 'orga.test', 'msg', '{}', now() - interval '4 days') RETURNING id")
        # a registered org that never met B: the relay carries it, B's door drops it (no peer row)
        r = httpx.post(f"{rel}/relay/register", json=relay.register_claim(ghost, "ghost.test", None, False))
        stranger = f"from a stranger {uuid.uuid4().hex[:6]}"
        e = relay.signed({"astryx": 0, "id": str(uuid.uuid4()), "from": "x@ghost.test", "to": "seed@orgb.test",
                          "thread": None, "intent": "chat", "body": stranger, "ts": time.time()}, ghost)
        r2 = httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg", "envelope": e})
        canary3 = f"canary-3 {uuid.uuid4().hex[:6]}"
        httpx.post(f"{rel}/relay/send", json={"to": "orgb.test", "kind": "msg",
                                              "envelope": A.envelope("seed@orgb.test", canary3)})
        arrived = wait(lambda: landed(B, "orga.test", canary3), 20, "canary after the stranger's envelope")
        arm("an org B never met cannot write to B through the relay (no peer row, dropped)",
            r.status_code == 200 and r2.status_code == 200 and bool(arrived)
            and landed(B, "ghost.test", stranger) == 0, (r.status_code, r2.status_code))
        arm("mail older than the TTL is dropped from the relay",
            q(R.dsn, "SELECT count(*) FROM relay_mail WHERE to_org='gone.test'")[0][0] == 0)
        lost = f"to nobody {uuid.uuid4().hex[:6]}"
        q(A.dsn, "INSERT INTO messages (from_agent, to_agent, to_org, intent, body) "
                 "VALUES ('alice', 'seed', 'nobody.test', 'chat', %s) RETURNING id", lost)
        dead = wait(lambda: q(A.dsn, "SELECT status FROM messages WHERE body=%s", lost) == [("dead",)], 20,
                    "a row to an org we never met goes dead")
        arm("a row to an org we never met dies with an error to its sender (unchanged behaviour)",
            bool(dead) and q(A.dsn, "SELECT count(*) FROM messages WHERE to_agent='alice' AND intent='error'")[0][0] == 1)

        # --- reach
        rr = httpx.get(f"{rel}/relay/reach", params={"url": A.base}).json()
        arm("reach answers with the target gateway's identity", rr.get("reachable") and rr.get("pubkey") == A.pub, rr)
        closed = f"http://127.0.0.1:{free_port()}"
        rr = httpx.get(f"{rel}/relay/reach", params={"url": closed}).json()
        arm("reach reports a closed port as unreachable", rr.get("reachable") is False, rr)
        arm("reach refuses private and loopback targets by default",
            not relay.public_target("http://127.0.0.1:8845") and not relay.public_target("http://10.1.2.3:8845")
            and not relay.public_target("http://192.168.1.5:8845"))

        # --- the wizard's .env edits, one temp .env per choice
        secret = A.env["ASTRYX_SECRET_KEY"]

        def envfile(name, url="http://old.example:8845"):
            p = tmp / name
            p.write_text(f"# my org\nFOO=bar\nASTRYX_ORG=orga.test\nASTRYX_SECRET_KEY={secret}\n"
                         f"ASTRYX_URL={url}\nASTRYX_DSN={A.dsn}\n")
            return p

        def wiz(args):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = federate.main(args)
            return rc, out.getvalue()

        p = envfile("relay.env")
        rc, out = wiz(["--relay", rel, "--no-introduce", "--env-file", str(p)])
        kv = intro.load_env(p)
        arm("wizard (1) relay: ASTRYX_RELAY set, ASTRYX_URL cleared, listed, other lines kept",
            rc == 0 and kv.get("ASTRYX_RELAY") == rel and kv.get("ASTRYX_URL") == ""
            and kv.get("ASTRYX_RELAY_LISTED") == "1" and kv.get("FOO") == "bar"
            and p.read_text().startswith("# my org\nFOO=bar\n") and kv.get("ASTRYX_SECRET_KEY") == secret,
            (rc, p.read_text().replace(secret, "<secret>")))
        arm("wizard never prints the secret", secret not in out)
        p = envfile("unlisted.env")
        rc, _ = wiz(["--relay", rel, "--unlisted", "--no-introduce", "--env-file", str(p)])
        arm("wizard (1) --unlisted writes ASTRYX_RELAY_LISTED=0", intro.load_env(p).get("ASTRYX_RELAY_LISTED") == "0")
        p = envfile("public.env")
        rc, out = wiz(["--public-url", A.base, "--relay-url", rel, "--no-introduce", "--env-file", str(p)])
        kv = intro.load_env(p)
        arm("wizard (2) public URL: reachable as this org -> ASTRYX_URL set, ASTRYX_RELAY cleared",
            rc == 0 and kv.get("ASTRYX_URL") == A.base and kv.get("ASTRYX_RELAY") == "", (rc, out))
        p = envfile("closed.env")
        before = p.read_bytes()
        rc, out = wiz(["--public-url", closed, "--relay-url", rel, "--no-introduce", "--env-file", str(p)])
        arm("wizard (2) unreachable: nothing written, port-forwarding help shown, rc 2",
            rc == 2 and p.read_bytes() == before and "8845" in out and "Firewall" in out, (rc, out))
        p = envfile("wrongorg.env")
        before = p.read_bytes()
        rc, out = wiz(["--public-url", B.base, "--relay-url", rel, "--no-introduce", "--env-file", str(p)])
        arm("wizard (2) a URL that answers as ANOTHER org is refused", rc == 2 and p.read_bytes() == before, out)
        p = envfile("skip.env")
        before = p.read_bytes()
        rc, _ = wiz(["--skip", "--env-file", str(p)])
        arm("wizard (3) skip: rc 0, .env untouched", rc == 0 and p.read_bytes() == before)

        # --- the wizard introduces to the relay's host org; a peer WITH a URL keeps direct delivery
        p = envfile("intro.env")
        rc, out = wiz(["--relay", rel, "--introduce", "--env-file", str(p)])
        ph = q(A.dsn, "SELECT url, pubkey, status FROM peers WHERE org='relayhost.test'")
        arm("wizard introduces to the host org and shows the peer row",
            rc == 0 and ph and ph[0][1] == R.pub and "Peer row" in out and "relayhost.test" in out, (rc, out))
        arm("the host org now holds this org as a peer",
            q(R.dsn, "SELECT pubkey FROM peers WHERE org='orga.test'") == [(A.pub,)])
        again = intro.introduce(R.base, intro.load_env(p))
        arm("introducing twice is idempotent (one peer row, same key)",
            again["pubkey"] == R.pub and q(R.dsn, "SELECT count(*) FROM peers WHERE org='orga.test'")[0][0] == 1)
        arm("peer_row of an org we never met is None", intro.peer_row(intro.load_env(p), "nobody.test") is None)
        direct = f"direct {uuid.uuid4().hex[:6]}"
        q(A.dsn, "INSERT INTO messages (from_agent, to_agent, to_org, intent, body) "
                 "VALUES ('alice', 'seed', 'relayhost.test', 'chat', %s) RETURNING id", direct)
        got = wait(lambda: landed(R, "orga.test", direct), 20, "direct delivery to a peer with a URL")
        arm("a peer with a URL keeps direct delivery (no relay mailbox involved)",
            bool(got) and q(R.dsn, "SELECT count(*) FROM relay_mail WHERE to_org='relayhost.test'")[0][0] == 0,
            A.tail())
        polled = wait(lambda: "GET /astryx/pickup?org=orga.test" in R.log.read_text(), 70,
                      "A's direct pickup_task polls the host (it sleeps 30s while peerless, holds 25s)")
        arm("a NAT org still long-polls its URL peers directly (pickup_task unchanged)", bool(polled))
    finally:
        for o in orgs:
            o.stop()


async def proxy_arms():
    """(a): behind cloudflared every client is 127.0.0.1. The unit runs uvicorn with --proxy-headers
    --forwarded-allow-ips 127.0.0.1, so the per-IP introduce cap keys on X-Forwarded-For from the tunnel,
    and on the real address from anyone else. Driven through uvicorn's own ProxyHeadersMiddleware around
    the real gateway app (the cap fires before any DB read, so no lifespan is needed)."""
    unit = [l for l in (REPO / "init.sh").read_text().splitlines() if "uvicorn gateway:app" in l]
    arm("the generated gateway unit trusts X-Forwarded-For from 127.0.0.1 only",
        len(unit) == 1 and "--proxy-headers --forwarded-allow-ips 127.0.0.1" in unit[0], unit)
    for k, v in {"ASTRYX_ORG": "proxytest.test", "ASTRYX_SECRET_KEY": "22" * 32, "ASTRYX_URL": "",
                 "ASTRYX_RELAY": "", "ASTRYX_RELAY_HOST": "0", "ASTRYX_DSN": "postgresql:///unused"}.items():
        os.environ[k] = v
    import bridges.gateway as gw
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    app = ProxyHeadersMiddleware(gw.app, trusted_hosts="127.0.0.1")

    async def knock(client_ip, xff):
        t = httpx.ASGITransport(app=app, client=(client_ip, 5000))
        async with httpx.AsyncClient(transport=t, base_url="http://gw") as c:
            return (await c.post("/astryx/introduce", content=b"{}",
                                 headers={"x-forwarded-for": xff})).status_code
    tunnel = [await knock("127.0.0.1", "198.51.100.7") for _ in range(gw.INTRO_RATE + 1)]
    other = await knock("127.0.0.1", "198.51.100.8")
    arm("through the tunnel (127.0.0.1 + XFF) the cap keys on the forwarded IP",
        tunnel[:-1] == [400] * gw.INTRO_RATE and tunnel[-1] == 429 and other == 400, (tunnel, other))
    direct = [await knock("203.0.113.9", f"198.51.100.{i}") for i in range(gw.INTRO_RATE + 1)]
    spoof = await knock("203.0.113.10", "198.51.100.7")
    arm("from any other address XFF is ignored: the cap keys on the real client",
        direct[:-1] == [400] * gw.INTRO_RATE and direct[-1] == 429 and spoof == 400, (direct, spoof))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="test-relay-") as tmp, \
            fixture_db() as fr, fixture_db() as fa, fixture_db() as fb:
        run(fr, fa, fb, Path(tmp))
    asyncio.run(proxy_arms())
    print(f"{'ALL PASS' if not fails else 'FAIL'}: relay federation ({fails} failing)")
    sys.exit(1 if fails else 0)
