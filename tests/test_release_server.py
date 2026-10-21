#!/usr/bin/env python3
"""Oracle for plan-9139 S1b-2's node seats: channel/server.mjs for a tier-LABELLED member, run for real.

The server is staged into a fixture HOME (tests/_stage_channel.py) whose src/ is a COPY of this tree's, so the door it
shells out to (src/astryx/security/release.py, by path) resolves its REPO to the fixture: fixture charters, fixture
routes, a fixture key in the fixture .env, the fixture tier store. A symlinked src would resolve to the LIVE roster,
key and tier/ (repo_root follows realpath), so arm H0 proves the door's REPO is the fixture before anything else runs.
The database is a throwaway created for this run and dropped after it; the org's own database is never written.

  H0  the staged door's REPO is the fixture home
  L   a malformed private grant (each of a4 #46035's spellings) REFUSES the server's start, named; an identity with
      no charter starts UNKNOWN (its ear works, its sends and permission requests are refused); an exact grant starts
      labelled; an unlabelled charter starts as today
  D   a door that can't run: an org charter starts UNKNOWN, and while it still can't run its send is refused with
      no row (D″); once it runs, the label is read again and the next send and permission take today's path (D′)
  S   a labelled send: to the owner → one row whose body is a size marker, the sentinel nowhere in messages, a stamp
      that open_stamped() resolves to the body; to an agent → body withheld, thread derived, intent clamped, and a
      reply on a thread delivered to this session keeps it; to a person's address or a federation address → refused,
      NO row; with no release key → refused, NO row
  P   a labelled member's permission request is DENIED on the MCP stream and writes NO row; the unlabelled control's
      is relayed as today
  I   an inbound tier-route row (S1b-2b): its own tier's member is pushed the BODY, resolved through the door; an
      org or UNKNOWN session gets the marker; a wrong body MAC gets the marker and the refusal
  U   the unlabelled control's send is today's row, column for column, delivery NULL
Exit 0 pass · 1 fail · 77 skipped (no node, no node_modules, no database, no CREATEDB).
"""
import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

for _k in [k for k in os.environ if k.startswith("GIT_")]:
    del os.environ[_k]
REPO = Path(__file__).resolve().parents[1]


import sys as _sys  # noqa: E402
_sys.path.insert(0, str(REPO / "tests"))
from org_estate import astryx_call  # noqa: E402


def _astryx(mod, fn, *args):   # astryx.<mod>.<fn>(*args) from THIS tree, side-effect free (tests/org_estate.py)
    return astryx_call(REPO, mod, fn, *args)


ESTATE = _astryx("paths", "estate", __file__)   # the org's estate: this tree on one org, its HOME on several (S3a)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _stage_channel import stage_server  # noqa: E402

SERVER = Path(os.environ.get("CHANNEL_SERVER_SRC", REPO / "channel" / "server.mjs"))
SENT = "S1B2-SENTINEL-labelled-body-7f3e"
KEY = "f" * 40
ROUTE = {"chat": "101@s.whatsapp.net", "agent": "member", "enabled": True, "counterpart": "owner", "tier": "career"}
failures: list[str] = []


def skip(why: str) -> None:
    print(f"SKIP: {why}. Nothing was verified here.")
    sys.exit(77)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def node_bin() -> str | None:
    spawn = REPO / "scripts" / "spawn.sh"
    if spawn.exists():
        m = re.search(r"^NODE=(\S+)", spawn.read_text(), re.M)
        if m and Path(m.group(1)).is_file():
            return m.group(1)
    return shutil.which("node")


def admin_dsn() -> str | None:
    try:                     # the ONE resolver (astryx.config.dsn): the environment first, else the estate's .env
        return _astryx("config", "dsn", ESTATE / ".env")
    except LookupError:
        return None


NODE = node_bin()
if not NODE:
    skip("no node binary")
if not (REPO / "channel" / "node_modules" / "pg").is_dir():
    skip("channel/node_modules/pg is absent (run npm install in channel/)")
if sys.prefix == sys.base_prefix:
    skip("run under the org's venv (the fixture links it for the interpreter and site-packages)")
try:
    import psycopg
except ImportError:
    skip("no psycopg")
ADMIN = admin_dsn()
if not ADMIN:
    skip("no ASTRYX_DSN")
try:
    admin = psycopg.connect(ADMIN, autocommit=True, connect_timeout=5)
except Exception as e:                                          # noqa: BLE001
    skip(f"database unreachable ({type(e).__name__})")
