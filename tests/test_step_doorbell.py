#!/usr/bin/env python3
"""Oracle: a steps doorbell resolves only to a step OF THE AGENT IT NAMES (a4 #22117).

    venv/bin/python tests/test_step_doorbell.py        (also run by nucleus/check.sh)
    CHANNEL_SERVER_SRC=<path> / STEP_LINE_SRC=<path>   (the subjects; mutation_probe sets one)

The payload on `astryx_steps` is {id, agent, kind}. Both consumers matched the SUBSCRIPTION (or
the progress job) on the payload's agent, then fetched the row by id ALONE. So a payload whose
id names another agent's step pushed THAT step's content under a subscription to someone else.
Anyone who can pg_notify can forge one (same-uid, like every wire row), so this is defense in
depth, graded as such.

  C1 channel/server.mjs (the REAL server, against a THROWAWAY database, the ear-survival
     harness): a real step of the subscribed agent is pushed (positive control); a forged
     payload {id: <another agent's step>, agent: <the subscribed agent>} pushes NOTHING; and a
     second real step pushed AFTER the forgery arrives. That last one proves the ear was
     listening throughout, so the silence came from the fix and not from a dead server.
  C2 an empty agent in the payload pushes nothing, even against a real step whose agent IS ''
     and a subscription whose target IS ''. steps.agent is NOT NULL but admits ''. So without
     this fixture, "SQL agent='' matches nothing" would be true only of today's DATA, and the
     early return would be unpinned (abstractor-4's note on 9c1b729).
  B1 bridges/common.py step_line, through a real asyncpg pool on the same throwaway DB: the
     right agent gets the line, the wrong agent gets None, and "" gets None (the label
     default must never be a match key).
  B2 step_line's `agent` is a REQUIRED keyword, and every step_line call in bridges/ passes
     `agent=` (AST: a call can't silently fall back to matching "").

THE DATABASE is sqlguard's stamped fixture (nucleus/sqlguard/fixture.py, the ONE applier), not a
hand-built one: an unstamped relation caps every site at FIXTURE-DDL, so step_line's owner-matched
query could never read RESPONSIVE. B1 then gives that query both witnesses (1 row for the owner,
0 for the forger). B1 uses ONE asyncpg connection, not a pool: step_line only calls .fetchrow, which
both provide, and a pool's release runs asyncpg's own reset SQL, which is driver-internal and not
under test here (seed #23668; the general sqlguard rule for driver SQL is a4's call).

Exits 77 when the substrate (node + pg modules, a buildable fixture database) is absent.
"""
import ast
import asyncio
import importlib
import inspect
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
SERVER = Path(os.environ.get("CHANNEL_SERVER_SRC") or REPO / "channel" / "server.mjs")
COMMON = Path(os.environ.get("STEP_LINE_SRC") or REPO / "bridges" / "common.py")
PROBE_AGENT = "doorprobe"
fails = []


def skip(why):
    print(f"SKIP: {why}. Nothing was verified here.")
    sys.exit(77)


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


# ── B2 (static, needs no substrate) ─────────────────────────────────────────────────────────
sig_src = COMMON.read_text()
fn = next((n for n in ast.walk(ast.parse(sig_src))
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "step_line"), None)
kwonly = {a.arg for a in fn.args.kwonlyargs} if fn else set()
defaults = dict(zip([a.arg for a in fn.args.kwonlyargs], fn.args.kw_defaults)) if fn else {}
check("B2 step_line takes `agent` as a REQUIRED keyword (no default to fall back on)",
      "agent" in kwonly and defaults.get("agent") is None, f"kwonly={kwonly}")
missing = []
for f in sorted((REPO / "bridges").glob("*.py")):
    for n in ast.walk(ast.parse(f.read_text())):
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "step_line":
            if not any(k.arg == "agent" for k in n.keywords):
                missing.append(f"{f.name}:{n.lineno}")
check("B2 every step_line call in bridges/ passes agent=", not missing, str(missing))

# ── substrate ───────────────────────────────────────────────────────────────────────────────
try:
    import psycopg
    import asyncpg
except ModuleNotFoundError as e:
    skip(f"{e.name} not importable")


def dsn():
    env = REPO / ".env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("ASTRYX_DSN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def node_bin():
    spawn = REPO / "nucleus" / "spawn.sh"
    if spawn.exists():
        m = re.search(r"^NODE=(\S+)", spawn.read_text(), re.M)
        if m and Path(m.group(1)).is_file():
            return m.group(1)
    return shutil.which("node")


ADMIN_DSN, NODE = dsn(), node_bin()
if not ADMIN_DSN:
    skip("no ASTRYX_DSN")
if not NODE or not (REPO / "channel" / "node_modules" / "pg").is_dir():
    skip("node or channel/node_modules/pg absent")
sys.path.insert(0, str(REPO))
from nucleus.sqlguard.fixture import fixture_db  # noqa: E402 — the ONE applier

_fx = fixture_db()
try:
    fx = _fx.__enter__()
except Exception as e:  # noqa: BLE001 — no CREATEDB / DB down: cannot verify, don't fake
    skip(f"the fixture database couldn't be built ({type(e).__name__}: {e})")
# fixture_db() hands back a libpq key=value conninfo; node-pg (the staged ear) and asyncpg both
# take a URL. Same database, URL form, derived from the org's URL DSN; refuse rather than guess.
PROBE_DSN = re.sub(r"/[^/?]+(\?|$)", f"/{fx['dbname']}\\1", ADMIN_DSN, count=1)
if f"/{fx['dbname']}" not in PROBE_DSN:
    _fx.__exit__(None, None, None)
    skip("could not derive a URL DSN for the fixture database (unexpected ASTRYX_DSN shape)")
