"""The ear must outlive a database blip.

WHY THIS FILE EXISTS. On 2026-08-14 the org restarted its own postgres container to
load Apache AGE (a clean, deliberate `docker restart`: RestartCount=0, ExitCode=0,
"database system was shut down at 12:40:42 UTC"). Twenty-two LISTEN connections
reconnected two seconds later. FORGE's did not — its channel/server.mjs process was
gone, and forge was deaf for 8h49m while its tmux pane sat at a healthy prompt and
every message addressed to it queued `pending` in the table.

That is the FOURTH liveness state — body alive, turns possible, EAR GONE — and it is
invisible to both existing watchers by construction: agent_dark sees a live body, and
wedge_watch's subjects are DELIVERED rows, which these never become. Detection can only
ever be sender-side and after the fact. This file is the other half: the ear should not
die in the first place.

Two ways it died, both proven on node v26.2.0 against this repo's own pg:
  A. pg.Pool emits 'error' when a POOLED-BUT-IDLE client's backend goes away. A
     postgres restart sends every open backend 57P01 ("terminating connection due to
     administrator command"). An EventEmitter 'error' with no listener is an uncaught
     exception -> exit(1).
  B. an async function handed straight to setInterval has nowhere to put a rejection,
     and node's default for an unhandled rejection is exit(1). refreshSubs queries the
     pool once a minute, forever, so every minute the database is unreachable is a coin
     flip on the ear.

WHAT THIS TEST IS, AND WHAT IT REFUSES TO BE. It runs the REAL channel/server.mjs
(copied byte-for-byte at test time) against a THROWAWAY database, proves the ear works,
breaks the database underneath it in each of the two ways, and proves the ear both
survived and still delivers. It is behavioural, not a source grep: a grep for
`pool.on('error'` would pass on a commented-out line, and the org has been bitten by a
check that read prose as code before.

The instrument checks itself. Each fault must leave POSITIVE evidence on stderr that it
actually landed on the code path under test. If a fault never reaches the path (a staging
race, a vanished test seam), the case verified NOTHING and this exits 77 (SKIP) rather
than reporting the survival as a pass -- a fault that missed is not a fix that worked.

Run: venv/bin/python tests/test_ear_survival.py   (also wired into nucleus/check.sh)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# CHANNEL_SERVER_SRC is nucleus/mutation_probe.py's channel for handing this oracle a
# deliberately-broken copy; the default is always the real file. It selects the SUBJECT,
# never the axis — every fault below is injected explicitly, per case, by this file.
SERVER = Path(os.environ.get("CHANNEL_SERVER_SRC", REPO / "channel" / "server.mjs"))
PROBE_AGENT = "earprobe"


def skip(why: str) -> None:
    print(f"SKIP: {why}. Nothing was verified here.")
    sys.exit(77)


def fail(why: str) -> None:
    print(f"FAIL: {why}")
    sys.exit(1)


# ---------------------------------------------------------------- prerequisites
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


if not SERVER.exists():
    skip("channel/server.mjs is absent — nothing to test")
NODE = node_bin()
if not NODE:
    skip("no node binary (nucleus/spawn.sh NODE= is absent and node is not on PATH)")
if not (REPO / "channel" / "node_modules" / "pg").is_dir():
    skip("channel/node_modules/pg is absent (a fresh clone: run npm install in channel/)")
ADMIN_DSN = dsn()
if not ADMIN_DSN:
    skip("no ASTRYX_DSN (env or .env) — no database to blip")
SCHEMA = REPO / "nucleus" / "schema.sql"
if not SCHEMA.exists():
    skip("nucleus/schema.sql is absent — cannot build a throwaway database")

try:
    admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=5)
except Exception as e:                                          # noqa: BLE001
    skip(f"database unreachable ({type(e).__name__}) — no substrate to break")

row = admin.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles "
                    "WHERE rolname = current_user").fetchone()
if not row or not row[0]:
    admin.close()
    skip("this role cannot CREATE DATABASE — a throwaway is the only safe substrate "
         "(this test never touches the org's own database)")

PROBE_DB = f"astryx_earprobe_{os.getpid()}"
PROBE_DSN = re.sub(r"/[^/?]+(\?|$)", f"/{PROBE_DB}\\1", ADMIN_DSN, count=1)
if PROBE_DB not in PROBE_DSN:
    admin.close()
    skip("could not derive a throwaway DSN from ASTRYX_DSN (unexpected shape)")

stage = Path(tempfile.mkdtemp(prefix="ear-survival-"))
proc = None
cases: list[tuple[str, str]] = []          # (name, verdict) verdict in pass/skip


def cleanup() -> None:
    if proc and proc.poll() is None:
        proc.kill()
        proc.wait(timeout=10)
    try:
        admin.execute(f'DROP DATABASE IF EXISTS "{PROBE_DB}" WITH (FORCE)')
    except Exception:                                           # noqa: BLE001
        pass
    admin.close()
    shutil.rmtree(stage, ignore_errors=True)


def stderr_text() -> str:
    return (stage / "stderr.log").read_text(errors="replace")


def wait_for(predicate, timeout: float, tick: float = 0.2) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(tick)
    return False


def deliver_probe(db, body: str, timeout: float = 25.0) -> bool:
    """Insert a pending message for the probe agent; did the ear mark it delivered?"""
    mid = db.execute(
        "INSERT INTO messages (from_agent, from_org, to_agent, to_org, intent, body, status) "
        "VALUES ('probe','local',%s,'local','chat',%s,'pending') RETURNING id",
        (PROBE_AGENT, body)).fetchone()[0]
    return wait_for(
        lambda: db.execute("SELECT status FROM messages WHERE id=%s", (mid,)).fetchone()[0]
        == "delivered", timeout)


def kill_backends() -> int:
    """Exactly what a postgres restart does to every open connection: 57P01."""
    return admin.execute(
        "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()", (PROBE_DB,)).fetchone()[0]


try:
    # ------------------------------------------------------ throwaway substrate
    admin.execute(f'CREATE DATABASE "{PROBE_DB}"')
    subprocess.run([sys.executable, "-c", "import sys,psycopg;"
                    "psycopg.connect(sys.argv[1],autocommit=True).execute(open(sys.argv[2]).read())",
                    PROBE_DSN, str(SCHEMA)], check=True, capture_output=True, timeout=120)

    # The server resolves its DSN as ../.env relative to its own file and its imports
    # from the nearest node_modules, so a staged copy needs both — and staging it
    # OUTSIDE the repo is the point: a test that writes into channel/ to test channel/
    # can leave a live DSN behind when it dies.
    (stage / "channel").mkdir()
    shutil.copy2(SERVER, stage / "channel" / "server.mjs")
    (stage / "channel" / "node_modules").symlink_to(REPO / "channel" / "node_modules")
    (stage / ".env").write_text(f"ASTRYX_DSN={PROBE_DSN}\n")

    env = {**os.environ, "ASTRYX_AGENT": PROBE_AGENT, "ASTRYX_DSN": PROBE_DSN,
           "ASTRYX_SUBS_REFRESH_MS": "500"}     # the seam that makes case B testable
    with open(stage / "stdout.log", "wb") as out, open(stage / "stderr.log", "wb") as err:
        proc = subprocess.Popen([NODE, str(stage / "channel" / "server.mjs")],
                                cwd=stage, env=env, stdin=subprocess.PIPE,
                                stdout=out, stderr=err)
    spawned = time.monotonic()

    db = psycopg.connect(PROBE_DSN, autocommit=True, connect_timeout=5)

    # ---------------------------------------------- 0. the instrument itself works
    # Without this the whole file is vacuous: a server that never started also never
    # crashes, and every survival case below would pass on a corpse.
    if not wait_for(lambda: admin.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND query LIKE 'LISTEN%%'",
            (PROBE_DB,)).fetchone()[0] >= 1, 20):
        fail(f"the probe server never LISTENed — stderr:\n{stderr_text()[:2000]}")
    if not deliver_probe(db, "pre-fault: does the ear work at all?"):
        fail(f"the ear never delivered before any fault was injected; the test proves "
             f"nothing about survival — stderr:\n{stderr_text()[:2000]}")
    print("  ✓ the probe ear starts, listens, and delivers (the instrument is live)")

    # ------------------------------- A. an idle pooled client's backend is killed
    # deliver_probe just used the pool, so a client is idle in it now (pg-pool's
    # default idleTimeoutMillis is 10s — the window is real but not generous).
    if kill_backends() < 1:
        fail("no probe backends to terminate — the fault could not be injected")
    time.sleep(2.0)
    if proc.poll() is not None:
        fail(f"THE EAR DIED when an idle pooled client's backend went away "
             f"(exit {proc.returncode}). This is the 2026-08-14 outage, reproduced. "
             f"stderr:\n{stderr_text()[:3000]}")
    if "pool" in stderr_text().lower():
        cases.append(("A: idle pooled client killed", "pass"))
        print("  ✓ pool client death is caught and discarded, the ear lives")
    else:
        cases.append(("A: idle pooled client killed", "skip"))
        print("  ○ the pool never noticed the terminated backend (no idle client at "
              "the moment of the fault) — case A VERIFIED NOTHING this run")

    # ---------------------------------- B. the database is unreachable for a moment
    # A restarting postgres refuses connections for a second or two. refreshSubs runs
    # on a timer against the pool and cannot be told to wait.
    admin.execute(f'ALTER DATABASE "{PROBE_DB}" WITH ALLOW_CONNECTIONS false')
    db.close()
    kill_backends()
    time.sleep(3.0)
    outage_err = stderr_text()
    admin.execute(f'ALTER DATABASE "{PROBE_DB}" WITH ALLOW_CONNECTIONS true')
    if proc.poll() is not None:
        fail(f"THE EAR DIED while the database was briefly unreachable "
             f"(exit {proc.returncode}) — an unhandled rejection from the subscription "
             f"refresh. stderr:\n{outage_err[:3000]}")
    if re.search(r"refresh", outage_err, re.I):
        cases.append(("B: database unreachable", "pass"))
        print("  ✓ a failed subscription refresh is survivable, the ear lives")
    else:
        cases.append(("B: database unreachable", "skip"))
        print("  ○ no subscription refresh was attempted during the outage window "
              "(ASTRYX_SUBS_REFRESH_MS seam gone?) — case B VERIFIED NOTHING this run")

    # --------------------------------------------- C. and it still WORKS afterwards
    # Surviving is not the promise; hearing is. A process that is alive but whose pool
    # and listener are both poisoned is a WEDGED ear, which is worse than a dead one:
    # nothing downstream can tell it apart from a healthy one.
    #
    # Wait out the startup drain first. server.mjs sweeps `pending` once, 15s after it
    # connects, to catch anything that arrived while it was down — and that one-shot
    # delivers this message too if we ask early enough. The mutant that swallows the
    # LISTEN client's error without redialling (a permanently deaf ear) passed this case
    # on exactly that timing, and mutation_probe caught it. Anything delivered after the
    # drain window had to be rung for.
    time.sleep(max(0.0, 20.0 - (time.monotonic() - spawned)))
    db = psycopg.connect(PROBE_DSN, autocommit=True, connect_timeout=5)
    if not deliver_probe(db, "post-fault: is the ear still an ear?", timeout=30.0):
        fail(f"the ear survived both faults but stopped delivering — a WEDGED ear, "
             f"which is worse than a dead one. stderr:\n{stderr_text()[:3000]}")
    cases.append(("C: still delivers after the blips", "pass"))
    print("  ✓ the ear still delivers after the database came back")
    db.close()

finally:
    cleanup()

# ------------------------------------------------------------------- the verdict
# The aggregate may not out-claim its parts (check.sh, 08-14): if a fault never landed,
# this run did not verify the fix, and saying so is the whole point.
unverified = [n for n, v in cases if v == "skip"]
if unverified:
    print("SKIP: the following faults never reached the code path they test, so this "
          "run proves nothing about them: " + "; ".join(unverified))
    sys.exit(77)
print(f"\n{len(cases)}/{len(cases)} passed — the ear survives a database blip and "
      f"still hears afterwards")