if not admin.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()[0]:
    skip("this role cannot CREATE DATABASE; a throwaway is the only safe substrate")
# The throwaway is a fixture_db(): PREFIX-named and owner-stamped, so reap() collects a killed run's. A hand-made
# astryx_relserver_<pid> had neither, and 7 killed runs' leaked for good on 10-14 (a2 #61827, seed #61829).
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db  # noqa: E402
_fx = fixture_db()                       # schema.sql applied whole, as this oracle used to apply it by hand
try:
    FX = _fx.__enter__()
except FixtureUnavailable as e:
    skip(f"no fixture database ({e})")
PROBE_DB, PROBE_DSN = FX["dbname"], FX["url"]   # a URL: node-pg reads it from the fixture .env and ASTRYX_DSN

home = Path(tempfile.mkdtemp(prefix="relserver."))
atexit.register(shutil.rmtree, home, True)   # it holds the fixture .env with PROBE_DSN; a TERM'd run left it (a2 A-1 #61835)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # a TERM exits through the finally's cleanup() and atexit
procs: list[subprocess.Popen] = []


def cleanup() -> None:
    for p in procs:
        if p.poll() is None:
            p.kill()
            try:
                p.wait(timeout=10)
            except Exception:                                   # noqa: BLE001
                pass
    try:
        _fx.__exit__(None, None, None)                          # fixture_db drops it WITH (FORCE)
    except Exception:                                           # noqa: BLE001
        pass
    admin.close()
    shutil.rmtree(home, ignore_errors=True)


def write_env(with_key: bool) -> None:
    (home / ".env").write_text(f"ASTRYX_DSN={PROBE_DSN}\n" + (f"ASTRYX_RELEASE_KEY={KEY}\n" if with_key else ""))


def wait_for(pred, timeout: float, tick: float = 0.2) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(tick)
    return False


