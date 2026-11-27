#!/usr/bin/env python3
"""Oracle: the shipped idle usage reading (src/astryx/pulse/shipped_triggers/usage_idle.py) reads a login's limits
when no turn has, and says when no reading has landed (medic 12485).
  U1 STALE: a login whose fresh reading is older than FRESH_S is read once, and the result is a usage_polls row
  U2 FRESH: a fresh reading is not read again
  U3 FAILED: a failed attempt is a row too (its state), and is not retried for RETRY_S
  U4 BOUNDED: a hanging endpoint costs the evaluation at most its 4 s timeout, never the tick
  U5 PER LOGIN: two logins are two tagged rows, one per evaluation, the stalest first; a login with no value is skipped
  U6 SILENT: no reading in SILENT_S is said, re-nagged only after RENAG_S, re-armed by a landed one
  U7 SUBSTRATE: a usage_polls row reaches usage_readings with its credential (the real database)
  U8 SHIPPED: the shim imports the module; init.sh installs it (node, reconcile list, reinstall list); cog orgs get it
Exit 0 · 1."""
import importlib
import json
import shutil
import socket
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))
fails = []


def arm(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {str(detail)[:300]}"))
    if not ok:
        fails.append(name)


U = importlib.import_module("astryx.pulse.shipped_triggers.usage_idle")
R = U.usage_refresh
H = 3600.0
now = 1_000_000_000.0

# the pure choice
arm("U1 never read: the org's own login is due", U.due(now, {}, [None]) is None)
arm("U1 stale past FRESH_S: due", U.due(now, {None: (now - 2 * H, now - 2 * H)}, [None]) is None)
arm("U2 fresh within FRESH_S: none", U.due(now, {None: (now - 60, now - 60)}, [None]) is False)
arm("U3 a failure 5 min ago: not retried", U.due(now, {None: (now - 5 * H, now - 300)}, [None]) is False)
arm("U3 …retried past RETRY_S", U.due(now, {None: (now - 5 * H, now - U.RETRY_S - 1)}, [None]) is None)
arm("U5 the stalest due login wins", U.due(now, {None: (now - 2 * H, 0), "work": (now - 9 * H, 0)}, [None, "work"]) == "work")
arm("U5 a never-read login before a stale one", U.due(now, {None: (now - 9 * H, 0)}, [None, "work"]) == "work")


class Ctx:
    """the pulse's ctx over an in-memory usage_readings: SELECT groups it, INSERT appends"""
    def __init__(self, readings=()):
        self.state, self.rows, self.inserts = {}, list(readings), []

    def sql(self, q, params=()):
        if q.startswith("INSERT"):
            snap = params[1].obj
            self.inserts.append(snap)
            self.rows.append((snap.get("credential"), snap["state"], datetime.fromisoformat(snap["fetched_at"]).timestamp()))
            return []
        if "GROUP BY" not in q:
            return [{"last": max((at for _, _, at in self.rows), default=None)}]
        out = {}
        for c, st, at in self.rows:
            f, l = out.get(c, (None, None))
            out[c] = (max(f or 0, at) if st == "fresh" else f, max(l or 0, at))
        return [{"credential": c, "fresh": f, "last": l} for c, (f, l) in out.items()]


def run(ctx, logins=(), status=200, hang=0.0):
    """one evaluation with the endpoint answering `status` (or hanging `hang` s) and `logins` [(name, token)]"""
    def urlopen(req, timeout):
        if hang:
            time.sleep(min(hang, timeout))
            raise socket.timeout("timed out")
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "no", {}, None)

        class Resp:
            status = 200
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return json.dumps({"five_hour": {"utilization": 10}}).encode()
        return Resp()
    saved = (urllib.request.urlopen, U.vault.logins, R.CRED)
    urllib.request.urlopen, U.vault.logins = urlopen, (lambda estate, env=None: list(logins))
    cred = Path(tempfile.mkdtemp()) / "credentials.json"
    cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": "host-token"}}))
    R.CRED = cred
    try:
        return U.usage_idle(ctx)
    finally:
        urllib.request.urlopen, U.vault.logins, R.CRED = saved
        shutil.rmtree(cred.parent)


import urllib.error  # noqa: E402

t = time.time()
c = Ctx([(None, "fresh", t - 2 * H)])
run(c)
arm("U1 a stale reading: one snapshot, written as a fresh row", [(s.get("credential"), s["state"]) for s in c.inserts] == [(None, "fresh")], c.inserts)

