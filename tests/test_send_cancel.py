#!/usr/bin/env python3
"""Oracle for the send tool's cancellation (channel/server.mjs): a send whose tool call is cancelled never reaches anyone.

Origin (2026-11-13, wire msg 11813): seed's send(to='owner', thread='obs:seed') was interrupted by the owner; Claude
Code reported the call rejected, yet the message was delivered. server.mjs INSERTed the row (committed: the observatory
pushed it at once) and then polled up to 20s for a receipt, and its CallTool handler ignored the request's AbortSignal.

The real server.mjs is staged into a fixture home (tests/_stage_channel.py) on a throwaway fixture database
(fixture_db), driven over a real MCP stdio handshake; a cancel is the client's `notifications/cancelled`. A cancelled
call gets NO response from the SDK, so every arm waits on a CONDITION it measures (a stderr line, a row), never a sleep.

  C1  cancelled before the INSERT          -> no row (the server says so on stderr; an unmeasured attempt is retried)
  C2  cancelled during the receipt wait    -> status 'retracted', delivery.retracted=true; the bridges' selector
                                              (bridges/common.py listen) and the observatory's thread/read never take
                                              it; the id is rung again on astryx_wire
  C3  cancelled after delivery             -> the row is untouched ('delivered', no retracted mark)
  O1  the observatory's tap turns that ring into {"type": "message_retracted", "id"} for every SSE client; a new row
      is still a "message"; a malformed payload never takes the tap down
  O2  /api/messages (thread, global, after_id) leave a retracted row out; the workspace thread list
      (THREADS_SQL / TITLES_SQL / FIRST_SQL) never lists a thread whose only row is retracted
  O3  POST /api/thread/read never marks a retracted row
Exit 0 pass · 1 fail · 77 skipped (no node / node_modules / venv / fixture database).
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

for _k in [k for k in os.environ if k.startswith("GIT_")]:
    del os.environ[_k]
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_send_cancel", REPO, deps=("fastapi", "httpx", "asyncpg", "psycopg"), env=False)   # fixture_db only
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402
from _stage_channel import stage_server  # noqa: E402

SERVER = Path(os.environ.get("CHANNEL_SERVER_SRC", REPO / "channel" / "server.mjs"))
OBS_KEY = "test-owner-key"
fails = 0


def skip(why: str) -> None:
    print(f"SKIP: {why}")
    sys.exit(77)


def arm(name: str, ok: bool, detail="") -> None:
    global fails
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))


def wait_for(pred, timeout: float, tick: float = 0.1) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(tick)
    return bool(pred())


def node_bin() -> str | None:
    spawn = REPO / "scripts" / "spawn.sh"
    if spawn.exists():
        m = re.search(r"^NODE=(\S+)", spawn.read_text(), re.M)
        if m and Path(m.group(1)).exists():
            return m.group(1)
    return shutil.which("node")


class Body:
    """One staged server.mjs under one identity; its stdout is the MCP stream (tests/test_release_server.py's)."""

    def __init__(self, home: Path, agent: str, dsn: str):
        self.dir = Path(tempfile.mkdtemp(prefix=f"run-{agent}-", dir=home))
        self.out, self.err, self.n = self.dir / "stdout.log", self.dir / "stderr.log", 10
        env = {k: v for k, v in os.environ.items() if k not in ("ASTRYX_RELEASE_KEY", "ASTRYX_HOME")}
        env.update(ASTRYX_AGENT=agent, ASTRYX_DSN=dsn, ASTRYX_SUBS_REFRESH_MS="60000")
        with open(self.out, "wb") as o, open(self.err, "wb") as e:
            self.p = subprocess.Popen([NODE, str(home / "channel" / "server.mjs")], cwd=home, env=env,
                                      stdin=subprocess.PIPE, stdout=o, stderr=e)
        self.write({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "send-cancel-probe", "version": "0"}}})
        self.write({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def write(self, *msgs: dict) -> None:
        self.p.stdin.write(b"".join((json.dumps(m) + "\n").encode() for m in msgs))
        self.p.stdin.flush()

    def lines(self) -> list[dict]:
        got = []
        for ln in self.out.read_text(errors="replace").splitlines():
            try:
                got.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        return got

    def stderr(self) -> str:
        return self.err.read_text(errors="replace")

    def call(self, args: dict, cancel: bool = False) -> int:
        """tools/call send; with cancel, the client's cancel rides in the SAME flush (before any await resolves)."""
        self.n += 1
        req = {"jsonrpc": "2.0", "id": self.n, "method": "tools/call", "params": {"name": "send", "arguments": args}}
        msgs = [req] + ([self.cancel_msg(self.n)] if cancel else [])
        self.write(*msgs)
        return self.n

    @staticmethod
    def cancel_msg(rid: int) -> dict:
        return {"jsonrpc": "2.0", "method": "notifications/cancelled",
                "params": {"requestId": rid, "reason": "the owner interrupted the call"}}

    def reply(self, rid: int) -> dict | None:
        return next((m for m in self.lines() if m.get("id") == rid), None)

    def stop(self) -> None:
        if self.p.poll() is None:
            self.p.kill()
            self.p.wait(timeout=10)


def node_arms(db, home: Path, dsn: str) -> None:
    import psycopg

    def row(body: str):
        return db.execute("SELECT id, status, delivery FROM messages WHERE body=%s", (body,)).fetchone()

    shutil.copytree(REPO / "src", home / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (home / "venv").symlink_to(Path(sys.prefix))
    (home / "init.sh").write_text("# fixture checkout marker\n")
    shutil.copy2(REPO / "astryx.py", home / "astryx.py")
    stage_server(home / "channel", SERVER)
    (home / "agents").mkdir()
    (home / "agents" / "sender.md").write_text("# sender\n")
    (home / ".env").write_text(f"ASTRYX_DSN={dsn}\n")
    b = Body(home, "sender", dsn)
    try:
        if not wait_for(lambda: b.reply(1) is not None, 30):
            arm("the staged server answers initialize", False, b.stderr()[-600:])
            return
        # control: the server can write at all (else every "no row" below is vacuous)
        rid = b.call({"to": "peer", "thread": "t-ctl", "body": "CANCEL-CTL"})
        wait_for(lambda: b.reply(rid) is not None, 30)
        arm("control: an uncancelled send writes its row", row("CANCEL-CTL") is not None, b.stderr()[-600:])

        print("C1 cancelled before the INSERT")
        measured = False
        for attempt in range(3):
            body = f"CANCEL-C1-{attempt}"
            mark = "nothing sent (to owner)"
            before = b.stderr().count(mark)
            b.call({"to": "owner", "thread": "obs:sender", "body": body}, cancel=True)
            # the precondition, MEASURED: the pre-INSERT abort said so; a cancel that lost the race to the INSERT
            # went down C2's path instead, so that attempt proves nothing here and is retried
            if wait_for(lambda: b.stderr().count(mark) > before or row(body) is not None, 30) \
                    and b.stderr().count(mark) > before:
                arm("C1 no row is written", row(body) is None, row(body))
                measured = True
                break
            print(f"    (attempt {attempt}: the cancel landed after the INSERT; unmeasured, retried)")
        arm("C1 the pre-INSERT abort was measured (within 3 attempts)", measured, b.stderr()[-600:])

        print("C2 cancelled during the receipt wait")
        listen = psycopg.connect(dsn, autocommit=True)
        listen.execute("LISTEN astryx_wire")
        rid = b.call({"to": "owner", "thread": "obs:sender", "body": "CANCEL-C2"})
        wait_for(lambda: row("CANCEL-C2") is not None, 30)
        r = row("CANCEL-C2")
        arm("C2 the row was written and is pending (no bridge here)", r is not None and r[1] == "pending", r)
        if r:
            b.write(b.cancel_msg(rid))
            wait_for(lambda: row("CANCEL-C2")[1] != "pending", 10)
            r = row("CANCEL-C2")
            arm("C2 status is 'retracted'", r[1] == "retracted", r)
            arm("C2 delivery carries retracted=true and why", (r[2] or {}).get("retracted") is True
                and "cancelled" in (r[2] or {}).get("why", ""), r[2])
            arm("C2 the server answered nothing for the cancelled call", b.reply(rid) is None, b.reply(rid))
            # the bridges' selector, verbatim from bridges/common.py listen() (with an all-surfaces pending_where)
            sel = re.search(r'"(SELECT \* FROM messages WHERE status=\'pending\' )"\s*f?"(AND to_org=\'local\' AND )',
                            (REPO / "bridges" / "common.py").read_text())
            arm("C2 bridges/common.py's selector is still status='pending'", bool(sel))
            taken = [x[0] for x in db.execute(
                "SELECT id FROM messages WHERE status='pending' AND to_org='local' AND (true)").fetchall()]
            arm("C2 no bridge selects it", r[0] not in taken, taken)
            rings = []
            wait_for(lambda: rings.extend(n.payload for n in listen.notifies(timeout=0.2, stop_after=50)) or
                     str(r[0]) in rings, 5)
            # the INSERT's own ring and the retract's: the id twice
            arm("C2 the retract rang astryx_wire with the id (after the insert's ring)",
                rings.count(str(r[0])) >= 2, rings)
        listen.close()

        print("C3 cancelled after delivery")
        rid = b.call({"to": "owner", "thread": "obs:sender", "body": "CANCEL-C3"})
        wait_for(lambda: row("CANCEL-C3") is not None, 30)
        r = row("CANCEL-C3")
        if r is None:
            arm("C3 the row was written", False, b.stderr()[-600:])
        else:
            db.execute("UPDATE messages SET status='delivered', delivered_at=now(), "
                       "delivery='{\"ok\": true, \"handle\": \"fixture\"}'::jsonb WHERE id=%s", (r[0],))
            b.write(b.cancel_msg(rid))
            out = "already out (not pending)"
            wait_for(lambda: b.reply(rid) is not None or out in b.stderr(), 10)
            r = row("CANCEL-C3")
            arm("C3 the row stays delivered, unmarked", r[1] == "delivered" and "retracted" not in (r[2] or {}), r)
            how = "the receipt won (answered 'delivered')" if b.reply(rid) else \
                "the cancel won and logged 'already out'" if out in b.stderr() else "neither"
            arm(f"C3 one of the two settled the call: {how}", how != "neither", b.stderr()[-600:])
    finally:
        b.stop()


def observatory_arms(db, url: str) -> None:
    import importlib.util
    import observatory.api  # noqa: F401
    spec = importlib.util.spec_from_file_location("main", REPO / "observatory" / "api" / "main.py")
    obs = importlib.util.module_from_spec(spec)
    sys.modules["main"] = obs
    spec.loader.exec_module(obs)
    from fastapi.testclient import TestClient
    from observatory.api import workspace as W

    def ins(thread, body, status="pending", to="owner", frm="sender"):
        return db.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body, status) "
                          "VALUES (%s,'local',%s,'local',%s,'chat',%s,%s) RETURNING id",
                          (frm, to, thread, body, status)).fetchone()[0]

    keep = ins("obs:retract-x", "KEEP")
    gone = ins("obs:retract-x", "GONE")
    lone = ins("obs:retract-lone", "LONE")
    db.execute("UPDATE messages SET status='retracted' WHERE id = ANY(%s)", ([gone, lone],))

    got: list[dict] = []

    class Ear:                                     # an SSE client as the tap sees one: put_nowait
        def put_nowait(self, x):
            got.append(x)

    O = {"x-obs-key": OBS_KEY}
    with TestClient(obs.app, client=("127.0.0.1", 50000)) as cl:
        obs.sse_clients.add(Ear())

        print("O1 the live feed")
        # the tap's LISTEN is up when a ring reaches it: ring the kept row until it arrives (measured, bounded)
        ok = wait_for(lambda: db.execute("SELECT pg_notify('astryx_wire', %s)", (str(keep),)) and False
                      or any(e.get("type") == "message" and e.get("id") == keep for e in got), 20, tick=0.3)
        arm("O1 the tap is listening (a pending row's ring arrives as 'message')", ok, got[-3:])
        db.execute("SELECT pg_notify('astryx_wire', 'not-an-id')")
        db.execute("SELECT pg_notify('astryx_wire', %s)", (str(gone),))
        ok = wait_for(lambda: {"type": "message_retracted", "id": gone} in got, 10)
        arm("O1 a retracted row's ring arrives as message_retracted (after a malformed one)", ok, got[-3:])
        arm("O1 the retracted row is never pushed as a 'message'",
            not any(e.get("type") == "message" and e.get("id") == gone for e in got), got[-3:])

        print("O2 history and lists")
        ids = lambda r: [m["id"] for m in r.json()]   # noqa: E731
        th = cl.get("/api/messages", params={"thread": "obs:retract-x"}, headers=O)
        arm("O2 /api/messages?thread keeps the live row, omits the retracted", th.status_code == 200
            and keep in ids(th) and gone not in ids(th), th.text[:300])
        al = cl.get("/api/messages", params={"limit": 500}, headers=O)
        arm("O2 /api/messages omits retracted rows", gone not in ids(al) and lone not in ids(al), ids(al))
        af = cl.get("/api/messages", params={"after_id": keep - 1, "limit": 500}, headers=O)
        arm("O2 /api/messages?after_id (backfill) omits them", keep in ids(af) and gone not in ids(af), ids(af))
        tl = cl.get("/api/threads", headers=O)
        arm("O2 /api/threads never lists a thread whose only row is retracted",
            "obs:retract-lone" not in [t["thread"] for t in tl.json()], tl.text[:300])

        async def ws_sql():
            import asyncpg
            c = await asyncpg.connect(url)
            try:
                listed = [r["thread"] for r in await c.fetch(W.THREADS_SQL, "owner", True)]
                titled = [r["thread"] for r in await c.fetch(W.TITLES_SQL, ["obs:retract-x", "obs:retract-lone"])]
                first = {r["thread"]: r["body"] for r in
                         await c.fetch(W.FIRST_SQL, ["obs:retract-x", "obs:retract-lone"])}
                return listed, titled, first
            finally:
                await c.close()
        listed, titled, first = asyncio.run(ws_sql())
        arm("O2 workspace THREADS_SQL lists the live thread, not the retracted-only one",
            "obs:retract-x" in listed and "obs:retract-lone" not in listed, listed)
        arm("O2 workspace TITLES_SQL / FIRST_SQL skip retracted rows",
            "obs:retract-lone" not in titled and "obs:retract-lone" not in first, (titled, first))

        print("O3 the pane's read mark")
        cl.post("/api/thread/read", json={"thread": "obs:retract-x", "upto": gone}, headers=O)
        st = dict(db.execute("SELECT id, status FROM messages WHERE id = ANY(%s)", ([keep, gone],)).fetchall())
        arm("O3 thread/read marks the live row and never the retracted one",
            st[keep] == "delivered" and st[gone] == "retracted", st)


if __name__ == "__main__":
    NODE = node_bin()
    if not NODE:
        skip("no node binary")
    if not (REPO / "channel" / "node_modules" / "pg").is_dir():
        skip("channel/node_modules/pg is absent (run npm install in channel/)")
    if sys.prefix == sys.base_prefix:
        skip("run under the org's venv (the fixture links it for the interpreter and site-packages)")
    import psycopg
    try:
        with fixture_db() as fx, tempfile.TemporaryDirectory(prefix="sendcancel.") as td:
            os.environ["ASTRYX_DSN"] = fx["url"]
            os.environ["OBS_KEY"] = OBS_KEY
            os.environ["ASTRYX_ORG"] = "fixture.example"
            os.environ["ASTRYX_GATEWAY_PORT"] = "9"
            os.environ.setdefault("ASTRYX_COG_REGISTRY", str(Path(td) / "absent.json"))
            with psycopg.connect(fx["dsn"], autocommit=True) as db:
                node_arms(db, Path(td) / "home", fx["url"])
                observatory_arms(db, fx["url"])
    except FixtureUnavailable as e:
        from astryx.security.sqlguard.estate import unavailable
        unavailable("test_send_cancel", REPO, e)
    print(f"{'PASS' if not fails else 'FAIL'}: send cancel ({fails} failing)")
    sys.exit(1 if fails else 0)