class Body:
    """One staged server under one identity, with a real MCP handshake; its stdout is the MCP stream."""

    def __init__(self, agent: str):
        self.agent, self.dir, self.n = agent, Path(tempfile.mkdtemp(prefix=f"run-{agent}-", dir=home)), 10
        self.out, self.err = self.dir / "stdout.log", self.dir / "stderr.log"
        env = {k: v for k, v in os.environ.items() if k not in ("ASTRYX_RELEASE_KEY", "ASTRYX_HOME")}
        env.update(ASTRYX_AGENT=agent, ASTRYX_DSN=PROBE_DSN, ASTRYX_SUBS_REFRESH_MS="60000")
        with open(self.out, "wb") as o, open(self.err, "wb") as e:
            self.p = subprocess.Popen([NODE, str(home / "channel" / "server.mjs")], cwd=home, env=env,
                                      stdin=subprocess.PIPE, stdout=o, stderr=e)
        procs.append(self.p)
        self.write({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "release-server-probe", "version": "0"}}})
        self.write({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def write(self, msg: dict) -> None:
        try:
            self.p.stdin.write((json.dumps(msg) + "\n").encode())
            self.p.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass

    def lines(self) -> list[dict]:
        got = []
        for ln in self.out.read_text(errors="replace").splitlines():
            try:
                got.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        return got

    def listening(self, n: int) -> bool:
        """Alive, and the n-th LISTEN connection on the probe DB is up (a LISTEN client's last query is
        `LISTEN astryx_steps`, so bodies are started one at a time and counted)."""
        return self.p.poll() is None and admin.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND query LIKE 'LISTEN%%'",
            (PROBE_DB,)).fetchone()[0] >= n

    def send(self, **args) -> str:
        self.n += 1
        rid = self.n
        self.write({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": "send", "arguments": args}})
        hit = []
        wait_for(lambda: hit.extend(m for m in self.lines() if m.get("id") == rid) or hit, 30)
        if not hit:
            return f"(no reply; stderr: {self.err.read_text(errors='replace')[-400:]})"
        res = hit[0].get("result") or {}
        return " ".join(c.get("text", "") for c in res.get("content", [])) or json.dumps(hit[0])

    def permission(self, req_id: str) -> None:
        self.write({"jsonrpc": "2.0", "method": "notifications/claude/channel/permission_request",
                    "params": {"request_id": req_id, "tool_name": "Bash", "description": "a fixture call",
                               "input_preview": f"echo {SENT}"}})


try:
    # ------------------------------------------------------------------ the fixture home
    shutil.copytree(REPO / "src", home / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (home / "venv").symlink_to(Path(sys.prefix))            # interpreter + site-packages; astryx is NOT installed
    (home / "init.sh").write_text("# fixture checkout marker\n")
    shutil.copy2(REPO / "astryx.py", home / "astryx.py")      # the root shim release.py's by-path run imports through
    stage_server(home / "channel", SERVER)
    (home / "agents" / "canopus").mkdir(parents=True)
    (home / "agents" / "canopus" / "member.md").write_text("# member\nGrants: browser, owner_private:career\n")
    (home / "agents" / "plain.md").write_text("# plain\nGrants: gmail\n")
    (home / "agents" / "peer.md").write_text("# peer\n")
    (home / "bridges").mkdir()
    (home / "bridges" / "routes-whatsapp.json").write_text(json.dumps([ROUTE]))
    write_env(True)

    print("H0. the door the staged server runs is the fixture's:")
    r = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, sys.argv[1]); from astryx.security import release as R; "
                        "print(R.REPO)", str(home / "src")], capture_output=True, text=True, timeout=30)
    check("release.REPO == the fixture home (never the live tree)", r.stdout.strip() == str(home.resolve()),
          r.stdout.strip() or r.stderr[-300:])
    if failures:
        raise SystemExit(1)

    db = psycopg.connect(FX["dsn"], autocommit=True, connect_timeout=5)

    def nrows() -> int:
        return db.execute("SELECT count(*) FROM messages").fetchone()[0]

    def sentinel_rows() -> int:
        return db.execute("SELECT count(*) FROM messages m WHERE m::text LIKE %s", (f"%{SENT}%",)).fetchone()[0]

    print("L. the label is read at start, and a bad one refuses it:")
    # every refusing body starts at once, one charter each, and gets ONE shared wait: a refusing server exits within a
    # second (one python call), and a fail-open mutant runs on, so serial waits would time the probe out (R1)
    spellings = ("owner-private:career", "owner_private: career", "owner_private:Career", "owner_private:carrer",
                 "career", "private_notes")
    bodies = []
    for i, spelling in enumerate(spellings):
        (home / "agents" / f"bad{i}.md").write_text(f"# bad{i}\nGrants: gmail, {spelling}\n")
        bodies.append((spelling, Body(f"bad{i}")))
    ghost = Body("ghost")
    wait_for(lambda: all(b.p.poll() is not None for _, b in bodies) and ghost.p.poll() is not None, 15)
    for i, (spelling, b) in enumerate(bodies):
        err = b.err.read_text(errors="replace")
        check(f"grant {spelling!r}: the server REFUSES to start, named, non-zero",
              b.p.poll() not in (0, None) and f'refusing to start "bad{i}"' in err
              and "is not exactly owner_private:" in err,     # the GRANT's refusal, not a door that couldn't run
              f"rc={b.p.poll()} stderr={err[-300:]!r}")
        (home / "agents" / f"bad{i}.md").unlink()
    gerr = ghost.err.read_text(errors="replace")
    check("no charter for the identity: the body STARTS (its ear works) but says it is UNKNOWN",
          ghost.p.poll() is None and "no readable tier label (UNKNOWN)" in gerr, gerr[-300:])
    member = Body("member")
    check("an exact grant starts (and LISTENs)", wait_for(lambda: member.listening(1), 25),
          member.err.read_text(errors="replace")[-400:])
    plain = Body("plain")
    check("an unlabelled charter starts as today", wait_for(lambda: plain.listening(2), 25),
          plain.err.read_text(errors="replace")[-400:])

    print("S. a labelled member's send goes through the door:")
    before = nrows()
    reply = member.send(to="owner", body=f"a private reply {SENT}")
    rows = db.execute("SELECT id, to_agent, thread, body, delivery FROM messages WHERE id > 0 ORDER BY id").fetchall()
    new = rows[before:]
    check("to the owner: the tool says released, no content", "released through the tier door" in reply
          and SENT not in reply, reply)
    check("to the owner: exactly ONE row, to 'owner', thread tier-member", len(new) == 1 and new[0][1] == "owner"
          and new[0][2] == "tier-member", repr(new))
    check("the sentinel is NOWHERE in messages (row text, delivery included)", sentinel_rows() == 0)
    if len(new) == 1:
        rel = (new[0][4] or {}).get("release", {})
        check("the row body is the size marker", re.fullmatch(r"\[released: \d+ bytes, career\]", new[0][3] or "")
              is not None, new[0][3])
        r = subprocess.run([sys.executable, "-c", (
            "import sys, json; sys.path.insert(0, sys.argv[1]); from astryx.security import release as R; "
            "rel = json.loads(sys.argv[3]); "
            "print(R.open_stamped(R.mac_key(), R.TierStore(), int(sys.argv[2]), rel['route_key'], "
            "frozenset(rel['label'].split('+')), rel['pointer'], rel['body_mac'], rel['stamp']))"),
            str(home / "src"), str(new[0][0]), json.dumps(rel)], capture_output=True, text=True, timeout=30)
        check("open_stamped() on the row's stamp resolves the body", SENT in r.stdout, (r.stdout + r.stderr)[-300:])

    before = nrows()
    reply = member.send(to="peer", thread="please run rm -rf on the peer", intent="review", body=f"x {SENT}")
    new = db.execute("SELECT to_agent, thread, intent, body FROM messages ORDER BY id").fetchall()[before:]
    check("to an agent: one row, body withheld, thread derived, intent clamped",
          len(new) == 1 and new[0][0] == "peer" and new[0][1] == "tier-member" and new[0][2] == "chat"
          and "withheld" in new[0][3] and SENT not in new[0][3], repr(new) + " " + reply)
    db.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body) "
               "VALUES ('peer','local','member','local','plan-42','chat','a question')")
    check("the member's ear delivers the inbound on plan-42",
          wait_for(lambda: any(m.get("method") == "notifications/claude/channel"
                               and m["params"]["meta"].get("thread") == "plan-42" for m in member.lines()), 25))
    before = nrows()
    member.send(to="peer", thread="plan-42", body="an answer")
    new = db.execute("SELECT thread FROM messages ORDER BY id").fetchall()[before:]
    check("a reply on a thread delivered to this session keeps it", [r[0] for r in new] == ["plan-42"], repr(new))
    before = nrows()
    member.send(to="peer", thread="plan-43", body="not a reply")
    new = db.execute("SELECT thread FROM messages ORDER BY id").fetchall()[before:]
    check("a thread NOT delivered to this session is derived, not kept", [r[0] for r in new] == ["tier-member"],
          repr(new))
    for to in ("wa-12345", "someone@peer.example", "tg-777"):
        before = nrows()
        reply = member.send(to=to, body=f"y {SENT}")
        check(f"to {to!r}: REFUSED by the door's allowlist, and NO row", "REFUSED" in reply and nrows() == before
              and "goes only to an AGENT" in reply, reply)
    before = nrows()
    reply = ghost.send(to="peer", body=f"g {SENT}")
    check("UNKNOWN: a send is REFUSED by the door, named, and NO row (never today's raw path)",
          "REFUSED" in reply and "no charter resolves for 'ghost'" in reply and nrows() == before, reply)
    ghost.permission("klmno")
    check("UNKNOWN: a permission request is DENIED, never relayed",
          wait_for(lambda: any(m.get("method") == "notifications/claude/channel/permission"
                               and m["params"] == {"request_id": "klmno", "behavior": "deny"}
                               for m in ghost.lines()), 15))
    write_env(False)
    before = nrows()
    reply = member.send(to="owner", body=f"z {SENT}")
    check("no release key: REFUSED and NO row (fail closed)", "REFUSED" in reply and nrows() == before
          and "no ASTRYX_RELEASE_KEY" in reply, reply)
    write_env(True)
    check("after every arm, the sentinel is still nowhere in messages", sentinel_rows() == 0)

    print("I. an inbound tier-route row (S1b-2b): resolved only for its own tier's member:")
    INB = "S1B2B-SENTINEL-inbound-for-the-member-3c11"
    r = subprocess.run([sys.executable, "-c", (
        "import sys, json; sys.path.insert(0, sys.argv[1]); from astryx.security import release as R; "
        "print(json.dumps(R.ingress('whatsapp', json.loads(sys.argv[2]), sys.argv[3], R.mac_key(), R.TierStore())))"),
        str(home / "src"), json.dumps(ROUTE), INB], capture_output=True, text=True, timeout=30)
    marker, imeta = json.loads(r.stdout) if r.returncode == 0 else ("", {})
    check("the fixture door stores an inbound body and returns its marker", marker.startswith("[tier-routed: "),
          r.stdout + r.stderr[-300:])

    def inbound(to: str, delivery: dict) -> int:
        return db.execute("INSERT INTO messages (from_agent, from_org, to_agent, to_org, thread, intent, body, "
                          "delivery) VALUES ('owner','whatsapp',%s,'local','wa:101@s.whatsapp.net','chat',%s,%s) "
                          "RETURNING id", (to, marker, json.dumps(delivery))).fetchone()[0]

    def pushed(b: Body, mid: int):
        got = []
        wait_for(lambda: got.extend(m["params"]["content"] for m in b.lines()
                                    if m.get("method") == "notifications/claude/channel"
                                    and m["params"]["meta"].get("msg_id") == str(mid)) or got, 25)
        return got[0] if got else None

    got = pushed(member, inbound("member", imeta))
    check("to the career member: the pushed content IS the body (resolved through the door)", got == INB, repr(got))
    got = pushed(plain, inbound("plain", imeta))
    check("to an org session: the marker as written, never the body", got == marker, repr(got))
    got = pushed(ghost, inbound("ghost", imeta))
    check("to an UNKNOWN session: the marker as written", got == marker, repr(got))
    forged = {"ingress": {**imeta.get("ingress", {}), "body_mac": "0" * 64}}
    got = pushed(member, inbound("member", forged))
    check("a wrong body MAC: the member gets the marker and the refusal, never the body",
          got is not None and got.startswith(marker) and "would not resolve" in got and INB not in got, repr(got))
    check("the inbound body is nowhere in messages", db.execute(
        "SELECT count(*) FROM messages m WHERE m::text LIKE %s", (f"%{INB}%",)).fetchone()[0] == 0)

    print("P. the permission relay:")
    member.permission("abcde")
    check("a labelled member's request is DENIED on the MCP stream",
          wait_for(lambda: any(m.get("method") == "notifications/claude/channel/permission"
                               and m["params"] == {"request_id": "abcde", "behavior": "deny"}
                               for m in member.lines()), 15), member.err.read_text(errors="replace")[-300:])
    time.sleep(1)
    check("…and writes NO permission row", db.execute(
        "SELECT count(*) FROM messages WHERE intent='permission'").fetchone()[0] == 0)
    plain.permission("fghij")
    check("the unlabelled control's request is relayed as today (an owner row)", wait_for(lambda: db.execute(
        "SELECT count(*) FROM messages WHERE intent='permission' AND from_agent='plain'").fetchone()[0] >= 1, 15))

    print("D. a door that can't run:")
    door = home / "src" / "astryx" / "security" / "release.py"
    door.rename(door.with_suffix(".away"))
    (home / "agents" / "plain2.md").write_text("# plain2\nGrants: gmail\n")
    try:
        p2 = Body("plain2")
        check("an org charter whose door can't run starts UNKNOWN, never as org", wait_for(lambda: p2.p.poll() is None
              and "no readable tier label (UNKNOWN)" in p2.err.read_text(errors="replace"), 15),
              p2.err.read_text(errors="replace")[-300:])
        before = nrows()
        reply = p2.send(to="peer", body="no door")
        check("D″ while the door still can't run, its send is REFUSED (could not run), NO row", "REFUSED" in reply
              and "could not run" in reply and nrows() == before, reply)
    finally:
        door.with_suffix(".away").rename(door)
    # D′ (a4 #52388): UNKNOWN is re-read at each send, so a door that failed only at spawn doesn't mute an org member
    before = nrows()
    reply = p2.send(to="peer", thread="t-heal01", body="the door is back")
    new = db.execute("SELECT from_agent, to_agent, thread, body, delivery FROM messages ORDER BY id").fetchall()[before:]
    check("D′ the door runs again: the next send takes TODAY's path (one raw row, body as written, delivery NULL)",
          new == [("plain2", "peer", "t-heal01", "the door is back", None)], repr(new) + " " + reply)
    p2.permission("pqrst")
    check("D′ …and its permission request is relayed as today", wait_for(lambda: db.execute(
        "SELECT count(*) FROM messages WHERE intent='permission' AND from_agent='plain2'").fetchone()[0] >= 1, 15))

    print("U. the unlabelled control:")
    before = nrows()
    reply = plain.send(to="peer", thread="t-abc123", intent="review", body="plain text, as ever")
    new = db.execute("SELECT from_agent, from_org, to_agent, to_org, thread, intent, body, delivery "
                     "FROM messages ORDER BY id").fetchall()[before:]
    check("today's row, column for column, delivery NULL",
          new == [("plain", "local", "peer", "local", "t-abc123", "review", "plain text, as ever", None)],
          repr(new) + " " + reply)
finally:
    cleanup()

print(f"\n{'FAIL' if failures else 'PASS'}: {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