c = Ctx([(None, "fresh", t - 60)])
run(c)
arm("U2 a fresh reading: nothing read", c.inserts == [], c.inserts)

c = Ctx([(None, "fresh", t - 2 * H)])
run(c, status=401)
arm("U3 a rejected login: a failed row (auth_rejected)", [s["state"] for s in c.inserts] == ["auth_rejected"], c.inserts)
run(c)
arm("U3 …and not retried in the next evaluation", len(c.inserts) == 1, c.inserts)

c = Ctx([(None, "fresh", t - 2 * H)])
t0 = time.monotonic()
run(c, hang=30)
took = time.monotonic() - t0
arm("U4 a hanging endpoint: back within its 4 s timeout, an unavailable row", took < 6 and [s["state"] for s in c.inserts] == ["unavailable"],
    f"{took:.1f}s {c.inserts}")

c = Ctx([(None, "fresh", t - 2 * H)])
two = [("work", "tok-w"), ("home", "tok-h"), ("empty", None)]
run(c, two)
run(c, two)
run(c, two)
got = [s.get("credential") for s in c.inserts]
arm("U5 two vault logins and the org's: three tagged rows over three evaluations, never the empty one",
    sorted(got, key=str) == sorted([None, "home", "work"], key=str), got)
run(c, two)
arm("U5 …then all fresh: nothing more", len(c.inserts) == 3, c.inserts)

c = Ctx([(None, "fresh", t - 60)])
c.rows = [(None, "fresh", t - 5 * H), (None, "unavailable", t - 4 * H)]
c.state = {}
out = run(type("X", (Ctx,), {"sql": lambda s, q, p=(): [] if q.startswith("INSERT") else Ctx.sql(s, q, p)})(c.rows))
arm("U6 nothing landed in SILENT_S (the write lost): said", bool(out) and "no usage reading has landed in 4 h" in out, out)
silent = type("X", (Ctx,), {"sql": lambda s, q, p=(): [] if q.startswith("INSERT") else Ctx.sql(s, q, p)})(c.rows)
silent.state = {"nagged": t - 60}
arm("U6 …re-nagged only after RENAG_S", run(silent) is None)
c = Ctx([(None, "fresh", t - 60)])
c.state = {"nagged": t - 60}
arm("U6 a landed reading re-arms it", run(c) is None and c.state["nagged"] == 0, c.state)

# U7 a real database, never the org's own (medic 12495): a fixture with schema.sql applied, dropped after
skipped = False
try:
    import psycopg
    from psycopg.types.json import Jsonb
    from astryx.security.sqlguard.fixture import FixtureUnavailable, fixture_db
    with fixture_db() as fx, psycopg.connect(fx["dsn"], autocommit=True) as conn:
        tag = "test-usage-idle"
        conn.execute("INSERT INTO usage_polls (state, snapshot) VALUES ('unavailable', %s)",
                     (Jsonb({"fetched_at": datetime.now(timezone.utc).isoformat(), "state": "unavailable", "credential": tag}),))
        r = conn.execute("SELECT src, state FROM usage_readings WHERE credential = %s", (tag,)).fetchall()
        cur = conn.execute("SELECT count(*) FROM current_usage").fetchone()[0]
        arm("U7 a usage_polls row reaches usage_readings tagged, never current_usage", r == [("polls", "unavailable")] and cur == 0, (r, cur))
except (ImportError, FixtureUnavailable) as e:
    skipped = True
    print(f"  NOT RUN  U7: no fixture database here ({type(e).__name__}: {str(e)[:120]})")

# U8 shipped
from astryx.pulse.shipped_triggers import shims  # noqa: E402
init = (REPO / "init.sh").read_text()
cog = (REPO / "devtools" / "cog_add_org.py").read_text()
arm("U8 the shim imports usage_idle", "from astryx.pulse.shipped_triggers.usage_idle import usage_idle" in shims.SHIMS["usage_idle"]
    and shims.NAMES["usage_idle"] == ("usage_idle",))
arm("U8 init.sh: node, reconcile list, reinstall list",
    "_act_usageidle()" in init and '"usageidle|interior"' in init and '"usage_idle|usageidle"' in init)
arm("U8 a cog org gets it", '"usage_idle")' in cog)

if fails:
    print(f"FAILED: {fails}")
    sys.exit(1)
print("ALL PASS" if not skipped else "PASS, U7 not run (77)")
sys.exit(77 if skipped else 0)
