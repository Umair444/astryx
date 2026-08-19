"""A wake delivered into a void must be recovered — and nothing else may be.

WHY THIS FILE EXISTS. `messages.status='delivered'` is written by the EAR, not by the
body: channel/server.mjs flips the row the instant it pushes the MCP notification, long
before any turn has read a word of it. The startup drain only ever sweeps `pending`, so a
message claimed by a body that then dies is never offered to anything again. The drain's
own comment has named this since it was written ("marked delivered into a void") — the
15s delay covers the boot race, not the death of the previous body.

Measured 2026-08-15 across 21 days of the org's own tables, under the strict predicate
below: 69 messages provably reached no turn and no step before their agent's next boot.
A single roster-wide respawn at 07:37Z on 08-15 ate the 04:00Z heartbeat of NINE agents
at once; two of steward's losses were guard alarms (pii_sweep, outbound_stuck), so a
detector fired and the restart threw the finding away. And the org's prescribed remedy
for a WEDGED agent — kill-session then spawn (triggers/seed/wedge_watch.py) — is exactly
the act that destroys the wakes that proved the wedge.

WHAT THIS TEST IS. It runs the REAL channel/server.mjs against a THROWAWAY database with
a hand-built fixture, and checks BOTH directions of the predicate, because a recovery
that fires on everything is not a fix, it is a duplicate-message generator:

  R1  a wake with no turn and no step after it  -> RECOVERED, and the body's notification
      says so (the marker is checked on the wire, not inferred from the row)
  R2  a wake covered by a turn that ended after it            -> LEFT ALONE
  R3  a wake covered by a step after it (a turn killed mid-flight writes no turn row,
      because turns.ended_at is NOT NULL and rows are INSERTed at turn END)  -> LEFT ALONE
  R4  a wake already recovered RECOVERY_TRIES times           -> LEFT ALONE
  R5  a wake this very process delivered seconds ago          -> LEFT ALONE
  R6  the age window, proved in both directions in one run: inside -> recovered,
      outside -> left alone, so a server that silently did nothing cannot pass it

EVERY NEGATIVE CASE CARRIES A POSITIVE CONTROL IN THE SAME GENERATION, because "was not
recovered" is also what a server that never started, never connected, or crashed on boot
produces. R1 controls gen1, R3a controls gen2, R6a controls gen3.

THREE GENERATIONS, ONE DISCRIMINATOR EACH. Both evidence clauses mean "anything newer
than this message", so they overlap: a step at T covers every wake older than T whatever
the turns say. A fixture holding both kinds at once isolates neither — the first draft of
this file did exactly that, and mutation_probe deleted the turns clause from the server
without failing a single assertion. Each generation now carries only the evidence its own
case needs, and the one before it is cleared away.

TWO INSTRUMENTS, DIFFERENT MEDIA. The row state (postgres) and the notification stream
(the MCP stdout the body actually reads) are read independently and must agree. A row
that flips to `pending` and back proves the SQL ran; only the notification proves the
body was handed anything. Neither alone is the promise.

The instrument checks itself: if the ear never delivers at all, or the MCP transport
hands back nothing to read, this exits 77 (SKIP) rather than reporting the absence of
wrong deliveries as a pass. An unread channel and a correct one look identical to a
test that only asserts what did NOT arrive.

Run: venv/bin/python nucleus/test_wake_recovery.py   (wire into nucleus/check.sh)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Selects the SUBJECT (mutation_probe hands this oracle deliberately-broken copies);
# it never selects the axis — every fixture below is built explicitly by this file.
SERVER = Path(os.environ.get("CHANNEL_SERVER_SRC", REPO / "channel" / "server.mjs"))
PROBE_AGENT = "wakeprobe"
DRAIN_WAIT = 32.0          # the server's own drain is a one-shot at 15s


def skip(why: str) -> None:
    print(f"SKIP: {why}. Nothing was verified here.")
    sys.exit(77)


def fail(why: str) -> None:
    print(f"FAIL: {why}")
    sys.exit(1)


try:
    import psycopg
except ModuleNotFoundError:
    skip("psycopg not importable (run with venv/bin/python)")


def dsn() -> str | None:
    if os.environ.get("ASTRYX_DSN"):
        return os.environ["ASTRYX_DSN"].strip()
    env = REPO / ".env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("ASTRYX_DSN="):
            return line[len("ASTRYX_DSN="):].strip().strip('"').strip("'")
    return None


def node_bin() -> str | None:
    """The node the org actually spawns agents with, not whatever is first on PATH."""
    spawn = REPO / "nucleus" / "spawn.sh"
    if spawn.exists():
        m = re.search(r"^NODE=(\S+)", spawn.read_text(), re.M)
        if m and Path(m.group(1)).is_file():
            return m.group(1)
    return shutil.which("node")


# ---------------------------------------------------------------- prerequisites
if not SERVER.exists():
    skip("channel/server.mjs is absent — nothing to test")
NODE = node_bin()
if not NODE:
    skip("no node binary (nucleus/spawn.sh NODE= is absent and node is not on PATH)")
if not (REPO / "channel" / "node_modules" / "pg").is_dir():
    skip("channel/node_modules/pg is absent (a fresh clone: run npm install in channel/)")
ADMIN_DSN = dsn()
if not ADMIN_DSN:
    skip("no ASTRYX_DSN (env or .env) — no database to build a fixture in")
SCHEMA = REPO / "nucleus" / "schema.sql"
if not SCHEMA.exists():
    skip("nucleus/schema.sql is absent — cannot build a throwaway database")

try:
    admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=5)
except Exception as e:                                          # noqa: BLE001
    skip(f"database unreachable ({type(e).__name__}) — no substrate")

row = admin.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles "
                    "WHERE rolname = current_user").fetchone()
if not row or not row[0]:
    admin.close()
    skip("this role cannot CREATE DATABASE — a throwaway is the only safe substrate "
         "(this test never touches the org's own database)")

PROBE_DB = f"astryx_wakeprobe_{os.getpid()}"
PROBE_DSN = re.sub(r"/[^/?]+(\?|$)", f"/{PROBE_DB}\\1", ADMIN_DSN, count=1)
if PROBE_DB not in PROBE_DSN:
    admin.close()
    skip("could not derive a throwaway DSN from ASTRYX_DSN (unexpected shape)")

stage = Path(tempfile.mkdtemp(prefix="wake-recovery-"))
procs: list[subprocess.Popen] = []
failures: list[str] = []


def cleanup() -> None:
    for p in procs:
        if p.poll() is None:
            p.kill()
            try:
                p.wait(timeout=10)
            except Exception:                                   # noqa: BLE001
                pass
    try:
        admin.execute(f'DROP DATABASE IF EXISTS "{PROBE_DB}" WITH (FORCE)')
    except Exception:                                           # noqa: BLE001
        pass
    admin.close()
    shutil.rmtree(stage, ignore_errors=True)


def wait_for(predicate, timeout: float, tick: float = 0.25) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(tick)
    return False


def start_server(tag: str, **env_extra) -> tuple[subprocess.Popen, Path]:
    """The real server, on a staged copy, with a real MCP client handshake.

    The handshake matters: without an initialised transport the notification stream
    this test reads as its second instrument may never be written, and the whole
    both-directions argument would rest on row state alone.
    """
    d = stage / tag
    (d / "channel").mkdir(parents=True)
    shutil.copy2(SERVER, d / "channel" / "server.mjs")
    (d / "channel" / "node_modules").symlink_to(REPO / "channel" / "node_modules")
    (d / ".env").write_text(f"ASTRYX_DSN={PROBE_DSN}\n")
    env = {**os.environ, "ASTRYX_AGENT": PROBE_AGENT, "ASTRYX_DSN": PROBE_DSN,
           "ASTRYX_SUBS_REFRESH_MS": "60000", **env_extra}
    out = d / "stdout.log"
    with open(out, "wb") as o, open(d / "stderr.log", "wb") as e:
        p = subprocess.Popen([NODE, str(d / "channel" / "server.mjs")], cwd=d, env=env,
                             stdin=subprocess.PIPE, stdout=o, stderr=e)
    procs.append(p)
    p.stdin.write((json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "wake-recovery-probe", "version": "0"}}}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
    ).encode())
    p.stdin.flush()
    return p, d


def channel_pushes(d: Path) -> list[dict]:
    """Every channel notification the server handed the body, in order."""
    got = []
    for line in (d / "stdout.log").read_text(errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("method") == "notifications/claude/channel":
            got.append(msg.get("params", {}))
    return got


def check(name: str, ok: bool, detail: str) -> None:
    if ok:
        print(f"  ✓ {name}")
    else:
        failures.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


try:
    # ------------------------------------------------------ throwaway substrate
    admin.execute(f'CREATE DATABASE "{PROBE_DB}"')
    subprocess.run([sys.executable, "-c", "import sys,psycopg;"
                    "psycopg.connect(sys.argv[1],autocommit=True).execute(open(sys.argv[2]).read())",
                    PROBE_DSN, str(SCHEMA)], check=True, capture_output=True, timeout=120)
    db = psycopg.connect(PROBE_DSN, autocommit=True, connect_timeout=5)

    def wake(body: str, ago_minutes: float, delivery: str | None = None) -> int:
        """A message already marked delivered N minutes ago — i.e. into a void."""
        return db.execute(
            "INSERT INTO messages (from_agent, from_org, to_agent, to_org, intent, body, "
            "status, ts, delivered_at, delivery) VALUES "
            "('pulse','local',%s,'local','trigger',%s,'delivered', "
            " now() - make_interval(mins => %s), now() - make_interval(mins => %s), %s::jsonb) "
            "RETURNING id", (PROBE_AGENT, body, ago_minutes, ago_minutes, delivery)
        ).fetchone()[0]

    def evidence_turn(start_ago: float, end_ago: float) -> None:
        db.execute("INSERT INTO turns (agent, started_at, ended_at, source) VALUES "
                   "(%s, now() - make_interval(mins => %s), now() - make_interval(mins => %s), "
                   "'probe')", (PROBE_AGENT, start_ago, end_ago))

    def evidence_step(ago: float) -> None:
        db.execute("INSERT INTO steps (agent, kind, content, ts) VALUES "
                   "(%s,'response','a turn that never finished', now() - make_interval(mins => %s))",
                   (PROBE_AGENT, ago))

    # ONE DISCRIMINATOR PER CASE, and it takes three generations to get it. Both evidence
    # clauses are "anything newer than the message", so they overlap: a step at T covers
    # every wake older than T no matter what the turns say, and vice versa. A fixture with
    # both kinds of evidence on one timeline cannot isolate either — the first draft of
    # this file put them together and mutation_probe proved it, deleting the turns clause
    # from the server without failing a single assertion. So each generation carries only
    # the evidence its own case needs, and the previous generation's is cleared away.
    evidence_turn(start_ago=600, end_ago=540)     # a turn spanning T-10h .. T-9h
    m_turn = wake("covered by a turn that outlived it", 570)   # T-9h30m, inside the turn
    m_lost = wake("nobody was ever home for this one", 120)    # T-2h, no evidence at all
    m_maxed = wake("already recovered three times", 60, '{"recovered": 3}')

    # ------------------------------------------------------------- generation 1
    proc, d1 = start_server("gen1")
    if not wait_for(lambda: admin.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND query LIKE 'LISTEN%%'",
            (PROBE_DB,)).fetchone()[0] >= 1, 20):
        fail(f"the probe server never LISTENed — stderr:\n"
             f"{(d1 / 'stderr.log').read_text(errors='replace')[:2000]}")

    # R5's fixture and the instrument in one: a message this process delivers itself,
    # seconds before its own recovery pass runs. If the predicate forgot to exclude
    # deliveries newer than boot, this is the row that would be recovered.
    m_now = db.execute(
        "INSERT INTO messages (from_agent, from_org, to_agent, to_org, intent, body, status) "
        "VALUES ('probe','local',%s,'local','chat','a live delivery, not a lost one','pending') "
        "RETURNING id", (PROBE_AGENT,)).fetchone()[0]
    if not wait_for(lambda: db.execute("SELECT status FROM messages WHERE id=%s",
                                       (m_now,)).fetchone()[0] == "delivered", 25):
        fail(f"the ear never delivered a plain pending message; nothing below would mean "
             f"anything — stderr:\n{(d1 / 'stderr.log').read_text(errors='replace')[:2000]}")

    time.sleep(DRAIN_WAIT)      # let the one-shot drain (15s) run and settle
    pushes = channel_pushes(d1)
    if not pushes:
        skip("the MCP notification stream is empty even for a delivery the row state "
             "confirms — this test's second instrument is not reading anything, so the "
             "'left alone' cases would pass on an unread channel")

    def recovered(mid: int) -> int:
        r = db.execute("SELECT coalesce((delivery->>'recovered')::int, 0), status "
                       "FROM messages WHERE id=%s", (mid,)).fetchone()
        return r[0]

    def pushed(mid: int) -> list[dict]:
        return [p for p in pushes if p.get("meta", {}).get("msg_id") == str(mid)]

    print("gen1 — recovery window 12h (default):")
    lost_pushes = pushed(m_lost)
    check("R1 a provably-unread wake comes back",
          recovered(m_lost) == 1 and len(lost_pushes) == 1,
          f"recovered={recovered(m_lost)} pushes={len(lost_pushes)} — a wake nobody could "
          f"have read stayed lost")
    if lost_pushes:
        content = lost_pushes[0].get("content", "")
        check("R1b the body is told it is a redelivery, with the original send time",
              content.startswith("[redelivered wake · sent ")
              and lost_pushes[0].get("meta", {}).get("redelivered") == "1",
              f"content began {content[:80]!r}, meta={lost_pushes[0].get('meta')} — a "
              f"recovered wake that reads as fresh is a lie about when it was sent")
    check("R2 a wake a turn outlived is left alone",
          recovered(m_turn) == 0 and not pushed(m_turn),
          f"recovered={recovered(m_turn)} pushes={len(pushed(m_turn))} — duplicated a "
          f"message a finished turn may well have read")
    # Its counter starts AT the cap, so the assertion is "did not advance", not "is zero".
    check("R4 a wake already recovered 3 times is left alone",
          recovered(m_maxed) == 3 and not pushed(m_maxed),
          f"recovered={recovered(m_maxed)} (fixture set it to 3) pushes="
          f"{len(pushed(m_maxed))} — a permanently wedged agent would be re-served the "
          f"same message at every respawn forever")
    check("R5 a delivery from this very session is not 'recovered' from itself",
          recovered(m_now) == 0 and len(pushed(m_now)) == 1,
          f"recovered={recovered(m_now)} pushes={len(pushed(m_now))} — the predicate has "
          f"no boot boundary, so every fresh delivery is a recovery candidate")

    proc.kill(); proc.wait(timeout=10)

    # ------------------------------------------------------------- generation 2
    # Step evidence, alone. Every case here is newer than gen1's turn (which ended T-9h),
    # so the turns clause cannot be what leaves anything alone.
    evidence_step(ago=40)                                       # a lone step at T-40m
    m_step = wake("covered by a step after it", 50)             # T-50m, before that step
    m_ctl = wake("newer than the step — the positive control", 20)
    proc2, d2 = start_server("gen2")
    if not wait_for(lambda: admin.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND query LIKE 'LISTEN%%'",
            (PROBE_DB,)).fetchone()[0] >= 1, 20):
        fail(f"the second probe server never LISTENed — stderr:\n"
             f"{(d2 / 'stderr.log').read_text(errors='replace')[:2000]}")
    time.sleep(DRAIN_WAIT)
    pushes = channel_pushes(d2)

    print("gen2 — step evidence only:")
    check("R3a a wake newer than every step still comes back (the pass ran)",
          recovered(m_ctl) == 1 and len(pushed(m_ctl)) == 1,
          f"recovered={recovered(m_ctl)} pushes={len(pushed(m_ctl))} — nothing was "
          f"recovered at all, so R3b below proves nothing")
    check("R3b a wake a later step covers is left alone",
          recovered(m_step) == 0 and not pushed(m_step),
          f"recovered={recovered(m_step)} pushes={len(pushed(m_step))} — a step after "
          f"delivery is a body that was awake; 'may have read it' is not proof it didn't")
    proc2.kill(); proc2.wait(timeout=10)

    # ------------------------------------------------------------- generation 3
    # The window, both directions in one run — and the step evidence must GO first, or it
    # would cover the outside-the-window row for a second reason and M6 would walk free.
    # A negative case alone is worthless here anyway: a server that crashed on boot also
    # recovers nothing and would pass "outside the window is left alone" perfectly.
    db.execute("DELETE FROM steps WHERE agent = %s", (PROBE_AGENT,))
    m_in = wake("30 minutes old — inside a 1h window", 30)
    m_out = wake("3 hours old — outside a 1h window", 180)
    proc3, d3 = start_server("gen3", ASTRYX_WAKE_RECOVERY_HOURS="1")
    if not wait_for(lambda: admin.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND query LIKE 'LISTEN%%'",
            (PROBE_DB,)).fetchone()[0] >= 1, 20):
        fail(f"the third probe server never LISTENed — stderr:\n"
             f"{(d3 / 'stderr.log').read_text(errors='replace')[:2000]}")
    time.sleep(DRAIN_WAIT)
    pushes = channel_pushes(d3)

    print("gen3 — recovery window forced to 1h:")
    check("R6a inside the window: recovered (the pass demonstrably ran)",
          recovered(m_in) == 1 and len(pushed(m_in)) == 1,
          f"recovered={recovered(m_in)} pushes={len(pushed(m_in))} — nothing was recovered "
          f"at all, so R6b below proves nothing")
    check("R6b outside the window: left alone",
          recovered(m_out) == 0 and not pushed(m_out),
          f"recovered={recovered(m_out)} — ASTRYX_WAKE_RECOVERY_HOURS does not bound "
          f"anything; a stale wake is redelivered days late")
    proc3.kill(); proc3.wait(timeout=10)
    db.close()

finally:
    cleanup()

# ------------------------------------------------------------------- the verdict
if failures:
    print("\nFAIL — a wake delivered into a void is still lost, or a wake that was read "
          "is being served twice:")
    for f in failures:
        print(f"  ✗ {f}")
    sys.exit(1)
print("\n9/9 passed — provably-unread wakes are recovered at spawn, marked as "
      "redeliveries, and nothing a turn or a step could have covered is served twice")