stage = Path(tempfile.mkdtemp(prefix="doorbell-"))
proc = None


def wait_for(pred, timeout, tick=0.2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(tick)
    return False


def stdout_text():
    return (stage / "stdout.log").read_text(errors="replace")


db = None
try:
    db = psycopg.connect(PROBE_DSN, autocommit=True, connect_timeout=5)
    db.execute("INSERT INTO subscriptions (watcher, target, filter) VALUES (%s,'zzx','all')",
               (PROBE_AGENT,))
    # The degenerate case made REAL: a subscription to '' and (below) a step whose agent is ''.
    # With both present, only the early return keeps an agent:"" payload from resolving.
    db.execute("INSERT INTO subscriptions (watcher, target, filter) VALUES (%s,'','all')",
               (PROBE_AGENT,))

    # ── the REAL server, staged outside the repo (ear-survival pattern) ──────────────────
    (stage / "channel").mkdir()
    shutil.copy2(SERVER, stage / "channel" / "server.mjs")
    (stage / "channel" / "node_modules").symlink_to(REPO / "channel" / "node_modules")
    (stage / ".env").write_text(f"ASTRYX_DSN={PROBE_DSN}\n")
    env = {**os.environ, "ASTRYX_AGENT": PROBE_AGENT, "ASTRYX_DSN": PROBE_DSN,
           "ASTRYX_SUBS_REFRESH_MS": "500"}
    with open(stage / "stdout.log", "wb") as out, open(stage / "stderr.log", "wb") as err:
        proc = subprocess.Popen([NODE, str(stage / "channel" / "server.mjs")], cwd=stage,
                                env=env, stdin=subprocess.PIPE, stdout=out, stderr=err)

    def step(agent, content, kind="tool"):
        return db.execute("INSERT INTO steps (agent, kind, content) VALUES (%s,%s,%s) "
                          "RETURNING id", (agent, kind, content)).fetchone()[0]

    # C1 positive control: the ear is up and the subscription loaded. Retry until the
    # server's LISTEN is live (a step before it is simply missed, never queued).
    ok_first = False
    for i in range(20):
        step("zzx", f"LEGIT-first-{i}")
        if wait_for(lambda: "LEGIT-first-" in stdout_text(), 1.5):
            ok_first = True
            break
    if not ok_first:
        skip("the staged ear never pushed a real subscribed step (no positive control), "
             "so no silence below could mean anything")
    check("C1 positive control: a real step of the subscribed agent is pushed", ok_first)

    secret_id = step("zzy", "SECRET-zzy-content")             # zzy: nobody subscribes
    empty_id = step("", "SECRET-empty-agent-content")         # agent '' IS a legal value
    db.execute("SELECT pg_notify('astryx_steps', %s)",
               (json.dumps({"id": secret_id, "agent": "zzx", "kind": "tool"}),))
    db.execute("SELECT pg_notify('astryx_steps', %s)",
               (json.dumps({"id": empty_id, "agent": "", "kind": "tool"}),))
    after_id = step("zzx", "LEGIT-after-forgery")
    arrived = wait_for(lambda: "LEGIT-after-forgery" in stdout_text(), 10)
    check("C1 a real step AFTER the forgery arrives (the ear listened throughout)", arrived)
    check("C1 a forged payload pushed NOTHING of the other agent's step",
          "SECRET-zzy-content" not in stdout_text(),
          "the other agent's step content was pushed under the zzx subscription")
    check("C2 an agent:\"\" payload pushed nothing, with a '' step AND a '' subscription present",
          "SECRET-empty-agent-content" not in stdout_text(),
          "the '' step was pushed: the empty-agent early return is gone")

    # ── B1: the bridges' step_line, the SUBJECT copy, on a real asyncpg pool ─────────────
    pkg = stage / "bridges"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    shutil.copy2(COMMON, pkg / "common.py")
    for sib in ("transcribe.py",):
        if (REPO / "bridges" / sib).exists():
            (pkg / sib).symlink_to(REPO / "bridges" / sib)
    sys.path.insert(0, str(stage))
    common = importlib.import_module("bridges.common")

    async def b1():
        pool = await asyncpg.connect(PROBE_DSN)      # a connection: no pool-reset SQL
        try:
            call = common.step_line
            kw = "agent" if "agent" in inspect.signature(call).parameters else None
            right = await call(pool, secret_id, "tool", **({kw: "zzy"} if kw else {}))
            wrong = await (call(pool, secret_id, "tool", **{kw: "zzx"}) if kw
                           else call(pool, secret_id, "tool", "zzx"))
            empty = await (call(pool, empty_id, "tool", **{kw: ""}) if kw
                           else call(pool, empty_id, "tool"))
            return right, wrong, empty
        finally:
            await pool.close()

    right, wrong, empty = asyncio.run(b1())
    check("B1 step_line: the step's own agent gets the line",
          right is not None and "SECRET-zzy-content" in right, repr(right))
    check("B1 step_line: ANOTHER agent's payload gets None", wrong is None, repr(wrong))
    check("B1 step_line: an empty agent never matches, even a step whose agent IS ''",
          empty is None, repr(empty))
finally:
    if proc and proc.poll() is None:
        proc.kill()
        proc.wait(timeout=10)
    try:
        if db is not None:
            db.close()
    finally:
        _fx.__exit__(None, None, None)            # the fixture drops its own DB WITH (FORCE)
        shutil.rmtree(stage, ignore_errors=True)

if fails:
    print(f"\nFAIL: {len(fails)} doorbell invariant(s) broken")
    sys.exit(1)
print("\nPASS: a steps doorbell resolves only to a step of the agent it names")
